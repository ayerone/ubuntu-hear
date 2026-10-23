#!/usr/bin/env python
"""Persistent background speech-to-text server for the toggle_hear.sh hotkey.

Loads OpenAI Whisper once, then sits on a Unix socket waiting for "toggle"
commands from hear_client.py. The first toggle starts a session: play a
random ready clip from sounds/ (synchronous so the mic never hears it; espeak-ng
says "go ahead" if there are no clips), then record from the
default microphone, cut the audio into utterances at pauses, transcribe each
with Whisper, and type the text at the active cursor via ydotool. The next
toggle ends the session after flushing whatever was being said.

Not meant to be run directly -- hear_client.py starts it automatically.

Settings live in config.toml next to this file (copy config.example.toml);
hear_config.py documents the keys and their defaults.
"""
import os
import queue
import random
import signal
import socket
import subprocess
import sys
import threading

import numpy as np

from hear_config import load_config

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "ubuntu-hear")
SOCKET_PATH = os.path.join(STATE_DIR, "daemon.sock")

CONFIG = load_config()
MODEL_NAME = CONFIG["model"]
PAUSE_SECONDS = CONFIG["pause_seconds"]
MIN_RMS = CONFIG["speech_threshold"]
IDLE_TIMEOUT_SECONDS = CONFIG["idle_timeout_seconds"]
MAX_SESSION_SECONDS = CONFIG["max_session_seconds"]

SAMPLE_RATE = 16000  # what Whisper wants
FRAME_SECONDS = 0.03
FRAME_BYTES = int(SAMPLE_RATE * FRAME_SECONDS) * 2  # s16 mono
PREROLL_FRAMES = 10  # ~0.3s kept from before speech starts so first words aren't clipped
MIN_SPEECH_FRAMES = 10  # ~0.3s of voiced audio before an utterance is worth transcribing
MAX_UTTERANCE_SECONDS = 25  # force a cut on someone who never pauses


def notify(msg, persistent=False, replace_id=None):
    """Show a toast and return its id. Persistent toasts stay up until a later notify() passes that id as replace_id.

    GNOME Shell ignores the x-canonical-private-synchronous hint, so replacement goes by id.
    """
    timing = ["-t", "0", "-u", "critical"] if persistent else ["-t", "1500", "-e"]
    replace = ["-r", str(replace_id)] if replace_id else []
    out = subprocess.run(["notify-send", "-p", *timing, *replace, "Hear", msg],
                         capture_output=True, text=True, check=False).stdout.strip()
    return int(out) if out.isdigit() else None


def close_notification(nid):
    """Close a toast by id over D-Bus."""
    if nid is None:
        return
    subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.Notifications",
                    "--object-path", "/org/freedesktop/Notifications",
                    "--method", "org.freedesktop.Notifications.CloseNotification", str(nid)],
                   capture_output=True, check=False)


def announce_ready():
    """Play a random canned clip from the sounds dir, or fall back to espeak-ng. Blocks until done."""
    sounds_dir = CONFIG["sounds_dir"]
    if not os.path.isabs(sounds_dir):
        sounds_dir = os.path.join(HERE, sounds_dir)
    try:
        clips = [f for f in os.listdir(sounds_dir) if f.lower().endswith(".wav")]
    except OSError:
        clips = []
    if clips:
        subprocess.run(["aplay", "-q", os.path.join(sounds_dir, random.choice(clips))], check=False)
    else:
        subprocess.run(["espeak-ng", CONFIG["go_ahead_text"]], check=False)


def type_text(text):
    subprocess.run(["ydotool", "type", "--key-delay", "2", "--", text], check=False)


class Transcriber:
    """Single worker so Whisper never runs concurrently with itself; typing order == speaking order."""

    def __init__(self, model):
        self.model = model
        self.q = queue.Queue()
        self.typed_any = False  # per session; controls the leading space between utterances
        threading.Thread(target=self._loop, daemon=True).start()

    def submit(self, samples):
        self.q.put(samples)

    def begin_session(self):
        self.typed_any = False

    def _loop(self):
        while True:
            pcm = self.q.get()
            audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
            result = self.model.transcribe(
                audio,
                language="en" if MODEL_NAME.endswith(".en") else None,
                fp16=False,
                condition_on_previous_text=False,
                temperature=0.0,
                no_speech_threshold=0.6,
            )
            segments = [s for s in result["segments"] if s["no_speech_prob"] < 0.6]
            text = " ".join(s["text"].strip() for s in segments).strip()
            if not text:
                continue
            type_text((" " if self.typed_any else "") + text)
            self.typed_any = True


class Session:
    """One listening run: record, segment on pauses, hand utterances to the Transcriber."""

    def __init__(self, transcriber):
        self.transcriber = transcriber
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    @property
    def active(self):
        return self.thread.is_alive()

    def request_stop(self):
        self.stop.set()

    def _run(self):
        announce_ready()
        if self.stop.is_set():
            return
        self.transcriber.begin_session()
        listening_id = notify("Listening", persistent=True)
        rec = subprocess.Popen(
            ["pw-record", "--rate", str(SAMPLE_RATE), "--channels", "1", "--format", "s16", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        # pw-record is blocked on read() of the pipe; this unblocks it when stop is requested.
        threading.Thread(target=self._kill_on_stop, args=(rec,), daemon=True).start()
        reason = ""
        try:
            reason = self._segment(rec.stdout)
        finally:
            rec.terminate()
            notify(f"Stopped ({reason})" if reason else "Stopped", replace_id=listening_id)

    def _kill_on_stop(self, rec):
        self.stop.wait()
        rec.terminate()

    def _segment(self, stream):
        """Cut the stream into utterances until it ends or a timeout hits. Returns why it ended ("" if stopped by hand)."""
        preroll = []
        utterance = []  # frames, including trailing silence
        voiced = 0
        silent_run = 0
        noise_floor = MIN_RMS / 3
        pause_frames = int(PAUSE_SECONDS / FRAME_SECONDS)
        max_frames = int(MAX_UTTERANCE_SECONDS / FRAME_SECONDS)
        idle_limit = int(IDLE_TIMEOUT_SECONDS / FRAME_SECONDS)  # 0 disables
        session_limit = int(MAX_SESSION_SECONDS / FRAME_SECONDS)  # 0 disables
        idle_run = 0  # consecutive non-speech frames
        total = 0
        reason = ""

        def flush():
            nonlocal utterance, voiced, silent_run
            if voiced >= MIN_SPEECH_FRAMES:
                self.transcriber.submit(b"".join(utterance))
            utterance, voiced, silent_run = [], 0, 0

        while True:
            frame = stream.read(FRAME_BYTES)
            if len(frame) < FRAME_BYTES:
                break  # recorder killed
            samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
            rms = float(np.sqrt(np.mean(samples ** 2)))
            is_speech = rms > max(MIN_RMS, noise_floor * 3)
            if not is_speech:
                noise_floor = 0.95 * noise_floor + 0.05 * rms
                idle_run += 1
            else:
                idle_run = 0
            total += 1
            if idle_limit and idle_run >= idle_limit:
                reason = "idle"
                break
            if session_limit and total >= session_limit:
                reason = "time limit"
                break

            if not utterance:
                if is_speech:
                    utterance = preroll + [frame]
                    voiced = 1
                    silent_run = 0
                else:
                    preroll.append(frame)
                    preroll = preroll[-PREROLL_FRAMES:]
                continue

            utterance.append(frame)
            if is_speech:
                voiced += 1
                silent_run = 0
            else:
                silent_run += 1
            if silent_run >= pause_frames or len(utterance) >= max_frames:
                flush()
                preroll = []
        flush()
        return reason


class Daemon:
    def __init__(self, transcriber):
        self.transcriber = transcriber
        self.session = None

    def toggle(self):
        if self.session is not None and self.session.active:
            self.session.request_stop()
            self.session = None
        else:
            self.session = Session(self.transcriber)


def cleanup_and_exit():
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)
    os._exit(0)


def bind_socket():
    os.makedirs(STATE_DIR, exist_ok=True)
    if os.path.exists(SOCKET_PATH):
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.connect(SOCKET_PATH)
            probe.close()
            sys.exit("hear_daemon.py is already running.")
        except OSError:
            os.remove(SOCKET_PATH)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(SOCKET_PATH)
    except OSError:
        sys.exit("hear_daemon.py: lost startup race, exiting.")
    sock.listen(8)
    return sock


def main():
    # Bind first so clients that arrive during the model load queue up in the backlog.
    sock = bind_socket()
    loading_id = notify("Loading STT...", persistent=True)

    def handle_term(signum, frame):
        sock.close()
        cleanup_and_exit()

    signal.signal(signal.SIGTERM, handle_term)
    signal.signal(signal.SIGINT, handle_term)

    try:
        import torch
        import whisper
        torch.set_num_threads(os.cpu_count() or 4)
        model = whisper.load_model(MODEL_NAME, device="cpu")
    finally:
        close_notification(loading_id)
    daemon = Daemon(Transcriber(model))

    while True:
        conn, _ = sock.accept()
        with conn:
            cmd = conn.recv(64).decode("utf-8", errors="replace").strip()
        if cmd == "toggle":
            daemon.toggle()
        elif cmd == "kill":
            if daemon.session is not None:
                daemon.session.request_stop()
            cleanup_and_exit()


if __name__ == "__main__":
    main()

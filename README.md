# ubuntu-hear

Local speech-to-text for Ubuntu. Transcribe from your mic to the cursor in any app, launched by a keyboard shortcut. Runs on CPU.

Check out the dual to this project (text-to-speech) [ubuntu-say](https://github.com/ayerone/ubuntu-say).

## Details

Uses [OpenAI Whisper](https://github.com/openai/whisper) and PyTorch.

The first Hotkey (keyboard shortcut) press after login starts a background daemon (python process) that loads the model. Subsequent presses get a warm start (daemon already running). Each press toggles a session:

- **Start:** a short ready clip plays (finished before the microphone opens), then it listens. Each phrase, ended by a pause, is transcribed and typed at the cursor.
- **Stop:** the phrase in progress is still transcribed and typed, then the microphone closes.

## Tested on

Ubuntu 24.04, GNOME on Wayland, Mini PC (Intel N150, 4 cores, no GPU), PipeWire. Other setups may need changes. The typing step uses `ydotool` because `wtype` does not work on GNOME.

## Install

1. System packages:

   ```bash
   sudo apt install pipewire-bin alsa-utils espeak-ng ydotool libnotify-bin
   ```

2. Python environment (3.11 or newer) with CPU-only PyTorch. Run these from the project folder:

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
   .venv/bin/pip install -r requirements.txt
   .venv/bin/pip uninstall -y triton
   ```

   PyTorch comes from the CPU wheel index so pip does not pull the 2+ GB CUDA build. `openai-whisper` pulls in `triton` (about 900 MB of GPU-only code that CPU inference never uses), so the last command removes it. The resulting venv is about 1 GB. The daemon looks for `.venv/bin/python` in the project folder, so keep the venv there.

   Optionally download the Whisper model now so the first hotkey press does not wait on it (use your `model` setting if you changed it):

   ```bash
   .venv/bin/python -c "import whisper; whisper.load_model('base.en', device='cpu')"
   ```

3. Typing setup. `ydotool` writes through `/dev/uinput`, so it needs a running `ydotoold` and access to that device:

   ```bash
   sudo usermod -aG input "$USER"      # then log out and back in
   mkdir -p ~/.config/systemd/user
   cat > ~/.config/systemd/user/ydotool.service <<'UNIT'
   [Unit]
   Description=ydotool daemon

   [Service]
   ExecStart=/usr/bin/ydotoold
   Restart=always

   [Install]
   WantedBy=default.target
   UNIT
   systemctl --user enable --now ydotool
   ```

   If `/dev/uinput` is not group-writable by `input` on your system, add a udev rule such as `KERNEL=="uinput", GROUP="input", MODE="0660"`.

4. Bind a global keyboard shortcut (GNOME Settings, Keyboard, Custom Shortcuts) to the absolute path of `toggle_hear.sh` in this checkout. I chose ctrl-alt-v, which is reminiscent of ctrl-v.

## Usage

On a cold start (the first press after login, or after a kill) a notification reading "Loading STT..." stays up until Whisper has loaded. Press the shortcut, wait for the ready clip to finish, and talk. Press it again to stop. A desktop notification stays on screen with "Listening" until you stop, then it changes to "Stopped" and clears itself. A session also stops by itself after the idle or maximum time in the settings below, and the notification then reads "Stopped (idle)" or "Stopped (time limit)".

`toggle_hear.sh kill` shuts the background daemon down (it restarts on the next press). Run it by absolute path from anywhere, or symlink the script onto your PATH, for example `ln -s "$PWD/toggle_hear.sh" ~/.local/bin/hear`, then use `hear kill`. Daemon output goes to `~/.cache/ubuntu-hear/daemon.log`.

## Configuration

Copy `config.example.toml` to `config.toml` and edit it. `config.toml` is gitignored, and every setting is optional.

| Setting | Default | Meaning |
| --- | --- | --- |
| `model` | `base.en` | Whisper model name. `base.en` transcribed 6 s of speech in about 1.6 s on the N150. `small.en` is more accurate and took about 5 s. |
| `pause_seconds` | `0.8` | Seconds of silence that end a phrase. |
| `speech_threshold` | `250` | Minimum RMS loudness (int16 scale) counted as speech. Raise it if background noise produces phantom text. |
| `sounds_dir` | `sounds` | Folder of `.wav` clips for the start cue (see below). |
| `go_ahead_text` | `go ahead` | What espeak-ng says when `sounds_dir` has no clips. |
| `idle_timeout_seconds` | `10` | Seconds without speech before the session stops itself. `0` turns it off. |
| `max_session_seconds` | `60` | Total session length before it stops itself, whatever the sound level. `0` turns it off. |

The daemon reads the file at startup, so run `toggle_hear.sh kill` after editing it.

## Start clips

Each session starts by playing one random `.wav` file from `sounds/`. The clips are not part of the repo (they are gitignored), so make your own: any short mono or stereo WAV works (keep each to a single short phrase so you are not tempted to talk over it), for example generated with a local text-to-speech tool or recorded yourself. With an empty `sounds/` folder, espeak-ng says the `go_ahead_text` setting instead.

## How it works

- `toggle_hear.sh` runs `hear_client.py`, which sends `toggle` over a Unix socket (`~/.cache/ubuntu-hear/daemon.sock`) and starts the daemon first if needed.
- `hear_daemon.py` plays the start cue, records 16 kHz mono audio from the default microphone with `pw-record`, cuts it into phrases with a simple adaptive loudness detector, and transcribes each phrase on a single worker thread so typed output keeps speaking order.
- Typing is `ydotool type`, so text goes to whichever window has focus when the phrase finishes.

## Limitations

- Text appears after you pause at the end of each phrase.
- Phrase detection uses a simple adaptive loudness threshold, so steady loud noise can be mistaken for speech.
- Stopping flushes the last phrase right after you press the shortcut. Before typing, the daemon waits (up to 2 seconds) for any held Ctrl, Alt, Shift or Super key to be released, by reading key state from `/dev/input/event*`. This keeps a Ctrl+Alt shortcut from turning the text into key combos, which could freeze a terminal (Ctrl+S pauses terminal output). If that state cannot be read, typing proceeds without the wait, and a shortcut bound to a single key with no modifiers, such as `Pause` or `Scroll Lock`, avoids the problem entirely.

## License

MIT. See `LICENSE`.

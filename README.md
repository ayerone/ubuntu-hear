# ubuntu-hear

Hotkey speech-to-text for Ubuntu. Press a shortcut, talk, and your words are typed at the cursor in whatever window has focus. Transcription runs locally with [OpenAI Whisper](https://github.com/openai/whisper), on CPU only, with no network use after the model download.

Each press of the shortcut toggles a session:

- **Start:** a short ready clip plays (finished before the microphone opens), then it listens. Each phrase, ended by a pause, is transcribed and typed at the cursor.
- **Stop:** the phrase in progress is still transcribed and typed, then the microphone closes.

The first press after login starts a small background daemon that loads Whisper. The daemon stays resident, so every later press is a warm start.

## Tested on

Ubuntu 24.04, GNOME on Wayland, Intel N150 (4 cores, no GPU), PipeWire. Other setups may need changes. The typing step uses `ydotool` because `wtype` does not work on GNOME.

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

4. Bind a global keyboard shortcut (GNOME Settings, Keyboard, Custom Shortcuts) to the absolute path of `toggle_hear.sh` in this checkout.

## Usage

Press the shortcut, wait for the ready clip to finish, and talk. Press it again to stop. A desktop notification shows "Listening" and "Stopped".

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
- Stopping flushes the last phrase right after you press the shortcut. If the shortcut uses modifiers such as Ctrl+Alt and they are still held when the text is typed, the letters arrive as key combos, and a terminal can freeze briefly or show stray characters (Ctrl+S pauses terminal output). Release the keys before the text lands, or bind the shortcut to a single key with no modifiers, such as `Pause` or `Scroll Lock`.

## License

MIT. See `LICENSE`.

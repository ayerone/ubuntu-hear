#!/usr/bin/env bash
# Toggle speech-to-text typing. Bind this to a global keyboard shortcut.
#
# First press: plays a short ready clip, then listens to the microphone, transcribes
# each phrase with a local Whisper model, and types it at the active cursor.
# Press again to stop (the phrase in progress is still transcribed and typed).
#
# hear_client.py starts hear_daemon.py on first use and reuses it on every
# press after that, so only the first press of a login session is slow (Whisper
# loads first).
#
# Extra commands: `toggle_hear.sh kill` shuts the background daemon down.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/hear_client.py" "${1:-toggle}" &
disown

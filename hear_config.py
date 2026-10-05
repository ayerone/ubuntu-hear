"""Settings for ubuntu-hear, read from config.toml next to this file.

Copy config.example.toml to config.toml and edit. Every key is optional; the
defaults below apply to anything left out. config.toml is read when the daemon
starts, so run `toggle_hear.sh kill` after editing it.
"""
import os
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.toml")

DEFAULTS = {
    "model": "base.en",           # Whisper model name
    "pause_seconds": 0.8,         # silence that ends a phrase
    "speech_threshold": 250,      # minimum RMS (int16 scale) counted as speech
    "sounds_dir": "sounds",       # .wav clips; one is played at random before listening
    "go_ahead_text": "go ahead",  # espeak-ng fallback when sounds_dir has no clips
}


def load_config():
    config = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "rb") as f:
            user = tomllib.load(f)
        unknown = set(user) - set(DEFAULTS)
        if unknown:
            raise SystemExit(f"{CONFIG_PATH}: unknown setting(s): {', '.join(sorted(unknown))}")
        config.update(user)
    return config

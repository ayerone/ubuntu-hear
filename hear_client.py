#!/usr/bin/env python
"""Send a command ("toggle" by default) to hear_daemon.py, starting it first if needed.

Used by toggle_hear.sh. If the daemon is up this is a near-instant socket
send. If not, it starts the daemon in the background and sends the toggle once
the daemon is ready (a few seconds while Whisper loads), so the first press just
plays the usual start clip a little late.
"""
import os
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "ubuntu-hear")
SOCKET_PATH = os.path.join(STATE_DIR, "daemon.sock")


def send(cmd):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(SOCKET_PATH)
        sock.sendall(cmd.encode("utf-8"))


def start_daemon():
    subprocess.Popen(
        [os.path.join(HERE, ".venv", "bin", "python"), os.path.join(HERE, "hear_daemon.py")],
        stdout=open(os.path.join(STATE_DIR, "daemon.log"), "ab"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def wait_for_socket(timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(SOCKET_PATH):
            return True
        time.sleep(0.1)
    return False


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "toggle"
    try:
        send(cmd)
        return
    except (ConnectionRefusedError, FileNotFoundError):
        pass

    if cmd == "kill":
        return
    os.makedirs(STATE_DIR, exist_ok=True)
    start_daemon()
    if not wait_for_socket():
        sys.exit("hear_daemon.py did not start in time")
    for _ in range(50):  # the socket file can appear a moment before it accepts
        try:
            send(cmd)
            break
        except (ConnectionRefusedError, FileNotFoundError):
            time.sleep(0.1)


if __name__ == "__main__":
    main()

#!/bin/bash
set -e

# Start VNC only if DEBUG=true
if [ "${DEBUG}" = "true" ]; then
    mkdir -p ~/.vnc
    echo "$VNC_PASSWORD" | vncpasswd -f > ~/.vnc/passwd
    chmod 600 ~/.vnc/passwd

    Xvnc :99 -geometry 1920x1080 -depth 24 -rfbport 5900 -SecurityTypes VncAuth -PasswordFile ~/.vnc/passwd \
        -AlwaysShared -AcceptKeyEvents -AcceptPointerEvents -SendCutText -AcceptCutText &

    export DISPLAY=:99
    sleep 2

    autocutsel -s PRIMARY -fork &
    autocutsel -s CLIPBOARD -fork &

    echo "[entrypoint] DEBUG mode: VNC started on :5900"
else
    # Headless mode — no VNC
    export DISPLAY=
    echo "[entrypoint] Production mode: VNC disabled"
fi

exec python run.py

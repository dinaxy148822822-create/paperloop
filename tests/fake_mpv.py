#!/usr/bin/env python3
"""Stand-in for mpv in tests: records its argv and every IPC command it receives."""
import json, os, socket, sys

ipc = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--input-ipc-server=")), None)
log = os.environ["FAKE_MPV_LOG"]
with open(log, "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:]}) + "\n")
if not ipc:
    sys.exit(0)
try:
    os.unlink(ipc)
except OSError:
    pass
srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
srv.bind(ipc)
srv.listen(5)
while True:
    conn, _ = srv.accept()
    data = conn.recv(65536).decode()
    with open(log, "a") as f:
        for line in data.splitlines():
            f.write(line + "\n")
    conn.close()

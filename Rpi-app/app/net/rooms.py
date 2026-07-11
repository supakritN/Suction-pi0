"""LAN rooms over stdlib HTTP (no extra dependencies).

The host Pi runs an in-process HTTP server; clients join by the host's LAN
IP. The shared state is the attendee list (name / time / score). A client
finishing a run sends its raw metrics; the host scores them with the host's
authoritative rubric and everyone polls the updated list.

Endpoints (JSON):
  GET  /attendees            -> {host, ip, attendees:[...]}
  POST /join   {name}        -> snapshot
  POST /result {name,metrics}-> snapshot
"""
from __future__ import annotations

import json
import socket
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .. import config as cfg_store
from .. import results_log
from ..models import Attendee, SessionMetrics
from ..scoring import score_session

ROOM_PORT = 8765


def get_lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class _Handler(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/attendees":
            self._send(self.server.snapshot())
        else:
            self._send({"error": "not_found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._send({"error": "bad_json"}, 400)
        if self.path == "/join":
            self.server.join(str(data.get("name", "guest")))
            self._send(self.server.snapshot())
        elif self.path == "/result":
            self.server.record(str(data.get("name", "guest")), data.get("metrics", {}))
            self._send(self.server.snapshot())
        else:
            self._send({"error": "not_found"}, 404)

    def log_message(self, *args):
        pass  # keep the console quiet


class RoomServer(ThreadingHTTPServer):
    def __init__(self, host_name: str):
        super().__init__(("0.0.0.0", ROOM_PORT), _Handler)
        self.host_name = host_name
        self.attendees: dict = {}
        self.lock = threading.Lock()
        self.ip = get_lan_ip()
        self.join(host_name)

    def start(self):
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def join(self, name: str):
        with self.lock:
            self.attendees.setdefault(name, Attendee(username=name))

    def record(self, name: str, metrics_dict: dict):
        metrics = SessionMetrics.from_dict(metrics_dict)
        result = score_session(metrics, cfg_store.load_config())
        with self.lock:
            attendee = self.attendees.setdefault(name, Attendee(username=name))
            attendee.time_sec = round(metrics.duration_sec, 2)
            attendee.score = result.total
            attendee.level = result.level
            attendee.finished = True
        # host keeps a CSV of every attendee result it receives
        try:
            results_log.log_result(name, "room", self.host_name, metrics, result,
                                   path=results_log.ROOM_RESULTS_PATH)
        except Exception:
            pass

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "host": self.host_name,
                "ip": self.ip,
                "attendees": [a.to_dict() for a in self.attendees.values()],
            }


class RoomClient:
    def __init__(self, host_ip: str):
        self.base = f"http://{host_ip}:{ROOM_PORT}"

    def _post(self, path, obj):
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(obj).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=4) as r:
            return json.loads(r.read())

    def _get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=4) as r:
            return json.loads(r.read())

    def join(self, name: str):
        return self._post("/join", {"name": name})

    def send_result(self, name: str, metrics_dict: dict):
        return self._post("/result", {"name": name, "metrics": metrics_dict})

    def get_attendees(self):
        return self._get("/attendees")

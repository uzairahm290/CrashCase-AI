"""BentoDetector client against a fake HTTP server shaped like the BentoML service."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from conftest import make_image

from crashcase.config import Settings
from crashcase.pipeline.detector import build_detector


class FakeBento(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers["content-length"]))
        if self.path == "/version":
            body, ctype = b"stub-0", "text/plain"
        else:
            det = {
                "damage_type": "dent",
                "part": "door",
                "confidence": 0.8,
                "bbox": [1, 2, 3, 4],
                "severity": 0.3,
            }
            body, ctype = json.dumps([det]).encode(), "application/json"
        self.send_response(200)
        self.send_header("content-type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_bento_client_round_trip():
    server = HTTPServer(("127.0.0.1", 0), FakeBento)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        d = build_detector(Settings(detector_backend="bento", bento_url=url))
        assert d.version == "bento:stub-0"
        [det] = d.detect(make_image(1))
        assert det.damage_type == "dent" and det.severity == 0.3
    finally:
        server.shutdown()

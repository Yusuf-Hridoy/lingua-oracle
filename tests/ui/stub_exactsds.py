"""A stand-in ExactSDS, for the browser suite only.

The picker is a question the server asks when several products could be the
sheet, and answering it is a round trip: a POST back to the same report, a
re-run against the application, a page with both halves filled. None of that
can be driven without an application answering, and the real one has no
business being in a test suite - it is slow, it is somebody's live data, and
it is not ours to depend on.

So this serves the three endpoints the client uses, out of a dict. It is not a
mock of the client: the server under test makes real HTTP requests to it.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

PRODUCT = "Synthetic Test Solvent SDS-TEST-001"

#: Two products either of which could be the uploaded sheet, with different
#: compositions, so the page after the choice can only have come from the one
#: that was chosen.
LIBRARY = [
    {"primary_product_id": 4101, "product_name": f"{PRODUCT} A",
     "regulations": [{"regulation": "eu_clp"}], "updated_at": "2026-01-01"},
    {"primary_product_id": 4102, "product_name": f"{PRODUCT} B",
     "regulations": [{"regulation": "eu_clp"}], "updated_at": "2026-02-01"},
]

INGREDIENTS = {
    4101: [{"components": [
        {"cas_no": "67-64-1", "chemical_name": "<a>",
         "chemical_hazard_code": "H225,H319,H336", "concentration": "60"}]}],
    4102: [{"components": [
        {"cas_no": "7664-93-9", "chemical_name": "<b>",
         "chemical_hazard_code": "H314", "concentration": "40"}]}],
}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # noqa: D102 - quiet in the test output
        pass

    def _send(self, body) -> None:
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's name
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path.endswith("/users/login"):
            return self._send({"access_token": "stub"})
        self.send_error(404)
        return None

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        parts = url.path.strip("/").split("/")
        if parts[-1] == "library":
            query = (parse_qs(url.query).get("q") or [""])[0].casefold()
            rows = [r for r in LIBRARY
                    if query in r["product_name"].casefold()]
            return self._send({"count": len(rows), "results": rows})
        if parts[-2:-1] == ["products"] and parts[-1].isdigit():
            product_id = int(parts[-1])
            name = next((r["product_name"] for r in LIBRARY
                         if r["primary_product_id"] == product_id), None)
            return self._send({"product_name": name})
        if parts[-1] == "ingredients" and parts[-2].isdigit():
            return self._send(INGREDIENTS.get(int(parts[-2]), []))
        if parts[-2:-1] == ["compound"]:
            return self._send({"source": "stub"})
        self.send_error(404)
        return None


def start() -> tuple[str, HTTPServer]:
    """Serve on a free port in a background thread; return its base URL."""
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_port}", server

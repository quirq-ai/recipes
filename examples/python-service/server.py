"""A tiny HTTP service: GET /health and GET /greet?name=... on the port in $PORT."""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from greet import greeting


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/health":
            body = {"status": "ok"}
        elif url.path == "/greet":
            body = {"message": greeting(parse_qs(url.query).get("name", [""])[0])}
        else:
            self.send_error(404)
            return
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("PORT", "8000"))), Handler).serve_forever()

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json

from api.fuel import get_payload


class LocalDashboardHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/fuel"):
            try:
                payload = get_payload()
                status = 200
            except Exception as error:
                payload = {"error": str(error), "rows": []}
                status = 502

            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/":
            self.path = "/index.html"

        super().do_GET()


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8000), LocalDashboardHandler)
    print("Local dashboard: http://127.0.0.1:8000")
    server.serve_forever()

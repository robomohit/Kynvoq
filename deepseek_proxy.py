import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import Request, urlopen

ZEN_URL = "https://opencode.ai/zen/v1/chat/completions"
ZEN_MODEL = "deepseek-v4-flash-free"


class Proxy(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/v1/models":
            stub = json.dumps({"object":"list","data":[{"id":"deepseek-v4-flash-free","object":"model"}]})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(stub.encode())
            return
        self.send_error(404)

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        clen = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(clen)) if clen else {}
        body["model"] = ZEN_MODEL
        req = Request(
            ZEN_URL,
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "opencode-proxy/1.0",
            },
            method="POST",
        )
        try:
            resp = urlopen(req, timeout=60)
            self.send_response(resp.status)
            for k, v in resp.getheaders():
                if k.lower() in ("content-type",):
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(resp.read())
        except Exception as e:
            self.send_error(502, str(e))


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8080), Proxy).serve_forever()

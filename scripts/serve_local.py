"""Run the hosted demo locally (same routes as the Lambda), with in-memory storage and local uploads.

  python scripts/serve_local.py --port 8765                 # rules only, no AWS call, inspections inline
  python scripts/serve_local.py --jobs                      # same, but like AWS: {job_id} + polling (background thread)
  AWS_PROFILE=<profile> python scripts/serve_local.py --bedrock   # Nova 2 Lite on Bedrock as the planner
"""
import argparse
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from crackwatch.api import App, LocalBlobs  # noqa: E402
from crackwatch.store import MemStore  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--bedrock", action="store_true")
    ap.add_argument("--jobs", action="store_true", help="answer POST /api/inspect with a job id, run it in a thread")
    ap.add_argument("--uploads", default=os.path.join(os.path.dirname(__file__), "..", "data", "local_uploads"))
    a = ap.parse_args()
    factory = None
    if a.bedrock:
        import boto3
        from crackwatch.agent import NovaConversePlanner
        client = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        factory = lambda allow: NovaConversePlanner(client=client, allow_call=allow)  # noqa: E731
    app = App(MemStore(), LocalBlobs(a.uploads), factory, log=lambda s: print(s[:300], flush=True))
    if a.jobs:
        import threading
        app.dispatcher = lambda job: threading.Thread(target=app.run_job, args=(job,), daemon=True).start()

    class H(BaseHTTPRequestHandler):
        def _go(self, method):
            u = urlsplit(self.path)
            n = int(self.headers.get("content-length") or 0)
            body = self.rfile.read(n) if n else b""
            r = app.handle(method, u.path, dict(self.headers), body, dict(parse_qsl(u.query)), self.client_address[0])
            self.send_response(r.status)
            for k, v in r.headers.items():
                self.send_header(k, v)
            self.send_header("content-length", str(len(r.body)))
            self.end_headers()
            self.wfile.write(r.body)

        def do_GET(self):
            self._go("GET")

        def do_POST(self):
            self._go("POST")

        def log_message(self, *args):
            pass

    print(f"CrackWatch local demo on http://127.0.0.1:{a.port}  (planner: {'Nova 2 Lite' if a.bedrock else 'rules'})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()


if __name__ == "__main__":
    main()

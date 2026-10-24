"""HTTP routes of the hosted demo, independent of the transport (API Gateway + Lambda, or a local server).

GET  /                         single-page app (web/index.html)
GET  /app.js /app.css /ds/*    static assets
GET  /samples/<file>           synthetic sample photos + their ground truth (samples.json)
GET  /card.pdf                 printable A6 ChArUco card (print at 100 %)
GET  /api/health
POST /api/upload-url           presigned S3 POST for one photo (private bucket, deleted after 1 day)
POST /api/inspect              measure + agent loop -> decision, trace, overlay. With a dispatcher (AWS: the Lambda
                               invokes itself asynchronously) it answers {job_id} at once, the work runs in the
                               background (up to 120 s, never against API Gateway's 29 s), and the result is read with
GET  /api/job/<id>             {status: "pending"} until done, then the inspection result (or its error, same codes)
POST /api/tickets/<id>/decision  human approval / rejection of a proposed ticket
POST /api/visit                anonymous visit event (see visits.py)
GET  /internal?k=...           owner-only: marks this browser as internal (not counted)

Cost guards (all configurable by environment): global inspections/day, inspections/day per anonymous
visitor, LLM calls/day (then the deterministic rules decide alone), photo size <= 15 MB.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import secrets
import threading
import time
import traceback

from . import visits

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
WEB_DIR = os.environ.get("CW_WEB_DIR", os.path.join(ROOT, "web"))
PRINT_DIR = os.environ.get("CW_PRINT_DIR", os.path.join(ROOT, "print"))
SAMPLES = ("blurry", "far", "close", "visit2", "real")
MAX_UPLOAD = 15 * 1024 * 1024
KEY_RE = re.compile(r"^uploads/\d{4}-\d{2}-\d{2}/[0-9a-f]{32}\.jpg$")


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


LIMITS = {"inspections_per_day": _env_int("CW_MAX_INSPECTIONS_PER_DAY", 1500),
          "inspections_per_visitor_day": _env_int("CW_MAX_INSPECTIONS_PER_VISITOR_DAY", 80),
          "llm_calls_per_day": _env_int("CW_MAX_LLM_CALLS_PER_DAY", 250)}

STATIC = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/app.css": ("app.css", "text/css; charset=utf-8"), "/ds/tokens.css": ("ds/tokens.css", "text/css; charset=utf-8"),
          "/ds/components.css": ("ds/components.css", "text/css; charset=utf-8"),
          "/ds/motion.js": ("ds/motion.js", "text/javascript; charset=utf-8"),
          "/i18n.js": ("i18n.js", "text/javascript; charset=utf-8"),
          "/camera.js": ("camera.js", "text/javascript; charset=utf-8"),
          "/vendor/jspdf.umd.min.js": ("vendor/jspdf.umd.min.js", "text/javascript; charset=utf-8"),
          "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
          "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"),
          "/favicon.svg": ("favicon.svg", "image/svg+xml"),
          # guided camera (camera-guidee): lazy-loaded when the camera opens
          "/camera.js": ("camera.js", "text/javascript; charset=utf-8"), "/camera.css": ("camera.css", "text/css; charset=utf-8"),
          "/camera-worker.js": ("camera-worker.js", "text/javascript; charset=utf-8"),
          "/camera-detect.js": ("camera-detect.js", "text/javascript; charset=utf-8")}
# OpenCV.js 4.12.0 (pinned, Apache-2.0), stored pre-gzipped: 10.9 MB -> 3.5 MB, under the Lambda 6 MB response cap
OPENCV_JS = ("/vendor/opencv-4.12.0.js", "vendor/opencv-4.12.0.js.gz")

CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
       "connect-src 'self' https://*.amazonaws.com; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
# The camera worker runs OpenCV.js (WebAssembly + Emscripten embind, which needs eval): allowed in the worker only.
WORKER_CSP = "default-src 'self'; script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval'; connect-src 'self' data:; base-uri 'none'"


class Response:
    def __init__(self, status=200, body=b"", ctype="application/json", headers=None):
        self.status, self.body, self.headers = status, body, {"content-type": ctype, **(headers or {})}


def jresp(obj, status=200, headers=None):
    return Response(status, json.dumps(obj, separators=(",", ":"), default=str).encode(), "application/json",
                    dict({"cache-control": "no-store"}, **(headers or {})))


def err(code, status=400, detail=""):
    return jresp({"error": code, "detail": detail}, status)


def _day():
    return time.strftime("%Y-%m-%d", time.gmtime())


JOB_RE = re.compile(r"^[0-9a-f]{24}$")
JOB_STALE_S = 150          # a job still running after this (worker timeout 120 s) has died: reported as an error


class App:
    def __init__(self, store, blobs, planner_factory=None, log=print, dispatcher=None):
        """`dispatcher(job_id)`: start the background run of a stored job (AWS: async self-invocation). None =
        run inspections inline in the request (local server, tests)."""
        self.store, self.blobs, self.planner_factory, self.log = store, blobs, planner_factory, log
        self.dispatcher = dispatcher
        self._tl = threading.local()       # per-thread: inside a background job run (local --jobs server)

    # ------------------------------------------------------------------ guards
    def _count(self, name, limit, visitor=None):
        if getattr(self._tl, "in_job", False) and name.startswith("inspections"):
            return True                # a background job was already counted when it was accepted
        sk = f"{name}#{visitor}" if visitor else name
        n = self.store.incr(f"USAGE#{_day()}", sk, 1, ttl_days=40)
        return n <= limit

    def llm_allowed(self):
        return self._count("llm_calls", LIMITS["llm_calls_per_day"])

    # ------------------------------------------------------------------ routing
    def handle(self, method, path, headers, body: bytes, query: dict, ip: str) -> Response:
        try:
            return self._route(method, path, {k.lower(): v for k, v in (headers or {}).items()}, body or b"", query or {}, ip)
        except Exception as e:   # never leak a stack trace to the client
            self.log(json.dumps({"event": "error", "path": path, "error": type(e).__name__, "detail": str(e)[:300],
                                 "trace": traceback.format_exc()[-1200:]}))
            return err("internal_error", 500, type(e).__name__)

    def _route(self, method, path, h, body, query, ip):
        if method == "GET" and path in STATIC:
            name, ctype = STATIC[path]
            extra = {"content-security-policy": WORKER_CSP if path == "/camera-worker.js" else CSP,
                     "x-content-type-options": "nosniff", "referrer-policy": "strict-origin-when-cross-origin"}
            return self._file(os.path.join(WEB_DIR, name), ctype, "no-cache" if path == "/" else "public, max-age=300", extra)
        if method == "GET" and path == OPENCV_JS[0]:
            return self._file(os.path.join(WEB_DIR, OPENCV_JS[1]), "application/javascript", "public, max-age=31536000, immutable",
                              {"content-encoding": "gzip", "x-content-type-options": "nosniff", "vary": "accept-encoding"})
        if method == "GET" and path.startswith("/samples/"):
            name = path.rsplit("/", 1)[-1]
            if not re.fullmatch(r"(blurry|far|close|visit2|real)\.jpg|samples\.json", name):
                return err("not_found", 404)
            return self._file(os.path.join(WEB_DIR, "samples", name), mimetypes.guess_type(name)[0] or "application/octet-stream",
                              "public, max-age=3600")
        if method == "GET" and path.startswith("/fonts/"):
            name = path.rsplit("/", 1)[-1]
            if not re.fullmatch(r"onest-latin-[4-8]00-normal\.woff2", name):
                return err("not_found", 404)
            return self._file(os.path.join(WEB_DIR, "fonts", name), "font/woff2", "public, max-age=86400")
        if method == "GET" and path in ("/card.pdf", "/card-a5.pdf"):
            f = "card_A6-5x7-15mm.pdf" if path == "/card.pdf" else "card_A5-7x10-17mm.pdf"
            return self._file(os.path.join(PRINT_DIR, f), "application/pdf", "public, max-age=3600",
                              {"content-disposition": f'inline; filename="crackwatch-{f}"'})
        if method == "GET" and path == "/api/health":
            import platform
            where = "AWS Lambda" if os.environ.get("AWS_LAMBDA_FUNCTION_NAME") else "local"
            return jresp({"ok": True, "service": "crackwatch", "opencv": self._cv_version(),
                          "runtime": f"{where} · {platform.machine()}", "limits": LIMITS})
        if method == "GET" and path == "/internal":
            if secrets.compare_digest(str(query.get("k", "")), visits.internal_key()):
                return Response(302, b"", "text/plain", {"location": "/", "set-cookie":
                                f"cw_internal={visits.internal_key()}; Path=/; Max-Age=31536000; HttpOnly; Secure; SameSite=Lax"})
            return err("not_found", 404)
        m = re.fullmatch(r"/api/job/([0-9a-f]+)", path) if method == "GET" else None
        if m:
            return self._job(m.group(1))
        if method != "POST":
            return err("not_found", 404)
        try:
            data = json.loads(body.decode() or "{}") if path != "/api/local-upload" else {}
        except (ValueError, UnicodeDecodeError):
            return err("bad_json")
        if path == "/api/visit":
            ok = visits.log_visit(self.store, h, ip, data if isinstance(data, dict) else {})
            return jresp({"logged": ok})
        if path == "/api/upload-url":
            key = f"uploads/{_day()}/{secrets.token_hex(16)}.jpg"
            return jresp({"key": key, **self.blobs.presign_post(key, MAX_UPLOAD)})
        if path == "/api/local-upload" and hasattr(self.blobs, "accept_upload"):
            return jresp(self.blobs.accept_upload(h.get("content-type", ""), body))
        if path == "/api/inspect":
            return self._enqueue(data, h, ip) if self.dispatcher else self._inspect(data, h, ip)
        m = re.fullmatch(r"/api/tickets/([0-9a-f]{10})/decision", path)
        if m:
            return self._decide(m.group(1), data, h, ip)
        return err("not_found", 404)

    # ------------------------------------------------------------------ handlers
    def _file(self, path, ctype, cache, extra=None):
        try:
            with open(path, "rb") as f:
                return Response(200, f.read(), ctype, dict({"cache-control": cache}, **(extra or {})))
        except FileNotFoundError:
            return err("not_found", 404)

    @staticmethod
    def _cv_version():
        import cv2
        return cv2.__version__

    def _load(self, ref):
        if not isinstance(ref, dict):
            raise ValueError("bad_image_ref")
        if ref.get("sample") in SAMPLES:
            with open(os.path.join(WEB_DIR, "samples", ref["sample"] + ".jpg"), "rb") as f:
                return f.read(), "sample:" + ref["sample"]
        key = str(ref.get("key", ""))
        if KEY_RE.fullmatch(key):
            data = self.blobs.get(key)
            if len(data) > MAX_UPLOAD:
                raise ValueError("image_too_large")
            return data, "upload"
        raise ValueError("bad_image_ref")

    def _inspect(self, data, h, ip):
        from .service import decode_image, inspect
        vid = visits.visitor_id(ip, h.get("user-agent", ""))
        if not self._count("inspections", LIMITS["inspections_per_day"]):
            return err("daily_limit", 429, "The public demo reached its daily limit. Please try again tomorrow.")
        if not self._count("inspections_v", LIMITS["inspections_per_visitor_day"], vid):
            return err("visitor_limit", 429, "You reached the per-visitor daily limit of the public demo.")
        try:
            cur_bytes, cur_src = self._load(data.get("image"))
            prev = None
            if data.get("previous"):
                try:
                    pbytes, _ = self._load(data["previous"])
                    prev = decode_image(pbytes)
                except Exception:
                    if not data.get("previous_stations"):
                        raise                  # uploads expire after a day: the stations still allow a comparison
            cur = decode_image(cur_bytes)
        except ValueError as e:
            return err(str(e), 400)
        except Exception as e:  # missing / expired upload
            return err("image_unavailable", 400, type(e).__name__)
        planner = self.planner_factory(self.llm_allowed) if self.planner_factory else None
        ref = data.get("reference") if data.get("reference") in ("auto", "charuco", "idcard") else "auto"
        out = inspect(cur, prev, retakes=min(int(data.get("retakes") or 0), 5), planner=planner, reference=ref,
                      focal_35mm=data.get("focal_35mm"), previous_stations=data.get("previous_stations"))
        out["source"] = cur_src
        redacted = out.pop("_redacted_jpeg", None)
        if redacted is not None and cur_src == "upload":
            # wallet-card photo: replace the raw upload by the redacted copy (card numbers never kept), or delete it
            key = str(data["image"]["key"])
            try:
                if redacted:
                    self.blobs.put(key, redacted)
                else:
                    self.blobs.delete(key)
                out["upload_redacted"] = True
            except Exception as e:  # never return a result while the raw card photo may remain stored
                self.log(json.dumps({"event": "redact_store_failed", "error": type(e).__name__}))
                try:
                    self.blobs.delete(key)
                    out["upload_redacted"] = True
                except Exception:
                    return err("redaction_failed", 500)
        names = [t["action"]["name"] for t in out["trace"]]
        planners = sorted({t["action"]["planner"] for t in out["trace"]})
        self.store.put(f"INSP#{out['inspection_id']}", "TRACE",
                       {"at": time.time(), "source": cur_src, "status": out["measurement"]["status"],
                        "actions": names, "trace": out["trace"], "llm": out["llm"], "timings_ms": out["timings_ms"]}, ttl_days=30)
        if out["ticket"]:
            self.store.put(f"TICKET#{out['ticket']['id']}", "META",
                           {"ticket": out["ticket"], "inspection_id": out["inspection_id"], "created_at": time.time(),
                            "status": "pending_human_approval"}, ttl_days=30)
        self.log(json.dumps({"event": "inspect", "inspection": out["inspection_id"], "source": cur_src,
                             "status": out["measurement"]["status"], "actions": names, "planners": planners,
                             "llm_calls": out["llm"]["calls"], "llm_cost_usd": out["llm"]["cost_usd"], **out["timings_ms"]}))
        visits.log_visit(self.store, h, ip, {"type": "inspect", "sample": cur_src.removeprefix("sample:"),
                                             "action": names[-1], "planner": planners[-1] if planners else ""})
        return jresp(out)

    # ------------------------------------------------------------------ background jobs
    def _enqueue(self, data, h, ip):
        """Count the request against the limits, store it, start the background run, answer at once."""
        vid = visits.visitor_id(ip, h.get("user-agent", ""))
        if not isinstance(data, dict) or not isinstance(data.get("image"), dict):
            return err("bad_image_ref", 400)
        if not self._count("inspections", LIMITS["inspections_per_day"]):
            return err("daily_limit", 429, "The public demo reached its daily limit. Please try again tomorrow.")
        if not self._count("inspections_v", LIMITS["inspections_per_visitor_day"], vid):
            return err("visitor_limit", 429, "You reached the per-visitor daily limit of the public demo.")
        job = secrets.token_hex(12)
        self.store.put(f"JOB#{job}", "META", {"status": "pending", "at": time.time(), "request": json.dumps(data)[:20000],
                                              "ip": ip, "ua": h.get("user-agent", "")[:300], "referer": h.get("referer", "")[:300]},
                       ttl_days=1)
        try:
            self.dispatcher(job)
        except Exception as e:
            self.log(json.dumps({"event": "dispatch_failed", "error": type(e).__name__, "detail": str(e)[:300]}))
            return err("busy", 503, "Could not start the analysis. Please try again.")
        return jresp({"job_id": job, "status": "pending"}, 202)

    def run_job(self, job):
        """Background run of a stored job: the same handler as the inline route; the response (result or error,
        with its HTTP status) is kept for GET /api/job/<id> (result JSON in the uploads bucket, 1-day expiry)."""
        if not JOB_RE.fullmatch(str(job)):
            return
        row = self.store.get(f"JOB#{job}", "META")
        if not row or row.get("status") != "pending":
            return                                   # unknown, or already taken (a retried event)
        self.store.put(f"JOB#{job}", "META", dict(row, status="running", started=time.time()), ttl_days=1)
        h = {"user-agent": row.get("ua", ""), "referer": row.get("referer", "")}
        self._tl.in_job = True
        try:
            r = self._run_inspect(json.loads(row["request"]), h, row.get("ip", ""))
        finally:
            self._tl.in_job = False
        key = f"uploads/jobs/{job}.json"
        try:
            self.blobs.put(key, r.body)
            self.store.put(f"JOB#{job}", "META", {"status": "done" if r.status == 200 else "error", "http": r.status,
                                                  "at": row.get("at"), "done_at": time.time(), "key": key}, ttl_days=1)
        except Exception as e:
            self.log(json.dumps({"event": "job_store_failed", "job": job, "error": type(e).__name__}))
            self.store.put(f"JOB#{job}", "META", {"status": "error", "http": 500, "at": row.get("at"),
                                                  "error": "internal_error"}, ttl_days=1)

    def _run_inspect(self, data, h, ip):
        try:
            return self._inspect(data, h, ip)
        except Exception as e:   # same contract as handle(): never leak a stack trace
            self.log(json.dumps({"event": "error", "path": "job", "error": type(e).__name__, "detail": str(e)[:300],
                                 "trace": traceback.format_exc()[-1200:]}))
            return err("internal_error", 500, type(e).__name__)

    def _job(self, job):
        if not JOB_RE.fullmatch(job):
            return err("job_not_found", 404)
        row = self.store.get(f"JOB#{job}", "META")
        if not row:
            return err("job_not_found", 404)
        st = row.get("status")
        if st in ("pending", "running"):
            if time.time() - float(row.get("at") or 0) > JOB_STALE_S:
                return err("analysis_timeout", 504, "The analysis did not finish in time.")
            return jresp({"status": "pending", "job_id": job})
        if row.get("key"):
            try:
                body = self.blobs.get(row["key"])
            except Exception:
                return err("job_expired", 410)
            return Response(int(row.get("http") or 200), body, "application/json", {"cache-control": "no-store"})
        return err(row.get("error") or "internal_error", int(row.get("http") or 500))

    def _decide(self, tid, data, h, ip):
        decision = data.get("decision")
        if decision not in ("approve", "reject"):
            return err("bad_decision")
        row = self.store.get(f"TICKET#{tid}", "META")
        if not row:
            return err("ticket_not_found", 404)
        if row.get("status") != "pending_human_approval":
            return jresp({"id": tid, "status": row["status"], "already_decided": True})
        status = "approved" if decision == "approve" else "rejected"
        row.update({"status": status, "decided_at": time.time(), "note": str(data.get("note", ""))[:200]})
        self.store.put(f"TICKET#{tid}", "META", row, ttl_days=30)
        self.log(json.dumps({"event": "ticket_decision", "ticket": tid, "status": status}))
        visits.log_visit(self.store, h, ip, {"type": "ticket", "action": status})
        return jresp({"id": tid, "status": status})


# ---------------------------------------------------------------------- blob backends
class S3Blobs:
    def __init__(self, bucket, region=None):
        import boto3
        from botocore.config import Config
        self.bucket = bucket
        self.s3 = boto3.client("s3", region_name=region, config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}))

    def presign_post(self, key, max_bytes):
        p = self.s3.generate_presigned_post(self.bucket, key, Fields={"Content-Type": "image/jpeg"},
                                            Conditions=[["content-length-range", 1024, max_bytes], {"Content-Type": "image/jpeg"}],
                                            ExpiresIn=300)
        return {"url": p["url"], "fields": p["fields"]}

    def get(self, key):
        return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def put(self, key, data: bytes):
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType="image/jpeg")

    def delete(self, key):
        self.s3.delete_object(Bucket=self.bucket, Key=key)


class LocalBlobs:
    """Local stand-in for S3 (scripts/serve_local.py): the browser posts the same multipart form."""
    def __init__(self, root):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def presign_post(self, key, max_bytes):
        return {"url": "/api/local-upload", "fields": {"key": key, "Content-Type": "image/jpeg"}}

    def accept_upload(self, ctype, body):
        from email.parser import BytesParser
        from email.policy import default
        msg = BytesParser(policy=default).parsebytes(b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + body)
        fields, data = {}, None
        for part in msg.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if name == "file":
                data = part.get_payload(decode=True)
            else:
                fields[name] = part.get_content().strip()
        key = fields.get("key", "")
        if not KEY_RE.fullmatch(key) or not data or len(data) > MAX_UPLOAD:
            return {"ok": False}
        path = os.path.join(self.root, key.replace("/", "_"))
        with open(path, "wb") as f:
            f.write(data)
        return {"ok": True}

    def get(self, key):
        with open(os.path.join(self.root, key.replace("/", "_")), "rb") as f:
            return f.read()

    def put(self, key, data: bytes):
        with open(os.path.join(self.root, key.replace("/", "_")), "wb") as f:
            f.write(data)

    def delete(self, key):
        try:
            os.remove(os.path.join(self.root, key.replace("/", "_")))
        except FileNotFoundError:
            pass

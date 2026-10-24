"""Guided camera (camera-guidee): static routes, worker CSP and the pre-gzipped OpenCV.js.
Run: python tests/test_camera_routes.py"""
import base64
import gzip
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from crackwatch import api  # noqa: E402
from crackwatch.store import MemStore  # noqa: E402

OPENCV_SHA256 = "bd0c3e6448043de04f6a64a12cb7b759f78c3ab8f7c35c9f2e0f71c88bb17103"  # @techstark/opencv-js 4.12.0-release.1


def app():
    return api.App(MemStore(), None, log=lambda *_: None)


def test_camera_files():
    a = app()
    for p in ("/camera.js", "/camera.css", "/camera-detect.js", "/camera-worker.js"):
        r = a.handle("GET", p, {}, b"", {}, "1")
        assert r.status == 200 and len(r.body) > 500, p
    page = a.handle("GET", "/camera.js", {}, b"", {}, "1").headers["content-security-policy"]
    assert "unsafe-eval" not in page                       # the page keeps the strict policy
    w = a.handle("GET", "/camera-worker.js", {}, b"", {}, "1").headers["content-security-policy"]
    assert "'wasm-unsafe-eval'" in w and "'unsafe-eval'" in w
    assert "https://cdn.jsdelivr.net" in w and "blob:" in w   # OpenCV.js from the CDN, checked, run from a Blob URL
    src = a.handle("GET", "/camera-worker.js", {}, b"", {}, "1").body.decode()
    assert OPENCV_SHA256 in src                              # the worker checks the same file as the self-hosted copy


def test_opencv_gzip_under_lambda_cap():
    r = app().handle("GET", "/vendor/opencv-4.12.0.js", {}, b"", {}, "1")
    assert r.status == 200 and r.headers["content-encoding"] == "gzip"
    assert not r.headers["content-type"].startswith("text/")  # lambda_handler base64-encodes it
    raw = gzip.decompress(r.body)
    assert hashlib.sha256(raw).hexdigest() == OPENCV_SHA256
    # Lambda synchronous response cap is 6 MB for the whole JSON envelope (body is base64 there)
    assert len(json.dumps({"body": base64.b64encode(r.body).decode()})) < 6 * 1024 * 1024 - 64 * 1024


if __name__ == "__main__":
    test_camera_files()
    test_opencv_gzip_under_lambda_cap()
    print("camera routes: ok")

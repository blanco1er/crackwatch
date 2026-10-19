"""Dependency-free writers for print-exact PNG (pHYs DPI chunk) and single-page PDF.

OpenCV has no PDF writer and cv2.imwrite does not store a physical resolution, so a
printed PNG could be silently rescaled. These helpers guarantee that 1 mm on paper is
exactly `px_per_mm` pixels of the raster.
"""
from __future__ import annotations

import struct
import zlib

import cv2
import numpy as np

MM_PER_INCH = 25.4
PT_PER_MM = 72.0 / MM_PER_INCH


def write_png_with_dpi(path: str, gray: np.ndarray, px_per_mm: float) -> None:
    ok, buf = cv2.imencode(".png", gray)
    if not ok:
        raise RuntimeError("PNG encoding failed")
    data = buf.tobytes()
    ppm = int(round(px_per_mm * 1000.0))  # pixels per metre
    payload = struct.pack(">IIB", ppm, ppm, 1)
    chunk = struct.pack(">I", len(payload)) + b"pHYs" + payload
    chunk += struct.pack(">I", zlib.crc32(b"pHYs" + payload) & 0xFFFFFFFF)
    # Insert right after IHDR (8-byte signature + 25-byte IHDR chunk).
    out = data[:33] + chunk + data[33:]
    with open(path, "wb") as f:
        f.write(out)


def write_pdf_single_image(path: str, gray: np.ndarray, page_w_mm: float, page_h_mm: float) -> None:
    """Write a one-page PDF whose page is exactly page_w_mm x page_h_mm and is fully
    covered by the grayscale raster (no interpolation, so edges stay sharp)."""
    if gray.ndim != 2 or gray.dtype != np.uint8:
        raise ValueError("expects uint8 grayscale")
    h, w = gray.shape
    W = page_w_mm * PT_PER_MM
    H = page_h_mm * PT_PER_MM
    img_stream = zlib.compress(np.ascontiguousarray(gray).tobytes(), 9)
    content = f"q {W:.4f} 0 0 {H:.4f} 0 0 cm /Im0 Do Q".encode()

    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W:.4f} {H:.4f}] "
         f"/Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>").encode(),
        (f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceGray "
         f"/BitsPerComponent 8 /Interpolate false /Filter /FlateDecode /Length {len(img_stream)} >>\nstream\n").encode()
        + img_stream + b"\nendstream",
        f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    with open(path, "wb") as f:
        f.write(bytes(out))

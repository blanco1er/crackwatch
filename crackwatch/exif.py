"""Minimal EXIF reader (no dependency): the 35 mm-equivalent focal length of a JPEG, which the wallet-card
reference needs (cv2.imdecode drops EXIF). Only FocalLengthIn35mmFilm (0xA405) is read, from the Exif sub-IFD of
the APP1 segment; GPS and every other tag are ignored."""
from __future__ import annotations

import struct


def _ifd_entries(tiff: bytes, off: int, endian: str):
    if off + 2 > len(tiff):
        return
    n = struct.unpack_from(endian + "H", tiff, off)[0]
    for i in range(min(n, 512)):
        e = off + 2 + 12 * i
        if e + 12 > len(tiff):
            return
        tag, typ, cnt = struct.unpack_from(endian + "HHI", tiff, e)
        yield tag, typ, cnt, e + 8


def _value(tiff, typ, cnt, voff, endian):
    if cnt != 1:
        return None
    if typ == 3:                                    # SHORT, stored in the entry itself
        return struct.unpack_from(endian + "H", tiff, voff)[0]
    if typ == 4:                                    # LONG
        return struct.unpack_from(endian + "I", tiff, voff)[0]
    if typ == 5:                                    # RATIONAL, stored at an offset
        p = struct.unpack_from(endian + "I", tiff, voff)[0]
        if p + 8 <= len(tiff):
            a, b = struct.unpack_from(endian + "II", tiff, p)
            return a / b if b else None
    return None


def focal_35mm(data: bytes) -> float | None:
    """FocalLengthIn35mmFilm of a JPEG (bytes), or None."""
    try:
        if data[:2] != b"\xff\xd8":
            return None
        i = 2
        while i + 4 <= len(data) and data[i] == 0xFF:
            marker = data[i + 1]
            size = struct.unpack_from(">H", data, i + 2)[0]
            if marker == 0xE1 and data[i + 4:i + 10] == b"Exif\x00\x00":
                tiff = data[i + 10:i + 2 + size]
                endian = "<" if tiff[:2] == b"II" else ">"
                ifd0 = struct.unpack_from(endian + "I", tiff, 4)[0]
                for tag, typ, cnt, voff in _ifd_entries(tiff, ifd0, endian):
                    if tag == 0x8769:                   # Exif sub-IFD
                        sub = _value(tiff, 4, 1, voff, endian)
                        for t2, ty2, c2, v2 in _ifd_entries(tiff, sub, endian):
                            if t2 == 0xA405:
                                v = _value(tiff, ty2, c2, v2, endian)
                                return float(v) if v else None
                return None
            if marker in (0xDA, 0xD9):                 # start of scan: no more metadata
                return None
            i += 2 + size
    except (struct.error, IndexError, TypeError):
        return None
    return None

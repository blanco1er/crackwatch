"""ChArUco scale/registration cards and the E2/E4 printed test chart ("mire").

Board frame convention (used everywhere in CrackWatch): origin at the top-left outer
corner of the ChArUco board, x to the right, y downwards, units = millimetres. This is
exactly the frame returned by `CharucoBoard.matchImagePoints` when the board is built
with millimetre lengths.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field

import cv2
import numpy as np

from .printio import write_pdf_single_image, write_png_with_dpi

PRINT_PX_PER_MM = 20  # 508 dpi raster; every 0.05 mm is an integer pixel count


@dataclass(frozen=True)
class CardSpec:
    name: str
    squares: tuple            # (squaresX, squaresY)
    square_mm: float
    marker_mm: float
    dict_id: int
    first_id: int
    paper_mm: tuple           # (w, h) of the printed sheet
    board_offset_mm: tuple    # board top-left position on the sheet

    @property
    def board_mm(self):
        return (self.squares[0] * self.square_mm, self.squares[1] * self.square_mm)

    @property
    def n_markers(self):
        return (self.squares[0] * self.squares[1]) // 2

    def paper_rect_in_board_frame(self):
        """(x0, y0, x1, y1) of the whole sheet in board-frame mm (used to mask it)."""
        ox, oy = self.board_offset_mm
        return (-ox, -oy, self.paper_mm[0] - ox, self.paper_mm[1] - oy)

    def to_json(self):
        d = asdict(self)
        d["board_mm"] = self.board_mm
        return d


# A6 wall card (default) and a bigger A5 card for far shots. Disjoint marker ids so
# both can be told apart in the same picture.
CARD_A6 = CardSpec("A6-5x7-15mm", (5, 7), 15.0, 11.0, cv2.aruco.DICT_5X5_100, 0,
                   (105.0, 148.0), (15.0, 15.0))
CARD_A5 = CardSpec("A5-7x10-17mm", (7, 10), 17.0, 12.5, cv2.aruco.DICT_5X5_100, 20,
                   (148.0, 210.0), (14.5, 14.0))
KNOWN_CARDS = (CARD_A6, CARD_A5)


def make_board(spec: CardSpec) -> cv2.aruco.CharucoBoard:
    dictionary = cv2.aruco.getPredefinedDictionary(spec.dict_id)
    ids = np.arange(spec.first_id, spec.first_id + spec.n_markers, dtype=np.int32)
    return cv2.aruco.CharucoBoard(spec.squares, spec.square_mm, spec.marker_mm, dictionary, ids)


def render_board(spec: CardSpec, px_per_mm: float) -> np.ndarray:
    bw, bh = spec.board_mm
    size = (int(round(bw * px_per_mm)), int(round(bh * px_per_mm)))
    return make_board(spec).generateImage(size, marginSize=0, borderBits=1)


def _text(img, txt, x_mm, y_mm, h_mm, ppm, thickness_mm=0.35):
    scale = h_mm * ppm / 22.0
    cv2.putText(img, txt, (int(x_mm * ppm), int(y_mm * ppm)), cv2.FONT_HERSHEY_SIMPLEX,
                scale, 0, max(1, int(round(thickness_mm * ppm))), cv2.LINE_AA)


def _rect_mm(img, x0, y0, x1, y1, ppm, value=0):
    """Fill [x0,x1) x [y0,y1) in mm with exact pixel edges."""
    img[int(round(y0 * ppm)):int(round(y1 * ppm)), int(round(x0 * ppm)):int(round(x1 * ppm))] = value


def _ruler(img, x_mm, y_mm, length_mm, ppm):
    _rect_mm(img, x_mm, y_mm, x_mm + length_mm, y_mm + 0.3, ppm)
    for i in range(int(length_mm) + 1):
        h = 3.0 if i % 10 == 0 else (2.0 if i % 5 == 0 else 1.2)
        _rect_mm(img, x_mm + i - 0.1, y_mm - h, x_mm + i + 0.1, y_mm, ppm)


def render_card_page(spec: CardSpec, ppm: float = PRINT_PX_PER_MM) -> np.ndarray:
    pw, ph = spec.paper_mm
    page = np.full((int(round(ph * ppm)), int(round(pw * ppm))), 255, np.uint8)
    ox, oy = spec.board_offset_mm
    board = render_board(spec, ppm)
    y0, x0 = int(round(oy * ppm)), int(round(ox * ppm))
    page[y0:y0 + board.shape[0], x0:x0 + board.shape[1]] = board
    bw, bh = spec.board_mm
    ty = oy + bh + 6
    _text(page, f"CrackWatch scale card {spec.name}", ox, ty, 3.0, ppm)
    _text(page, f"square = {spec.square_mm:.1f} mm  board = {bw:.0f} x {bh:.0f} mm", ox, ty + 5, 2.4, ppm)
    _text(page, "PRINT AT 100% (actual size). Check: ruler = 50 mm", ox, ty + 9.5, 2.4, ppm)
    _ruler(page, ox, ty + 16, 50.0, ppm)
    return page


# ---------------------------------------------------------------- E2 / E4 test chart
MIRE_WIDTHS_MM = (0.2, 0.3, 0.5, 0.7, 1.0, 1.5, 2.0, 3.0)


@dataclass
class MireLine:
    label: str
    x_mm: float         # centre-line x in board frame
    y0_mm: float
    y1_mm: float
    width_mm: float


@dataclass
class MireSpec:
    version: int
    card: dict
    paper_mm: tuple
    board_offset_mm: tuple
    lines: list = field(default_factory=list)
    exclude_rects_mm: list = field(default_factory=list)   # board frame, label areas


def mire_layout(version: int = 1) -> MireSpec:
    """A5 portrait sheet: A6-type board top-left, 8 vertical bars of known width.
    v2 = simulated evolution: bars 3, 5 and 7 widened, bars 2 and 6 extended by 10 mm."""
    spec = CARD_A6
    off = (10.0, 12.0)
    mire = MireSpec(version, spec.to_json(), (148.0, 210.0), off)
    for i, w in enumerate(MIRE_WIDTHS_MM, start=1):
        x_page = 92.0 + (i - 1) * 6.5
        y0_page, y1_page = 30.0, 115.0
        if version == 2:
            if i in (3, 5, 7):
                w = round(w + (0.2 if w < 1 else 0.5), 2)
            if i in (2, 6):
                y1_page += 10.0
        mire.lines.append(MireLine(f"L{i}", x_page - off[0], y0_page - off[1], y1_page - off[1], w))
    # label band above the bars and the footer text are excluded from crack search
    mire.exclude_rects_mm.append((88.0 - off[0], 14.0 - off[1], 145.0 - off[0], 27.0 - off[1]))
    mire.exclude_rects_mm.append((0.0 - off[0], 130.0 - off[1], 148.0 - off[0], 210.0 - off[1]))
    return mire


def render_mire_page(mire: MireSpec, ppm: float = PRINT_PX_PER_MM) -> np.ndarray:
    pw, ph = mire.paper_mm
    page = np.full((int(round(ph * ppm)), int(round(pw * ppm))), 255, np.uint8)
    ox, oy = mire.board_offset_mm
    board = render_board(CARD_A6, ppm)
    y0, x0 = int(round(oy * ppm)), int(round(ox * ppm))
    page[y0:y0 + board.shape[0], x0:x0 + board.shape[1]] = board
    for ln in mire.lines:
        xc = ln.x_mm + ox
        _rect_mm(page, xc - ln.width_mm / 2, ln.y0_mm + oy, xc + ln.width_mm / 2, ln.y1_mm + oy, ppm)
        _text(page, ln.label, xc - 2.2, 20.0, 2.2, ppm)
        _text(page, f"{ln.width_mm:g}", xc - 2.6, 25.0, 1.8, ppm, 0.25)
    _text(page, f"CrackWatch test chart v{mire.version} (E2/E4). PRINT AT 100%.", 10, 140, 3.0, ppm)
    _text(page, "Bar widths in mm above each bar. Check: ruler = 100 mm", 10, 146, 2.6, ppm)
    _ruler(page, 10, 160, 100.0, ppm)
    _text(page, "Verify printed widths with a loupe/scanner before using as ground truth.", 10, 172, 2.4, ppm)
    return page


def export_all(out_dir: str) -> list:
    import json
    import os
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for spec in KNOWN_CARDS:
        page = render_card_page(spec)
        base = os.path.join(out_dir, f"card_{spec.name}")
        write_png_with_dpi(base + ".png", page, PRINT_PX_PER_MM)
        write_pdf_single_image(base + ".pdf", page, *spec.paper_mm)
        with open(base + ".json", "w") as f:
            json.dump(spec.to_json(), f, indent=2)
        written += [base + ext for ext in (".png", ".pdf", ".json")]
    for v in (1, 2):
        mire = mire_layout(v)
        page = render_mire_page(mire)
        base = os.path.join(out_dir, f"mire_v{v}")
        write_png_with_dpi(base + ".png", page, PRINT_PX_PER_MM)
        write_pdf_single_image(base + ".pdf", page, *mire.paper_mm)
        with open(base + ".json", "w") as f:
            json.dump(asdict(mire), f, indent=2)
        written += [base + ext for ext in (".png", ".pdf", ".json")]
    return written

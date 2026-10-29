"""
hd2stats.py - Helldivers 2 end-of-mission stat screens -> spreadsheet.

One process, everything in memory, no intermediate files.

    python hd2stats.py                       # reads ./To_Process
    python hd2stats.py "D:/screens" --form FormResponses.csv

See README.md for details.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import difflib
import datetime
import json
import os
import re
import shutil
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

# Tesseract spawns OpenMP threads by default; we run many tesseract processes
# in parallel ourselves, so one thread each is much faster overall.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pytesseract  # noqa: E402
from PIL import Image  # noqa: E402

__version__ = "1.6"
HERE = Path(__file__).resolve().parent
SETTINGS_FILE = HERE / "settings.json"


FILE_HASH: dict = {}   # screenshot file name -> content fingerprint (duplicates are read once)


def file_hash(p: Path) -> str:
    import hashlib
    try:
        h = hashlib.sha1()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()[:16]
    except OSError:
        return ""


def load_settings() -> dict:
    """settings.json next to the script (written by Stats UI). Missing or broken file -> {}."""
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def synced_folder() -> Path | None:
    """The Google Drive folder synced to this PC (Drive for desktop), if one is set and reachable."""
    f = str(load_settings().get("drive_folder") or "").strip()
    if f and Path(f).is_dir():
        return Path(f)
    return None

# --------------------------------------------------------------------------
# Stats shown on the screen, in on-screen order (row index = list index)
# --------------------------------------------------------------------------
STATS = [
    "kills", "accuracy", "shots_fired", "shots_hit", "deaths", "stims_used",
    "accidentals", "samples_extracted", "stratagems_used", "melee_kills",
    "times_reinforcing", "friendly_fire_damage",
]
LEGACY_STATS = STATS[:8]  # the 8 stats the old pipeline produced
LEGACY_HEADERS = ["KILLS", "ACCURACY", "SHOTS FIRED", "SHOTS HIT", "DEATH",
                  "STIMS USED", "ACCIDENTALS", "SAMPLES EXTRACTED"]

# label word -> (row index, is it the first word of the label?)
LABEL_WORDS = {
    "KILLS": (0, True), "ACCURACY": (1, True), "FIRED": (2, False),
    "HIT": (3, False), "DEATHS": (4, True), "STIMS": (5, True),
    "ACCIDENTALS": (6, True), "SAMPLES": (7, True), "EXTRACTED": (7, False),
    "STRATAGEMS": (8, True), "MELEE": (9, True), "TIMES": (10, True),
    "REINFORCING": (10, False), "FRIENDLY": (11, True), "DAMAGE": (11, False),
    # German game client
    "ELIMINIERUNGEN": (0, True), "PRAZISION": (1, True), "ABGEGEBENE": (2, True),
    "GETROFFENE": (3, True), "VERLUSTE": (4, True), "SPRITZEN": (5, True), "BENUTZT": (5, False),
    "UNFALLE": (6, True), "PROBEN": (7, True), "EXTRAHIERT": (7, False),
    "TAKTIKAUSRUSTUNGEN": (8, True), "NAHKAMPF": (9, True), "NAHKAMPFELIMINIERUNG": (9, True),
    "VERSTARKUNGEN": (10, True), "FRIENDLYFIRESCHADEN": (11, True), "SCHADEN": (11, False),
}
# Words that are row 0 at the panel's left edge but also end the row-9 label ("MELEE KILLS",
# "NAHKAMPF-ELIMINIERUNG").
ROW0_AMBIGUOUS = {"KILLS", "ELIMINIERUNGEN"}

NORM_WIDTH = 1800  # images are scaled to this width for layout detection
IMG_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff", ".gif"}

# OCR variants: (min brightness for text, target text height px, tesseract psm)
VARIANTS = [(165, 40, 7), (140, 52, 7), (195, 34, 8)]
WHITELIST = "0123456789.,%"


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def find_tesseract(cli_value: str | None) -> str:
    candidates = [cli_value, os.environ.get("TESSERACT_CMD"), shutil.which("tesseract"),
                  r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                  r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                  os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
                  "/usr/bin/tesseract", "/usr/local/bin/tesseract", "/opt/homebrew/bin/tesseract"]
    for c in candidates:
        if c and Path(c).exists():
            return str(c)
    sys.exit("Tesseract not found. Install it (see README) or pass --tesseract PATH.")


def load_bgr(path: Path) -> np.ndarray:
    """Read any image format (PNG/JPEG/WEBP/..., any path) as a BGR array."""
    with Image.open(path) as im:
        im = im.convert("RGB")
        arr = np.asarray(im)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def text_mask(bgr: np.ndarray, thr: int = 165, white_only: bool = False) -> np.ndarray:
    """255 where a pixel looks like on-screen text (white, or yellow highlight)."""
    b = bgr[:, :, 0].astype(np.int16)
    g = bgr[:, :, 1].astype(np.int16)
    r = bgr[:, :, 2].astype(np.int16)
    white = (b > thr) & (g > thr) & (r > thr) & (np.abs(r - b) < 60)
    if white_only:
        return white.astype(np.uint8) * 255
    yellow = (r > thr) & (g > thr - 25) & (b < 130) & (r - b > 80)
    return (white | yellow).astype(np.uint8) * 255


def letters(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()  # Ä -> A
    return re.sub(r"[^A-Z]", "", s.upper())


def match_label(word: str) -> str | None:
    w = letters(word)
    if len(w) < 3:
        return None
    if w in LABEL_WORDS:
        return w
    best = difflib.get_close_matches(w, LABEL_WORDS.keys(), n=1, cutoff=0.75)
    return best[0] if best else None


# --------------------------------------------------------------------------
# Layout detection: find the panels (players) and stat rows from the labels
# --------------------------------------------------------------------------
@dataclass
class Layout:
    scale: float          # original px -> normalised px
    lefts: list[float]    # left x of each panel (normalised)
    pitch: float          # distance between panels
    y0: float             # centre y of row 0
    dy: float             # row spacing
    label_end: dict       # (panel, row) -> x where the label text ends
    angle: float = 0.0    # estimated tilt of the screenshot in degrees


class LayoutError(Exception):
    pass


def detect_layout(bgr: np.ndarray) -> Layout:
    h, w = bgr.shape[:2]
    s = NORM_WIDTH / w
    small = cv2.resize(bgr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    m = 255 - text_mask(small, 165)
    d = pytesseract.image_to_data(m, config="--psm 11", output_type=pytesseract.Output.DICT)

    words = []
    for i, txt in enumerate(d["text"]):
        lab = match_label(txt) if txt.strip() else None
        if lab:
            words.append(dict(lab=lab, x=d["left"][i], y=d["top"][i] + d["height"][i] / 2,
                              r=d["left"][i] + d["width"][i], h=d["height"][i]))
    if len(words) < 6:
        raise LayoutError("could not find the stat labels (is this a stat screen?)")

    # Tilt: the same label in different panels sits on the same row.
    slopes = []
    by_lab = defaultdict(list)
    for wd in words:
        if wd["lab"] not in ROW0_AMBIGUOUS:
            by_lab[wd["lab"]].append(wd)
    for ws in by_lab.values():
        ws = sorted(ws, key=lambda q: q["x"])
        for a_, b_ in zip(ws, ws[1:]):
            dx = b_["x"] - a_["x"]
            if dx > 250:
                slopes.append((b_["y"] - a_["y"]) / dx)
    angle = float(np.degrees(np.arctan(np.median(slopes)))) if len(slopes) >= 3 else 0.0

    # Panel left edges: cluster the x of label words that start a row.
    starts = sorted(wd["x"] for wd in words if LABEL_WORDS[wd["lab"]][1] and wd["lab"] not in ROW0_AMBIGUOUS)
    clusters: list[list[float]] = []
    for x in starts:
        if clusters and x - clusters[-1][-1] < 60:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    clusters = [c for c in clusters if len(c) >= 3]
    if not clusters:
        raise LayoutError("could not locate player panels")
    lefts = [float(np.median(c)) for c in clusters]

    def panel_of(x: float) -> int | None:
        i = int(np.argmin([abs(x - l) for l in lefts]))
        return i if x >= lefts[i] - 30 else (i - 1 if i > 0 else None)

    # Row geometry: robust straight-line fit of y = y0 + row * dy
    pts = []
    for wd in words:
        row, first = LABEL_WORDS[wd["lab"]]
        p = panel_of(wd["x"])
        if p is None:
            continue
        if wd["lab"] in ROW0_AMBIGUOUS:  # "KILLS:" (row 0) vs "MELEE KILLS:" (row 9)
            row = 0 if abs(wd["x"] - lefts[p]) < 30 else 9
        wd["row"], wd["panel"] = row, p
        pts.append((row, wd["y"]))
    pts_a = np.array(pts, dtype=float)
    if len(set(pts_a[:, 0])) < 3:
        raise LayoutError("not enough stat rows found")
    keep = np.ones(len(pts_a), bool)
    for _ in range(3):
        b, a = np.polyfit(pts_a[keep, 0], pts_a[keep, 1], 1)
        resid = np.abs(pts_a[:, 1] - (a + b * pts_a[:, 0]))
        keep = resid < max(0.25 * b, 4)
    dy, y0 = b, a
    if dy <= 5:
        raise LayoutError("bad row spacing")

    if len(lefts) > 1:
        # smallest gap = one panel; bigger gaps are an empty slot (player left)
        pitch = float(np.min(np.diff(lefts)))
    else:
        pitch = 9.55 * dy  # panel width / row height ratio of the in-game UI

    # Where the label text ends, per panel and row (values start after it)
    label_end: dict = {}
    for wd in words:
        if "row" in wd:
            k = (wd["panel"], wd["row"])
            label_end[k] = max(label_end.get(k, 0), wd["r"] - lefts[wd["panel"]])
    return Layout(s, lefts, pitch, y0, dy, label_end, angle)


# --------------------------------------------------------------------------
# Reading one value
# --------------------------------------------------------------------------
def value_band(bgr, lay: Layout, panel: int, row: int):
    """Crop (original resolution) of the area right of the label."""
    off = lay.label_end.get((panel, row))
    if off is None:
        others = [v for (p, r), v in lay.label_end.items() if r == row]
        off = float(np.median(others)) if others else 0.45 * lay.pitch
    x0 = lay.lefts[panel] + off + 0.15 * lay.dy
    x1 = lay.lefts[panel] + 0.82 * lay.pitch
    yc = lay.y0 + row * lay.dy
    y0, y1 = yc - 0.45 * lay.dy, yc + 0.45 * lay.dy
    s = lay.scale
    H, W = bgr.shape[:2]
    X0, X1 = int(max(0, x0 / s)), int(min(W, x1 / s))
    Y0, Y1 = int(max(0, y0 / s)), int(min(H, y1 / s))
    if X1 - X0 < 5 or Y1 - Y0 < 5:
        return None
    return bgr[Y0:Y1, X0:X1]


def isolate_digits(band: np.ndarray, thr: int):
    """Find the right-aligned number in a value band.

    Returns (clean binary mask of just the number, text height) or None.
    """
    H = band.shape[0]
    m = text_mask(band, thr)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    glyphs = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if a < 4:
            continue
        if 0.28 * H <= h <= 0.85 * H and w <= 1.6 * h and y > 0 and y + h < H:
            glyphs.append((x, y, w, h))
    if not glyphs:
        return None
    glyphs.sort()
    run = [glyphs[-1]]                      # start from the rightmost glyph
    for g in reversed(glyphs[:-1]):
        if run[0][0] - (g[0] + g[2]) < 0.55 * H:
            run.insert(0, g)
        else:
            break
    # all real glyphs of a number have about the same height
    hs = sorted(g[3] for g in run)
    hmax = hs[-1]
    run = [g for g in run if g[3] >= 0.7 * hmax]
    gx0 = min(g[0] for g in run)
    gx1 = max(g[0] + g[2] for g in run)
    gy0 = min(g[1] for g in run)
    gy1 = max(g[1] + g[3] for g in run)
    text_h = gy1 - gy0
    clean = np.zeros_like(m)
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if x >= gx0 - 2 and x + w <= gx1 + 2 and y >= gy0 - 2 and y + h <= gy1 + 0.45 * text_h and h < 0.9 * H:
            clean[lab == i] = 255
    pad = max(2, int(0.1 * text_h))
    crop = clean[max(0, gy0 - pad):min(H, int(gy1 + 0.45 * text_h)), max(0, gx0 - pad):gx1 + pad]
    if crop.size == 0:
        return None
    return crop, text_h


def to_tesseract_image(crop: np.ndarray, text_h: int, target_h: int) -> np.ndarray:
    f = target_h / max(text_h, 1)
    img = cv2.resize(crop, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    _, img = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY)
    return cv2.copyMakeBorder(255 - img, 20, 20, 25, 25, cv2.BORDER_CONSTANT, value=255)


# ---- glyph recognition (the game always uses the same font) ---------------
GLYPH_W, GLYPH_H = 16, 24


def segment_glyphs(crop: np.ndarray, text_h: int, keep_last_whole: bool = False):
    """Split a number image into glyphs, left to right.

    Returns a list of ("sep", None) for , and . or ("glyph", binary image).
    """
    n, lab, st, _ = cv2.connectedComponentsWithStats(crop, 8)
    comps = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if a < 3:
            continue
        comps.append([x, x + w, y, y + h, [i]])
    comps.sort()
    # merge pieces that overlap horizontally (e.g. the parts of '%')
    merged = []
    for c in comps:
        if merged and c[0] < merged[-1][1] - 1:
            m = merged[-1]
            m[1], m[2], m[3] = max(m[1], c[1]), min(m[2], c[2]), max(m[3], c[3])
            m[4] += c[4]
        else:
            merged.append(c)
    top = min((c[2] for c in merged), default=0)
    out = []
    last = len(merged) - 1
    for ci, (x0, x1, y0, y1, ids) in enumerate(merged):
        h = y1 - y0
        if h < 0.5 * text_h and y0 > top + 0.4 * text_h:
            out.append(("sep", None))
            continue
        if h < 0.5 * text_h:
            continue  # stray speck
        g = np.isin(lab[y0:y1, x0:x1], ids).astype(np.uint8) * 255
        w = x1 - x0
        k = int(round(w / (0.62 * h))) if w > 0.95 * h else 1
        if k >= 2 and not (keep_last_whole and ci == last):
            step = w / k                    # touching digits: split evenly
            for j in range(k):
                out.append(("glyph", g[:, int(j * step):int((j + 1) * step)]))
        else:
            out.append(("glyph", g))
    return out


def glyph_feature(g: np.ndarray) -> np.ndarray:
    h, w = g.shape
    side = max(h, int(w * GLYPH_H / GLYPH_W))
    canvas = np.zeros((side, max(w, int(side * GLYPH_W / GLYPH_H))), np.uint8)
    oy, ox = (canvas.shape[0] - h) // 2, (canvas.shape[1] - w) // 2
    canvas[oy:oy + h, ox:ox + w] = g
    v = cv2.resize(canvas, (GLYPH_W, GLYPH_H), interpolation=cv2.INTER_AREA).astype(np.float32).ravel()
    v -= v.mean()
    nrm = np.linalg.norm(v)
    v = v / nrm if nrm else v
    return np.concatenate([v, [2.0 * w / max(h, 1)]]).astype(np.float32)


class GlyphModel:
    def __init__(self, path: Path):
        d = np.load(path)
        self.X, self.y = d["X"], d["y"]

    def classify(self, g):
        f = glyph_feature(g)
        dist = np.linalg.norm(self.X - f, axis=1)
        order = np.argsort(dist)
        best = self.y[order[0]]
        d1 = dist[order[0]]
        other = next((dist[i] for i in order[1:] if self.y[i] != best), 9.0)
        return str(best), float(d1), float(other)

    def read(self, crop, text_h, stat):
        """Return (text, ok). ok=False when any glyph is uncertain."""
        parts = segment_glyphs(crop, text_h, keep_last_whole=(stat == "accuracy"))
        if stat == "accuracy":
            # format is  d[d][d] . d %  (a bare "0" when nothing hit) -> drop the trailing % glyph
            if parts and parts[-1][0] == "glyph" and (
                    any(k == "sep" for k, _ in parts) or self.classify(parts[-1][1])[0] == "%"):
                parts = parts[:-1]
            if any(k == "sep" for k, _ in parts):
                i = max(j for j, (k, _) in enumerate(parts) if k == "sep")
                parts = parts[:i + 2]
        chars, ok = [], True
        for kind, g in parts:
            if kind == "sep":
                chars.append(",")
                continue
            c, d1, d2 = self.classify(g)
            if c == "%":
                ok = False
            if d1 > GLYPH_MAX_DIST or d2 - d1 < GLYPH_MIN_MARGIN:
                ok = False
            chars.append(c)
        txt = "".join(chars)
        if stat == "accuracy" and "," in txt:
            txt = txt.replace(",", ".")
        return txt, ok and bool(txt)


SMALL_TEXT_H = 14   # px; below this the screenshot is low resolution
GLYPH_MAX_DIST = 0.75
GLYPH_MIN_MARGIN = 0.12
_MODEL: GlyphModel | None = None


def glyph_model():
    global _MODEL
    if _MODEL is None:
        p = Path(os.environ.get("HD2_GLYPHS", Path(__file__).with_name("glyphs.npz")))
        if p.exists():
            _MODEL = GlyphModel(p)
    return _MODEL


def parse_value(text: str, stat: str):
    """Return (value or None, problem or '')."""
    t = text.strip().replace(" ", "")
    digits = re.sub(r"\D", "", t)
    if not digits:
        return None, "unreadable"
    if stat == "accuracy":
        v = int(digits) / 10.0          # the game always shows one decimal
        if digits == "0":
            return 0.0, ""                  # shown as a bare "0" when nothing hit
        if len(digits) < 2 or v > 400:      # >100% is possible (explosions hit several targets)
            return v, f"odd accuracy '{t}'"
        return v, ""
    v = int(digits)
    seps = re.findall(r"[.,]", t)
    if seps:
        groups = re.split(r"[.,]", t.replace("%", ""))
        if any(len(gp) != 3 for gp in groups[1:]) or not (1 <= len(groups[0]) <= 3):
            return v, f"odd grouping '{t}'"
    elif len(digits) > 3:
        return v, f"missing thousands separator '{t}'"
    if len(digits) > 1 and digits[0] == "0":
        return v, f"leading zero '{t}'"
    if "%" in t:
        return v, f"unexpected % '{t}'"
    return v, ""


def ocr(img: np.ndarray, psm: int) -> str:
    return pytesseract.image_to_string(
        img, config=f"--oem 3 --psm {psm} -c tessedit_char_whitelist={WHITELIST}").strip()


def read_glyphs(band, stat, thr):
    """Read a value with the glyph templates. Returns (value, problem, raw)."""
    model = glyph_model()
    iso = isolate_digits(band, thr)
    if iso is None:
        return None, "no digits found", ""
    if model is None:
        return None, "no glyph model", ""
    raw, ok = model.read(*iso, stat)
    v, prob = parse_value(raw, stat)
    if not ok and not prob:
        prob = f"uncertain glyph '{raw}'"
    if not prob and iso[1] < SMALL_TEXT_H:
        prob = "small text"  # usable, but always get a second opinion
    return v, prob, raw


def read_tesseract(band, stat, variant):
    thr, th, psm = variant
    iso = isolate_digits(band, thr)
    if iso is None:
        return None, "no digits found", ""
    raw = ocr(to_tesseract_image(*iso, th), psm)
    v, prob = parse_value(raw, stat)
    return v, prob, raw


def read_name(bgr, lay: Layout, panel: int) -> str:
    s = lay.scale
    yc = lay.y0 - 2.95 * lay.dy
    x0 = lay.lefts[panel] + 0.12 * lay.pitch
    x1 = lay.lefts[panel] + 0.88 * lay.pitch
    Y0, Y1 = int(max(0, (yc - 0.38 * lay.dy) / s)), int(max(0, (yc + 0.38 * lay.dy) / s))
    X0, X1 = int(max(0, x0 / s)), int(min(bgr.shape[1], x1 / s))
    if Y1 - Y0 < 5 or X1 - X0 < 5:
        return ""
    band = bgr[Y0:Y1, X0:X1]
    m = 255 - text_mask(band, 170)
    f = 40 / max(band.shape[0], 1)
    m = cv2.resize(m, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    m = cv2.copyMakeBorder(m, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
    txt = pytesseract.image_to_string(m, config="--oem 3 --psm 7").strip()
    return re.sub(r"\s+", " ", txt)


# --------------------------------------------------------------------------
# One player = 12 values, cross-checked
# --------------------------------------------------------------------------
def consistent(acc, fired, hit) -> bool:
    if None in (acc, fired, hit):
        return False
    # note: shots hit CAN exceed shots fired in this game (accuracy above 100%)
    if fired == 0:
        return hit == 0 and acc == 0
    return abs(acc - 100.0 * hit / fired) <= 0.11


def read_player(bgr, lay: Layout, panel: int, passes: int):
    """Read the 12 values of one player.

    1st opinion: glyph templates (fast, no OCR process).
    If that is unsure, or fails the accuracy = hit / fired check, more
    opinions are gathered (other thresholds, then Tesseract) and the
    combination that agrees / passes the check wins. Anything still doubtful
    is flagged for review instead of being silently guessed.
    """
    bands = {st: value_band(bgr, lay, panel, r) for r, st in enumerate(STATS)}
    cands: dict[str, list] = {st: [] for st in STATS}   # (value, problem, source)
    raws: dict[str, list] = {st: [] for st in STATS}

    def add(st, res, src):
        v, prob, raw = res
        raws[st].append(f"{raw or '?'}")
        if v is not None:
            cands[st].append((v, prob, src))

    def opinions(st, level):
        b = bands[st]
        if b is None:
            return
        if level == 0:
            add(st, read_glyphs(b, st, 165), "glyph")
        elif level == 1:
            add(st, read_glyphs(b, st, 140), "glyph140")
            up = cv2.resize(b, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            add(st, read_glyphs(up, st, 165), "glyph2x")
        elif level == 2:
            add(st, read_tesseract(b, st, VARIANTS[0]), "tess")
            add(st, read_tesseract(b, st, VARIANTS[2]), "tess8")

    def decide(st):
        """-> (value, votes, number of distinct values seen) or None."""
        good = [v for v, p, _ in cands[st] if p in ("", "small text")]
        allv = [v for v, _, _ in cands[st]]
        if not good:
            if len(allv) >= 3 and len(set(allv)) == 1 and all(
                    p.startswith("uncertain") for _, p, _ in cands[st]):
                return allv[0], len(allv), 1      # several faint but identical reads
            return None
        v, c = Counter(good).most_common(1)[0]
        seen = Counter(allv)
        others = [n for val, n in seen.items() if val != v]
        n_alt = 1 + len(others)
        if others and seen[v] >= 3 and seen[v] >= 2 * max(others):
            n_alt = 1                              # clear majority
        return v, c, n_alt

    def small(st):
        return any(p == "small text" for _, p, _ in cands[st])

    max_level = {1: 0, 2: 1, 3: 2}[passes]
    for st in STATS:
        opinions(st, 0)
        lvl = 0
        while lvl < max_level:
            d = decide(st)
            # glyph reading clean on the first try -> done
            if d and lvl == 0 and d[1] >= 1 and not small(st):
                break
            # later: need two agreeing clean readings and no disagreement
            if d and lvl > 0 and d[1] >= 2 and d[2] == 1:
                break
            lvl += 1
            opinions(st, lvl)

    values, flags = {}, {}
    for st in STATS:
        d = decide(st)
        if d:
            values[st] = d[0]
            if d[2] > 1:
                flags[st] = "readings disagree: " + " / ".join(raws[st])
        elif cands[st]:
            values[st] = cands[st][0][0]
            flags[st] = cands[st][0][1] + " (readings: " + " / ".join(raws[st]) + ")"
        else:
            values[st], flags[st] = None, "unreadable"

    trio = ("accuracy", "shots_fired", "shots_hit")
    if values["shots_hit"] == 0 and values["shots_fired"] is not None and values["accuracy"] != 0.0 \
            and not flags.get("shots_fired") and not flags.get("shots_hit"):
        flags.pop("accuracy", None)          # nothing hit -> the game shows "0" / "0.0%"
        info_zero = f"set to 0.0 because no shot hit (read: {' / '.join(raws['accuracy'])})"
        values["accuracy"] = 0.0
    else:
        info_zero = None
    if not consistent(*(values[t] for t in trio)):
        for st in trio:                       # get every opinion we can
            have = {c[2] for c in cands[st]}
            for lvl in range(1, max_level + 1):
                if lvl == 1 and "glyph140" not in have or lvl == 2 and "tess" not in have:
                    opinions(st, lvl)
        opts = {}
        for st in trio:
            seen = []
            for v in [values[st]] + [v for v, _, _ in cands[st]]:
                if v is not None and v not in seen:
                    seen.append(v)
            opts[st] = seen
        fixed = next(((a, f, h) for a in opts["accuracy"] for f in opts["shots_fired"]
                      for h in opts["shots_hit"] if consistent(a, f, h)), None)
        if fixed:
            for st, v in zip(trio, fixed):
                if values[st] != v:
                    flags[st] = f"corrected to {v} by accuracy check (readings: " + " / ".join(raws[st]) + ")"
                values[st] = v
        else:
            # A number cut off on the left ("73" for "2,073"): rebuild it from the other two.
            a, f, h = (values[t] for t in trio)
            rebuilt = None
            if a and h and f is not None and a > 0:
                lo, hi = 100.0 * h / (a + 0.05), 100.0 * h / (a - 0.05) if a > 0.05 else 10 ** 7
                cand = [n for n in range(max(1, int(lo)), int(hi) + 2)
                        if consistent(a, n, h) and str(n).endswith(str(f)) and n != f]
                if len(cand) == 1:
                    rebuilt = ("shots_fired", cand[0])
            if rebuilt is None and a is not None and f and h is not None:
                lo, hi = a * f / 100.0 - 1, a * f / 100.0 + 1
                cand = [n for n in range(max(0, int(lo)), int(hi) + 2)
                        if consistent(a, f, n) and str(n).endswith(str(h)) and n != h]
                if len(cand) == 1:
                    rebuilt = ("shots_hit", cand[0])
            if rebuilt:
                st, v = rebuilt
                flags[st] = (f"only '{values[st]}' was readable (cut off) - rebuilt as {v} from accuracy; "
                             "please confirm")
                values[st] = v
                for o in trio:
                    if o != st and flags.get(o, "").startswith("accuracy"):
                        flags.pop(o)
            else:
                msg = f"accuracy {a}% doesn't match shots_hit {h} / shots_fired {f}"
                for st in trio:
                    flags[st] = flags.get(st) or msg
    else:
        for st in trio:                       # the cross-check confirms them
            if flags.get(st, "").startswith("readings disagree"):
                flags.pop(st)
    # a correction that passes the check is reliable: keep it as info only
    info = {st: m for st, m in flags.items() if m.startswith("corrected")}
    for st in info:
        flags.pop(st)
    if info_zero:
        info["accuracy"] = info_zero
    return values, flags, bands, info


# --------------------------------------------------------------------------
# File name -> deployment / mission / players
# --------------------------------------------------------------------------
@dataclass
class Shot:
    path: Path
    key: str            # deployment key, e.g. "Pengus_Yokai_Inky_Blahaj"
    number: int | None  # mission number from the file name, if any
    names: list[str]
    dep_id: str | None = None   # "D20241218052844" from the Google Sheets rename script
    copy: int = 0               # " (1)" copy mark added by Windows / Drive
    mission: int = 0
    note: str = ""
    uploader: str = ""          # " - Name" added by Google Forms
    time: float | None = None   # capture time from "Screenshot 2024-12-18 154805", else file time


DEP_ID_RE = re.compile(r"^(D\d{14})[\s_\-]+(.*)$", re.IGNORECASE)


def parse_filename(path: Path) -> Shot:
    stem = path.stem.strip()
    copy = 0
    # " (1)" copy marks added by Windows / Drive when two files have the same name.
    # (A lone "(2)" right after the squad names is a mission number, not a copy mark.)
    m = re.match(r"^(.*\S)\s*\((\d{1,2})\)$", stem)
    if m and (re.search(r"\s-\s", m.group(1)) or re.search(r"[_\s\-]\d{1,2}$", m.group(1))):
        stem, copy = m.group(1), int(m.group(2))
    parts = re.split(r"\s+-\s+", stem)  # "Squad_1 - Uploader Name" (re-uploads: "Squad_1 - A - B")
    stem, uploader = parts[0], (re.sub(r"\(\d+\)$", "", parts[-1]).strip() if len(parts) > 1 else "")
    stem = re.sub(r"\.(png|jpe?g|webp|bmp|gif|tiff?)$", "", stem.strip(), flags=re.I)  # "x_1.png - y.png"
    stem = stem.strip().strip("_- ")
    shot_time = None
    m = re.search(r"(20\d\d)[-_.](\d\d)[-_.](\d\d)[ _-]?(\d\d)(\d\d)(\d\d)", stem)
    has_stamp = bool(m)
    if m:
        try:
            shot_time = datetime.datetime(*map(int, m.groups())).timestamp()
        except ValueError:
            shot_time = None
    if shot_time is None:
        try:
            shot_time = path.stat().st_mtime
        except OSError:
            shot_time = None
    dep_id = None
    m = DEP_ID_RE.match(stem)
    if m:
        dep_id, stem = m.group(1).upper(), m.group(2)
    m = None if has_stamp else re.match(r"^(.*?)[\s_\-]*\(?(\d{1,2})\)?$", stem)
    if m and m.group(1):
        base, num = m.group(1), int(m.group(2))
    else:
        base, num = stem, None
    base = re.sub(r"[\s\-]+", "_", base).strip("_")
    names = [n for n in base.split("_") if n]
    key = (f"{dep_id}_" if dep_id else "") + base + (f"#{copy + 1}" if copy else "")
    note = ("file name has a copy mark ' (n)': treated as another deployment of the same squad - "
            "check it (the Google Sheets rename script makes this exact)") if copy else ""
    if has_stamp or len(names) <= 2:
        names = []   # e.g. "Screenshot 2024-12-18 154805": no callsigns in the name
    return Shot(path, key, num, names, dep_id, copy, note=note, uploader=uploader, time=shot_time)


def group_shots(paths):
    groups: dict[str, list[Shot]] = defaultdict(list)
    for p in paths:
        s = parse_filename(p)
        groups[s.key.lower()].append(s)

    # Same squad + same mission number twice (two deployments, no ID in the file name):
    # split them into separate deployments instead of mixing them, and say so.
    split_note = ("same squad and mission number found more than once: split into separate deployments "
                  "by file name order - check they belong together (the Google Sheets rename script "
                  "makes this exact)")
    final: dict[str, list[Shot]] = defaultdict(list)
    for _, shots in groups.items():
        shots.sort(key=lambda s: (s.number or 1, s.path.name))
        seen: Counter = Counter()
        for s in shots:
            seen[s.number or 1] += 1
        was_split = max(seen.values()) > 1
        seen = Counter()
        for s in shots:
            n = s.number or 1
            seen[n] += 1
            if seen[n] > 1:
                s.key = f"{s.key}#{seen[n]}"
            if was_split and not s.note:
                s.note = split_note
            final[s.key.lower()].append(s)
    out = {}
    for _, shots in final.items():
        shots.sort(key=lambda s: (s.number if s.number is not None else 0, s.path.name))
        for i, s in enumerate(shots, 1):
            s.mission = i
        out[shots[0].key] = shots
    return out


# --------------------------------------------------------------------------
# Optional: Google Form export
# --------------------------------------------------------------------------
FORM_COLUMNS = {
    "host": ["Host Callsign", "Host"],
    "a1": ["Attendee 1 Callsign", "Attendee 1"],
    "a2": ["Attendee 2 Callsign", "Attendee 2"],
    "a3": ["Attendee 3 Callsign", "Attendee 3"],
    "date": ["Operation starting date", "Operation Start Time", "OperationStartTime", "Date"],
    "time": ["Operation starting time"],
    "timestamp": ["Timestamp"],
    "difficulty": ["Difficulty"],
    "front": ["Enemy", "Front", "Faction"],
    "planet": ["Planet"],
    "operation": ["Operation Name", "Operation"],
    "notes": ["Any notes", "Notes"],
    "success": ["Operation Success", "Success"],
    "affected": ["Were any of your missions affected", "Crashed missions", "Crashes"],
    "raid": ["Raid", "Was this a raid", "Raid deployment"],
}
# Columns that are read on purpose. Everything else in the form (e-mail address, suggestions...)
# is ignored and never copied to the outputs.

DISPLAY_TZ = "Europe/Paris"   # time zone used to show Discord <t:...> timestamps (change with --timezone)
DISCORD_TS = re.compile(r"<t:(-?\d{9,11})(?::[tTdDfFR])?>")


def set_timezone(name: str):
    global DISPLAY_TZ
    DISPLAY_TZ = name


def _naive(t):
    """Any timestamp -> naive local time (time-zone-aware values are converted to DISPLAY_TZ first)."""
    import pandas as pd
    try:
        t = pd.Timestamp(t)
    except Exception:
        return pd.NaT
    if pd.isna(t):
        return pd.NaT
    if t.tzinfo is not None:
        try:
            t = t.tz_convert(DISPLAY_TZ)
        except Exception:
            pass
        t = t.tz_localize(None)
    return t


_GMT_OFFSET = re.compile(r"\s*(?:GMT|UTC)\s*([+-])(\d{1,2})(?::?(\d{2}))?\s*$", re.I)


def parse_when(v, dayfirst=False):
    """Text date -> naive local time. Handles Google's 'GMT+1' suffix with the right sign
    (pandas would read 'GMT+1' as the POSIX zone Etc/GMT+1 = UTC-1)."""
    import pandas as pd
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return pd.NaT
    if not isinstance(v, str):
        return _naive(v)
    s = v.strip()
    if re.match(r"\d{4}", s):
        dayfirst = False          # 2026-10-25 / 2026/10/25: year first is never day-first
    m = _GMT_OFFSET.search(s)
    try:
        if m:
            t = pd.to_datetime(s[:m.start()], errors="coerce", dayfirst=dayfirst)
            if pd.isna(t):
                return pd.NaT
            off = int(m.group(2)) * 60 + int(m.group(3) or 0)
            off = off if m.group(1) == "+" else -off
            t = _naive(t).tz_localize(datetime.timezone(datetime.timedelta(minutes=off)))
            return _naive(t)
        return _naive(pd.to_datetime(s, errors="coerce", dayfirst=dayfirst))
    except Exception:
        return pd.NaT


def parse_op_date(v):
    """Operation start from the form: Discord timestamp '<t:1734098400:F>', a bare unix time, or a
    normal date. Returns (naive local Timestamp or NaT, problem text)."""
    import pandas as pd
    if v is None or (not isinstance(v, str) and pd.isna(v)) or str(v).strip() == "":
        return pd.NaT, ""
    if isinstance(v, (pd.Timestamp,)) or hasattr(v, "year"):
        return _naive(v), ""
    s = str(v).strip()
    m = DISCORD_TS.search(s) or re.fullmatch(r"(\d{10})(?:\.0)?", s)
    if m:
        try:
            t = pd.Timestamp(int(m.group(1)), unit="s", tz="UTC")
            try:
                t = t.tz_convert(DISPLAY_TZ)
            except Exception:
                pass  # unknown time zone name -> keep UTC
            return t.tz_localize(None), ""
        except Exception:
            pass
    t = parse_when(s, dayfirst=not s[:4].isdigit())
    if pd.isna(t):
        return pd.NaT, f"start date '{s[:40]}' not understood (expected <t:XXXXXXXXXX:F>), used the submission time"
    return t, ""


def _norm(c) -> str:
    return re.sub(r"\W", "", str(c)).lower()


def _read_table(path: Path, preferred_sheet: str | None = None):
    import pandas as pd
    if path.suffix.lower() in (".xlsx", ".xlsm", ".xls"):
        xl = pd.ExcelFile(path)
        name = next((n for n in xl.sheet_names if preferred_sheet and n.lower() == preferred_sheet.lower()),
                    None)
        if name is None and preferred_sheet:
            return None
        return pd.read_excel(xl, name or xl.sheet_names[0])
    return pd.read_csv(path)


def load_form(path: Path | None):
    """Read the Google Form answers (.csv, or .xlsx incl. the whole registry workbook)."""
    if not path:
        return []
    import pandas as pd
    if not path.exists():
        print(f"Form file not found: {path}")
        return []
    df = None
    if path.suffix.lower() in (".xlsx", ".xlsm", ".xls"):
        xl = pd.ExcelFile(path)
        sheet = next((n for n in xl.sheet_names if n.lower().startswith("form responses")), xl.sheet_names[0])
        df = pd.read_excel(xl, sheet)
        print(f"Form: reading sheet '{sheet}'")
    else:
        df = pd.read_csv(path)
    norm = {_norm(c): c for c in df.columns}

    def col(key):
        for cand in FORM_COLUMNS[key]:                  # exact header first ...
            if _norm(cand) in norm:
                return norm[_norm(cand)]
        for cand in FORM_COLUMNS[key]:                  # ... then "header starts with"
            for k, c in norm.items():
                if k.startswith(_norm(cand)):
                    return c
        return None

    cols = {k: col(k) for k in FORM_COLUMNS}
    rows = []
    for idx, r in df.iterrows():
        def get(k):
            c = cols[k]
            v = r[c] if c is not None else ""
            return "" if (not isinstance(v, str) and pd.isna(v)) else v
        names = [str(get(k)).strip() for k in ("host", "a1", "a2", "a3") if str(get(k)).strip()]
        if not names:
            continue
        ts = parse_when(get("timestamp")) if get("timestamp") != "" else pd.NaT
        date, date_problem = parse_op_date(get("date"))
        tv = get("time")
        if pd.notna(date) and tv != "" and date == date.normalize():   # date and time in two columns
            try:
                if hasattr(tv, "hour"):
                    date = date + pd.Timedelta(hours=tv.hour, minutes=tv.minute)
                else:
                    tt = pd.to_datetime(str(tv), errors="coerce")
                    if pd.notna(tt):
                        date = date + pd.Timedelta(hours=tt.hour, minutes=tt.minute)
            except Exception:
                pass
        if pd.notna(date) and pd.notna(ts) and (date > ts + pd.Timedelta(days=1) or date < ts - pd.Timedelta(days=30)):
            date_problem = (f"start date {date:%Y-%m-%d} doesn't fit the submission ({ts:%Y-%m-%d}) - "
                            "probably a typo, used the submission time")
            date = pd.NaT
        if pd.isna(date) and not date_problem and get("date") == "":
            date_problem = "no start date in the form, used the submission time" if pd.notna(ts) else ""
        rows.append(dict(row=idx + 2, names=names,
                         ts=ts, date=date if pd.notna(date) else (ts if pd.notna(ts) else pd.NaT),
                         date_problem=date_problem,
                         difficulty=get("difficulty"), front=str(get("front")).strip(),
                         planet=str(get("planet")).strip(), operation=str(get("operation")).strip(),
                         success=str(get("success")).strip(), affected=str(get("affected")).strip(),
                         raid=str(get("raid")).strip(),
                         form_notes=str(get("notes")).strip()))
    print(f"Form: {len(rows)} answers read from {path.name}")
    return rows


PLANET_NAMES: list = []     # planet names as written (for reading register screenshots)


def load_planets(path: Path | None) -> dict:
    """Planet -> sector, from the 'PlanetsAndSectors' tab of the registry workbook, else from
    google_apps_script/planets_and_sectors.tsv. Also fills PLANET_NAMES."""
    pairs = []
    if path and path.exists() and path.suffix.lower() in (".xlsx", ".xlsm", ".xls"):
        try:
            df = _read_table(path, "PlanetsAndSectors")
            if df is not None and df.shape[1] >= 2:
                pairs = [(str(p).strip(), str(sct).strip()) for p, sct in zip(df.iloc[:, 0], df.iloc[:, 1])
                         if str(p).strip() and str(p) != "nan"]
        except Exception:
            pairs = []
    if not pairs:
        tsv = Path(__file__).resolve().parent / "google_apps_script" / "planets_and_sectors.tsv"
        if tsv.exists():
            for line in tsv.read_text(encoding="utf-8").splitlines()[1:]:
                parts = line.split("\t")
                if parts and parts[0].strip():
                    pairs.append((parts[0].strip(), parts[1].strip() if len(parts) > 1 else ""))
    PLANET_NAMES[:] = [p for p, _ in pairs]
    return {p.lower(): sct for p, sct in pairs}


RANKS = {"pvt", "pfc", "spc", "cpl", "sgt", "ssg", "sfc", "msg", "sg", "csm", "sgm", "lt", "cpt", "maj",
         "col", "gen", "th", "the", "level", "and"}


def name_tokens(name: str) -> set[str]:
    """Callsign-ish tokens of a name: '505'th | Hawkeye | CPL-3786' -> {'hawkeye'},
    'SPC-1648 "Roach"' -> {'roach'}, 'Dalua_Pira11' -> {'dalua', 'pira', 'daluapira'}."""
    if not name or str(name) == "nan":
        return set()
    s = str(name)
    q = re.findall(r'["\u201c\u201d\u00ab\u00bb]([^"\u201c\u201d\u00ab\u00bb]{2,})["\u201c\u201d\u00ab\u00bb]', s)
    if q:
        s = " ".join(q)
    out = set()
    for part in re.split(r"[|\[\]()<>,/\\]+", s):
        words = [letters(w).lower() for w in re.split(r"[\s_.\-']+", part)]
        words = [w for w in words if len(w) >= 3 and w not in RANKS]
        out.update(words)
        joined = letters(re.sub(r"\d+", " ", part)).lower()   # "2-E-E-T-O" -> "eeto"
        if len(joined) >= 3 and joined not in RANKS:
            out.add(joined)
    return out


def tokens_match(a: str, b: str) -> bool:
    if a == b:
        return True
    if min(len(a), len(b)) >= 4 and (a in b or b in a):
        return True
    return min(len(a), len(b)) >= 4 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def callsign_hits(callsigns: list[str], tokens: set[str]) -> int:
    hits = 0
    for c in callsigns:
        ct = name_tokens(c)
        if ct and any(tokens_match(x, y) for x in ct for y in tokens):
            hits += 1
    return hits


def assign_form(groups: dict, form_rows: list, tokens: dict) -> dict:
    """Link every deployment to its form answer -> {key: (form row or None, note)}.

    1. Deployment ID in the file name (Google Sheets rename script): exact.
    2. Otherwise callsigns: names in the file name + names read on screen, best score wins;
       ties are broken by time (screenshot time vs. operation date, or upload time vs. submission).
       Each form answer is used once.
    """
    import pandas as pd
    out, used = {}, set()
    pending = []
    by_row = {f["row"]: f for f in form_rows}
    for key, shots in groups.items():          # forced by hand in corrections.csv
        forced = next((FORM_OVERRIDES[s.path.name] for s in shots if s.path.name in FORM_OVERRIDES), None)
        if forced is not None:
            fr = by_row.get(forced)
            out[key] = (fr, "linked by hand (corrections.csv)" if fr else f"form row {forced} not found")
            if fr:
                used.add(fr["row"])
    for key, shots in groups.items():
        if key in out:
            continue
        s0 = shots[0]
        if s0.dep_id:
            want = pd.to_datetime(s0.dep_id[1:], format="%Y%m%d%H%M%S")
            fr = next((f for f in form_rows if pd.notna(f["ts"]) and abs((f["ts"] - want).total_seconds()) <= 1.5),
                      None)
            out[key] = (fr, "" if fr else f"deployment ID {s0.dep_id} not found in the form answers")
            if fr:
                used.add(fr["row"])
        else:
            pending.append(key)

    cands = []
    for key in pending:
        shots = groups[key]
        toks = set(tokens.get(key, set()))
        for n in shots[0].names:
            toks |= name_tokens(n)
        times = [s.time for s in shots if s.time]
        t = min(times) if times else None
        from_name = any(re.search(r"20\d\d[-_.]\d\d[-_.]\d\d", s.path.stem) for s in shots)
        fname = letters(" ".join(s.path.stem.split(" - ")[0] for s in shots[:1])).lower()
        for fr in form_rows:
            hits = callsign_hits(fr["names"], toks)
            # operation name written in the file name ("Dalua_OperationRiddle_1")
            op = letters(re.sub(r"(?i)\boperation\b|\bop\b", " ", fr.get("operation", ""))).lower()
            op_hit = len(op) >= 4 and (op in fname or (len(fname) >= 4 and difflib.SequenceMatcher(
                None, op, fname.replace("operation", "")).ratio() >= 0.8))
            # screenshot taken during the operation (time in the file name)
            time_hit = False
            dt = 9e9
            if t is not None:
                ref = fr["date"] if from_name else fr["ts"]
                if pd.notna(ref):
                    dt = abs(pd.Timestamp(ref).timestamp() - t)
                    if from_name:
                        delta = t - pd.Timestamp(fr["date"]).timestamp() if pd.notna(fr["date"]) else 9e9
                        time_hit = -3600 <= delta <= 6 * 3600
            score = hits + (2 if op_hit else 0) + (1 if time_hit else 0)
            if hits >= 2 or (hits >= 1 and (op_hit or time_hit)) or op_hit:
                cands.append((-score, dt, key, fr))
    cands.sort(key=lambda c: (c[0], c[1]))
    best_hits = {}
    for h, dt, key, fr in cands:
        best_hits.setdefault(key, -h)
    for h, dt, key, fr in cands:
        if key in out or fr["row"] in used:
            continue
        rivals = [c for c in cands if c[2] == key and -c[0] == -h and c[3]["row"] != fr["row"]]
        note = ""
        if rivals:
            note = (f"{len(rivals) + 1} form answers fit this squad - picked the closest in time (form row "
                    f"{fr['row']}); check it")
        out[key] = (fr, note)
        used.add(fr["row"])
    for key in pending:
        out.setdefault(key, (None, "no matching form answer (callsigns on screen / in the file name "
                                   "don't match any answer)"))
    return out


def clean_callsign(c: str) -> str:
    q = re.findall(r'["\u201c\u201d]([^"\u201c\u201d]{2,})["\u201c\u201d]', str(c))
    return q[0].strip() if q else str(c).strip()


def infer_aliases(df, links: dict, roster) -> int:
    """Learn in-game names from repetition: if an in-game name shows up in 2+ deployments and only one
    callsign (not already taken by another name) is in every one of their form answers, that's its
    callsign. Repeats until nothing new is found. Returns how many names were learned."""
    from players import norm
    deps = {k: [clean_callsign(c) for c in fr["names"] if clean_callsign(c)] for k, (fr, _) in links.items() if fr}
    if not deps:
        return 0
    seen = {}
    for key in deps:
        sub = df[df["deployment"] == key]
        seen[key] = list(dict.fromkeys(str(o) for o in sub["ocr_name"].astype(object).fillna("") if len(norm(o)) >= 3))

    def resolve(o, calls):
        cs = roster.callsign_for(o)
        if cs:
            return cs
        ot = name_tokens(o)
        for c in calls:
            ct = name_tokens(c)
            if ct and ot and any(tokens_match(x, y) for x in ct for y in ot):
                return c
        return None

    learned = 0
    for _ in range(10):
        cand: dict[str, list] = {}
        for key, calls in deps.items():
            claimed = {norm(r) for o in seen[key] if (r := resolve(o, calls))}
            free = {norm(c): c for c in calls if norm(c) not in claimed}
            for o in seen[key]:
                if resolve(o, calls):
                    continue
                k = norm(o)
                if k in cand:
                    cand[k][0] &= set(free)
                    cand[k][1] += 1
                else:
                    cand[k] = [set(free), 1, o, dict(free)]
                cand[k][3].update(free)
        new = 0
        for k, (cs_set, n, raw, names) in cand.items():
            if n >= 2 and len(cs_set) == 1:
                if roster.learn(raw, names[next(iter(cs_set))]):
                    new += 1
        learned += new
        if not new:
            break
    return learned


def short_match(a: str, b: str) -> bool:
    """3-letter callsigns: 'tea' matches the in-game name 'inktea' / 'teabag' (start or end only)."""
    a, b = (a, b) if len(a) <= len(b) else (b, a)
    return len(a) == 3 and len(b) > 3 and (b.startswith(a) or b.endswith(a))


def trust_form_order() -> bool:
    """settings.json "trust_form_order" (default on): hosts type the callsigns in the order the players appear
    on the stat screen, left to right - so a full squad is named by position without asking."""
    return bool(load_settings().get("trust_form_order", True))


def name_players(mrows, callsigns: list[str], roster=None, uploader: str = "",
                 trust_order: bool | None = None) -> tuple[dict, dict]:
    """Map the rows of one mission (one per panel) to callsigns -> ({row index: callsign}, {row index: how}).

    1. players.csv: the in-game name read on screen is a known name of a callsign ("alias")
    2. the in-game name looks like one of the form's callsigns ("name")
    2a. same number of panels as callsigns and trust_form_order on: panel k = k-th callsign of the form
        ("form" - the hosts' rule: callsigns typed in screenshot order). Names on screen still win.
    2b. the panel without a name = the screenshot taker: uploader (players.csv) or the host
    3. one panel and one callsign left -> they go together ("last")
    4. several left: panel order = form order ("order", a guess - it goes to corrections.csv)
    File names are not used: players can name their screenshots anything."""
    calls = [clean_callsign(c) for c in callsigns if clean_callsign(c)]
    out, how = {}, {}
    used = set()
    if roster is not None:
        for idx, r in mrows.iterrows():
            cs = roster.callsign_for(r.get("ocr_name", ""))
            if not cs:
                continue
            match = next((c for c in calls if norm_cs(c) == norm_cs(cs)), None)
            out[idx], how[idx] = (match or cs), "alias"
            if match:
                used.add(norm_cs(match))
    pairs = []
    for idx, r in mrows.iterrows():
        if idx in out:
            continue
        rt = name_tokens(r.get("ocr_name", ""))
        if not rt:
            continue
        for j, c in enumerate(calls):
            if norm_cs(c) in used:
                continue
            ct = name_tokens(c)
            if ct and any(tokens_match(x, y) or short_match(x, y) for x in ct for y in rt):
                pairs.append((idx, j))
    taken_c = set()
    for idx, j in pairs:
        if idx not in out and j not in taken_c:
            out[idx], how[idx] = calls[j], "name"
            taken_c.add(j)
            used.add(norm_cs(calls[j]))
    if trust_order is None:
        trust_order = trust_form_order()
    if trust_order and calls and len(mrows) == len(calls):
        for k, i in enumerate(sorted(mrows.index, key=lambda i: mrows.at[i, "slot"])):
            if i in out or norm_cs(calls[k]) in used:
                continue                       # recognised by name, or that callsign is already on another panel
            out[i], how[i] = calls[k], "form"
            used.add(norm_cs(calls[k]))
    # the panel without a name is the player who took the screenshot: the uploader if players.csv knows
    # them, else the host (whoever fills in the form is usually the host) if the host isn't on screen
    for idx, r in mrows.iterrows():
        if idx in out or str(r.get("ocr_name") or "").strip() not in ("", "nan"):
            continue
        me = roster.callsign_for(uploader) if (roster is not None and uploader) else None
        if me and norm_cs(me) not in used:
            match = next((c for c in calls if norm_cs(c) == norm_cs(me)), me)
            out[idx], how[idx] = match, "self"
            used.add(norm_cs(match))
        elif not uploader and calls and norm_cs(calls[0]) not in used:
            out[idx], how[idx] = calls[0], "host"
            used.add(norm_cs(calls[0]))
        break
    rest_rows = [i for i in mrows.index if i not in out]
    rest_calls = [c for c in calls if norm_cs(c) not in used]
    if rest_rows and len(rest_rows) == len(rest_calls):
        tag = "last" if len(rest_rows) == 1 else "order"
        for i, c in zip(sorted(rest_rows, key=lambda i: mrows.at[i, "slot"]), rest_calls):
            out[i], how[i] = c, tag
    return out, how


def norm_cs(c) -> str:
    return re.sub(r"[^a-z0-9]", "", str(c).lower())


# --------------------------------------------------------------------------
# Hand corrections (corrections.csv next to the script)
# --------------------------------------------------------------------------
CORR_COLUMNS = ["file", "slot", "player", "stat", "value_read", "correct_value", "readings", "screenshot"]
FORM_OVERRIDES: dict = {}      # file name -> form row number, from corrections.csv (stat = form_row)
REGISTER_FIELDS = ("operation", "date", "planet", "front", "difficulty", "players", "register_id")
REGISTER_OVERRIDES: dict = {}  # (register screenshot, field) -> value typed in corrections.csv
PLAYER_OVERRIDES: dict = {}    # (file, slot) -> callsign typed in corrections.csv (stat = player)


def corrections_path() -> Path:
    return Path(__file__).resolve().parent / "corrections.csv"


def load_corrections(path: Path) -> list[dict]:
    import csv
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        return [{k.strip().lower(): (v or "").strip() for k, v in r.items() if k} for r in csv.DictReader(f, dialect=dialect)]


def _num(v: str, stat: str):
    t = v.replace(" ", "").replace("%", "")
    if stat == "accuracy":
        t = t.replace(",", ".")
        return float(t)
    return int(re.sub(r"[.,]", "", t))


def apply_corrections(all_rows: list, corr: list[dict]) -> int:
    """Apply filled-in lines of corrections.csv to the rows. Returns how many were applied."""
    FORM_OVERRIDES.clear()
    REGISTER_OVERRIDES.clear()
    PLAYER_OVERRIDES.clear()
    by_key = {(r["file"], str(r["slot"])): r for r in all_rows}
    applied = 0
    for c in corr:
        val, stat = c.get("correct_value", ""), c.get("stat", "").strip().lower()
        if not val or not c.get("file"):
            continue
        if stat == "form_row":
            try:
                FORM_OVERRIDES[c["file"]] = int(float(val))
                applied += 1
            except ValueError:
                print(f"corrections.csv: '{val}' is not a form row number ({c['file']})")
            continue
        if stat in REGISTER_FIELDS:                 # a value of a register screenshot
            REGISTER_OVERRIDES[(c["file"], stat)] = val
            applied += 1
            continue
        r = by_key.get((c["file"], str(c.get("slot", "")).split(".")[0]))
        if r is None:
            continue
        if stat == "image":
            r["image_check"] = ""
            applied += 1
            continue
        if stat == "player":                         # who this panel is (callsign), used when naming
            PLAYER_OVERRIDES[(c["file"], str(c.get("slot", "")).split(".")[0])] = val
            applied += 1
            continue
        if stat not in STATS:
            print(f"corrections.csv: unknown stat '{stat}' ({c['file']})")
            continue
        if val.lower() in ("ok", "yes", "y", "correct", "confirmed"):
            what = f"{stat}: confirmed by hand"
        else:
            try:
                r[stat] = _num(val, stat)
            except ValueError:
                print(f"corrections.csv: '{val}' is not a number ({c['file']}, {stat})")
                continue
            what = f"{stat}: corrected by hand to {val}"
        flagged = [x for x in str(r.get("flagged_stats") or "").split(", ") if x and x != stat]
        r["flagged_stats"] = ", ".join(flagged)
        notes = [n for n in str(r.get("notes") or "").split(" | ") if n and not n.startswith(stat + ":")]
        r["notes"] = " | ".join(notes + [what])
        applied += 1
    return applied


def update_corrections_file(path: Path, all_rows: list, corr: list[dict], sources: dict | None = None,
                            extra: list | None = None) -> int:
    """Add a line for every value still flagged (correct_value left empty). Returns open lines.
    `sources`: file name -> full path of the screenshot, shown in the 'screenshot' column."""
    import csv
    sources = sources or {}

    def where(name):
        p = sources.get(name)
        return str(p.resolve()) if p else ""

    # answered lines are kept (they are the hand fixes); unanswered ones are rebuilt from this run, so a
    # question that no longer applies (name now recognised, screenshot gone) disappears by itself
    corr = [c for c in corr if str(c.get("correct_value", "")).strip()]
    have = {(c.get("file"), str(c.get("slot", "")).split(".")[0], c.get("stat", "").lower()) for c in corr}
    rows = []
    for c in corr:
        r = {k: c.get(k, "") for k in CORR_COLUMNS}
        r["screenshot"] = where(r["file"]) or c.get("screenshot", "") or c.get("picture", "")
        rows.append(r)
    for r in sorted(all_rows, key=lambda r: (r["file"], r["slot"])):
        notes = {n.split(":", 1)[0]: n.split(":", 1)[1].strip() for n in str(r.get("notes") or "").split(" | ")
                 if ":" in n}
        for st in [x for x in str(r.get("flagged_stats") or "").split(", ") if x]:
            k = (r["file"], str(r["slot"]), st)
            if k in have:
                continue
            m = re.search(r"readings: ([^)]*)", notes.get(st, ""))
            rows.append(dict(file=r["file"], slot=r["slot"], player=r.get("player", ""), stat=st,
                             value_read=r.get(st, ""), correct_value="",
                             readings=m.group(1) if m else notes.get(st, "")[:80],
                             screenshot=where(r["file"])))
            have.add(k)
    for e in extra or []:                           # register fields / player names to check
        k = (e["file"], str(e.get("slot", "")), e["stat"])
        if k in have:
            continue
        rows.append(dict(file=e["file"], slot=e.get("slot", ""), player=e.get("player", "register"), stat=e["stat"],
                         value_read=e.get("value_read", ""), correct_value="", readings=e.get("readings", ""),
                         screenshot=where(e["file"])))
        have.add(k)
    try:
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CORR_COLUMNS)
            w.writeheader()
            w.writerows(rows)
    except PermissionError:
        print(f"Could not update {path.name} - is it open in another program? Close it and run again.")
    return sum(1 for r in rows if not str(r.get("correct_value", "")).strip())


def regroup(all_rows: list, groups: dict) -> tuple[dict, dict]:
    """Merge screenshots of one deployment that ended up in different groups
    ('Screenshot 2024-...' files, names in a different order, a player missing from one name).
    Same uploader + same squad on screen + no clashing mission numbers + close in time.
    Returns (new groups, {key: on-screen name tokens, key+'#n': players})."""
    rows_by_file = defaultdict(list)
    for r in all_rows:
        rows_by_file[r["file"]].append(r)

    def squad(shots):
        names = []
        for s in shots:
            for r in rows_by_file.get(s.path.name, []):
                names.append(name_tokens(r.get("ocr_name", "")) | name_tokens(r.get("player", "")))
        return names

    keys = list(groups)
    info = {}
    for k in keys:
        shots = groups[k]
        slot_sets = squad(shots)
        times = [s.time for s in shots if s.time]
        info[k] = dict(slots=slot_sets, up=shots[0].uploader.lower(), t=min(times) if times else None,
                       nums={s.number for s in shots if s.number is not None},
                       unnamed=not shots[0].names, dep=shots[0].dep_id)

    def overlap(a, b):
        hits = 0
        for sa in {frozenset(x) for x in a if x}:
            if any(any(tokens_match(x, y) for x in sa for y in sb) for sb in b if sb):
                hits += 1
        return hits

    parent = {k: k for k in keys}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    order = sorted(keys, key=lambda k: (info[k]["t"] or 0))
    for i, a in enumerate(order):
        for b in order[i + 1:]:
            A, B = info[a], info[b]
            if A["dep"] or B["dep"] or A["up"] != B["up"]:
                continue
            if A["t"] and B["t"] and abs(A["t"] - B["t"]) > 6 * 3600:
                continue
            ra, rb = find(a), find(b)
            if ra == rb:
                continue
            members_a = [k for k in keys if find(k) == ra]
            members_b = [k for k in keys if find(k) == rb]
            nums_a = set().union(*(info[k]["nums"] for k in members_a))
            nums_b = set().union(*(info[k]["nums"] for k in members_b))
            if nums_a & nums_b:
                continue
            slots_a = [x for k in members_a for x in info[k]["slots"]]
            slots_b = [x for k in members_b for x in info[k]["slots"]]
            n_a = len({frozenset(x) for x in slots_a if x})
            n_b = len({frozenset(x) for x in slots_b if x})
            # one image covers 3-4 players; slot sets repeat across missions, so compare per image
            ov = overlap(info[a]["slots"], info[b]["slots"])
            per_img = min(len(info[a]["slots"]) // max(1, len(groups[a])), len(info[b]["slots"]) // max(1, len(groups[b])))
            if per_img and ov >= max(2, per_img - 1) and n_a and n_b:
                parent[rb] = ra

    merged = defaultdict(list)
    for k in keys:
        merged[find(k)].append(k)
    new_groups, tokens = {}, {}
    for root, members in merged.items():
        shots = [s for k in members for s in groups[k]]
        named = [k for k in members if groups[k][0].names]
        if len(members) == 1:
            key = root
        else:
            base = max(named, key=lambda k: len(groups[k][0].names)) if named else None
            if base:
                key = base
            else:
                first = rows_by_file.get(shots[0].path.name, [])
                nm = "_".join(letters(r.get("ocr_name") or r.get("player") or "")[:14] or "X" for r in first) or "Unknown"
                tt = min((s.time for s in shots if s.time), default=None)
                key = nm + (datetime.datetime.fromtimestamp(tt).strftime("_%Y%m%d_%H%M") if tt else "")
            note = (f"put together from {len(shots)} files with different names "
                    f"({', '.join(sorted({s.path.name for s in shots}))[:300]}) - same uploader, same squad on screen")
            for s in shots:
                s.note = s.note or note
        names = max((groups[k][0].names for k in members), key=len)
        all_numbered = all(s.number is not None for s in shots) and len({s.number for s in shots}) == len(shots)
        shots.sort(key=lambda s: ((s.number, 0) if all_numbered else (s.time or 0, s.number or 0)), )
        for i, s in enumerate(shots, 1):
            s.key, s.mission, s.names = key, i, names if names else s.names
        new_groups[key] = shots
        toks = set()
        for x in squad(shots):
            toks |= x
        tokens[key] = toks
        tokens[key + "#n"] = max((len(rows_by_file.get(s.path.name, [])) for s in shots), default=0)
    # push the new deployment / mission numbers into the rows
    by_file = {s.path.name: s for shots in new_groups.values() for s in shots}
    for r in all_rows:
        s = by_file.get(r["file"])
        if s:
            r["deployment"], r["mission"] = s.key, s.mission
    return new_groups, tokens


# --------------------------------------------------------------------------
# Register screenshots (Phoenix bot "Deployment Register" embed)
# --------------------------------------------------------------------------
def apply_register_overrides(file: str, reg: dict) -> dict:
    """Register + hand corrections from corrections.csv; 'problems' keeps only what is still open."""
    reg = dict(reg)
    fixed = set()
    for field in REGISTER_FIELDS:
        val = REGISTER_OVERRIDES.get((file, field))
        if val is None:
            continue
        fixed.add(field)
        if val.lower() in ("ok", "yes", "y", "correct", "confirmed"):
            continue
        if field == "players":
            reg["names"] = [n.strip() for n in re.split(r"[,;/]", val) if n.strip()]
        elif field == "date":
            from register_reader import parse_date
            d = parse_date(val)
            if d is None:
                import pandas as pd
                t = pd.to_datetime(val, errors="coerce", dayfirst=not val.strip()[:4].isdigit())
                d = None if pd.isna(t) else t.to_pydatetime()
            if d is None:
                print(f"corrections.csv: date '{val}' not understood ({file})")
                fixed.discard(field)
                continue
            reg["date"] = d.strftime("%Y-%m-%d %H:%M")
        elif field == "difficulty":
            reg["difficulty"] = re.sub(r"\D", "", val) or reg.get("difficulty", "")
        else:
            reg[field] = val
    reg["problems"] = [tuple(p) for p in reg.get("problems", []) if p[0] not in fixed]
    return reg


def attach_registers(groups: dict, tokens: dict, registers: dict, orig_key: dict) -> tuple[dict, list]:
    """Link every register screenshot to its deployment -> ({group key: (register, file, note)}, problems).
    1. same deployment ID (Google rename script: all 4 uploads of one form answer share it)
    2. same file-name group  3. callsigns of the register vs. names read on the stat screens."""
    out, unattached = {}, []
    dep_of = {k: g[0].dep_id for k, g in groups.items()}
    keys_of = {k: {orig_key.get(s.path.name, "").lower() for s in g} for k, g in groups.items()}
    taken = set()
    for file, (shot, reg) in sorted(registers.items()):
        key = None
        if shot.dep_id:
            key = next((k for k, d in dep_of.items() if d == shot.dep_id), None)
        if key is None:
            key = next((k for k, ks in keys_of.items() if shot.key.lower() in ks), None)
        if key is None:
            best = []
            for k in groups:
                if k in taken:
                    continue
                hits = callsign_hits(reg.get("names", []), tokens.get(k, set()))
                if hits >= 2:
                    times = [s.time for s in groups[k] if s.time]
                    dt = abs(min(times) - shot.time) if times and shot.time else 9e9
                    best.append((-hits, dt, k))
            if best:
                key = sorted(best)[0][2]
        if key is None:
            unattached.append(file)
            continue
        if key in out:              # two registers for one deployment: keep the first, say so
            prev = out[key]
            out[key] = (prev[0], prev[1], (prev[2] + "; " if prev[2] else "") +
                        f"another register screenshot ({file}) also fits this deployment")
            continue
        out[key] = (reg, file, "")
        taken.add(key)
    by_id = defaultdict(list)
    for k, (reg, file, _) in out.items():
        if reg.get("register_id"):
            by_id[reg["register_id"]].append(k)
    for rid, ks in by_id.items():
        if len(ks) > 1:
            for k in ks:
                reg, file, note = out[k]
                out[k] = (reg, file, (note + "; " if note else "") +
                          f"Register #{rid} is also used by {', '.join(x for x in ks if x != k)} - submitted twice?")
    return out, unattached


def register_as_form(reg: dict, fr: dict | None) -> dict:
    """The register in the shape of a form answer (form fields the register doesn't have are kept)."""
    import pandas as pd
    m = dict(fr) if fr else dict(row="", ts=pd.NaT, date=pd.NaT, date_problem="", difficulty="", front="",
                                 planet="", operation="", success="", affected="", form_notes="", names=[])
    if reg.get("date"):
        m["date"], m["date_problem"] = pd.Timestamp(reg["date"]), ""
    for f in ("operation", "planet", "front", "difficulty"):
        if reg.get(f):
            m[f] = reg[f]
    if reg.get("names"):
        m["names"] = list(reg["names"])
    if reg.get("notes") and not m.get("form_notes"):
        m["form_notes"] = reg["notes"]
    m["register_id"], m["register_status"] = reg.get("register_id", ""), reg.get("status", "")
    return m


# --------------------------------------------------------------------------
# Processing an image
# --------------------------------------------------------------------------
def name_matches(file_name: str, ocr_name: str) -> bool:
    a, b = letters(file_name), letters(ocr_name)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() > 0.6


def assign_names(file_names: list[str], ocr_names: list[str]) -> list[str]:
    """Give each panel a name from the file name.

    Panels are in the same order as the names in the file name, but squads can
    be smaller than 4 or a name can be missing, so confident matches between
    the file name and the name read on screen win; the rest keep their order.
    """
    n = len(ocr_names)
    if len(file_names) == n:
        return list(file_names)
    out = [""] * n
    used = set()
    scores = []
    for i, o in enumerate(ocr_names):
        for j, f in enumerate(file_names):
            a, b = letters(f), letters(o)
            if not a or not b:
                continue
            sc = 1.0 if (a in b or b in a) else difflib.SequenceMatcher(None, a, b).ratio()
            scores.append((sc, i, j))
    for sc, i, j in sorted(scores, reverse=True):
        if sc >= 0.6 and not out[i] and j not in used:
            out[i] = file_names[j]
            used.add(j)
    rest = [f for j, f in enumerate(file_names) if j not in used]
    for i in range(n):
        if not out[i] and rest:
            out[i] = rest.pop(0)
    return out


def process_image(shot: Shot, n_variants: int, review_dir: Path | None):
    t0 = time.time()
    bgr = load_bgr(shot.path)
    try:
        lay = detect_layout(bgr)
    except LayoutError:
        # not a stat screen: maybe the Deployment Register screenshot
        try:                                       # optional (register_reader.py may be archived)
            from register_reader import read_register
        except ImportError:
            raise LayoutError("not a stat screen")
        reg = read_register(bgr, PLANET_NAMES)
        if reg is not None:
            return {"register": reg}, time.time() - t0
        raise LayoutError("neither a stat screen nor a Deployment Register screenshot")
    image_notes = []
    if abs(lay.angle) > 0.3:                       # photo of a screen / tilted capture
        h_, w_ = bgr.shape[:2]
        M = cv2.getRotationMatrix2D((w_ / 2, h_ / 2), lay.angle, 1.0)
        bgr = cv2.warpAffine(bgr, M, (w_, h_), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        image_notes.append(f"image was tilted {lay.angle:.1f} degrees, straightened")
        lay = detect_layout(bgr)
    n_panels = len(lay.lefts)
    ocr_names = [read_name(bgr, lay, p) for p in range(n_panels)]
    names = assign_names(shot.names, ocr_names) if len(shot.names) > 1 else [""] * n_panels
    rows = []
    for p in range(n_panels):
        values, flags, bands, info = read_player(bgr, lay, p, n_variants)
        file_name, ocr_name = names[p], ocr_names[p]
        row = dict(deployment=shot.key, mission=shot.mission, file=shot.path.name,
                   slot=p, player=file_name or ocr_name, ocr_name=ocr_name)
        row.update(values)
        name_check = []
        if len(shot.names) > 1 and len(shot.names) != n_panels:
            name_check.append(f"file name has {len(shot.names)} names, screen shows {n_panels} players")
        if file_name and ocr_name and not name_matches(file_name, ocr_name):
            name_check.append("name on screen differs")
        notes = [f"{st}: {why}" for st, why in info.items()]
        for st, why in flags.items():
            notes.append(f"{st}: {why}")
            if review_dir is not None and bands.get(st) is not None:
                review_dir.mkdir(parents=True, exist_ok=True)
                fn = f"{shot.path.stem}__p{p}_{st}.png"
                cv2.imencode(".png", bands[st])[1].tofile(str(review_dir / fn))
        row["flagged_stats"] = ", ".join(flags.keys())
        row["notes"] = " | ".join(notes)
        row["name_check"] = "; ".join(name_check)
        rows.append(row)
    # Whole-image sanity check: many doubtful values usually means a bad crop,
    # a photo of a screen, or a cut-off screenshot -> review every value of it.
    n_flag = sum(len(r["flagged_stats"].split(", ")) for r in rows if r["flagged_stats"])
    n_vals = max(1, len(rows) * len(STATS))
    if n_flag / n_vals > 0.10 or n_flag >= 4:
        image_notes.append(f"{n_flag} of {n_vals} values doubtful: screenshot may be cut off, "
                           "blurry or tilted - please check the whole image")
    for r in rows:
        r["image_check"] = "; ".join(image_notes)
    return rows, time.time() - t0


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------
PLANETS: dict = {}


def write_outputs(all_rows, out_dir: Path, form_rows, groups, errors, tokens=None, reg_links=None,
                  roster=None, name_issues=None):
    import pandas as pd
    out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(all_rows)
    if df.empty:
        print("Nothing extracted.")
        return
    df = df.sort_values(["deployment", "mission", "slot"]).reset_index(drop=True)

    # deployment-level info (form join)
    import pandas as pd
    planets = PLANETS
    dep_rows = []
    links = assign_form(groups, form_rows, tokens or {}) if form_rows else {}
    for key, (reg, rfile, rnote) in (reg_links or {}).items():   # register screenshot wins over the form
        fr, note = links.get(key, (None, ""))
        notes = [n for n in ((note if fr else ""), rnote) if n]
        notes += [f"register {field} not read{(' (' + what + ')') if what else ''} - see corrections.csv"
                  for field, what in reg.get("problems", [])]
        links[key] = (register_as_form(reg, fr), "; ".join(notes))
    for key, shots in sorted(groups.items(), key=lambda kv: (kv[1][0].dep_id or "", kv[0])):
        fr, note = links.get(key, (None, ""))
        if fr and fr.get("date_problem"):
            note = (note + "; " if note else "") + fr["date_problem"]
        extra = next((s.note for s in shots if s.note), "")
        if extra:
            note = (note + "; " if note else "") + extra
        date = fr["date"] if fr else pd.NaT
        planet = fr["planet"] if fr else ""
        dep_rows.append(dict(deployment=key, deployment_id=shots[0].dep_id or "", missions=len(shots),
                             players=", ".join(shots[0].names),
                             date=date.strftime("%Y-%m-%d %H:%M") if pd.notna(date) else "",
                             operation=fr["operation"] if fr else "",
                             planet=planet, sector=planets.get(planet.lower(), "") if planet else "",
                             difficulty=fr["difficulty"] if fr else "",
                             front=fr["front"] if fr else "",
                             success=fr.get("success", "") if fr else "",
                             missions_affected=fr.get("affected", "") if fr else "",
                             raid=fr.get("raid", "") if fr else "",
                             form_row=fr["row"] if fr else "",
                             register_id=fr.get("register_id", "") if fr else "",
                             register_status=fr.get("register_status", "") if fr else "",
                             form_notes=fr["form_notes"] if fr else "",
                             form_note=note))
    deps = pd.DataFrame(dep_rows)

    # Player names = callsigns: players.csv first, then the form's callsigns (see name_players)
    linked = {k for k, (fr, _) in links.items() if fr}
    if roster is not None:
        for key, (fr, _) in links.items():
            if fr:
                for c in fr["names"]:
                    roster.add_callsign(clean_callsign(c))
        infer_aliases(df, links, roster)
    asked = set()
    for key, (fr, _) in links.items():
        if not fr:
            continue
        if roster is not None:
            for c in fr["names"]:
                roster.add_callsign(clean_callsign(c))
        up_of = {sh.path.name: sh.uploader for sh in groups.get(key, [])}
        sure: dict = defaultdict(Counter)     # slot -> callsigns recognised for certain in this deployment
        guessed = []                          # (row, callsign, in-game name) placed by panel order only
        for _, m in df[df["deployment"] == key].groupby("mission"):
            uploader = next((up_of.get(f, "") for f in m["file"] if up_of.get(f)), "")
            names, how = name_players(m, fr["names"], roster, uploader)
            if roster is not None:                # panels the form doesn't explain: players.csv
                for idx in m.index:
                    if idx not in names:
                        cs = roster.callsign_for(m.at[idx, "ocr_name"])
                        if cs:
                            df.at[idx, "player"] = cs
            for idx, cs in names.items():
                df.at[idx, "player"] = cs
                ocr = str(df.at[idx, "ocr_name"] or "")
                if ocr == "nan":
                    ocr = ""
                if how[idx] == "order":
                    guessed.append((idx, cs, ocr))
                else:
                    sure[int(df.at[idx, "slot"])][cs] += 1
                    if how[idx] in ("name", "last") and roster is not None:
                        roster.learn(ocr, cs)
        # players keep their panel for the whole deployment: a guess in one mission takes the player
        # recognised for certain in the same panel in the other missions; only the rest is asked (once)
        for idx, cs, ocr in guessed:
            slot = int(df.at[idx, "slot"])
            known = sure.get(slot)
            if known and len(known) == 1:
                cs = next(iter(known))
                df.at[idx, "player"] = cs
                if roster is not None and ocr:
                    roster.learn(ocr, cs)
                continue
            df.at[idx, "name_check"] = "; ".join(x for x in (str(df.at[idx, "name_check"] or ""),
                                                             "name guessed from panel order") if x)
            ask = (key, slot)
            if name_issues is not None and ask not in asked:   # once per player per deployment
                asked.add(ask)
                name_issues.append(dict(file=df.at[idx, "file"], slot=df.at[idx, "slot"], stat="player",
                                        player=cs, value_read=cs,
                                        readings=f"in-game name '{ocr}' - guessed from the panel order; type ok if "
                                                 "right, or the right CALLSIGN"))
    if roster is not None:                        # deployments without a form answer: players.csv only
        for idx in df.index[~df["deployment"].isin(linked)]:
            cs = roster.callsign_for(df.at[idx, "ocr_name"])
            if cs:
                df.at[idx, "player"] = cs
    for (f, slot), val in PLAYER_OVERRIDES.items():   # corrections.csv, stat = player
        first = df.index[(df["file"] == f) & (df["slot"].astype(str) == slot)]
        if not len(first):
            continue
        dep_key = df.at[first[0], "deployment"]
        ok = val.lower() in ("ok", "yes", "y", "correct", "confirmed")
        guess = df.at[first[0], "player"]
        fr = links.get(dep_key, (None, ""))[0]
        form_calls = [clean_callsign(c) for c in (fr["names"] if fr else [])]
        alias_name = ""
        if ok:
            cs = guess
        else:
            # a callsign of this deployment's form answer, or a known name of a callsign (players.csv): that player
            cs = next((c for c in form_calls if norm_cs(c) == norm_cs(val)), None)
            if cs is None and roster is not None:
                cs = roster.callsign_for(val, fuzzy=False)
            if cs is None:
                # not a callsign: most likely the in-game name of the guessed player -> keep the guess, remember it
                cs, alias_name = guess, val
        # same panel in the other missions of this deployment: same player
        for idx in df.index[(df["deployment"] == dep_key) & (df["slot"].astype(str) == slot)]:
            df.at[idx, "player"] = cs
            df.at[idx, "name_check"] = ""
            if roster is not None:
                ocr = str(df.at[idx, "ocr_name"] or "")
                if ocr not in ("", "nan"):
                    roster.learn(ocr, cs)
        if roster is not None and alias_name:
            roster.learn(alias_name, cs)
    df = df.merge(deps[["deployment", "deployment_id", "date", "operation", "planet", "sector", "difficulty", "front",
                        "success", "missions_affected", "raid"]], on="deployment", how="left")

    front_cols = ["deployment", "deployment_id", "date", "operation", "planet", "sector", "difficulty", "front", "success",
                  "missions_affected", "raid", "mission", "file", "slot", "player", "ocr_name"]
    front_cols = [c for c in front_cols if c in df.columns]
    df = df[front_cols + STATS + ["flagged_stats", "notes", "name_check", "image_check"]]
    df["file_hash"] = df["file"].map(FILE_HASH).astype(object).fillna("")

    df.to_csv(out_dir / "stats.csv", index=False, encoding="utf-8-sig")
    bad_image = df["image_check"].astype(object).fillna("").astype(str).str.contains("please check")
    review = df[(df["flagged_stats"].astype(object).fillna("").astype(str) != "") | bad_image]
    err_df = pd.DataFrame(errors, columns=["file", "error"])

    xlsx = out_dir / "HD2_stats.xlsx"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as xw:
        df.to_excel(xw, sheet_name="Stats", index=False)
        review.to_excel(xw, sheet_name="Review", index=False)
        deps.to_excel(xw, sheet_name="Deployments", index=False)
        if len(err_df):
            err_df.to_excel(xw, sheet_name="Errors", index=False)
        _style_workbook(xw)

    # Legacy per-deployment sheets, same shape as the old All_Operation files
    leg = out_dir / "legacy_All_Operations"
    leg.mkdir(exist_ok=True)
    for key, d in df.groupby("deployment"):
        blocks = []
        for i, (_, m) in enumerate(d.groupby("mission")):
            if i:
                blocks.append(pd.DataFrame([[None] * 8] * 2, columns=LEGACY_HEADERS))
            b = m[LEGACY_STATS].copy()
            b.columns = LEGACY_HEADERS
            b["ACCURACY"] = b["ACCURACY"].map(lambda v: "" if pd.isna(v) else f"{v:.1f}%".replace(".", ","))
            blocks.append(b)
        pd.concat(blocks, ignore_index=True).to_excel(leg / f"{key}__All_Operation.xlsx",
                                                       index=False, header=False)
    return xlsx, len(review)


def _style_workbook(xw):
    from openpyxl.styles import Font, PatternFill
    hdr = PatternFill("solid", fgColor="1F2937")
    flag = PatternFill("solid", fgColor="FDE68A")
    for ws in xw.book.worksheets:
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = hdr
        ws.freeze_panes = "A2"
        for col in ws.columns:
            width = max(len(str(c.value)) if c.value is not None else 0 for c in col[:200])
            ws.column_dimensions[col[0].column_letter].width = min(max(8, width + 2), 60)
        if ws.title == "Stats":
            heads = [c.value for c in ws[1]]
            if "flagged_stats" in heads:
                fi = heads.index("flagged_stats")
                for row in ws.iter_rows(min_row=2):
                    flagged = str(row[fi].value or "")
                    if flagged:
                        for st in flagged.split(", "):
                            if st in heads:
                                row[heads.index(st)].fill = flag


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def looks_like_form(path: Path) -> bool:
    """True if the file has a sheet whose header row contains the form's callsign columns."""
    try:
        if path.suffix.lower() == ".csv":
            head = path.read_text(encoding="utf-8-sig", errors="ignore").splitlines()[:1]
            return bool(head) and "hostcallsign" in _norm(head[0])
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            for ws in wb.worksheets:
                row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
                if any(_norm(c or "").startswith("hostcallsign") or _norm(c or "") == "host" for c in row):
                    return True
        finally:
            wb.close()
    except Exception:
        return False
    return False


def find_form_file(extra_dirs=()) -> Path | None:
    """The newest .xlsx/.csv next to the script, in the current folder or in the synced Drive folder
    (form_answers.csv written by the Google script) that contains form answers."""
    here = Path(__file__).resolve().parent
    seen, files = set(), []
    for d in (here, Path.cwd(), *[Path(x) for x in extra_dirs if x]):
        if not d.is_dir():
            continue
        for p in list(d.glob("*.xlsx")) + list(d.glob("*.csv")):
            if p.name.startswith("~$") or p.resolve() in seen:
                continue
            seen.add(p.resolve())
            files.append(p)
    for p in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True):
        if looks_like_form(p):
            return p
    return None

def main(argv=None):
    ap = argparse.ArgumentParser(description="Helldivers 2 stat screens -> spreadsheet")
    ap.add_argument("input", nargs="?", default="To_Process",
                    help="folder with screenshots (default: To_Process)")
    ap.add_argument("-o", "--output", default="output", help="output folder (default: output)")
    ap.add_argument("--form", help="Google Form answers (.xlsx registry workbook or .csv) to add date, "
                    "operation, planet, difficulty and front. Default: FormResponses.xlsx/.csv or "
                    "*Registry*.xlsx next to this script")
    ap.add_argument("--no-form", action="store_true", help="don't look for a form file")
    ap.add_argument("--timezone", default=DISPLAY_TZ,
                    help=f"time zone for Discord <t:...> start dates (default: {DISPLAY_TZ})")
    ap.add_argument("--recursive", action="store_true", help="also look in sub-folders")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4,
                    help="images processed in parallel (default: CPU count)")
    ap.add_argument("--passes", type=int, choices=(1, 2, 3), default=3,
                    help="OCR passes per value: 1 = fastest, 3 = most accurate (default)")
    ap.add_argument("--force", action="store_true", help="ignore the cache and re-read every image")
    ap.add_argument("--tesseract", help="path to tesseract executable")
    ap.add_argument("--no-drive", action="store_true", help="don't read the synced Google Drive folder")
    ap.add_argument("--no-history", action="store_true", help="don't add this run to history/")
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="replace")  # odd characters in file names on Windows
    except Exception:
        pass
    if glyph_model() is None:
        print("WARNING: glyphs.npz not found next to hd2stats.py - falling back to Tesseract only "
              "(slower, less accurate). Using --passes 3.")
        args.passes = 3

    pytesseract.pytesseract.tesseract_cmd = find_tesseract(args.tesseract)
    src = Path(args.input)
    out = Path(args.output)
    drive = None if args.no_drive else synced_folder()
    has_history = (HERE / "history" / "stats.csv").exists()
    if not src.is_dir() and not drive:
        if has_history:
            print(f"No screenshot folder ({src}) - nothing new to read; the report is built from the history.")
            return
        sys.exit(f"Input folder not found: {src.resolve()}")

    # screenshots: the synced Google Drive folder (if set) + the input folder; the same picture in
    # both places (same name and size) is read once
    paths, seen_img = [], {}
    dupes = []
    for folder, recursive in ((drive, True), (src if src.is_dir() else None, args.recursive)):
        if folder is None:
            continue
        it = folder.rglob("*") if recursive else folder.iterdir()
        found = 0
        for p in sorted(it):
            if not (p.is_file() and p.suffix.lower() in IMG_EXT):
                continue
            sig = file_hash(p)              # same picture = same content, whatever its name
            if not sig:
                continue
            if sig in seen_img:
                dupes.append((p.name, seen_img[sig].name))
                continue
            seen_img[sig] = p
            FILE_HASH[p.name] = sig
            paths.append(p)
            found += 1
        if folder is drive:
            print(f"Google Drive folder: {drive}  ({found} screenshots)")
    if dupes:
        print(f"{len(dupes)} duplicate screenshot(s) skipped (same picture as another file): "
              + ", ".join(f"{a} = {b}" for a, b in dupes[:5]) + (" ..." if len(dupes) > 5 else ""))
    if not paths:
        if has_history:
            print("No screenshots to read - nothing new; the report is built from the history.")
            return
        sys.exit(f"No images in {src.resolve()}" + (f" or {drive}" if drive else ""))
    groups = group_shots(paths)
    shots = [s for g in groups.values() for s in g]
    print(f"{len(shots)} images, {len(groups)} deployments, {args.workers} workers, {args.passes} passes")

    # the reading cache lives in history/ so a reset (which empties output/) doesn't re-read everything
    cache_file = HERE / "history" / "ocr_cache.json"
    old_cache = out / "cache.json"
    if not cache_file.exists() and old_cache.exists():
        cache_file.parent.mkdir(exist_ok=True)
        shutil.copyfile(old_cache, cache_file)
    cache = {}
    if cache_file.exists() and not args.force:
        try:
            cache = json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            cache = {}
    cache_tag = f"v{__version__}-p{args.passes}"

    def ckey(s: Shot):
        st = s.path.stat()
        return f"{s.path.resolve()}|{st.st_size}|{int(st.st_mtime)}|{cache_tag}"

    # form + planet list first: the planet list helps reading register screenshots
    set_timezone(args.timezone)
    form_path = Path(args.form) if args.form else (None if args.no_form else find_form_file([drive] if drive else []))
    global PLANETS
    PLANETS = load_planets(form_path)

    review_dir = out / "review_crops"
    if args.force and review_dir.exists():
        shutil.rmtree(review_dir, ignore_errors=True)

    all_rows, errors = [], []
    registers: dict = {}          # file name -> (shot, register fields)
    todo = []
    for s in shots:
        k = ckey(s)
        if k in cache and isinstance(cache[k], dict) and "register" in cache[k]:
            registers[s.path.name] = (s, cache[k]["register"])
        elif k in cache:
            rows = cache[k]
            for r in rows:  # mission number may change if files were added
                r["mission"], r["deployment"] = s.mission, s.key
            all_rows.extend(rows)
        else:
            todo.append((s, k))
    if len(shots) - len(todo):
        print(f"{len(shots) - len(todo)} images already done (cache), {len(todo)} to read")

    t0 = time.time()
    done = 0
    with cf.ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {ex.submit(process_image, s, args.passes, review_dir): (s, k) for s, k in todo}
        for fut in cf.as_completed(futs):
            s, k = futs[fut]
            done += 1
            try:
                rows, dt = fut.result()
                if isinstance(rows, dict):          # a Deployment Register screenshot
                    registers[s.path.name] = (s, rows["register"])
                    cache[k] = rows
                    reg = rows["register"]
                    print(f"[{done}/{len(todo)}] {s.path.name}: Deployment Register "
                          f"#{reg.get('register_id') or '?'} ({reg.get('operation') or 'no name'}), {dt:.1f}s"
                          + (f", {len(reg['problems'])} field(s) to check" if reg.get("problems") else ""))
                    continue
                all_rows.extend(rows)
                cache[k] = rows
                nflag = sum(1 for r in rows if r["flagged_stats"])
                print(f"[{done}/{len(todo)}] {s.path.name}: {len(rows)} players, {dt:.1f}s"
                      + (f", {nflag} need review" if nflag else ""))
            except Exception as e:  # keep going, report at the end
                errors.append((s.path.name, str(e)))
                print(f"[{done}/{len(todo)}] {s.path.name}: ERROR {e}")
    elapsed = time.time() - t0

    out.mkdir(parents=True, exist_ok=True)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(cache, indent=0), encoding="utf-8")
    # hand corrections (never stored in the cache)
    import copy
    all_rows = copy.deepcopy(all_rows)
    corr_file = corrections_path()
    corr = load_corrections(corr_file)
    n_applied = apply_corrections(all_rows, corr)
    if n_applied:
        print(f"Applied {n_applied} correction(s) from {corr_file.name}")
    # keep only the review pictures of values that are still flagged
    if review_dir.exists():
        wanted = {f"{Path(r['file']).stem}__p{r['slot']}_{st}.png"
                  for r in all_rows if r.get("flagged_stats") for st in str(r["flagged_stats"]).split(", ")}
        for f in review_dir.glob("*.png"):
            if f.name not in wanted:
                f.unlink(missing_ok=True)
    if form_path:
        where_f = ("the Google Drive folder" if drive and form_path.parent.resolve() == drive.resolve()
                   else "the program folder")
        print(f"Form answers: {form_path.name}" + ("" if args.form else f"  (newest form file, found in {where_f})"))
    elif registers:
        print(f"No form file - using the {len(registers)} Deployment Register screenshot(s)")
    else:
        print("No form file and no register screenshots - dates, fronts and operations will be missing")
    form_rows = load_form(form_path) if form_path else []

    # register screenshots are not missions: take them out of the deployments, renumber the rest
    sources = {sh.path.name: sh.path for shots in groups.values() for sh in shots}
    if registers:
        for key in list(groups):
            kept = [sh for sh in groups[key] if sh.path.name not in registers]
            if not kept:
                del groups[key]
            elif len(kept) != len(groups[key]):
                for i, sh in enumerate(kept, 1):
                    sh.mission = i
                groups[key] = kept
    orig_key = {sh.path.name: sh.key for shots in groups.values() for sh in shots}
    groups, tokens = regroup(all_rows, groups)
    reg_links, unattached = attach_registers(groups, tokens, registers, orig_key)
    reg_links = {k: (apply_register_overrides(f, r), f, n) for k, (r, f, n) in reg_links.items()}
    for f in unattached:
        errors.append((f, "Deployment Register read, but no stat screenshots belong to it "
                          "(upload the 3 stat screens with it)"))
        print(f"{f}: register without stat screenshots - not counted")
    from players import Roster
    roster = Roster()
    name_issues: list = []
    res = write_outputs(all_rows, out, form_rows, groups, errors, tokens, reg_links, roster, name_issues)
    roster.save()
    if roster.learned:
        print(f"players.csv: learned {len(roster.learned)} in-game name(s): "
              + ", ".join(f"{n} = {c}" for n, c in roster.learned[:8]) + (" ..." if len(roster.learned) > 8 else ""))
    reg_issues = [dict(file=f, stat=field, value_read=r.get(field if field != "players" else "lead", ""),
                       readings=what) for _, (r, f, _) in reg_links.items() for field, what in r["problems"]]
    n_open = update_corrections_file(corr_file, all_rows, corr, sources, reg_issues + name_issues)
    if res and not args.no_history:
        import history
        history.merge(out / "stats.csv")
    if todo:
        print(f"\nRead {len(todo)} images in {elapsed:.1f}s "
              f"({elapsed / len(todo):.1f}s per image, ~{3 * elapsed / len(todo):.0f}s per 3-mission deployment)")
    if res:
        xlsx, n_review = res
        print(f"Wrote {xlsx}")
    if n_open:
        print(f"\n{n_open} value(s) to check: open corrections.csv, open the screenshot listed on each line "
              "(slot 0 = leftmost player), type the right number (or ok) in the correct_value column, save, "
              "run again.")
    else:
        print("\nNothing left to check.")
    if errors:
        print(f"{len(errors)} images failed, see the Errors sheet")


if __name__ == "__main__":
    main()

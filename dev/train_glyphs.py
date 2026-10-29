"""
train_glyphs.py - (re)build glyphs.npz, the digit templates used by hd2stats.py.

You only need this if the game changes its font / UI, or to add more samples.

    python train_glyphs.py MASS_DEPLOY [more folders...]

How it works: every value on every screenshot is read by Tesseract twice with
different settings. When both readings agree, are well-formed, and the number
of characters matches the number of glyphs found in the image, each glyph is
saved as a labelled example. No manual labelling needed.
"""
import argparse
import concurrent.futures as cf
import os
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pytesseract

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # the program folder (dev/ is one level down)
import hd2stats as h  # noqa: E402

MIN_TEXT_H = 14  # px; smaller digits are too blurry to label reliably


def harvest(path: Path):
    X, y = [], []
    try:
        bgr = h.load_bgr(path)
        lay = h.detect_layout(bgr)
    except Exception as e:
        print(f"skip {path.name}: {e}")
        return X, y
    for p in range(len(lay.lefts)):
        for r, st in enumerate(h.STATS):
            band = h.value_band(bgr, lay, p, r)
            if band is None:
                continue
            iso = h.isolate_digits(band, 165)
            if iso is None:
                continue
            crop, th = iso
            if th < MIN_TEXT_H:
                continue  # too small to trust the labels
            reads = [h.ocr(h.to_tesseract_image(crop, th, t), psm) for t, psm in ((40, 7), (52, 7))]
            if reads[0] != reads[1] or not reads[0]:
                continue
            raw = reads[0]
            _, prob = h.parse_value(raw, st)
            if prob:
                continue
            want = [c for c in raw if c not in ",."]
            parts = h.segment_glyphs(crop, th)
            glyphs = [g for k, g in parts if k == "glyph"]
            if len(glyphs) != len(want):
                continue
            for g, c in zip(glyphs, want):
                X.append(h.glyph_feature(g))
                y.append(c)
    return X, y


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folders", nargs="+")
    ap.add_argument("-o", "--output", default=str(Path(__file__).resolve().parent.parent / "glyphs.npz"))
    ap.add_argument("--tesseract")
    ap.add_argument("--max-per-class", type=int, default=400)
    a = ap.parse_args()
    pytesseract.pytesseract.tesseract_cmd = h.find_tesseract(a.tesseract)

    paths = sorted({p.resolve() for f in a.folders for p in Path(f).rglob("*")
                    if p.is_file() and p.suffix.lower() in h.IMG_EXT})
    print(f"harvesting glyphs from {len(paths)} images...")
    X, y = [], []
    with cf.ThreadPoolExecutor(os.cpu_count() or 4) as ex:
        for xs, ys in ex.map(harvest, paths):
            X += xs
            y += ys
    if not X:
        sys.exit("no glyphs harvested")
    X, y = np.array(X, np.float32), np.array(y)

    # drop samples whose 7 nearest neighbours mostly carry another label
    sq = (X * X).sum(1)
    D = sq[:, None] + sq[None, :] - 2 * X @ X.T
    np.fill_diagonal(D, np.inf)
    nn = np.argsort(D, 1)[:, :7]
    ok = np.array([Counter(y[nn[i]]).most_common(1)[0][0] == y[i] for i in range(len(y))])
    print(f"dropped {int((~ok).sum())} doubtful samples")
    X, y = X[ok], y[ok]

    # cap each class, keep a spread of examples
    rng = np.random.default_rng(0)
    keep = []
    for c in sorted(set(y)):
        idx = np.where(y == c)[0]
        if len(idx) > a.max_per_class:
            idx = rng.choice(idx, a.max_per_class, replace=False)
        keep.extend(idx)
    X, y = X[keep], y[keep]

    # leave-one-out check
    np.savez_compressed(a.output, X=X, y=y)
    sq = (X * X).sum(1)
    D = sq[:, None] + sq[None, :] - 2 * X @ X.T
    np.fill_diagonal(D, np.inf)
    loo = (y[D.argmin(1)] == y).mean()
    print(f"saved {len(y)} glyphs to {a.output}  per class: {dict(sorted(Counter(y).items()))}")
    print(f"leave-one-out accuracy: {loo:.4f}")


if __name__ == "__main__":
    main()

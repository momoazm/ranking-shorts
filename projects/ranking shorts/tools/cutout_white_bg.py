"""Turn a solid-background (usually white) cartoon image into a clean transparent cutout.

Why: most high-quality OFFICIAL character art online is on a white background (no alpha) or has a
fake baked checkerboard. This flood-fills the background inward from the image borders, so only
the background connected to the edges is removed — interior whites (Stewie's head, eye glints,
Peter's shirt) are preserved. Result: a matched-style, genuinely transparent PNG for overlays.

Usage:
    python tools/cutout_white_bg.py --in raw.png --out assets/characters/stewie.png
        [--thresh 32] [--bg-color 255,255,255] [--feather 0.8]

Prints JSON: {"path": ..., "opaque_ratio": F, "size": [W,H]}
"""
import argparse
import os

from _common import emit, fail

SENTINEL = (255, 0, 255)  # magenta marker for "background" pixels; ~never in cartoon art


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="inp", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--thresh", type=int, default=32, help="Color tolerance for the flood fill")
    parser.add_argument("--bg-color", default="255,255,255", help="Expected background color R,G,B")
    parser.add_argument("--feather", type=float, default=0.8, help="Gaussian blur radius on the alpha edge")
    parser.add_argument("--erode", type=int, default=1, help="Pixels to trim off the edge (kills white halo)")
    args = parser.parse_args()

    if not os.path.isfile(args.inp):
        fail(f"Input not found: {args.inp}")
        return

    from PIL import Image, ImageDraw, ImageFilter

    try:
        bg = tuple(int(x) for x in args.bg_color.split(","))
        assert len(bg) == 3
    except (ValueError, AssertionError):
        fail("--bg-color must be 'R,G,B'")
        return

    # Flatten any existing alpha onto the expected background so checker/transparent both normalize.
    src = Image.open(args.inp).convert("RGBA")
    flat = Image.new("RGB", src.size, bg)
    flat.paste(src, mask=src.split()[3])
    work = flat.copy()

    w, h = work.size
    seeds = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1),
             (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)]
    for xy in seeds:
        # Only flood from a seed that actually looks like background.
        px = work.getpixel(xy)
        if all(abs(px[i] - bg[i]) <= args.thresh for i in range(3)):
            ImageDraw.floodfill(work, xy, SENTINEL, thresh=args.thresh)

    # Build alpha: transparent where the flood marked background (== SENTINEL), opaque elsewhere.
    from PIL import ImageChops
    sent = Image.new("RGB", work.size, SENTINEL)
    diff = ImageChops.difference(work, sent).convert("L")   # 0 at background, >0 on the character
    alpha = diff.point(lambda v: 0 if v == 0 else 255)

    if args.erode > 0:
        alpha = alpha.filter(ImageFilter.MinFilter(2 * args.erode + 1))
    if args.feather > 0:
        alpha = alpha.filter(ImageFilter.GaussianBlur(args.feather))

    out_img = flat.convert("RGBA")
    out_img.putalpha(alpha)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    out_img.save(args.out)

    hist = alpha.histogram()
    opaque = sum(hist[200:]) / float(w * h)
    emit({"path": args.out, "opaque_ratio": round(opaque, 3), "size": [w, h]})


if __name__ == "__main__":
    main()

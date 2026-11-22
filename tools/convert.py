"""Convert roster sheets (lrrh_sprites/*_sheet.png) to 1-bit sprites for the 72x40 OLED.

Each source colour becomes off, a 50% checker, or on, by luma thresholds per character.
Writes ../sprites_<game>.py (frames as MONO_HLSB bytes plus a 1 px dilated mask) and
../art/preview_<game>.png.

  uv run --with pillow python tools/convert.py
"""
import os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(os.path.dirname(ROOT), "lrrh_sprites")
CELL = 32

RED = ("little_red_riding_hood_small", 64, 120)
WOLF = ("big_bad_wolf", 68, 120)
WISP = ("lost_wisp_small", 60, 110)
BRAMBLES = ("thorn_brambles_small", 50, 104)
HUNTER = ("rogue_hunter_small", 60, 110)
RAVEN = ("raven", 50, 100)
MUSHROOM = ("spore_mushroom_small", 60, 130)
BOAR = ("wild_boar", 40, 120)
BEAR = ("brown_bear", 45, 130)


def row(r, n, start=0):
    return [(r, c) for c in range(start, start + n)]


# game: {name: ((sheet, lo, hi), cells, options)}
# luma < lo -> off, lo..hi -> checker, >= hi -> on.
# options: flip (face left), air (crop tight instead of keeping the feet row),
#          rows (y0, y1) keeps only those source rows, vflip (hang from the top).
GAMES = {
    "runner": {
        "red_idle": (RED, row(0, 4), {}),
        "red_run": (RED, row(1, 4), {}),
        "red_jump": (RED, [(3, 1), (3, 2)], {}),
        "red_hit": (RED, [(4, 1), (4, 2)], {}),
        "red_death": (RED, row(5, 4), {}),
        "wolf_run": (WOLF, row(1, 4), {}),
        "wolf_bite": (WOLF, row(2, 4, 1), {}),
        "wolf_idle": (WOLF, row(0, 4), {}),
        "raven": (RAVEN, [(2, 2), (2, 3)], {"flip": True, "air": True}),
        "mushroom": (MUSHROOM, row(0, 4), {"flip": True}),
        "brambles": (BRAMBLES, row(0, 4), {"flip": True}),
    },
    "duel": {
        "red_idle": (RED, row(0, 4), {}),
        "red_swing": (RED, row(2, 6), {}),
        "red_hit": (RED, [(4, 1), (4, 2)], {}),
        "red_death": (RED, row(5, 4), {}),
        "wolf_idle": (WOLF, row(0, 4), {"flip": True}),
        "wolf_warn": (WOLF, [(2, 1), (2, 2), (2, 3)], {"flip": True}),
        "wolf_lunge": (WOLF, row(3, 8), {"flip": True}),
        "wolf_hit": (WOLF, [(4, 1), (4, 2)], {"flip": True}),
        "boar_idle": (BOAR, row(0, 4), {"flip": True}),
        "boar_paw": (BOAR, row(2, 4), {"flip": True}),  # 0-1 pawing, 2-3 the gleam on his tusk
        "boar_charge": (BOAR, row(3, 6, 1), {"flip": True}),
        "boar_hit": (BOAR, [(4, 1), (4, 2)], {"flip": True}),
        "bear_idle": (BEAR, row(0, 4), {"flip": True}),
        "bear_rear": (BEAR, [(2, 1), (2, 2)], {"flip": True}),
        "bear_swipe": (BEAR, [(2, 3), (2, 4), (2, 5)], {"flip": True}),
        "bear_hit": (BEAR, [(4, 1), (4, 2)], {"flip": True}),
    },
    "wisp": {
        "wisp_idle": (WISP, row(0, 4), {"air": True, "rows": (0, 29)}),
        "wisp_fly": (WISP, row(1, 4), {"air": True, "rows": (0, 29)}),
        "wisp_pop": (WISP, row(5, 6), {"air": True, "rows": (0, 29)}),
        "thicket": (BRAMBLES, [(3, 0)], {}),
        "thicket_top": (BRAMBLES, [(3, 0)], {"vflip": True, "air": True}),
        "raven": (RAVEN, [(2, 2), (2, 3)], {"flip": True, "air": True}),
    },
    "hunter": {
        "hunter_idle": (HUNTER, row(0, 4), {}),
        "hunter_shoot": (HUNTER, [(2, 0), (2, 1), (2, 2), (2, 5)], {}),
        "hunter_hit": (HUNTER, [(4, 1), (4, 2)], {}),
        "hunter_death": (HUNTER, row(5, 4, 2), {}),
        "raven_glide": (RAVEN, [(2, 2), (2, 3)], {"flip": True, "air": True}),
        "raven_hit": (RAVEN, [(4, 1), (4, 2)], {"flip": True, "air": True}),
        "raven_down": (RAVEN, row(5, 4, 2), {"flip": True}),
        "raven_idle": (RAVEN, row(0, 4), {"flip": True}),
        "boar_run": (BOAR, row(1, 4), {"flip": True}),
        "boar_hit": (BOAR, [(4, 1), (4, 2)], {"flip": True}),
        "boar_down": (BOAR, row(5, 4, 1), {"flip": True}),
    },
    "pinball": {
        "wolf_idle": (WOLF, row(0, 4), {}),
        "wolf_bite": (WOLF, row(2, 4, 1), {}),
        # frames 0-3 idle, 4 flaring up as it bumps the ball
        "wisp": (WISP, row(0, 4) + [(5, 2)], {"air": True, "rows": (0, 29)}),
        # frames 0-3 idle, 4 puffed up
        "mushroom": (MUSHROOM, row(0, 4) + [(1, 1)], {}),
        "red_idle": (RED, row(0, 4), {}),
        "red_jump": (RED, [(3, 1), (3, 2)], {}),
        "red_hit": (RED, [(4, 1), (4, 2)], {}),
        "red_death": (RED, row(5, 4), {}),
    },
}


def luma(p):
    return 0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2]


def convert(spec):
    (sheet, lo, hi), cells, opt = spec
    im = Image.open(os.path.join(SRC, sheet + "_sheet.png")).convert("RGBA")
    frames = []
    for r, c in cells:
        f = im.crop((c * CELL, r * CELL, c * CELL + CELL, r * CELL + CELL))
        if "rows" in opt:
            y0, y1 = opt["rows"]
            keep = Image.new("RGBA", f.size, (0, 0, 0, 0))
            keep.paste(f.crop((0, y0, CELL, y1)), (0, y0))
            f = keep
        if opt.get("flip"):
            f = f.transpose(Image.FLIP_LEFT_RIGHT)
        if opt.get("vflip"):
            f = f.transpose(Image.FLIP_TOP_BOTTOM)
        frames.append(f)
    # one shared box per animation, padded 1 px for the mask halo
    boxes = [b for b in (f.getbbox() for f in frames) if b]
    x0 = max(0, min(b[0] for b in boxes) - 1)
    y0 = max(0, min(b[1] for b in boxes) - 1)
    x1 = min(CELL, max(b[2] for b in boxes) + 1)
    y1 = min(CELL, max(b[3] for b in boxes) + 1) if opt.get("air") else CELL
    w, h = x1 - x0, y1 - y0
    out = []
    for f in frames:
        px = f.load()
        on = [[0] * w for _ in range(h)]
        solid = [[0] * w for _ in range(h)]
        for y in range(h):
            for x in range(w):
                p = px[x0 + x, y0 + y]
                if p[3] < 128:
                    continue
                solid[y][x] = 1
                l = luma(p)
                on[y][x] = 1 if l >= hi or (l >= lo and (x + y) & 1) else 0
        mask = [[0] * w for _ in range(h)]
        for y in range(h):
            for x in range(w):
                if any(
                    0 <= y + dy < h and 0 <= x + dx < w and solid[y + dy][x + dx]
                    for dy, dx in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))
                ):
                    mask[y][x] = 1
        out.append((on, mask))
    return w, h, x0, out


def pack(rows, w):
    stride = (w + 7) // 8
    b = bytearray(stride * len(rows))
    for y, r in enumerate(rows):
        for x, v in enumerate(r):
            if v:
                b[y * stride + x // 8] |= 0x80 >> (x & 7)
    return bytes(b)


def preview(data, path):
    pad, scale = 3, 6
    width = max(sum(w + pad for _ in fr) for w, h, ox, fr in data.values()) + pad
    height = sum(h + pad for w, h, ox, fr in data.values()) + pad
    pv = Image.new("RGB", (width, height), (0, 0, 0))
    y = pad
    for w, h, ox, frames in data.values():
        x = pad
        for on, mask in frames:
            for yy in range(h):
                for xx in range(w):
                    if on[yy][xx]:
                        pv.putpixel((x + xx, y + yy), (255, 255, 255))
                    elif mask[yy][xx]:
                        pv.putpixel((x + xx, y + yy), (38, 38, 52))
            x += w + pad
        y += h + pad
    pv.resize((width * scale, height * scale), Image.NEAREST).save(path)


def main():
    os.makedirs(os.path.join(ROOT, "art"), exist_ok=True)
    for game, specs in GAMES.items():
        data = {n: convert(s) for n, s in specs.items()}
        with open(os.path.join(ROOT, "sprites_%s.py" % game), "w") as fh:
            fh.write("# Generated by tools/convert.py from lrrh_sprites sheets. Do not edit.\n")
            fh.write("# name = (w, h, ox, ((bits, mask), ...)) in MONO_HLSB. ox is the crop's left edge in\n")
            fh.write("# the 32 px source cell; grounded sprites stand on their bottom row.\n")
            for n, (w, h, ox, frames) in data.items():
                fh.write("%s = (%d, %d, %d, (\n" % (n, w, h, ox))
                for on, mask in frames:
                    fh.write("    (%r, %r),\n" % (pack(on, w), pack(mask, w)))
                fh.write("))\n")
        preview(data, os.path.join(ROOT, "art", "preview_%s.png" % game))
        for n, (w, h, ox, fr) in data.items():
            print(game, n, w, h, ox, len(fr))


if __name__ == "__main__":
    main()

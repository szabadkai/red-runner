"""Build the pinball table for pinball.py: ../pinball.bin and ../art/table_pinball.png.

The table is laid out here as walls, solid shapes and the outlines of the roster sprites. For
every pixel the ball's centre could be on, the map says whether the ball is blocked there and
which way the surface faces, so the game bounces the ball with one lookup per step whatever
the shape of the table.

  uv run --with pillow python tools/table.py

The drop targets on the side walls are not in the map: they come and go, so the game tests
them itself. Their rows are in the header.

pinball.bin: 24-byte header, flipper tables, palette of (kind, normal), wall art in MONO_HLSB,
then the map, one palette index per pixel (0 is free). Sprite positions in the header are the
left edge of the idle animation's box and the row the sprite stands on (wisps: the box's top).
"""
import math
import os
import random
import struct

from PIL import Image

import convert

TW, TH = 72, 124
R = 2.5  # ball radius
MID = 32.5  # centre line of the playfield; the launch lane takes the right 7 px
LANE = 64.5  # the wall between playfield and launch lane
LANE_TOP = 18
CORNER = 14  # radius of the two top corners
PIV_L, PIV_R, PIV_Y = 13, 52, 88  # flipper pivots
FLIP_LEN = 15
FLIP_REST = 26  # degrees below level at rest
FLIP_STEPS = (4, 6, 8, 8, 8, 7, 6, 5)  # degrees per half tick on the way up
SLOPE_Y = 80  # where the slopes down to the flippers leave the side walls
PLUNGER_Y = 118  # the ball rests on this in the lane
MOON = (28, 9)  # top left of the 9 px moon
WISPS = ((13.5, 54), (51.5, 54))  # centres, left one first
WISP_R = 4
MUSH_FEET = 46
TARGETS = (22, 30, 38)  # tops of the drop targets, the same three on each side wall
TARGET_W, TARGET_H = 3, 4
RED_FEET = WOLF_FEET = TH - 1  # the two of them watch from the aprons either side of the drain

WALL, DEAD, WISP, MUSH, MOONK = 1, 2, 3, 4, 5  # DEAD: a wall that takes the bounce out
DIRS = 64

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def seg_dist(px, py, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    ll = dx * dx + dy * dy
    t = 0 if ll == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / ll))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def poly_sdf(px, py, pts):
    """Signed distance to a polygon, negative inside."""
    d = 1e9
    inside = False
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        d = min(d, seg_dist(px, py, a, b))
        if (a[1] > py) != (b[1] > py) and px < a[0] + (py - a[1]) * (b[0] - a[0]) / (b[1] - a[1]):
            inside = not inside
    return -d if inside else d


def arc(cx, cy, r, a0, a1, n=14):
    return [
        (cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)), cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n)))
        for i in range(n + 1)
    ]


def hull(points):
    pts = sorted(set(points))

    def half(seq):
        out = []
        for p in seq:
            while len(out) > 1 and (out[-1][0] - out[-2][0]) * (p[1] - out[-2][1]) - (out[-1][1] - out[-2][1]) * (p[0] - out[-2][0]) <= 0:
                out.pop()
            out.append(p)
        return out[:-1]

    return half(pts) + half(reversed(pts))


def mask_points(frames, bx, by):
    """Corners of every mask pixel of the frames, with the sprite box at (bx, by)."""
    pts = []
    for on, mask in frames:
        for y, r in enumerate(mask):
            for x, v in enumerate(r):
                if v:
                    pts += [(bx + x, by + y), (bx + x + 1, by + y), (bx + x, by + y + 1), (bx + x + 1, by + y + 1)]
    return pts


def build():
    sp = {n: convert.convert(s) for n, s in convert.GAMES["pinball"].items()}

    # the room: side walls, rounded top corners, open at the bottom
    c = CORNER
    room = (
        [(0.5, TH + 30)]
        + arc(0.5 + c, 0.5 + c, c, 180, 270)
        + arc(TW - 0.5 - c, 0.5 + c, c, 270, 360)
        + [(TW - 0.5, TH + 30)]
    )
    thin = [
        (WALL, (LANE, LANE_TOP), (LANE, TH + 30)),
        (DEAD, (LANE, PLUNGER_Y), (TW - 0.5, PLUNGER_Y)),
    ]
    polys = []  # (kind, points, how it is drawn)

    # aprons: a slope from each side wall to the flipper's top face, then under the flipper
    # to the drain. The right one is the left one mirrored.
    rest = math.radians(FLIP_REST)
    tip_x = PIV_L + FLIP_LEN * math.cos(rest)
    tip_y = PIV_Y + FLIP_LEN * math.sin(rest)
    drain_l = round(tip_x) + 0.5
    left = [(0.5, SLOPE_Y), (PIV_L, PIV_Y - 1), (PIV_L, PIV_Y + 4), (drain_l, tip_y + 6), (drain_l, TH + 30), (0.5, TH + 30)]
    polys.append((DEAD, left, "apron"))
    polys.append((DEAD, [(2 * MID - x, y) for x, y in left], "apron"))

    # the mushroom on a tuft, centre; the tuft's underside is an ordinary wall
    w, h, ox, frames = sp["mushroom"]
    idle = frames[:4]
    pts = mask_points(idle, 0, 0)
    mush_x = round(MID - (min(p[0] for p in pts) + max(p[0] for p in pts)) / 2) - ox
    pts = mask_points(idle, mush_x + ox, MUSH_FEET - h)
    polys.append((MUSH, hull(pts), None))
    base = [p[0] for p in pts if p[1] == MUSH_FEET]
    polys.append((WALL, [(min(base) - 1, MUSH_FEET), (max(base) + 1, MUSH_FEET), (max(base) + 1, MUSH_FEET + 2), (min(base) - 1, MUSH_FEET + 2)], "solid"))

    # wisps: a circle round the body of the first idle frame
    w, h, ox, frames = sp["wisp"]
    pts = mask_points(frames[:1], 0, 0)
    cx = (min(p[0] for p in pts) + max(p[0] for p in pts)) / 2
    cy = (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2
    wisp_boxes = [(round(x - cx), round(y - cy)) for x, y in WISPS]
    circles = [(WISP, bx + cx, by + cy, WISP_R) for bx, by in wisp_boxes]
    circles.append((MOONK, MOON[0] + 4.5, MOON[1] + 4.5, 4.5))

    w, h, ox, frames = sp["red_idle"]
    red_x = int(LANE) - w - ox
    wolf_x = 0

    def dist(px, py):
        """Distance from a point to the nearest thing the ball bounces off, and its kind."""
        best = (-poly_sdf(px, py, room), WALL)
        for kind, a, b in thin:
            best = min(best, (seg_dist(px, py, a, b), kind))
        for kind, pts, how in polys:
            best = min(best, (poly_sdf(px, py, pts), kind))
        for kind, x, y, r in circles:
            best = min(best, (math.hypot(px - x, py - y) - r, kind))
        return best

    palette = {}
    cells = bytearray(TW * TH)
    art = [[0] * TW for _ in range(TH)]
    free = []
    for y in range(TH):
        for x in range(TW):
            px, py = x + 0.5, y + 0.5
            d, kind = dist(px, py)
            if d < R:
                e = 0.05
                gx = dist(px + e, py)[0] - dist(px - e, py)[0]
                gy = dist(px, py + e)[0] - dist(px, py - e)[0]
                a = round(math.atan2(gy, gx) / (2 * math.pi) * DIRS) % DIRS if gx or gy else DIRS * 3 // 4
                cells[y * TW + x] = palette.setdefault((kind, a), len(palette) + 1)
            elif d > 5:
                free.append((x, y))
            lit = abs(poly_sdf(px, py, room)) <= 0.5 or any(seg_dist(px, py, a, b) <= 0.5 for kind, a, b in thin)
            for kind, pts, how in polys:
                if how:
                    s = poly_sdf(px, py, pts)
                    if s <= 0 and (how == "solid" or s > -1):
                        lit = True
            # the moon: a crescent, the same one as in the other games' sky
            mx, my = x - MOON[0], y - MOON[1]
            if (mx - 4) ** 2 + (my - 4) ** 2 <= 18 and (mx - 7) ** 2 + (my - 3) ** 2 > 14:
                lit = True
            art[y][x] = 1 if lit else 0
    assert len(palette) < 256, len(palette)

    # a few stars, so the scrolling shows where there is nothing else to see
    rnd = random.Random(5)
    for x, y in rnd.sample([p for p in free if p[1] < SLOPE_Y and p[0] < LANE - 4], 22):
        art[y][x] = 1

    angles = [FLIP_REST]
    for s in FLIP_STEPS:
        angles.append(angles[-1] - s)
    table = b"".join(
        struct.pack("<hh", round(256 * math.cos(math.radians(a))), round(256 * math.sin(math.radians(a)))) for a in angles
    ) + bytes(round(2 * math.radians(s) * 256) for s in FLIP_STEPS)

    header = bytes([
        TH, len(palette), wolf_x + sp["wolf_idle"][2], WOLF_FEET,
        wisp_boxes[0][0], wisp_boxes[0][1], wisp_boxes[1][0], wisp_boxes[1][1],
        mush_x + sp["mushroom"][2], MUSH_FEET, PIV_L, PIV_R, PIV_Y, FLIP_LEN,
        int(LANE) + 4, PLUNGER_Y, red_x + sp["red_idle"][2], RED_FEET, MOON[0], MOON[1],
        TARGETS[0], TARGETS[1], TARGETS[2],
    ]).ljust(24, b"\0")
    pal = bytearray()
    for (kind, a), i in sorted(palette.items(), key=lambda kv: kv[1]):
        t = a * 2 * math.pi / DIRS
        pal += struct.pack("<Bbb", kind, round(127 * math.cos(t)), round(127 * math.sin(t)))
    with open(os.path.join(ROOT, "pinball.bin"), "wb") as f:
        f.write(header + table + pal + convert.pack(art, TW) + cells)
    print("pinball.bin", len(header + table + pal) + TW // 8 * TH + len(cells), "bytes, palette", len(palette))
    print("wolf", wolf_x, "wisps", wisp_boxes, "mushroom", mush_x, "red", red_x)

    # preview: walls white, blocked band tinted by kind, sprites and both flipper positions
    tint = {WALL: (70, 30, 30), DEAD: (30, 30, 80), WISP: (20, 70, 70), MUSH: (80, 30, 80), MOONK: (80, 70, 20)}
    kinds = {i: k for (k, a), i in palette.items()}
    pv = Image.new("RGB", (TW, TH), (0, 0, 0))
    for y in range(TH):
        for x in range(TW):
            if art[y][x]:
                pv.putpixel((x, y), (255, 255, 255))
            elif cells[y * TW + x]:
                pv.putpixel((x, y), tint[kinds[cells[y * TW + x]]])

    def stamp(name, bx, by, i=0):
        w, h, ox, frames = sp[name]
        on, mask = frames[i]
        for y in range(h):
            for x in range(w):
                if 0 <= bx + x < TW and 0 <= by + y < TH and mask[y][x]:
                    pv.putpixel((bx + x, by + y), (255, 255, 255) if on[y][x] else (60, 60, 60))

    stamp("wolf_idle", wolf_x + sp["wolf_idle"][2], WOLF_FEET - sp["wolf_idle"][1])
    stamp("mushroom", mush_x + sp["mushroom"][2], MUSH_FEET - sp["mushroom"][1])
    for bx, by in wisp_boxes:
        stamp("wisp", bx, by)
    stamp("red_idle", red_x + sp["red_idle"][2], RED_FEET - sp["red_idle"][1])
    for ty in TARGETS:
        for y in range(ty, ty + TARGET_H):
            for x in range(TARGET_W):
                pv.putpixel((1 + x, y), (255, 160, 0))
                pv.putpixel((int(LANE) - 1 - x, y), (255, 160, 0))
    for a, col in ((angles[0], (0, 255, 0)), (angles[-1], (0, 120, 0))):
        for i in range(FLIP_LEN * 2 + 1):
            dx = i / 2 * math.cos(math.radians(a))
            y = int(PIV_Y + i / 2 * math.sin(math.radians(a)))
            pv.putpixel((int(PIV_L + dx), y), col)
            pv.putpixel((int(PIV_R - dx), y), col)
    pv.resize((TW * 6, TH * 6), Image.NEAREST).save(os.path.join(ROOT, "art", "table_pinball.png"))


if __name__ == "__main__":
    build()

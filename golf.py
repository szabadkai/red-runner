"""TINY GOLF: nine short holes seen from the side, one gesture per shot.

The aim arrow sweeps up and down by itself. Press to lock it, keep holding to wind up (the
arrow grows, and shrinks again if you hold too long), let go to hit. Red swings her basket.

Mushrooms throw the ball back up, brambles stop it dead and take the sting out of the next
shot, water costs a stroke and puts the ball back, and on the last hole the wolf sits in
front of the flag. Nine strokes on a hole and it is picked up as a ten. The score is the
strokes for the round, so lower is better.
"""
import framebuf
from micropython import const

import sprites_golf as sprites
from engine import Anim, Rng, hud, num, text

W = const(72)
H = const(40)
G = const(13)  # gravity per tick, 1/256 px
E_GROUND = const(77)  # bounce off the ground, /256
GRIP = const(150)  # how much of its speed along the ground a landing takes off, /256
E_WALL = const(115)  # ... off a cliff face or the wolf
KICK = const(400)  # the least a mushroom throws the ball back with
V0 = const(90)  # speed of the softest shot ...
V_STEP = const(10)  # ... and what each step of power adds: 2.2 px per tick flat out
POWER_MAX = const(48)
AIM_TICKS = const(4)  # ticks the arrow rests on each of its 16 angles
REST2 = const(900)  # speed squared under which a ball on level ground stops
MAX_STROKES = const(9)
CUP_HALF = const(2)
CUP_DEPTH = const(5)

GROUND = const(0)
BOUNCY = const(1)  # a mushroom
STICKY = const(2)  # brambles
BEAST = const(3)  # the wolf
WET = const(4)  # a pond

TITLE = const(0)
INTRO = const(1)
AIM = const(2)
CHARGE = const(3)
SWING = const(4)
FLY = const(5)
SPLASH = const(6)
HOLED = const(7)
OVER = const(8)

# the 16 aim angles, 8 to 83 degrees, /256
_COS = (254, 249, 243, 236, 226, 215, 202, 187, 171, 154, 136, 116, 96, 75, 53, 31)
_SIN = (36, 58, 79, 100, 120, 139, 158, 175, 190, 204, 217, 228, 237, 245, 250, 254)
# which way the ground faces where it climbs s px over two columns, s from -8 to 8, /256
_NX = (-248, -246, -243, -238, -229, -213, -181, -114, 0, 114, 181, 213, 229, 238, 243, 246, 248)
_NY = (-62, -70, -81, -95, -114, -142, -181, -229, -256, -229, -181, -142, -114, -95, -81, -70, -62)

# par, tee x, cup x, water level (0 for none), ground as x, y corners, things as kind, x
HOLES = (
    (2, 12, 58, 0, b"\x00\x1f\x47\x1f", b""),
    (2, 12, 60, 0, b"\x00\x1f\x18\x1f\x22\x15\x2c\x1f\x47\x1f", b""),
    (2, 12, 62, 32, b"\x00\x1d\x14\x1d\x19\x25\x2b\x25\x30\x1d\x47\x1d", b""),
    (3, 12, 62, 0, b"\x00\x23\x2a\x23\x2f\x11\x47\x11", b"\x01\x0e"),
    (2, 12, 64, 0, b"\x00\x1b\x10\x1b\x18\x22\x30\x22\x38\x1b\x47\x1b", b"\x02\x16"),
    (3, 12, 60, 0, b"\x00\x21\x1c\x21\x20\x0f\x28\x0f\x2c\x1b\x47\x1b", b""),
    (3, 10, 65, 31, b"\x00\x1c\x0e\x1c\x12\x24\x1b\x24\x1f\x1c\x29\x1c\x2d\x24\x36\x24\x3a\x1c\x47\x1c", b""),
    (2, 12, 49, 0, b"\x00\x1e\x10\x1e\x1c\x0d\x24\x0d\x2c\x21\x36\x21\x3c\x1e\x47\x1e", b""),
    (3, 12, 67, 0, b"\x00\x1f\x47\x1f", b"\x03\x1e"),
)
_WORDS = (b"EAGLE", b"BIRDIE", b"PAR", b"BOGEY", b"DOUBLE")


class Game:
    def __init__(self, fb, best=0, seed=1):
        self.fb = fb
        self.best = best  # fewest strokes for a round, 0 before the first one
        self.rng = Rng(seed)
        self.stir = self.rng.stir
        self.red_idle = (Anim(sprites.red_idle), Anim(sprites.red_idle_l))
        self.red_swing = (Anim(sprites.red_swing), Anim(sprites.red_swing_l))
        self.things = (None, Anim(sprites.mushroom), Anim(sprites.brambles), Anim(sprites.wolf_idle))
        self.wolf_hit = Anim(sprites.wolf_hit)
        self.art = framebuf.FrameBuffer(bytearray(W // 8 * H), W, H, framebuf.MONO_HLSB)
        self.h = [0] * W  # the ground: the first solid row of each column
        self.hc = [0] * W  # the same with mushroom and wolf standing on it
        self.mat = bytearray(W)
        self.score_text = "0"
        self.state = TITLE
        self.menu = True
        self.t = 0
        self.led = False
        self.flash = 0
        self.prev = False
        self.score = 0
        self.new_best = False
        self._load(0)
        self.state = TITLE

    # ---- holes -----------------------------------------------------------

    def _load(self, n):
        """Lay out hole n: ground, cup, things standing on it, and the picture of it all."""
        par, tee, cup, water, pts, objs = HOLES[n]
        h = self.h
        hc = self.hc
        mat = self.mat
        for i in range(0, len(pts) - 2, 2):
            x0 = pts[i]
            y0 = pts[i + 1]
            x1 = pts[i + 2]
            dy = pts[i + 3] - y0
            for x in range(x0, x1 + 1):
                h[x] = y0 + dy * (x - x0) // (x1 - x0)
        for x in range(W):
            mat[x] = WET if water and h[x] > water else GROUND
        rim = h[cup]
        for x in range(cup - CUP_HALF, cup + CUP_HALF + 1):
            h[x] = rim + CUP_DEPTH
        for x in range(W):
            hc[x] = h[x]
        self.hole = n
        self.par = par
        self.cup = cup
        self.rim = rim
        self.water = water
        self.objs = objs
        self.obj_t = 0  # ticks a mushroom stays puffed or the wolf yelps
        # a thing blocks the ball up to the top of its outline in each column
        for i in range(0, len(objs), 2):
            kind = objs[i]
            a = self.things[kind]
            x0 = objs[i + 1] + a.ox
            top = h[x0 + a.w // 2] - a.h
            m = a.mask[0]
            for cx in range(a.w):
                for cy in range(a.h):
                    if m.pixel(cx, cy):
                        mat[x0 + cx] = kind
                        if kind != STICKY and top + cy < hc[x0 + cx]:
                            hc[x0 + cx] = top + cy
                        break

        art = self.art
        art.fill(0)
        for x in range(W):
            y = h[x]
            if mat[x] == WET:
                # a pond: its surface, and ripples below
                art.pixel(x, water, 1)
                for wy in range(water + 2, H, 3):
                    if (x + wy) & 3 == 0:
                        art.hline(x, wy, 2, 1)
                continue
            # the ground: a line with a stipple under it; cliff faces drawn solid
            y1 = h[x + 1] if x < W - 1 else y
            art.vline(x, y, (y1 - y if y1 > y else 0) + 1, 1)
            y0 = h[x - 1] if x else y
            if y0 > y:
                art.vline(x, y, y0 - y + 1, 1)
            for gy in range((y + 2) | 1, H, 2):  # odd rows, so the stipple lines up between columns
                if (x + gy) & 3 == 0:
                    art.pixel(x, gy, 1)
        # the flag
        art.vline(cup, rim - 9, 9 + CUP_DEPTH, 1)
        art.hline(cup + 1, rim - 9, 3, 1)
        art.hline(cup + 1, rim - 8, 2, 1)
        art.pixel(cup + 1, rim - 7, 1)

        self.strokes = 0
        self.rough = False
        self.x = tee << 8
        self.y = (h[tee] << 8) - 1
        self.vx = 0
        self.vy = 0
        self._ready()

    def _ready(self):
        """The ball is at rest: Red steps up to it and the arrow starts sweeping."""
        self.lx = self.x
        self.ly = self.y
        self.dir = 1 if self.cup >= self.x >> 8 else -1
        self.at = 0
        self.aim = 0
        self.power = 0
        self.pt = 0
        self.still = 0
        self.led = False
        self.state = AIM
        self.t = 0

    # ---- update ----------------------------------------------------------

    def tick(self, pressed):
        edge = pressed and not self.prev
        self.prev = pressed
        self.t += 1
        if self.flash:
            self.flash -= 1
        if self.obj_t:
            self.obj_t -= 1
        s = self.state
        if s == AIM:
            if edge:
                self.state = CHARGE
                self.pt = 0
                self.power = 0
            else:
                # the arrow climbs through the 16 angles and comes back down
                self.at += 1
                p = self.at // AIM_TICKS % 30
                self.aim = p if p < 16 else 30 - p
        elif s == CHARGE:
            if pressed:
                self.pt += 1
                p = self.pt % (2 * POWER_MAX)
                self.power = p if p <= POWER_MAX else 2 * POWER_MAX - p
            else:
                self.strokes += 1
                self.state = SWING
                self.t = 0
        elif s == SWING:
            if self.t == 4:
                self._launch(self.aim, self.power)
        elif s == FLY:
            self._fly()
        elif s == INTRO:
            if self.t >= 70:
                self._ready()
        elif s == SPLASH:
            if self.t >= 45:
                self.x = self.lx
                self.y = self.ly
                self._after()
        elif s == HOLED:
            self.led = (self.t >> 3) & 1 == 0
            if self.t >= 90:
                self.led = False
                self.score += self.strokes
                if self.hole + 1 < len(HOLES):
                    self._load(self.hole + 1)
                    self.state = INTRO
                    self.t = 0
                else:
                    if self.best == 0 or self.score < self.best:
                        self.best = self.score
                        self.new_best = True
                    self.score_text = str(self.score)
                    self.state = OVER
                    self.menu = True
                    self.t = 0
        elif edge and self.t > 30:  # TITLE or OVER
            self.score = 0
            self.new_best = False
            self._load(0)
            self.state = INTRO
            self.menu = False
            self.t = 0

    def _launch(self, aim, power):
        v = V0 + (power if power > 1 else 1) * V_STEP
        if self.rough:
            v = v * 5 >> 3  # out of the brambles
            self.rough = False
        self.vx = self.dir * (_COS[aim] * v >> 8)
        self.vy = -(_SIN[aim] * v >> 8)
        self.y -= 256
        self.still = 0
        self.state = FLY
        self.t = 0

    def _after(self):
        """The ball has stopped, or come back from the water: what next?"""
        if self.strokes >= MAX_STROKES:
            self.strokes = MAX_STROKES + 1  # picked up
            self.state = HOLED
            self.t = 0
        else:
            self._ready()

    def _fly(self):
        hc = self.hc
        x = self.x
        y = self.y
        vx = self.vx
        vy = self.vy + G
        water = self.water
        touched = False
        s = 0
        for sub in range(3):
            nx = x + vx // 3
            ny = y + vy // 3
            c = nx >> 8
            if c < 0 or c >= W:
                vx = 0  # the edge of the screen: the ball drops straight down
                continue
            if self.mat[c] == WET and ny >> 8 >= water:
                self.x = nx
                self.y = water << 8
                self.strokes += 1
                self.flash = 3
                self.state = SPLASH
                self.t = 0
                return
            g = hc[c]
            if ny >> 8 < g:
                x = nx
                y = ny
                continue
            if (y >> 8) - g > 1:
                vx = -(vx * E_WALL >> 8)  # ground more than two rows higher: a cliff face
                continue
            touched = True
            m = self.mat[c]
            if m == STICKY:
                # brambles: the ball drops into them and stays
                self.x = nx
                self.y = (g << 8) - 1
                self.vx = self.vy = 0
                self.rough = True
                self._after()
                return
            s = (hc[c + 1] if c < W - 1 else g) - (hc[c - 1] if c else g)
            s = -8 if s < -8 else 8 if s > 8 else s
            ax = _NX[s + 8]
            ay = _NY[s + 8]
            dot = (vx * ax + vy * ay) >> 8  # speed into the ground, negative
            if dot < 0:
                if m == GROUND:
                    j = -dot - (dot * E_GROUND >> 8)
                    if dot < -60:
                        # a landing, not a roll: the turf grips the ball
                        k = ((vy * ax - vx * ay) >> 8) * GRIP >> 8
                        vx += k * ay >> 8
                        vy -= k * ax >> 8
                else:
                    self.obj_t = 30
                    if m == BOUNCY:
                        j = -dot + (-dot if -dot > KICK else KICK)
                    else:
                        j = -dot - (dot * E_WALL >> 8)
                vx += j * ax >> 8
                vy += j * ay >> 8
            x = nx
            y = (g << 8) - 1
        if touched:
            # rolling: the ground takes a little speed off every tick
            vx -= (vx + 4) >> 3
            vy -= (vy + 4) >> 3
            if s == 0 and vx * vx + vy * vy < REST2:
                self.still += 1
            else:
                self.still = 0
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        if self.still >= 8 or self.t > 900:
            self.vx = self.vy = 0
            c = x >> 8
            if self.cup - CUP_HALF <= c <= self.cup + CUP_HALF and y >> 8 > self.rim + 1:
                self.flash = 4
                self.state = HOLED
                self.t = 0
            else:
                self._after()

    # ---- drawing ---------------------------------------------------------

    def _red(self, a, f, cell):
        """Draw Red with her source cell at x = cell, standing on the ground under her."""
        x = cell + 16
        x = 0 if x < 0 else W - 1 if x >= W else x
        a.draw(self.fb, f, cell + a.ox, self.h[x] - a.h)

    def draw(self):
        fb = self.fb
        s = self.state
        t = self.t
        if s == TITLE or s == OVER:
            fb.fill(0)
            fb.hline(0, 37, W, 1)
            a = self.red_idle[0]
            a.draw(fb, (t >> 4) & 3, 6 + a.ox, 37 - a.h)
            fb.vline(56, 23, 14, 1)  # a flag
            fb.hline(57, 23, 3, 1)
            fb.hline(57, 24, 2, 1)
            fb.pixel(57, 25, 1)
            fb.fill_rect(32, 35, 2, 2, 1)
            if s == TITLE:
                p = (t >> 7) % 3
                if p == 0:
                    fb.text("TINY GOLF", 0, 1, 1)
                elif p == 1:
                    text(fb, b"PRESS LOCKS AIM", 6, 3)
                else:
                    text(fb, b"HOLD FOR POWER", 8, 3)
                if (t >> 5) & 1 == 0:
                    text(fb, b"PRESS", 30, 14)
                return
            fb.text(self.score_text, 36 - 4 * len(self.score_text), 2, 1)
            if self.new_best:
                if (t >> 4) & 1 == 0:
                    text(fb, b"NEW BEST", 22, 12)
            else:
                text(fb, b"BEST", 26, 12)
                num(fb, self.best, 52, 12)
            return

        fb.blit(self.art, 0, 0)
        objs = self.objs
        for i in range(0, len(objs), 2):
            kind = objs[i]
            a = self.things[kind]
            f = 0
            if kind == BOUNCY:
                f = 4 if self.obj_t else (t >> 4) & 3
            elif kind == BEAST:
                if self.obj_t:
                    a = self.wolf_hit
                    f = (self.obj_t >> 3) & 1
                else:
                    f = (t >> 4) & 3
            x = objs[i + 1]
            a.draw(fb, f, x + a.ox, self.h[x + self.things[kind].ox + self.things[kind].w // 2] - a.h)

        bx = self.x >> 8
        by = self.y >> 8
        left = 0 if self.dir > 0 else 1
        # Red stands where the ball last lay, with it in front of her feet
        cell = (self.lx >> 8) - (18 if self.dir > 0 else 13)
        if s == SWING:
            self._red(self.red_swing[left], 2 + (t >> 1), cell)
        elif s == CHARGE:
            self._red(self.red_swing[left], 0 if self.power < 24 else 1, cell)
        elif s == FLY and t < 10:
            self._red(self.red_swing[left], 5, cell)
        else:
            self._red(self.red_idle[left], (t >> 4) & 3, cell)
        if s == AIM or s == CHARGE:
            # the arrow: longer with more power
            dx = _COS[self.aim] * self.dir
            dy = -_SIN[self.aim]
            for i in range(2, 5 + (self.power >> 3)):
                fb.pixel(bx + (dx * i * 2 >> 8), by - 1 + (dy * i * 2 >> 8), 1)
            if s == CHARGE:
                fb.fill_rect(0, 38, self.power * W // POWER_MAX, 2, 1)
        if s == SPLASH:
            # rings where it went in
            r = t >> 2
            fb.hline(bx - r, by, 2, 1)
            fb.hline(bx + r, by, 2, 1)
        elif by < 1:
            fb.vline(bx, 0, 3, 1)  # the ball is above the screen
        else:
            fb.fill_rect(bx - 1, by - 1, 2, 2, 0 if (s == HOLED and self.strokes > MAX_STROKES) else 1)

        fb.fill_rect(0, 0, 19, 7, 0)
        text(fb, b"H", 1, 1)
        num(fb, self.hole + 1, 7, 1)
        text(fb, b"P", 11, 1)
        num(fb, self.par, 17, 1)
        hud(fb, self.strokes)
        if s == INTRO:
            fb.fill_rect(18, 12, 36, 9, 0)
            fb.rect(18, 12, 36, 9, 1)
            text(fb, b"HOLE", 24, 14)
            num(fb, self.hole + 1, 46, 14)
        elif s == HOLED and (t >> 3) & 1:
            d = self.strokes - self.par
            if self.strokes > MAX_STROKES:
                w = b"PICKED UP"
            elif self.strokes == 1:
                w = b"ACE!"
            elif d > 2:
                w = b"OUCH"
            else:
                w = _WORDS[d + 2 if d > -2 else 0]
            n = len(w) * 4
            fb.fill_rect(35 - n // 2 - 2, 12, n + 3, 9, 0)
            text(fb, w, 36 - n // 2, 14)

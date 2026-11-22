"""PINBALL: a table in the night wood, taller than the screen, scrolling with the ball.

Hold the button to wind up the launch and let go; from then on the button works both
flippers. For the first seconds after a launch a net across the drain throws the ball back.
The wolf waits beside the drain for the balls that get past; Red watches from the other side.
Three balls.

What is on the table, and how one thing leads to the next:

  drop targets  three on each side wall, 2 points each. Knocking down all three on a side
                pays 5 and wakes the wisp on that side; then they stand up again.
  wisps         bump the ball: 1 point asleep, 3 awake (they flicker). They stay awake until
                the jackpot.
  mushroom      bumps the ball harder, 2 points.
  moon          2 points; but with both wisps awake it is lit (it blinks, and so does the
                board's LED) and the next hit is the jackpot: 20 points, everything is worth
                one more times over from then on (up to x5), the net comes back, and every
                second jackpot gives a ball back.

A bumper that has just thrown the ball takes a moment to settle before it will again.

The table comes from tools/table.py as pinball.bin: the wall art, and a map that says for
every pixel whether the ball's centre is blocked there and which way the surface faces.
"""
import struct

import framebuf
from micropython import const

import sprites_pinball as sprites
from engine import Anim, Rng, hearts, hud, num, text

TW = const(72)
VIEW = const(40)
G = const(5)  # gravity per tick, 1/256 px
DRAG = const(7)  # each tick takes v >> DRAG off the speed, so the ball falls at G << DRAG at most
VX_MAX = const(620)
VY_MAX = const(950)
RF = const(896)  # ball radius plus half a flipper's thickness: 3.5 px
RF2 = const(896 * 896)
E_FLIP = const(90)  # how much of the bounce a flipper gives back, /256
FLIP_POWER = const(200)  # how much of its own speed a flipper passes on, /256
KICK_WISP = const(260)  # the speed a bumper throws the ball at, plus up to a quarter pixel
KICK_MUSH = const(330)
WISP_REST = const(60)  # ticks before a bumper that has thrown the ball will throw it again
MUSH_REST = const(90)
CHARGE_MAX = const(40)  # ticks of holding for the hardest launch
LAUNCH0 = const(720)  # a tap clears the lane; holding adds to it
LAUNCH_K = const(6)
NET_KICK = const(700)
SAVE_TICKS = const(600)
BALLS = const(3)
LANE = const(65 << 8)  # the launch lane is right of this
GATE = const(62 << 8)  # as far right as a ball in play gets: a one-way gate shuts the lane
MID = const(8320)  # 32.5 px: the playfield's centre line
TL = const(6 << 8)  # a ball this far left is against a standing target on the left wall ...
TR = const(59 << 8)  # ... and this far right against one on the right
T_HALF = const(1152)  # ... if it is within 4.5 px of the target's middle
JACKPOT = const(20)

WALL = const(1)
DEAD = const(2)
WISP = const(3)
MUSH = const(4)
MOON = const(5)

TITLE = const(0)
PLAY = const(1)
LOST = const(2)
OVER = const(3)

# the ball: a 5 px disc, with a 1 px dark rim so it shows against the walls
_BALL = (7, 7, 0, ((b"\x00\x38\x7c\x7c\x7c\x38\x00", b"\x38\x7c\xfe\xfe\xfe\x7c\x38"),))
# the full moon that shows for a moment when the crescent is hit
_FULL = b"\x1c\x00\x7f\x00\x7f\x00\xff\x80\xff\x80\xff\x80\x7f\x00\x7f\x00\x1c\x00"
_MOON = (9, 9, 0, ((_FULL, _FULL),))


def _isqrt(n):
    x = 1024  # more than the root of anything passed in
    while True:
        y = (x + n // x) >> 1
        if y >= x:
            return x
        x = y


class Game:
    def __init__(self, fb, best=0, seed=1):
        self.fb = fb
        self.best = best
        self.rng = Rng(seed)
        self.stir = self.rng.stir
        with open("pinball.bin", "rb") as f:
            hd = f.read(24)
            tb = f.read(44)
            pal = f.read(hd[1] * 3)
            art = bytearray(TW // 8 * hd[0])
            f.readinto(art)
            self.map = f.read()
        th = hd[0]
        self.art = framebuf.FrameBuffer(art, TW, th, framebuf.MONO_HLSB)
        self.lim = (hd[12] + 16) << 8  # a ball in play is lost below this, level with the wolf's jaws
        self.end = (th - 1) << 8
        self.cam_max = (th - VIEW) << 8
        # what the map's values mean: a kind and the way the surface faces, /127
        self.pk = bytes([0]) + bytes(pal[i] for i in range(0, len(pal), 3))
        self.pnx = tuple([0] + [pal[i] - 256 if pal[i] > 127 else pal[i] for i in range(1, len(pal), 3)])
        self.pny = tuple([0] + [pal[i] - 256 if pal[i] > 127 else pal[i] for i in range(2, len(pal), 3)])
        self.wolf_x = hd[2] - sprites.wolf_idle[2]  # x of the sprites' 32 px source cell
        self.wolf_y = hd[3]
        self.wisp_x = (hd[4], hd[6])
        self.wisp_y = (hd[5], hd[7])
        self.mush_x = hd[8] - sprites.mushroom[2]
        self.mush_y = hd[9]
        self.plx = hd[10] << 8  # flipper pivots
        self.prx = hd[11] << 8
        self.py = hd[12] << 8
        self.flen = hd[13] << 8
        self.fl_top = (hd[12] - 24) << 8  # the flippers cannot reach a ball above this
        self.net_y = (hd[12] + 12) << 8
        self.serve_x = hd[14] << 8
        self.serve_y = (hd[15] - 3) << 8
        self.red_x = hd[16] - sprites.red_idle[2]
        self.red_y = hd[17]
        self.moon_x = hd[18]
        self.moon_y = hd[19]
        self.tg_top = (hd[20], hd[21], hd[22])  # drop targets: the same rows on both walls
        self.tg_y = tuple((hd[20 + i] + 2) << 8 for i in range(3))
        self.tg = [True] * 6  # standing; 0-2 on the left wall, 3-5 on the right
        self.bank_t = [0, 0]  # ticks until a cleared bank stands up again
        self.awake = [False, False]  # the wisps
        # a flipper's direction from its pivot in each of its 9 positions, /256 (the left
        # one; the right one is its mirror image), and how fast each step turns it
        v = struct.unpack("<18h", tb)
        self.ux = tuple(v[i] for i in range(0, 18, 2))
        self.uy = tuple(v[i] for i in range(1, 18, 2))
        self.sw = bytes(b * FLIP_POWER >> 8 for b in tb[36:])
        self.tipx = tuple((hd[13] * u) >> 8 for u in self.ux)
        self.tipy = tuple((hd[13] * u) >> 8 for u in self.uy)
        self.ball = Anim(_BALL)
        self.full = Anim(_MOON)
        self.wolf_idle = Anim(sprites.wolf_idle)
        self.wolf_bite = Anim(sprites.wolf_bite)
        self.wisp = Anim(sprites.wisp)
        self.mush = Anim(sprites.mushroom)
        self.red_idle = Anim(sprites.red_idle)
        self.red_jump = Anim(sprites.red_jump)
        self.red_hit = Anim(sprites.red_hit)
        self.red_death = Anim(sprites.red_death)
        self.wisp_t = [0, 0]
        self.score_text = "0"
        self.state = TITLE
        self.menu = True
        self.t = 0
        self.led = False
        self.flash = 0
        self.prev = False
        self._reset()

    def _reset(self):
        self.score = 0
        self.hearts = BALLS
        self.new_best = False
        self.mult = 1
        self.jackpots = 0
        self.moon_t = 0
        for i in range(6):
            self.tg[i] = True
        self.bank_t[0] = self.bank_t[1] = 0
        self.awake[0] = self.awake[1] = False
        self.mush_t = 0
        self.wisp_t[0] = self.wisp_t[1] = 0
        self.cam = self.cam_max
        self._serve()

    def _serve(self):
        self.x = self.serve_x
        self.y = self.serve_y
        self.vx = 0
        self.vy = 0
        self.flip = 0  # 0 at rest .. 8 fully up
        self.charge = 0
        self.live = False  # the ball has left the launch lane
        self.save = 0  # ticks of net left
        self.still = 0
        self.red_t = 0
        self.led_t = 0

    # ---- update ----------------------------------------------------------

    def tick(self, pressed):
        edge = pressed and not self.prev
        self.prev = pressed
        self.t += 1
        if self.flash:
            self.flash -= 1
        s = self.state
        if s == PLAY:
            self._play(pressed)
        elif s == LOST:
            self.led = (self.t >> 3) & 1 == 0
            if self.t >= 60:
                self.led = False
                self.t = 0
                if self.hearts:
                    self._serve()
                    self.state = PLAY
                else:
                    if self.score > self.best:
                        self.best = self.score
                        self.new_best = True
                    self.score_text = str(self.score)
                    self.state = OVER
                    self.menu = True
        elif edge and self.t > 30:
            self._reset()
            self.state = PLAY
            self.menu = False
            self.t = 0

    def _bump(self, k, nx):
        """Score a hit on a wisp, the mushroom or the moon.

        Returns the speed a bumper throws the ball at, or -1 for an ordinary bounce.
        """
        r = self.rng.next() & 63
        if k == WISP:
            i = 0 if nx < MID else 1
            if self.wisp_t[i]:
                return -1  # still settling from the last hit
            self.wisp_t[i] = WISP_REST
            self.led_t = 5
            if self.awake[i]:
                self.score += 3 * self.mult
                return KICK_WISP + 100 + r
            self.score += self.mult
            return KICK_WISP + r
        if k == MUSH:
            if self.mush_t:
                return -1  # still puffed up
            self.mush_t = MUSH_REST
            self.score += 2 * self.mult
            self.led_t = 5
            return KICK_MUSH + r
        self.led_t = 5
        if self.moon_t == 0:  # hits close together count once
            if self.awake[0] and self.awake[1]:
                self.score += JACKPOT * self.mult
                self.jackpots += 1
                if self.mult < 5:
                    self.mult += 1
                self.awake[0] = self.awake[1] = False
                self.save = SAVE_TICKS
                self.flash = 6
                if self.jackpots & 1 == 0 and self.hearts < BALLS:
                    self.hearts += 1
            else:
                self.score += 2 * self.mult
        self.moon_t = 30
        return -1

    def _target(self, i):
        """Knock drop target i down; the third of a bank wakes that side's wisp."""
        tg = self.tg
        tg[i] = False
        self.score += 2 * self.mult
        self.led_t = 5
        b = i - i % 3
        if not (tg[b] or tg[b + 1] or tg[b + 2]):
            self.score += 5 * self.mult
            self.awake[b // 3] = True
            self.bank_t[b // 3] = 60

    def _play(self, pressed):
        m = self.map
        pnx = self.pnx
        pny = self.pny
        x = self.x
        y = self.y
        vx = self.vx
        vy = self.vy
        f = self.flip
        if self.moon_t:
            self.moon_t -= 1
        if self.mush_t:
            self.mush_t -= 1
        if self.wisp_t[0]:
            self.wisp_t[0] -= 1
        if self.wisp_t[1]:
            self.wisp_t[1] -= 1
        if self.red_t:
            self.red_t -= 1
        if self.led_t:
            self.led_t -= 1
        lit = self.awake[0] and self.awake[1]
        self.led = self.led_t > 0 or (lit and self.t & 16 != 0)
        for i in range(2):
            if self.bank_t[i]:
                self.bank_t[i] -= 1
                if self.bank_t[i] == 0:
                    self.tg[i * 3] = self.tg[i * 3 + 1] = self.tg[i * 3 + 2] = True

        # the plunger: wind up while the ball sits on it, launch on release
        ready = x > LANE and y > self.serve_y - 256 and -100 < vy < 100
        if ready and pressed:
            if self.charge < CHARGE_MAX:
                self.charge += 1
        elif self.charge:
            if ready:
                vy = -(LAUNCH0 + self.charge * LAUNCH_K)
                self.red_t = 24
            self.charge = 0
        if self.live:
            if self.save:
                self.save -= 1
        elif x < GATE - 512:
            self.live = True
            self.save = SAVE_TICKS

        vy += G
        vx -= (vx + 64) >> DRAG  # rounded, so that it slows both directions alike
        vy -= (vy + 64) >> DRAG
        if vx > VX_MAX:
            vx = VX_MAX
        elif vx < -VX_MAX:
            vx = -VX_MAX
        if vy > VY_MAX:
            vy = VY_MAX
        elif vy < -VY_MAX:
            vy = -VY_MAX

        lim = self.lim
        end = self.end
        fl_top = self.fl_top
        lost = False
        for sub in range(2):
            # the flippers turn one step each half tick; ws is how fast, signed
            ws = 0
            if pressed:
                if f < 8:
                    ws = self.sw[f]
                    f += 1
            elif f:
                f -= 1
                ws = -self.sw[f]
            nx = x + (vx >> 1)
            ny = y + (vy >> 1)
            if ny >= lim and nx < LANE:
                lost = True
                break
            c = m[(ny >> 8) * TW + (nx >> 8)]
            if c:
                ax = pnx[c]
                ay = pny[c]
                dot = (vx * ax + vy * ay + 64) >> 7  # speed into the surface, negative
                if dot < 0:
                    k = self.pk[c]
                    if k == WALL:
                        j = -dot - (dot >> 1)
                    elif k == DEAD:
                        j = -dot - (dot >> 2)
                    else:
                        j = self._bump(k, nx)
                        j = -dot - (dot >> 1) if j < 0 else j - dot
                    vx += (j * ax + 64) >> 7
                    vy += (j * ay + 64) >> 7
                i = 0
                while True:  # back out of the surface, half a pixel at a time
                    nx += ax
                    ny += ay
                    if ny >= end or not m[(ny >> 8) * TW + (nx >> 8)]:
                        break
                    i += 1
                    if i == 6:
                        nx = x
                        ny = y
                        break
            x = nx
            y = ny
            if x > GATE and self.live:
                x = GATE
                if vx > 0:
                    vx = -(vx >> 1)
            if (x < TL or x > TR) and x < LANE:
                # against a side wall: is a drop target standing there?
                b = 0 if x < MID else 3
                for i in range(3):
                    if self.tg[b + i] and -T_HALF < y - self.tg_y[i] < T_HALF:
                        self._target(b + i)
                        if b:
                            x = TR
                            vx = -(abs(vx) >> 1) - 150
                        else:
                            x = TL
                            vx = (abs(vx) >> 1) + 150
                        break
            if y > fl_top:
                # both flippers, worked out for the left one; the right one is mirrored
                ux = self.ux[f]
                uy = self.uy[f]
                flen = self.flen
                ry = y - self.py
                for side in range(2):
                    if side:
                        rx = self.prx - x
                        wx = -vx
                    else:
                        rx = x - self.plx
                        wx = vx
                    t = (rx * ux + ry * uy) >> 8  # how far along the flipper
                    if t <= -RF or t >= flen + RF:
                        continue
                    pen = 0
                    if 0 <= t <= flen:
                        d = (rx * uy - ry * ux) >> 8  # how far above its centre line
                        if -RF < d < RF:
                            vs = (t * ws) >> 8  # the flipper's own speed at that point
                            if d >= 0:
                                cnx = uy
                                cny = -ux
                                pen = RF - d
                            else:
                                cnx = -uy
                                cny = ux
                                pen = RF + d
                                vs = -vs
                    else:
                        # the rounded end at the pivot or the tip
                        tt = flen if t > 0 else 0
                        cx = rx - ((tt * ux) >> 8)
                        cy = ry - ((tt * uy) >> 8)
                        d2 = cx * cx + cy * cy
                        if d2 < RF2:
                            ln = _isqrt(d2) or 1
                            cnx = (cx << 8) // ln
                            cny = (cy << 8) // ln
                            pen = RF - ln
                            vs = (((tt * ws) >> 8) * (uy * cnx - ux * cny)) >> 16
                    if pen > 0:
                        vn = ((wx * cnx + vy * cny + 128) >> 8) - vs
                        if vn < 0:
                            j = -vn - ((vn * E_FLIP) >> 8)
                            wx += (j * cnx + 128) >> 8
                            vy += (j * cny + 128) >> 8
                        rx += (pen * cnx) >> 8
                        ry += (pen * cny) >> 8
                        y = self.py + ry
                        if side:
                            x = self.prx - rx
                            vx = -wx
                        else:
                            x = self.plx + rx
                            vx = wx
        self.flip = f

        if lost:
            self.hearts -= 1
            self.flash = 4
            self.charge = 0
            self.state = LOST
            self.t = 0
            return
        if self.save and y > self.net_y and vy > 0:
            # the net throws it back up between the flippers, a little to one side
            r = self.rng.next()
            x = MID
            vy = -NET_KICK
            vx = 100 + (r & 127) if r & 128 else -100 - (r & 127)
        if -40 < vx < 40 and -40 < vy < 40 and not ready and not pressed:
            self.still += 1
            if self.still > 180:  # stuck somewhere: shake it loose
                self.still = 0
                vy = -500
                vx = 300 if self.rng.next() & 1 else -300
        else:
            self.still = 0
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy

        # the view leads the ball: more table below it on the way down, above on the way up
        lead = 18 * 256 - vy * 6
        if lead < 8 * 256:
            lead = 8 * 256
        elif lead > 30 * 256:
            lead = 30 * 256
        target = y - lead
        if target < 0:
            target = 0
        elif target > self.cam_max:
            target = self.cam_max
        self.cam += (target - self.cam) >> 3

    # ---- drawing ---------------------------------------------------------

    def _table(self, cy, red, ri, wolf, wi):
        """The table with the view's top at row cy; red and wolf are their animations and frames."""
        fb = self.fb
        t = self.t
        fb.fill(0)
        fb.blit(self.art, 0, -cy)
        # the moon shows full for a moment when hit, and blinks full while the jackpot is lit
        if self.moon_t > 8 or (self.awake[0] and self.awake[1] and t & 8):
            self.full.draw(fb, 0, self.moon_x, self.moon_y - cy)
        tg = self.tg
        for i in range(3):
            # drop targets; a bank that has just gone down blinks before it stands up again
            y = self.tg_top[i] - cy
            if tg[i] or self.bank_t[0] & 4:
                fb.fill_rect(1, y, 3, 4, 1)
            if tg[3 + i] or self.bank_t[1] & 4:
                fb.fill_rect(61, y, 3, 4, 1)
        a = self.wisp
        for i in range(2):
            # flared when just hit; an awake wisp flickers
            if self.wisp_t[i] > WISP_REST - 12 or (self.awake[i] and t & 4):
                f = 4
            else:
                f = ((t >> 3) + i * 2) & 3
            a.draw(fb, f, self.wisp_x[i], self.wisp_y[i] - cy)
        a = self.mush
        a.draw(fb, 4 if self.mush_t else (t >> 4) & 3, self.mush_x + a.ox, self.mush_y - a.h - cy)
        red.draw(fb, ri, self.red_x + red.ox, self.red_y - red.h - cy)
        wolf.draw(fb, wi, self.wolf_x + wolf.ox, self.wolf_y - wolf.h - cy)
        f = self.flip
        tx = self.tipx[f]
        ty = self.tipy[f]
        y = (self.py >> 8) - cy
        x = self.plx >> 8
        fb.line(x, y, x + tx, y + ty, 1)
        fb.line(x, y + 1, x + tx, y + ty + 1, 1)
        x = (self.prx >> 8) - 1
        fb.line(x, y, x - tx, y + ty, 1)
        fb.line(x, y + 1, x - tx, y + ty + 1, 1)

    def draw(self):
        fb = self.fb
        s = self.state
        t = self.t
        if s == TITLE or s == OVER:
            fb.fill(0)
            fb.hline(0, 37, 72, 1)
            a = self.red_idle if s == TITLE else self.red_death
            a.draw(fb, (t >> 4) & 3 if s == TITLE else 3, 2 + a.ox, 37 - a.h)
            a = self.wolf_idle
            a.draw(fb, (t >> 4) & 3, 42 + a.ox, 37 - a.h)
            if s == TITLE:
                if (t >> 7) & 1:
                    text(fb, b"HOLD TO LAUNCH", 8, 3)
                else:
                    fb.text("PINBALL", 8, 1, 1)
                if (t >> 5) & 1 == 0:
                    text(fb, b"PRESS", 26, 12)
                return
            fb.text(self.score_text, 36 - 4 * len(self.score_text), 2, 1)
            if self.new_best:
                if (t >> 4) & 1 == 0:
                    text(fb, b"NEW BEST", 20, 12)
            else:
                text(fb, b"BEST", 20, 12)
                num(fb, self.best, 50, 12)
            return

        cy = self.cam >> 8
        if s == LOST:
            # the wolf snaps the ball up and Red flinches
            if t < 32:
                self._table(cy, self.red_hit, (t >> 3) & 1, self.wolf_bite, t >> 3)
            else:
                self._table(cy, self.red_hit, 1, self.wolf_idle, (t >> 4) & 3)
        else:
            if self.red_t:
                self._table(cy, self.red_jump, 0 if self.red_t > 12 else 1, self.wolf_idle, (t >> 4) & 3)
            else:
                self._table(cy, self.red_idle, (t >> 4) & 3, self.wolf_idle, (t >> 4) & 3)
            if self.save > 120 or self.save & 8:
                y = (self.net_y >> 8) - cy
                for x in range(28, 38, 2):
                    fb.pixel(x, y, 1)
            if self.live and cy < 18:
                for y in range(3 - cy, 18 - cy, 3):  # the gate
                    fb.pixel(64, y, 1)
            self.ball.draw(fb, 0, (self.x >> 8) - 3, (self.y >> 8) - 3 - cy)
            if self.charge:
                fb.fill_rect(0, 38, self.charge * 72 // CHARGE_MAX, 2, 1)
        hearts(fb, self.hearts)
        hud(fb, self.score)
        if self.mult > 1:
            fb.fill_rect(26, 0, 10, 7, 0)
            text(fb, b"X", 27, 1)
            num(fb, self.mult, 33, 1)

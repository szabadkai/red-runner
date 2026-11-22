"""LOST WISP: hold the button to rise, let go to sink, thread the thorn thickets.

Thickets grow from the floor, hang from the top, or both with a gap between. Later on ravens
hang in the air between them: go over or under. The wisp has three hearts; the floor and the
top edge are safe.

Motes twinkle between the obstacles, off the easy line. Each one is a point, like each
obstacle passed, and every eighth mote mends a heart.

The wisp has almost no inertia: it settles to a steady climb or a steady sink within a
few ticks, so its path is straight lines the player can aim.
"""
from micropython import const

import sprites_wisp as sprites
from engine import FP, H, W, Anim, Backdrop, Rng, hearts, hud, num, text

WISP_X = const(8)
HIT_L = const(17)  # the wisp's hit box, screen px (right and bottom exclusive)
HIT_R = const(27)
HIT_T = const(2)  # ... inside its sprite, from the top
HIT_B = const(9)
WISP_H = const(11)
V_RISE = const(-190)  # 0.74 px per tick while the button is held
V_SINK = const(155)  # 0.6 px per tick otherwise
EASE = const(2)  # velocity closes a quarter of the gap to its target each tick
SPEED0 = const(205)  # 0.8 px per tick
SPEED_MAX = const(340)
HEARTS = const(3)
SAFE_TICKS = const(70)  # untouchable this long after a hit
THICKET_W = const(28)
THICKET_H = const(26)
T_INSET = const(5)  # thicket hit box is inset this much on each side
T_TIP = const(2)  # ... and its tip is this forgiving
MAXO = const(4)
RAVEN_W = const(30)
R_INSET = const(8)  # the raven's hit box, inset from its sprite at each end ...
R_T = const(6)  # ... and these rows of it
R_B = const(12)
RAVEN_FROM = const(6)  # obstacles passed before the first raven
MAXM = const(3)
MOTES_PER_HEART = const(8)

TITLE = const(0)
PLAY = const(1)
POP = const(2)
OVER = const(3)


class Game:
    def __init__(self, fb, best=0, seed=1):
        self.fb = fb
        self.best = best
        self.rng = Rng(seed)
        self.stir = self.rng.stir
        self.idle_a = Anim(sprites.wisp_idle)
        self.fly = Anim(sprites.wisp_fly)
        self.pop = Anim(sprites.wisp_pop)
        self.thicket = Anim(sprites.thicket)
        self.thicket_top = Anim(sprites.thicket_top)
        self.raven = Anim(sprites.raven)
        self.back = Backdrop()
        self.ob_x = [0] * MAXO
        self.ob_top = [0] * MAXO  # visible height of the hanging thicket, 0 for none
        self.ob_bot = [0] * MAXO  # visible height of the floor thicket, 0 for none
        self.ob_live = [False] * MAXO
        self.ob_done = [False] * MAXO
        self.ob_raven = [False] * MAXO  # a raven instead: ob_top is then the top of its sprite
        self.m_x = [0] * MAXM
        self.m_y = [0] * MAXM
        self.m_live = [False] * MAXM
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
        self.hearts = HEARTS
        self.inv = 0
        self.new_best = False
        self.passed = 0  # obstacles passed: what the difficulty goes by
        self.after_raven = False
        self.motes = 0
        self.mote_t = 0  # ticks until the next mote appears, 0 for none due
        self.led_t = 0
        self.gain = 0  # ticks left of showing off a mended heart
        self.dist = 0
        self.speed = SPEED0
        self.y = 14 << FP
        self.vy = 0
        self.centre = 20  # middle of the last opening, so the next one is reachable
        self.next_t = 30  # ticks until the next thicket appears
        for i in range(MAXO):
            self.ob_live[i] = False
        for i in range(MAXM):
            self.m_live[i] = False

    # ---- thickets --------------------------------------------------------

    def _spawn(self):
        for i in range(MAXO):
            if not self.ob_live[i]:
                break
        else:
            return
        rng = self.rng
        lv = self.passed if self.passed < 30 else 30
        gap = 24 - lv * 4 // 15  # 24 px down to 16
        reach = 6 if self.after_raven else 13  # either way round a raven must leave the next one reachable
        self.after_raven = False
        c = self.centre - reach + rng.next() % (2 * reach + 1)
        lo = gap // 2 + 3
        hi = H - gap // 2 - 3
        c = lo if c < lo else hi if c > hi else c
        self.ob_live[i] = True
        self.ob_done[i] = False
        self.ob_x[i] = W << FP
        # spaced in time, not distance, so there is always room to change height
        self.next_t = 50 - lv // 2 + rng.next() % 10
        if rng.next() & 1:
            self.mote_t = self.next_t >> 1
        if self.passed >= RAVEN_FROM and rng.next() % 4 == 0:
            # a raven in mid-air, on the line the wisp is flying: over or under
            c = 15 if c < 15 else 25 if c > 25 else c
            self.centre = c
            self.after_raven = True
            self.next_t += 12
            self.ob_raven[i] = True
            self.ob_top[i] = c - (R_T + R_B) // 2
            self.ob_bot[i] = 0
            return
        self.ob_raven[i] = False
        self.centre = c
        top = c - gap // 2
        bot = H - (c + gap // 2)
        kind = rng.next() % 10
        if lv < 8 or kind < 4:
            # one-sided: keep whichever thicket is taller, so there is something to dodge
            if top > bot:
                bot = 0
            else:
                top = 0
        if top > THICKET_H:
            top = THICKET_H
        if bot > THICKET_H:
            bot = THICKET_H
        self.ob_top[i] = top
        self.ob_bot[i] = bot

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
        elif s == POP:
            self.led = (self.t >> 3) & 1 == 0
            if self.t >= 48:
                self.led = False
                if self.score > self.best:
                    self.best = self.score
                    self.new_best = True
                self.score_text = str(self.score)
                self.state = OVER
                self.menu = True
                self.t = 0
        elif edge and self.t > 30:
            self._reset()
            self.state = PLAY
            self.menu = False
            self.t = 0

    def _play(self, pressed):
        s = SPEED0 + self.passed * 3
        self.speed = s if s < SPEED_MAX else SPEED_MAX
        self.dist += self.speed
        if self.inv:
            self.inv -= 1
        if self.led_t:
            self.led_t -= 1
        if self.gain:
            self.gain -= 1
        self.led = self.led_t > 0

        vy = self.vy
        vy += ((V_RISE if pressed else V_SINK) - vy) >> EASE
        y = self.y + vy
        if y < 0:
            y = 0
            vy = 0
        elif y > (H - WISP_H) << FP:
            y = (H - WISP_H) << FP
            vy = 0
        self.y = y
        self.vy = vy

        self.next_t -= 1
        if self.next_t <= 0:
            self._spawn()
        top = (y >> FP) + HIT_T
        bottom = (y >> FP) + HIT_B
        if self.mote_t:
            self.mote_t -= 1
            if self.mote_t == 0:
                for i in range(MAXM):
                    if not self.m_live[i]:
                        self.m_live[i] = True
                        self.m_x[i] = W << FP
                        self.m_y[i] = 5 + self.rng.next() % 30
                        break
        for i in range(MAXM):
            if self.m_live[i]:
                x = self.m_x[i] - self.speed
                self.m_x[i] = x
                px = x >> FP
                if px < -2:
                    self.m_live[i] = False
                elif HIT_L - 2 <= px <= HIT_R + 1 and top - 2 <= self.m_y[i] <= bottom + 1:
                    self.m_live[i] = False
                    self.score += 1
                    self.motes += 1
                    self.led_t = 4
                    if self.motes % MOTES_PER_HEART == 0 and self.hearts < HEARTS:
                        self.hearts += 1
                        self.gain = 40
        for i in range(MAXO):
            if not self.ob_live[i]:
                continue
            x = self.ob_x[i] - self.speed
            self.ob_x[i] = x
            px = x >> FP
            if self.ob_raven[i]:
                w = RAVEN_W
                inset = R_INSET
            else:
                w = THICKET_W
                inset = T_INSET
            if px + w < 0:
                self.ob_live[i] = False
            elif px + inset < HIT_R and px + w - inset > HIT_L:
                if self.inv:
                    continue
                if self.ob_raven[i]:
                    hit = bottom > self.ob_top[i] + R_T and top < self.ob_top[i] + R_B
                else:
                    hit = top < self.ob_top[i] - T_TIP or bottom > H - self.ob_bot[i] + T_TIP
                if hit:
                    self.hearts -= 1
                    self.flash = 4
                    self.inv = SAFE_TICKS
                    if self.hearts == 0:
                        self.state = POP
                        self.t = 0
                        return
            elif not self.ob_done[i] and px + w - inset <= HIT_L:
                self.ob_done[i] = True
                self.score += 1
                self.passed += 1

    # ---- drawing ---------------------------------------------------------

    def draw(self):
        fb = self.fb
        s = self.state
        t = self.t
        fb.fill(0)
        if s == TITLE:
            fb.text("LOST WISP", 0, 1, 1)
            a = self.idle_a
            bob = (t >> 4) & 3
            a.draw(fb, (t >> 3) & 3, 10, 13 + (bob if bob < 3 else 1))
            if (t >> 5) & 1 == 0:
                text(fb, b"PRESS", 38, 17)
            text(fb, b"HOLD TO RISE", 12, 32)
            return
        if s == OVER:
            self.back.sky(fb, t, 0, None)
            fb.text(self.score_text, 36 - 4 * len(self.score_text), 8, 1)
            if self.new_best:
                if (t >> 4) & 1 == 0:
                    text(fb, b"NEW BEST", 20, 22)
            else:
                text(fb, b"BEST", 20, 22)
                num(fb, self.best, 52, 22)
            return

        self.back.sky(fb, t, self.dist >> (FP + 3), None)
        a = self.thicket
        b = self.thicket_top
        for i in range(MAXO):
            if self.ob_live[i]:
                x = self.ob_x[i] >> FP
                if self.ob_raven[i]:
                    self.raven.draw(fb, (t >> 3) & 1, x, self.ob_top[i])
                    continue
                if self.ob_bot[i]:
                    a.draw(fb, 0, x, H - self.ob_bot[i])
                if self.ob_top[i]:
                    b.draw(fb, 0, x, self.ob_top[i] - THICKET_H)
        for i in range(MAXM):
            if self.m_live[i]:
                # a mote: a twinkling cross
                x = self.m_x[i] >> FP
                y = self.m_y[i]
                fb.pixel(x, y, 1)
                if (t + i * 5) & 8:
                    fb.hline(x - 1, y, 3, 1)
                    fb.vline(x, y - 1, 3, 1)
                else:
                    fb.hline(x - 2, y, 5, 1)
                    fb.vline(x, y - 2, 5, 1)
        y = self.y >> FP
        if s == POP:
            f = t >> 3
            if f < 6:
                a = self.pop
                a.draw(fb, f, WISP_X - 2, y - 3)
        elif (self.inv >> 2) & 1 == 0:
            self.fly.draw(fb, (t >> 3) & 3, WISP_X, y)
        # a mended heart blinks for a moment
        hearts(fb, self.hearts - 1 if self.gain & 4 else self.hearts)
        hud(fb, self.score)

"""RED RUN: jump mushrooms and brambles, don't jump into ravens, don't get hit twice.

The first hit makes Red stumble and brings the wolf in close for ten seconds; a second
hit while he is there ends the run.
"""
from micropython import const

import sprites_runner as sprites
from engine import FP, GROUND, W, Anim, Backdrop, Rng, hud, logo, num, text

RX = const(4)  # screen x of Red's 32 px source cell
RED_L = const(15)  # Red's hit box, screen px
RED_R = const(22)
RED_TALL = const(15)
JUMP_V = const(600)  # 21 px apex, 36 ticks in the air
GRAVITY = const(33)
SPEED0 = const(282)  # 1.1 px per tick
SPEED_MAX = const(410)
RAVEN_V = const(140)  # raven air speed on top of the scroll
RAVEN_Y = const(1)
WOLF_NEAR = const(-16)
WOLF_FAR = const(-36)
WOLF_BITE = const(-2)
KNOCK = const(27)  # how far Red is thrown ahead when caught
DANGER_TICKS = const(600)  # how long the wolf stays close after a stumble
GAP_MIN = const(46)  # ticks between obstacles reaching Red; one jump is 36
MAXO = const(4)

TITLE = const(0)
PLAY = const(1)
CAUGHT = const(2)
OVER = const(3)

MUSHROOM = const(0)
BRAMBLES = const(1)
RAVEN = const(2)

# hit boxes inside each obstacle sprite (right and bottom exclusive)
HIT_L = (7, 8, 8)
HIT_R = (16, 19, 22)
HIT_T = (7, 7, 5)
HIT_B = (17, 16, 12)


class Game:
    def __init__(self, fb, best=0, seed=1):
        self.fb = fb
        self.best = best
        self.rng = Rng(seed)
        self.stir = self.rng.stir
        self.red_idle = Anim(sprites.red_idle)
        self.red_run = Anim(sprites.red_run)
        self.red_jump = Anim(sprites.red_jump)
        self.red_hit = Anim(sprites.red_hit)
        self.red_death = Anim(sprites.red_death)
        self.wolf_run = Anim(sprites.wolf_run)
        self.wolf_bite = Anim(sprites.wolf_bite)
        self.wolf_idle = Anim(sprites.wolf_idle)
        self.obs = (Anim(sprites.mushroom), Anim(sprites.brambles), Anim(sprites.raven))
        self.back = Backdrop()
        self.logo = logo("RED")
        self.ob_kind = [-1] * MAXO
        self.ob_x = [0] * MAXO
        self.score_text = "0"
        self.state = TITLE
        self.menu = True
        self.t = 0
        self.led = False
        self.flash = 0
        self.prev = False
        self._reset()

    def _reset(self):
        self.tick_n = 0
        self.dist = 0
        self.speed = SPEED0
        self.ry = 0
        self.rvy = 0
        self.air = False
        self.jbuf = 0
        self.hurt = 0
        self.inv = 0
        self.danger = 0
        self.wx = -10 << FP
        self.kx = 0
        self.score = 0
        self.new_best = False
        for i in range(MAXO):
            self.ob_kind[i] = -1
        self.last_arrive = 70
        self._plan()

    # ---- obstacles -------------------------------------------------------

    def _plan(self):
        r = self.rng.next()
        span = 70 - ((self.speed - SPEED0) >> 2)
        self.next_arrive = self.last_arrive + GAP_MIN + r % span
        k = (r >> 7) % 10
        if k < 3 and self.score >= 60:
            self.next_kind = RAVEN
        else:
            self.next_kind = MUSHROOM if k & 1 else BRAMBLES

    def _spawn(self):
        kind = self.next_kind
        rel = self.speed + (RAVEN_V if kind == RAVEN else 0)
        centre = (HIT_L[kind] + HIT_R[kind]) // 2
        travel = ((W + centre - (RED_L + RED_R) // 2) << FP) // rel
        if self.tick_n + travel < self.next_arrive:
            return
        for i in range(MAXO):
            if self.ob_kind[i] < 0:
                self.ob_kind[i] = kind
                self.ob_x[i] = W << FP
                self.last_arrive = self.tick_n + travel
                self._plan()
                return

    def _hits(self, kind, x):
        if x + HIT_L[kind] >= RED_R or x + HIT_R[kind] <= RED_L:
            return False
        feet = GROUND - (self.ry >> FP)
        if kind == RAVEN:
            return feet - RED_TALL < RAVEN_Y + HIT_B[kind]
        return feet > GROUND - self.obs[kind].h + HIT_T[kind]

    # ---- update ----------------------------------------------------------

    def tick(self, pressed):
        edge = pressed and not self.prev
        self.prev = pressed
        self.t += 1
        if self.flash:
            self.flash -= 1
        s = self.state
        if s == PLAY:
            self._play(edge)
        elif s == CAUGHT:
            self._caught()
        elif edge and self.t > 30:
            self._reset()
            self.state = PLAY
            self.menu = False
            self.t = 0

    def _play(self, edge):
        self.tick_n += 1
        s = SPEED0 + (self.dist >> (FP + 5))
        self.speed = s if s < SPEED_MAX else SPEED_MAX
        self.dist += self.speed
        self.score = self.dist >> (FP + 3)

        if edge:
            self.jbuf = 8
        if self.air:
            self.rvy -= GRAVITY
            self.ry += self.rvy
            if self.ry <= 0:
                self.ry = 0
                self.rvy = 0
                self.air = False
        if self.jbuf:
            self.jbuf -= 1
            if not self.air:
                self.air = True
                self.rvy = JUMP_V
                self.ry = JUMP_V
                self.jbuf = 0

        if self.hurt:
            self.hurt -= 1
        if self.inv:
            self.inv -= 1
        if self.danger:
            self.danger -= 1
        self.led = self.hurt > 0
        target = (WOLF_NEAR if self.danger else WOLF_FAR) << FP
        if self.wx < target:
            self.wx += 256
            if self.wx > target:
                self.wx = target
        elif self.wx > target:
            self.wx -= 72

        self._spawn()
        for i in range(MAXO):
            kind = self.ob_kind[i]
            if kind < 0:
                continue
            x = self.ob_x[i] - self.speed - (RAVEN_V if kind == RAVEN else 0)
            self.ob_x[i] = x
            px = x >> FP
            if px + self.obs[kind].w < 0:
                self.ob_kind[i] = -1
            elif self.inv == 0 and self._hits(kind, px):
                self.ob_kind[i] = -1
                self._stumble()

    def _stumble(self):
        self.flash = 4
        if self.danger:
            self.state = CAUGHT
            self.t = 0
            self.led = True
            return
        self.danger = DANGER_TICKS
        self.hurt = 26
        self.inv = 70

    def _caught(self):
        if self.air:
            self.rvy -= GRAVITY * 2
            self.ry += self.rvy
            if self.ry <= 0:
                self.ry = 0
                self.air = False
        target = WOLF_BITE << FP
        if self.wx < target:
            self.wx += 300
        if self.kx < KNOCK:
            self.kx += 2 if self.kx < 20 else 1
        self.led = (self.t >> 3) & 1 == 0
        if self.t >= 110:
            self.led = False
            if self.score > self.best:
                self.best = self.score
                self.new_best = True
            self.score_text = str(self.score)
            self.state = OVER
            self.menu = True
            self.t = 0

    # ---- drawing ---------------------------------------------------------

    def draw(self):
        fb = self.fb
        s = self.state
        back = self.back
        px = self.dist >> FP
        fb.fill(0)
        if s == TITLE:
            back.ground(fb, px)
            a = self.red_idle
            a.draw(fb, (self.t >> 4) & 3, 1, GROUND - a.h)
            fb.blit(self.logo, 23, 4, 0)
            if (self.t >> 5) & 1 == 0:
                text(fb, b"PRESS", 37, 26)
            return
        if s == OVER:
            back.ground(fb, px)
            a = self.wolf_idle
            a.draw(fb, (self.t >> 4) & 3, 1, GROUND - a.h)
            fb.fill_rect(31, 3, 41, 26, 0)
            fb.text(self.score_text, 32, 5, 1)
            if self.new_best:
                if (self.t >> 4) & 1 == 0:
                    text(fb, b"NEW BEST", 33, 19)
            else:
                text(fb, b"BEST", 33, 19)
                num(fb, self.best, 71, 19)
            return

        back.sky(fb, self.t)
        back.trees(fb, px)
        back.ground(fb, px)
        obs = self.obs
        for i in range(MAXO):
            kind = self.ob_kind[i]
            if kind >= 0:
                a = obs[kind]
                x = self.ob_x[i] >> FP
                if kind == RAVEN:
                    a.draw(fb, (self.t >> 2) & 1, x, RAVEN_Y)
                else:
                    a.draw(fb, (self.t >> 4) & 3, x, GROUND - a.h)

        wx = self.wx >> FP
        feet = GROUND - (self.ry >> FP)
        if s == CAUGHT:
            a = self.wolf_bite
            a.draw(fb, (self.t >> 3) & 3, wx, GROUND - a.h)
            a = self.red_death
            f = self.t // 12
            a.draw(fb, f if f < 3 else 3, RX + a.ox + self.kx, feet - a.h)
        else:
            if wx > -32:
                a = self.wolf_bite if self.hurt else self.wolf_run
                a.draw(fb, (self.dist >> (FP + 3)) & 3, wx, GROUND - a.h)
            if self.inv > 56 or (self.inv >> 2) & 1 == 0:
                if self.air:
                    a = self.red_jump
                    f = 0 if self.rvy > 0 else 1
                elif self.hurt:
                    a = self.red_hit
                    f = (self.hurt >> 3) & 1
                else:
                    a = self.red_run
                    f = (self.dist >> (FP + 3)) & 3
                a.draw(fb, f, RX + a.ox, feet - a.h)
        hud(fb, self.score)

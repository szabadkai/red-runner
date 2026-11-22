"""HUNTSMAN: ravens swoop in on a rolling flight; loose an arrow to meet one as it dips.

The arrow flies level at chest height and takes its time. A raven rises and falls as it
comes, and can only be hit while it is down in the arrow's lane, so the arrow has to leave
early: the further off the bird, the sooner. He needs a moment to nock the next arrow.
A raven that reaches him takes a heart.

After every six ravens the sky empties, a "!" flashes at the edge and a boar comes for him
along the ground. It is always in the line of fire but it takes two arrows, so the first has
to go early enough to nock the second. Three hearts; a raven scores 1, a boar 3.
"""
import math

from micropython import const

import sprites_hunter as sprites
from engine import FP, GROUND, Anim, Backdrop, Rng, hearts, hud, num, text

HUNTER_X = const(0)  # screen x of the hunter's 32 px source cell
ARROW_X0 = const(24)  # arrow tip as it leaves the bow
ARROW_V = const(384)  # 1.5 px per tick
LANE_Y = const(29)  # the arrow's row
MID = const(18)  # raven centre height: it rolls between MID - SWING and MID + SWING
SWING = const(10)
HEAD = const(16)  # ... on its final run at his head
IN_LANE = const(26)  # a raven this low or lower is in the line of fire
HALF = const(8)  # half the length of a raven's body
PECK_X = const(30)  # raven centre x when its beak reaches him
ENTER_X = const(88)
DIP_NEAR = const(40)  # every raven has one dip somewhere between these, and the game
DIP_FAR = const(58)  # leaves time to shoot it there
NOCK = const(36)  # ticks to ready the next arrow
HEARTS = const(3)
MAXR = const(3)
FLOCK = const(6)  # ravens shot between boars
BOAR_HALF = const(11)  # half the length of a boar
BOAR_BITE = const(34)  # boar centre x when his tusks reach the hunter
BOAR_WARN = const(50)  # ticks of "!" before he appears: longer than it takes to nock

TITLE = const(0)
PLAY = const(1)
DEAD = const(2)
OVER = const(3)

FREE = const(0)
WAVE = const(1)
ATTACK = const(2)
LEAVE = const(3)
FALL = const(4)
DOWN = const(5)

B_NONE = const(0)
B_WARN = const(1)
B_RUN = const(2)
B_STUN = const(3)  # knocked back by the first arrow
B_DOWN = const(4)
B_PAST = const(5)  # he got through and runs on

# one turn of sine as offsets from MID, 64 steps; index 16 is the bottom of a dip
_ROLL = bytes(int(SWING + 0.5 + SWING * math.sin(i * math.pi / 32)) for i in range(64))


class Game:
    def __init__(self, fb, best=0, seed=1):
        self.fb = fb
        self.best = best
        self.rng = Rng(seed)
        self.stir = self.rng.stir
        self.idle_a = Anim(sprites.hunter_idle)
        self.shoot = Anim(sprites.hunter_shoot)
        self.hit_a = Anim(sprites.hunter_hit)
        self.death = Anim(sprites.hunter_death)
        self.glide = Anim(sprites.raven_glide)
        self.raven_hit = Anim(sprites.raven_hit)
        self.raven_down = Anim(sprites.raven_down)
        self.raven_idle = Anim(sprites.raven_idle)
        self.boar_run = Anim(sprites.boar_run)
        self.boar_hit = Anim(sprites.boar_hit)
        self.boar_down = Anim(sprites.boar_down)
        self.back = Backdrop()
        self.r_state = [FREE] * MAXR
        self.r_x = [0] * MAXR  # raven centre x, fixed point
        self.r_y = [0] * MAXR  # raven centre y, px
        self.r_v = [0] * MAXR
        self.r_ph = [0] * MAXR  # where it is in its roll, 0..65535 per turn
        self.r_dp = [0] * MAXR
        self.r_t = [0] * MAXR  # ticks left lying on the ground
        self.r_fire = [0] * MAXR  # tick at which an arrow meets its promised dip
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
        self.new_best = False
        self.tick_n = 0
        self.nock = 0  # ticks until the next arrow is ready
        self.hurt = 0
        self.arrow = -1  # arrow tip x in fixed point, -1 when none is flying
        self.last_fire = 0
        self.kills = 0  # ravens shot since the last boar
        self.b_state = B_NONE
        self.b_x = 0  # boar centre x, fixed point
        self.b_v = 0
        self.b_t = 0
        self.b_hp = 0
        for i in range(MAXR):
            self.r_state[i] = FREE
        self.next_t = 50
        self._plan()

    def _level(self):
        lv = self.score // 3
        return lv if lv < 8 else 8

    # ---- ravens ----------------------------------------------------------

    def _plan(self):
        rng = self.rng
        lv = self._level()
        self.n_v = 125 + lv * 9 + rng.next() % 45  # 0.5 px per tick up to 0.95
        self.n_dp = 65536 // (64 - lv * 2 + rng.next() % 12)  # one roll takes 76 ticks down to 48
        self.n_dip = DIP_NEAR + rng.next() % (DIP_FAR - DIP_NEAR + 1)

    def _spawn(self):
        v = self.n_v
        to_dip = ((ENTER_X - self.n_dip) << FP) // v  # ticks until it bottoms out at n_dip
        fire = self.tick_n + to_dip - ((self.n_dip - ARROW_X0) << FP) // ARROW_V
        # the promised shots at two ravens must be far enough apart to nock in between
        if fire < self.last_fire + NOCK + 12:
            return
        for i in range(MAXR):
            if self.r_state[i] == FREE:
                break
        else:
            return
        self.r_state[i] = WAVE
        self.r_x[i] = ENTER_X << FP
        self.r_v[i] = v
        self.r_dp[i] = self.n_dp
        self.r_ph[i] = (16384 - self.n_dp * to_dip) & 0xFFFF
        self.r_y[i] = MID - SWING + _ROLL[self.r_ph[i] >> 10]
        self.r_fire[i] = fire
        self.last_fire = fire
        self.next_t = 100 - self._level() * 7 + self.rng.next() % 50
        self._plan()

    def _ravens(self):
        for i in range(MAXR):
            st = self.r_state[i]
            if st == FREE:
                continue
            if st == DOWN:
                self.r_t[i] -= 1
                if self.r_t[i] <= 0:
                    self.r_state[i] = FREE
                continue
            if st == FALL:
                y = self.r_y[i] + 2
                if y >= MID + SWING:
                    y = MID + SWING
                    self.r_state[i] = DOWN
                    self.r_t[i] = 44
                self.r_y[i] = y
                continue
            x = self.r_x[i] - self.r_v[i]
            self.r_x[i] = x
            px = x >> FP
            if px < -16:
                self.r_state[i] = FREE
            elif st == LEAVE:
                self.r_y[i] -= 1
            elif st == WAVE:
                ph = (self.r_ph[i] + self.r_dp[i]) & 0xFFFF
                self.r_ph[i] = ph
                self.r_y[i] = MID - SWING + _ROLL[ph >> 10]
                if px <= PECK_X + 8:
                    self.r_state[i] = ATTACK
            else:
                y = self.r_y[i]
                if y != HEAD:
                    self.r_y[i] = y + (1 if y < HEAD else -1)
                if px <= PECK_X:
                    self.r_state[i] = LEAVE
                    if self.state != PLAY:
                        continue
                    self.hearts -= 1
                    self.flash = 4
                    self.hurt = 40
                    self.nock = NOCK
                    if self.hearts == 0:
                        self.state = DEAD
                        self.arrow = -1
                        self.t = 0

    def _arrow(self):
        was = self.arrow >> FP
        self.arrow += ARROW_V
        tip = self.arrow >> FP
        if tip >= 82:
            self.arrow = -1
        st = self.b_state
        if st == B_RUN or st == B_STUN:
            cx = self.b_x >> FP
            if tip >= cx - BOAR_HALF and was <= cx + BOAR_HALF:
                self.arrow = -1
                self.b_hp -= 1
                if self.b_hp:
                    self.b_state = B_STUN
                    self.b_t = 14
                    self.b_x += 8 << FP
                else:
                    self.b_state = B_DOWN
                    self.b_t = 50
                    self.score += 3
                return
        for i in range(MAXR):
            st = self.r_state[i]
            if st == WAVE or st == ATTACK:
                cx = self.r_x[i] >> FP
                if self.r_y[i] >= IN_LANE and tip >= cx - HALF and was <= cx + HALF:
                    self.r_state[i] = FALL
                    self.arrow = -1
                    self.score += 1
                    self.kills += 1
                    return

    # ---- the boar --------------------------------------------------------

    def _boar(self):
        st = self.b_state
        if st == B_NONE:
            return
        self.b_t -= 1
        if st == B_WARN:
            if self.b_t <= 0:
                self.b_state = B_RUN
                self.b_x = (ENTER_X + 4) << FP
                self.b_hp = 2
                self.b_v = 205 + self._level() * 10  # 0.8 px per tick up to 1.1
        elif st == B_RUN:
            self.b_x -= self.b_v
            if self.b_x >> FP <= BOAR_BITE:
                self.b_state = B_PAST
                self.hearts -= 1
                self.flash = 4
                self.hurt = 40
                self.nock = NOCK
                if self.hearts == 0:
                    self.state = DEAD
                    self.arrow = -1
                    self.t = 0
        elif st == B_STUN:
            if self.b_t <= 0:
                self.b_state = B_RUN
        elif st == B_PAST:
            self.b_x -= 512
        if (st == B_DOWN and self.b_t <= 0) or self.b_x < -(20 << FP):
            self.b_state = B_NONE
            self.kills = 0
            self.next_t = 50

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
        elif s == DEAD:
            self.led = (self.t >> 3) & 1 == 0
            self._ravens()
            self._boar()
            if self.t >= 100:
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

    def _play(self, edge):
        self.tick_n += 1
        if self.hurt:
            self.hurt -= 1
        if self.nock:
            self.nock -= 1
        elif edge:
            self.arrow = ARROW_X0 << FP
            self.nock = NOCK
        self.led = self.nock > NOCK - 6 or (self.b_state == B_WARN and self.b_t & 4 != 0)
        if self.arrow >= 0:
            self._arrow()
        self._ravens()
        self._boar()
        self.next_t -= 1
        if self.next_t <= 0:
            if self.kills < FLOCK:
                self._spawn()
            elif self.b_state == B_NONE:
                # the boar waits for the sky to empty
                for i in range(MAXR):
                    if self.r_state[i] != FREE:
                        break
                else:
                    self.b_state = B_WARN
                    self.b_t = BOAR_WARN

    # ---- drawing ---------------------------------------------------------

    def _draw_ravens(self):
        fb = self.fb
        t = self.t
        for i in range(MAXR):
            st = self.r_state[i]
            if st == FREE:
                continue
            cx = self.r_x[i] >> FP
            cy = self.r_y[i]
            if st == DOWN:
                a = self.raven_down
                f = 3 - (self.r_t[i] >> 3)
                a.draw(fb, f if f > 0 else 0, cx - 16, GROUND - a.h)
            elif st == FALL:
                a = self.raven_hit
                a.draw(fb, (t >> 2) & 1, cx - 16, cy - 13)
            else:
                self.glide.draw(fb, (t >> 2) & 1, cx - 15, cy - 8)

    def draw(self):
        fb = self.fb
        s = self.state
        t = self.t
        back = self.back
        fb.fill(0)
        if s == TITLE:
            back.ground(fb, 0)
            a = self.idle_a
            a.draw(fb, (t >> 4) & 3, HUNTER_X + a.ox, GROUND - a.h)
            a = self.raven_idle
            a.draw(fb, (t >> 4) & 3, 42, GROUND - a.h)
            if (t >> 7) & 1:
                text(fb, b"SHOOT AS THEY DIP", 2, 3)
            else:
                fb.text("HUNTSMAN", 4, 1, 1)
            if (t >> 5) & 1 == 0:
                text(fb, b"PRESS", 22, 16)
            return
        if s == OVER:
            back.ground(fb, 0)
            a = self.death
            a.draw(fb, 3, HUNTER_X + a.ox, GROUND - a.h)
            a = self.raven_idle
            a.draw(fb, (t >> 4) & 3, 42, GROUND - a.h)
            fb.text(self.score_text, 36 - 4 * len(self.score_text), 2, 1)
            if self.new_best:
                if (t >> 4) & 1 == 0:
                    text(fb, b"NEW BEST", 20, 12)
            else:
                text(fb, b"BEST", 20, 12)
                num(fb, self.best, 50, 12)
            return

        back.sky(fb, t, 0, 31)
        back.trees(fb, 0)
        back.ground(fb, 0)
        if s == DEAD:
            a = self.death
            f = t // 10
            a.draw(fb, f if f < 3 else 3, HUNTER_X + a.ox, GROUND - a.h)
        elif self.hurt:
            a = self.hit_a
            a.draw(fb, (self.hurt >> 3) & 1, HUNTER_X + a.ox, GROUND - a.h)
        else:
            a = self.shoot
            n = self.nock
            # arrow drawn and ready, then bow lowered, reaching for an arrow, drawing again
            a.draw(fb, 2 if n == 0 else 3 if n > 24 else 0 if n > 10 else 1, HUNTER_X + a.ox, GROUND - a.h)
        self._draw_ravens()
        st = self.b_state
        if st == B_WARN:
            if (self.b_t >> 2) & 1:
                fb.fill_rect(66, 18, 3, 6, 1)
                fb.fill_rect(66, 26, 3, 3, 1)
        elif st != B_NONE:
            if st == B_STUN:
                a = self.boar_hit
                f = (self.b_t >> 2) & 1
            elif st == B_DOWN:
                a = self.boar_down
                f = (50 - self.b_t) >> 3
                if f > 3:
                    f = 3
            else:
                a = self.boar_run
                f = (t >> 2) & 3
            a.draw(fb, f, (self.b_x >> FP) - 16 + a.ox, GROUND - a.h)
        if self.arrow >= 0:
            tip = self.arrow >> FP
            fb.hline(tip - 7, LANE_Y, 8, 1)
            fb.pixel(tip - 7, LANE_Y - 1, 1)
            fb.pixel(tip - 7, LANE_Y + 1, 1)
        hearts(fb, self.hearts)
        hud(fb, self.score)

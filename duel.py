"""WOLF DUEL: three beasts take turns at Red; whack each one out of its attack.

Press to swing the basket. The swing only connects while the beast is coming at her and in
reach, and swinging at nothing leaves Red open to a free bite. They come four at a time:

  the wolf  crouches, flashes a "!" and leaps: swing as he leaps, not at the "!". Later he
            sometimes stands back up instead.
  the boar  paws the ground, backs off and charges. How far he backs off and how long the
            charge takes change every time, so watch him come.
  the bear  rears up, flashes a "!" and swipes; the first blow only staggers him and he
            swipes again. Putting him down takes two and scores two.

Three hearts. The tells get shorter and the attacks faster as the score climbs.
"""
from micropython import const

import sprites_duel as sprites
from engine import GROUND, Anim, Backdrop, Rng, hearts, hud, num, text

RED_X = const(0)  # screen x of Red's 32 px source cell
HOME = const(40)  # screen x of the beast's cell when it waits
REACH = const(30)  # the basket connects once the beast's cell is this far left
SWING_TICKS = const(30)
ACTIVE_FROM = const(8)  # swing ticks during which the basket can connect
ACTIVE_TO = const(16)
COUNTER_AT = const(12)  # a whiffed swing is answered at this swing tick ...
COUNTER_LUNGE = const(14)  # ... by an attack this fast, landing before Red recovers
HEARTS = const(3)
ROUND = const(4)  # each beast leaves after being put down this many times

WOLF = const(0)
BOAR = const(1)
BEAR = const(2)
_END = b"\x0e\x10\x10"  # the cell's x when each beast's attack reaches Red

TITLE = const(0)
PLAY = const(1)
DEAD = const(2)
OVER = const(3)

SIT = const(0)
CROUCH = const(1)
WARN = const(2)
LUNGE = const(3)
RECOIL = const(4)
BITE = const(5)
BACK = const(6)
ENTER = const(7)
LEAVE = const(8)
STAGGER = const(9)  # the bear, after the first blow

_SWING_FRAME = b"\x00\x00\x00\x00\x01\x01\x01\x01\x02\x02\x02\x03\x03\x03\x03\x03\x04\x04\x04\x04\x04\x04\x05\x05\x05\x05\x05\x05\x05\x05"


class Game:
    def __init__(self, fb, best=0, seed=1):
        self.fb = fb
        self.best = best
        self.rng = Rng(seed)
        self.stir = self.rng.stir
        self.red_idle = Anim(sprites.red_idle)
        self.red_swing = Anim(sprites.red_swing)
        self.red_hit = Anim(sprites.red_hit)
        self.red_death = Anim(sprites.red_death)
        # per beast: waiting, the tell, the attack, being hit
        self.idle = (Anim(sprites.wolf_idle), Anim(sprites.boar_idle), Anim(sprites.bear_idle))
        self.tell = (Anim(sprites.wolf_warn), Anim(sprites.boar_paw), Anim(sprites.bear_rear))
        self.att = (Anim(sprites.wolf_lunge), Anim(sprites.boar_charge), Anim(sprites.bear_swipe))
        self.hit = (Anim(sprites.wolf_hit), Anim(sprites.boar_hit), Anim(sprites.bear_hit))
        self.back = Backdrop()
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
        self.swing = -1  # swing tick, -1 when Red is ready
        self.hurt = 0
        self.foe = WOLF
        self.end = _END[WOLF]
        self.downs = 0  # beasts put down
        self.dazed = False  # the bear has taken his first blow
        self.ph = SIT
        self.wt = 0  # ticks in the beast's current phase
        self.wlen = 60  # length of that phase
        self.fx = HOME
        self.far = HOME  # where the current attack started from
        self.lunge_len = 24

    def _level(self):
        lv = self.score // 3
        return lv if lv < 8 else 8

    def _phase(self, phase, length):
        self.ph = phase
        self.wt = 0
        self.wlen = length

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
            if self.fx < HOME:
                self.fx += 1
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
        if self.hurt:
            self.hurt -= 1
        if self.swing >= 0:
            self.swing += 1
            if self.swing >= SWING_TICKS:
                self.swing = -1
        elif edge and self.hurt == 0:
            self.swing = 0

        p = self.ph
        foe = self.foe
        self.wt += 1
        wt = self.wt
        self.led = p == WARN
        if p == SIT:
            if self.swing == COUNTER_AT:
                self._leap(COUNTER_LUNGE)
            elif wt >= self.wlen:
                self._phase(CROUCH, 25 + self.rng.next() % 60)
        elif p == CROUCH:
            if self.swing == COUNTER_AT:
                self._leap(COUNTER_LUNGE)
            elif wt >= self.wlen:
                self._tell()
        elif p == WARN:
            if foe == BOAR and self.fx < self.far:
                self.fx += 1  # backing off for the run-up
            if wt >= self.wlen:
                self._attack()
        elif p == LUNGE:
            self.fx = self.far - (self.far - self.end) * wt // self.lunge_len
            if self.fx <= REACH and ACTIVE_FROM <= self.swing < ACTIVE_TO:
                self.flash = 4
                if foe == BEAR and not self.dazed:
                    self.dazed = True
                    self._phase(STAGGER, 12)
                else:
                    self.score += 2 if foe == BEAR else 1
                    self.downs += 1
                    self._phase(RECOIL, 34)
            elif wt >= self.lunge_len:
                self.hearts -= 1
                self.flash = 4
                self.hurt = 40
                self.swing = -1
                self._phase(BITE, 16)
                if self.hearts == 0:
                    self.state = DEAD
                    self.t = 0
        elif p == STAGGER:
            if self.fx < HOME and wt & 1:
                self.fx += 1
            if wt >= self.wlen:
                self._phase(CROUCH, 12 + self.rng.next() % 30)
        elif p == RECOIL:
            if self.fx < HOME:
                self.fx += 2
            if wt >= self.wlen:
                if self.downs % ROUND == 0:
                    self._phase(LEAVE, 0)
                else:
                    self._sit()
        elif p == BITE:
            if wt >= self.wlen:
                self._phase(BACK, 26)
        elif p == BACK:
            if self.fx < HOME:
                self.fx += 1
            if wt >= self.wlen:
                self._sit()
        elif p == LEAVE:
            self.fx += 2
            if self.fx >= 74:
                self.foe = foe = (foe + 1) % 3
                self.end = _END[foe]
                self._phase(ENTER, 0)
        elif p == ENTER:
            self.fx -= 1
            if self.fx <= HOME:
                self._sit()

    def _tell(self):
        """The beast has waited long enough: start the tell that comes before its attack."""
        rng = self.rng
        lv = self._level()
        foe = self.foe
        if foe == WOLF:
            if lv >= 3 and rng.next() % 10 < 3:
                self._phase(SIT, 20 + rng.next() % 30)  # fake-out: he stands back up
            else:
                self._phase(WARN, 24 - lv * 5 // 4)
        elif foe == BOAR:
            self.far = 50 + rng.next() % 20
            self._phase(WARN, self.far - HOME)
        elif self.dazed:
            self._phase(WARN, 16 - (lv >> 1))
        else:
            self._phase(WARN, 24 - lv * 5 // 4)

    def _attack(self):
        lv = self._level()
        foe = self.foe
        if foe == WOLF:
            self._leap(24 - lv)
        elif foe == BOAR:
            self._leap(40 - lv * 3 // 2 + self.rng.next() % 10)
        elif self.dazed:
            self._leap(16 - (lv >> 1))
        else:
            self._leap(22 - lv)

    def _leap(self, length):
        self.far = self.fx
        self.lunge_len = length
        self._phase(LUNGE, length)

    def _sit(self):
        self.fx = HOME
        self.dazed = False
        self._phase(SIT, 50 - self._level() * 3 + self.rng.next() % 40)

    # ---- drawing ---------------------------------------------------------

    def _draw_foe(self, resting):
        fb = self.fb
        t = self.t
        foe = self.foe
        p = self.ph
        wt = self.wt
        fx = self.fx
        hop = 0
        if resting or p == SIT:
            a = self.idle[foe]
            f = (t >> 4) & 3
        elif p == CROUCH:
            a = self.tell[foe]
            f = (wt >> 3) & 1 if foe == BOAR else 0
        elif p == WARN:
            a = self.tell[foe]
            f = (wt >> 2) & 1
            f = 1 + f if foe == WOLF else 2 + f if foe == BOAR else 1
            if (wt >> 1) & 1 == 0:
                x = fx - 5 if foe == BEAR else fx + 13
                fb.fill_rect(x, 3, 3, 6, 1)
                fb.fill_rect(x, 11, 3, 3, 1)
        elif p == LUNGE:
            a = self.att[foe]
            if foe == WOLF:
                f = wt * 8 // self.lunge_len & 7
            elif foe == BOAR:
                f = 1 + ((wt >> 1) & 3)
            else:
                f = 0 if wt * 2 < self.lunge_len else 1
        elif p == BITE:
            if foe == WOLF:
                a = self.tell[foe]
                f = 0
            else:
                a = self.att[foe]
                f = a.n - 1
        elif p == RECOIL or p == STAGGER:
            a = self.hit[foe]
            f = (wt >> 3) & 1
            hop = wt if wt < 8 else 16 - wt if wt < 16 else 0
        else:  # walking in, out or back
            a = self.idle[foe]
            f = (t >> 2) & 3
        a.draw(fb, f, fx + a.ox, GROUND - a.h - hop)

    def draw(self):
        fb = self.fb
        s = self.state
        t = self.t
        back = self.back
        fb.fill(0)
        if s == TITLE:
            back.ground(fb, 0)
            a = self.red_idle
            a.draw(fb, (t >> 4) & 3, RED_X + a.ox, GROUND - a.h)
            a = self.idle[WOLF]
            a.draw(fb, (t >> 4) & 3, HOME + a.ox, GROUND - a.h)
            if (t >> 7) & 1:
                text(fb, b"SWING AS HE LEAPS", 2, 3)
            else:
                fb.text("WOLF DUEL", 0, 1, 1)
            if (t >> 5) & 1 == 0:
                text(fb, b"PRESS", 26, 22)
            return
        if s == OVER:
            back.ground(fb, 0)
            a = self.red_death
            a.draw(fb, 3, RED_X + a.ox, GROUND - a.h)
            a = self.idle[self.foe]
            a.draw(fb, (t >> 4) & 3, HOME + a.ox, GROUND - a.h)
            fb.text(self.score_text, 36 - 4 * len(self.score_text), 2, 1)
            if self.new_best:
                if (t >> 4) & 1 == 0:
                    text(fb, b"NEW BEST", 10, 12)
            else:
                text(fb, b"BEST", 12, 12)
                num(fb, self.best, 42, 12)
            return

        back.sky(fb, t, 0, 31)
        back.trees(fb, 0)
        back.ground(fb, 0)
        self._draw_foe(s == DEAD)

        if s == DEAD:
            a = self.red_death
            f = t // 12
            a.draw(fb, f if f < 3 else 3, RED_X + a.ox, GROUND - a.h)
        elif self.swing >= 0:
            a = self.red_swing
            a.draw(fb, _SWING_FRAME[self.swing], RED_X + a.ox, GROUND - a.h)
        elif self.hurt:
            a = self.red_hit
            a.draw(fb, (self.hurt >> 3) & 1, RED_X + a.ox, GROUND - a.h)
        else:
            a = self.red_idle
            a.draw(fb, (t >> 4) & 3, RED_X + a.ox, GROUND - a.h)

        hearts(fb, self.hearts)
        hud(fb, self.score)

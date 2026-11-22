"""Shared parts of the one-button games: screen constants, sprites, small font, night backdrop.

A game is a class Game(fb, best, seed) with tick(pressed) at 60 Hz, draw(), stir(n), and the
attributes menu (True on its title and game-over screens), best, led and flash. Games are
hardware-free, so they also run under host MicroPython (tools/sim.py).
"""
import framebuf
from micropython import const

W = const(72)
H = const(40)
GROUND = const(37)  # first ground row; feet stand on the row above
FP = const(8)  # positions and speeds are fixed point, 1/256 px
FAR_W = const(96)
GND_W = const(48)

_FB = framebuf.FrameBuffer
_HLSB = framebuf.MONO_HLSB

# Blitting a mask through this palette with key 1 clears the mask's set pixels.
_CUT = _FB(bytearray(1), 2, 1, _HLSB)
_CUT.pixel(0, 0, 1)


class Rng:
    def __init__(self, seed):
        self.s = seed % 65537 or 1

    def next(self):
        self.s = self.s * 75 % 65537
        return self.s

    def stir(self, n):
        self.s = (self.s + n) % 65537 or 1


class Anim:
    """Frames from a sprites_*.py entry: (w, h, ox, ((bits, mask), ...))."""

    def __init__(self, src):
        self.w, self.h, self.ox, frames = src
        self.n = len(frames)
        self.bits = [_FB(bytearray(b), self.w, self.h, _HLSB) for b, m in frames]
        self.mask = [_FB(bytearray(m), self.w, self.h, _HLSB) for b, m in frames]

    def draw(self, fb, i, x, y):
        fb.blit(self.mask[i], x, y, 1, _CUT)
        fb.blit(self.bits[i], x, y, 0)


_GLYPHS = {
    "0": "111101101101111", "1": "010110010010111", "2": "111001111100111",
    "3": "111001111001111", "4": "101101111001001", "5": "111100111001111",
    "6": "111100111101111", "7": "111001001001001", "8": "111101111101111",
    "9": "111101111001111",
    "A": "010101111101101", "B": "110101110101110", "C": "011100100100011",
    "D": "110101101101110", "E": "111100110100111", "F": "111100110100100",
    "G": "011100101101011", "H": "101101111101101", "I": "111010010010111",
    "J": "001001001101010", "K": "101101110101101", "L": "100100100100111",
    "M": "101111111101101", "N": "110101101101101", "O": "010101101101010",
    "P": "110101110100100", "Q": "010101101111011", "R": "110101110101101",
    "S": "011100010001110", "T": "111010010010010", "U": "101101101101111",
    "V": "101101101101010", "W": "101101111111101", "X": "101101010101101",
    "Y": "101101010010010", "Z": "111001010100111", "!": "010010010000010",
}


def _glyph(bits):
    fb = _FB(bytearray(5), 3, 5, _HLSB)
    for i in range(15):
        if bits[i] == "1":
            fb.pixel(i % 3, i // 3, 1)
    return fb


FONT = {ord(k): _glyph(v) for k, v in _GLYPHS.items()}
DIGITS = [FONT[48 + i] for i in range(10)]


def text(fb, s, x, y):
    """Draw bytes in the 3x5 font (4 px advance); unknown characters are spaces."""
    for i in range(len(s)):
        g = FONT.get(s[i])
        if g:
            fb.blit(g, x, y, 0)
        x += 4


def num(fb, n, right, y):
    """Draw a number right-aligned so its last column is `right`."""
    x = right - 3
    while True:
        fb.blit(DIGITS[n % 10], x, y, 0)
        n //= 10
        if n == 0:
            return
        x -= 4


def hud(fb, n):
    """Score in the top-right corner on a cleared box."""
    w = 3 if n < 10 else 7 if n < 100 else 11 if n < 1000 else 15 if n < 10000 else 19
    fb.fill_rect(70 - w, 0, w + 2, 7, 0)
    num(fb, n, 71, 1)


def _heart():
    fb = _FB(bytearray(5), 5, 5, _HLSB)
    for y, bits in enumerate((0b01010, 0b11111, 0b11111, 0b01110, 0b00100)):
        for x in range(5):
            if bits >> (4 - x) & 1:
                fb.pixel(x, y, 1)
    return fb


HEART = _heart()


def hearts(fb, n):
    """Lives in the top-left corner on a cleared box."""
    fb.fill_rect(0, 0, 19, 7, 0)
    for i in range(n):
        fb.blit(HEART, 1 + i * 6, 1, 0)


def logo(s):
    """The built-in 8x8 font at double size, as a framebuffer."""
    n = len(s) * 8
    small = _FB(bytearray(len(s) * 8), n, 8, _HLSB)
    small.text(s, 0, 0, 1)
    fb = _FB(bytearray(len(s) * 2 * 16), n * 2, 16, _HLSB)
    for y in range(8):
        for x in range(n):
            if small.pixel(x, y):
                fb.fill_rect(x * 2, y * 2, 2, 2, 1)
    return fb


class Backdrop:
    """Night forest: twinkling stars, a moon, stippled pines and a ground strip that scroll."""

    def __init__(self):
        rng = Rng(7)
        self.far = self._far(rng)
        self.gnd = self._ground(rng)
        self.moon = self._moon()
        self.stars = bytes((22, 2, 33, 9, 44, 4, 57, 12, 66, 6, 3, 15, 28, 16, 49, 19))

    def _far(self, rng):
        fw = FAR_W + W
        fh = 24
        fb = _FB(bytearray(((fw + 7) // 8) * fh), fw, fh, _HLSB)
        x = 3
        while x < FAR_W - 4:
            h = 9 + rng.next() % 10
            half = 3 + h // 6
            cx = x + half
            tier = (h - 3) // 3
            for r in range(h):
                if r >= h - 3:
                    hw = 0
                else:
                    hw = 1 + (r % tier) * half // tier + (r // tier)
                    if hw > half:
                        hw = half
                y = fh - h + r
                for px in range(cx - hw, cx + hw + 1):
                    if (hw == 0 and y & 1) or ((px + y) & 3 == 0 and y & 1 == 0):
                        fb.pixel(px % FAR_W, y, 1)
                        if px % FAR_W < W:
                            fb.pixel(px % FAR_W + FAR_W, y, 1)
            x += half * 2 + 5 + rng.next() % 12
        return fb

    def _ground(self, rng):
        fw = GND_W + W
        fb = _FB(bytearray(((fw + 7) // 8) * 4), fw, 4, _HLSB)
        fb.hline(0, 1, fw, 1)
        x = 2
        while x < GND_W - 2:
            r = rng.next()
            row = 0 if r % 3 == 0 else 3
            n = 1 + (r >> 4) % 2 if row == 0 else 1 + (r >> 4) % 3
            for px in range(x, x + n):
                fb.pixel(px, row, 1)
                if px < W:
                    fb.pixel(px + GND_W, row, 1)
            x += n + 3 + (r >> 8) % 7
        return fb

    def _moon(self):
        fb = _FB(bytearray(2 * 9), 9, 9, _HLSB)
        for y in range(9):
            for x in range(9):
                d = (x - 4) * (x - 4) + (y - 4) * (y - 4)
                c = (x - 7) * (x - 7) + (y - 3) * (y - 3)
                if d <= 18 and c > 14:
                    fb.pixel(x, y, 1)
        return fb

    def sky(self, fb, t, drift=0, moon=8):
        """Stars, shifted left by drift, and the moon at x = moon (None for no moon)."""
        st = self.stars
        for i in range(0, len(st), 2):
            if (t + i * 23) & 127 > 5:
                fb.pixel((st[i] - drift) % W, st[i + 1], 1)
        if moon is not None:
            fb.blit(self.moon, moon, 3, 0)

    def trees(self, fb, px):
        fb.blit(self.far, -((px >> 2) % FAR_W), GROUND - 24, 0)

    def ground(self, fb, px):
        fb.blit(self.gnd, -(px % GND_W), GROUND - 1, 0)

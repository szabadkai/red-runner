"""One-button console: OLED, BOOT button (GPIO 9), LED (GPIO 8), game picker, 60 Hz loop.

On a menu screen (the picker, or a game's title and game-over screens) a tap is the screen's
action and holding the button for HOLD ticks is the other one: play the game shown in the
picker, or leave a game for the picker. A bar grows along the bottom while holding.
"""
import gc
import sys
import time

from machine import Pin

import oled
from engine import num, text

TICK_US = 16667
HOLD = 45
SLEEP_TICKS = 60 * 120  # blank the OLED after two idle minutes on a menu, to spare the panel

# module name, title; best scores live in files named best_<module>
GAMES = (
    ("runner", "RED RUN"),
    ("duel", "WOLF DUEL"),
    ("wisp", "LOST WISP"),
    ("hunter", "HUNTSMAN"),
    ("pinball", "PINBALL"),
    ("golf", "TINY GOLF"),
)


def read_int(name):
    try:
        with open(name) as f:
            return int(f.read())
    except (OSError, ValueError):
        return 0


def write_int(name, value):
    with open(name, "w") as f:
        f.write(str(value))


class Picker:
    """The game list. A tap shows the next game."""

    menu = True
    led = False
    flash = 0
    best = 0

    def __init__(self, fb, sel):
        self.fb = fb
        self.sel = sel
        self.t = 0
        self.bests = [read_int("best_" + module) for module, title in GAMES]

    def stir(self, n):
        pass

    def tick(self, pressed):
        self.t += 1
        if pressed:
            self.sel = (self.sel + 1) % len(GAMES)
            self.t = 0

    def draw(self):
        fb = self.fb
        fb.fill(0)
        title = GAMES[self.sel][1]
        fb.text(title, 36 - 4 * len(title), 3, 1)
        text(fb, b"BEST", 20, 15)
        num(fb, self.bests[self.sel], 51, 15)
        n = len(GAMES)
        for i in range(n):
            x = 38 - n * 4 + i * 8
            if i == self.sel:
                fb.fill_rect(x, 23, 4, 4, 1)
            else:
                fb.rect(x, 23, 4, 4, 1)
        text(fb, b"TAP FOR NEXT" if (self.t >> 6) & 1 else b"HOLD TO PLAY", 12, 31)


def loop(d, btn, led, scene, save=None, frames=0):
    """Run a scene at 60 Hz until the button is held on one of its menu screens.

    save names the game whose best score to keep. frames > 0 returns after that many drawn
    frames instead (for timing tests).
    """
    best = scene.best
    last = time.ticks_us()
    acc = 0
    inverted = False
    asleep = False
    armed = False  # the button has been up since this screen appeared
    was_menu = True
    held = 0
    idle = 0
    while True:
        now = time.ticks_us()
        acc += time.ticks_diff(now, last)
        last = now
        if acc < TICK_US:
            time.sleep_ms(1)
            continue
        if acc > 4 * TICK_US:
            acc = 4 * TICK_US
        pressed = not btn.value()
        if asleep:
            acc = 0
            if pressed:
                asleep = False
                armed = False  # the waking press must not act
                idle = 0
                d.power(True)
            continue
        if scene.menu:
            scene.stir(now)
        while acc >= TICK_US:
            acc -= TICK_US
            menu = scene.menu
            if menu and not was_menu:
                armed = False  # a button still down from play must be let go first
            was_menu = menu
            p = False
            if not armed:
                armed = not pressed
                held = 0
            elif not menu:
                p = pressed
            elif pressed:
                held += 1
                if held >= HOLD:
                    led.value(1)
                    if inverted:
                        d.invert(False)
                    return
            elif held:
                held = 0
                p = True
            scene.tick(p)
            idle = 0 if pressed else idle + 1
        scene.draw()
        if held > 6:
            d.fill_rect(0, 38, held * 72 // HOLD, 2, 1)
        d.show()
        if frames:
            frames -= 1
            if frames == 0:
                return
        led.value(not scene.led)
        if (scene.flash > 0) != inverted:
            inverted = not inverted
            d.invert(inverted)
        if save and scene.best != best:
            best = scene.best
            write_int("best_" + save, best)
        if scene.menu and idle > SLEEP_TICKS:
            asleep = True
            led.value(1)
            d.power(False)


def run():
    d = oled.OLED()
    btn = Pin(9, Pin.IN, Pin.PULL_UP)
    led = Pin(8, Pin.OUT, value=1)  # active low
    sel = read_int("last") % len(GAMES)
    while True:
        picker = Picker(d, sel)
        loop(d, btn, led, picker)
        if picker.sel != sel:
            sel = picker.sel
            write_int("last", sel)
        picker = None
        name = GAMES[sel][0]
        d.fill(0)
        text(d, b"LOADING", 22, 17)
        d.show()
        gc.collect()
        game = __import__(name).Game(d, read_int("best_" + name), time.ticks_us())
        gc.collect()
        loop(d, btn, led, game, name)
        game = None
        for module in (name, "sprites_" + name):
            sys.modules.pop(module, None)
        gc.collect()

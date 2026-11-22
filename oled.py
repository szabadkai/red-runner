"""72x40 SSD1306 OLED on the ABrobot ESP32-C3 0.42" board (I2C 0x3C, SDA 5, SCL 6).

The glass is a 72x40 window into a 128x64 controller. The start line is shifted so the
window is RAM rows 0-39 (pages 0-4), and each frame is one 360-byte windowed write.

ROTATED picks which way up the picture is: True with the USB socket at the top and the
buttons at the bottom, False the other way round.
"""
import time

import framebuf
from machine import I2C, Pin

W = 72
H = 40
XOFF = 28  # first visible column; the glass is centred, so the same either way up
YOFF = 24  # first visible row with start line 0, buttons at the top
ROTATED = True


class OLED(framebuf.FrameBuffer):
    def __init__(self, sda=5, scl=6, freq=400000, addr=0x3C, xoff=XOFF, yoff=YOFF, rotated=ROTATED):
        self.i2c = I2C(0, sda=Pin(sda), scl=Pin(scl), freq=freq)
        self.addr = addr
        self.xoff = xoff
        self._tx = bytearray(1 + W * H // 8)
        self._tx[0] = 0x40
        self.buf = memoryview(self._tx)[1:]
        super().__init__(self.buf, W, H, framebuf.MONO_VLSB)
        self._win = bytearray((0x00, 0x21, xoff, xoff + W - 1, 0x22, 0, H // 8 - 1))
        for attempt in range(20):  # the panel can miss the first transfer after a reset
            try:
                self._cmd(
                    0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00,
                    # the glass is wired to the first 40 rows, which scan upwards unrotated
                    0x40 if rotated else 0x40 | ((64 - yoff) & 0x3F),
                    0x8D, 0x14, 0x20, 0x00,
                    0xA0 if rotated else 0xA1,
                    0xC0 if rotated else 0xC8,
                    0xDA, 0x12,
                    0x81, 0xCF, 0xD9, 0xF1, 0xDB, 0x40, 0x2E, 0xA4, 0xA6,
                )
                break
            except OSError:
                time.sleep_ms(25)
        self.fill(0)
        self.show()
        self._cmd(0xAF)

    def _cmd(self, *c):
        self.i2c.writeto(self.addr, bytes((0x00,) + c))

    def show(self):
        self.i2c.writeto(self.addr, self._win)
        self.i2c.writeto(self.addr, self._tx)

    def power(self, on):
        self._cmd(0xAF if on else 0xAE)

    def invert(self, on):
        self._cmd(0xA7 if on else 0xA6)

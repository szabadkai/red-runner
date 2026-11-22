"""Turn raw 72x40 MONO_VLSB frames (from tools/sim.py or the board) into a PNG sheet or GIF.

  uv run --with pillow python tools/frames.py IN.bin OUT.png [cols] [scale] [pick,pick,...]
  uv run --with pillow python tools/frames.py IN.bin OUT.gif [scale] [ms per frame]
"""
import sys

from PIL import Image

W, H = 72, 40


def load(path):
    data = open(path, "rb").read()
    out = []
    for o in range(0, len(data) - 359, 360):
        im = Image.new("L", (W, H), 0)
        px = im.load()
        for page in range(5):
            for x in range(W):
                b = data[o + page * W + x]
                for bit in range(8):
                    if b >> bit & 1:
                        px[x, page * 8 + bit] = 255
        out.append(im)
    return out


def main():
    src, dst = sys.argv[1], sys.argv[2]
    fr = load(src)
    if dst.endswith(".gif"):
        s = int(sys.argv[3]) if len(sys.argv) > 3 else 6
        ms = int(sys.argv[4]) if len(sys.argv) > 4 else 33
        big = [f.resize((W * s, H * s), Image.NEAREST) for f in fr]
        big[0].save(dst, save_all=True, append_images=big[1:], duration=ms, loop=0)
        return
    cols = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    s = int(sys.argv[4]) if len(sys.argv) > 4 else 4
    if len(sys.argv) > 5:
        fr = [fr[int(i)] for i in sys.argv[5].split(",")]
    rows = (len(fr) + cols - 1) // cols
    gap = 2
    sheet = Image.new("RGB", (cols * (W + gap) + gap, rows * (H + gap) + gap), (70, 30, 30))
    for i, f in enumerate(fr):
        sheet.paste(f.convert("RGB"), (gap + (i % cols) * (W + gap), gap + (i // cols) * (H + gap)))
    sheet.resize((sheet.width * s, sheet.height * s), Image.NEAREST).save(dst)
    print(len(fr), "frames")


main()

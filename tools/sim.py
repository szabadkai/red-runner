"""Run a game off the board, under host MicroPython, with a bot on the button.

  micropython tools/sim.py frames GAME OUT.bin [ticks] [every] [seed]   dump raw 360-byte frames
  micropython tools/sim.py fair GAME [ticks] [seeds]                    a perfect bot must never be hit
  micropython tools/sim.py stats pinball [games] [delay] [jitter]       whole games; the bot sees the ball delay ticks
                                                                        late and flips up to jitter ticks later still
  micropython tools/sim.py stats golf [jitter]                          a round by a bot that tries every shot first,
                                                                        then misses its power by up to jitter

GAME is runner, duel, wisp, hunter, pinball or golf (`fair` is for the first four: they have hearts to lose).
In `frames` the bot plays badly now and then, so the dump also shows the stumble, bite and
game-over screens.
"""
import sys

sys.path.insert(0, ".")
import framebuf


def make(name, seed):
    mod = __import__(name)
    buf = bytearray(360)
    fb = framebuf.FrameBuffer(buf, 72, 40, framebuf.MONO_VLSB)
    return mod, mod.Game(fb, 0, seed), buf


def start(g, n):
    """Tap through title and game-over screens."""
    return g.t > 40 and g.t % 20 < 3


def runner_bot(m, g, n, sloppy):
    if g.state != m.PLAY:
        return start(g, n)
    if g.air:
        return False
    lead = (g.speed * 9 >> 8) - (14 if sloppy else 0)
    for i in range(m.MAXO):
        k = g.ob_kind[i]
        if k < 0 or k == m.RAVEN:
            continue
        gap = (g.ob_x[i] >> 8) + m.HIT_L[k] - m.RED_R
        if -4 <= gap <= lead:
            return True
    return False


def duel_bot(m, g, n, sloppy):
    if g.state != m.PLAY:
        return g.state != m.DEAD and start(g, n)
    if g.swing >= 0:
        return False
    if sloppy:
        return g.ph == m.CROUCH and g.wt == 10  # swing at nothing
    # swing so the basket is live when the beast comes into reach
    if g.ph == m.LUNGE:
        reach_t = (g.far - m.REACH) * g.lunge_len // (g.far - g.end) + 1 if g.far > m.REACH else 0
        return reach_t - g.wt <= m.ACTIVE_FROM + 2
    return False


HORIZON = [3]  # ticks ahead the wisp bot steers by; a bot with late hands needs more


def wisp_bot(m, g, n, sloppy):
    if g.state != m.PLAY:
        return g.state != m.POP and start(g, n)
    if sloppy:
        return False
    # safe range for the wisp's centre at the next two thickets; sit in the first one as
    # close as possible to the middle of the second
    ahead = []
    centre = (g.y >> 8) + (m.HIT_T + m.HIT_B) // 2
    for i in range(m.MAXO):
        if g.ob_live[i]:
            px = g.ob_x[i] >> 8
            if g.ob_raven[i]:
                if px + m.RAVEN_W - m.R_INSET > m.HIT_L:
                    # over or under, whichever is nearer
                    mid = g.ob_top[i] + (m.R_T + m.R_B) // 2
                    if centre <= mid:
                        ahead.append((px, 5, g.ob_top[i] + m.R_T - 5))
                    else:
                        ahead.append((px, g.ob_top[i] + m.R_B + 5, 35))
            elif px + m.THICKET_W - m.T_INSET > m.HIT_L:
                lo = g.ob_top[i] - m.T_TIP + 5 if g.ob_top[i] else 5
                hi = 40 - g.ob_bot[i] + m.T_TIP - 5 if g.ob_bot[i] else 35
                ahead.append((px, lo, hi))
    ahead.sort()
    target = centre
    if len(ahead) > 1:
        target = (ahead[1][1] + ahead[1][2]) // 2
    if ahead:
        lo, hi = ahead[0][1], ahead[0][2]
        target = lo if target < lo else hi if target > hi else target
    return centre + (g.vy * HORIZON[0] >> 8) > target


_shadow = []


def hunter_would_hit(m, g):
    """Would an arrow loosed this tick hit a raven? Plays it out on a copy of the game."""
    if not _shadow:
        _shadow.append(m.Game(g.fb, 0, 1))
    sh = _shadow[0]
    sh.state = m.PLAY
    sh.score = 0
    sh.hearts = m.HEARTS
    for name in ("r_state", "r_x", "r_y", "r_v", "r_ph", "r_dp", "r_t"):
        src, dst = getattr(g, name), getattr(sh, name)
        for i in range(m.MAXR):
            dst[i] = src[i]
    sh.arrow = m.ARROW_X0 << 8
    while sh.arrow >= 0:
        sh._arrow()
        sh._ravens()
    return sh.score > 0


def hunter_bot(m, g, n, sloppy):
    if g.state != m.PLAY:
        return g.state != m.DEAD and start(g, n)
    if g.nock or g.prev:
        return False
    if sloppy:
        return n % 50 == 0  # shoots on a timer, mostly at nothing
    if g.b_state == m.B_RUN or g.b_state == m.B_STUN:
        return True  # the boar: as soon as there is an arrow
    if g.b_state == m.B_WARN:
        return False
    # shoot each raven at the dip the game promises, never earlier ones
    for i in range(m.MAXR):
        if g.r_state[i] == m.WAVE and g.tick_n + 1 >= g.r_fire[i]:
            return hunter_would_hit(m, g)
    return False


_seen = []  # the ball's recent past, for a bot with slow eyes
_hold = [0]
_dice = [1]
_late = [0]
DELAY = [0]
JITTER = [0]


def pinball_bot(m, g, n, sloppy):
    if g.state != m.PLAY:
        del _seen[:]
        _hold[0] = 0
        return g.state != m.LOST and start(g, n)
    if g.x > m.LANE:
        return g.charge < m.CHARGE_MAX - 2 - g.hearts * 3  # wind up, a little differently each ball
    if sloppy:
        return False
    _seen.append((g.x, g.y, g.vx, g.vy))
    if len(_seen) > DELAY[0] + 1:
        _seen.pop(0)
    if _hold[0] > 0:
        _hold[0] -= 1
        return _hold[0] > 6  # up for 10 ticks, then down for at least 6
    x, y, vx, vy = _seen[0]
    ux = g.ux[0]
    uy = g.uy[0]
    ry = y - g.py
    for side in range(2):
        rx = g.prx - x if side else x - g.plx
        wx = -vx if side else vx
        t = (rx * ux + ry * uy) >> 8
        d = (rx * uy - ry * ux) >> 8
        # flip when the ball, 3 ticks on from what the bot sees, is on the flipper's outer part
        lead = 3 + DELAY[0]
        t += ((wx * ux + vy * uy) >> 8) * lead
        if d >= 0 and 9 * 256 < t < g.flen + 256 and d - m.RF < 128 - ((wx * uy - vy * ux) >> 8) * lead:
            # a tick late now and then, so it never repeats one shot for ever; with jitter,
            # up to that many ticks late, like a thumb
            _dice[0] = _dice[0] * 75 % 65537
            if _late[0] == 0:
                _late[0] = 1 + _dice[0] % (JITTER[0] + 1) + (_dice[0] >> 8 & 3 == 0)
            _late[0] -= 1
            if _late[0]:
                return False
            _hold[0] = 16
            return True
    return False


_golf = {}


def golf_try(m, g, sh, aim, power):
    """Play one shot on a copy of the game; returns how bad the result is, -1 for holed."""
    if sh.hole != g.hole:
        sh._load(g.hole)
    sh.strokes = 0
    sh.x = g.x
    sh.y = g.y
    sh.lx = g.x
    sh.ly = g.y
    sh.dir = g.dir
    sh.rough = g.rough
    sh.t = 0
    sh._launch(aim, power)
    while sh.state == m.FLY:
        sh.t += 1
        sh._fly()
    if sh.state == m.HOLED:
        return -1
    d = abs((sh.x >> 8) - g.cup)
    return d + 100 if sh.state == m.SPLASH else d + 30 if sh.rough else d


def golf_bot(m, g, n, sloppy):
    """Tries every angle and every second power on a copy and plays the one that ends nearest."""
    if g.state == m.TITLE or g.state == m.OVER:
        return start(g, n)
    if g.state == m.AIM:
        key = (g.hole, g.strokes, g.x, g.y)
        if _golf.get("key") != key:
            _golf["key"] = key
            if "sh" not in _golf:
                _golf["sh"] = m.Game(g.fb, 0, 1)
            best = None
            for aim in range(16):
                for power in range(2, m.POWER_MAX + 1, 2):
                    r = golf_try(m, g, _golf["sh"], aim, power)
                    if best is None or r < best[0]:
                        best = (r, aim, power)
            aim, power = best[1:]
            if JITTER[0]:
                # an unsteady hand: a step of aim and a few of power either way
                _dice[0] = _dice[0] * 75 % 65537
                aim = min(15, max(0, aim + _dice[0] % 3 - 1))
                power = min(m.POWER_MAX, max(1, power + (_dice[0] >> 4) % (2 * JITTER[0] + 1) - JITTER[0]))
            _golf["shot"] = (7, 30) if sloppy and g.strokes == 0 else (aim, power)
        return g.aim == _golf["shot"][0]
    if g.state == m.CHARGE:
        return g.power < _golf["shot"][1]
    return False


BOTS = {"runner": runner_bot, "duel": duel_bot, "wisp": wisp_bot, "hunter": hunter_bot, "pinball": pinball_bot, "golf": golf_bot}


def hurt(name, m, g, was):
    """True if the player took damage this tick."""
    if name == "runner":
        return g.state != m.PLAY or g.danger > was
    return g.hearts < m.HEARTS


def frames(name, path, ticks, every, seed):
    m, g, buf = make(name, seed)
    bot = BOTS[name]
    with open(path, "wb") as f:
        for n in range(ticks):
            sloppy = 500 < n < 640 or 900 < n < 1100 or n > 1500
            was = (g.state, getattr(g, "hearts", 0), getattr(g, "danger", 0))
            g.tick(bot(m, g, n, sloppy))
            now = (g.state, getattr(g, "hearts", 0), getattr(g, "danger", 0))
            if now[0] != was[0] or now[1] != was[1] or now[2] > was[2]:
                print("tick", n, "state", g.state, "score", g.score, now[1:])
            if n % every == 0:
                g.draw()
                f.write(buf)
    print("state", g.state, "score", g.score, "best", g.best)


def fair(name, ticks, seeds):
    bot = BOTS[name]
    bad = 0
    for seed in range(1, seeds + 1):
        m, g, buf = make(name, seed * 7919)
        for n in range(45):
            g.tick(False)
        g.tick(True)
        g.tick(False)
        for n in range(ticks):
            was = getattr(g, "danger", 0)
            g.tick(bot(m, g, n, False))
            if hurt(name, m, g, was):
                bad += 1
                print("  seed", seed, "hit at tick", n, "score", g.score)
                break
        print("seed", seed, "score", g.score)
    print("FAIR" if bad == 0 else "UNFAIR")


def stats(name, games, delay, jitter):
    DELAY[0] = delay
    JITTER[0] = jitter
    bot = BOTS[name]
    total = 0
    for seed in range(1, games + 1):
        m, g, buf = make(name, seed * 7919)
        n = balls = shakes = targets = banks = 0
        while (g.state != m.OVER or n < 50) and n < 400000:
            was = g.still
            lost = g.state == m.LOST
            up = sum(g.tg)
            woke = g.awake[0] + g.awake[1]
            g.tick(bot(m, g, n, False))
            shakes += was > 179 and g.still == 0
            balls += g.state == m.LOST and not lost
            targets += sum(g.tg) < up
            banks += g.awake[0] + g.awake[1] > woke
            n += 1
        total += g.score
        print("seed", seed, "score", g.score, "targets", targets, "banks", banks, "jackpots", g.jackpots,
              "seconds per ball", n // 60 // (balls or 1), "shakes", shakes)
    print("mean score", total // games)


def round_of_golf(jitter):
    JITTER[0] = jitter
    m, g, buf = make("golf", 3)
    n = 0
    while g.state != m.OVER and n < 200000:
        was = g.state
        g.tick(golf_bot(m, g, n, False))
        n += 1
        if g.state == m.HOLED and was != m.HOLED:
            print("hole", g.hole + 1, "par", g.par, "strokes", g.strokes)
    print("round", g.score, "par", sum(h[0] for h in m.HOLES))


a = sys.argv
if a[1] == "stats" and a[2] == "golf":
    round_of_golf(int(a[3]) if len(a) > 3 else 0)
elif a[1] == "stats":
    stats(a[2], int(a[3]) if len(a) > 3 else 10, int(a[4]) if len(a) > 4 else 0, int(a[5]) if len(a) > 5 else 0)
elif a[1] == "frames":
    frames(a[2], a[3], int(a[4]) if len(a) > 4 else 600, int(a[5]) if len(a) > 5 else 1, int(a[6]) if len(a) > 6 else 3)
else:
    fair(a[2], int(a[3]) if len(a) > 3 else 20000, int(a[4]) if len(a) > 4 else 8)

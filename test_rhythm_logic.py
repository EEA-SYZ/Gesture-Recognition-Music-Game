# -*- coding: utf-8 -*-
"""Unit tests for the gesture rhythm game (no camera, display or sound needed).

Run with::

    .venv\\Scripts\\python.exe test_rhythm_logic.py
"""

from __future__ import absolute_import

import json
import os
import random
import sys
import tempfile
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from game_core import (RED_MILESTONES, STAGE_1, STAGE_2, HighScoreStore,  # noqa
                       Note, PLAY_BOTTOM, PLAY_TOP, RhythmGame)
from gesture_catalog import (ALL_PATTERNS, CATALOG, CODES_BY_VALUE,  # noqa
                             PATTERNS_5, PATTERNS_10, PATTERNS_15,
                             describe, format_code, hand_code,
                             hand_thumb_on_right, is_valid_code, make_code,
                             parse_hand, random_code, score_for_patterns,
                             value_of_code)

RESULTS = []


def check(name, condition, detail=""):
    RESULTS.append((name, bool(condition), detail))
    print("[{}] {}{}".format("PASS" if condition else "FAIL", name,
                             "  " + detail if detail else ""))


def gesture(code=None, start_pose=False):
    return SimpleNamespace(code=code, start_pose=start_pose, hand_count=2)


def advance(game, seconds, gesture_state=None, step=1.0 / 60.0):
    elapsed = 0.0
    while elapsed < seconds:
        game.update(min(step, seconds - elapsed), gesture_state)
        elapsed += step


# ---------------------------------------------------------------------------
# Gesture catalog
# ---------------------------------------------------------------------------
def test_examples_from_requirements():
    five = {
        "P11111P11111", "N11111N11111", "P11111N11111", "N11111P11111",
        "P00000P00000",
    }
    removed = {
        "N00000N00000", "P00000N00000", "N00000P00000",
    }
    ten = {
        "P01000P01000", "P01100P01100", "P01110P01110",
        "P01111P01111", "P00111P00111",
    }
    fifteen = {
        "P10000P10000", "P11000P11000", "P11100P11100", "P11001P11001",
        "N10000N10000", "P10000N10000", "N11000P11000", "N11001N11001",
    }
    twenty = {
        "P11111P00000", "P01000P01100", "P10000P01000", "P00111N11111",
        "P11000N11111", "P11100P01110", "P11001P01000",
    }
    for code in sorted(five):
        check("5 points {}".format(format_code(code)),
              value_of_code(code) == 5, describe(code))
    for code in sorted(removed):
        check("N hand with folded thumb is not a note",
              value_of_code(code) == 0, describe(code))
    for code in sorted(ten):
        check("10 points {}".format(format_code(code)),
              value_of_code(code) == 10, describe(code))
    for code in sorted(fifteen):
        check("15 points {}".format(format_code(code)),
              value_of_code(code) == 15, describe(code))
    for code in sorted(twenty):
        check("20 points {}".format(format_code(code)),
              value_of_code(code) == 20, describe(code))
    # Thumb variations: N hands must keep the thumb extended.
    check("yellow allows N (11000 thumb is extended)",
          value_of_code("N11000N11000") == 15)
    check("blue does not allow N (folded thumb)",
          value_of_code("N01110P01110") == 0)
    check("11000 is no longer a blue pattern",
          value_of_code("P11000P11000") == 15)
    # Everything else is not a note gesture.
    check("invalid pattern 10101", value_of_code("P10101P10101") == 0)
    check("invalid thumb X", value_of_code("X11111P11111") == 0)
    check("too short", value_of_code("P1111P11111") == 0)
    check("empty", value_of_code("") == 0)
    check("removed pattern 11010", value_of_code("P11010P11010") == 0)
    check("is_valid_code", is_valid_code("P11111N00000")
          and not is_valid_code("p11111n00000"))


def test_catalog_sizes_and_consistency():
    check("catalog total is 256", len(CATALOG) == 256, str(len(CATALOG)))
    sizes = {value: len(codes) for value, codes in CODES_BY_VALUE.items()}
    check("5 green gestures", sizes[5] == 5, str(sizes[5]))
    check("5 blue gestures", sizes[10] == 5, str(sizes[10]))
    check("16 yellow gestures", sizes[15] == 16, str(sizes[15]))
    check("230 red gestures", sizes[20] == 230, str(sizes[20]))
    check("categories are disjoint",
          not (set(CODES_BY_VALUE[5]) & set(CODES_BY_VALUE[10])) and
          not (set(CODES_BY_VALUE[10]) & set(CODES_BY_VALUE[15])) and
          not (set(CODES_BY_VALUE[15]) & set(CODES_BY_VALUE[20])))

    wrong = []
    for code, value in CATALOG.items():
        left_thumb, left_bits = parse_hand(code[:6])
        right_thumb, right_bits = parse_hand(code[6:])
        expected = score_for_patterns(left_bits, right_bits)
        if expected != value:
            wrong.append((code, value, expected))
        if value == 20 and left_bits == right_bits:
            wrong.append((code, "20 with equal patterns", ""))
        if value in (5, 10, 15) and left_bits != right_bits:
            wrong.append((code, "same-pattern rule broken", ""))
        for thumb, bits in ((left_thumb, left_bits),
                            (right_thumb, right_bits)):
            if thumb == "N" and bits[0] == "0":
                wrong.append((code, "N hand with folded thumb", ""))
    check("catalog rule consistency", not wrong, str(wrong[:4]))
    check("all patterns used", set(PATTERNS_5 + PATTERNS_10 +
                                   PATTERNS_15) == set(ALL_PATTERNS))
    check("11 per-hand patterns", len(ALL_PATTERNS) == 11)
    check("every N hand has the thumb out",
          all(parse_hand(code[6:])[0] != "N" or
              parse_hand(code[6:])[1][0] == "1"
              for code in CATALOG),
          "checked {} codes".format(len(CATALOG)))


def test_hand_code_helpers():
    check("hand_code", hand_code("p", "10101") == "P10101")
    check("make_code", make_code("N00000", "P11111") == "N00000P11111")
    check("format_code", format_code("N00000P11111") == "N00000 P11111")
    check("random_code value", all(
        value_of_code(random_code(value, random.Random(1))) == value
        for value in (5, 10, 15, 20)))
    check("thumb on right, left hand P", hand_thumb_on_right("P11111", "L"))
    check("thumb on left, left hand N",
          not hand_thumb_on_right("N11111", "L"))
    check("thumb on left, right hand P",
          not hand_thumb_on_right("P11111", "R"))
    check("thumb on right, right hand N",
          hand_thumb_on_right("N11111", "R"))
    try:
        parse_hand("P1111")
        ok = False
    except ValueError:
        ok = True
    check("parse_hand rejects short codes", ok)


# ---------------------------------------------------------------------------
# Landmark classifier (synthetic hands)
# ---------------------------------------------------------------------------
PALM_WRIST = (0.50, 0.90)
PALM_MIDDLE = (0.48, 0.59)


def build_hand(open_flags, thumb_right=True, thumb_out=True):
    """Synthetic 21 landmarks in image coordinates (y grows downwards)."""
    points = [(0.5, 0.8)] * 21
    points[0] = PALM_WRIST
    xs = [0.55, 0.48, 0.41, 0.34]  # index..pinky when the thumb is right
    if not thumb_right:
        xs = [1 - value for value in xs][::-1]
    for (mcp, _name), x, is_open in zip(
            ((5, "index"), (9, "middle"), (13, "ring"), (17, "pinky")),
            xs, open_flags):
        points[mcp] = (x, 0.60)
        if is_open:
            points[mcp + 1] = (x, 0.47)
            points[mcp + 2] = (x, 0.40)
            points[mcp + 3] = (x, 0.34)
        else:
            points[mcp + 1] = (x, 0.57)
            points[mcp + 2] = (x, 0.60)
            points[mcp + 3] = (x, 0.63)
    sign = 1.0 if thumb_right else -1.0
    base_x = 0.5 + sign * 0.10
    points[1] = (base_x, 0.74)
    points[2] = (base_x + sign * 0.03, 0.72)
    if thumb_out:
        points[3] = (base_x + sign * 0.07, 0.70)
        points[4] = (base_x + sign * 0.13, 0.68)
    else:
        points[3] = (base_x + sign * 0.01, 0.70)
        points[4] = (base_x - sign * 0.01, 0.69)
    return [SimpleNamespace(x=x, y=y, z=0.0) for x, y in points]


def test_landmark_classifier():
    from gesture_twohands import classify_hand

    cases = [
        ("open right thumbs, L", build_hand((1, 1, 1, 1), True, True), "L",
         ("P", "11111")),
        ("open right thumbs, R", build_hand((1, 1, 1, 1), True, True), "R",
         ("N", "11111")),
        ("open left thumbs, L", build_hand((1, 1, 1, 1), False, True), "L",
         ("N", "11111")),
        ("fist folded thumb, L", build_hand((0, 0, 0, 0), True, False), "L",
         ("P", "00000")),
        ("fist folded thumb, R", build_hand((0, 0, 0, 0), False, False), "R",
         ("P", "00000")),
        ("point, L", build_hand((1, 0, 0, 0), True, False), "L",
         ("P", "01000")),
        ("three, R", build_hand((1, 1, 1, 0), False, False), "R",
         ("P", "01110")),
        ("ring only, L", build_hand((0, 0, 1, 0), False, True), "L",
         ("N", "10010")),
    ]
    for name, hand, side, expected in cases:
        check("landmarks " + name, classify_hand(hand, side) == expected,
              str(expected))
    check("landmarks reject short input",
          classify_hand(build_hand((1, 1, 1, 1))[:10], "L") is None)


def test_start_pose():
    from gesture_twohands import START_CODE, is_start_pose

    check("start pose code", START_CODE == "P11111P11111", START_CODE)
    check("exactly both hands open with P thumbs",
          is_start_pose("P11111P11111"))
    check("N thumbs do not start",
          not is_start_pose("N11111N11111") and
          not is_start_pose("P11111N11111") and
          not is_start_pose("N11111P11111"))
    check("a folded finger does not start",
          not is_start_pose("P11110P11110") and
          not is_start_pose("P11111P01111"))
    check("a fist does not start",
          not is_start_pose("P00000P11111") and
          not is_start_pose("P00000P00000"))
    check("no code does not start", not is_start_pose(None))

    # The ready screen only fills its hold bar for this exact pose.
    game = RhythmGame(seed=13, highscore=HighScoreStore(os.devnull))
    advance(game, 0.5, gesture(start_pose=True))
    check("start pose fills the hold bar", game.hold_progress > 0.6,
          "{:.2f}".format(game.hold_progress))
    advance(game, 0.5, gesture(start_pose=False))
    check("other poses drain the hold bar", game.hold_progress == 0.0)


def test_finger_metrics():
    """Folding is decided by the joint angles (PIP + DIP) of the finger."""
    import numpy as np

    from gesture_twohands import (finger_angles, thumb_bend_towards_palm,
                                  _finger_extended, _thumb_extended)

    def chain(mcp, pip, dip, tip):
        pts = np.zeros((21, 3), dtype=np.float32)
        pts[5], pts[6], pts[7], pts[8] = mcp, pip, dip, tip
        return pts

    straight = chain((0.0, -0.60, 0.0), (0.0, -0.90, 0.0),
                     (0.0, -1.05, 0.0), (0.0, -1.20, 0.0))
    pip_angle, dip_angle = finger_angles(straight, 5, 6, 7, 8)
    check("straight joints are close to 180 degrees",
          abs(pip_angle - 180.0) < 0.1 and abs(dip_angle - 180.0) < 0.1,
          "({:.1f}, {:.1f})".format(pip_angle, dip_angle))
    check("finger with straight joints is extended",
          _finger_extended(straight, 5, 6, 7, 8))

    folded = chain((0.0, -0.60, 0.0), (0.0, -0.90, 0.0),
                   (0.30, -0.90, 0.0), (0.45, -0.85, 0.0))
    check("finger folded at the knuckle is folded",
          not _finger_extended(folded, 5, 6, 7, 8))

    half = chain((0.0, -0.60, 0.0), (0.0, -0.90, 0.0),
                 (0.125, -1.1165, 0.0), (0.25, -1.233, 0.0))
    check("finger bent 150 degrees is folded",
          not _finger_extended(half, 5, 6, 7, 8))

    hook = chain((0.0, -0.60, 0.0), (0.0, -0.90, 0.0),
                 (0.0, -1.10, 0.0), (0.20, -1.05, 0.0))
    check("finger hooked at the DIP is folded",
          not _finger_extended(hook, 5, 6, 7, 8),
          str(finger_angles(hook, 5, 6, 7, 8)))

    # A finger pointing at the camera looks short in 2D; 3D keeps it straight.
    towards_camera = chain((0.0, -0.60, 0.0), (0.0, -0.75, -0.25),
                           (0.0, -0.80, -0.40), (0.0, -0.85, -0.55))
    check("finger pointing at the camera is extended",
          _finger_extended(towards_camera, 5, 6, 7, 8))

    palm_center = np.zeros(3, dtype=np.float32)
    thumb = np.zeros((21, 3), dtype=np.float32)
    thumb[2] = (0.0, -0.50, 0.0)
    thumb[3] = (0.20, -0.60, 0.0)
    thumb[4] = (0.40, -0.70, 0.0)
    check("spread thumb is extended",
          _thumb_extended(thumb, palm_center, 1.0))
    thumb[4] = (0.15, -0.55, 0.0)   # resting on the palm, still straight
    check("thumb resting on the palm is folded",
          not _thumb_extended(thumb, palm_center, 1.0))

    # Hyperextension: the tip bends *away* from the palm.  The unsigned IP
    # angle drops below the fold threshold, but the thumb is still out.
    palm = np.array([-0.30, -0.20, 0.0], dtype=np.float32)
    thumb[2] = (0.0, -0.50, 0.0)
    thumb[3] = (0.20, -0.60, 0.0)
    thumb[4] = (0.25, -0.75, 0.0)
    check("hyperextended thumb is still extended",
          _thumb_extended(thumb, palm, 1.0),
          "bend={:.2f}".format(thumb_bend_towards_palm(thumb, palm)))
    check("hyperextension bends away from the palm",
          thumb_bend_towards_palm(thumb, palm) < 0.0,
          "{:.2f}".format(thumb_bend_towards_palm(thumb, palm)))
    # Flexion towards the palm must still count as folded.
    thumb[4] = (0.35, -0.55, 0.0)
    check("flexed thumb is folded",
          not _thumb_extended(thumb, palm, 1.0),
          "bend={:.2f}".format(thumb_bend_towards_palm(thumb, palm)))


def test_smoothing():
    from gesture_twohands import _smooth_tokens

    history = []
    stable = None
    outputs = []
    for token in ["P11111"] * 2 + ["N00000"] + ["P11111"] * 4:
        stable = _smooth_tokens(history, stable, token)
        outputs.append(stable)
    check("smoothing keeps the majority", outputs[-1] == "P11111",
          str(outputs))
    check("smoothing starts at the first token", outputs[0] == "P11111")


# ---------------------------------------------------------------------------
# Difficulty
# ---------------------------------------------------------------------------
def test_difficulty_curve():
    game = RhythmGame(seed=1, ramp_seconds=90.0,
                      highscore=HighScoreStore(os.devnull))
    difficulty = game.difficulty
    ramp = difficulty.ramp_seconds
    check("difficulty starts at 0", difficulty.at(0.0) == 0.0)
    check("difficulty halfway", abs(difficulty.at(45.0) - 0.5) < 1e-6)
    check("difficulty caps at 1", difficulty.at(500.0) == 1.0)

    def snapshot(seconds):
        difficulty.at(seconds)
        return (difficulty.spawn_interval(), difficulty.base_speed(),
                difficulty.value_weights(),
                difficulty.speed_jitter(), difficulty.interval_jitter())

    start = snapshot(0.0)                 # 0 s
    at_15 = snapshot(ramp * 0.5 / 3.0)    # 15 s
    at_30 = snapshot(ramp * STAGE_1)      # 30 s
    at_45 = snapshot(ramp * 0.5)          # 45 s
    at_60 = snapshot(ramp * STAGE_2)      # 60 s
    at_75 = snapshot(ramp * 0.8333)       # 75 s
    final = snapshot(ramp)                # 90 s

    # 0-30 s: only the value mix changes, interval and speed stay at the top
    # of the range and no red note is introduced.
    check("first stage keeps the interval", at_15[0] == start[0] == at_30[0],
          "{:.2f}".format(at_30[0]))
    check("first stage keeps the fall speed", at_15[1] == start[1] == at_30[1],
          "{:.0f}".format(at_30[1]))
    check("first stage mixes 10 and 15 point notes",
          at_15[2][1] > 0 and at_15[2][2] > 0, str(at_15[2]))
    check("no red notes before 60 s",
          at_15[2][3] == 0 and at_30[2][3] == 0 and at_45[2][3] == 0,
          "{} / {}".format(at_30[2], at_45[2]))
    check("mix at 30 s is 20/45/35/0",
          all(abs(a - b) < 1e-9 for a, b in
              zip(at_30[2], (0.20, 0.45, 0.35, 0.0))), str(at_30[2]))
    check("starts with green notes only", start[2][0] == 1.0)

    # 30-60 s: interval and speed rise together, the mix stays put.
    check("interval rises in the middle stage",
          at_45[0] < at_30[0] and at_45[0] > at_60[0],
          "{:.2f} > {:.2f} > {:.2f}".format(at_30[0], at_45[0], at_60[0]))
    check("speed rises in the middle stage",
          at_45[1] > at_30[1] and at_45[1] < at_60[1],
          "{:.0f} < {:.0f} < {:.0f}".format(at_30[1], at_45[1], at_60[1]))
    check("middle stage keeps the note mix",
          at_45[2] == at_30[2] == at_60[2], str(at_60[2]))
    check("mix at 60 s is still 20/45/35/0",
          all(abs(a - b) < 1e-9 for a, b in
              zip(at_60[2], (0.20, 0.45, 0.35, 0.0))), str(at_60[2]))

    # 60-90 s: red fades in while interval and speed rise to their limits.
    check("red fades in during the last stage",
          at_60[2][3] == 0.0 and at_75[2][3] > 0.0 and final[2][3] > 0.0,
          "{} -> {}".format(at_60[2], at_75[2]))
    check("final interval is 0.65 s", abs(final[0] - 0.65) < 1e-9,
          "{:.2f}".format(final[0]))
    check("final speed is 240 px/s", abs(final[1] - 240.0) < 1e-9,
          "{:.0f}".format(final[1]))
    check("final mix is 15/30/30/25",
          all(abs(a - b) < 1e-9 for a, b in
              zip(final[2], (0.15, 0.30, 0.30, 0.25))), str(final[2]))
    check("weights sum to 1", abs(sum(final[2]) - 1.0) < 1e-9)

    check("speed jitter per stage", start[3] == 20.0 and at_45[3] == 15.0 and
          final[3] == 20.0, "{}/{}/{}".format(start[3], at_45[3], final[3]))
    check("interval jitter per stage",
          start[4] == 0.2 and at_45[4] == 0.15 and final[4] == 0.2,
          "{}/{}/{}".format(start[4], at_45[4], final[4]))
    check("hud level reaches 10", difficulty.at(ramp) and
          difficulty.level == 10)


def test_speed_fluctuation():
    game = RhythmGame(seed=2, highscore=HighScoreStore(os.devnull))
    ramp = game.difficulty.ramp_seconds
    game.difficulty.at(0.0)
    base = game.difficulty.base_speed()
    speeds = [game._roll_speed() for _ in range(400)]
    check("note speeds vary", max(speeds) - min(speeds) > 20.0,
          "{:.0f}..{:.0f}".format(min(speeds), max(speeds)))
    check("note speeds stay within +-20 px/s of the base",
          base - 20.0 - 1e-6 <= min(speeds) and
          max(speeds) <= base + 20.0 + 1e-6,
          "base {:.0f}, {:.0f}..{:.0f}".format(base, min(speeds),
                                               max(speeds)))
    intervals = [game._next_interval() for _ in range(400)]
    check("spawn intervals vary within +-0.2 s",
          abs(min(intervals) - 1.8) < 0.05 and
          abs(max(intervals) - 2.2) < 0.05,
          "{:.2f}..{:.2f}".format(min(intervals), max(intervals)))
    game.difficulty.at(ramp * 0.5)          # 45 s: +-15 px/s, +-0.15 s
    speeds = [game._roll_speed() for _ in range(400)]
    check("middle stage speed jitter is +-15",
          max(speeds) - min(speeds) < 30.0 and
          max(speeds) - game.difficulty.base_speed() < 15.0 + 1e-6,
          "{:.0f}..{:.0f}".format(min(speeds), max(speeds)))


def test_note_generation_distribution():
    game = RhythmGame(seed=3, highscore=HighScoreStore(os.devnull))
    ramp = game.difficulty.ramp_seconds

    game.difficulty.at(0.0)
    easy_values = [game._pick_value() for _ in range(2000)]
    game.difficulty.at(ramp * 0.5)      # 45 s, middle stage
    middle_values = [game._pick_value() for _ in range(3000)]
    game.difficulty.at(ramp * 0.9)      # 81 s, last stage
    late_values = [game._pick_value() for _ in range(3000)]
    game.difficulty.at(ramp)
    hard_values = [game._pick_value() for _ in range(4000)]

    check("only green notes at the start", set(easy_values) == {5},
          str(sorted(set(easy_values))))
    check("blue/yellow appear in the middle stage but no red",
          10 in middle_values and 15 in middle_values and
          20 not in middle_values,
          "{}/{}/{}".format(middle_values.count(10),
                            middle_values.count(15),
                            middle_values.count(20)))
    check("red appears in the last stage", 20 in late_values,
          "red {}".format(late_values.count(20)))
    check("all four values appear at full difficulty",
          set(hard_values) == {5, 10, 15, 20}, str(sorted(set(hard_values))))
    check("20 point share is about 25 %",
          0.20 < hard_values.count(20) / len(hard_values) < 0.30,
          "{:.2f}".format(hard_values.count(20) / len(hard_values)))
    check("middle stage mix is 20/45/35",
          abs(middle_values.count(5) / 3000.0 - 0.20) < 0.04 and
          abs(middle_values.count(10) / 3000.0 - 0.45) < 0.04 and
          abs(middle_values.count(15) / 3000.0 - 0.35) < 0.04,
          str({v: middle_values.count(v) for v in (5, 10, 15)}))
    check("mean value grows", (sum(hard_values) / len(hard_values) >
                               sum(easy_values) / len(easy_values)))


def test_red_milestone():
    game = RhythmGame(seed=14, max_chances=99,
                      highscore=HighScoreStore(os.devnull))
    ramp = game.difficulty.ramp_seconds
    game.start()
    spawned = []
    original = game._spawn_note

    def spawn(value=None):
        note = original(value)
        spawned.append(note)
        return note

    game._spawn_note = spawn

    advance(game, ramp * RED_MILESTONES[0] - 1.0)     # 19 s
    check("no red note before 20 s", not any(
        note.value == 20 for note in spawned),
        str([note.value for note in spawned]))
    advance(game, 2.0)                                 # 21 s
    reds = [note for note in spawned if note.value == 20]
    check("exactly one red note appears at 20 s", len(reds) == 1,
          "{} red(s) at {:.1f} s".format(len(reds), game.elapsed))
    check("the first milestone red note is a valid 20 point code",
          bool(reds) and value_of_code(reds[0].code) == 20,
          reds[0].code if reds else "")
    check("the first milestone fired once", game.red_milestones_fired == 1)

    advance(game, ramp * RED_MILESTONES[1] - game.elapsed)
    check("no extra red note between the milestones",
          sum(1 for note in spawned if note.value == 20) == 1,
          str([note.value for note in spawned]))
    advance(game, 1.0)                                 # 46 s
    check("second red note appears at 45 s",
          sum(1 for note in spawned if note.value == 20) == 2,
          "{} red(s) at {:.1f} s".format(
              sum(1 for note in spawned if note.value == 20), game.elapsed))
    check("both milestones fired", game.red_milestones_fired == 2)

    game.restart()
    check("restart clears the milestones", game.red_milestones_fired == 0)


# ---------------------------------------------------------------------------
# Gameplay
# ---------------------------------------------------------------------------
def test_ready_and_start():
    game = RhythmGame(seed=2, highscore=HighScoreStore(os.devnull))
    check("starts in ready state", game.state == RhythmGame.READY)
    advance(game, 0.3, gesture(start_pose=True))
    check("hold progress grows", 0.4 < game.hold_progress < 0.5,
          "{:.2f}".format(game.hold_progress))
    game.update(0.1, gesture(start_pose=False))
    check("hold decays when hands close", game.hold_progress < 0.45)
    events = []
    for _ in range(120):
        events.extend(game.update(1 / 60.0, gesture(start_pose=True)))
        if game.state == RhythmGame.PLAYING:
            break
    check("start pose starts the game",
          game.state == RhythmGame.PLAYING)
    check("start event emitted",
          any(event["type"] == "start" for event in events))
    check("chances are full", game.chances == 3)


def test_spawn_and_fall():
    game = RhythmGame(seed=4, highscore=HighScoreStore(os.devnull))
    game.start()
    advance(game, 1.0)
    check("a note spawned after one second", len(game.notes) == 1,
          str(len(game.notes)))
    note = game.notes[0]
    check("note starts above the play field",
          note.y <= PLAY_TOP, "{:.0f}".format(note.y))
    check("note stays inside its lane",
          0 <= note.x and note.x + note.w <= game.width,
          "{:.0f}".format(note.x))
    check("note value is a valid score", note.value in (5, 10, 15, 20))
    check("note code is in the catalog", value_of_code(note.code) == note.value)
    y_before = note.y
    advance(game, 0.5)
    check("note falls downwards", note.y > y_before)


def test_hit_scoring():
    game = RhythmGame(seed=5, highscore=HighScoreStore(os.devnull))
    game.start()
    code = random_code(20, game.rng)
    game.notes = [Note(code, 20, 0, 10, 300, 0.0)]
    game.update(1 / 60.0, gesture(code=code))
    check("hit removes the note", not game.notes)
    check("hit adds the note value", game.score == 20, str(game.score))
    check("hit increases combo", game.combo == 1)
    check("hit event emitted", any(event["type"] == "hit"
                                   for event in game.events))
    check("hit popup created", len(game.popups) == 1)

    # A different gesture does nothing.
    game.notes = [Note("P00000P00000", 5, 0, 10, 300, 0.0)]
    score_before = game.score
    game.hit_cooldown = 0.0
    game.update(1 / 60.0, gesture(code="P11111P11111"))
    check("wrong gesture scores nothing", game.score == score_before)
    check("wrong gesture keeps the note", len(game.notes) == 1)

    # The cooldown prevents one gesture from clearing two notes in a frame.
    game.notes = [Note("P00000P00000", 5, 0, 10, 300, 0.0),
                  Note("P00000P00000", 5, 1, 170, 400, 0.0)]
    game.hit_cooldown = 0.3
    game.update(1 / 60.0, gesture(code="P00000P00000"))
    check("cooldown blocks a second instant hit", len(game.notes) == 2)
    game.hit_cooldown = 0.0
    game.update(1 / 60.0, gesture(code="P00000P00000"))
    check("lowest note is cleared first", len(game.notes) == 1 and
          game.notes[0].y == 300, str([note.y for note in game.notes]))


def test_miss_and_game_over():
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "highscore.json")
        store = HighScoreStore(path)
        game = RhythmGame(seed=6, highscore=store)
        game.start()
        game.notes = [Note(random_code(5, game.rng), 5, 0, 10,
                           PLAY_BOTTOM - 1, 500.0)]
        game.update(1 / 60.0, gesture())
        check("miss removes the note", not game.notes)
        check("miss costs one chance", game.chances == 2, str(game.chances))
        check("miss resets combo", game.combo == 0)
        check("miss flash triggered", game.miss_flash > 0)

        game.notes = [Note(random_code(5, game.rng), 5, 0, 10,
                           PLAY_BOTTOM - 1, 500.0)]
        game.update(1 / 60.0, gesture())
        check("second miss", game.chances == 1)
        check("still playing with one chance left",
              game.state == RhythmGame.PLAYING)

        game.notes = [Note(random_code(5, game.rng), 5, 0, 10,
                           PLAY_BOTTOM - 1, 500.0)]
        game.update(1 / 60.0, gesture())
        check("third miss ends the game",
              game.state == RhythmGame.OVER and game.chances == 0)
        check("game over event emitted",
              any(event["type"] == "gameover" for event in game.events))
        check("chances never go negative", game.chances == 0)

        data = json.load(open(path, encoding="utf-8"))
        check("game over persists the best score", "best" in data and
              data["games"] == 1, str(data))

        game.restart()
        check("restart resets the score and returns to the ready screen",
              game.score == 0 and game.chances == 3 and
              game.state == RhythmGame.READY and game.hold_progress == 0.0)
        check("restart keeps the best score", game.best_score ==
              data["best"])


def test_highscore_store():
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "score.json")
        store = HighScoreStore(path)
        check("missing file gives defaults", store.load()["best"] == 0)
        store.save({"best": 42, "last": 12, "games": 3})
        loaded = store.load()
        check("save/load roundtrip", loaded == {"best": 42, "last": 12,
                                                "games": 3}, str(loaded))
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        check("corrupt file falls back to defaults",
              store.load()["best"] == 0)

        game = RhythmGame(seed=7, highscore=store)
        game.start()
        game.score = 30
        game.chances = 1
        game.notes = [Note(random_code(5, game.rng), 5, 0, 10,
                           PLAY_BOTTOM - 1, 500.0)]
        game.update(1 / 60.0, gesture())
        data = store.load()
        check("best score is kept", data["best"] == 30, str(data))
        check("last score recorded", data["last"] == 30)
        check("games counted", data["games"] == 1)


def test_game_over_requires_restart():
    game = RhythmGame(seed=8, highscore=HighScoreStore(os.devnull))
    game.start()
    game.chances = 0
    game._finish()
    advance(game, 0.5, gesture(start_pose=True))
    check("game over does not restart on its own",
          game.state == RhythmGame.OVER)
    game.restart()
    check("restart returns to the ready screen",
          game.state == RhythmGame.READY)
    advance(game, 1.0, gesture(start_pose=True))
    check("the new round needs the start pose",
          game.state == RhythmGame.PLAYING)


def test_restart_requires_hold():
    game = RhythmGame(seed=11, highscore=HighScoreStore(os.devnull))
    game.start()
    game.chances = 0
    game._finish()
    game.restart()
    check("restart resets the hold timer", game.hold_progress == 0.0)
    advance(game, 0.3, gesture(start_pose=True))
    check("holding is required again after restart",
          game.state == RhythmGame.READY)
    check("hold progress accumulates again",
          0.3 < game.hold_progress < 0.5,
          "{:.2f}".format(game.hold_progress))
    advance(game, 0.6, gesture(start_pose=True))
    check("holding hands starts the new round",
          game.state == RhythmGame.PLAYING)
    check("the new round has full chances", game.chances == 3)


def test_matching_notes_and_spawn_spread():
    game = RhythmGame(seed=9, highscore=HighScoreStore(os.devnull))
    game.start()
    game.notes = [Note("P11111P11111", 5, 0, 10, 120, 0.0),
                  Note("P11111P11111", 5, 1, 170, 200, 0.0),
                  Note("P00000P00000", 5, 2, 330, 300, 0.0)]
    check("matching notes", len(game.matching_notes("P11111P11111")) == 2)
    check("no matching notes", not game.matching_notes("N11111N11111"))
    check("empty gesture matches nothing", not game.matching_notes(None))

    # New notes avoid lanes that already have a note near the top.
    game.notes = [Note("P11111P11111", 5, 0, 10, -25, 0.0)]
    lanes = set(game._pick_lane() for _ in range(20))
    check("spawner avoids the busy lane", 0 not in lanes, str(lanes))


def main():
    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    for test in tests:
        print("-" * 66)
        print(test.__name__)
        test()

    failed = [name for name, ok, _ in RESULTS if not ok]
    print("=" * 66)
    print("{} checks, {} failed".format(len(RESULTS), len(failed)))
    if failed:
        print("FAILED:", ", ".join(failed))
        return 1
    print("RESULT: all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

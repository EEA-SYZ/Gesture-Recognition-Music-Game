# -*- coding: utf-8 -*-
"""Gesture encoding and the gesture catalog of the rhythm game.

A gesture is written as 12 characters::

    <left hand><right hand>
    <P|N><thumb><index><middle><ring><pinky>  (repeated per hand)

* ``P`` / ``N`` is the thumb direction.  For the hand on the **left** of the
  screen ``P`` means "thumb points right"; for the hand on the **right** of the
  screen ``P`` means "thumb points left".  In other words ``P`` points towards
  the centre of the screen, ``N`` points outwards.
* The five digits are 1 (extended) / 0 (folded) for thumb, index, middle, ring
  and pinky.

Score categories (see docs/实现报告.md for the full derivation):

======  ==============================================================
value   rule
======  ==============================================================
5       both hands share the same finger pattern, pattern is 11111 or
        00000                                        (4 + 1 = 5)
10      both hands share the same pattern from 01000, 01100, 01110,
        01111 or 00111                                    (5 * 1 = 5)
15      both hands share the same pattern from 10000, 11000 or 11100
                                                   (3 * 4 = 12)
20      the two hands use *different* patterns, both from the 10
        patterns above                           (10 * 9 pairs, thumbs
                                                   per the rule = 174)
======  ==============================================================

An ``N`` hand must have its thumb extended: an outward pointing thumb that is
folded does not read clearly, so the game never asks for it (``N00000`` and
friends are not note gestures), while ``P`` hands may keep the thumb folded.
With that rule the catalog holds 5 + 5 + 12 + 174 = 196 gestures.  Any other
code is a valid *reading* of the hands but not a note gesture: it matches
nothing.
"""

from __future__ import absolute_import

import random

# ---------------------------------------------------------------------------
# Finger patterns (thumb, index, middle, ring, pinky).
# ---------------------------------------------------------------------------

PATTERNS_5 = ("11111", "00000")
PATTERNS_10 = ("01000", "01100", "01110", "01111", "00111")
PATTERNS_15 = ("10000", "11000", "11100")

#: Every per-hand finger pattern that can appear on a note (10 in total).
ALL_PATTERNS = PATTERNS_5 + PATTERNS_10 + PATTERNS_15

THUMBS = ("P", "N")

#: Note colour per score value (RGB).
VALUE_COLORS = {
    5: (72, 219, 130),
    10: (82, 168, 255),
    15: (250, 200, 70),
    20: (255, 88, 102),
}

#: Human readable score names, used by the UI and the reports.
VALUE_NAMES = {5: "green", 10: "blue", 15: "yellow", 20: "red"}


def hand_code(thumb, bits):
    """Combine a thumb token and five finger bits into one 6 character code."""
    thumb = str(thumb).upper()
    bits = str(bits)
    if thumb not in THUMBS:
        raise ValueError("thumb must be 'P' or 'N': {!r}".format(thumb))
    if len(bits) != 5 or any(ch not in "01" for ch in bits):
        raise ValueError("bits must be 5 characters of 0/1: {!r}".format(bits))
    return thumb + bits


def parse_hand(code6):
    """Split a 6 character hand code into ``(thumb, bits)``."""
    code6 = str(code6)
    if len(code6) != 6:
        raise ValueError("hand code must be 6 characters: {!r}".format(code6))
    thumb, bits = code6[0], code6[1:]
    if thumb not in THUMBS:
        raise ValueError("thumb must be 'P' or 'N': {!r}".format(thumb))
    hand_code(thumb, bits)  # validation only
    return thumb, bits


def make_code(left6, right6):
    """Join two 6 character hand codes into the 12 character gesture code."""
    parse_hand(left6)
    parse_hand(right6)
    return left6 + right6


def is_valid_code(code):
    """True when *code* is a syntactically valid 12 character gesture code."""
    if not isinstance(code, str) or len(code) != 12:
        return False
    try:
        parse_hand(code[:6])
        parse_hand(code[6:])
    except ValueError:
        return False
    return True


def score_for_patterns(left_bits, right_bits):
    """Return the score value of a pair of finger patterns (0 = not a note)."""
    if left_bits not in ALL_PATTERNS or right_bits not in ALL_PATTERNS:
        return 0
    if left_bits == right_bits:
        if left_bits in PATTERNS_5:
            return 5
        if left_bits in PATTERNS_10:
            return 10
        if left_bits in PATTERNS_15:
            return 15
        return 0
    return 20


def thumb_options(bits):
    """Return the thumb tokens allowed for a hand with the given finger *bits*.

    The game never asks for an ``N`` hand whose thumb is folded: an outward
    pointing thumb always has to be extended, so codes such as ``N00000`` are
    not note gestures.  ``P`` hands keep both options (the thumb may be folded
    while pointing towards the middle of the screen).
    """
    return THUMBS if bits[0] == "1" else ("P",)


def build_catalog():
    """Build ``{code: value}`` for every playable gesture."""
    table = {}
    for left_bits in ALL_PATTERNS:
        for right_bits in ALL_PATTERNS:
            value = score_for_patterns(left_bits, right_bits)
            if not value:
                continue
            for left_thumb in thumb_options(left_bits):
                for right_thumb in thumb_options(right_bits):
                    table[hand_code(left_thumb, left_bits) +
                          hand_code(right_thumb, right_bits)] = value
    return table


#: ``{12 character code: 5 | 10 | 15 | 20}`` for all note gestures (225).
CATALOG = build_catalog()

#: ``{value: tuple(codes)}`` grouped by score value.
CODES_BY_VALUE = {
    value: tuple(sorted(code for code, val in CATALOG.items() if val == value))
    for value in (5, 10, 15, 20)
}


def value_of_code(code):
    """Score value of a gesture code, or 0 when it is not a note gesture."""
    return CATALOG.get(code, 0)


def random_code(value, rng=None):
    """Pick a random gesture code of the given score *value*."""
    rng = rng or random
    codes = CODES_BY_VALUE[value]
    return codes[rng.randrange(len(codes))]


def format_code(code):
    """Pretty print a gesture code for debug overlays ("P11111 N00000")."""
    if not is_valid_code(code):
        return str(code)
    return code[:6] + " " + code[6:]


def hand_thumb_on_right(code6, side):
    """Where the thumb of *code6* has to be drawn on screen.

    ``side`` is ``"L"`` for the hand drawn on the left half of the screen and
    ``"R"`` for the right half.  ``P`` points towards the screen centre, so for
    the left hand ``P`` puts the thumb on its right side and for the right hand
    on its left side.
    """
    thumb, _ = parse_hand(code6)
    pointing_right = (thumb == "P") if side == "L" else (thumb == "N")
    return pointing_right


def describe(code):
    """Human readable description, mainly used by tests and debug output."""
    if not is_valid_code(code):
        return "invalid"
    left_thumb, left_bits = parse_hand(code[:6])
    right_thumb, right_bits = parse_hand(code[6:])
    return "left {}{}, right {}{} ({} points)".format(
        left_thumb, left_bits, right_thumb, right_bits, value_of_code(code))

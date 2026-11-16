# -*- coding: utf-8 -*-
"""Procedural hand / gesture pictures drawn with pygame.

No image assets are needed: every 6 character hand code is turned into a small
hand pictogram (palm + five fingers).  Extended fingers are drawn long, folded
fingers short, and the thumb is drawn on the side that matches its ``P`` / ``N``
direction, so the picture fully shows the gesture of a falling note.

Surfaces are cached per ``(code, side, colour, size)`` because the same
gestures are drawn again and again while notes fall.
"""

from __future__ import absolute_import

import pygame

from gesture_catalog import (VALUE_COLORS, hand_thumb_on_right, parse_hand,
                             value_of_code)

#: Canonical drawing size; other sizes are smooth-scaled from it.
CANVAS = (64, 88)

_HAND_CACHE = {}
_CARD_CACHE = {}

#: Card colours.
CARD_BG = (17, 21, 33)
CARD_BG_LIGHT = (30, 36, 54)
TEXT_LIGHT = (238, 242, 250)
TEXT_DIM = (150, 158, 176)


def _scale_points(points, size):
    sx = size[0] / float(CANVAS[0])
    sy = size[1] / float(CANVAS[1])
    return [(int(round(x * sx)), int(round(y * sy))) for x, y in points]


def _draw_hand(surface, code6, side, color, size):
    _thumb, bits = parse_hand(code6)
    thumb_right = hand_thumb_on_right(code6, side)
    sx = size[0] / float(CANVAS[0])
    sy = size[1] / float(CANVAS[1])

    def rect(x, y, w, h, radius=3):
        pygame.draw.rect(
            surface, color,
            pygame.Rect(int(x * sx), int(y * sy),
                        max(2, int(w * sx)), max(2, int(h * sy))),
            border_radius=max(1, int(radius * min(sx, sy))))

    # Palm and wrist.
    rect(16, 42, 32, 36, 9)
    rect(24, 74, 16, 12, 4)

    # Four long fingers: index next to the thumb, pinky on the far side.
    finger_bits = bits[1:]
    xs = (17, 25, 33, 41)  # left -> right when the thumb is on the left
    order = list(xs) if not thumb_right else list(reversed(xs))
    for x, extended in zip(order, finger_bits):
        if extended == "1":
            rect(x, 6, 7, 38, 3)
        else:
            rect(x, 34, 7, 12, 3)

    # Thumb: a diagonal bar on the proper side of the palm.
    tip_x = 60 if thumb_right else 4
    base_x = 46 if thumb_right else 18
    if bits[0] == "1":
        start = (base_x, 60)
        end = (tip_x, 40)
    else:
        start = (base_x, 64)
        end = ((base_x + tip_x) / 2.0, 55)
    start = _scale_points([start], size)[0]
    end = _scale_points([end], size)[0]
    width = max(3, int(9 * min(sx, sy)))
    pygame.draw.line(surface, color, start, end, width)
    pygame.draw.circle(surface, color, start, width // 2)
    pygame.draw.circle(surface, color, end, width // 2)


def hand_surface(code6, side, color, size=CANVAS):
    """Return a (cached) transparent surface with one hand pictogram."""
    key = (code6, side, tuple(color), tuple(size))
    cached = _HAND_CACHE.get(key)
    if cached is not None:
        return cached

    surface = pygame.Surface(CANVAS, pygame.SRCALPHA)
    _draw_hand(surface, code6, side, color, CANVAS)
    if tuple(size) != CANVAS:
        surface = pygame.transform.smoothscale(surface, size)
    _HAND_CACHE[key] = surface
    return surface


def clear_cache():
    _HAND_CACHE.clear()
    _CARD_CACHE.clear()


def hands_size(hand_size, gap=6):
    """Size of the two hand pictograms plus the gap between them."""
    return (hand_size[0] * 2 + gap, hand_size[1])


def draw_hands(surface, code, color, topleft, hand_size=(54, 76), gap=6):
    """Blit both hands of *code* (12 chars) at *topleft*."""
    left = hand_surface(code[:6], "L", color, hand_size)
    right = hand_surface(code[6:], "R", color, hand_size)
    surface.blit(left, topleft)
    surface.blit(right, (topleft[0] + hand_size[0] + gap, topleft[1]))
    return pygame.Rect(topleft, hands_size(hand_size, gap))


def draw_note_card(surface, code, value, rect, score_font, alpha=255):
    """Blit one falling gesture note card (cached, optional fade-in)."""
    card = pygame.Rect(rect)
    cached = note_surface(code, value, card.size, score_font)
    if alpha < 255:
        cached.set_alpha(max(0, min(255, int(alpha))))
    else:
        cached.set_alpha(255)
    surface.blit(cached, card.topleft)
    return card


def note_surface(code, value, size, score_font):
    """Cached card surface for ``(code, value, size, font)``."""
    key = (code, value, tuple(size), score_font.get_height())
    cached = _CARD_CACHE.get(key)
    if cached is not None:
        return cached
    if len(_CARD_CACHE) > 160:
        _CARD_CACHE.clear()
    surface = pygame.Surface(size, pygame.SRCALPHA)
    _draw_note_card(surface, code, value, pygame.Rect((0, 0), size),
                    score_font)
    _CARD_CACHE[key] = surface
    return surface


def _draw_note_card(surface, code, value, card, score_font):
    color = VALUE_COLORS[value]
    pygame.draw.rect(surface, CARD_BG, card, border_radius=14)
    pygame.draw.rect(surface, color, card, width=3, border_radius=14)
    pygame.draw.rect(surface, CARD_BG_LIGHT, card.inflate(-8, -8),
                     width=1, border_radius=10)

    hand_size = (60, 86)
    total_w = hands_size(hand_size)[0]
    left = card.x + (card.w - total_w) // 2
    draw_hands(surface, code, color, (left, card.y + 8), hand_size)

    label = score_font.render("{} 分".format(value), True, color)
    surface.blit(label, label.get_rect(
        center=(card.centerx, card.bottom - 20)))


def draw_current_gesture(surface, code, rect, label_font, hint_font,
                         hint="", matches=0):
    """Bottom panel: the live gesture picture plus its code."""
    panel = pygame.Rect(rect)
    pygame.draw.rect(surface, CARD_BG, panel, border_radius=10)
    pygame.draw.rect(surface, CARD_BG_LIGHT, panel, width=1, border_radius=10)

    if not code:
        text = hint_font.render(hint or "把双手放进摄像头画面", True, TEXT_DIM)
        surface.blit(text, text.get_rect(center=(panel.centerx,
                                                 panel.centery - 10)))
        return

    value = value_of_code(code)
    color = VALUE_COLORS.get(value, TEXT_LIGHT)
    hand_size = (44, 62)
    left = panel.x + 12
    draw_hands(surface, code, color, (left, panel.y + 8), hand_size)

    text_x = left + hands_size(hand_size)[0] + 16
    code_text = label_font.render(code[:6] + " " + code[6:], True, TEXT_LIGHT)
    surface.blit(code_text, (text_x, panel.y + 10))
    if value:
        note = "可消除 {} 分音符".format(value)
        if matches:
            note += "（画面中 {} 个）".format(matches)
    else:
        note = "该手势不是音符"
    info = hint_font.render(note, True, color)
    surface.blit(info, (text_x, panel.y + 45))

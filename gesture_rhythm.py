# -*- coding: utf-8 -*-
"""手势音游 / Gesture Rhythm — pygame window + camera window.

Run with ``run_game.bat`` (elevated, camera) or::

    .venv\\Scripts\\python.exe gesture_rhythm.py

Two windows open: the OpenCV preview of the mirrored camera with both hand
skeletons, and the pygame game window with falling gesture notes.

Controls
--------
* hold P11111 P11111 for 0.7 s: start the round
* make the gesture drawn on a falling note: clear it and score
* a note that reaches the bottom costs one of the three chances
* click 重新开始 (or press space) on the game over screen: back to the ready
  screen, where the round starts by holding P11111 P11111 again
* ESC quits
"""

from __future__ import absolute_import

import math
import os
import sys

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame
from pygame.locals import (KEYDOWN, K_ESCAPE, K_RETURN, K_SPACE,
                           MOUSEBUTTONDOWN, QUIT)

import cv2
import numpy as np

import gesture_icons
from camera_compat import open_camera
from game_core import (HUD_HEIGHT, PLAY_BOTTOM, PLAY_TOP, POPUP_TTL,
                       RhythmGame, SCREEN_HEIGHT, SCREEN_WIDTH)
from gesture_catalog import VALUE_COLORS
from gesture_icons import (TEXT_DIM, TEXT_LIGHT, draw_current_gesture,
                           draw_hands, draw_note_card)
from gesture_twohands import HAND_COLORS, CameraWorker, TwoHandRecognizer
from sound_effects import SoundBank

FONT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "platech.ttf")
CAMERA_WINDOW = "Camera - Two Hands"

#: The scene is laid out for 480x800 and shown in a smaller window.
WINDOW_SCALE = 0.875
WINDOW_SIZE = (int(SCREEN_WIDTH * WINDOW_SCALE),
               int(SCREEN_HEIGHT * WINDOW_SCALE))

#: Restart button on the game over screen.
RESTART_BUTTON = pygame.Rect(130, 486, 220, 58)

ACCENT = (110, 200, 255)
ACCENT_DIM = (70, 120, 170)
BG_PANEL = (16, 21, 34)
GOLD = (255, 205, 90)
WARN = (255, 170, 90)

_OPEN_HANDS = "P11111P11111"


# ---------------------------------------------------------------------------
# Small drawing helpers
# ---------------------------------------------------------------------------
def load_fonts():
    return {
        "title": pygame.font.Font(FONT_FILE, 70),
        "subtitle": pygame.font.Font(FONT_FILE, 20),
        "huge": pygame.font.Font(FONT_FILE, 56),
        "big": pygame.font.Font(FONT_FILE, 42),
        "medium": pygame.font.Font(FONT_FILE, 28),
        "small": pygame.font.Font(FONT_FILE, 22),
        "tiny": pygame.font.Font(FONT_FILE, 18),
        "score": pygame.font.Font(FONT_FILE, 34),
        "card": pygame.font.Font(FONT_FILE, 26),
        "popup": pygame.font.Font(FONT_FILE, 26),
    }


def make_background(size):
    """Vertical gradient with a few soft glows, built once."""
    surface = pygame.Surface(size)
    top, bottom = (9, 12, 22), (22, 30, 52)
    for y in range(size[1]):
        ratio = y / float(size[1])
        color = tuple(int(top[i] + (bottom[i] - top[i]) * ratio)
                      for i in range(3))
        pygame.draw.line(surface, color, (0, y), (size[0], y))
    glow = pygame.Surface(size, pygame.SRCALPHA)
    for cx, cy, radius, alpha in ((70, 190, 150, 20), (420, 560, 190, 16),
                                  (240, 800, 230, 12)):
        pygame.draw.circle(glow, (90, 150, 255, alpha), (cx, cy), radius)
    surface.blit(glow, (0, 0))
    return surface


def heart_points(center, size):
    """Parametric heart outline polygon."""
    cx, cy = center
    points = []
    for step in range(36):
        t = step / 36.0 * 2.0 * math.pi
        x = 16.0 * math.sin(t) ** 3
        y = (13.0 * math.cos(t) - 5.0 * math.cos(2 * t) -
             2.0 * math.cos(3 * t) - math.cos(4 * t))
        points.append((cx + x * size / 32.0, cy - y * size / 32.0))
    return points


def draw_heart(surface, center, size, color, filled=True):
    points = heart_points(center, size)
    if filled:
        pygame.draw.polygon(surface, color, points)
    else:
        pygame.draw.polygon(surface, color, points, 2)


def draw_progress_bar(surface, rect, progress, color, back=(40, 48, 66)):
    bar = pygame.Rect(rect)
    pygame.draw.rect(surface, back, bar, border_radius=bar.h // 2)
    width = int(bar.w * max(0.0, min(1.0, progress)))
    if width > 2:
        fill = pygame.Rect(bar.x, bar.y, width, bar.h)
        pygame.draw.rect(surface, color, fill, border_radius=bar.h // 2)
    pygame.draw.rect(surface, (70, 82, 108), bar, 1,
                     border_radius=bar.h // 2)


def draw_text(surface, font, text, color, center=None, topleft=None,
              topright=None):
    rendered = font.render(text, True, color)
    rect = rendered.get_rect()
    if center is not None:
        rect.center = center
    elif topleft is not None:
        rect.topleft = topleft
    elif topright is not None:
        rect.topright = topright
    surface.blit(rendered, rect)
    return rect


def draw_text_alpha(surface, font, text, color, center, alpha):
    rendered = font.render(text, True, color)
    rendered.set_alpha(int(max(0, min(255, alpha))))
    surface.blit(rendered, rendered.get_rect(center=center))


# ---------------------------------------------------------------------------
# Scene
# ---------------------------------------------------------------------------
class RhythmScene(object):
    """Draws the READY / PLAYING / GAME OVER screens."""

    def __init__(self, size=(SCREEN_WIDTH, SCREEN_HEIGHT)):
        self.size = size
        self.fonts = load_fonts()
        self.background = make_background(size)
        self.play_field = pygame.Rect(0, PLAY_TOP, size[0],
                                      PLAY_BOTTOM - PLAY_TOP)
        self.bottom_panel = pygame.Rect(12, SCREEN_HEIGHT - 92,
                                        size[0] - 24, 80)
        #: Mouse position in scene coordinates (set by the main loop).
        self.mouse_pos = (0, 0)

    # -- entry point ----------------------------------------------------
    def draw(self, screen, game, gesture=None, warning=None):
        screen.blit(self.background, (0, 0))
        code = getattr(gesture, "code", None) if gesture is not None else None

        if game.state == RhythmGame.READY:
            self._draw_ready(screen, game, warning)
        else:
            self._draw_playfield(screen, game)
            self._draw_hud(screen, game)
            if game.state == RhythmGame.OVER:
                self._draw_game_over(screen, game)
                return

        draw_current_gesture(
            screen, code, self.bottom_panel, self.fonts["small"],
            self.fonts["tiny"],
            hint="把双手放进摄像头画面",
            matches=len(game.matching_notes(code)))

    # -- READY ----------------------------------------------------------
    def _draw_ready(self, screen, game, warning):
        fonts = self.fonts
        draw_text(screen, fonts["title"], "手势音游", TEXT_LIGHT,
                  center=(self.size[0] // 2, 118))
        draw_text(screen, fonts["subtitle"], "GESTURE  RHYTHM", ACCENT_DIM,
                  center=(self.size[0] // 2, 172))

        hand_size = (82, 112)
        total = gesture_icons.hands_size(hand_size, 14)[0]
        draw_hands(screen, _OPEN_HANDS, ACCENT,
                   ((self.size[0] - total) // 2, 206), hand_size, 14)

        draw_text(screen, fonts["medium"], "双手张开，保持 0.7 秒开始",
                  TEXT_LIGHT, center=(self.size[0] // 2, 340))
        draw_text(screen, fonts["tiny"], "开始姿势：P11111  P11111",
                  ACCENT_DIM, center=(self.size[0] // 2, 370))
        draw_progress_bar(screen, pygame.Rect(110, 394, 260, 16),
                          game.hold_progress, ACCENT)
        draw_text(screen, fonts["small"],
                  "历史最高  {}".format(game.best_score), TEXT_DIM,
                  center=(self.size[0] // 2, 440))

        for index, line in enumerate((
                "屏幕上的手势音符 = 双手要做的动作",
                "做出音符的手势即可消除并得分",
                "音符落到屏幕外会扣除一次机会（共 3 次）")):
            draw_text(screen, fonts["tiny"], line, TEXT_DIM,
                      center=(self.size[0] // 2, 560 + index * 30))

        if warning:
            draw_text(screen, fonts["tiny"], warning, WARN,
                      center=(self.size[0] // 2, 650))
        draw_text(screen, fonts["tiny"], "ESC 退出", TEXT_DIM,
                  center=(self.size[0] // 2, 682))

    # -- PLAYING --------------------------------------------------------
    def _draw_playfield(self, screen, game):
        # Lane backdrops and the judgement line.
        lane_height = PLAY_BOTTOM - PLAY_TOP - 8
        for lane in range(game.lanes):
            lane_rect = pygame.Rect(
                int(lane * game.lane_width) + 5, PLAY_TOP + 4,
                int(game.lane_width) - 10, lane_height)
            pygame.draw.rect(screen, (15, 20, 34), lane_rect,
                             border_radius=12)
            pygame.draw.rect(screen, (26, 34, 52), lane_rect, 1,
                             border_radius=12)
        pygame.draw.line(screen, (58, 70, 100), (0, PLAY_BOTTOM - 6),
                         (self.size[0], PLAY_BOTTOM - 6), 2)
        glow = pygame.Surface((self.size[0], 34), pygame.SRCALPHA)
        for index in range(34):
            alpha = int(26 * (1.0 - index / 34.0))
            pygame.draw.line(glow, (110, 200, 255, alpha), (0, index),
                             (self.size[0], index))
        screen.blit(glow, (0, PLAY_BOTTOM - 40))

        screen.set_clip(self.play_field)
        for note in game.notes:
            hidden = PLAY_TOP - note.y
            alpha = 255
            if hidden > 0:
                alpha = int(255 * max(0.0, min(
                    1.0, 1.0 - hidden / (note.h * 0.6))))
            draw_note_card(screen, note.code, note.value,
                           pygame.Rect(note.x, note.y, note.w, note.h),
                           self.fonts["card"], alpha)
        screen.set_clip(None)

        # Hit / miss feedback.
        if game.hit_flash > 0:
            color = VALUE_COLORS.get(game.last_hit_value, ACCENT)
            self._draw_border(screen, color, game.hit_flash / 0.35)
        if game.miss_flash > 0:
            self._draw_tint(screen, (255, 40, 60),
                            90 * game.miss_flash / 0.5)

        for popup in game.popups:
            progress = popup["age"] / POPUP_TTL
            alpha = 255 * (1.0 - progress)
            center = (popup["x"], popup["y"] - 34 * progress)
            draw_text_alpha(screen, self.fonts["popup"],
                            "+{}".format(popup["value"]),
                            VALUE_COLORS.get(popup["value"], TEXT_LIGHT),
                            center, alpha)

    def _draw_hud(self, screen, game):
        fonts = self.fonts
        pygame.draw.rect(screen, BG_PANEL,
                         pygame.Rect(0, 0, self.size[0], HUD_HEIGHT))
        pygame.draw.line(screen, (34, 44, 66), (0, HUD_HEIGHT - 1),
                         (self.size[0], HUD_HEIGHT - 1), 2)

        draw_text(screen, fonts["tiny"], "得分", TEXT_DIM, topleft=(18, 12))
        draw_text(screen, fonts["score"], str(game.score), TEXT_LIGHT,
                  topleft=(18, 34))
        draw_text(screen, fonts["tiny"], "最高 {}".format(game.best_score),
                  TEXT_DIM, topleft=(18, 76))

        # Hearts (chances).
        for index in range(game.max_chances):
            center = (self.size[0] - 30 - index * 30, 26)
            filled = index < game.chances
            draw_heart(screen, center, 24,
                       (255, 92, 110) if filled else (70, 78, 98), filled)

        draw_text(screen, fonts["tiny"], "Lv.{}".format(game.difficulty.level),
                  TEXT_DIM, topright=(self.size[0] - 18, 44))
        draw_progress_bar(
            screen, pygame.Rect(self.size[0] - 128, 66, 110, 10),
            game.difficulty_value, (255, 190, 90))

        if game.combo >= 2:
            draw_text(screen, fonts["medium"],
                      "连击 x{}".format(game.combo), ACCENT,
                      center=(self.size[0] // 2, 74))

    # -- GAME OVER ------------------------------------------------------
    def _draw_game_over(self, screen, game):
        fonts = self.fonts
        self._draw_tint(screen, (4, 6, 12), 190)
        panel = pygame.Rect(46, 206, self.size[0] - 92, 388)
        pygame.draw.rect(screen, BG_PANEL, panel, border_radius=18)
        pygame.draw.rect(screen, (52, 64, 92), panel, 2, border_radius=18)

        draw_text(screen, fonts["big"], "游戏结束", TEXT_LIGHT,
                  center=(self.size[0] // 2, panel.y + 58))
        draw_text(screen, fonts["tiny"], "本局得分", TEXT_DIM,
                  center=(self.size[0] // 2, panel.y + 104))
        draw_text(screen, fonts["huge"], str(game.score), TEXT_LIGHT,
                  center=(self.size[0] // 2, panel.y + 146))
        draw_text(screen, fonts["small"],
                  "历史最高  {}".format(game.best_score), TEXT_DIM,
                  center=(self.size[0] // 2, panel.y + 200))
        if game.new_record:
            draw_text(screen, fonts["small"], "新纪录！", GOLD,
                      center=(self.size[0] // 2, panel.y + 234))
        else:
            draw_text(screen, fonts["tiny"],
                      "命中 {}    最高连击 x{}    漏掉 {}".format(
                          game.hits, game.best_combo, game.misses),
                      TEXT_DIM, center=(self.size[0] // 2, panel.y + 234))

        hovered = self.mouse_pos
        color = (90, 200, 140) if RESTART_BUTTON.collidepoint(hovered) \
            else (70, 165, 118)
        pygame.draw.rect(screen, color, RESTART_BUTTON, border_radius=14)
        draw_text(screen, fonts["medium"], "重新开始", (12, 24, 18),
                  center=RESTART_BUTTON.center)
        draw_text(screen, fonts["tiny"], "点击按钮或按空格键，再双手张开开始",
                  TEXT_DIM, center=(self.size[0] // 2, panel.bottom - 22))

    # -- effects --------------------------------------------------------
    def _draw_tint(self, screen, color, alpha):
        overlay = pygame.Surface(self.size, pygame.SRCALPHA)
        overlay.fill((color[0], color[1], color[2], int(alpha)))
        screen.blit(overlay, (0, 0))

    def _draw_border(self, screen, color, strength):
        alpha = int(max(0, min(255, 150 * strength)))
        overlay = pygame.Surface(self.size, pygame.SRCALPHA)
        pygame.draw.rect(overlay, (color[0], color[1], color[2], alpha),
                         self.play_field.inflate(-6, -6), 8,
                         border_radius=10)
        screen.blit(overlay, (0, 0))


# ---------------------------------------------------------------------------
# Camera preview overlay (ASCII only: OpenCV cannot render CJK here)
# ---------------------------------------------------------------------------
def annotate_camera(image, game, gesture):
    """Draw the game status and the per-hand recognition result on the preview.

    The left and right hand are listed explicitly (code + thumb state), because
    the wrist labels alone are easy to miss while playing.
    """
    frame = image.copy()
    height, width = frame.shape[:2]
    scale = max(0.75, min(1.6, width / 640.0))
    font = cv2.FONT_HERSHEY_SIMPLEX
    hands = getattr(gesture, "hands", []) or []
    by_side = {hand.side: hand for hand in hands}

    states = {
        RhythmGame.READY: "START: hold P11111 P11111",
        RhythmGame.PLAYING: "PLAYING: match the note gestures",
        RhythmGame.OVER: "GAME OVER - restart on the game window",
    }

    # Top strip: round statistics.
    strip = int(38 * scale)
    cv2.rectangle(frame, (0, 0), (width, strip), (18, 20, 28), -1)
    cv2.putText(frame, "SCORE {}    BEST {}    CHANCES {}".format(
        game.score, game.best_score, max(0, game.chances)),
        (int(10 * scale), int(26 * scale)), font, 0.6 * scale,
        (235, 240, 250), 1, cv2.LINE_AA)

    # Recognition panel: explicit LEFT / RIGHT results.
    x1, y1 = int(10 * scale), strip + int(8 * scale)
    x2, y2 = x1 + int(320 * scale), y1 + int(104 * scale)
    roi = frame[y1:y2, x1:x2]
    if roi.size:
        dark = np.zeros_like(roi)
        dark[:] = (16, 18, 26)
        cv2.addWeighted(dark, 0.66, roi, 0.34, 0, roi)
    cv2.rectangle(frame, (x1, y1), (x2, y2), (72, 84, 108), 1)
    cv2.putText(frame, "RECOGNITION   {}/2 hands".format(len(hands)),
                (x1 + int(8 * scale), y1 + int(20 * scale)), font,
                0.46 * scale, (168, 176, 194), 1, cv2.LINE_AA)
    for index, side in enumerate(("L", "R")):
        hand = by_side.get(side)
        name = "LEFT " if side == "L" else "RIGHT"
        row_y = y1 + int((48 + index * 27) * scale)
        if hand is not None:
            text = "{}  {}   thumb {}".format(
                name, hand.code,
                "EXT" if hand.bits[0] == "1" else "FOLD")
            color = HAND_COLORS[side]
        else:
            text = "{}  --   not detected".format(name)
            color = (150, 156, 172)
        cv2.putText(frame, text, (x1 + int(8 * scale), row_y), font,
                    0.58 * scale, color, 1, cv2.LINE_AA)

    code = getattr(gesture, "code", None)
    cv2.putText(frame, "code " + (code or "--"),
                (x1 + int(8 * scale), y1 + int(98 * scale)), font,
                0.48 * scale, (205, 212, 226), 1, cv2.LINE_AA)

    # Bottom strip: state hint and the "hold both hands" progress.
    cv2.rectangle(frame, (0, height - int(38 * scale)), (width, height),
                  (18, 20, 28), -1)
    cv2.putText(frame, states[game.state],
                (int(10 * scale), height - int(14 * scale)), font,
                0.55 * scale, (150, 210, 255), 1, cv2.LINE_AA)
    if game.state == RhythmGame.READY:
        bar_w = int(190 * scale)
        bar_h = int(12 * scale)
        bar_x = width - bar_w - int(16 * scale)
        bar_y = height - int(30 * scale)
        cv2.rectangle(frame, (bar_x, bar_y),
                      (bar_x + bar_w, bar_y + bar_h), (60, 60, 60), -1)
        cv2.rectangle(frame, (bar_x, bar_y),
                      (bar_x + int(bar_w * game.hold_progress),
                       bar_y + bar_h), (0, 220, 120), -1)
    return frame


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def run(source, scene=None, sound=None, hook=None, fps=60,
        warning=None, window_title="手势音游 / Gesture Rhythm",
        show_camera=True, camera_window=CAMERA_WINDOW, game=None):
    """Run the game loop until the user quits.

    Args:
        source: object with ``latest() -> (image, gesture)``.  The real game
            passes a :class:`gesture_twohands.CameraWorker`; tests and the
            screenshot capture pass a scripted source with ``image = None``.
        hook: optional ``hook(frame_index, game, source)`` called after every
            rendered frame; return ``False`` to stop (used by capture_screens).
        game: optional pre-built :class:`game_core.RhythmGame` (tests inject a
            temporary high score file).
    """
    window = pygame.display.set_mode(WINDOW_SIZE)
    pygame.display.set_caption(window_title)
    canvas = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    scaled = pygame.Surface(WINDOW_SIZE)
    scene = scene or RhythmScene()
    sound = sound if sound is not None else SoundBank()
    game = game or RhythmGame()
    clock = pygame.time.Clock()

    def to_scene(pos):
        """Window pixel -> scene pixel (the canvas is scaled down on show)."""
        return (pos[0] * SCREEN_WIDTH / float(WINDOW_SIZE[0]),
                pos[1] * SCREEN_HEIGHT / float(WINDOW_SIZE[1]))

    camera_visible = show_camera and camera_window is not None
    running = True
    frame_index = 0
    try:
        while running:
            dt = min(clock.tick(fps) / 1000.0, 0.05)
            for event in pygame.event.get():
                if event.type == QUIT:
                    running = False
                elif event.type == KEYDOWN:
                    if event.key == K_ESCAPE:
                        running = False
                    elif event.key in (K_SPACE, K_RETURN):
                        _handle_restart(game)
                elif event.type == MOUSEBUTTONDOWN and event.button == 1:
                    if (game.state == RhythmGame.OVER and
                            RESTART_BUTTON.collidepoint(to_scene(event.pos))):
                        _handle_restart(game)

            image, gesture = source.latest()
            game.update(dt, gesture)
            if sound is not None:
                for game_event in game.events:
                    sound.play(game_event)

            scene.mouse_pos = to_scene(pygame.mouse.get_pos())
            scene.draw(canvas, game, gesture, warning)
            pygame.transform.smoothscale(canvas, WINDOW_SIZE, scaled)
            window.blit(scaled, (0, 0))
            pygame.display.update()

            if image is not None and camera_visible:
                try:
                    cv2.imshow(camera_window, annotate_camera(image, game,
                                                              gesture))
                    cv2.waitKey(1)
                except Exception:
                    # The preview window was closed or the GUI is unavailable;
                    # the game itself keeps running.
                    camera_visible = False

            frame_index += 1
            if hook is not None and hook(frame_index, game, source) is False:
                running = False
    finally:
        pygame.display.quit()
        if camera_visible:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass
    return game


def _handle_restart(game):
    """The restart button only returns to the ready screen.

    Starting to play always requires holding P11111 P11111, every round.
    """
    if game.state == RhythmGame.OVER:
        game.restart()


def main(argv=None):
    """Open the camera, start the recogniser thread and run the game."""
    pygame.init()

    camera = None
    recognizer = None
    worker = None
    warning = None
    try:
        camera = open_camera()
        if not getattr(camera, "is_real", True):
            if getattr(camera, "reason", "") == "forced":
                warning = "摄像头已禁用（GAME_CAMERA=virtual）：需双手张开才能开始"
            else:
                warning = "摄像头不可用：需双手张开才能开始，请检查摄像头"
        recognizer = TwoHandRecognizer()
        worker = CameraWorker(camera, recognizer).start()
        return run(worker, warning=warning)
    finally:
        if worker is not None:
            worker.close()
        elif camera is not None:
            try:
                camera.release()
            except Exception:
                pass
        if recognizer is not None:
            recognizer.close()
        pygame.quit()


if __name__ == "__main__":
    main(sys.argv[1:])

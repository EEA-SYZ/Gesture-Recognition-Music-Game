# -*- coding: utf-8 -*-
"""Headless screenshot capture / smoke test of the gesture rhythm game.

Runs the real pygame game loop with the dummy SDL video driver and a scripted
"hands" source (no camera needed).  The scripted source plays the game by
adopting the gesture of the lowest note, so the hit / miss / game over paths
are all exercised.  Screenshots are written to ``docs/``.

Usage::

    .venv\\Scripts\\python.exe capture_screens.py
"""

from __future__ import absolute_import

import os
import sys
import tempfile
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("GAME_NO_SOUND", "1")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

#: Documentation images live next to the implementation report.
DOCS_DIR = os.path.join(ROOT, "docs")

import pygame  # noqa: E402

from game_core import HighScoreStore, Note, RhythmGame  # noqa: E402
from gesture_catalog import CODES_BY_VALUE  # noqa: E402
from gesture_rhythm import RhythmScene, run  # noqa: E402

#: A valid pose used for the "current gesture" panel when not hitting.
DISPLAY_CODE = "P00000P00000"

#: One note of every value, staged for the "high difficulty" screenshot so the
#: documentation always shows all four colours.
SHOWCASE = ((0, 120, 5), (1, 240, 10), (2, 360, 15), (0, 500, 20))

STATE = {
    "shots": [],
    "hit_pause": 0,
    "fail_mode": False,
    "over_frames": 0,
    "game_shot": False,
    "difficulty_forced": False,
    "freeze_at": None,
    "hard_at": None,
    "showcase_at": None,
    "fail_at": None,
}


class ScriptedSource(object):
    """Stands in for the camera worker: returns a fixed gesture state."""

    def __init__(self):
        self.code = None
        self.both_open = False

    def set(self, code=None, both_open=False):
        self.code = code
        self.both_open = both_open

    def latest(self):
        gesture = SimpleNamespace(code=self.code, both_open=self.both_open,
                                  hand_count=2 if self.code else 0)
        return None, gesture


def stage_showcase(game):
    """Put one note of every value on the field for the documentation shot."""
    notes = []
    for lane, y, value in SHOWCASE:
        code = CODES_BY_VALUE[value][0]
        x = (lane * game.lane_width +
             (game.lane_width - game.note_width) / 2.0)
        notes.append(Note(code, value, lane, x, y, 110.0))
    game.notes = notes


def save_shot(name):
    screen = pygame.display.get_surface()
    os.makedirs(DOCS_DIR, exist_ok=True)
    pygame.image.save(screen, os.path.join(DOCS_DIR, name))
    STATE["shots"].append(name)
    print("[capture] saved docs/{}".format(name))


def make_hook(source):
    def hook(frame, game, current_source):
        if frame >= 1500:      # safety stop for the headless run
            return False

        if game.state == RhythmGame.READY:
            source.set(both_open=True)
            if frame == 22:
                save_shot("screenshot_start.png")
            return None

        if game.state == RhythmGame.PLAYING:
            if STATE["fail_mode"]:
                source.set(code=None)
                return None

            # Stop hitting shortly before the "hard" screenshot so that a few
            # notes accumulate in the play field for the picture.  While the
            # field is frozen the chances are refilled: the picture needs notes
            # of every value on screen, not a game over.
            freezing = (STATE["freeze_at"] is not None and
                        frame >= STATE["freeze_at"])
            if freezing:
                game.chances = game.max_chances
            if freezing or STATE["hit_pause"] > 0:
                STATE["hit_pause"] = max(0, STATE["hit_pause"] - 1)
                source.set(code=DISPLAY_CODE)
            else:
                urgent = [note for note in game.notes
                          if note.y + note.h >= 560]
                if urgent:
                    note = max(urgent, key=lambda item: item.y)
                    source.set(code=note.code)
                    if game.hit_flash > 0.33:
                        STATE["hit_pause"] = 8
                else:
                    source.set(code=DISPLAY_CODE)

            # Screenshot as soon as a few notes are falling, so the picture
            # shows the real note density instead of an empty field.  Frames
            # with a miss flash are skipped so the picture stays readable.
            if not STATE["game_shot"]:
                if ((frame >= 380 and len(game.notes) >= 3) or
                        frame >= 820):
                    if game.miss_flash <= 0.0:
                        save_shot("screenshot_game.png")
                        STATE["game_shot"] = True
                    elif frame >= 880:
                        save_shot("screenshot_game.png")
                        STATE["game_shot"] = True

            if STATE["game_shot"] and not STATE["difficulty_forced"]:
                # Jump into the speed stage (note mix final, faster fall) and
                # let a mixed set of notes accumulate for the second picture.
                game.elapsed = 80.0
                game.chances = game.max_chances   # keep the run alive
                STATE["difficulty_forced"] = True
                STATE["freeze_at"] = frame + 30
                STATE["hard_at"] = frame + 30

            if STATE["hard_at"] is not None and frame >= STATE["hard_at"]:
                # Stage one note of each value and clear the hit effects, then
                # take the picture once the next frame has been drawn.
                stage_showcase(game)
                game.popups = []
                game.hit_flash = 0.0
                game.miss_flash = 0.0
                STATE["hard_at"] = None
                STATE["showcase_at"] = frame + 2

            if (STATE["showcase_at"] is not None and
                    frame >= STATE["showcase_at"]):
                save_shot("screenshot_hard.png")
                STATE["showcase_at"] = None
                STATE["fail_at"] = frame + 25

            if STATE["fail_at"] is not None and frame >= STATE["fail_at"]:
                STATE["fail_mode"] = True
                game.chances = 1
                game.misses = 0      # the freeze misses are not real play
                source.set(code=None)
            return None

        if game.state == RhythmGame.OVER:
            source.set(code=None)
            STATE["over_frames"] += 1
            if STATE["over_frames"] == 25:
                save_shot("screenshot_over.png")
                return False
        return None

    return hook


def main():
    pygame.init()
    pygame.display.set_mode((480, 800))
    scene = RhythmScene()
    source = ScriptedSource()

    # Keep the capture high score out of the real highscore.json.
    with tempfile.TemporaryDirectory() as folder:
        store = HighScoreStore(os.path.join(folder, "highscore.json"))
        store.save({"best": 240, "last": 0, "games": 4})
        game = RhythmGame(seed=7, highscore=store)
        result = run(source, scene=scene, sound=None, hook=make_hook(source),
                     game=game, show_camera=False, fps=60)

    print("[capture] final state={} score={} best={} hits={} misses={}".format(
        result.state, result.score, result.best_score, result.hits,
        result.misses))
    print("[capture] shots:", ", ".join(STATE["shots"]))
    pygame.quit()
    if result.state != RhythmGame.OVER:
        print("[capture] WARNING: game did not reach the game over screen")
        return 1
    if len(STATE["shots"]) != 4:
        print("[capture] WARNING: expected 4 screenshots")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())


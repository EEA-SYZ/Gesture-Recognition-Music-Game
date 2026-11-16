# -*- coding: utf-8 -*-
"""Environment self-check for the gesture rhythm game.

Run with the project virtual environment::

    .venv\\Scripts\\python.exe verify_environment.py
"""

from __future__ import absolute_import

import os
import platform
import sys
import time
import traceback
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

RESULTS = []


def record(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print("[{}] {}{}".format("PASS" if ok else "FAIL", name,
                             " - " + detail if detail else ""))


def check_runtime():
    print("=" * 70)
    print("Python :", sys.version.replace("\n", " "))
    print("Exe    :", sys.executable)
    print("Bits   :", platform.architecture()[0])
    print("System :", platform.platform())
    record("Python >= 3.9", sys.version_info >= (3, 9),
           "{}.{}".format(*sys.version_info[:2]))
    record("64-bit interpreter", platform.architecture()[0] == "64bit")


def check_packages():
    packages = [
        ("numpy", "numpy"),
        ("cv2", "opencv-python"),
        ("pygame", "pygame"),
        ("mediapipe", "mediapipe"),
        ("gesture_catalog", "gesture_catalog"),
        ("game_core", "game_core"),
        ("gesture_icons", "gesture_icons"),
        ("gesture_twohands", "gesture_twohands"),
        ("sound_effects", "sound_effects"),
        ("gesture_rhythm", "gesture_rhythm"),
    ]
    for module_name, label in packages:
        try:
            module = __import__(module_name)
            version = getattr(module, "__version__", "local")
            record("import {}".format(label), True, str(version))
        except Exception as exc:
            record("import {}".format(label), False, repr(exc))


def check_files():
    required = [
        "gesture_rhythm.py",
        "gesture_twohands.py",
        "gesture_catalog.py",
        "gesture_icons.py",
        "game_core.py",
        "sound_effects.py",
        "platech.ttf",
    ]
    for path in required:
        record("file {}".format(path), os.path.exists(path))


def check_catalog():
    from gesture_catalog import CATALOG, CODES_BY_VALUE, value_of_code

    sizes = {value: len(codes) for value, codes in CODES_BY_VALUE.items()}
    record("gesture catalog 256 gestures", len(CATALOG) == 256,
           str(len(CATALOG)))
    record("score groups 5 / 5 / 16 / 230",
           sizes.get(5) == 5 and sizes.get(10) == 5 and
           sizes.get(15) == 16 and sizes.get(20) == 230, str(sizes))
    record("catalog lookup",
           value_of_code("P11111P11111") == 5 and
           value_of_code("P01110P01110") == 10 and
           value_of_code("P10000P10000") == 15 and
           value_of_code("P11111P00000") == 20 and
           value_of_code("N00000P00000") == 0,
           "P11111P11111=5, P01110P01110=10, P10000P10000=15, "
           "P11111P00000=20, N-folded=0")


def check_gesture():
    from gesture_twohands import TwoHandRecognizer, classify_hand

    started = time.time()
    recognizer = TwoHandRecognizer()
    load_time = time.time() - started
    record("load MediaPipe Hands", True, "{:.2f}s".format(load_time))

    import numpy as np

    blank = np.zeros((450, 600, 3), dtype=np.uint8)
    started = time.time()
    frame = recognizer.process(blank)
    infer_time = time.time() - started
    record("two-hand pipeline (no hands)", frame.code is None and
           frame.hand_count == 0,
           "{:.1f} ms/frame, image {}".format(
               infer_time * 1000, frame.image.shape))
    recognizer.close()

    # Synthetic open right hand on the right half of the screen.
    points = [(0.5, 0.82)] * 21
    points[0] = (0.50, 0.90)
    for mcp, x in ((5, 0.44), (9, 0.51), (13, 0.58), (17, 0.65)):
        points[mcp] = (x, 0.60)
        points[mcp + 1] = (x, 0.47)
        points[mcp + 2] = (x, 0.40)
        points[mcp + 3] = (x, 0.34)
    points[2] = (0.36, 0.72)
    points[3] = (0.31, 0.71)
    points[4] = (0.27, 0.70)
    hand = [SimpleNamespace(x=x, y=y, z=0.0) for x, y in points]
    result = classify_hand(hand, "R")
    record("landmark classifier", result == ("P", "11111"), str(result))


def check_camera():
    from camera_compat import open_camera

    camera = open_camera()
    real = getattr(camera, "is_real", True)
    ok, frame = camera.read()
    camera.release()
    shape = None if frame is None else frame.shape
    record("camera source", ok and frame is not None,
           "{} ({})".format("physical" if real else "virtual fallback", shape))
    if not real:
        print("       No usable camera in this process: the virtual camera "
              "is active.")
        print("       Run check_camera.bat as administrator to test the webcam.")


def check_pygame():
    import pygame

    pygame.init()
    try:
        screen = pygame.display.set_mode((480, 800))
        record("pygame display", screen is not None,
               "{}x{}".format(*screen.get_size()))
        font_path = os.path.join(ROOT, "platech.ttf")
        font = pygame.font.Font(font_path, 32)
        surface = font.render("手势音游 得分 120", True, (255, 255, 255))
        record("Chinese font rendering", surface.get_width() > 0,
               "{}x{}".format(surface.get_width(), surface.get_height()))
        from gesture_icons import draw_note_card
        card_font = pygame.font.Font(font_path, 26)
        draw_note_card(screen, "P11111N11111", 5,
                       pygame.Rect(10, 10, 140, 130), card_font)
        record("gesture note card drawing", True, "140x130")
    finally:
        pygame.display.quit()
        pygame.quit()


def check_game_logic():
    from game_core import HighScoreStore, RhythmGame

    game = RhythmGame(seed=1, highscore=HighScoreStore(os.devnull))
    record("game starts in ready state",
           game.state == RhythmGame.READY)
    game.start()
    for _ in range(120):
        game.update(1 / 60.0, SimpleNamespace(code=None, start_pose=False))
    record("notes spawn while playing", len(game.notes) > 0,
           "{} note(s)".format(len(game.notes)))


def main():
    print("Gesture Rhythm - environment check")
    print("=" * 70)
    check_runtime()
    print("-" * 70)
    check_packages()
    print("-" * 70)
    check_files()
    print("-" * 70)
    try:
        check_catalog()
    except Exception:
        record("gesture catalog", False, "see traceback below")
        traceback.print_exc()
    print("-" * 70)
    try:
        check_gesture()
    except Exception:
        record("load MediaPipe Hands", False, "see traceback below")
        traceback.print_exc()
    print("-" * 70)
    try:
        check_camera()
    except Exception:
        record("camera source", False, "see traceback below")
        traceback.print_exc()
    print("-" * 70)
    try:
        check_pygame()
    except Exception:
        record("pygame display", False, "see traceback below")
        traceback.print_exc()
    print("-" * 70)
    try:
        check_game_logic()
    except Exception:
        record("game logic", False, "see traceback below")
        traceback.print_exc()

    failed = [name for name, ok, _ in RESULTS if not ok]
    print("=" * 70)
    if failed:
        print("RESULT: {} check(s) failed: {}".format(
            len(failed), ", ".join(failed)))
        return 1
    print("RESULT: all {} checks passed.".format(len(RESULTS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

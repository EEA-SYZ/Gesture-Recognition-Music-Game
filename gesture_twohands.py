# -*- coding: utf-8 -*-
"""Two-hand MediaPipe recognition over the whole camera frame.

The camera image is mirrored (selfie view) and the *complete* frame is fed to
MediaPipe Hands with ``max_num_hands=2``.  For every hand the 21 landmarks are
turned into the 6 character description used by the game::

    <P|N><thumb><index><middle><ring><pinky>

Hands are ordered by their horizontal position in the (mirrored) image, so the
hand drawn on the left half of the screen is always the left hand of the code.

``CameraWorker`` runs capture + inference in a background thread so the pygame
loop keeps a smooth frame rate; the main thread only reads the newest annotated
frame / gesture state and shows it with ``cv2.imshow``.
"""

from __future__ import absolute_import

import collections
import os
import threading
import time
import traceback

os.environ.setdefault("GLOG_minloglevel", "2")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

import cv2
import numpy as np

try:  # Keep the console readable; we print our own diagnostics.
    cv2.setLogLevel(0)
except Exception:
    pass

from gesture_catalog import hand_code, make_code  # noqa: E402

# ---------------------------------------------------------------------------
# Tuning constants.  They are deliberately gathered here so they can be tuned
# on a real camera without touching the maths below.
#
# A long finger is classified purely by the angles between its joint nodes
# (MCP -> PIP -> DIP -> TIP); the angles are measured in 3D so a finger that
# points towards the camera is not judged from its shortened 2D projection.
# ---------------------------------------------------------------------------

#: PIP joint angle (degrees) above which the middle phalanx is straight.
FOLD_ANGLE = 158.0
#: DIP joint angle (degrees) above which the distal phalanx is straight.
FOLD_ANGLE_DIP = 140.0
#: Thumb tip distance from the palm centre, relative to the palm size.  The
#: thumb folds by rotating at its base, which no chain angle can see, so its
#: distance from the palm is used instead.  Resting on the fingers ~0.4-0.65,
#: a spread thumb ~0.9-1.1.
THUMB_PALM_RATIO = 0.72
#: Thumb IP angle (degrees) below which the thumb counts as curled.
THUMB_FOLD_ANGLE = 150.0
#: Horizontal thumb offset (relative to palm size) that is unambiguous.
THUMB_SIDE_RATIO = 0.22
#: Number of frames used by the per-hand majority vote.
SMOOTH_WINDOW = 4

#: Colours per screen side, shared by the skeleton drawing and the preview
#: overlay (BGR).
HAND_COLORS = {"L": (0, 226, 255), "R": (120, 255, 120)}

WRIST = 0
THUMB_MCP, THUMB_IP, THUMB_TIP = 2, 3, 4
INDEX_MCP = 5
MIDDLE_MCP = 9
PALM_POINTS = (0, 5, 9, 13, 17)
FINGER_CHAINS = (
    (5, 6, 7, 8),      # index  (MCP, PIP, DIP, TIP)
    (9, 10, 11, 12),   # middle
    (13, 14, 15, 16),  # ring
    (17, 18, 19, 20),  # pinky
)


def _as_xyz(landmarks):
    """Landmarks (objects with x/y/z) -> float32 array of shape (21, 3)."""
    return np.array([[float(lm.x), float(lm.y),
                      float(getattr(lm, "z", 0.0))] for lm in landmarks],
                    dtype=np.float32)


def _joint_angle(a, b, c):
    """Angle ABC in degrees, measured in 3D."""
    v1 = a - b
    v2 = c - b
    n1 = float(np.linalg.norm(v1))
    n2 = float(np.linalg.norm(v2))
    if n1 < 1e-9 or n2 < 1e-9:
        return 0.0
    cos_value = float(np.dot(v1, v2) / (n1 * n2))
    return float(np.degrees(np.arccos(np.clip(cos_value, -1.0, 1.0))))


def finger_angles(pts, mcp, pip, dip, tip):
    """Return the PIP and DIP joint angles of one long finger in degrees."""
    return (_joint_angle(pts[mcp], pts[pip], pts[dip]),
            _joint_angle(pts[pip], pts[dip], pts[tip]))


def _finger_extended(pts, mcp, pip, dip, tip):
    """A long finger is extended when both of its joints are almost straight.

    This is purely the joint-angle test: the middle phalanx (PIP) has to be
    straight and the distal phalanx (DIP) must not hook under.  Folded fingers
    bend at the knuckle, which drops the PIP angle far below the threshold.
    """
    pip_angle, dip_angle = finger_angles(pts, mcp, pip, dip, tip)
    return pip_angle >= FOLD_ANGLE and dip_angle >= FOLD_ANGLE_DIP


def _thumb_extended(pts, palm_center, palm_size):
    """The thumb is out when it is straight and clearly away from the palm.

    A thumb folded over the fingers keeps its own joints almost straight (it
    rotates at the base of the hand), so the distance from the palm centre is
    the discriminating measurement here.
    """
    angle = _joint_angle(pts[THUMB_MCP], pts[THUMB_IP], pts[THUMB_TIP])
    if angle < THUMB_FOLD_ANGLE:
        return False
    distance = float(np.linalg.norm(pts[THUMB_TIP] - palm_center)) / palm_size
    return distance >= THUMB_PALM_RATIO


def _thumb_points_right(pts, palm_size):
    """True when the thumb points to the right of the image (mirrored view)."""
    palm_center = pts[list(PALM_POINTS)].mean(axis=0)
    dx = float(pts[THUMB_TIP][0] - palm_center[0])
    if abs(dx) >= THUMB_SIDE_RATIO * palm_size:
        return dx > 0.0
    # Thumb pointing up / down (e.g. a fist): fall back to the side of the
    # palm the thumb is attached to.
    return float(pts[THUMB_MCP][0] - pts[INDEX_MCP][0]) > 0.0


def classify_hand(landmarks, side):
    """Classify one MediaPipe hand into ``(thumb_token, bits)``.

    Args:
        landmarks: 21 MediaPipe landmarks (``x``/``y`` normalised 0..1 and
            ``z`` relative depth) from a mirrored frame.
        side: ``"L"`` when the hand is on the left half of the screen,
            ``"R"`` when it is on the right half.

    Returns:
        ``(thumb, bits)`` such as ``("P", "11111")`` or ``None`` when the
        landmarks are unusable.
    """
    pts = _as_xyz(landmarks)
    if pts.shape != (21, 3):
        return None
    palm_size = float(np.linalg.norm(pts[WRIST] - pts[MIDDLE_MCP]))
    if palm_size < 1e-6:
        return None
    palm_center = pts[list(PALM_POINTS)].mean(axis=0)

    bits = ["1" if _thumb_extended(pts, palm_center, palm_size) else "0"]
    for mcp, pip, dip, tip in FINGER_CHAINS:
        bits.append("1" if _finger_extended(pts, mcp, pip, dip, tip)
                    else "0")

    pointing_right = _thumb_points_right(pts, palm_size)
    points_centre = pointing_right if side == "L" else not pointing_right
    thumb = "P" if points_centre else "N"
    return thumb, "".join(bits)


class HandReading(object):
    """One recognised hand."""

    __slots__ = ("side", "thumb", "bits", "landmarks")

    def __init__(self, side, thumb, bits, landmarks=None):
        self.side = side
        self.thumb = thumb
        self.bits = bits
        self.landmarks = landmarks  # raw MediaPipe landmarks (for drawing)

    @property
    def code(self):
        return hand_code(self.thumb, self.bits)

    def __repr__(self):
        return "HandReading({}, {})".format(self.side, self.code)


#: The exact pose that starts a round: both hands fully open, both thumbs
#: pointing towards the middle of the screen.
START_CODE = "P11111P11111"


def is_start_pose(code):
    """True when a 12 character code is the "both hands open" start pose."""
    return code == START_CODE


class GestureFrame(object):
    """Result of one recognition pass."""

    __slots__ = ("code", "hands", "image", "start_pose", "timestamp")

    def __init__(self, code=None, hands=None, image=None, start_pose=False,
                 timestamp=0.0):
        self.code = code
        self.hands = hands or []
        self.image = image
        self.start_pose = start_pose
        self.timestamp = timestamp

    @property
    def hand_count(self):
        return len(self.hands)

    def hand(self, side):
        for item in self.hands:
            if item.side == side:
                return item
        return None

    def __repr__(self):
        return "GestureFrame(code={!r}, hands={})".format(
            self.code, len(self.hands))


EMPTY_FRAME = GestureFrame()


def _smooth_tokens(history, stable, token):
    """Per-character majority vote over the recent 6 character tokens."""
    history.append(token)
    previous = stable or token
    chars = []
    for index in range(6):
        counts = collections.Counter(item[index] for item in history)
        char, count = counts.most_common(1)[0]
        if count * 2 <= len(history):
            # No strict majority (including a tie): keep what we had.
            char = previous[index]
        chars.append(char)
    return "".join(chars)


class TwoHandRecognizer(object):
    """MediaPipe Hands wrapper producing :class:`GestureFrame` objects."""

    def __init__(self,
                 min_detection_confidence=0.55,
                 min_tracking_confidence=0.50,
                 model_complexity=None,
                 smooth_window=SMOOTH_WINDOW):
        import mediapipe as mp

        if model_complexity is None:
            # Complexity 0 is roughly twice as fast (two hands must fit in one
            # camera frame); set GAME_HAND_MODEL=1 for the slower, more precise
            # landmark model.
            try:
                model_complexity = int(os.environ.get("GAME_HAND_MODEL", "0"))
            except ValueError:
                model_complexity = 0

        self._modules = mp.solutions.hands
        self._drawing = mp.solutions.drawing_utils
        self._hands = self._modules.Hands(
            static_image_mode=False,
            max_num_hands=2,
            model_complexity=model_complexity,
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence)
        self._history = {"L": collections.deque(maxlen=smooth_window),
                         "R": collections.deque(maxlen=smooth_window)}
        self._stable = {"L": None, "R": None}
        #: Distinct colours per screen side (BGR).
        self.colors = dict(HAND_COLORS)

    # -- recognition ----------------------------------------------------
    def _reset_side(self, side):
        self._history[side].clear()
        self._stable[side] = None

    def _smooth(self, side, token):
        smoothed = _smooth_tokens(self._history[side], self._stable[side],
                                  token)
        self._stable[side] = smoothed
        return smoothed

    def process(self, frame_bgr):
        """Recognise both hands on *frame_bgr* and draw the skeletons on it."""
        if frame_bgr is None or frame_bgr.size == 0:
            return GestureFrame()

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        results = self._hands.process(rgb)

        detections = []
        if results.multi_hand_landmarks:
            for hand_landmarks in results.multi_hand_landmarks:
                xs = [lm.x for lm in hand_landmarks.landmark]
                detections.append((sum(xs) / len(xs), hand_landmarks))
        detections.sort(key=lambda item: item[0])

        if len(detections) >= 2:
            sides = ["L", "R"]
            detections = detections[:2]
        elif len(detections) == 1:
            sides = ["L" if detections[0][0] < 0.5 else "R"]
        else:
            sides = []

        present = set(sides)
        for side in ("L", "R"):
            if side not in present:
                self._reset_side(side)

        hands = []
        for side, (_, hand_landmarks) in zip(sides, detections):
            classified = classify_hand(hand_landmarks.landmark, side)
            if classified is None:
                self._reset_side(side)
                continue
            thumb, bits = classified
            smoothed = self._smooth(side, hand_code(thumb, bits))
            hands.append(HandReading(side, smoothed[0], smoothed[1:],
                                     hand_landmarks))

        hands.sort(key=lambda item: item.side)

        code = None
        if len(hands) == 2:
            code = make_code(hands[0].code, hands[1].code)

        start_pose = is_start_pose(code)

        for hand in hands:
            self._draw_hand(frame_bgr, hand)

        return GestureFrame(code=code, hands=hands, image=frame_bgr,
                            start_pose=start_pose, timestamp=time.time())

    # -- drawing --------------------------------------------------------
    def _draw_hand(self, frame, hand):
        color = self.colors[hand.side]
        try:
            self._drawing.draw_landmarks(
                frame,
                hand.landmarks,
                self._modules.HAND_CONNECTIONS,
                self._drawing.DrawingSpec(color=color, thickness=2,
                                          circle_radius=3),
                self._drawing.DrawingSpec(color=color, thickness=2))
        except Exception:
            return
        points = hand.landmarks.landmark
        height, width = frame.shape[:2]
        x = int(points[WRIST].x * width)
        y = int(points[WRIST].y * height)
        label = "{} {}".format("LEFT" if hand.side == "L" else "RIGHT",
                               hand.code)
        label_x = min(max(4, x - 40), max(4, width - 150))
        label_y = min(max(4, y + 16), max(4, height - 40))
        _text_box(frame, label, (label_x, label_y), color, 0.62)

    def close(self):
        try:
            self._hands.close()
        except Exception:
            pass

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


def _text_box(frame, text, org, color, scale):
    """Draw text with a translucent dark background for readability."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    thickness = 1
    (text_w, text_h), baseline = cv2.getTextSize(text, font, scale, thickness)
    x, y = org
    cv2.rectangle(frame, (x - 4, y - 4),
                  (x + text_w + 4, y + text_h + baseline + 2),
                  (25, 25, 25), -1)
    cv2.rectangle(frame, (x - 4, y - 4),
                  (x + text_w + 4, y + text_h + baseline + 2),
                  (90, 90, 90), 1)
    cv2.putText(frame, text, (x, y + text_h), font, scale, color,
                thickness, cv2.LINE_AA)


class CameraWorker(object):
    """Capture + recognise in a background thread, expose the newest frame."""

    def __init__(self, camera, recognizer=None, mirror=True, target_fps=30):
        self._camera = camera
        self._recognizer = recognizer
        self._mirror = mirror
        self._interval = 1.0 / float(target_fps)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._latest_frame = None
        self._latest_gesture = EMPTY_FRAME
        self.error = None
        #: Warning text shown on the game screen (virtual camera, ...).
        self.warning = None

    # -- lifecycle ------------------------------------------------------
    def start(self):
        self._thread = threading.Thread(target=self._run,
                                        name="camera-worker", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    # -- data -----------------------------------------------------------
    def latest(self):
        """Return ``(annotated_image, GestureFrame)`` (both may be empty)."""
        with self._lock:
            return self._latest_frame, self._latest_gesture

    def _publish(self, image, gesture):
        with self._lock:
            self._latest_frame = image
            self._latest_gesture = gesture

    def _run(self):
        while not self._stop.is_set():
            started = time.time()
            try:
                grabbed, frame = self._camera.read()
            except Exception:
                self.error = "camera read failed"
                traceback.print_exc()
                break
            if not grabbed or frame is None or not getattr(frame, "size", 0):
                time.sleep(0.05)
                continue
            if self._mirror:
                frame = cv2.flip(frame, 1)
            try:
                if self._recognizer is None:
                    gesture = GestureFrame(image=frame, timestamp=started)
                else:
                    gesture = self._recognizer.process(frame)
            except Exception:
                self.error = "hand recognition failed"
                traceback.print_exc()
                break
            self._publish(gesture.image if gesture.image is not None
                          else frame, gesture)
            delay = self._interval - (time.time() - started)
            if delay > 0:
                time.sleep(delay)

    def close(self):
        self.stop()
        try:
            self._camera.release()
        except Exception:
            pass
        if self._recognizer is not None:
            self._recognizer.close()

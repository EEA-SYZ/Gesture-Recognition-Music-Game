# -*- coding: utf-8 -*-
"""Pure game logic of the gesture rhythm game (no pygame, fully testable).

The scene, the hand recogniser and the audio live elsewhere; this module only
knows about notes, difficulty, scoring and the game state machine, so it can be
unit tested without a camera, a display or a sound card.
"""

from __future__ import absolute_import

import json
import math
import random

from gesture_catalog import random_code

#: Window / play field geometry (pixels).
SCREEN_WIDTH = 480
SCREEN_HEIGHT = 800
PLAY_TOP = 100
PLAY_BOTTOM = 700
HUD_HEIGHT = PLAY_TOP

LANES = 3
NOTE_WIDTH = 140
NOTE_HEIGHT = 130

MAX_CHANCES = 3
RAMP_SECONDS = 90.0       # seconds from "as easy as possible" to full difficulty
HOLD_SECONDS = 0.7        # the P11111P11111 pose held this long starts the game
HIT_COOLDOWN = 0.22       # seconds between two matches of the same gesture
POPUP_TTL = 0.85

SPAWN_INTERVAL_EASY = 1.90
SPAWN_INTERVAL_MID = 1.10    # end of the 30-60 s stage (not the limit yet)
SPAWN_INTERVAL_HARD = 0.55
SPEED_EASY = 105.0
SPEED_MID = 175.0            # end of the 30-60 s stage (not the limit yet)
SPEED_HARD = 290.0
SPEED_SPREAD = 0.55          # per-note speed range above the current base speed
SPEED_WOBBLE = 0.09          # slow fluctuation of the base speed (up to +-9%)
SPEED_WOBBLE_RATE = 0.55     # rad/s of that fluctuation

#: Stage boundaries as fractions of the 90 s ramp: 0-30 s, 30-60 s, 60-90 s.
STAGE_1 = 1.0 / 3.0
STAGE_2 = 2.0 / 3.0

#: Note value probabilities when the first (variety) stage ends: 5 / 10 / 15,
#: still no red 20 note.  The 20 point share then fades in during the last
#: stage together with the final interval and speed.
WEIGHTS_STAGE_1_END = (0.35, 0.35, 0.30, 0.00)
WEIGHTS_FINAL = (0.20, 0.30, 0.25, 0.25)


class Note(object):
    """One falling gesture note."""

    __slots__ = ("code", "value", "lane", "x", "y", "w", "h", "speed")

    def __init__(self, code, value, lane, x, y, speed,
                 width=NOTE_WIDTH, height=NOTE_HEIGHT):
        self.code = code
        self.value = value
        self.lane = lane
        self.x = float(x)
        self.y = float(y)
        self.w = width
        self.h = height
        self.speed = float(speed)

    @property
    def center(self):
        return (self.x + self.w / 2.0, self.y + self.h / 2.0)

    @property
    def rect(self):
        return (int(round(self.x)), int(round(self.y)), self.w, self.h)

    def __repr__(self):
        return "Note({}, {}pt, lane {})".format(self.code, self.value,
                                                self.lane)


class HighScoreStore(object):
    """Tiny JSON persistence for the best score (never crashes the game)."""

    def __init__(self, path="highscore.json"):
        self.path = path
        self.default = {"best": 0, "last": 0, "games": 0}

    def load(self):
        data = dict(self.default)
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                for key in data:
                    value = loaded.get(key)
                    if isinstance(value, (int, float)) and value >= 0:
                        data[key] = int(value)
        except Exception:
            pass
        return data

    def save(self, data):
        try:
            with open(self.path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            return True
        except Exception:
            return False


class Difficulty(object):
    """Three-stage difficulty ramp (90 s by default).

    * ``0-30 s``   note *variety* only: 10 and 15 point notes fade in, the
      spawn interval and the fall speed stay at their easiest values and the
      red 20 point notes do not appear at all;
    * ``30-60 s``  spawn *rate* and fall *speed* rise together, but only up to
      a mid value - neither reaches its limit yet;
    * ``60-90 s``  the red 20 point notes fade in while the interval and the
      fall speed are pushed to their limits.

    The stage boundaries are fractions of the ramp (``STAGE_1``/``STAGE_2``),
    so the default 90 s timeline is exactly 0-30-60-90 seconds.
    """

    def __init__(self, ramp_seconds=RAMP_SECONDS):
        self.ramp_seconds = float(ramp_seconds)
        self.progress = 0.0
        self.elapsed = 0.0

    def at(self, elapsed):
        self.elapsed = max(0.0, float(elapsed))
        if self.ramp_seconds <= 0:
            self.progress = 1.0
        else:
            self.progress = max(0.0, min(1.0,
                                          self.elapsed / self.ramp_seconds))
        return self.progress

    @property
    def value(self):
        return self.progress

    @property
    def stage(self):
        """0, 1 or 2 (0-30 s, 30-60 s, 60-90 s of the ramp)."""
        if self.progress < STAGE_1:
            return 0
        if self.progress < STAGE_2:
            return 1
        return 2

    @property
    def stage_t(self):
        """Progress (0..1) inside the current stage."""
        if self.progress < STAGE_1:
            return self.progress / STAGE_1 if STAGE_1 > 0 else 1.0
        if self.progress < STAGE_2:
            return ((self.progress - STAGE_1) / (STAGE_2 - STAGE_1)
                    if STAGE_2 > STAGE_1 else 1.0)
        return ((self.progress - STAGE_2) / (1.0 - STAGE_2)
                if STAGE_2 < 1.0 else 1.0)

    @property
    def level(self):
        """1..10 for the HUD."""
        return 1 + int(round(self.progress * 9))

    def spawn_interval(self):
        stage, t = self.stage, self.stage_t
        if stage == 0:
            return SPAWN_INTERVAL_EASY
        if stage == 1:
            return (SPAWN_INTERVAL_EASY +
                    (SPAWN_INTERVAL_MID - SPAWN_INTERVAL_EASY) * t)
        return (SPAWN_INTERVAL_MID +
                (SPAWN_INTERVAL_HARD - SPAWN_INTERVAL_MID) * t)

    def _base_speed_ramp(self):
        stage, t = self.stage, self.stage_t
        if stage == 0:
            return SPEED_EASY
        if stage == 1:
            return SPEED_EASY + (SPEED_MID - SPEED_EASY) * t
        return SPEED_MID + (SPEED_HARD - SPEED_MID) * t

    @property
    def speed_ramp(self):
        """0..1 across the whole speed range (105..290 px/s)."""
        span = SPEED_HARD - SPEED_EASY
        if span <= 0:
            return 1.0
        return max(0.0, min(1.0, (self._base_speed_ramp() - SPEED_EASY) / span))

    def base_speed(self):
        """Base fall speed for new notes.

        From 30 s on it wobbles slowly around the ramp so the fall speed never
        feels like a fixed constant; during the variety stage it is exactly
        ``SPEED_EASY``.
        """
        base = self._base_speed_ramp()
        wobble = 1.0 + (SPEED_WOBBLE * self.speed_ramp *
                        math.sin(self.elapsed * SPEED_WOBBLE_RATE))
        return base * wobble

    def speed_exponent(self):
        """Smaller exponent -> faster notes become more likely."""
        return 1.0 - 0.65 * self.speed_ramp

    def value_weights(self):
        """Probabilities of 5 / 10 / 15 / 20 point notes."""
        stage, t = self.stage, self.stage_t
        if stage == 0:
            w10 = 0.35 * t
            w15 = 0.30 * t ** 1.5
            w20 = 0.0
        elif stage == 1:
            w10 = WEIGHTS_STAGE_1_END[1]
            w15 = WEIGHTS_STAGE_1_END[2]
            w20 = 0.0
        else:
            w10 = (WEIGHTS_STAGE_1_END[1] +
                   (WEIGHTS_FINAL[1] - WEIGHTS_STAGE_1_END[1]) * t)
            w15 = (WEIGHTS_STAGE_1_END[2] +
                   (WEIGHTS_FINAL[2] - WEIGHTS_STAGE_1_END[2]) * t)
            w20 = WEIGHTS_FINAL[3] * t
        w5 = max(0.0, 1.0 - w10 - w15 - w20)
        return (w5, w10, w15, w20)


class RhythmGame(object):
    """State machine, note spawner and scoring of the rhythm game."""

    READY = "ready"
    PLAYING = "playing"
    OVER = "over"

    def __init__(self, width=SCREEN_WIDTH, play_top=PLAY_TOP,
                 play_bottom=PLAY_BOTTOM, lanes=LANES,
                 note_width=NOTE_WIDTH, note_height=NOTE_HEIGHT,
                 max_chances=MAX_CHANCES, ramp_seconds=RAMP_SECONDS,
                 hold_seconds=HOLD_SECONDS, hit_cooldown=HIT_COOLDOWN,
                 seed=None, highscore=None):
        self.width = width
        self.play_top = play_top
        self.play_bottom = play_bottom
        self.lanes = int(lanes)
        self.note_width = note_width
        self.note_height = note_height
        self.lane_width = width / float(self.lanes)
        self.max_chances = int(max_chances)
        self.hold_seconds = float(hold_seconds)
        self.hit_cooldown_seconds = float(hit_cooldown)
        self.rng = random.Random(seed)
        self.difficulty = Difficulty(ramp_seconds)

        self.highscores = highscore or HighScoreStore()
        self.record = self.highscores.load()
        self.best_score = self.record["best"]

        self.events = []
        self.popups = []
        self.time = 0.0
        self.gesture_code = None
        self.reset()

    # -- state ----------------------------------------------------------
    def reset(self):
        """Back to the "show both hands" screen (holding hands is required)."""
        self.state = self.READY
        self.score = 0
        self.chances = self.max_chances
        self.combo = 0
        self.best_combo = 0
        self.hits = 0
        self.misses = 0
        self.red_introduced = False
        self.elapsed = 0.0
        self.difficulty.at(0.0)
        self.notes = []
        self.spawn_timer = 0.0
        self.hit_cooldown = 0.0
        self.hold_time = 0.0
        self.hit_flash = 0.0
        self.miss_flash = 0.0
        self.last_hit_value = 0
        self.last_hit_pos = None
        self.events = []
        self.popups = []
        self.new_record = False
        self.last_score = 0

    def start(self):
        """Start a fresh round from the ready screen."""
        self.score = 0
        self.chances = self.max_chances
        self.combo = 0
        self.best_combo = 0
        self.hits = 0
        self.misses = 0
        self.red_introduced = False
        self.elapsed = 0.0
        self.difficulty.at(0.0)
        self.notes = []
        self.spawn_timer = 0.9
        self.hit_cooldown = 0.0
        self.hold_time = 0.0
        self.hit_flash = 0.0
        self.miss_flash = 0.0
        self.last_hit_value = 0
        self.last_hit_pos = None
        self.popups = []
        self.new_record = False
        self.state = self.PLAYING

    def restart(self):
        """Restart button: back to the ready screen.

        The next round always has to be started by holding P11111P11111 again,
        exactly like the first round.
        """
        self.reset()

    @property
    def hold_progress(self):
        if self.hold_seconds <= 0:
            return 1.0
        return max(0.0, min(1.0, self.hold_time / self.hold_seconds))

    @property
    def difficulty_value(self):
        return self.difficulty.value

    # -- update ---------------------------------------------------------
    def update(self, dt, gesture=None):
        """Advance the game by *dt* seconds.

        Args:
            gesture: object with ``code`` (12 chars or None) and ``start_pose``
                attributes, i.e. a :class:`gesture_twohands.GestureFrame`.
        """
        dt = max(0.0, min(float(dt), 0.1))
        self.time += dt
        self.events = []
        self._update_flashes(dt)

        if gesture is not None:
            self.gesture_code = getattr(gesture, "code", None)

        if self.state == self.READY:
            self._update_ready(dt, gesture)
        elif self.state == self.PLAYING:
            self._update_playing(dt, gesture)
        return self.events

    def _update_flashes(self, dt):
        self.hit_flash = max(0.0, self.hit_flash - dt)
        self.miss_flash = max(0.0, self.miss_flash - dt)
        for popup in self.popups:
            popup["age"] += dt
        self.popups = [p for p in self.popups if p["age"] < POPUP_TTL]

    def _update_ready(self, dt, gesture):
        start_pose = bool(getattr(gesture, "start_pose", False))
        if not start_pose:
            self.hold_time = max(0.0, self.hold_time - dt * 2.5)
            return
        self.hold_time += dt
        if self.hold_time >= self.hold_seconds:
            self.start()
            self.events.append({"type": "start"})

    def _update_playing(self, dt, gesture):
        self.elapsed += dt
        self.difficulty.at(self.elapsed)
        if self.hit_cooldown > 0:
            self.hit_cooldown = max(0.0, self.hit_cooldown - dt)

        # One red note is introduced exactly when the second stage begins
        # (30 s of the default 90 s ramp), even though red notes only start
        # appearing randomly in the last stage.
        if not self.red_introduced and self.difficulty.progress >= STAGE_1:
            self._spawn_note(value=20)
            self.red_introduced = True

        # Spawn.
        self.spawn_timer -= dt
        guard = 0
        while self.spawn_timer <= 0.0 and guard < 4:
            self._spawn_note()
            self.spawn_timer += self._next_interval()
            guard += 1

        # Fall and detect missed notes.
        alive = []
        missed = []
        for note in self.notes:
            note.y += note.speed * dt
            if note.y >= self.play_bottom:
                missed.append(note)
            else:
                alive.append(note)
        self.notes = alive
        for note in missed:
            self._register_miss(note)
            if self.state != self.PLAYING:
                return

        self._try_hit(gesture)

    # -- gameplay helpers ----------------------------------------------
    def _pick_lane(self):
        best_lane, best_space = 0, -1e9
        for lane in range(self.lanes):
            lane_notes = [n for n in self.notes if n.lane == lane]
            space = min([n.y for n in lane_notes]) if lane_notes else 1e9
            # A little randomness keeps two equally free lanes from always
            # receiving the next note in the same order.
            space += self.rng.random() * 40.0
            if space > best_space:
                best_lane, best_space = lane, space
        return best_lane

    def _pick_value(self):
        weights = self.difficulty.value_weights()
        roll = self.rng.random()
        cumulative = 0.0
        for value, weight in zip((5, 10, 15, 20), weights):
            cumulative += weight
            if roll < cumulative:
                return value
        return 20

    def _roll_speed(self):
        exponent = self.difficulty.speed_exponent()
        return self.difficulty.base_speed() * (
            1.0 + SPEED_SPREAD * self.rng.random() ** exponent)

    def _next_interval(self):
        return self.difficulty.spawn_interval() * self.rng.uniform(0.85, 1.15)

    def _spawn_note(self, value=None):
        if value is None:
            value = self._pick_value()
        code = random_code(value, self.rng)
        lane = self._pick_lane()
        x = lane * self.lane_width + (self.lane_width - self.note_width) / 2.0
        note = Note(code, value, lane, x,
                    self.play_top - self.note_height, self._roll_speed())
        self.notes.append(note)
        return note

    def _try_hit(self, gesture):
        code = getattr(gesture, "code", None) if gesture else None
        if not code or self.hit_cooldown > 0:
            return None
        matches = [note for note in self.notes if note.code == code]
        if not matches:
            return None
        note = max(matches, key=lambda item: item.y)
        self.notes.remove(note)
        self.score += note.value
        self.hits += 1
        self.combo += 1
        self.best_combo = max(self.best_combo, self.combo)
        self.hit_cooldown = self.hit_cooldown_seconds
        self.hit_flash = 0.35
        self.last_hit_value = note.value
        self.last_hit_pos = note.center
        self.popups.append({"x": note.center[0], "y": note.center[1],
                            "value": note.value, "age": 0.0})
        self.events.append({"type": "hit", "value": note.value,
                            "code": note.code, "combo": self.combo,
                            "pos": note.center})
        return note

    def _register_miss(self, note):
        self.chances -= 1
        self.combo = 0
        self.misses += 1
        self.miss_flash = 0.5
        self.events.append({"type": "miss", "code": note.code,
                            "value": note.value, "chances": self.chances})
        if self.chances <= 0:
            self._finish()

    def _finish(self):
        self.state = self.OVER
        self.last_score = self.score
        self.new_record = self.score > self.record["best"]
        data = self.highscores.load()
        data["best"] = max(data["best"], self.score)
        data["last"] = self.score
        data["games"] = data.get("games", 0) + 1
        self.highscores.save(data)
        self.record = data
        self.best_score = data["best"]
        self.events.append({"type": "gameover", "score": self.score,
                            "best": self.best_score,
                            "new_record": self.new_record})

    # -- views ----------------------------------------------------------
    def matching_notes(self, code):
        """Notes that the given gesture would clear right now."""
        if not code:
            return []
        return [note for note in self.notes if note.code == code]

# -*- coding: utf-8 -*-
"""Optional sound effects, synthesised with numpy (no audio assets needed).

Every sound is generated at start-up and played through ``pygame.mixer``.  If
no audio device exists (headless CI, RDP session, muted machine) the module
silently disables itself, so the game never fails because of audio.  Set
``GAME_NO_SOUND=1`` to disable it explicitly.
"""

from __future__ import absolute_import

import os

SAMPLE_RATE = 44100


class SoundBank(object):
    """Small collection of generated blips and jingles."""

    def __init__(self, enabled=None):
        if enabled is None:
            enabled = os.environ.get("GAME_NO_SOUND", "0") != "1"
        self.enabled = False
        self.sounds = {}
        self._pygame = None
        self.rate = SAMPLE_RATE
        self.channels = 1
        if not enabled:
            return
        try:
            import numpy as np
            import pygame

            if not pygame.mixer.get_init():
                pygame.mixer.init(SAMPLE_RATE, -16, 1, 512)
            init = pygame.mixer.get_init()
            if not init or init[1] != -16:
                raise RuntimeError("unsupported mixer format")
            self.rate, _fmt, self.channels = init
            self._pygame = pygame
            self._np = np
            self._build()
            self.enabled = True
        except Exception:
            self.enabled = False
            self.sounds = {}

    # -- synthesis ------------------------------------------------------
    def _to_sound(self, samples):
        """Convert a float waveform (-1..1) to a pygame Sound."""
        np = self._np
        samples = (samples * 32767.0).astype(np.int16)
        if self.channels > 1:
            samples = np.stack([samples] * self.channels, axis=1)
        return self._pygame.sndarray.make_sound(
            np.ascontiguousarray(samples))

    def _tone(self, freqs, duration=0.12, volume=0.20, decay=16.0,
              attack=0.004):
        np = self._np
        count = max(1, int(self.rate * duration))
        times = np.arange(count, dtype=np.float32) / self.rate
        wave = np.zeros(count, dtype=np.float32)
        for freq in freqs:
            wave += np.sin(2.0 * np.pi * freq * times).astype(np.float32)
        wave /= float(len(freqs))
        envelope = np.exp(-decay * times).astype(np.float32)
        attack_count = max(1, int(self.rate * attack))
        envelope[:attack_count] *= np.linspace(0.0, 1.0, attack_count,
                                              dtype=np.float32)
        return self._to_sound(wave * envelope * volume)

    def _sequence(self, notes, volume=0.20, decay=9.0):
        np = self._np
        chunks = []
        for freq, duration in notes:
            count = max(1, int(self.rate * duration))
            times = np.arange(count, dtype=np.float32) / self.rate
            wave = np.sin(2.0 * np.pi * freq * times).astype(np.float32)
            envelope = np.exp(-decay * times).astype(np.float32)
            fade = max(1, int(self.rate * 0.006))
            envelope[:fade] *= np.linspace(0.0, 1.0, fade, dtype=np.float32)
            envelope[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)
            chunks.append(wave * envelope)
        return self._to_sound(np.concatenate(chunks) * volume)

    def _build(self):
        self.sounds = {
            # Higher notes for higher value gestures.
            "hit5": self._tone([660.0], 0.11, 0.18, 20.0),
            "hit10": self._tone([880.0, 1320.0], 0.13, 0.17, 16.0),
            "hit15": self._tone([1046.0, 1568.0, 2093.0], 0.16, 0.16, 13.0),
            "miss": self._tone([150.0, 110.0], 0.30, 0.24, 7.0),
            "start": self._sequence([(523.25, 0.09), (659.25, 0.09),
                                     (783.99, 0.14)]),
            "gameover": self._sequence([(392.0, 0.16), (311.13, 0.16),
                                        (233.08, 0.30)], volume=0.22,
                                       decay=5.0),
        }

    # -- playback -------------------------------------------------------
    def play(self, event):
        if not self.enabled or not isinstance(event, dict):
            return
        kind = event.get("type")
        if kind == "hit":
            key = {5: "hit5", 10: "hit10", 15: "hit15"}.get(
                event.get("value"), "hit5")
        elif kind == "miss":
            key = "miss"
        elif kind == "start":
            key = "start"
        elif kind == "gameover":
            key = "gameover"
        else:
            return
        sound = self.sounds.get(key)
        if sound is not None:
            try:
                sound.play()
            except Exception:
                pass

    def close(self):
        if self._pygame is not None:
            try:
                self._pygame.mixer.stop()
                self._pygame.mixer.quit()
            except Exception:
                pass
        self.enabled = False

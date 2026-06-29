"""
Geometry helpers in `classifier.py` are pure functions over a 99-float
landmark vector — the easiest things in the world to unit-test, and
the most likely to silently regress (a flipped sign in a threshold, an
axis confusion). These tests pin the contract down.

Numeric thresholds we're testing against (from classifier.py):
  is_head_down:          nose_y - ear_y > 0.025  AND  shoulder_y - nose_y < 0.18
  wrists_low_and_close:  both (wy - shoulder_y) > 0.15  AND  |lw_x - rw_x| < 0.15
  is_sipping:            min(left_wrist_to_nose, right_wrist_to_nose) < 0.15
"""
from __future__ import annotations

from classifier import (
    HeadDownTracker,
    SipTracker,
    is_head_down,
    is_sipping,
    wrists_low_and_close,
)
from test_utils import make_landmarks


# ── is_head_down ──────────────────────────────────────────────────────────

class TestIsHeadDown:
    def test_upright_posture_is_not_head_down(self, upright_landmarks):
        assert is_head_down(upright_landmarks) is False

    def test_chin_to_chest_is_head_down(self, head_down_landmarks):
        assert is_head_down(head_down_landmarks) is True

    def test_below_ear_threshold_is_not_head_down(self):
        # Nose only barely below ears (0.02 < the 0.025 threshold).
        lm = make_landmarks(
            nose=(0.50, 0.42),
            left_ear=(0.45, 0.40),
            right_ear=(0.55, 0.40),
            left_shoulder=(0.40, 0.55),
            right_shoulder=(0.60, 0.55),
        )
        assert is_head_down(lm) is False

    def test_just_past_ear_threshold_is_head_down(self):
        # Nose 0.04 below ears (clearly past 0.025) AND nose 0.11 above
        # shoulders (under the 0.18 ceiling).
        lm = make_landmarks(
            nose=(0.50, 0.44),
            left_ear=(0.45, 0.40),
            right_ear=(0.55, 0.40),
            left_shoulder=(0.40, 0.55),
            right_shoulder=(0.60, 0.55),
        )
        assert is_head_down(lm) is True

    def test_nose_too_high_above_shoulders_is_not_head_down(self):
        # Nose is below ears (slight forward tilt) but still way above the
        # shoulder line — looking down at the screen, not at a phone in lap.
        lm = make_landmarks(
            nose=(0.50, 0.35),
            left_ear=(0.45, 0.32),
            right_ear=(0.55, 0.32),
            left_shoulder=(0.40, 0.70),   # shoulders far below
            right_shoulder=(0.60, 0.70),
        )
        # shoulder_y - nose_y = 0.35, way over the 0.18 ceiling.
        assert is_head_down(lm) is False


# ── wrists_low_and_close ──────────────────────────────────────────────────

class TestWristsLowAndClose:
    def test_phone_in_lap_triggers(self, phone_in_lap_landmarks):
        assert wrists_low_and_close(phone_in_lap_landmarks) is True

    def test_hands_at_keyboard_does_not_trigger(self, upright_landmarks):
        # upright fixture has wrists at y=0.65, shoulders at y=0.55 →
        # 0.10 < 0.15, so this check fails. Good — typing must not look
        # like phone-in-lap.
        assert wrists_low_and_close(upright_landmarks) is False

    def test_wrists_apart_does_not_trigger(self):
        # Wrists low enough, but far apart in x — like hands resting on
        # two sides of the keyboard.
        lm = make_landmarks(
            left_shoulder=(0.40, 0.50),
            right_shoulder=(0.60, 0.50),
            left_wrist=(0.20, 0.80),
            right_wrist=(0.80, 0.80),
        )
        assert wrists_low_and_close(lm) is False

    def test_one_wrist_high_does_not_trigger(self):
        # Right wrist resting on the desk, left wrist scratching face.
        lm = make_landmarks(
            left_shoulder=(0.40, 0.50),
            right_shoulder=(0.60, 0.50),
            left_wrist=(0.45, 0.40),    # high
            right_wrist=(0.55, 0.80),   # low
        )
        assert wrists_low_and_close(lm) is False


# ── is_sipping ────────────────────────────────────────────────────────────

class TestIsSipping:
    def test_wrist_near_nose_is_sipping(self, sipping_landmarks):
        assert is_sipping(sipping_landmarks) is True

    def test_hands_at_desk_is_not_sipping(self, upright_landmarks):
        assert is_sipping(upright_landmarks) is False

    def test_either_wrist_qualifies(self):
        # Left wrist near nose should trigger just as well as right.
        lm = make_landmarks(
            nose=(0.50, 0.30),
            left_wrist=(0.45, 0.32),    # ~0.05 from nose
            right_wrist=(0.70, 0.65),
        )
        assert is_sipping(lm) is True


# ── HeadDownTracker ───────────────────────────────────────────────────────

class TestHeadDownTracker:
    def test_empty_tracker_not_sustained(self):
        t = HeadDownTracker(window_s=30.0)
        assert t.sustained() is False

    def test_below_min_samples_not_sustained(self):
        # Default min_samples=10. Five all-true samples shouldn't qualify
        # even though the ratio is 100% — we need enough data to trust it.
        t = HeadDownTracker(window_s=30.0)
        for i in range(5):
            t.add(float(i), head_down=True)
        assert t.sustained() is False

    def test_sustained_when_ratio_met(self):
        t = HeadDownTracker(window_s=30.0)
        # 16 samples, all head_down → 100%, well above the 80% default.
        for i in range(16):
            t.add(float(i), head_down=True)
        assert t.sustained() is True

    def test_not_sustained_when_below_ratio(self):
        t = HeadDownTracker(window_s=30.0)
        # 20 samples, only 10 head_down → 50%, below 80% default.
        for i in range(20):
            t.add(float(i), head_down=(i % 2 == 0))
        assert t.sustained() is False

    def test_old_samples_age_out(self):
        t = HeadDownTracker(window_s=10.0)
        # Drop 20 head_down samples at t=0..19. Then ask at t=25, when
        # only samples with ts >= 15 are still in the window.
        for i in range(20):
            t.add(float(i), head_down=True)
        # Now poison the recent window with head-up samples.
        for i in range(20, 30):
            t.add(float(i), head_down=False)
        # Only the last 10 samples (head_down=False) survive the 10s window.
        assert t.sustained() is False

    def test_custom_ratio(self):
        t = HeadDownTracker(window_s=30.0)
        # 20 samples, 12 head_down → 60%. Should fail default 80%,
        # pass with ratio=0.5.
        for i in range(20):
            t.add(float(i), head_down=(i < 12))
        assert t.sustained() is False
        assert t.sustained(ratio=0.5) is True

    def test_custom_min_samples_guard(self):
        t = HeadDownTracker(window_s=30.0)
        for i in range(5):
            t.add(float(i), head_down=True)
        # With min_samples lowered to 3, five 100%-true samples qualify.
        assert t.sustained(min_samples=3) is True


# ── SipTracker ────────────────────────────────────────────────────────────

class TestSipTracker:
    def test_empty_tracker_not_sustained(self):
        t = SipTracker(window_s=1.5)
        assert t.sustained() is False

    def test_below_min_samples_not_sustained(self):
        # Default min_samples=5. Three all-true samples shouldn't qualify.
        t = SipTracker(window_s=1.5)
        for i in range(3):
            t.add(float(i) * 0.1, sipping=True)
        assert t.sustained() is False

    def test_sustained_when_ratio_met(self):
        # 6 samples within the window, all sipping → 100% > 0.6.
        t = SipTracker(window_s=1.5)
        for i in range(6):
            t.add(float(i) * 0.2, sipping=True)
        assert t.sustained() is True

    def test_single_frame_flash_not_sustained(self):
        # Regression for the over-counting bug: 5 not-sipping frames
        # followed by 1 sipping frame must NOT count as sustained.
        # A single hand-to-face gesture is exactly this shape.
        t = SipTracker(window_s=1.5)
        for i in range(5):
            t.add(float(i) * 0.2, sipping=False)
        t.add(1.2, sipping=True)
        # 1 sip out of 6 samples = 17% < 60% default ratio.
        assert t.sustained() is False

    def test_old_samples_age_out(self):
        # Window is 1.5s. Drop 6 sipping samples in the first second,
        # then 6 not-sipping samples in the next second. By the time the
        # last sample is added (t=2.0s), the 0.5s+ samples are gone — so
        # only the non-sipping recent samples should count.
        t = SipTracker(window_s=1.0)
        for i in range(6):
            t.add(i * 0.1, sipping=True)        # t=0.0..0.5
        for i in range(6):
            t.add(1.0 + i * 0.1, sipping=False) # t=1.0..1.5
        assert t.sustained() is False

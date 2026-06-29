"""
Tests for the ActivityClassifier.predict() decision tree — how the phone
signal, sustained head-down signal, sustained sipping signal, and pose
geometry compose into an activity label and confidence.

The decision tree from classifier.py is:
  phone_visible AND head_down            → "phone"   (0.90)
  phone_visible AND wrists_low_and_close → "phone"   (0.78)
  NOT phone_visible AND sustained_hd     → "phone"   (0.55)
  is_sipping(latest) AND sustained_sip   → "sipping" (0.75)
  (trained model output, or rule-default)
"""
from __future__ import annotations

from classifier import ActivityClassifier


def _buffer(landmarks: list[float], n: int = 30) -> list[tuple[float, list[float]]]:
    """Build a frame buffer of n identical frames at timestamps 0..n-1."""
    return [(float(i), landmarks) for i in range(n)]


def _fresh_classifier() -> ActivityClassifier:
    """A classifier with no trained model — exercises only the rule layer."""
    # Path that doesn't exist → self.model stays None.
    return ActivityClassifier(model_path="/nonexistent/path/never/find.pkl")


class TestPhonePriority:
    def test_phone_visible_plus_head_down_is_phone_high_conf(self, head_down_landmarks):
        clf = _fresh_classifier()
        label, conf = clf.predict(
            _buffer(head_down_landmarks),
            phone_visible=True,
            sustained_head_down=False,
        )
        assert label == "phone"
        assert conf >= 0.85  # the high-confidence branch

    def test_phone_visible_plus_wrists_in_lap_is_phone_mid_conf(self, phone_in_lap_landmarks):
        # Head is upright in this fixture → first branch fails, second
        # (wrists_low_and_close) fires.
        clf = _fresh_classifier()
        label, conf = clf.predict(
            _buffer(phone_in_lap_landmarks),
            phone_visible=True,
            sustained_head_down=False,
        )
        assert label == "phone"
        assert 0.70 <= conf < 0.85

    def test_sustained_head_down_without_visible_phone_is_phone_low_conf(self, head_down_landmarks):
        # The phone-in-lap-no-visible-phone fallback.
        clf = _fresh_classifier()
        label, conf = clf.predict(
            _buffer(head_down_landmarks),
            phone_visible=False,
            sustained_head_down=True,
        )
        assert label == "phone"
        assert conf < 0.70

    def test_no_signals_falls_through_to_at_desk(self, upright_landmarks):
        clf = _fresh_classifier()
        label, _ = clf.predict(
            _buffer(upright_landmarks),
            phone_visible=False,
            sustained_head_down=False,
        )
        assert label == "at_desk"


class TestSippingOverride:
    def test_sipping_fires_when_geometry_and_sustained_signal_both_true(self, sipping_landmarks):
        # Wrist-near-nose pose AND the rolling window has been sipping
        # for long enough: this is a real sip.
        clf = _fresh_classifier()
        label, conf = clf.predict(
            _buffer(sipping_landmarks),
            phone_visible=False,
            sustained_head_down=False,
            sustained_sipping=True,
        )
        assert label == "sipping"
        assert conf > 0.5

    def test_single_frame_sip_geometry_without_sustain_does_not_fire(self, sipping_landmarks):
        # Regression: the over-counting bug. A momentary gesture (scratch
        # nose, adjust glasses) puts the wrist near the face for ONE
        # frame — that must not log a sip. The sustained-window check is
        # the guard.
        clf = _fresh_classifier()
        label, _ = clf.predict(
            _buffer(sipping_landmarks),
            phone_visible=False,
            sustained_head_down=False,
            sustained_sipping=False,
        )
        assert label != "sipping"

    def test_sustained_sip_without_current_geometry_does_not_fire(self, upright_landmarks):
        # The complementary guard: the window says "we were sipping recently"
        # but the current frame is back at desk. We should NOT re-fire
        # `sipping` after a drink ends — that would re-log every classifier
        # tick during the tail of the sustained window.
        clf = _fresh_classifier()
        label, _ = clf.predict(
            _buffer(upright_landmarks),
            phone_visible=False,
            sustained_head_down=False,
            sustained_sipping=True,
        )
        assert label != "sipping"

    def test_sustained_head_down_overrides_sipping_geometry(self, sipping_landmarks):
        # The decision tree checks all three phone branches BEFORE checking
        # sipping. So if the sustained-head-down signal is true, phone
        # wins even though the wrist-near-nose geometry would otherwise
        # have produced a sipping classification.
        clf = _fresh_classifier()
        label, _ = clf.predict(
            _buffer(sipping_landmarks),
            phone_visible=False,
            sustained_head_down=True,
            sustained_sipping=True,
        )
        assert label == "phone"


class TestPhoneOverridesTrainedModel:
    """
    Regression: the trained classifier was trained on 4 classes that don't
    include `phone`. If the override layer ever stops running, a held
    phone would silently get classified as at_desk by the trained model.
    """

    def test_phone_layer_runs_even_when_a_model_is_loaded(self, head_down_landmarks, monkeypatch):
        clf = _fresh_classifier()

        # Inject a fake trained model that would always say "at_desk".
        class StubModel:
            classes_ = ["at_desk", "sipping", "away"]

            def predict_proba(self, X):
                return [[1.0, 0.0, 0.0]]

        clf.model = StubModel()

        label, conf = clf.predict(
            _buffer(head_down_landmarks),
            phone_visible=True,
            sustained_head_down=False,
        )
        # The phone override layer must short-circuit *before* the trained
        # model gets a vote.
        assert label == "phone"
        assert conf >= 0.85

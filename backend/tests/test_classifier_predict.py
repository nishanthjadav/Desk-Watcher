"""
Tests for ActivityClassifier.predict().

The live classifier runs on the trained model's output, with two
guard rails:

  1. YOLO cross-check: a "phone" prediction is demoted to the model's
     next-best non-phone class if the phone detector sees nothing
     in frame.
  2. Confidence floor: if the model's top probability is below
     MODEL_CONF_FLOOR, fall back to "at_desk" rather than emit a
     low-confidence label.

The geometry short-circuits the classifier used to run (is_head_down,
wrists_low_and_close, is_sipping) were removed because they over-fired
on incidental matches (nose-scratch became sip, head-tilted typing
became phone). The trained model scores ~98% per-class on held-out
data, so we trust it.
"""
from __future__ import annotations

from classifier import ActivityClassifier


def _buffer(landmarks: list[float], n: int = 30) -> list[tuple[float, list[float]]]:
    """Build a frame buffer of n identical frames at timestamps 0..n-1."""
    return [(float(i), landmarks) for i in range(n)]


def _no_model_classifier() -> ActivityClassifier:
    """A classifier with no trained model — exercises the rule-based fallback."""
    return ActivityClassifier(model_path="/nonexistent/path/never/find.pkl")


def _stub_model_classifier(classes: list[str], proba: list[float]) -> ActivityClassifier:
    """A classifier whose trained model emits a fixed probability vector."""
    class StubModel:
        classes_ = classes

        def predict_proba(self, X):
            return [proba]

    clf = _no_model_classifier()
    clf.model = StubModel()
    return clf


# ── No-model fallback ─────────────────────────────────────────────────────

class TestNoModelFallback:
    """When no trained model is loaded, predict() falls through to a
    time-of-day default. Production should always have a model — this
    branch is a safety net for fresh installs and tests."""

    def test_no_model_returns_at_desk(self, upright_landmarks):
        clf = _no_model_classifier()
        label, _ = clf.predict(_buffer(upright_landmarks), phone_visible=False)
        assert label == "at_desk"


# ── Trained model passes through ──────────────────────────────────────────

class TestTrainedModelPassThrough:
    """When the model is confident and the YOLO check doesn't object,
    its prediction is what gets returned."""

    def test_confident_at_desk_returned_as_is(self, upright_landmarks):
        clf = _stub_model_classifier(
            ["at_desk", "away", "phone", "sipping"],
            [0.92, 0.02, 0.03, 0.03],
        )
        label, conf = clf.predict(_buffer(upright_landmarks), phone_visible=False)
        assert label == "at_desk"
        assert conf == 0.92

    def test_confident_sipping_returned_as_is(self, sipping_landmarks):
        clf = _stub_model_classifier(
            ["at_desk", "away", "phone", "sipping"],
            [0.10, 0.00, 0.05, 0.85],
        )
        label, conf = clf.predict(_buffer(sipping_landmarks), phone_visible=False)
        assert label == "sipping"
        assert conf == 0.85

    def test_confident_phone_returned_when_detector_agrees(self, head_down_landmarks):
        clf = _stub_model_classifier(
            ["at_desk", "away", "phone", "sipping"],
            [0.15, 0.00, 0.80, 0.05],
        )
        label, conf = clf.predict(_buffer(head_down_landmarks), phone_visible=True)
        assert label == "phone"
        assert conf == 0.80

    def test_legacy_stretching_label_normalized_to_at_desk(self, upright_landmarks):
        # Older 5-class models emit "stretching"; the live pipeline treats
        # it as at_desk so legacy artifacts don't crash anything downstream.
        clf = _stub_model_classifier(
            ["at_desk", "stretching"],
            [0.10, 0.90],
        )
        label, conf = clf.predict(_buffer(upright_landmarks), phone_visible=False)
        assert label == "at_desk"
        assert conf == 0.90


# ── YOLO phone cross-check ────────────────────────────────────────────────

class TestPhoneYoloGate:
    """A "phone" prediction is honored when YOLO sees a phone OR when the
    model is highly confident (the phone-out-of-frame case — the model has
    learned the pose of looking down at a phone in your lap). Otherwise
    we demote to the next-best non-phone class."""

    def test_low_conf_phone_demoted_when_detector_disagrees(self, head_down_landmarks):
        # Model picks phone with 0.65 — above the conf floor (0.55) but
        # below the OOF threshold (0.80). YOLO sees nothing. Should
        # demote to runner-up.
        clf = _stub_model_classifier(
            ["at_desk", "phone", "sipping"],
            [0.30, 0.65, 0.05],
        )
        label, conf = clf.predict(_buffer(head_down_landmarks), phone_visible=False)
        assert label == "at_desk"
        assert conf == 0.30

    def test_high_conf_phone_kept_even_when_detector_disagrees(self, head_down_landmarks):
        # Phone-out-of-frame case: model is highly confident (≥ 0.80)
        # that this is phone, but YOLO sees nothing because the phone
        # is in the user's lap. Trust the model.
        clf = _stub_model_classifier(
            ["at_desk", "phone", "sipping"],
            [0.10, 0.85, 0.05],
        )
        label, conf = clf.predict(_buffer(head_down_landmarks), phone_visible=False)
        assert label == "phone"
        assert conf == 0.85

    def test_phone_at_oof_threshold_passes_through(self, head_down_landmarks):
        # Exactly at the OOF threshold — should pass through, not demote.
        clf = _stub_model_classifier(
            ["at_desk", "phone"],
            [0.20, ActivityClassifier.PHONE_OOF_CONF_THRESHOLD],
        )
        label, _ = clf.predict(_buffer(head_down_landmarks), phone_visible=False)
        assert label == "phone"

    def test_phone_demotion_skips_phone_in_order(self):
        # Defensive: if there were ever two phone-like classes, demotion
        # must skip past any "phone" entry to reach a non-phone label.
        # (Today there's only one phone class; this just pins behavior.)
        clf = _stub_model_classifier(
            ["phone", "at_desk", "sipping"],
            [0.60, 0.30, 0.10],
        )
        label, _ = clf.predict(_buffer([0.0] * 99), phone_visible=False)
        assert label == "at_desk"

    def test_non_phone_predictions_are_unaffected_by_detector(self, upright_landmarks):
        # phone_visible should only affect the prediction when the model
        # picks phone. A "sipping" prediction stays sipping regardless.
        clf = _stub_model_classifier(
            ["at_desk", "phone", "sipping"],
            [0.20, 0.05, 0.75],
        )
        label_no_phone, _ = clf.predict(_buffer(upright_landmarks), phone_visible=False)
        label_phone, _ = clf.predict(_buffer(upright_landmarks), phone_visible=True)
        assert label_no_phone == "sipping"
        assert label_phone == "sipping"

    def test_low_conf_phone_kept_when_detector_confirms(self, head_down_landmarks):
        # Even at low (but above-floor) phone confidence, if YOLO sees
        # the phone we trust the model's call. The detector is the
        # ground truth for "there is a phone here."
        clf = _stub_model_classifier(
            ["at_desk", "phone", "sipping"],
            [0.30, 0.60, 0.10],
        )
        label, _ = clf.predict(_buffer(head_down_landmarks), phone_visible=True)
        assert label == "phone"


# ── Confidence floor ──────────────────────────────────────────────────────

class TestConfidenceFloor:
    """When the model is uncertain, default to at_desk rather than emit
    a low-confidence specific activity. "I don't know but you're in
    frame" is better than guessing phone or sip."""

    def test_below_floor_falls_back_to_at_desk(self, sipping_landmarks):
        # Top class is sipping at 0.40 — below the 0.55 floor.
        clf = _stub_model_classifier(
            ["at_desk", "away", "phone", "sipping"],
            [0.30, 0.05, 0.25, 0.40],
        )
        label, _ = clf.predict(_buffer(sipping_landmarks), phone_visible=False)
        assert label == "at_desk"

    def test_at_floor_passes_through(self, sipping_landmarks):
        # Exactly at the floor: should emit the model's choice, not fall back.
        clf = _stub_model_classifier(
            ["at_desk", "sipping"],
            [0.45, ActivityClassifier.MODEL_CONF_FLOOR],
        )
        label, conf = clf.predict(_buffer(sipping_landmarks), phone_visible=False)
        assert label == "sipping"
        assert conf == ActivityClassifier.MODEL_CONF_FLOOR

    def test_demoted_phone_can_still_be_below_floor(self, head_down_landmarks):
        # Phone demoted to at_desk runner-up which is itself below the
        # floor — we still return at_desk (both branches land on at_desk
        # but via different paths). The point is no low-conf "phone" leaks.
        clf = _stub_model_classifier(
            ["at_desk", "phone", "sipping"],
            [0.30, 0.50, 0.20],
        )
        label, _ = clf.predict(_buffer(head_down_landmarks), phone_visible=False)
        assert label == "at_desk"

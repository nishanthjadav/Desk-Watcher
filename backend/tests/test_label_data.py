"""
Tests for the labeling tool's data-layer helpers (ml/label_data.py).
The GUI itself isn't tested — OpenCV input is hard to drive headlessly —
but every state transition can be tested through the pure helpers:

  - CSV roundtrip: write labels, reload, verify equality
  - commit_range / clear_range / undo: label-array mutations
  - handle_label_key: the anchor-then-commit state machine
  - jump_to_label_boundary: navigation across label transitions
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from label_data import (
    ACTIVITIES,
    Frame,
    Session,
    clear_range,
    commit_range,
    handle_label_key,
    jump_to_label_boundary,
    load_csv,
    load_labels,
    save_labels,
    step_cursor,
    undo,
)


# ─── Fixtures ───────────────────────────────────────────────────────────────

def _make_csv(path: Path, n_frames: int = 20) -> None:
    """Write a CSV in the same shape collect_data.py produces."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        header = ["timestamp"] + [
            f"lm{i}_{ax}" for i in range(33) for ax in ("x", "y", "v")
        ]
        w.writerow(header)
        for i in range(n_frames):
            w.writerow([float(i) * 0.1] + [0.5] * 99)


@pytest.fixture
def session(tmp_path) -> Session:
    csv_path = tmp_path / "session.csv"
    _make_csv(csv_path, n_frames=20)
    frames = load_csv(csv_path)
    labels_path = csv_path.with_suffix(".labels.csv")
    return Session(
        csv_path=csv_path,
        labels_path=labels_path,
        frames=frames,
        labels=[None] * len(frames),
    )


# ─── load_csv ───────────────────────────────────────────────────────────────

class TestLoadCsv:
    def test_loads_all_frames(self, tmp_path):
        csv_path = tmp_path / "s.csv"
        _make_csv(csv_path, n_frames=7)
        frames = load_csv(csv_path)
        assert len(frames) == 7

    def test_frame_has_timestamp_and_99_landmarks(self, tmp_path):
        csv_path = tmp_path / "s.csv"
        _make_csv(csv_path, n_frames=3)
        frames = load_csv(csv_path)
        assert frames[0].timestamp == pytest.approx(0.0)
        assert frames[2].timestamp == pytest.approx(0.2)
        assert len(frames[0].landmarks) == 99

    def test_rejects_wrong_column_count(self, tmp_path):
        csv_path = tmp_path / "bad.csv"
        with open(csv_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["timestamp", "lm0_x"])
            w.writerow([0.0, 0.5])
        with pytest.raises(SystemExit):
            load_csv(csv_path)

    def test_rejects_missing_timestamp_header(self, tmp_path):
        csv_path = tmp_path / "bad.csv"
        with open(csv_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["wrong"] + ["x"] * 99)
            w.writerow([0.0] + [0.5] * 99)
        with pytest.raises(SystemExit):
            load_csv(csv_path)


# ─── load / save labels roundtrip ───────────────────────────────────────────

class TestLabelPersistence:
    def test_empty_sidecar_returns_all_none(self, tmp_path):
        labels = load_labels(tmp_path / "missing.labels.csv", n_frames=5)
        assert labels == [None] * 5

    def test_save_then_load_roundtrip(self, session):
        commit_range(session, 2, 7, "sipping")
        save_labels(session)
        reloaded = load_labels(session.labels_path, len(session.frames))
        assert reloaded == session.labels

    def test_unknown_labels_in_sidecar_are_dropped(self, session):
        # Hand-write a sidecar that mixes a bogus label in with valid ones.
        with open(session.labels_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["row", "label"])
            w.writerow([0, "at_desk"])
            w.writerow([1, "bogus_made_up_label"])
            w.writerow([2, "phone"])
        reloaded = load_labels(session.labels_path, len(session.frames))
        assert reloaded[0] == "at_desk"
        assert reloaded[1] is None       # bogus dropped
        assert reloaded[2] == "phone"

    def test_out_of_range_rows_are_dropped(self, session):
        with open(session.labels_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["row", "label"])
            w.writerow([5, "at_desk"])
            w.writerow([999, "phone"])    # out of range
            w.writerow([-1, "phone"])     # also out of range
        reloaded = load_labels(session.labels_path, len(session.frames))
        assert reloaded[5] == "at_desk"
        assert all(reloaded[i] is None for i in range(len(reloaded)) if i != 5)


# ─── commit_range / clear_range / undo ──────────────────────────────────────

class TestRangeOperations:
    def test_commit_labels_half_open_interval(self, session):
        commit_range(session, 3, 8, "sipping")
        for i in range(3, 8):
            assert session.labels[i] == "sipping"
        assert session.labels[2] is None
        assert session.labels[8] is None

    def test_commit_marks_session_dirty(self, session):
        assert session.dirty is False
        commit_range(session, 0, 2, "at_desk")
        assert session.dirty is True

    def test_empty_range_is_noop(self, session):
        commit_range(session, 5, 5, "sipping")
        assert all(lbl is None for lbl in session.labels)
        assert session.dirty is False

    def test_overlapping_commits_overwrite(self, session):
        commit_range(session, 0, 10, "at_desk")
        commit_range(session, 4, 7, "phone")
        assert session.labels[3] == "at_desk"
        assert session.labels[5] == "phone"
        assert session.labels[7] == "at_desk"

    def test_clear_range_removes_labels(self, session):
        commit_range(session, 0, 5, "at_desk")
        clear_range(session, 2, 4)
        assert session.labels[1] == "at_desk"
        assert session.labels[2] is None
        assert session.labels[3] is None
        assert session.labels[4] == "at_desk"

    def test_undo_reverts_last_commit(self, session):
        commit_range(session, 0, 5, "at_desk")
        commit_range(session, 5, 10, "sipping")
        undo(session)
        # The sipping commit is reverted; the at_desk one remains.
        for i in range(5):
            assert session.labels[i] == "at_desk"
        for i in range(5, 10):
            assert session.labels[i] is None

    def test_undo_with_empty_history_is_safe(self, session):
        undo(session)
        assert all(lbl is None for lbl in session.labels)

    def test_undo_chain(self, session):
        commit_range(session, 0, 5, "at_desk")
        commit_range(session, 0, 5, "phone")        # overwrite
        commit_range(session, 0, 5, "sipping")      # overwrite again
        assert session.labels[0] == "sipping"
        undo(session)
        assert session.labels[0] == "phone"
        undo(session)
        assert session.labels[0] == "at_desk"
        undo(session)
        assert session.labels[0] is None


# ─── handle_label_key — the anchor-then-commit state machine ────────────────

class TestAnchorThenCommit:
    def test_first_press_drops_anchor(self, session):
        session.cursor = 5
        handle_label_key(session, "at_desk")
        assert session.anchor == 5
        assert session.anchor_activity == "at_desk"
        # No commit happened yet.
        assert all(lbl is None for lbl in session.labels)

    def test_second_press_same_key_commits_range_inclusive(self, session):
        session.cursor = 5
        handle_label_key(session, "at_desk")
        session.cursor = 10
        handle_label_key(session, "at_desk")
        # Inclusive of the cursor: [5, 10] = 6 frames.
        for i in range(5, 11):
            assert session.labels[i] == "at_desk"
        assert session.labels[4] is None
        assert session.labels[11] is None
        # Anchor cleared.
        assert session.anchor is None
        assert session.anchor_activity is None

    def test_different_key_chains_a_new_anchor(self, session):
        session.cursor = 2
        handle_label_key(session, "at_desk")        # anchor @ 2
        session.cursor = 6
        handle_label_key(session, "sipping")        # commit at_desk[2,6], anchor sipping @ 6
        # The at_desk range was committed with at_desk activity, not sipping.
        for i in range(2, 7):
            assert session.labels[i] == "at_desk"
        assert session.anchor == 6
        assert session.anchor_activity == "sipping"

    def test_chain_a_full_workday_pattern(self, session):
        # Three transitions, four commits — the realistic pattern.
        session.cursor = 0
        handle_label_key(session, "at_desk")        # anchor @ 0
        session.cursor = 5
        handle_label_key(session, "sipping")        # commit at_desk[0,5], anchor sipping @ 5
        session.cursor = 7
        handle_label_key(session, "at_desk")        # commit sipping[5,7], anchor at_desk @ 7
        session.cursor = 15
        handle_label_key(session, "at_desk")        # commit at_desk[7,15], close anchor

        assert session.labels[:5] == ["at_desk"] * 5
        assert session.labels[5:7] == ["sipping"] * 2
        assert session.labels[7:16] == ["at_desk"] * 9
        assert session.anchor is None

    def test_backward_cursor_range_still_commits(self, session):
        # Drop anchor at frame 10, scrub backward to frame 3, press the
        # same key. The committed range should still be [3, 10].
        session.cursor = 10
        handle_label_key(session, "at_desk")
        session.cursor = 3
        handle_label_key(session, "at_desk")
        for i in range(3, 11):
            assert session.labels[i] == "at_desk"


# ─── Navigation ─────────────────────────────────────────────────────────────

class TestNavigation:
    def test_step_cursor_clamps_at_bounds(self, session):
        n = len(session.frames)
        session.cursor = 0
        step_cursor(session, -5)
        assert session.cursor == 0
        session.cursor = n - 1
        step_cursor(session, 10)
        assert session.cursor == n - 1

    def test_jump_to_next_label_boundary(self, session):
        # Layout: [None]*5 + [at_desk]*5 + [sipping]*5 + [None]*5
        commit_range(session, 5, 10, "at_desk")
        commit_range(session, 10, 15, "sipping")
        session.cursor = 0
        next_b = jump_to_label_boundary(session, +1)
        assert next_b == 5        # first labeled frame
        session.cursor = 5
        next_b = jump_to_label_boundary(session, +1)
        assert next_b == 10       # at_desk → sipping transition

    def test_jump_to_previous_label_boundary(self, session):
        commit_range(session, 5, 10, "at_desk")
        commit_range(session, 10, 15, "sipping")
        session.cursor = 14
        prev_b = jump_to_label_boundary(session, -1)
        assert prev_b == 10

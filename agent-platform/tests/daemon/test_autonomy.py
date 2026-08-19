from daemon.autonomy import AutonomyTracker


def test_starts_locked():
    t = AutonomyTracker()
    assert not t.is_unlocked("hermes", "research")


def test_unlocks_after_three_consecutive_clean_passes():
    t = AutonomyTracker(unlock_threshold=3)
    t.record_pass("hermes", "research", clean=True)
    t.record_pass("hermes", "research", clean=True)
    assert not t.is_unlocked("hermes", "research")
    t.record_pass("hermes", "research", clean=True)
    assert t.is_unlocked("hermes", "research")


def test_dirty_pass_resets_streak():
    t = AutonomyTracker(unlock_threshold=3)
    t.record_pass("hermes", "research", clean=True)
    t.record_pass("hermes", "research", clean=True)
    t.record_pass("hermes", "research", clean=False)
    t.record_pass("hermes", "research", clean=True)
    assert not t.is_unlocked("hermes", "research")  # only 1 clean since the reset


def test_classes_are_independent():
    t = AutonomyTracker(unlock_threshold=1)
    t.record_pass("hermes", "research", clean=True)
    assert t.is_unlocked("hermes", "research")
    assert not t.is_unlocked("hermes", "coding")
    assert not t.is_unlocked("claude-direct", "research")


def test_to_dict_from_dict_roundtrip_preserves_streaks_and_unlock_state():
    t = AutonomyTracker(unlock_threshold=3)
    t.record_pass("hermes", "research", clean=True)
    t.record_pass("hermes", "research", clean=True)
    t.record_pass("claude-direct", "cli", clean=True)

    restored = AutonomyTracker.from_dict(t.to_dict())

    assert restored.unlock_threshold == 3
    assert not restored.is_unlocked("hermes", "research")
    restored.record_pass("hermes", "research", clean=True)
    assert restored.is_unlocked("hermes", "research")
    assert not restored.is_unlocked("claude-direct", "cli")
    restored.record_pass("claude-direct", "cli", clean=True)
    restored.record_pass("claude-direct", "cli", clean=True)
    assert restored.is_unlocked("claude-direct", "cli")

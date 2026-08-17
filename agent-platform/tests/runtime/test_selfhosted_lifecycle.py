from runtime.selfhosted_lifecycle import should_stop_for_idle

def test_should_stop_when_idle_past_threshold():
    assert should_stop_for_idle(last_activity_ts=1000.0, now_ts=1000.0 + 16*60,
                                 idle_threshold_minutes=15) is True

def test_should_not_stop_when_within_threshold():
    assert should_stop_for_idle(last_activity_ts=1000.0, now_ts=1000.0 + 5*60,
                                 idle_threshold_minutes=15) is False

def test_should_not_stop_when_no_activity_recorded_yet():
    # Fail-closed the other direction: never seen activity means "just started",
    # not "idle forever" -- caller passes provisioning time as last_activity_ts.
    assert should_stop_for_idle(last_activity_ts=1000.0, now_ts=1000.0,
                                 idle_threshold_minutes=15) is False

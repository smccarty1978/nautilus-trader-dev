from collectors.collector_v2.aggregator import CompletedMinuteFiveMinuteAggregator, TimeframeAggregator


NS = 1_000_000_000


def _feed(aggregator, seconds):
    for second in seconds:
        aggregator.on_1s_bar(second * NS, 100.0, 101.0, 99.0, 100.0, 10.0)


def test_full_5m_coverage_is_promoted_at_its_completed_availability_boundary():
    completed = []
    aggregator = TimeframeAggregator(lambda tf, bucket: completed.append((tf, bucket)), timeframes=("5m",))
    _feed(aggregator, range(300))
    aggregator.finalize_through(300 * NS)
    assert [(tf, bucket.close_ts) for tf, bucket in completed] == [("5m", 300 * NS)]


def test_partial_5m_bucket_is_discarded_and_reported_not_promoted():
    completed = []
    aggregator = TimeframeAggregator(lambda tf, bucket: completed.append((tf, bucket)), timeframes=("5m",))
    _feed(aggregator, (second for second in range(300) if second != 100))
    aggregator.finalize_through(300 * NS)
    assert completed == []
    assert aggregator.consume_incomplete_close_ts("5m") == [300 * NS]


def test_five_consecutive_completed_1m_parents_publish_one_completed_5m_bar():
    completed = []
    aggregator = CompletedMinuteFiveMinuteAggregator(lambda tf, bucket: completed.append((tf, bucket)))
    for minute in range(5):
        aggregator.on_completed_1m(minute * 60 * NS, 100.0 + minute, 102.0 + minute,
                                   99.0 + minute, 101.0 + minute, 1000.0)
    assert [(tf, bucket.open_ts, bucket.close_ts) for tf, bucket in completed] == [("5m", 0, 300 * NS)]
    assert completed[0][1].high == 106.0


def test_missing_completed_1m_parent_discards_five_minute_bucket():
    completed = []
    aggregator = CompletedMinuteFiveMinuteAggregator(lambda tf, bucket: completed.append((tf, bucket)))
    for minute in (0, 1, 3, 4):
        aggregator.on_completed_1m(minute * 60 * NS, 100.0, 101.0, 99.0, 100.0, 1000.0)
    aggregator.on_completed_1m(5 * 60 * NS, 100.0, 101.0, 99.0, 100.0, 1000.0)
    assert completed == []
    assert aggregator.consume_incomplete_close_ts() == [300 * NS]

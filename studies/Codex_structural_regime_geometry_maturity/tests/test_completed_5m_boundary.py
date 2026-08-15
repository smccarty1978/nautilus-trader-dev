from collectors.collector_v2.aggregator import TimeframeAggregator


def test_final_completed_1s_publishes_5m_at_its_availability_timestamp():
    completed = []
    aggregator = TimeframeAggregator(lambda timeframe, bucket: completed.append((timeframe, bucket)), timeframes=("5m",))
    # This is the final 1s bar in [0, 300s): its open is 299s and it is known at 300s.
    aggregator.on_1s_bar(299_000_000_000, 100.0, 101.0, 99.0, 100.5, 10.0)
    aggregator.finalize_through(300_000_000_000)
    assert len(completed) == 1
    timeframe, bucket = completed[0]
    assert timeframe == "5m"
    assert bucket.close_ts == 300_000_000_000


def test_finalization_does_not_publish_a_forming_bucket():
    completed = []
    aggregator = TimeframeAggregator(lambda timeframe, bucket: completed.append((timeframe, bucket)), timeframes=("5m",))
    aggregator.on_1s_bar(299_000_000_000, 100.0, 101.0, 99.0, 100.5, 10.0)
    aggregator.finalize_through(299_999_999_999)
    assert completed == []

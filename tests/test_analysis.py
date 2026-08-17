from xion import analysis
from xion.config import Config


def test_rsrp_quality_bands():
    assert analysis.rsrp_quality(-60) == "Excellent"
    assert analysis.rsrp_quality(-80) == "Good"
    assert analysis.rsrp_quality(-100) == "Fair"
    assert analysis.rsrp_quality(-115) == "Poor"
    assert analysis.rsrp_quality(-125) == "Very Poor"


def test_analyze_signal_strength(sample_df):
    summary = analysis.analyze_signal_strength(sample_df)
    assert summary.total_records == 6
    assert summary.analyzed_records == 6
    assert summary.strongest_rsrp == -80
    assert summary.weakest_rsrp == -130


def test_top_cells_by_signal(sample_df):
    top = analysis.top_cells_by_signal(sample_df, top_n=2)
    assert len(top) <= 2
    assert top.iloc[0]["avg_rsrp"] >= top.iloc[-1]["avg_rsrp"]


def test_network_type_distribution(sample_df):
    dist = analysis.network_type_distribution(sample_df)
    assert dist["LTE"] == 5
    assert dist["3G"] == 1


def test_time_series_trend_daily(sample_df):
    trend = analysis.time_series_trend(sample_df, freq="D")
    assert len(trend) == 2


def test_detect_anomalies_flags_very_poor_signal(sample_df):
    cfg = Config()
    anomalies = analysis.detect_anomalies(sample_df, cfg)
    kinds = [a.kind for a in anomalies]
    assert "signal" in kinds


def test_detect_anomalies_flags_repeated_missed_calls(sample_df):
    cfg = Config()
    cfg.missed_call_repeat_count = 3
    cfg.missed_call_window_hours = 48
    anomalies = analysis.detect_anomalies(sample_df, cfg)
    assert any(a.kind == "missed_calls" for a in anomalies)


def test_detect_anomalies_empty_df_returns_nothing():
    import pandas as pd
    cfg = Config()
    assert analysis.detect_anomalies(pd.DataFrame(), cfg) == []


def _duration_df(durations, call_types=None):
    import pandas as pd
    n = len(durations)
    call_types = call_types or ["OUTGOING"] * n
    return pd.DataFrame({
        "timestamp": ["2026-01-01 08:00:00"] * n,
        "call_type": call_types,
        "phone_number": ["+10000000001"] * n,
        "duration": durations,
        "cell_id": ["101"] * n,
        "lac": ["20"] * n,
        "mcc": ["310"] * n,
        "mnc": ["260"] * n,
        "radio_type": ["LTE"] * n,
        "rsrp": [None] * n,
    })


def test_detect_duration_outliers_flags_far_above_average():
    df = _duration_df([30, 40, 35, 3000])
    outliers = analysis.detect_duration_outliers(df, multiplier=3.0)
    assert len(outliers) == 1
    assert outliers.iloc[0]["duration"] == 3000


def test_detect_duration_outliers_ignores_zero_duration_calls_in_baseline():
    # Missed/rejected calls (duration 0) shouldn't drag the baseline down
    # and cause ordinary connected calls to look like outliers.
    df = _duration_df([60, 65, 70, 0, 0, 0],
                       call_types=["OUTGOING", "OUTGOING", "OUTGOING",
                                   "MISSED", "MISSED", "MISSED"])
    outliers = analysis.detect_duration_outliers(df, multiplier=3.0)
    assert outliers.empty


def test_detect_duration_outliers_needs_at_least_two_connected_calls():
    df = _duration_df([500])
    assert analysis.detect_duration_outliers(df).empty


def test_detect_duration_outliers_empty_df():
    df = _duration_df([])
    assert analysis.detect_duration_outliers(df).empty


def test_weak_signal_readings_returns_weakest_first(sample_df):
    weak = analysis.weak_signal_readings(sample_df, -120)
    assert len(weak) == 3
    assert weak.iloc[0]["rsrp"] == -130


def test_weak_signal_readings_empty_when_none_below_threshold(sample_df):
    weak = analysis.weak_signal_readings(sample_df, -200)
    assert weak.empty


def test_detect_anomalies_flags_duration_outliers():
    cfg = Config()
    df = _duration_df([30, 40, 35, 3000])
    anomalies = analysis.detect_anomalies(df, cfg)
    kinds = [a.kind for a in anomalies]
    assert "duration_outlier" in kinds


def test_detect_duration_outliers_missing_column_returns_empty():
    import pandas as pd
    df = pd.DataFrame({"rsrp": [-80, -90]})
    assert analysis.detect_duration_outliers(df).empty


def test_detect_duration_outliers_non_numeric_durations_dont_crash():
    import pandas as pd
    df = pd.DataFrame({"duration": ["abc", "xyz", "9999"],
                        "call_type": ["OUTGOING"] * 3, "rsrp": [None] * 3})
    assert analysis.detect_duration_outliers(df).empty


def test_weak_signal_readings_missing_column_returns_empty():
    import pandas as pd
    df = pd.DataFrame({"duration": [10, 20]})
    assert analysis.weak_signal_readings(df, -100).empty


def test_fully_empty_dataframe_no_columns_does_not_crash():
    import pandas as pd
    df = pd.DataFrame()
    assert analysis.detect_duration_outliers(df).empty
    assert analysis.weak_signal_readings(df, -100).empty


def test_display_columns_narrows_to_requested_set(sample_df):
    narrowed = analysis.display_columns(sample_df, analysis.WEAK_SIGNAL_DISPLAY_COLUMNS)
    assert list(narrowed.columns) == analysis.WEAK_SIGNAL_DISPLAY_COLUMNS


def test_display_columns_skips_missing_columns_instead_of_crashing():
    import pandas as pd
    df = pd.DataFrame({"timestamp": ["2026-01-01"], "rsrp": [-90]})
    # "phone_number", "cell_id", "radio_type" aren't present — should be dropped, not raise
    narrowed = analysis.display_columns(df, analysis.WEAK_SIGNAL_DISPLAY_COLUMNS)
    assert list(narrowed.columns) == ["timestamp", "rsrp"]

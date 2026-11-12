from datetime import date, timedelta

import pytest

from assistant_agent.analysis import (
    dimension_contribution,
    period_compare,
    structure_effect,
)
from assistant_agent.forecast import trend_forecast
from assistant_agent.models import json_safe


def daily_rows(start: str, days: int, value_fn, *, dims: dict[str, str] | None = None):
    begin = date.fromisoformat(start)
    rows = []
    for offset in range(days):
        row = {"order_date": (begin + timedelta(days=offset)).isoformat()}
        row.update(dims or {})
        row["total_amount"] = float(value_fn(offset))
        rows.append(row)
    return rows


def test_period_compare_with_dimension():
    rows = [
        {"order_date": date(2026, 1, 1), "region": "east", "total_amount": 100.0},
        {"order_date": date(2026, 1, 2), "region": "west", "total_amount": 200.0},
        {"order_date": date(2026, 2, 1), "region": "east", "total_amount": 150.0},
        {"order_date": date(2026, 2, 2), "region": "west", "total_amount": 180.0},
    ]
    result = period_compare(
        rows,
        period_col="order_date",
        value_col="total_amount",
        base_start="2026-01-01",
        base_end="2026-01-28",
        current_start="2026-02-01",
        current_end="2026-02-28",
        dimensions=["region"],
    )
    assert result.basis == "total"
    assert result.rows[0]["member"] == "east"
    assert result.rows[0]["delta"] == 50.0
    assert result.rows[0]["contribution_pct"] == 166.6667
    assert result.rows[1]["member"] == "west"
    assert result.rows[1]["delta"] == -20.0
    assert result.rows[1]["contribution_pct"] == -66.6667


def test_period_compare_equal_windows_use_total_basis():
    rows = daily_rows("2026-01-01", 10, lambda i: 100 + i) + daily_rows(
        "2026-02-01", 10, lambda i: 120 + i
    )
    result = period_compare(
        rows,
        period_col="order_date",
        value_col="total_amount",
        base_start="2026-01-01",
        base_end="2026-01-10",
        current_start="2026-02-01",
        current_end="2026-02-10",
    )
    assert result.basis == "total"
    assert result.rows[0]["base"] == 1045.0
    assert result.rows[0]["current"] == 1245.0
    assert result.rows[0]["delta"] == 200.0
    assert result.significance is not None
    assert result.significance["significant"] is True
    assert result.significance["p_value"] > 0


def test_period_compare_unequal_windows_switch_to_daily_average():
    rows = daily_rows("2026-01-01", 31, lambda i: 100) + daily_rows(
        "2026-02-01", 28, lambda i: 100
    )
    result = period_compare(
        rows,
        period_col="order_date",
        value_col="total_amount",
        base_start="2026-01-01",
        base_end="2026-01-31",
        current_start="2026-02-01",
        current_end="2026-02-28",
    )
    assert result.basis == "daily_avg"
    assert result.base_stats["total"] == 3100.0
    assert result.current_stats["total"] == 2800.0
    # 每天都是 100，日均口径下两期完全相同，总量差只是天数差
    assert result.rows[0]["delta"] == 0.0
    assert result.rows[0]["base_total"] == 3100.0
    assert result.rows[0]["current_total"] == 2800.0


def test_period_compare_names_largest_decline_not_smallest():
    rows = (
        daily_rows("2026-01-01", 5, lambda i: 1000, dims={"region": "east"})
        + daily_rows("2026-01-01", 5, lambda i: 100, dims={"region": "west"})
        + daily_rows("2026-02-01", 5, lambda i: 900, dims={"region": "east"})
        + daily_rows("2026-02-01", 5, lambda i: 90, dims={"region": "west"})
    )
    result = period_compare(
        rows,
        period_col="order_date",
        value_col="total_amount",
        base_start="2026-01-01",
        base_end="2026-01-05",
        current_start="2026-02-01",
        current_end="2026-02-05",
        dimensions=["region"],
    )
    assert all(row["delta"] < 0 for row in result.rows)
    assert result.rows[0]["member"] == "east"
    assert "影响最大的成员是 east" in result.summary


def test_period_compare_multi_dimension_cross_grouping():
    rows = []
    for region in ("east", "west"):
        for category in ("A", "B"):
            rows += daily_rows(
                "2026-01-01", 3, lambda i: 100, dims={"region": region, "category": category}
            )
            rows += daily_rows(
                "2026-02-01",
                3,
                lambda i: 150 if (region, category) == ("east", "A") else 100,
                dims={"region": region, "category": category},
            )
    result = period_compare(
        rows,
        period_col="order_date",
        value_col="total_amount",
        base_start="2026-01-01",
        base_end="2026-01-03",
        current_start="2026-02-01",
        current_end="2026-02-03",
        dimensions=["region", "category"],
    )
    assert result.dimensions == ["region", "category"]
    assert len(result.rows) == 4
    assert result.rows[0]["member"] == "east / A"
    assert result.rows[0]["delta"] == 150.0
    assert result.rows[0]["contribution_pct"] == 100.0


def test_dimension_contribution_warns_on_zero_delta():
    rows = [
        {"order_date": "2026-01-01", "region": "east", "total_amount": 100},
        {"order_date": "2026-02-01", "region": "east", "total_amount": 100},
    ]
    result = dimension_contribution(
        rows,
        dimensions=["region"],
        value_col="total_amount",
        period_col="order_date",
        base_start="2026-01-01",
        base_end="2026-01-28",
        current_start="2026-02-01",
        current_end="2026-02-28",
    )
    assert result.basis == "total"
    assert result.total_delta == 0
    assert any("接近 0" in warning for warning in result.warnings)


def test_dimension_contribution_concentration_and_offsetting():
    rows = (
        daily_rows("2026-01-01", 4, lambda i: 100, dims={"region": "east"})
        + daily_rows("2026-01-01", 4, lambda i: 100, dims={"region": "west"})
        + daily_rows("2026-02-01", 4, lambda i: 300, dims={"region": "east"})
        + daily_rows("2026-02-01", 4, lambda i: 0, dims={"region": "west"})
    )
    result = dimension_contribution(
        rows,
        dimensions=["region"],
        value_col="total_amount",
        period_col="order_date",
        base_start="2026-01-01",
        base_end="2026-01-04",
        current_start="2026-02-01",
        current_end="2026-02-04",
    )
    assert result.total_delta == 400.0
    assert result.offsetting["positive_delta"] == 800.0
    assert result.offsetting["negative_delta"] == -400.0
    assert result.offsetting["offset_ratio"] == 0.6667
    assert any("抵消" in warning for warning in result.warnings)
    assert result.concentration["member_count"] == 2
    assert result.concentration["top1_abs_share_pct"] == 66.6667
    # 2 个成员 2:1 只是「较集中」，达不到主导
    assert result.concentration["top1_excess_pp"] == 16.6667
    assert result.concentration["verdict"] == "较集中"
    assert result.rows[0]["base_share_pct"] == 50.0
    assert result.rows[0]["current_share_pct"] == 100.0


def test_concentration_does_not_flag_balanced_two_members_as_concentrated():
    # 实测踩过：两个成员贡献 51% / 49% 时，Top1 过了 40% 的绝对阈值会被误判为「较集中」
    rows = (
        daily_rows("2026-01-01", 10, lambda i: 1000, dims={"region": "east"})
        + daily_rows("2026-01-01", 10, lambda i: 1000, dims={"region": "west"})
        + daily_rows("2026-02-01", 10, lambda i: 1018, dims={"region": "east"})
        + daily_rows("2026-02-01", 10, lambda i: 983, dims={"region": "west"})
    )
    result = dimension_contribution(
        rows,
        dimensions=["region"],
        value_col="total_amount",
        period_col="order_date",
        base_start="2026-01-01",
        base_end="2026-01-10",
        current_start="2026-02-01",
        current_end="2026-02-10",
    )
    assert result.concentration["top1_abs_share_pct"] == 51.4286
    assert result.concentration["verdict"] == "较分散，属普遍性变化"


def test_dimension_contribution_multi_dim_adds_ranking_without_extra_rows():
    rows = []
    for region in ("east", "west"):
        for category in ("A", "B"):
            rows += daily_rows(
                "2026-01-01", 3, lambda i: 100, dims={"region": region, "category": category}
            )
            rows += daily_rows(
                "2026-02-01",
                3,
                lambda i: 200 if region == "east" else 100,
                dims={"region": region, "category": category},
            )
    result = dimension_contribution(
        rows,
        dimensions=["region", "category"],
        value_col="total_amount",
        period_col="order_date",
        base_start="2026-01-01",
        base_end="2026-01-03",
        current_start="2026-02-01",
        current_end="2026-02-03",
    )
    assert len(result.rows) == 4
    ranking = {item["dimension"]: item for item in result.dimension_ranking}
    assert set(ranking) == {"region", "category"}
    assert ranking["region"]["top1_abs_share_pct"] == 100.0
    assert ranking["category"]["top1_abs_share_pct"] == 50.0
    assert "region" in result.summary


def test_dimension_contribution_requires_dimension():
    with pytest.raises(ValueError, match="至少需要一个分析维度"):
        dimension_contribution(
            [],
            dimensions=[],
            value_col="total_amount",
            period_col="order_date",
            base_start="2026-01-01",
            base_end="2026-01-31",
            current_start="2026-02-01",
            current_end="2026-02-28",
        )


def test_structure_effect_pure_efficiency():
    rows = [
        {"order_date": "2026-01-01", "category": "A", "amount": 50, "count": 100},
        {"order_date": "2026-01-01", "category": "B", "amount": 30, "count": 100},
        {"order_date": "2026-02-01", "category": "A", "amount": 80, "count": 100},
        {"order_date": "2026-02-01", "category": "B", "amount": 20, "count": 100},
    ]
    result = structure_effect(
        rows,
        dimensions=["category"],
        numerator_col="amount",
        denominator_col="count",
        period_col="order_date",
        base_start="2026-01-01",
        base_end="2026-01-31",
        current_start="2026-02-01",
        current_end="2026-02-28",
    )
    assert result.structure_effect == 0
    assert result.efficiency_effect == 0.1
    assert result.interaction_effect == 0
    assert result.total_delta == 0.1
    assert result.residual == 0
    assert result.dominant["term"] == "efficiency"
    assert result.dominant["abs_share_pct"] == 100.0


def test_structure_effect_mix_shift():
    rows = [
        {"order_date": "2026-01-01", "category": "A", "amount": 50, "count": 100},
        {"order_date": "2026-01-01", "category": "B", "amount": 30, "count": 100},
        {"order_date": "2026-02-01", "category": "A", "amount": 60, "count": 150},
        {"order_date": "2026-02-01", "category": "B", "amount": 40, "count": 100},
    ]
    result = structure_effect(
        rows,
        dimensions=["category"],
        numerator_col="amount",
        denominator_col="count",
        period_col="order_date",
        base_start="2026-01-01",
        base_end="2026-01-31",
        current_start="2026-02-01",
        current_end="2026-02-28",
    )
    assert result.total_delta == 0
    assert result.structure_effect == 0.02
    assert result.efficiency_effect == 0
    assert result.interaction_effect == -0.02
    assert result.residual == 0
    assert result.dominant["term"] in {"structure", "interaction"}
    assert {row["member"] for row in result.rows} == {"A", "B"}
    assert all("weight_delta_pp" in row for row in result.rows)


def test_structure_effect_multi_dimension():
    rows = []
    for region in ("east", "west"):
        for category in ("A", "B"):
            rows.append(
                {
                    "order_date": "2026-01-01",
                    "region": region,
                    "category": category,
                    "amount": 100,
                    "count": 100,
                }
            )
            rows.append(
                {
                    "order_date": "2026-02-01",
                    "region": region,
                    "category": category,
                    "amount": 200 if category == "A" else 100,
                    "count": 100,
                }
            )
    result = structure_effect(
        rows,
        dimensions=["region", "category"],
        numerator_col="amount",
        denominator_col="count",
        period_col="order_date",
        base_start="2026-01-01",
        base_end="2026-01-31",
        current_start="2026-02-01",
        current_end="2026-02-28",
    )
    assert result.dimensions == ["region", "category"]
    assert len(result.rows) == 4
    assert result.rows[0]["member"] == "east / A"
    assert abs(result.residual) < 1e-9


def forecast_rows(days: int = 60, *, start: str = "2026-01-01"):
    import math

    return daily_rows(
        start,
        days,
        lambda i: 1000 + 5 * i + 120 * math.sin(i * 2 * math.pi / 7) + (i % 3) * 7,
    )


def test_trend_forecast_recovers_trend_and_seasonality():
    result = trend_forecast(
        forecast_rows(60),
        period_col="order_date",
        value_col="total_amount",
        start="2026-01-01",
        end="2026-03-01",
        horizon_days=7,
    )
    assert result.observed_days == 60
    assert result.coverage_pct == 100.0
    assert len(result.forecast) == 7
    assert result.forecast[0]["date"] == "2026-03-02"
    assert result.trend["significant"] is True
    assert result.trend["slope_per_day"] > 0
    assert result.trend["p_value"] > 0
    assert result.decomposition["available"] is True
    assert result.decomposition["seasonal_strength"] > 0.5
    assert result.backtest["available"] is True
    assert result.backtest["best"] == "model"
    assert result.interval["level"] == 0.95
    assert result.interval["downside_width"] >= 0
    assert result.interval["upside_width"] >= 0
    assert result.interval["skew_ratio"] > 0
    for row in result.forecast:
        assert row["lower"] <= row["yhat"] <= row["upper"]
    assert result.forecast_total == pytest.approx(
        sum(row["yhat"] for row in result.forecast), abs=0.05
    )
    assert len(result.history_tail) == 30
    assert result.assumptions


def test_trend_forecast_clamps_horizon():
    result = trend_forecast(
        forecast_rows(30),
        period_col="order_date",
        value_col="total_amount",
        start="2026-01-01",
        end="2026-01-30",
        horizon_days=9999,
    )
    assert result.horizon_days == 365
    assert len(result.forecast) == 365


def test_trend_forecast_refuses_short_history():
    result = trend_forecast(
        forecast_rows(10),
        period_col="order_date",
        value_col="total_amount",
        start="2026-01-01",
        end="2026-01-10",
        horizon_days=7,
    )
    assert result.forecast == []
    assert result.observed_days == 10
    assert "不足" in result.summary or "只有" in result.summary


def test_trend_forecast_refuses_low_coverage():
    rows = forecast_rows(60)[::4]
    result = trend_forecast(
        rows,
        period_col="order_date",
        value_col="total_amount",
        start="2026-01-01",
        end="2026-03-01",
        horizon_days=7,
    )
    assert result.forecast == []
    assert result.coverage_pct < 50
    assert any("缺失日过多" in warning for warning in result.warnings)


def test_trend_forecast_constant_series_needs_no_model():
    result = trend_forecast(
        daily_rows("2026-01-01", 30, lambda i: 500),
        period_col="order_date",
        value_col="total_amount",
        start="2026-01-01",
        end="2026-01-30",
        horizon_days=5,
    )
    assert len(result.forecast) == 5
    assert all(row["yhat"] == 500 for row in result.forecast)
    assert all(row["lower"] == row["upper"] == 500 for row in result.forecast)
    assert any("方差为 0" in warning for warning in result.warnings)


def test_trend_forecast_discloses_interpolated_gaps():
    rows = [row for i, row in enumerate(forecast_rows(40)) if i % 5 != 0]
    result = trend_forecast(
        rows,
        period_col="order_date",
        value_col="total_amount",
        start="2026-01-01",
        end="2026-02-09",
        horizon_days=7,
    )
    assert result.observed_days == 32
    assert result.expected_days == 40
    assert len(result.forecast) == 7
    assert any("插值" in warning for warning in result.warnings)


def test_json_safe():
    assert json_safe(float("nan")) is None
    assert json_safe(date(2026, 1, 1)) == "2026-01-01"
    assert json_safe({"a": 1}) == {"a": 1}
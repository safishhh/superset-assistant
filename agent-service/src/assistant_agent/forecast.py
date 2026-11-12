from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.seasonal import STL

from .analysis import EPSILON, _frame, _round, _round_sig, _slice
from .models import TrendForecastResult

SEASONAL_PERIOD = 7
MIN_HISTORY_DAYS = 14
SEASONAL_MIN_DAYS = 21
HOLDOUT_DAYS = 7
HISTORY_TAIL_DAYS = 30
INTERVAL_LEVEL = 0.95
SIMULATIONS = 1000
MIN_COVERAGE_PCT = 50.0
ASSUMPTIONS = [
    "历史窗口的趋势与周内季节结构在外推期保持不变",
    "未纳入节假日、促销、政策等外部事件，事件期预测会失真",
    "区间由历史残差自助模拟得到，不包含模型误设与口径变更的风险",
]


def _daily_series(
    rows: list[dict[str, Any]],
    period_col: str,
    value_col: str,
    start: str,
    end: str,
) -> tuple[pd.Series, int, int]:
    frame = _frame(rows, period_col, [value_col])
    part = _slice(frame, period_col, start, end)
    expected = (pd.Timestamp(end) - pd.Timestamp(start)).days + 1
    if part.empty:
        return pd.Series(dtype="float64"), expected, 0
    daily = part.groupby(period_col)[value_col].sum().sort_index()
    return daily, expected, int(daily.shape[0])


def _regular(daily: pd.Series, start: str, end: str) -> tuple[pd.Series, int]:
    """补齐日历频率：缺失日按时间线性插值，仅供建模，数量与覆盖度如实披露。"""
    index = pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="D")
    series = daily.reindex(index)
    gaps = int(series.isna().sum())
    if gaps:
        series = series.interpolate(method="time").ffill().bfill()
    return series.astype(float), gaps


def _trend_stats(series: pd.Series) -> dict[str, Any]:
    if series.shape[0] < 3:
        return {"available": False}
    x = np.arange(series.shape[0], dtype=float)
    y = series.to_numpy(dtype=float)
    fit = stats.linregress(x, y)
    r2 = float(fit.rvalue) ** 2
    p_value = float(fit.pvalue)
    slope = float(fit.slope)
    significant = math.isfinite(p_value) and p_value < 0.05
    if not significant:
        verdict = "趋势不显著，外推主要依赖季节与均值"
    elif slope > 0:
        verdict = "存在显著上升趋势"
    else:
        verdict = "存在显著下降趋势"
    return {
        "available": True,
        "slope_per_day": _round(slope, 6),
        "intercept": _round(float(fit.intercept), 4),
        "slope_stderr": _round(float(fit.stderr), 6),
        "r2": _round(r2, 6),
        "p_value": _round_sig(p_value),
        "significant": significant,
        "verdict": verdict,
        "method": "最小二乘线性回归（scipy.stats.linregress）",
    }


def _decomposition(series: pd.Series) -> dict[str, Any]:
    """STL 分解给出趋势/季节强度（Hyndman 口径：1 - Var(残差)/Var(残差+分量)）。"""
    if series.shape[0] < 2 * SEASONAL_PERIOD + 1:
        return {
            "available": False,
            "reason": f"历史不足 {2 * SEASONAL_PERIOD + 1} 天，无法做周期为 7 的 STL 分解",
        }
    result = STL(series, period=SEASONAL_PERIOD, robust=True).fit()
    resid = np.asarray(result.resid, dtype=float)
    seasonal = np.asarray(result.seasonal, dtype=float)
    trend = np.asarray(result.trend, dtype=float)
    var_resid = float(np.var(resid))

    def strength(component: np.ndarray) -> float | None:
        denominator = float(np.var(component + resid))
        if denominator < EPSILON:
            return None
        return max(0.0, min(1.0, 1 - var_resid / denominator))

    return {
        "available": True,
        "method": f"STL（周期 {SEASONAL_PERIOD} 天，robust）",
        "trend_strength": _round(strength(trend), 6),
        "seasonal_strength": _round(strength(seasonal), 6),
        "seasonal_amplitude": _round(float(np.max(seasonal) - np.min(seasonal)), 4),
        "residual_std": _round(float(np.std(resid, ddof=1)), 4),
    }


def _fit(series: pd.Series):
    seasonal = "add" if series.shape[0] >= SEASONAL_MIN_DAYS else None
    model = ExponentialSmoothing(
        series,
        trend="add",
        damped_trend=True,
        seasonal=seasonal,
        seasonal_periods=SEASONAL_PERIOD if seasonal else None,
        initialization_method="estimated",
    )
    return model.fit(), seasonal


def _mape(actual: np.ndarray, predicted: np.ndarray) -> float | None:
    if actual.shape[0] == 0:
        return None
    denominator = np.maximum(np.abs(actual), EPSILON)
    return float(np.mean(np.abs(actual - predicted) / denominator) * 100)


def _backtest(series: pd.Series) -> dict[str, Any]:
    n = series.shape[0]
    holdout = min(HOLDOUT_DAYS, n // 4)
    if holdout < 3 or n - holdout < MIN_HISTORY_DAYS:
        return {
            "available": False,
            "reason": f"历史 {n} 天太短，留出回测至少需要 {MIN_HISTORY_DAYS + 3} 天",
        }
    train = series.iloc[:-holdout]
    actual = series.iloc[-holdout:].to_numpy(dtype=float)
    fitted, _ = _fit(train)
    predicted = np.asarray(fitted.forecast(holdout), dtype=float)
    model_mape = _mape(actual, predicted)
    last = float(train.iloc[-1])
    naive_mape = _mape(actual, np.full(holdout, last))
    seasonal_naive_mape = None
    if train.shape[0] >= SEASONAL_PERIOD:
        seasonal_pred = np.array(
            [
                float(train.iloc[-SEASONAL_PERIOD + (i % SEASONAL_PERIOD)])
                for i in range(holdout)
            ]
        )
        seasonal_naive_mape = _mape(actual, seasonal_pred)
    candidates = {"model": model_mape, "naive_last": naive_mape}
    if seasonal_naive_mape is not None:
        candidates["seasonal_naive"] = seasonal_naive_mape
    best = min(
        (key for key, value in candidates.items() if value is not None),
        key=lambda key: candidates[key],
        default=None,
    )
    labels = {
        "model": "Holt-Winters",
        "naive_last": "朴素法（沿用最后一天）",
        "seasonal_naive": "季节朴素法（沿用上周同日）",
    }
    if best == "model":
        verdict = "模型优于朴素基线，预测可作参考"
    else:
        verdict = f"模型不如{labels.get(best, '基线')}，预测只作粗略参考"
    return {
        "available": True,
        "holdout_days": holdout,
        "train_days": int(train.shape[0]),
        "model_mape_pct": _round(model_mape, 4),
        "naive_last_mape_pct": _round(naive_mape, 4),
        "seasonal_naive_mape_pct": _round(seasonal_naive_mape, 4),
        "best": best,
        "best_label": labels.get(best or "", ""),
        "verdict": verdict,
        "method": "留出最后 N 天，比较 MAPE（平均绝对百分比误差）",
    }


def _interval(
    fitted: Any, horizon: int, non_negative: bool
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """自助模拟预测分布取分位数，不假设残差正态。"""
    alpha = 1 - INTERVAL_LEVEL
    try:
        simulated = fitted.simulate(
            horizon,
            anchor="end",
            repetitions=SIMULATIONS,
            random_errors="bootstrap",
        )
        paths = np.asarray(simulated, dtype=float)
        if paths.ndim == 1:
            paths = paths.reshape(horizon, -1)
        lower = np.quantile(paths, alpha / 2, axis=1)
        upper = np.quantile(paths, 1 - alpha / 2, axis=1)
        method = f"残差自助模拟 {SIMULATIONS} 次取 {INTERVAL_LEVEL:.0%} 分位区间"
    except Exception:
        resid = np.asarray(fitted.resid, dtype=float)
        sigma = float(np.std(resid, ddof=1)) if resid.size > 2 else 0.0
        steps = np.arange(1, horizon + 1, dtype=float)
        width = stats.norm.ppf(1 - alpha / 2) * sigma * np.sqrt(steps)
        point = np.asarray(fitted.forecast(horizon), dtype=float)
        lower = point - width
        upper = point + width
        method = (
            f"残差正态近似（σ={sigma:.4f}，随步长按 √h 放宽）"
            f"取 {INTERVAL_LEVEL:.0%} 区间"
        )
    clamped = False
    if non_negative:
        clamped = bool(np.any(lower < 0))
        lower = np.maximum(lower, 0.0)
    center = np.asarray(fitted.forecast(horizon), dtype=float)
    downside = float(np.mean(center - lower))
    upside = float(np.mean(upper - center))
    return lower, upper, {
        "level": INTERVAL_LEVEL,
        "method": method,
        "clamped_at_zero": clamped,
        "downside_width": _round(downside, 4),
        "upside_width": _round(upside, 4),
        "skew_ratio": _round(downside / upside, 4) if upside > EPSILON else None,
    }


def trend_forecast(
    rows: list[dict[str, Any]],
    *,
    period_col: str,
    value_col: str,
    start: str,
    end: str,
    horizon_days: int,
) -> TrendForecastResult:
    horizon = max(1, min(int(horizon_days), 365))
    daily, expected, observed = _daily_series(rows, period_col, value_col, start, end)
    coverage = observed / expected * 100 if expected > 0 else 0.0
    warnings: list[str] = []
    base = TrendForecastResult(
        metric=value_col,
        history_start=start,
        history_end=end,
        horizon_days=horizon,
        expected_days=expected,
        observed_days=observed,
        coverage_pct=_round(coverage),
        method="",
        assumptions=list(ASSUMPTIONS),
    )
    if observed < MIN_HISTORY_DAYS:
        base.summary = (
            f"历史只有 {observed} 天（至少需要 {MIN_HISTORY_DAYS} 天），不足以拟合趋势与季节，未生成预测。"
        )
        base.warnings = ["历史天数不足，请扩大取数区间后重试"]
        return base
    if coverage < MIN_COVERAGE_PCT:
        base.summary = f"历史覆盖率只有 {coverage:.1f}%，数据缺口过大，未生成预测。"
        base.warnings = ["缺失日过多，插值会主导结果，预测不可信"]
        return base

    series, gaps = _regular(daily, start, end)
    if gaps:
        warnings.append(
            f"历史区间有 {gaps} 天无数据，建模时按时间线性插值补齐；"
            f"实际观测 {observed}/{expected} 天（覆盖 {coverage:.1f}%）"
        )
    if float(series.std(ddof=1)) < EPSILON:
        base.summary = "历史值几乎不变，无需预测：外推等于当前水平。"
        base.warnings = ["序列方差为 0"]
        base.forecast = [
            {
                "date": (pd.Timestamp(end) + pd.Timedelta(days=step)).date().isoformat(),
                "yhat": _round(float(series.iloc[-1])),
                "lower": _round(float(series.iloc[-1])),
                "upper": _round(float(series.iloc[-1])),
            }
            for step in range(1, horizon + 1)
        ]
        return base

    trend = _trend_stats(series)
    decomposition = _decomposition(series)
    backtest = _backtest(series)
    fitted, seasonal = _fit(series)
    point = np.asarray(fitted.forecast(horizon), dtype=float)
    non_negative = bool(float(series.min()) >= 0)
    lower, upper, interval = _interval(fitted, horizon, non_negative)
    dates = pd.date_range(pd.Timestamp(end) + pd.Timedelta(days=1), periods=horizon, freq="D")
    forecast_rows = [
        {
            "date": day.date().isoformat(),
            "yhat": _round(float(value)),
            "lower": _round(float(low)),
            "upper": _round(float(high)),
        }
        for day, value, low, high in zip(dates, point, lower, upper)
    ]
    widths = upper - lower
    mean_point = float(np.mean(np.abs(point)))
    interval["mean_width"] = _round(float(np.mean(widths)), 4)
    interval["mean_width_pct_of_forecast"] = (
        _round(float(np.mean(widths)) / mean_point * 100)
        if mean_point > EPSILON
        else None
    )
    resid = np.asarray(fitted.resid, dtype=float)
    model_info = {
        "name": "Holt-Winters 指数平滑（加法趋势、阻尼）",
        "seasonal": seasonal or "none",
        "seasonal_periods": SEASONAL_PERIOD if seasonal else None,
        "residual_std": _round(float(np.std(resid, ddof=1)), 4) if resid.size > 2 else None,
        "aic": _round(float(fitted.aic), 4) if math.isfinite(float(fitted.aic)) else None,
        "library": "statsmodels.tsa.holtwinters.ExponentialSmoothing",
    }
    tail = daily.tail(HISTORY_TAIL_DAYS)
    history_tail = [
        {"date": day.date().isoformat(), "value": _round(float(value))}
        for day, value in tail.items()
    ]

    if trend.get("available") and trend.get("r2") is not None and trend["r2"] < 0.3:
        warnings.append(
            f"线性趋势解释力弱（R²={trend['r2']}），外推更多依赖季节与近期水平"
        )
    if backtest.get("available") and backtest.get("best") != "model":
        best_key = f"{backtest.get('best')}_mape_pct"
        warnings.append(
            f"回测中{backtest['best_label']}更准（MAPE {_round(backtest.get(best_key), 2)}% "
            f"vs 模型 {_round(backtest.get('model_mape_pct'), 2)}%），预测可信度有限"
        )
    if not backtest.get("available"):
        warnings.append(backtest.get("reason", "未做回测"))
    if decomposition.get("available") and (decomposition.get("seasonal_strength") or 0) < 0.1:
        warnings.append("周内季节性很弱，季节因子贡献有限")
    if interval.get("mean_width_pct_of_forecast") is not None and interval[
        "mean_width_pct_of_forecast"
    ] > 50:
        warnings.append(
            f"预测区间平均宽度达预测值的 {interval['mean_width_pct_of_forecast']}%，不确定性偏高"
        )
    if interval.get("skew_ratio") is not None and interval["skew_ratio"] >= 2:
        warnings.append(
            f"区间明显左偏：下行空间是上行的 {interval['skew_ratio']} 倍，"
            f"说明历史里有过异常大幅下跌，区间下限不应当作崩盘预测"
        )
    if horizon > observed:
        warnings.append(
            f"外推 {horizon} 天超过历史观测 {observed} 天，越远越不可靠"
        )

    total = float(np.sum(point))
    daily_avg = float(np.mean(point))
    summary = (
        f"未来 {horizon} 天（{dates[0].date()} ~ {dates[-1].date()}）预计合计 {total:.2f}、"
        f"日均 {daily_avg:.2f}"
    )
    if trend.get("available"):
        summary += (
            f"；趋势 {trend['slope_per_day']:+.4f}/天"
            f"（R²={trend['r2']}，p={trend['p_value']}，{trend['verdict']}）"
        )
    if backtest.get("available"):
        summary += (
            f"；回测 MAPE：模型 {backtest['model_mape_pct']}%、"
            f"季节朴素 {backtest['seasonal_naive_mape_pct']}%、"
            f"朴素 {backtest['naive_last_mape_pct']}% —— {backtest['verdict']}"
        )
    summary += f"；{interval['level']:.0%} 区间平均宽度 {interval['mean_width']}"
    return TrendForecastResult(
        metric=value_col,
        history_start=start,
        history_end=end,
        horizon_days=horizon,
        expected_days=expected,
        observed_days=observed,
        coverage_pct=_round(coverage),
        trend=trend,
        decomposition=decomposition,
        model=model_info,
        backtest=backtest,
        interval=interval,
        history_tail=history_tail,
        forecast=forecast_rows,
        forecast_total=_round(total),
        forecast_daily_avg=_round(daily_avg),
        summary=summary,
        warnings=warnings,
        method=(
            f"{model_info['name']}；趋势检验用最小二乘，结构识别用 STL；"
            f"区间为{interval['method']}"
        ),
        assumptions=list(ASSUMPTIONS),
    )
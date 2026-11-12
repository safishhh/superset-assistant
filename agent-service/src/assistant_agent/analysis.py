from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import pandas as pd
from scipy import stats

from .models import (
    ContributionResult,
    PeriodCompareResult,
    StructureEffectResult,
)

EPSILON = 1e-9
SIGNIFICANCE_ALPHA = 0.05
BASIS_TOTAL = "total"
BASIS_DAILY_AVG = "daily_avg"


def _safe_div(numerator: float, denominator: float) -> float | None:
    if abs(denominator) < EPSILON:
        return None
    return numerator / denominator


def _round(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    rounded = round(number, digits)
    return 0.0 if rounded == 0 else rounded  # 避免 -0.0 显示成「-0」


def _round_sig(value: float | None, digits: int = 4) -> float | None:
    """按有效数字保留：p 值这类极小数用定点小数会被抹成 0，读起来像「概率为零」。"""
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    if number == 0:
        return 0.0
    return float(f"{number:.{digits}g}")


def _frame(
    rows: list[dict[str, Any]],
    period_col: str,
    value_cols: list[str],
) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    if period_col not in frame.columns:
        raise ValueError(
            f"缺少日期列 {period_col}；可用列：{', '.join(map(str, frame.columns))}"
        )
    for column in [period_col, *value_cols]:
        if column not in frame.columns:
            raise ValueError(
                f"缺少列 {column}；可用列：{', '.join(map(str, frame.columns))}"
            )
    frame[period_col] = pd.to_datetime(frame[period_col], errors="coerce")
    frame = frame.dropna(subset=[period_col])
    for column in value_cols:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    return frame


def _slice(
    frame: pd.DataFrame,
    period_col: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    if frame.empty:
        return frame
    return frame[
        (frame[period_col] >= pd.Timestamp(start))
        & (frame[period_col] <= pd.Timestamp(end))
    ]


def _dims(dimensions: Sequence[str] | None) -> list[str]:
    return [str(item) for item in (dimensions or []) if str(item)]


def _require_dims(dimensions: Sequence[str] | None) -> list[str]:
    dims = _dims(dimensions)
    if not dims:
        raise ValueError("至少需要一个分析维度")
    return dims


def _label(dims: Sequence[str]) -> str:
    return " / ".join(dims)


def _member_series(frame: pd.DataFrame, dims: Sequence[str]) -> pd.Series:
    parts = [
        frame[dim].map(lambda value: "∅" if pd.isna(value) else str(value))
        for dim in dims
    ]
    if len(parts) == 1:
        return parts[0]
    return parts[0].str.cat(parts[1:], sep=" / ")


def _window_stats(
    part: pd.DataFrame,
    period_col: str,
    value_col: str,
    start: str,
    end: str,
) -> dict[str, Any]:
    """日历天数、覆盖度与日序列波动：判断两期是否可比、变化是否超出日常波动。"""
    expected = (pd.Timestamp(end) - pd.Timestamp(start)).days + 1
    if part.empty:
        daily = pd.Series(dtype="float64")
    else:
        daily = part.groupby(period_col)[value_col].sum().sort_index()
    observed = int(daily.shape[0])
    total = float(daily.sum())
    observed_mean = total / observed if observed else 0.0
    std = float(daily.std(ddof=1)) if observed >= 2 else None
    return {
        "start": start,
        "end": end,
        "expected_days": expected,
        "observed_days": observed,
        "coverage_pct": _round(observed / expected * 100) if expected > 0 else None,
        "total": _round(total),
        "daily_avg": _round(total / expected) if expected > 0 else None,
        "observed_daily_avg": _round(observed_mean),
        "daily_std": _round(std),
        "cv_pct": _round(std / observed_mean * 100)
        if std is not None and abs(observed_mean) > EPSILON
        else None,
        "min_daily": _round(float(daily.min())) if observed else None,
        "max_daily": _round(float(daily.max())) if observed else None,
    }


def _basis(
    base_stats: dict[str, Any], current_stats: dict[str, Any]
) -> tuple[str, str]:
    """天数或覆盖度不一致时总量不可比， headline 改用日历天日均。"""
    if (
        base_stats["expected_days"] == current_stats["expected_days"]
        and base_stats["observed_days"] == current_stats["observed_days"]
    ):
        return BASIS_TOTAL, "两期日历天数与有数据天数一致，按总量对比"
    return BASIS_DAILY_AVG, (
        f"基期 {base_stats['expected_days']} 天（{base_stats['observed_days']} 天有数据）、"
        f"本期 {current_stats['expected_days']} 天（{current_stats['observed_days']} 天有数据），"
        "总量不可比，按日历天日均对比"
    )


def _basis_value(stats: dict[str, Any], basis: str) -> float:
    value = stats["total"] if basis == BASIS_TOTAL else stats["daily_avg"]
    return float(value or 0.0)


def _comparable(
    base_stats: dict[str, Any], current_stats: dict[str, Any], basis: str
) -> dict[str, Any]:
    base_value = _basis_value(base_stats, basis)
    current_value = _basis_value(current_stats, basis)
    delta = current_value - base_value
    pct = _safe_div(delta, base_value)
    return {
        "basis": basis,
        "unit": "总量" if basis == BASIS_TOTAL else "日历天日均",
        "base": _round(base_value),
        "current": _round(current_value),
        "delta": _round(delta),
        "pct_change": _round(pct * 100) if pct is not None else None,
    }


def _significance(
    base_stats: dict[str, Any], current_stats: dict[str, Any]
) -> dict[str, Any] | None:
    """Welch t 检验（按日聚合值）：判断日均差异是否超出日常波动。"""
    n0 = base_stats["observed_days"]
    n1 = current_stats["observed_days"]
    s0 = base_stats["daily_std"]
    s1 = current_stats["daily_std"]
    if n0 < 2 or n1 < 2 or s0 is None or s1 is None:
        return None
    m0 = float(base_stats["observed_daily_avg"] or 0.0)
    m1 = float(current_stats["observed_daily_avg"] or 0.0)
    v0 = float(s0) ** 2 / n0
    v1 = float(s1) ** 2 / n1
    if v0 + v1 < EPSILON:
        return None
    test = stats.ttest_ind_from_stats(m1, float(s1), n1, m0, float(s0), n0, equal_var=False)
    df = (v0 + v1) ** 2 / (
        v0**2 / (n0 - 1) + v1**2 / (n1 - 1)
    )
    statistic = float(test.statistic)
    p_value = float(test.pvalue)
    significant = math.isfinite(p_value) and p_value < SIGNIFICANCE_ALPHA
    if not significant:
        verdict = "仍在日常波动范围内"
    elif statistic > 0:
        verdict = "上升超出日常波动"
    else:
        verdict = "下降超出日常波动"
    return {
        "mean_diff": _round(m1 - m0),
        "t": _round(statistic),
        "df": _round(df, 2),
        "p_value": _round_sig(p_value),
        "alpha": SIGNIFICANCE_ALPHA,
        "significant": significant,
        "verdict": verdict,
        "method": "Welch 两样本 t 检验（样本为日聚合值，不假设等方差）",
        "caveat": (
            "日序列通常有周内季节性与自相关，会低估标准误、放大显著性；"
            "结论只作量级参考，严格推断需先做季节性调整"
        ),
    }


def _coverage_warnings(
    base_stats: dict[str, Any], current_stats: dict[str, Any]
) -> list[str]:
    warnings: list[str] = []
    for name, stats in (("基期", base_stats), ("本期", current_stats)):
        coverage = stats["coverage_pct"]
        if coverage is not None and coverage < 100:
            warnings.append(
                f"{name}只有 {stats['observed_days']}/{stats['expected_days']} 天有数据"
                f"（覆盖 {coverage:.1f}%），缺失日按 0 计入总量，日均可能被低估"
            )
    return warnings


def _member_values(
    part: pd.DataFrame,
    dims: Sequence[str],
    value_col: str,
    basis: str,
    expected_days: int,
) -> pd.Series:
    if part.empty:
        return pd.Series(dtype="float64")
    tmp = part.copy()
    tmp["_member"] = _member_series(tmp, dims)
    grouped = tmp.groupby("_member", dropna=False)[value_col].sum()
    if basis == BASIS_DAILY_AVG and expected_days > 0:
        grouped = grouped / expected_days
    return grouped


def _concentration(deltas: Sequence[float]) -> dict[str, Any] | None:
    """按 |变化| 份额算集中度：区分「个别成员主导」与「普遍性变化」。"""
    gross = sum(abs(float(delta)) for delta in deltas)
    count = len(deltas)
    if gross < EPSILON or count == 0:
        return None
    shares = sorted((abs(float(delta)) / gross for delta in deltas), reverse=True)
    hhi = sum(share * share for share in shares)
    normalized = (hhi - 1 / count) / (1 - 1 / count) if count > 1 else None
    top1 = shares[0] * 100
    # n 很小时 Top1 的绝对阈值会误判（2 个成员 51/49 也能过 40%），所以按「超出均分份额的百分点」判断
    excess = top1 - 100 / count
    if count == 1:
        verdict = "只有一个成员"
    elif excess >= 30 or (normalized is not None and normalized >= 0.5):
        verdict = "个别成员主导"
    elif excess >= 10 or (normalized is not None and normalized >= 0.2):
        verdict = "较集中"
    else:
        verdict = "较分散，属普遍性变化"
    return {
        "member_count": count,
        "top1_abs_share_pct": _round(top1),
        "top1_excess_pp": _round(excess),
        "top3_abs_share_pct": _round(sum(shares[:3]) * 100),
        "hhi": _round(hhi, 6),
        "normalized_hhi": _round(normalized, 6),
        "verdict": verdict,
    }


def _offsetting(deltas: Sequence[float]) -> dict[str, Any]:
    positive = sum(float(delta) for delta in deltas if delta > 0)
    negative = sum(float(delta) for delta in deltas if delta < 0)
    gross = positive + abs(negative)
    net = positive + negative
    ratio = 1 - abs(net) / gross if gross > EPSILON else 0.0
    return {
        "positive_delta": _round(positive),
        "negative_delta": _round(negative),
        "net_delta": _round(net),
        "gross_delta": _round(gross),
        "offset_ratio": _round(ratio),
    }


def _top_member(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return max(rows, key=lambda item: abs(float(item.get("delta") or 0.0)))


def _dimension_ranking(
    base: pd.DataFrame,
    current: pd.DataFrame,
    dimensions: Sequence[str],
    value_col: str,
    basis: str,
    base_stats: dict[str, Any],
    current_stats: dict[str, Any],
) -> list[dict[str, Any]]:
    """用同一份数据按每个单维度回卷，比较哪个口径更能解释变化（不额外取数）。"""
    if len(dimensions) < 2:
        return []
    ranking: list[dict[str, Any]] = []
    for dim in dimensions:
        base_group = _member_values(
            base, [dim], value_col, basis, base_stats["expected_days"]
        )
        current_group = _member_values(
            current, [dim], value_col, basis, current_stats["expected_days"]
        )
        members = sorted(set(base_group.index) | set(current_group.index), key=str)
        deltas = [
            float(current_group.get(member, 0.0)) - float(base_group.get(member, 0.0))
            for member in members
        ]
        concentration = _concentration(deltas)
        ranking.append(
            {
                "dimension": dim,
                "member_count": len(members),
                "top1_abs_share_pct": (concentration or {}).get("top1_abs_share_pct"),
                "top1_excess_pp": (concentration or {}).get("top1_excess_pp"),
                "normalized_hhi": (concentration or {}).get("normalized_hhi"),
                "verdict": (concentration or {}).get("verdict", "变化为 0，无法判断"),
            }
        )
    ranking.sort(
        key=lambda item: (
            item["normalized_hhi"] is None,
            -(item["normalized_hhi"] or 0.0),
        )
    )
    return ranking


def period_compare(
    rows: list[dict[str, Any]],
    *,
    period_col: str,
    value_col: str,
    base_start: str,
    base_end: str,
    current_start: str,
    current_end: str,
    dimensions: Sequence[str] | None = None,
) -> PeriodCompareResult:
    dims = _dims(dimensions)
    warnings: list[str] = []
    base_label = f"{base_start}..{base_end}"
    current_label = f"{current_start}..{current_end}"
    frame = _frame(rows, period_col, [value_col])
    if frame.empty:
        return PeriodCompareResult(
            base_period=base_label,
            current_period=current_label,
            dimension=_label(dims),
            dimensions=dims,
            summary="没有可用于对比的数据。",
            warnings=["查询结果为空或日期列无法解析"],
        )

    base = _slice(frame, period_col, base_start, base_end)
    current = _slice(frame, period_col, current_start, current_end)
    if base.empty or current.empty:
        warnings.append("基期或本期没有数据，结果可能不完整")
    for dim in dims:
        if dim not in frame.columns:
            raise ValueError(
                f"缺少维度 {dim}；可用列：{', '.join(map(str, frame.columns))}"
            )

    base_stats = _window_stats(base, period_col, value_col, base_start, base_end)
    current_stats = _window_stats(
        current, period_col, value_col, current_start, current_end
    )
    basis, basis_reason = _basis(base_stats, current_stats)
    comparable = _comparable(base_stats, current_stats, basis)
    warnings.extend(_coverage_warnings(base_stats, current_stats))
    significance = _significance(base_stats, current_stats)

    base_total = float(base_stats["total"] or 0.0)
    current_total = float(current_stats["total"] or 0.0)
    total_delta = current_total - base_total
    headline_delta = float(comparable["delta"] or 0.0)
    if abs(total_delta) < EPSILON:
        warnings.append("总变化接近 0，贡献率可能失真")
    if base_total == 0 and current_total != 0:
        warnings.append("基期总量为 0，总量变化率无定义")

    out_rows: list[dict[str, Any]] = []
    if dims:
        base_group = _member_values(
            base, dims, value_col, basis, base_stats["expected_days"]
        )
        current_group = _member_values(
            current, dims, value_col, basis, current_stats["expected_days"]
        )
        base_raw = _member_values(base, dims, value_col, BASIS_TOTAL, 0)
        current_raw = _member_values(current, dims, value_col, BASIS_TOTAL, 0)
        for member in sorted(set(base_group.index) | set(current_group.index), key=str):
            base_value = float(base_group.get(member, 0.0))
            current_value = float(current_group.get(member, 0.0))
            delta = current_value - base_value
            pct = _safe_div(delta, base_value)
            contribution = _safe_div(delta, headline_delta)
            pull = _safe_div(delta, float(comparable["base"] or 0.0))
            out_rows.append(
                {
                    "member": str(member),
                    "base": _round(base_value),
                    "current": _round(current_value),
                    "delta": _round(delta),
                    "base_total": _round(float(base_raw.get(member, 0.0))),
                    "current_total": _round(float(current_raw.get(member, 0.0))),
                    "pct_change": _round(pct * 100) if pct is not None else None,
                    "contribution_pct": _round(contribution * 100)
                    if contribution is not None
                    else None,
                    "pull_pp": _round(pull * 100) if pull is not None else None,
                }
            )
        out_rows.sort(key=lambda item: abs(float(item["delta"] or 0.0)), reverse=True)
    else:
        pct = comparable["pct_change"]
        out_rows.append(
            {
                "base": comparable["base"],
                "current": comparable["current"],
                "delta": comparable["delta"],
                "base_total": _round(base_total),
                "current_total": _round(current_total),
                "pct_change": pct,
            }
        )

    summary = (
        f"{current_label} {comparable['unit']} {comparable['current']}，"
        f"{base_label} {comparable['unit']} {comparable['base']}，"
        f"变化 {comparable['delta']}"
    )
    if comparable["pct_change"] is not None:
        summary += f"（{comparable['pct_change']:+.4f}%）"
    if dims:
        summary += f"；总量口径变化 {total_delta:.2f}"
        top = _top_member(out_rows)
        if top is not None:
            summary += f"；影响最大的成员是 {top['member']}（{top['delta']:+.2f}）"
    if significance:
        summary += (
            f"；日均差异 t={significance['t']}、p={significance['p_value']}，"
            f"{significance['verdict']}"
        )
    return PeriodCompareResult(
        base_period=base_label,
        current_period=current_label,
        dimension=_label(dims),
        dimensions=dims,
        basis=basis,
        basis_reason=basis_reason,
        base_stats=base_stats,
        current_stats=current_stats,
        comparable=comparable,
        significance=significance,
        rows=out_rows,
        summary=summary,
        warnings=warnings,
    )


def dimension_contribution(
    rows: list[dict[str, Any]],
    *,
    dimensions: Sequence[str],
    value_col: str,
    period_col: str,
    base_start: str,
    base_end: str,
    current_start: str,
    current_end: str,
) -> ContributionResult:
    dims = _require_dims(dimensions)
    warnings: list[str] = []
    frame = _frame(rows, period_col, [value_col])
    if frame.empty:
        return ContributionResult(
            dimension=_label(dims),
            dimensions=dims,
            total_delta=0.0,
            summary="没有可用于归因的数据。",
            warnings=["查询结果为空或日期列无法解析"],
        )
    for dim in dims:
        if dim not in frame.columns:
            raise ValueError(
                f"缺少维度 {dim}；可用列：{', '.join(map(str, frame.columns))}"
            )

    base = _slice(frame, period_col, base_start, base_end)
    current = _slice(frame, period_col, current_start, current_end)
    base_stats = _window_stats(base, period_col, value_col, base_start, base_end)
    current_stats = _window_stats(
        current, period_col, value_col, current_start, current_end
    )
    basis, basis_reason = _basis(base_stats, current_stats)
    comparable = _comparable(base_stats, current_stats, basis)
    warnings.extend(_coverage_warnings(base_stats, current_stats))
    if base.empty or current.empty:
        warnings.append("基期或本期没有数据，结果可能不完整")

    base_group = _member_values(
        base, dims, value_col, basis, base_stats["expected_days"]
    )
    current_group = _member_values(
        current, dims, value_col, basis, current_stats["expected_days"]
    )
    base_raw = _member_values(base, dims, value_col, BASIS_TOTAL, 0)
    current_raw = _member_values(current, dims, value_col, BASIS_TOTAL, 0)
    headline_delta = float(comparable["delta"] or 0.0)
    base_headline = float(comparable["base"] or 0.0)
    current_headline = float(comparable["current"] or 0.0)
    if abs(headline_delta) < EPSILON:
        warnings.append("总变化接近 0，贡献率可能失真")

    out_rows: list[dict[str, Any]] = []
    for member in sorted(set(base_group.index) | set(current_group.index), key=str):
        base_value = float(base_group.get(member, 0.0))
        current_value = float(current_group.get(member, 0.0))
        delta = current_value - base_value
        contribution = _safe_div(delta, headline_delta)
        pull = _safe_div(delta, base_headline)
        base_share = _safe_div(base_value, base_headline)
        current_share = _safe_div(current_value, current_headline)
        out_rows.append(
            {
                "member": str(member),
                "base": _round(base_value),
                "current": _round(current_value),
                "delta": _round(delta),
                "base_total": _round(float(base_raw.get(member, 0.0))),
                "current_total": _round(float(current_raw.get(member, 0.0))),
                "contribution_pct": _round(contribution * 100)
                if contribution is not None
                else None,
                "pull_pp": _round(pull * 100) if pull is not None else None,
                "base_share_pct": _round(base_share * 100)
                if base_share is not None
                else None,
                "current_share_pct": _round(current_share * 100)
                if current_share is not None
                else None,
            }
        )
    out_rows.sort(key=lambda item: abs(float(item["delta"] or 0.0)), reverse=True)
    deltas = [float(item["delta"] or 0.0) for item in out_rows]
    concentration = _concentration(deltas)
    offsetting = _offsetting(deltas)
    ranking = _dimension_ranking(
        base, current, dims, value_col, basis, base_stats, current_stats
    )
    if offsetting["offset_ratio"] is not None and offsetting["offset_ratio"] >= 0.5:
        warnings.append(
            f"正负变化相互抵消（抵消比 {offsetting['offset_ratio']:.2f}），"
            "净额掩盖了成员间的剧烈变化，建议同时看正/负两侧"
        )

    summary = f"{comparable['unit']}总变化 {headline_delta:.2f}"
    top = _top_member(out_rows)
    if top is not None:
        share = top.get("contribution_pct")
        summary += f"；影响最大的成员 {top['member']}（{top['delta']:+.2f}"
        summary += f"，贡献 {share:.2f}%）" if share is not None else "）"
    if concentration:
        summary += f"；{concentration['verdict']}（Top1 占 |变化| 的 {concentration['top1_abs_share_pct']}%）"
    if ranking:
        summary += f"；解释力最强的口径是 {ranking[0]['dimension']}"
    return ContributionResult(
        dimension=_label(dims),
        dimensions=dims,
        basis=basis,
        basis_reason=basis_reason,
        base_stats=base_stats,
        current_stats=current_stats,
        total_delta=_round(headline_delta) or 0.0,
        concentration=concentration,
        offsetting=offsetting,
        dimension_ranking=ranking,
        rows=out_rows,
        summary=summary,
        warnings=warnings,
    )


def structure_effect(
    rows: list[dict[str, Any]],
    *,
    dimensions: Sequence[str],
    numerator_col: str,
    denominator_col: str,
    period_col: str,
    base_start: str,
    base_end: str,
    current_start: str,
    current_end: str,
) -> StructureEffectResult:
    dims = _require_dims(dimensions)
    warnings: list[str] = []
    frame = _frame(rows, period_col, [numerator_col, denominator_col])
    if frame.empty:
        return StructureEffectResult(
            dimension=_label(dims),
            dimensions=dims,
            total_delta=0.0,
            structure_effect=0.0,
            efficiency_effect=0.0,
            interaction_effect=0.0,
            summary="没有可用于结构效应拆解的数据。",
            warnings=["查询结果为空或日期列无法解析"],
        )
    for dim in dims:
        if dim not in frame.columns:
            raise ValueError(
                f"缺少维度 {dim}；可用列：{', '.join(map(str, frame.columns))}"
            )

    base = _slice(frame, period_col, base_start, base_end)
    current = _slice(frame, period_col, current_start, current_end)
    base_stats = _window_stats(base, period_col, numerator_col, base_start, base_end)
    current_stats = _window_stats(
        current, period_col, numerator_col, current_start, current_end
    )
    warnings.extend(_coverage_warnings(base_stats, current_stats))

    def aggregate(part: pd.DataFrame) -> pd.DataFrame:
        if part.empty:
            return pd.DataFrame(
                {numerator_col: [], denominator_col: [], "weight": [], "rate": []}
            )
        tmp = part.copy()
        tmp["_member"] = _member_series(tmp, dims)
        grouped = tmp.groupby("_member", dropna=False)[
            [numerator_col, denominator_col]
        ].sum()
        total_den = float(grouped[denominator_col].sum())
        grouped["weight"] = grouped[denominator_col].apply(
            lambda value: (_safe_div(float(value), total_den) or 0.0)
        )
        grouped["rate"] = grouped.apply(
            lambda row: (
                _safe_div(float(row[numerator_col]), float(row[denominator_col]))
                or 0.0
            ),
            axis=1,
        )
        return grouped

    base_group = aggregate(base)
    current_group = aggregate(current)
    index = sorted(set(base_group.index) | set(current_group.index), key=str)
    structure = 0.0
    efficiency = 0.0
    interaction = 0.0
    out_rows: list[dict[str, Any]] = []
    for member in index:
        bw = float(base_group["weight"].get(member, 0.0))
        br = float(base_group["rate"].get(member, 0.0))
        cw = float(current_group["weight"].get(member, 0.0))
        cr = float(current_group["rate"].get(member, 0.0))
        member_structure = (cw - bw) * br
        member_efficiency = bw * (cr - br)
        member_interaction = (cw - bw) * (cr - br)
        structure += member_structure
        efficiency += member_efficiency
        interaction += member_interaction
        out_rows.append(
            {
                "member": str(member),
                "base_share_pct": _round(bw * 100),
                "current_share_pct": _round(cw * 100),
                "weight_delta_pp": _round((cw - bw) * 100),
                "base_rate": _round(br, 6),
                "current_rate": _round(cr, 6),
                "rate_delta": _round(cr - br, 6),
                "structure_effect": _round(member_structure, 6),
                "efficiency_effect": _round(member_efficiency, 6),
                "interaction_effect": _round(member_interaction, 6),
                "member_total_effect": _round(
                    member_structure + member_efficiency + member_interaction, 6
                ),
            }
        )
    out_rows.sort(
        key=lambda item: abs(float(item["member_total_effect"] or 0.0)), reverse=True
    )

    base_total_den = float(base_group[denominator_col].sum())
    current_total_den = float(current_group[denominator_col].sum())
    base_rate = _safe_div(float(base_group[numerator_col].sum()), base_total_den)
    current_rate = _safe_div(
        float(current_group[numerator_col].sum()), current_total_den
    )
    total_delta = (current_rate or 0.0) - (base_rate or 0.0)
    if base_total_den < EPSILON or current_total_den < EPSILON:
        warnings.append("基期或本期分母为 0，结构效应可能无定义")
    if abs(total_delta) < EPSILON:
        warnings.append("总比率变化接近 0，拆解项可能相互抵消")
    residual = total_delta - (structure + efficiency + interaction)
    if abs(residual) > 1e-6:
        warnings.append(f"拆解残差 {residual:.6f}，请检查数据口径")

    terms = {
        "structure": structure,
        "efficiency": efficiency,
        "interaction": interaction,
    }
    term_labels = {
        "structure": "结构效应（成员占比变化）",
        "efficiency": "效率效应（成员自身比率变化）",
        "interaction": "交互项（占比与比率同时变化）",
    }
    gross = sum(abs(value) for value in terms.values())
    dominant_key = max(terms, key=lambda key: abs(terms[key])) if gross > EPSILON else None
    dominant = (
        {
            "term": dominant_key,
            "label": term_labels[dominant_key],
            "value": _round(terms[dominant_key], 6),
            "abs_share_pct": _round(abs(terms[dominant_key]) / gross * 100),
        }
        if dominant_key
        else None
    )
    summary = (
        f"总比率变化 {total_delta:.6f}，其中结构效应 {structure:.6f}、"
        f"效率效应 {efficiency:.6f}、交互项 {interaction:.6f}"
    )
    if dominant:
        summary += f"；主导项是{dominant['label']}（占三项绝对值 {dominant['abs_share_pct']}%）"
    if out_rows:
        top = out_rows[0]
        summary += (
            f"；影响最大的成员 {top['member']}"
            f"（合计效应 {top['member_total_effect']:+.6f}）"
        )
    return StructureEffectResult(
        dimension=_label(dims),
        dimensions=dims,
        base_stats=base_stats,
        current_stats=current_stats,
        total_delta=_round(total_delta, 6) or 0.0,
        structure_effect=_round(structure, 6) or 0.0,
        efficiency_effect=_round(efficiency, 6) or 0.0,
        interaction_effect=_round(interaction, 6) or 0.0,
        residual=_round(residual, 8) or 0.0,
        dominant=dominant,
        rows=out_rows,
        summary=summary,
        warnings=warnings,
    )
import { useEffect, useMemo, useRef, useState } from "react";

// 零依赖手写 SVG 图表：按数据形态自动选择 柱/折线，吃 Superset 主题 CSS 变量。
// 宽度跟随容器实测值（ResizeObserver），viewBox 与像素 1:1，字号不随面板缩放变形。

const PALETTE = [
  "#4c78d0",
  "#e8873a",
  "#54a878",
  "#c65d7a",
  "#8a6fb0",
  "#3fa7b8",
  "#b8912f",
  "#7a8b99",
  "#d0664f",
  "#6a9bd0",
];

const H = 188;
const PAD_L = 42;
const PAD_R = 10;
const PAD_T = 12;
const PAD_B = 30;
const MIN_W = 240;
const FALLBACK_W = 340;

type Kind = "bar" | "line" | "pie" | null;

type Series = { name: string; label: string; values: number[] };

export type ChartModel = {
  kind: Exclude<Kind, null>;
  categories: string[];
  series: Series[];
  temporal: boolean;
  metric: string;
};

function isTemporalType(type?: string | null): boolean {
  const t = (type || "").toLowerCase();
  return (
    t.includes("date") ||
    t.includes("time") ||
    t.includes("timestamp") ||
    t.includes("datetime")
  );
}

function looksTemporal(value: unknown): boolean {
  if (typeof value !== "string") return false;
  return /^\d{4}[-/]\d{1,2}[-/]\d{1,2}/.test(value.trim()) ||
    /^\d{4}[-/]\d{1,2}$/.test(value.trim());
}

function toNumber(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value.replace(/[, ]/g, ""));
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

type Analysis = {
  categories: string[];
  metrics: string[];
  used: Record<string, any>[];
  temporal: boolean;
};

function analyze(
  rows: Record<string, any>[],
  columns: { name: string; type?: string | null }[],
): Analysis | null {
  if (!rows.length) return null;
  const names = columns.length
    ? columns.map((c) => c.name)
    : Object.keys(rows[0] || {});
  if (names.length < 2) return null;

  // 数值列 = 指标；首个非数值列 = 维度
  const numericFlags = names.map((name) =>
    rows.some((row) => toNumber(row[name]) !== null),
  );
  // 多维度结果是明细（如 天 × 品类 714 行），画成单维序列会误导，直接不画
  if (numericFlags.filter((flag) => !flag).length > 1) return null;
  const metricNames = names.filter((_, i) => numericFlags[i]);
  let dimIndex = names.findIndex((_, i) => !numericFlags[i]);
  if (dimIndex < 0) dimIndex = 0;
  const dimName = names[dimIndex];
  const metrics = metricNames.filter((n) => n !== dimName);
  if (!metrics.length) return null;

  const limit = dimIndex === 0 ? 30 : 20;
  const used = rows.slice(0, limit);
  if (used.length < 2 || used.length > 30) return null;

  const categories = used.map((row) => {
    const value = row[dimName];
    if (value === null || value === undefined) return "—";
    return typeof value === "number"
      ? String(value)
      : String(value).trim();
  });

  const dimType = columns.find((c) => c.name === dimName)?.type;
  const temporal =
    isTemporalType(dimType) ||
    (categories.length > 0 && looksTemporal(row0Value(used, dimName)));
  return { categories, metrics, used, temporal };
}

/**
 * auto 时判断数据是否更像"构成"：单指标、2–7 个类别、全部非负，
 * 且指标名是占比类，或数值合计≈100（百分比）。避免把普通小类目柱状图都变饼图。
 */
function looksLikeShare(
  metric: string,
  label: string | undefined,
  values: number[],
  analysis: Analysis,
): boolean {
  if (analysis.temporal) return false;
  if (values.length < 2 || values.length > 7) return false;
  if (values.some((value) => value < 0)) return false;
  const name = `${metric} ${label || ""}`.toLowerCase();
  if (/占比|比例|百分比|份额|share|ratio|percent|pct/.test(name)) return true;
  const positive = values.filter((value) => value > 0).length;
  const total = values.reduce((sum, value) => sum + value, 0);
  return positive >= 2 && Math.abs(total - 100) < 0.5;
}

function buildModel(
  analysis: Analysis,
  metric: string,
  labels?: Record<string, string>,
  preferred?: string,
): ChartModel {
  const values = analysis.used.map((row) => toNumber(row[metric]) ?? 0);
  // 优先听模型的类型提示（趋势→line、比较→bar、构成→pie），
  // 不合适（pie 要求非负）或没给时按数据形态自动选
  const nonNegative = values.every((value) => value >= 0);
  let kind: Exclude<Kind, null>;
  if (preferred === "pie" && nonNegative) {
    kind = "pie";
  } else if (preferred === "line") {
    kind = "line";
  } else if (preferred === "bar") {
    kind = "bar";
  } else if (looksLikeShare(metric, labels?.[metric], values, analysis)) {
    kind = "pie";
  } else {
    kind = analysis.temporal || analysis.used.length > 12 ? "line" : "bar";
  }
  return {
    kind,
    categories: analysis.categories,
    series: [
      {
        name: metric,
        label: labels?.[metric] || metric,
        values,
      },
    ],
    temporal: analysis.temporal,
    metric,
  };
}

/**
 * 一个指标一张图：不同量纲/量级不再挤在同一根 Y 轴（订单数 vs 营业额）。
 * 数值完全相同的列（如订单数与去重订单数）和多指标里的全零列不画，
 * 仍保留在原始明细表里。
 */
export function classifyAll(
  rows: Record<string, any>[],
  columns: { name: string; type?: string | null }[],
  labels?: Record<string, string>,
  preferred?: string,
): ChartModel[] {
  const analysis = analyze(rows, columns);
  if (!analysis) return [];
  const seen = new Set<string>();
  const metrics = analysis.metrics.filter((metric) => {
    const key = analysis.used
      .map((row) => {
        const value = toNumber(row[metric]);
        return value === null ? "null" : String(value);
      })
      .join("|");
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  // pie 只给第一个指标，其余按数据形态自动选，避免一排饼图
  let models = metrics.map((metric, index) =>
    buildModel(
      analysis,
      metric,
      labels,
      preferred === "pie" && index > 0 ? undefined : preferred,
    ),
  );
  if (models.length > 1) {
    models = models.filter((model) =>
      model.series[0].values.some((value) => value !== 0),
    );
  }
  return models;
}

/** 结果里的维度与指标列名（图表口径说明用，run_sql 没有请求参数时兜底）。 */
export function chartFields(
  rows: Record<string, any>[],
  columns: { name: string; type?: string | null }[],
): { dimension?: string; metrics: string[] } {
  if (!rows.length) return { metrics: [] };
  const names = columns.length
    ? columns.map((column) => column.name)
    : Object.keys(rows[0] ?? {});
  const numeric = names.filter((name) =>
    rows.some((row) => toNumber(row[name]) !== null),
  );
  const dimension = names.find((name) => !numeric.includes(name));
  return {
    dimension,
    metrics: numeric.filter((name) => name !== dimension),
  };
}

function row0Value(rows: Record<string, any>[], key: string): unknown {
  return rows.length ? rows[0][key] : undefined;
}

function niceScale(min: number, max: number, count = 4) {
  if (min === max) {
    if (min === 0) return { lo: 0, hi: 1, step: 0.25, ticks: [0, 0.25, 0.5, 0.75, 1] };
    const pad = Math.abs(min) * 0.2;
    return niceScale(min - pad, max + pad, count);
  }
  const range = max - min;
  const rawStep = range / count;
  const mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
  const norm = rawStep / mag;
  const factor = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10;
  const step = factor * mag;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let v = lo; v <= hi + step * 1e-6; v += step) ticks.push(round(v));
  return { lo, hi, step, ticks };
}

function round(value: number): number {
  return Math.round(value * 1e6) / 1e6;
}

function short(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${(value / 1e9).toFixed(1).replace(/\.0$/, "")}B`;
  if (abs >= 1e6) return `${(value / 1e6).toFixed(1).replace(/\.0$/, "")}M`;
  if (abs >= 1e3) return `${(value / 1e3).toFixed(1).replace(/\.0$/, "")}k`;
  if (Number.isInteger(value)) return String(value);
  return value.toFixed(abs < 1 ? 2 : 1);
}

/** 同一年份的日期标签去掉年份（2025-09-01 → 09-01），把横向空间让给可读性。 */
function compactCategories(categories: string[]): string[] {
  const dateRe = /^\d{4}[-/]\d{1,2}[-/]\d{1,2}/;
  if (categories.length < 2) return categories;
  if (!categories.every((c) => dateRe.test(c))) return categories;
  const year = categories[0].slice(0, 4);
  if (!categories.every((c) => c.slice(0, 4) === year)) return categories;
  return categories.map((c) => c.slice(5).split(/[T ]/)[0] || c);
}

// SVG 里没有 text-measure，用字号估算：中文接近 1em，拉丁字母约 0.58em
function charWidth(char: string): number {
  return /[\u2e80-\u9fff\u3000-\u303f\uff00-\uffef]/.test(char) ? 9.3 : 5.6;
}

function measure(text: string): number {
  let total = 0;
  for (const char of text) total += charWidth(char);
  return total;
}

function truncateToWidth(text: string, maxWidth: number): string {
  if (measure(text) <= maxWidth) return text;
  let out = "";
  for (const char of text) {
    if (measure(`${out}${char}…`) > maxWidth) break;
    out += char;
  }
  return out ? `${out}…` : `${text.slice(0, 1)}…`;
}

function anchorFor(
  x: number,
  text: string,
  width: number,
): "start" | "middle" | "end" {
  const half = measure(text) / 2 + 2;
  if (x + half > width - PAD_R) return "end";
  // 画布左缘（不是绘图区左缘）：首标签居中不会压到下一条
  if (x - half < 2) return "start";
  return "middle";
}

/** 轴下方标签：按可用宽度决定隔几个显示一个、每个最多几个字。 */
function labelPlan(
  count: number,
  plotWidth: number,
  minSpacing: number,
): { step: number; width: number } {
  const visible = Math.max(2, Math.floor(plotWidth / minSpacing));
  const step = Math.max(1, Math.ceil(count / visible));
  const width = plotWidth / Math.max(1, Math.ceil(count / step));
  return { step, width };
}

type CategoryLayout = {
  rotate: boolean;
  step: number;
  labels: string[];
  /** 轴下方需要预留的高度 */
  bottom: number;
};

const ROTATE_DEG = -40;
const SIN_ROT = Math.sin((-ROTATE_DEG * Math.PI) / 180);
const COS_ROT = Math.cos((-ROTATE_DEG * Math.PI) / 180);
const ROTATED_BOTTOM_MAX = 150;

/**
 * X 轴名称过长时斜向下展示并完整显示；间隔按倾斜后的投影算，
 * 始终同一 step，避免标签忽密忽疏。
 */
function categoryLayout(
  categories: string[],
  slot: number,
  temporal: boolean,
  plotWidth: number,
  minSpacing: number,
): CategoryLayout {
  const labels = compactCategories(categories);
  const widest = Math.max(0, ...labels.map(measure));
  const rotate = !temporal && widest > Math.max(26, slot * 0.96);
  if (!rotate) {
    const plan = labelPlan(categories.length, plotWidth, minSpacing);
    return {
      rotate,
      step: plan.step,
      labels: labels.map((label) => truncateToWidth(label, plan.width - 6)),
      bottom: PAD_B,
    };
  }
  const bottom = Math.min(
    ROTATED_BOTTOM_MAX,
    Math.ceil(widest * SIN_ROT) + 14,
  );
  // 相邻标签沿倾斜方向的法向间距；小于一行字高就隔几个显示一个
  const normal = Math.max(1, slot * SIN_ROT);
  const step = Math.max(1, Math.ceil(11 / normal));
  const maxWidth = (bottom - 14) / SIN_ROT || 90;
  return {
    rotate,
    step,
    labels: labels.map((label) => truncateToWidth(label, maxWidth)),
    bottom,
  };
}

function Axes({
  width,
  ticks,
  lo,
  hi,
}: {
  width: number;
  ticks: number[];
  lo: number;
  hi: number;
}) {
  const plotH = H - PAD_T - PAD_B;
  const y = (v: number) =>
    PAD_T + plotH - ((v - lo) / (hi - lo || 1)) * plotH;
  return (
    <g>
      {ticks.map((t) => (
        <g key={t}>
          <line
            x1={PAD_L}
            x2={width - PAD_R}
            y1={y(t)}
            y2={y(t)}
            className="sa-chart-grid"
          />
          <text x={PAD_L - 5} y={y(t) + 3} className="sa-chart-tick" textAnchor="end">
            {short(t)}
          </text>
        </g>
      ))}
      <line
        x1={PAD_L}
        x2={width - PAD_R}
        y1={y(lo < 0 ? 0 : lo)}
        y2={y(lo < 0 ? 0 : lo)}
        className="sa-chart-axis"
      />
    </g>
  );
}

function BarChart({ model, width }: { model: ChartModel; width: number }) {
  const { categories, series, temporal } = model;
  const all = series.flatMap((s) => s.values);
  const { lo, hi, ticks } = niceScale(Math.min(0, ...all), Math.max(...all));
  const plotW = width - PAD_L - PAD_R;
  const plotH = H - PAD_T - PAD_B;
  const axisY = PAD_T + plotH;
  const y = (v: number) => axisY - ((v - lo) / (hi - lo || 1)) * plotH;
  const slot = plotW / (categories.length || 1);
  const group = slot * 0.72;
  const barW = group / series.length;
  const zeroY = y(lo < 0 ? 0 : lo);
  const layout = categoryLayout(
    categories,
    slot,
    temporal,
    plotW,
    46,
  );
  const height = axisY + layout.bottom;
  // 柱子太密时不标数值，避免互相压字
  const showValues = barW >= 24;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="sa-chart" role="img">
      <Axes width={width} ticks={ticks} lo={lo} hi={hi} />
      {categories.map((cat, ci) => {
        const base = PAD_L + slot * ci + (slot - group) / 2;
        const labelText = layout.labels[ci] ?? "";
        const labelX = base + group / 2;
        const showLabel = ci % layout.step === 0;
        const rotateAnchor =
          labelX - measure(labelText) * COS_ROT < 2 ? "start" : "end";
        return (
          <g key={ci}>
            {series.map((s, si) => {
              const v = s.values[ci];
              const x = base + barW * si;
              const yTop = y(Math.max(v, 0));
              const barH = Math.max(1, Math.abs(y(v) - zeroY));
              const fill =
                series.length === 1
                  ? v < 0
                    ? "var(--sa-danger)"
                    : "var(--sa-accent)"
                  : PALETTE[si % PALETTE.length];
              return (
                <g key={si}>
                  <rect
                    x={x}
                    y={v < 0 ? zeroY : yTop}
                    width={Math.max(1, barW - 1.5)}
                    height={barH}
                    rx={1.5}
                    fill={fill}
                  >
                    <title>{`${cat} · ${s.label}: ${short(v)}`}</title>
                  </rect>
                  {showValues ? (
                    <text
                      x={x + Math.max(1, barW - 1.5) / 2}
                      y={
                        v < 0
                          ? Math.min(axisY + layout.bottom - 4, y(v) + 11)
                          : Math.max(PAD_T + 9, yTop - 4)
                      }
                      className="sa-chart-value"
                      textAnchor="middle"
                    >
                      {short(v)}
                    </text>
                  ) : null}
                </g>
              );
            })}
            {showLabel ? (
              <text
                x={labelX}
                y={axisY + 14}
                className="sa-chart-tick"
                textAnchor={
                  layout.rotate ? rotateAnchor : anchorFor(labelX, labelText, width)
                }
                transform={
                  layout.rotate
                    ? `rotate(${ROTATE_DEG} ${labelX} ${axisY + 14})`
                    : undefined
                }
              >
                {labelText}
              </text>
            ) : null}
          </g>
        );
      })}
    </svg>
  );
}

function LineChart({ model, width }: { model: ChartModel; width: number }) {
  const { categories, series, temporal } = model;
  const all = series.flatMap((s) => s.values);
  const { lo, hi, ticks } = niceScale(Math.min(...all), Math.max(...all));
  const plotW = width - PAD_L - PAD_R;
  const plotH = H - PAD_T - PAD_B;
  const axisY = PAD_T + plotH;
  const n = categories.length || 1;
  const x = (i: number) => PAD_L + (plotW * i) / (n - 1 || 1);
  const y = (v: number) => axisY - ((v - lo) / (hi - lo || 1)) * plotH;
  const layout = categoryLayout(categories, plotW / Math.max(1, n - 1), temporal, plotW, 64);
  const height = axisY + layout.bottom;
  const showValues =
    series.length === 1 && n <= 12 && plotW / Math.max(1, n - 1) >= 30;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="sa-chart" role="img">
      <Axes width={width} ticks={ticks} lo={lo} hi={hi} />
      {series.map((s, si) => {
        const color =
          series.length === 1 ? "var(--sa-accent)" : PALETTE[si % PALETTE.length];
        const points = s.values.map((v, i) => `${x(i)},${y(v)}`).join(" ");
        return (
          <g key={si}>
            <polyline
              points={points}
              fill="none"
              stroke={color}
              strokeWidth={1.8}
              strokeLinejoin="round"
            />
            {s.values.map((v, i) => (
              <circle key={i} cx={x(i)} cy={y(v)} r={2.1} fill={color}>
                <title>{`${categories[i]} · ${s.label}: ${short(v)}`}</title>
              </circle>
            ))}
            {showValues
              ? s.values.map((v, i) => {
                  const text = short(v);
                  const anchor = anchorFor(x(i), text, width);
                  return (
                    <text
                      key={`v-${i}`}
                      x={x(i)}
                      y={Math.max(PAD_T + 9, y(v) - 6)}
                      className="sa-chart-value"
                      textAnchor={anchor}
                    >
                      {text}
                    </text>
                  );
                })
              : null}
          </g>
        );
      })}
      {categories.map((cat, i) => {
        // 折线图从最后一个点往前对齐，保证最新时间点始终有标签且间隔一致
        if ((n - 1 - i) % layout.step !== 0) return null;
        const text = layout.labels[i] ?? "";
        return (
          <text
            key={i}
            x={x(i)}
            y={axisY + 14}
            className="sa-chart-tick"
            textAnchor={
              layout.rotate
                ? x(i) - measure(text) * COS_ROT < 2
                  ? "start"
                  : "end"
                : anchorFor(x(i), text, width)
            }
            transform={
              layout.rotate ? `rotate(${ROTATE_DEG} ${x(i)} ${axisY + 14})` : undefined
            }
          >
            {text}
          </text>
        );
      })}
    </svg>
  );
}

type PieSlice = { label: string; value: number; pct: number; color: string };

function pieSlices(model: ChartModel): PieSlice[] {
  const series = model.series[0];
  if (!series) return [];
  const items = model.categories
    .map((label, index) => ({
      label,
      value: Math.max(0, series.values[index] ?? 0),
    }))
    .filter((item) => item.value > 0)
    .sort((a, b) => b.value - a.value);
  if (!items.length) return [];
  const head = items.slice(0, 7);
  const rest = items.slice(7);
  if (rest.length) {
    head.push({
      label: "其他",
      value: rest.reduce((sum, item) => sum + item.value, 0),
    });
  }
  const total = head.reduce((sum, item) => sum + item.value, 0) || 1;
  return head.map((item, index) => ({
    ...item,
    color: PALETTE[index % PALETTE.length],
    pct: (item.value / total) * 100,
  }));
}

function arcPath(
  cx: number,
  cy: number,
  outer: number,
  inner: number,
  start: number,
  end: number,
): string {
  const point = (radius: number, angle: number) =>
    `${(cx + radius * Math.cos(angle)).toFixed(2)},${(
      cy +
      radius * Math.sin(angle)
    ).toFixed(2)}`;
  const large = end - start > Math.PI ? 1 : 0;
  return [
    `M ${point(outer, start)}`,
    `A ${outer} ${outer} 0 ${large} 1 ${point(outer, end)}`,
    `L ${point(inner, end)}`,
    `A ${inner} ${inner} 0 ${large} 0 ${point(inner, start)}`,
    "Z",
  ].join(" ");
}

function PieChart({
  slices,
  width,
}: {
  slices: PieSlice[];
  width: number;
}) {
  const total = slices.reduce((sum, slice) => sum + slice.value, 0) || 1;
  const cx = width / 2;
  const cy = H / 2;
  const outer = Math.min(76, H / 2 - 8);
  const inner = outer * 0.56;
  let angle = -Math.PI / 2;
  return (
    <svg viewBox={`0 0 ${width} ${H}`} className="sa-chart" role="img">
      {slices.map((slice) => {
        const sweep = (slice.value / total) * Math.PI * 2;
        const start = angle;
        const end = angle + sweep;
        angle = end;
        return (
          <path
            key={slice.label}
            d={arcPath(cx, cy, outer, inner, start, end)}
            fill={slice.color}
          >
            <title>{`${slice.label}: ${short(slice.value)}（${slice.pct.toFixed(1)}%）`}</title>
          </path>
        );
      })}
      <text x={cx} y={cy - 2} textAnchor="middle" className="sa-chart-center">
        {short(total)}
      </text>
      <text x={cx} y={cy + 12} textAnchor="middle" className="sa-chart-tick">
        合计
      </text>
    </svg>
  );
}

export function hasChart(
  rows: Record<string, any>[],
  columns: { name: string; type?: string | null }[],
  labels?: Record<string, string>,
): boolean {
  return classifyAll(rows, columns, labels).length > 0;
}

export type KpiCard = {
  metric: string;
  label: string;
  value: number;
  formatted: string;
  /** 单行里的维度值（如「区域 east」），没有维度时为空 */
  hint?: string;
};

function formatKpi(value: number): string {
  if (Number.isInteger(value)) return value.toLocaleString("zh-CN");
  return value.toLocaleString("zh-CN", {
    maximumFractionDigits: Math.abs(value) >= 100 ? 1 : 2,
  });
}

/**
 * 单行结果用大数字卡展示：每个数值列一张，维度值作为副标题。
 * 两行及以上仍交给图表（只有一个点的序列画图没有意义）。
 */
export function kpiCards(
  rows: Record<string, any>[],
  columns: { name: string; type?: string | null }[],
  labels?: Record<string, string>,
): KpiCard[] {
  if (rows.length !== 1) return [];
  const row = rows[0] ?? {};
  const names = columns.length ? columns.map((c) => c.name) : Object.keys(row);
  const numeric = names.filter((name) => toNumber(row[name]) !== null);
  if (!numeric.length) return [];
  const dimension = names.find((name) => !numeric.includes(name));
  const hint =
    dimension === undefined
      ? undefined
      : `${labels?.[dimension] || dimension} ${String(row[dimension] ?? "—")}`;
  return numeric.map((name) => {
    const value = toNumber(row[name]) as number;
    return {
      metric: name,
      label: labels?.[name] || name,
      value,
      formatted: formatKpi(value),
      hint,
    };
  });
}

/** 有图或有大数字卡：调用方据此决定是否渲染 ChartBlock。 */
export function hasVisual(
  rows: Record<string, any>[],
  columns: { name: string; type?: string | null }[],
  labels?: Record<string, string>,
): boolean {
  return (
    classifyAll(rows, columns, labels).length > 0 ||
    kpiCards(rows, columns, labels).length > 0
  );
}

const GRID_GAP = 10;
const MIN_CELL = 110;

/** 宽度够就并排 2–3 张（1366 浮窗 2、停靠/全屏 3），窄屏回落单列。 */
function columnCount(count: number, width: number): number {
  if (count <= 1) return 1;
  if (width >= 700) return Math.min(3, count);
  if (width >= 250) return Math.min(2, count);
  return 1;
}

/** 单行结果的大数字卡：多指标按容器宽度并排，窄面板单列。 */
export function KpiGrid({
  cards,
  width: fixedWidth,
}: {
  cards: KpiCard[];
  width?: number;
}) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [measured, setMeasured] = useState(0);
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return undefined;
    const update = () => setMeasured(Math.round(el.clientWidth));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [cards.length]);
  if (!cards.length) return null;
  const container = fixedWidth ?? Math.max(MIN_W, measured || FALLBACK_W);
  const cols = columnCount(cards.length, container);
  return (
    <div
      className="sa-kpi-grid"
      ref={wrapRef}
      style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
    >
      {cards.map((card) => (
        <div className="sa-kpi-card" key={card.metric}>
          <div className="sa-kpi-label" title={card.label}>
            {card.label}
          </div>
          <div className="sa-kpi-value" title={card.formatted}>
            {card.formatted}
          </div>
          {card.hint ? <div className="sa-kpi-hint">{card.hint}</div> : null}
        </div>
      ))}
    </div>
  );
}

export function ChartViz({
  rows,
  columns,
  labels,
  width: fixedWidth,
  chartType,
  only,
  onSelectMetric,
}: {
  rows: Record<string, any>[];
  columns: { name: string; type?: string | null }[];
  labels?: Record<string, string>;
  width?: number;
  chartType?: string;
  /** 只渲染指定指标（放大用） */
  only?: string;
  /** 传入后每张图可点击放大 */
  onSelectMetric?: (metric: string) => void;
}) {
  const models = useMemo(() => {
    const all = classifyAll(rows, columns, labels, chartType);
    return only ? all.filter((model) => model.metric === only) : all;
  }, [rows, columns, labels, chartType, only]);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [measured, setMeasured] = useState(0);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return undefined;
    const update = () => setMeasured(Math.round(el.clientWidth));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [models.length]);

  if (!models.length) return null;
  const container = fixedWidth ?? Math.max(MIN_W, measured || FALLBACK_W);
  const cols = columnCount(models.length, container);
  const cellWidth = Math.max(
    MIN_CELL,
    Math.floor((container - GRID_GAP * (cols - 1)) / cols),
  );
  return (
    <div
      className="sa-chart-multi"
      ref={wrapRef}
      style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
    >
      {models.map((model) => {
        const label = model.series[0]?.label ?? model.metric;
        const slices = model.kind === "pie" ? pieSlices(model) : [];
        const isPie = model.kind === "pie" && slices.length > 0;
        const clickable = typeof onSelectMetric === "function";
        return (
          <div
            key={model.metric}
            className={`sa-chart-wrap${clickable ? " is-clickable" : ""}`}
            role={clickable ? "button" : undefined}
            tabIndex={clickable ? 0 : undefined}
            aria-label={clickable ? `放大查看 ${label}` : undefined}
            title={clickable ? "点击放大图表" : undefined}
            onClick={
              clickable ? () => onSelectMetric?.(model.metric) : undefined
            }
            onKeyDown={
              clickable
                ? (event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onSelectMetric?.(model.metric);
                    }
                  }
                : undefined
            }
          >
            {models.length > 1 || only ? (
              <div className="sa-chart-metric" title={label}>
                {label}
              </div>
            ) : null}
            {isPie ? (
              <div className="sa-chart-legend-row sa-chart-legend-pie">
                {slices.map((slice) => (
                  <span
                    className="sa-chart-legend-item"
                    key={slice.label}
                    title={`${slice.label} · ${short(slice.value)}（${slice.pct.toFixed(1)}%）`}
                  >
                    <i style={{ background: slice.color }} />
                    <span className="sa-chart-legend-label">{slice.label}</span>
                    <span className="sa-chart-legend-val">
                      {short(slice.value)} · {slice.pct.toFixed(1)}%
                    </span>
                  </span>
                ))}
              </div>
            ) : model.series.length > 1 ? (
              <div className="sa-chart-legend-row">
                {model.series.map((s, index) => (
                  <span className="sa-chart-legend-item" key={s.name} title={s.label}>
                    <i style={{ background: PALETTE[index % PALETTE.length] }} />
                    <span className="sa-chart-legend-label">{s.label}</span>
                  </span>
                ))}
              </div>
            ) : null}
            {isPie ? (
              <PieChart slices={slices} width={cellWidth} />
            ) : model.kind === "line" ? (
              <LineChart model={model} width={cellWidth} />
            ) : (
              <BarChart model={model} width={cellWidth} />
            )}
          </div>
        );
      })}
    </div>
  );
}

export default ChartViz;

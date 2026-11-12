import React, { useEffect, useMemo, useRef, useState } from "react";

import { ToolLikePart } from "./types";
import { WriteActionCard, type WriteProposal } from "./WriteActionCard";
import { ChartViz } from "./ChartViz";

const TOOL_LABELS: Record<string, string> = {
  list_datasets: "检索数据集",
  get_dataset_info: "读取数据集结构",
  get_dashboard_info: "读取看板信息",
  search_metadata: "检索元数据",
  query_dataset: "数据集查询",
  run_sql: "执行 SQL",
  list_dashboards: "看板列表",
  list_charts: "图表列表",
  mcp_search: "发现 MCP 工具",
  mcp_call: "调用 MCP 工具",
  period_compare: "环比 / 同比",
  dimension_contribution: "维度贡献",
  structure_effect: "结构效应",
  trend_forecast: "趋势预测",
  search_knowledge: "检索知识库",
  list_knowledge: "知识库目录",
  save_knowledge: "保存知识",
  delete_knowledge: "删除知识",
  propose_write: "写操作方案",
};

function labelOf(name: string): string {
  return TOOL_LABELS[name] ?? name;
}

function truncate(value: string, length: number): string {
  return value.length > length ? `${value.slice(0, length)}…` : value;
}

function formatNumber(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return "—";
    const abs = Math.abs(value);
    // p 值与比率效应可能极小，定点两位小数会把它们抹成 0
    if (value !== 0 && abs < 0.0001) return value.toExponential(2);
    if (value !== 0 && abs < 1) return String(Number(value.toPrecision(4)));
    if (Number.isInteger(value)) return value.toLocaleString("zh-CN");
    return value.toLocaleString("zh-CN", {
      minimumFractionDigits: 0,
      maximumFractionDigits: 2,
    });
  }
  return String(value);
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return formatNumber(value);
  if (typeof value === "object") return JSON.stringify(value);
  const text = String(value);
  return text.length > 80 ? `${text.slice(0, 80)}…` : text;
}

function textList(value: unknown): string[] {
  if (typeof value === "string") return value ? [value] : [];
  if (!Array.isArray(value)) return [];
  return value.map((item) => {
    if (typeof item === "string") return item;
    if (item && typeof item === "object") {
      const record = item as Record<string, unknown>;
      const label = record.name ?? record.label ?? record.metric_name;
      if (typeof label === "string") return label;
    }
    return String(item);
  });
}

function dimText(value: unknown): string {
  const list = textList(value);
  return list.length ? ` · 按 ${list.join(" × ")}` : "";
}

function inputSummary(name: string, input: unknown): string {
  const value = (input ?? {}) as Record<string, any>;
  switch (name) {
    case "query_dataset": {
      const metrics = textList(value.metrics);
      const columns = textList(value.columns);
      return `#${value.dataset_id ?? "?"} · ${metrics.join(", ") || "无指标"}${
        columns.length ? ` · 按 ${columns.join(", ")}` : ""
      }`;
    }
    case "run_sql":
      return truncate(String(value.sql ?? ""), 80);
    case "period_compare":
      return `${value.metric ?? "指标"} · ${value.base_start ?? "?"} ~ ${
        value.base_end ?? "?"
      } vs ${value.current_start ?? "?"} ~ ${value.current_end ?? "?"}${
        dimText(value.dimensions ?? value.dimension)
      }`;
    case "dimension_contribution":
      return `${value.metric ?? "指标"}${dimText(value.dimensions ?? value.dimension) || " · 按 ?"}`;
    case "structure_effect":
      return `${value.numerator_metric ?? "?"} / ${
        value.denominator_metric ?? "?"
      }${dimText(value.dimensions ?? value.dimension) || " · 按 ?"}`;
    case "trend_forecast":
      return `${value.metric ?? "指标"} · ${value.start ?? "?"} ~ ${
        value.end ?? "?"
      } → 未来 ${value.horizon_days ?? 7} 天`;
    case "list_datasets":
      return value.search ? `搜索：${value.search}` : "全部数据集";
    case "get_dataset_info":
      return `数据集 #${value.dataset_id ?? "?"}`;
    case "get_dashboard_info":
      return `看板 #${value.dashboard_id ?? "?"}`;
    case "list_dashboards":
      return value.search ? `搜索看板：${value.search}` : "全部看板";
    case "list_charts":
      return value.search ? `搜索图表：${value.search}` : "全部图表";
    case "mcp_search":
      return value.query ? `检索：${value.query}` : "列出基础工具";
    case "mcp_call": {
      const inner = String(value.tool_name ?? "");
      return TOOL_LABELS[inner] ? `${TOOL_LABELS[inner]} · ${inner}` : inner;
    }
    case "search_metadata":
      return `检索：${value.query ?? "?"}`;
    case "search_knowledge":
      return `检索：${value.query ?? "?"}`;
    case "propose_write":
      return truncate(String(value.summary ?? value.action_type ?? ""), 80);
    default:
      return "";
  }
}

function DataTable({
  rows,
  columns,
  labels,
}: {
  rows: unknown;
  columns?: unknown;
  labels?: Record<string, string>;
}) {
  const list = Array.isArray(rows) ? rows : [];
  const columnNames = useMemo(() => {
    if (Array.isArray(columns) && columns.length > 0) {
      return columns
        .map((column) =>
          typeof column === "string"
            ? column
            : (column as Record<string, unknown>)?.name,
        )
        .filter((name): name is string => typeof name === "string");
    }
    if (list.length > 0 && list[0] && typeof list[0] === "object") {
      return Object.keys(list[0] as Record<string, unknown>);
    }
    return [];
  }, [columns, list]);

  if (list.length === 0) {
    return <div className="sa-tool-summary">没有返回行。</div>;
  }
  const visible = list.slice(0, 100);
  return (
    <div className="sa-table-wrap">
      <table className="sa-table">
        <thead>
          <tr>
            {columnNames.map((column) => (
              <th key={column}>{labels?.[column] || column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {visible.map((row, index) => {
            const record = (row ?? {}) as Record<string, unknown>;
            return (
              <tr key={index}>
                {columnNames.map((column) => {
                  const value = record[column];
                  const numeric = typeof value === "number";
                  return (
                    <td
                      key={column}
                      className={numeric ? "sa-num" : undefined}
                      title={typeof value === "string" ? value : undefined}
                    >
                      {formatCell(value)}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
      {list.length > visible.length ? (
        <div className="sa-table-more">
          仅显示前 {visible.length} 行，共 {list.length} 行
        </div>
      ) : null}
    </div>
  );
}

function Warnings({ warnings }: { warnings: unknown }) {
  if (!Array.isArray(warnings) || warnings.length === 0) return null;
  return (
    <>
      {warnings.map((warning, index) => (
        <div className="sa-warning" key={index}>
          {String(warning)}
        </div>
      ))}
    </>
  );
}

function Bars({
  rows,
  valueKey = "delta",
  labelKey = "member",
  detailKey = "contribution_pct",
}: {
  rows: unknown;
  valueKey?: string;
  labelKey?: string;
  detailKey?: string;
}) {
  const list = Array.isArray(rows) ? (rows as Record<string, any>[]) : [];
  const maxAbs = Math.max(
    1,
    ...list.map((row) => Math.abs(Number(row[valueKey] ?? 0))),
  );
  return (
    <div className="sa-bars">
      {list.map((row, index) => {
        const value = Number(row[valueKey] ?? 0);
        const detail = row[detailKey];
        const width = Math.min(100, (Math.abs(value) / maxAbs) * 100);
        return (
          <div className="sa-bar-row" key={index}>
            <div className="sa-bar-label" title={String(row[labelKey] ?? "")}>
              {String(row[labelKey] ?? "—")}
            </div>
            <div className="sa-bar-track">
              <div
                className={`sa-bar-fill ${value < 0 ? "sa-neg" : "sa-pos"}`}
                style={{ width: `${width}%` }}
              />
            </div>
            <div className="sa-bar-value">
              {value >= 0 ? "+" : ""}
              {formatNumber(value)}
              {detail !== undefined && detail !== null
                ? ` (${formatNumber(detail)}%)`
                : ""}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Waterfall({ output }: { output: Record<string, any> }) {
  const structure = Number(output.structure_effect ?? 0);
  const efficiency = Number(output.efficiency_effect ?? 0);
  const interaction = Number(output.interaction_effect ?? 0);
  const total = Number(output.total_delta ?? 0);
  const steps = [
    { label: "结构效应", start: 0, end: structure },
    { label: "效率效应", start: structure, end: structure + efficiency },
    {
      label: "交互项",
      start: structure + efficiency,
      end: structure + efficiency + interaction,
    },
    { label: "总变化", start: 0, end: total, isTotal: true },
  ];
  const values = [0, total, ...steps.flatMap((s) => [s.start, s.end])];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(max - min, 1e-9);
  const pct = (value: number) => ((value - min) / span) * 100;

  return (
    <div className="sa-waterfall">
      {steps.map((step) => {
        const top = Math.max(pct(step.start), pct(step.end));
        const bottom = Math.min(pct(step.start), pct(step.end));
        const value = step.end - step.start;
        return (
          <div className="sa-wf-col" key={step.label}>
            <div className="sa-wf-val">
              {value >= 0 ? "+" : ""}
              {value.toFixed(4)}
            </div>
            <div className="sa-wf-plot">
              <div
                className={`sa-wf-bar ${
                  step.isTotal
                    ? "sa-wf-bar-total"
                    : value >= 0
                      ? "sa-wf-bar-pos"
                      : "sa-wf-bar-neg"
                }`}
                style={{ top: `${100 - top}%`, height: `${Math.max(top - bottom, 1.5)}%` }}
              />
              <div className="sa-wf-zero" style={{ top: `${100 - pct(0)}%` }} />
            </div>
            <div className="sa-wf-label">{step.label}</div>
          </div>
        );
      })}
    </div>
  );
}

function CompareTable({ rows }: { rows: unknown }) {
  const list = (Array.isArray(rows) ? rows : []) as Array<Record<string, any>>;
  if (list.length === 0) {
    return <div className="sa-tool-summary">没有返回行。</div>;
  }
  const hasContribution = list.some(
    (row) => row.contribution_pct !== undefined && row.contribution_pct !== null,
  );
  const hasPull = list.some(
    (row) => row.pull_pp !== undefined && row.pull_pp !== null,
  );
  const deltaCell = (value: unknown) =>
    typeof value === "number" ? (
      <span className={value >= 0 ? "sa-delta-pos" : "sa-delta-neg"}>
        {value >= 0 ? "+" : ""}
        {formatNumber(value)}
      </span>
    ) : (
      <>—</>
    );
  return (
    <div className="sa-table-wrap">
      <table className="sa-table">
        <thead>
          <tr>
            <th>成员</th>
            <th>基期</th>
            <th>本期</th>
            <th>变化</th>
            <th>变化率</th>
            {hasContribution ? <th>贡献率</th> : null}
            {hasPull ? <th>拉动 pp</th> : null}
          </tr>
        </thead>
        <tbody>
          {list.map((row, index) => (
            <tr key={index}>
              <td title={String(row.member ?? "")}>{String(row.member ?? "—")}</td>
              <td className="sa-num">{formatNumber(row.base)}</td>
              <td className="sa-num">{formatNumber(row.current)}</td>
              <td className="sa-num">{deltaCell(row.delta)}</td>
              <td className="sa-num">
                {typeof row.pct_change === "number"
                  ? `${row.pct_change >= 0 ? "+" : ""}${row.pct_change}%`
                  : "—"}
              </td>
              {hasContribution ? (
                <td className="sa-num">
                  {typeof row.contribution_pct === "number"
                    ? `${row.contribution_pct}%`
                    : "—"}
                </td>
              ) : null}
              {hasPull ? (
                <td className="sa-num">
                  {typeof row.pull_pp === "number"
                    ? `${row.pull_pp >= 0 ? "+" : ""}${row.pull_pp}`
                    : "—"}
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const WINDOW_FIELDS: Array<[string, string]> = [
  ["日历天数", "expected_days"],
  ["有数据天数", "observed_days"],
  ["覆盖率 %", "coverage_pct"],
  ["总量", "total"],
  ["日历天日均", "daily_avg"],
  ["有数据日日均", "observed_daily_avg"],
  ["日标准差", "daily_std"],
  ["变异系数 %", "cv_pct"],
  ["最小日值", "min_daily"],
  ["最大日值", "max_daily"],
];

function WindowNotes({ output }: { output: Record<string, any> }) {
  const base = (output.base_stats ?? {}) as Record<string, any>;
  const current = (output.current_stats ?? {}) as Record<string, any>;
  const sig = output.significance as Record<string, any> | null | undefined;
  const hasStats = Object.keys(base).length > 0 || Object.keys(current).length > 0;
  if (!hasStats && !sig) return null;
  return (
    <details className="sa-table-more sa-stat-notes">
      <summary>统计口径与检验</summary>
      {output.basis_reason ? (
        <div className="sa-stat-line">{String(output.basis_reason)}</div>
      ) : null}
      {hasStats ? (
        <div className="sa-table-wrap">
          <table className="sa-table">
            <thead>
              <tr>
                <th>窗口统计</th>
                <th>基期</th>
                <th>本期</th>
              </tr>
            </thead>
            <tbody>
              {WINDOW_FIELDS.map(([label, key]) => (
                <tr key={key}>
                  <td>{label}</td>
                  <td className="sa-num">{formatNumber(base[key])}</td>
                  <td className="sa-num">{formatNumber(current[key])}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {sig ? (
        <div className="sa-stat-line">
          {String(sig.method ?? "")}：t={formatNumber(sig.t)}，df=
          {formatNumber(sig.df)}，p={formatNumber(sig.p_value)}，α=
          {formatNumber(sig.alpha)} → {String(sig.verdict ?? "")}
          {sig.caveat ? (
            <div className="sa-stat-caveat">{String(sig.caveat)}</div>
          ) : null}
        </div>
      ) : null}
    </details>
  );
}

function NoteLines({ title, lines }: { title: string; lines: string[] }) {
  const visible = lines.filter((line) => line.trim().length > 0);
  if (!visible.length) return null;
  return (
    <details className="sa-table-more sa-stat-notes">
      <summary>{title}</summary>
      {visible.map((line, index) => (
        <div className="sa-stat-line" key={index}>
          {line}
        </div>
      ))}
    </details>
  );
}

function axisNumber(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
  if (abs >= 1e4) return `${(value / 1e3).toFixed(0)}k`;
  if (abs >= 1) return value.toFixed(0);
  return String(Number(value.toPrecision(2)));
}

function ForecastChart({
  history,
  forecast,
  label,
}: {
  history: Array<Record<string, any>>;
  forecast: Array<Record<string, any>>;
  label: string;
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
  }, []);

  const points = useMemo(() => {
    const past = history.map((row) => ({
      date: String(row.date ?? ""),
      value: Number(row.value ?? 0),
      lower: null as number | null,
      upper: null as number | null,
    }));
    const future = forecast.map((row) => ({
      date: String(row.date ?? ""),
      value: Number(row.yhat ?? 0),
      lower: Number(row.lower ?? 0),
      upper: Number(row.upper ?? 0),
    }));
    return [...past, ...future];
  }, [history, forecast]);

  const width = Math.max(260, measured || 420);
  if (points.length < 2) return <div className="sa-chart-wrap" ref={wrapRef} />;

  const H = 200;
  const PAD_L = 52;
  const PAD_R = 14;
  const PAD_T = 14;
  const PAD_B = 30;
  const plotW = width - PAD_L - PAD_R;
  const plotH = H - PAD_T - PAD_B;
  const values = points.flatMap((p) =>
    [p.value, p.lower ?? p.value, p.upper ?? p.value].filter(Number.isFinite),
  );
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (max - min < 1e-9) max = min + 1;
  const pad = (max - min) * 0.08;
  min -= pad;
  max += pad;
  const x = (index: number) => PAD_L + (index / (points.length - 1)) * plotW;
  const y = (value: number) => PAD_T + (1 - (value - min) / (max - min)) * plotH;

  const split = history.length;
  const lastPast = points[split - 1];
  const band = [
    ...(lastPast ? [{ ...lastPast, lower: lastPast.value, upper: lastPast.value }] : []),
    ...points.slice(split),
  ];
  const bandPath = band.length > 1
    ? `M ${band.map((p, i) => `${x(split - 1 + i)},${y(p.upper ?? p.value)}`).join(" L ")} L ${band
        .map((p, i) => `${x(split - 1 + band.length - 1 - i)},${y(band[band.length - 1 - i].lower ?? band[band.length - 1 - i].value)}`)
        .join(" L ")} Z`
    : "";
  const pastLine = points
    .slice(0, split)
    .map((p, i) => `${i === 0 ? "M" : "L"} ${x(i)},${y(p.value)}`)
    .join(" ");
  const futureLine = [
    ...(lastPast ? [lastPast] : []),
    ...points.slice(split),
  ]
    .map((p, i) => `${i === 0 ? "M" : "L"} ${x(split - 1 + i)},${y(p.value)}`)
    .join(" ");

  const ticks = [0, 1, 2, 3].map((i) => min + ((max - min) * i) / 3);
  const maxLabels = Math.max(2, Math.floor(plotW / 64));
  const step = Math.max(1, Math.ceil(points.length / maxLabels));
  // 从最后一个点向前等距取，避免末尾标签与前一个挤在一起
  const labelIndexes: number[] = [];
  for (let i = points.length - 1; i >= 0; i -= step) labelIndexes.unshift(i);

  return (
    <div className="sa-chart-wrap" ref={wrapRef}>
      <div className="sa-chart-metric" title={label}>{label}</div>
      <div className="sa-chart-legend-row">
        <span className="sa-chart-legend-item">
          <i style={{ background: "var(--sa-accent)" }} />
          <span className="sa-chart-legend-label">历史</span>
        </span>
        <span className="sa-chart-legend-item">
          <i className="sa-forecast-dash" />
          <span className="sa-chart-legend-label">预测</span>
        </span>
        <span className="sa-chart-legend-item">
          <i className="sa-forecast-band" />
          <span className="sa-chart-legend-label">95% 区间</span>
        </span>
      </div>
      <svg viewBox={`0 0 ${width} ${H}`} className="sa-chart" role="img" aria-label={`${label} 历史与预测`}>
        {ticks.map((tick, i) => (
          <g key={i}>
            <line x1={PAD_L} x2={width - PAD_R} y1={y(tick)} y2={y(tick)} className="sa-chart-grid" />
            <text x={PAD_L - 5} y={y(tick) + 3} className="sa-chart-tick" textAnchor="end">
              {axisNumber(tick)}
            </text>
          </g>
        ))}
        {bandPath ? <path d={bandPath} className="sa-forecast-area" /> : null}
        {split > 0 && split < points.length ? (
          <line x1={x(split - 1)} x2={x(split - 1)} y1={PAD_T} y2={H - PAD_B} className="sa-forecast-split" />
        ) : null}
        {pastLine ? <path d={pastLine} className="sa-forecast-past" /> : null}
        {futureLine ? <path d={futureLine} className="sa-forecast-future" /> : null}
        <line x1={PAD_L} x2={width - PAD_R} y1={H - PAD_B} y2={H - PAD_B} className="sa-chart-axis" />
        {labelIndexes.map((i) => (
          <text
            key={i}
            x={x(i)}
            y={H - PAD_B + 14}
            className="sa-chart-tick"
            textAnchor={
              x(i) < PAD_L + 18 ? "start" : x(i) > width - PAD_R - 18 ? "end" : "middle"
            }
          >
            {points[i].date.slice(5)}
          </text>
        ))}
      </svg>
    </div>
  );
}

function SqlBlock({ sql }: { sql: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <pre className="sa-sql">
      {sql}
      <button
        type="button"
        className="sa-copy"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(sql);
            setCopied(true);
            setTimeout(() => setCopied(false), 1200);
          } catch {
            setCopied(false);
          }
        }}
      >
        {copied ? "已复制" : "复制"}
      </button>
    </pre>
  );
}

function Kpi({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="sa-badge">
      <span style={{ color: "var(--sa-fg-muted)", marginRight: 4 }}>{label}</span>
      {formatNumber(value)}
    </div>
  );
}

function renderOutput(name: string, output: unknown, showChart = true) {
  if (output === null || output === undefined) return null;
  if (typeof output === "string") {
    return <pre className="sa-sql">{output}</pre>;
  }
  const data = output as Record<string, any>;
  switch (name) {
    case "list_datasets": {
      const datasets = Array.isArray(data.datasets) ? data.datasets : [];
      return (
        <>
          <div className="sa-badges">
            <span className="sa-badge sa-badge-accent">
              {data.count ?? datasets.length} 个数据集
            </span>
          </div>
          <DataTable rows={datasets} columns={["id", "name", "schema", "database"]} />
        </>
      );
    }
    case "get_dataset_info": {
      const columns = Array.isArray(data.columns) ? data.columns : [];
      const metrics = Array.isArray(data.metrics) ? data.metrics : [];
      return (
        <>
          <div className="sa-badges">
            <span className="sa-badge sa-badge-accent">{data.name ?? "数据集"}</span>
            {data.main_dttm_col ? (
              <span className="sa-badge">时间列 {data.main_dttm_col}</span>
            ) : null}
            {data.database ? <span className="sa-badge">{data.database}</span> : null}
          </div>
          <div className="sa-badges">
            {columns.slice(0, 40).map((column: any, index: number) => (
              <span className="sa-badge" key={`${column.name}-${index}`}>
                {column.name}
                {column.type ? ` · ${column.type}` : ""}
              </span>
            ))}
            {columns.length > 40 ? (
              <span className="sa-badge">+{columns.length - 40} 列</span>
            ) : null}
          </div>
          <div className="sa-badges">
            {metrics.slice(0, 30).map((metric: any, index: number) => (
              <span className="sa-badge sa-badge-accent" key={`${metric.name}-${index}`}>
                {metric.name}
                {metric.expression ? ` = ${metric.expression}` : ""}
              </span>
            ))}
          </div>
          <Warnings warnings={data.warnings} />
        </>
      );
    }
    case "get_dashboard_info": {
      const charts = Array.isArray(data.charts) ? data.charts : [];
      return (
        <>
          <div className="sa-badges">
            <span className="sa-badge sa-badge-accent">
              {data.title || "看板"}
            </span>
            <span className="sa-badge">#{data.id}</span>
            <span className="sa-badge">{data.chart_count ?? charts.length} 个图表</span>
          </div>
          {Array.isArray(data.native_filters) && data.native_filters.length > 0 ? (
            <div className="sa-badges">
              {data.native_filters.slice(0, 20).map((filter: any, index: number) => (
                <span className="sa-badge" key={index}>
                  {filter.name || filter.id || "筛选器"}
                  {filter.filter_type ? ` · ${filter.filter_type}` : ""}
                </span>
              ))}
            </div>
          ) : null}
          <DataTable rows={charts} columns={["id", "name", "viz_type", "datasource_name"]} />
          {data.filter_state ? (
            <details className="sa-table-more">
              <summary style={{ cursor: "pointer" }}>筛选状态</summary>
              <pre className="sa-sql" style={{ marginTop: 6 }}>
                {JSON.stringify(data.filter_state, null, 2)}
              </pre>
            </details>
          ) : null}
        </>
      );
    }
    case "search_metadata": {
      const datasets = Array.isArray(data.datasets) ? data.datasets : [];
      const candidates = Array.isArray(data.candidates) ? data.candidates : [];
      return (
        <>
          <div className="sa-badges">
            <span className="sa-badge">检索 {String(data.query ?? "")}</span>
            <span className="sa-badge sa-badge-accent">{datasets.length} 个匹配数据集</span>
            {candidates.length ? (
              <span className="sa-badge">目录 {candidates.length} 个</span>
            ) : null}
          </div>
          {datasets.map((dataset: any, index: number) => (
            <div key={index} className="sa-table-more">
              <strong>{dataset.name}</strong>（#{dataset.id}）
              {dataset.main_dttm_col ? ` · 时间列 ${dataset.main_dttm_col}` : ""}
              {Array.isArray(dataset.columns)
                ? ` · ${dataset.columns.length} 列 / ${dataset.metrics?.length ?? 0} 个指标`
                : ""}
              {Array.isArray(dataset.matched_in) && dataset.matched_in.length
                ? ` · 命中 ${dataset.matched_in.join("、")}`
                : ""}
            </div>
          ))}
          {!datasets.length && candidates.length ? (
            <div className="sa-table-more">
              没有命名字段匹配到这个说法，以下数据集目录仍可查：
              {candidates.map((item: any) => `${item.name}（#${item.id}）`).join("、")}
            </div>
          ) : null}
          <Warnings warnings={data.warnings} />
        </>
      );
    }
    case "query_dataset": {
      return (
        <>
          <div className="sa-badges">
            <span className="sa-badge sa-badge-accent">RLS 生效</span>
            <span className="sa-badge">{data.dataset_name ?? "数据集"}</span>
            <span className="sa-badge">{data.row_count ?? 0} 行</span>
            {data.from_dttm ? (
              <span className="sa-badge">
                {data.from_dttm} ~ {data.to_dttm ?? "?"}
              </span>
            ) : null}
          </div>
          <Warnings warnings={data.warnings} />
          {showChart ? (
            <ChartViz rows={data.rows} columns={data.columns} labels={data.labels} />
          ) : null}
          <DataTable
            rows={data.rows}
            columns={data.columns}
            labels={data.labels}
          />
        </>
      );
    }
    case "run_sql": {
      return (
        <>
          <div className="sa-badges">
            <span className="sa-badge sa-badge-accent">仅 Admin 可用</span>
            <span className="sa-badge">{data.row_count ?? 0} 行</span>
            {data.truncated ? <span className="sa-badge">已截断</span> : null}
          </div>
          <Warnings warnings={data.warnings} />
          <SqlBlock sql={String(data.sql ?? "")} />
          {showChart ? (
            <ChartViz rows={data.rows} columns={data.columns} labels={data.labels} />
          ) : null}
          <DataTable
            rows={data.rows}
            columns={data.columns}
            labels={data.labels}
          />
        </>
      );
    }
    case "list_dashboards": {
      const dashboards = Array.isArray(data.dashboards) ? data.dashboards : [];
      return (
        <>
          <div className="sa-badges">
            <span className="sa-badge sa-badge-accent">
              {data.count ?? dashboards.length} 个看板
            </span>
          </div>
          <DataTable
            rows={dashboards}
            columns={["id", "title", "slug", "published", "url"]}
          />
        </>
      );
    }
    case "list_charts": {
      const charts = Array.isArray(data.charts) ? data.charts : [];
      return (
        <>
          <div className="sa-badges">
            <span className="sa-badge sa-badge-accent">
              {data.count ?? charts.length} 个图表
            </span>
          </div>
          <DataTable rows={charts} columns={["id", "name", "viz_type", "url"]} />
        </>
      );
    }
    case "mcp_call": {
      const inner =
        data && typeof data === "object" && "result" in data
          ? (data as any).result
          : data;
      const notes =
        data && typeof data === "object" && Array.isArray((data as any).notes)
          ? ((data as any).notes as string[])
          : [];
      if (Array.isArray((inner as any)?.rows) || Array.isArray((inner as any)?.data)) {
        const rows = (inner as any).rows ?? (inner as any).data;
        return (
          <>
            <div className="sa-badges">
              <span className="sa-badge sa-badge-accent">以你的 Superset 权限执行</span>
            </div>
            {notes.length ? <Warnings warnings={notes} /> : null}
            {showChart ? (
              <ChartViz rows={rows} columns={(inner as any).columns ?? []} />
            ) : null}
            <DataTable rows={rows} columns={(inner as any).columns ?? []} />
          </>
        );
      }
      return (
        <>
          {notes.length ? <Warnings warnings={notes} /> : null}
          <pre className="sa-sql">{JSON.stringify(inner, null, 2)}</pre>
        </>
      );
    }
    case "mcp_search": {
      const tools = Array.isArray((data as any).tools)
        ? ((data as any).tools as Record<string, any>[])
        : [];
      return (
        <>
          <div className="sa-badges">
            <span className="sa-badge">{tools.length} 个可用工具</span>
            <span className="sa-badge">已按你的权限过滤</span>
          </div>
          <DataTable
            rows={tools.map((tool) => ({
              name: tool.name,
              title: tool.title,
              access: tool.destructive
                ? "破坏性写入"
                : tool.read_only
                  ? "只读"
                  : "写入",
              description: String(tool.description ?? "").slice(0, 80),
            }))}
            columns={["name", "title", "access", "description"]}
          />
        </>
      );
    }
    case "period_compare": {
      const rows = Array.isArray(data.rows) ? data.rows : [];
      const sig = data.significance as Record<string, any> | null | undefined;
      const daily = data.basis === "daily_avg";
      return (
        <>
          <div className="sa-badges">
            <span className="sa-badge sa-badge-accent">基期 {data.base_period}</span>
            <span className="sa-badge sa-badge-accent">本期 {data.current_period}</span>
            <span className="sa-badge">{daily ? "口径 日历天日均" : "口径 总量"}</span>
            {data.dimension ? (
              <span className="sa-badge">维度 {String(data.dimension)}</span>
            ) : null}
            {sig ? (
              <span className={`sa-badge ${sig.significant ? "sa-badge-accent" : ""}`}>
                {String(sig.verdict ?? "")} · p={formatNumber(sig.p_value)}
              </span>
            ) : null}
          </div>
          <div>{String(data.summary ?? "")}</div>
          <Warnings warnings={data.warnings} />
          {rows.length === 1 && !("member" in (rows[0] ?? {})) ? (
            <div className="sa-badges">
              <Kpi label={daily ? "基期日均" : "基期"} value={rows[0].base} />
              <Kpi label={daily ? "本期日均" : "本期"} value={rows[0].current} />
              <Kpi label="变化" value={rows[0].delta} />
              <Kpi label="变化率" value={rows[0].pct_change} />
              {daily ? (
                <>
                  <Kpi label="基期总量" value={rows[0].base_total} />
                  <Kpi label="本期总量" value={rows[0].current_total} />
                </>
              ) : null}
            </div>
          ) : (
            <CompareTable rows={rows} />
          )}
          <WindowNotes output={data} />
        </>
      );
    }
    case "dimension_contribution": {
      const concentration = data.concentration as Record<string, any> | null | undefined;
      const offsetting = data.offsetting as Record<string, any> | undefined;
      const ranking = Array.isArray(data.dimension_ranking) ? data.dimension_ranking : [];
      const offsetRatio = Number(offsetting?.offset_ratio ?? 0);
      return (
        <>
          <div className="sa-badges">
            <span className="sa-badge sa-badge-accent">维度 {data.dimension}</span>
            <span className="sa-badge">总变化 {formatNumber(data.total_delta)}</span>
            <span className="sa-badge">
              {data.basis === "daily_avg" ? "口径 日历天日均" : "口径 总量"}
            </span>
            {concentration?.verdict ? (
              <span className="sa-badge">{String(concentration.verdict)}</span>
            ) : null}
            {offsetRatio >= 0.3 ? (
              <span className="sa-badge">
                正负抵消 {(offsetRatio * 100).toFixed(0)}%
              </span>
            ) : null}
          </div>
          <div>{String(data.summary ?? "")}</div>
          <Warnings warnings={data.warnings} />
          <Bars rows={data.rows} />
          <CompareTable rows={data.rows} />
          {ranking.length > 1 ? (
            <DataTable
              rows={ranking}
              columns={[
                "dimension",
                "member_count",
                "top1_abs_share_pct",
                "top1_excess_pp",
                "normalized_hhi",
                "verdict",
              ]}
              labels={{
                dimension: "单维度口径",
                member_count: "成员数",
                top1_abs_share_pct: "Top1 占 |变化| %",
                top1_excess_pp: "高出均分 pp",
                normalized_hhi: "归一化 HHI",
                verdict: "集中度判定",
              }}
            />
          ) : null}
          <NoteLines
            title="集中度与抵消口径"
            lines={[
              concentration
                ? `集中度按 |变化| 份额计算：HHI=${formatNumber(concentration.hhi)}，归一化 HHI=${formatNumber(concentration.normalized_hhi)}（成员数 ${formatNumber(concentration.member_count)}），Top1=${formatNumber(concentration.top1_abs_share_pct)}%（比均分高出 ${formatNumber(concentration.top1_excess_pp)} 个百分点）、Top3=${formatNumber(concentration.top3_abs_share_pct)}%。成员很少时按超出均分的幅度判断，避免 51/49 这种两成员被误判为主导。`
                : "",
              offsetting
                ? `正向合计 ${formatNumber(offsetting.positive_delta)}、负向合计 ${formatNumber(offsetting.negative_delta)}，净变化 ${formatNumber(offsetting.net_delta)}；抵消比例 = 1 - |净| / 总变动 = ${formatNumber(offsetting.offset_ratio)}，越高说明净变化越掩盖了内部大幅波动。`
                : "",
              ranking.length > 1
                ? "单维度排名由同一份交叉分组数据汇总得到，不额外取数；Top1 份额越高说明该口径越能解释变化。"
                : "",
            ]}
          />
          <WindowNotes output={data} />
        </>
      );
    }
    case "structure_effect": {
      const dominant = data.dominant as Record<string, any> | null | undefined;
      const residual = Number(data.residual ?? 0);
      return (
        <>
          <div className="sa-badges">
            <span className="sa-badge sa-badge-accent">
              总变化 {formatNumber(data.total_delta)}
            </span>
            {data.dimension ? (
              <span className="sa-badge">维度 {String(data.dimension)}</span>
            ) : null}
            {dominant?.label ? (
              <span className="sa-badge">
                主导 {String(dominant.label)} · {formatNumber(dominant.abs_share_pct)}%
              </span>
            ) : null}
            {Math.abs(residual) > 1e-6 ? (
              <span className="sa-badge">残差 {formatNumber(residual)}</span>
            ) : null}
          </div>
          <div>{String(data.summary ?? "")}</div>
          <Warnings warnings={data.warnings} />
          <Waterfall output={data} />
          <DataTable
            rows={data.rows}
            labels={{
              member: "成员",
              base_share_pct: "基期权重 %",
              current_share_pct: "本期权重 %",
              weight_delta_pp: "权重变化 pp",
              base_rate: "基期比率",
              current_rate: "本期比率",
              rate_delta: "比率变化",
              structure_effect: "结构效应",
              efficiency_effect: "效率效应",
              interaction_effect: "交互项",
              member_total_effect: "合计效应",
            }}
          />
          <NoteLines
            title="拆解口径"
            lines={[
              "结构效应 = Σ(本期权重 - 基期权重) × 基期比率；效率效应 = Σ基期权重 × (本期比率 - 基期比率)；交互项 = Σ(权重变化 × 比率变化)。权重按分母指标占比计算。",
              dominant
                ? `主导项：${String(dominant.label)} = ${formatNumber(dominant.value)}，占三项绝对值之和的 ${formatNumber(dominant.abs_share_pct)}%。`
                : "",
              `闭合校验：三项之和与总变化的残差 = ${formatNumber(residual)}（应接近 0）。`,
            ]}
          />
        </>
      );
    }
    case "trend_forecast": {
      const history = Array.isArray(data.history_tail) ? data.history_tail : [];
      const forecast = Array.isArray(data.forecast) ? data.forecast : [];
      const trend = (data.trend ?? {}) as Record<string, any>;
      const decomposition = (data.decomposition ?? {}) as Record<string, any>;
      const backtest = (data.backtest ?? {}) as Record<string, any>;
      const interval = (data.interval ?? {}) as Record<string, any>;
      const model = (data.model ?? {}) as Record<string, any>;
      const assumptions = Array.isArray(data.assumptions) ? data.assumptions : [];
      const metricLabel = String(data.metric ?? "指标");
      return (
        <>
          <div className="sa-badges">
            <span className="sa-badge sa-badge-accent">
              未来 {formatNumber(data.horizon_days)} 天
            </span>
            <span className="sa-badge">合计 {formatNumber(data.forecast_total)}</span>
            <span className="sa-badge">日均 {formatNumber(data.forecast_daily_avg)}</span>
            {trend.available ? (
              <span className={`sa-badge ${trend.significant ? "sa-badge-accent" : ""}`}>
                趋势 {formatNumber(trend.slope_per_day)}/天 · {String(trend.verdict ?? "")}
              </span>
            ) : null}
            {backtest.available ? (
              <span className="sa-badge">
                回测 MAPE {formatNumber(backtest.model_mape_pct)}%
              </span>
            ) : null}
            <span className="sa-badge">
              历史 {formatNumber(data.observed_days)}/{formatNumber(data.expected_days)} 天
            </span>
          </div>
          <div>{String(data.summary ?? "")}</div>
          <Warnings warnings={data.warnings} />
          {forecast.length ? (
            <>
              <ForecastChart history={history} forecast={forecast} label={metricLabel} />
              <DataTable
                rows={forecast}
                columns={["date", "yhat", "lower", "upper"]}
                labels={{ date: "日期", yhat: "预测值", lower: "区间下限", upper: "区间上限" }}
              />
            </>
          ) : null}
          <NoteLines
            title="模型、回测与预测假设"
            lines={[
              data.method ? `方法：${String(data.method)}` : "",
              trend.available
                ? `趋势检验：斜率 ${formatNumber(trend.slope_per_day)}/天，R²=${formatNumber(trend.r2)}，p=${formatNumber(trend.p_value)}，${String(trend.verdict ?? "")}。`
                : "",
              decomposition.available
                ? `STL 分解：趋势强度 ${formatNumber(decomposition.trend_strength)}、周内季节强度 ${formatNumber(decomposition.seasonal_strength)}，季节振幅 ${formatNumber(decomposition.seasonal_amplitude)}，残差标准差 ${formatNumber(decomposition.residual_std)}。`
                : String(decomposition.reason ?? ""),
              backtest.available
                ? `留出回测：训练 ${formatNumber(backtest.train_days)} 天、留出 ${formatNumber(backtest.holdout_days)} 天；MAPE 模型 ${formatNumber(backtest.model_mape_pct)}%、季节朴素 ${formatNumber(backtest.seasonal_naive_mape_pct)}%、朴素 ${formatNumber(backtest.naive_last_mape_pct)}% → ${String(backtest.verdict ?? "")}。`
                : String(backtest.reason ?? ""),
              `预测区间：${formatNumber((Number(interval.level ?? 0.95)) * 100)}% 水平，平均宽度 ${formatNumber(interval.mean_width)}（占预测值 ${formatNumber(interval.mean_width_pct_of_forecast)}%），${String(interval.method ?? "")}。`,
              interval.skew_ratio
                ? `区间左右不对称：均值上方 ${formatNumber(interval.upside_width)}、下方 ${formatNumber(interval.downside_width)}，下行是上行的 ${formatNumber(interval.skew_ratio)} 倍；自助模拟会重放历史里的异常下跌，所以下限偏低不代表崩盘预测。`
                : "",
              interval.clamped_at_zero ? "区间下限按 0 截断（业务量不应为负）。" : "",
              model.name ? `模型：${String(model.name)}，季节项 ${String(model.seasonal ?? "none")}，残差标准差 ${formatNumber(model.residual_std)}。` : "",
              ...assumptions.map((item: unknown) => `假设：${String(item)}`),
            ]}
          />
        </>
      );
    }
    case "propose_write":
      return <WriteActionCard proposal={data as WriteProposal} />;
    case "search_knowledge": {
      const items = Array.isArray(data.items) ? data.items : [];
      if (!items.length) {
        return <div className="sa-tool-summary">没有命中知识条目。</div>;
      }
      return (
        <>
          <div className="sa-badges">
            <span className="sa-badge sa-badge-accent">
              命中 {data.count ?? items.length} 条
            </span>
            {Number(data.total_matched ?? 0) > items.length ? (
              <span className="sa-badge">
                共 {data.total_matched} 条相关
              </span>
            ) : null}
          </div>
          <ul className="sa-tool-list">
            {items.map((item: Record<string, any>, index: number) => (
              <li key={`kb-${index}`}>
                <strong>{String(item?.title ?? "")}</strong>
                {item?.content ? (
                  <div className="sa-tool-note">{String(item.content)}</div>
                ) : null}
              </li>
            ))}
          </ul>
        </>
      );
    }
    default:
      return <pre className="sa-sql">{JSON.stringify(data, null, 2)}</pre>;
  }
}

export function ToolCard({
  name,
  part,
  variant = "full",
  showChart = true,
}: {
  name: string;
  part: ToolLikePart;
  variant?: "full" | "step";
  showChart?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const running = part.state === "input-streaming" || part.state === "input-available";
  const failed = part.state === "output-error";
  const summary = inputSummary(name, part.input);
  const stateText = failed
    ? "失败"
    : running
      ? "执行中"
      : part.output !== undefined
        ? "完成"
        : "等待中";

  return (
    <div className="sa-tool">
      <div className="sa-tool-head" onClick={() => setOpen(!open)}>
        <span className="sa-tool-title">{labelOf(name)}</span>
        {summary ? <span className="sa-tool-summary">{summary}</span> : null}
        <span className="sa-tool-state">
          {running ? <span className="sa-spinner" /> : null}
          {stateText}
          <span style={{ fontSize: 9 }}>{open ? "▾" : "▸"}</span>
        </span>
      </div>
      {open ? (
        <div className="sa-tool-body">
          {failed ? (
            <div className="sa-tool-error">
              {part.errorText ?? "工具执行失败"}
            </div>
          ) : null}
          {part.output !== undefined && !failed
            ? variant === "step" && name === "propose_write" ? (
              <div className="sa-tool-note">
                确认卡在下方回答区，可直接点击“确认执行”。
              </div>
            ) : (
              renderOutput(name, part.output, showChart)
            )
            : null}
          {running ? (
            <div className="sa-thinking">
              <span className="sa-spinner" /> {labelOf(name)}正在执行…
            </div>
          ) : null}
          {part.input !== undefined ? (
            <details className="sa-table-more">
              <summary style={{ cursor: "pointer" }}>参数</summary>
              <pre className="sa-sql" style={{ marginTop: 6 }}>
                {JSON.stringify(part.input, null, 2)}
              </pre>
            </details>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

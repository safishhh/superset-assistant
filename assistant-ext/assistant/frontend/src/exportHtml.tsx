import ReactMarkdown from "react-markdown";
import { renderToStaticMarkup } from "react-dom/server";
import remarkGfm from "remark-gfm";

import { interleaveCharts, type ChartPayload } from "./chartLayout";
import { buildChartPayload } from "./chartPayload";
import { ChartViz, KpiGrid, chartFields, kpiCards } from "./ChartViz";
import type { SelectedBlock } from "./context";
import { collectKnowledgeRefs, type KnowledgeRef } from "./knowledgeRefs";
import { selectionKindLabel } from "./selectionLabels";
import { stripThinking } from "./thinking";
import { chartMeta, formatCell, isQueryTool } from "./toolResult";
import {
  downloadBlob,
  type UserConversationDetail,
  type UserToolCall,
} from "./userApi";

type ExportTurn = {
  runId: string;
  question: string;
  answer: string;
  error: string;
  selection?: SelectedBlock[] | null;
};

export type TurnExportData = {
  answer: string;
  error?: string;
  selection?: SelectedBlock[] | null;
  charts: ChartPayload[];
  knowledgeRefs?: KnowledgeRef[];
  turnIndex: number;
  conversationId: string;
  date: string;
};

const EXPORT_CHART_WIDTH = 640;
const EXPORT_RAW_ROWS = 100;

const EXPORT_CSS = `
:root {
  color-scheme: light;
  --sa-accent: #2563eb;
  --sa-danger: #dc2626;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: #f4f6fa;
  color: #0f172a;
  font: 14px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  -webkit-font-smoothing: antialiased;
}
.sheet {
  max-width: 860px;
  margin: 32px auto;
  padding: 36px 40px 30px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  box-shadow: 0 18px 48px rgba(15, 23, 42, 0.08);
}
.head h1 { margin: 0 0 8px; font-size: 21px; line-height: 1.35; }
.meta { padding-bottom: 18px; border-bottom: 1px solid #eef2f7; color: #64748b; font-size: 12px; }
.turn { margin-top: 26px; break-inside: avoid; }
.who { margin-bottom: 6px; color: #94a3b8; font-size: 11px; letter-spacing: 0.12em; }
.q { display: flex; flex-direction: column; align-items: flex-end; }
.q .bubble {
  max-width: 86%;
  padding: 10px 14px;
  border-radius: 16px 16px 4px 16px;
  background: #2563eb;
  color: #fff;
  white-space: pre-wrap;
  word-break: break-word;
  box-shadow: 0 2px 10px rgba(37, 99, 235, 0.18);
}
.sel { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 0 0 6px; color: #64748b; font-size: 11px; }
.q .sel { justify-content: flex-end; }
.sel-label { color: #94a3b8; }
.chip {
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 1px 9px;
  border: 1px solid #e2e8f0;
  border-radius: 999px;
  background: #f8fafc;
  color: #475569;
}
.a { margin-top: 16px; }
.md { font-size: 14px; word-break: break-word; }
.md p { margin: 0 0 10px; }
.md p:last-child { margin-bottom: 0; }
.md h1, .md h2, .md h3, .md h4 { margin: 16px 0 8px; font-size: 15px; line-height: 1.4; }
.md ul, .md ol { margin: 6px 0 10px; padding-left: 22px; }
.md li { margin: 3px 0; }
.md code {
  padding: 1px 5px;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  background: #f1f5f9;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}
.md pre { padding: 12px 14px; border-radius: 12px; background: #0f172a; color: #e2e8f0; overflow-x: auto; font-size: 12px; line-height: 1.55; }
.md pre code { padding: 0; border: 0; background: transparent; color: inherit; }
.md table { width: 100%; margin: 8px 0; border-collapse: collapse; font-size: 12px; }
.md th, .md td { padding: 6px 8px; border: 1px solid #e2e8f0; text-align: left; }
.md th { background: #f8fafc; }
.md blockquote { margin: 8px 0; padding: 2px 12px; border-left: 3px solid #e2e8f0; color: #475569; }
.md a { color: #2563eb; }
.md hr { margin: 16px 0; border: 0; border-top: 1px solid #e2e8f0; }
.err { color: #dc2626; }
.muted { color: #94a3b8; }
.chart { margin: 16px 0 0; padding: 12px 12px 10px; border: 1px solid #e2e8f0; border-radius: 12px; }
.chart figcaption { margin-top: 6px; color: #64748b; font-size: 12px; text-align: left; }
.sa-chart { display: block; width: 100%; height: auto; font-family: inherit; }
.sa-chart-multi { display: grid; gap: 10px; align-items: start; }
.sa-kpi-grid { display: grid; gap: 8px; align-items: stretch; }
.sa-kpi-card { min-width: 0; padding: 8px 10px; border: 1px solid #e2e8f0; border-radius: 8px; background: #f8fafc; }
.sa-kpi-label { font-size: 11px; color: #64748b; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sa-kpi-value { margin-top: 2px; font-size: 20px; font-weight: 600; line-height: 1.2; color: #0f172a; font-variant-numeric: tabular-nums; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sa-kpi-hint { margin-top: 2px; font-size: 10.5px; color: #94a3b8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sa-chart-wrap { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.sa-chart-metric { font-size: 11px; font-weight: 500; color: #475569; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sa-chart-grid { stroke: #e2e8f0; stroke-width: 1; opacity: 0.7; }
.sa-chart-axis { stroke: #cbd5e1; stroke-width: 1; }
.sa-chart-tick { fill: #64748b; font-size: 9.5px; }
.sa-chart-value { fill: #475569; font-size: 8.5px; font-variant-numeric: tabular-nums; }
.sa-chart-center { fill: #0f172a; font-size: 12px; font-weight: 600; }
.sa-chart-legend-row { display: flex; flex-wrap: wrap; gap: 3px 12px; font-size: 11px; color: #475569; }
.sa-chart-legend-item { display: inline-flex; align-items: center; gap: 5px; max-width: 100%; }
.sa-chart-legend-item i { display: inline-block; width: 8px; height: 8px; border-radius: 2px; }
.sa-chart-legend-val { color: #64748b; white-space: nowrap; font-variant-numeric: tabular-nums; }
.chart-details { margin-top: 8px; font-size: 12px; color: #475569; }
.chart-details summary { color: #2563eb; font-size: 12px; cursor: pointer; }
.chart-details .raw { margin-top: 8px; max-height: 320px; overflow: auto; border: 1px solid #e2e8f0; border-radius: 8px; }
.chart-details table { width: 100%; border-collapse: collapse; font-size: 12px; }
.chart-details th, .chart-details td { padding: 5px 8px; border-bottom: 1px solid #eef2f7; text-align: left; white-space: nowrap; }
.chart-details th { background: #f8fafc; }
.chart-details .note { margin: 6px 0 0; color: #94a3b8; font-size: 11px; }
.foot { margin-top: 36px; padding-top: 14px; border-top: 1px solid #eef2f7; color: #94a3b8; font-size: 11px; }
.kb { margin-top: 12px; }
.kb-details { margin-top: 6px; font-size: 12px; }
.kb-details summary { color: #2563eb; cursor: pointer; }
.kb-body { margin-top: 6px; padding: 8px 10px; border: 1px solid #eef2f7; border-radius: 8px; background: #f8fafc; white-space: pre-wrap; word-break: break-word; color: #475569; }
@media (max-width: 640px) {
  .sheet { margin: 0; padding: 24px 18px; border: 0; border-radius: 0; }
}
@media print {
  body { background: #fff; }
  .sheet { margin: 0; padding: 0; border: 0; border-radius: 0; box-shadow: none; }
  .turn { page-break-inside: avoid; }
  .q .bubble { box-shadow: none; }
}
`;

function esc(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatTime(value: string): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? value.slice(0, 16)
    : parsed.toLocaleString("zh-CN", { hour12: false });
}

function buildTurns(detail: UserConversationDetail): ExportTurn[] {
  const turns: ExportTurn[] = [];
  const byRun = new Map<string, ExportTurn>();
  for (const message of detail.messages) {
    const runId = message.run_id || `message-${message.id}`;
    let turn = byRun.get(runId);
    if (!turn) {
      turn = { runId, question: "", answer: "", error: "" };
      byRun.set(runId, turn);
      turns.push(turn);
    }
    if (message.role === "user") {
      turn.question = message.content || "";
      turn.selection = message.selection ?? null;
    } else {
      turn.answer = message.content || "";
      turn.error = message.error || "";
    }
  }
  return turns;
}

function selectionHtml(blocks?: SelectedBlock[] | null): string {
  if (!blocks || blocks.length === 0) return "";
  const chips = blocks
    .map((block) => {
      const kind = selectionKindLabel(block.kind);
      const title = block.title || "未命名";
      return `<span class="chip">${esc(`${kind} · ${title}`)}</span>`;
    })
    .join("");
  return `<div class="sel"><span class="sel-label">选中</span>${chips}</div>`;
}

function selectionText(blocks?: SelectedBlock[] | null): string {
  if (!blocks || blocks.length === 0) return "";
  return blocks
    .map((block) => {
      return `${selectionKindLabel(block.kind)} · ${block.title || "未命名"}`;
    })
    .join("、");
}

function markdownHtml(text: string): string {
  return renderToStaticMarkup(
    <ReactMarkdown remarkPlugins={[remarkGfm]}>{text || "—"}</ReactMarkdown>,
  );
}

function chartPayload(tool: UserToolCall): ChartPayload | null {
  if (tool.status === "error" || !isQueryTool(tool.tool_name)) return null;
  return buildChartPayload(tool.tool_name, tool.result_json, tool.args_json);
}

function chartFigureHtml(chart: ChartPayload): string {
  const kpis = kpiCards(chart.rows, chart.columns, chart.labels);
  const markup = kpis.length
    ? renderToStaticMarkup(
        <KpiGrid cards={kpis} width={EXPORT_CHART_WIDTH} />,
      )
    : renderToStaticMarkup(
        <ChartViz
          rows={chart.rows}
          columns={chart.columns}
          labels={chart.labels}
          chartType={chart.chartType}
          width={EXPORT_CHART_WIDTH}
        />,
      );
  if (!markup) return "";
  const names = chart.columns.length
    ? chart.columns.map((column) => column.name)
    : Object.keys(chart.rows[0] ?? {});
  const shown = chart.rows.slice(0, EXPORT_RAW_ROWS);
  const head = names
    .map((name) => `<th>${esc(chart.labels?.[name] || name)}</th>`)
    .join("");
  const body = shown
    .map(
      (row) =>
        `<tr>${names
          .map((name) => `<td>${esc(formatCell(row[name]))}</td>`)
          .join("")}</tr>`,
    )
    .join("");
  const note =
    chart.rows.length > shown.length
      ? `<p class="note">共 ${chart.rows.length} 行，仅显示前 ${shown.length} 行</p>`
      : "";
  const caption = esc(
    [
      chart.datasetName,
      chartMeta(
        chart.query,
        chart.labels,
        chartFields(chart.rows, chart.columns),
        chart.appliedFilters,
      ),
      chart.rowCount ? `${chart.rowCount} 行` : "",
    ]
      .filter(Boolean)
      .join(" · "),
  );
  return `<figure class="chart">${markup}<figcaption>${caption}</figcaption>
<details class="chart-details"><summary>展开详情</summary><div class="raw"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>${note}</div></details>
</figure>`;
}

function renderTurnHtml(
  turn: ExportTurn,
  charts: ChartPayload[],
  withQuestion = true,
  knowledgeRefs: KnowledgeRef[] = [],
): string {
  const hasQuestion = withQuestion && Boolean(turn.question);
  const question = hasQuestion
    ? `<div class="q"><div class="who">用户</div>${selectionHtml(turn.selection)}<div class="bubble">${esc(turn.question)}</div></div>`
    : "";
  const items = interleaveCharts(stripThinking(turn.answer), charts);
  const answer = items.length
    ? items
        .map((item) =>
          item.kind === "chart"
            ? chartFigureHtml(item.chart)
            : `<div class="md">${markdownHtml(stripThinking(item.text))}</div>`,
        )
        .join("\n")
    : turn.error
      ? `<p class="err">${esc(turn.error)}</p>`
      : `<p class="muted">—</p>`;
  return `<section class="turn">
${question}
<div class="a">
<div class="who">助手</div>
${hasQuestion ? "" : selectionHtml(turn.selection)}
${answer}
${knowledgeRefsHtml(knowledgeRefs)}
</div>
</section>`;
}

function knowledgeRefsHtml(refs: KnowledgeRef[]): string {
  if (!refs.length) return "";
  const chips = refs
    .map((ref) => `<span class="chip">${esc(ref.title)}</span>`)
    .join("");
  const details = refs
    .map(
      (ref) =>
        `<details class="kb-details"><summary>${esc(ref.title)}</summary><div class="kb-body">${esc(ref.content)}</div></details>`,
    )
    .join("");
  return `<div class="kb"><div class="sel"><span class="sel-label">参考知识库</span>${chips}</div>${details}</div>`;
}

function htmlShell(
  title: string,
  meta: string,
  body: string,
  footer: string,
): string {
  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>${esc(title)}</title>
<style>${EXPORT_CSS}</style>
</head>
<body>
<main class="sheet">
<header class="head">
<h1>${esc(title)}</h1>
<div class="meta">${esc(meta)}</div>
</header>
${body}
<footer class="foot">${esc(footer)}</footer>
</main>
</body>
</html>`;
}

export function conversationHtml(detail: UserConversationDetail): string {
  const title = detail.title || detail.id;
  const turns = buildTurns(detail);
  const meta = [
    `用户 ${detail.username}`,
    detail.model_name || "—",
    `${detail.run_count} 轮`,
    `${(detail.input_tokens + detail.output_tokens).toLocaleString("zh-CN")} Token`,
    detail.last_at ? `最后活动 ${formatTime(detail.last_at)}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
  const chartsByRun = new Map<string, ChartPayload[]>();
  for (const tool of detail.tool_calls) {
    const payload = chartPayload(tool);
    if (!payload) continue;
    const charts = chartsByRun.get(tool.run_id) ?? [];
    charts.push(payload);
    chartsByRun.set(tool.run_id, charts);
  }
  const refsByRun = new Map<string, KnowledgeRef[]>();
  const toolsByRun = new Map<string, UserToolCall[]>();
  for (const tool of detail.tool_calls) {
    const tools = toolsByRun.get(tool.run_id) ?? [];
    tools.push(tool);
    toolsByRun.set(tool.run_id, tools);
  }
  for (const [runId, tools] of toolsByRun) {
    const refs = collectKnowledgeRefs(
      tools.map((tool) => ({
        name: tool.tool_name,
        result: tool.result_json,
      })),
    );
    if (refs.length) refsByRun.set(runId, refs);
  }
  const body = turns.length
    ? turns
        .map((turn) =>
          renderTurnHtml(
            turn,
            chartsByRun.get(turn.runId) ?? [],
            true,
            refsByRun.get(turn.runId) ?? [],
          ),
        )
        .join("\n")
    : `<p class="muted">这条会话没有记录。</p>`;
  return htmlShell(
    title,
    meta,
    body,
    `由 Superset 数据分析助手导出 · ${detail.id}`,
  );
}

export function turnHtml(data: TurnExportData): string {
  const turn: ExportTurn = {
    runId: "turn",
    question: "",
    answer: data.answer,
    error: data.error || "",
    selection: data.selection,
  };
  const title = `第 ${data.turnIndex} 轮回答`;
  const meta = [
    `第 ${data.turnIndex} 轮`,
    `会话 ${data.conversationId}`,
    `导出 ${data.date}`,
  ].join(" · ");
  return htmlShell(
    title,
    meta,
    renderTurnHtml(turn, data.charts, false, data.knowledgeRefs ?? []),
    `由 Superset 数据分析助手导出 · ${data.conversationId} · 第 ${data.turnIndex} 轮`,
  );
}

export function turnMarkdown(data: TurnExportData): string {
  const lines = [
    `# 第 ${data.turnIndex} 轮回答`,
    "",
    `> 对话：第 ${data.turnIndex} 轮 · 会话：${data.conversationId} · 导出：${data.date}`,
    "",
  ];
  const selected = selectionText(data.selection);
  if (selected) lines.push(`> 选中：${selected}`, "");
  const refs = data.knowledgeRefs ?? [];
  if (refs.length) {
    lines.push(
      `> 参考知识库：${refs.map((ref) => ref.title).join("、")}`,
      "",
    );
  }
  lines.push(data.answer || data.error || "—", "");
  return lines.join("\n");
}

function exportFilename(detail: UserConversationDetail, ext: string): string {
  const raw = `${detail.last_at || detail.started_at || ""}`;
  const day = /^\d{4}-\d{2}-\d{2}/.test(raw)
    ? raw.slice(0, 10)
    : new Date().toISOString().slice(0, 10);
  const base =
    (detail.title || detail.id)
      .replace(/[\\/:*?"<>|\u0000-\u001f]+/g, "_")
      .replace(/^[\s._]+|[\s._]+$/g, "")
      .slice(0, 60)
      .trim() || "会话";
  return `${base}-${day}.${ext}`;
}

export function downloadConversationHtml(detail: UserConversationDetail): void {
  const blob = new Blob([conversationHtml(detail)], {
    type: "text/html;charset=utf-8",
  });
  downloadBlob(exportFilename(detail, "html"), blob);
}

function turnFilename(data: TurnExportData, ext: string): string {
  return `第${data.turnIndex}轮回答-${data.date}.${ext}`;
}

export function downloadTurnHtml(data: TurnExportData): void {
  const blob = new Blob([turnHtml(data)], {
    type: "text/html;charset=utf-8",
  });
  downloadBlob(turnFilename(data, "html"), blob);
}

export function downloadTurnMarkdown(data: TurnExportData): void {
  const blob = new Blob([turnMarkdown(data)], {
    type: "text/markdown;charset=utf-8",
  });
  downloadBlob(turnFilename(data, "md"), blob);
}

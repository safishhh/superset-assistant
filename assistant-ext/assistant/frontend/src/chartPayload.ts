import type { ChartPayload } from "./chartLayout";
import { hasVisual } from "./ChartViz";
import { canonicalToolName, normalizeToolResult } from "./toolResult";

/**
 * 把一次查询工具结果归一化成图表/KPI 的渲染载荷。
 * 聊天、历史、后台审计和 HTML 导出共用，保证四处对同一结果的判定与文案一致；
 * 不构成可视结果（无维度、多维度明细、空结果）时返回 null。
 */
export function buildChartPayload(
  name: string,
  raw: unknown,
  args?: unknown,
): ChartPayload | null {
  const data = normalizeToolResult(name, raw);
  const rows = Array.isArray(data.rows)
    ? (data.rows as Record<string, any>[])
    : [];
  const columns = Array.isArray(data.columns)
    ? (data.columns as { name: string; type?: string | null }[])
    : [];
  const labels =
    data.labels && typeof data.labels === "object"
      ? (data.labels as Record<string, string>)
      : undefined;
  if (!hasVisual(rows, columns, labels)) return null;
  return {
    rows,
    columns,
    labels,
    datasetName: String(
      data.dataset_name ||
        (canonicalToolName(name) === "run_sql" ? "SQL 结果" : "查询结果"),
    ),
    rowCount: data.row_count,
    query: args,
    appliedFilters: Array.isArray(data.applied_filters)
      ? data.applied_filters
      : undefined,
    chartType:
      typeof data.chart_type === "string" ? data.chart_type : undefined,
    datasetId: data.dataset_id ?? (args as any)?.dataset_id ?? undefined,
  };
}

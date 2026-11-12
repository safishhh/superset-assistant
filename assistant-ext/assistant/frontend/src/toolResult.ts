export type ChartFields = { dimension?: string; metrics: string[] };

/** 表格单元格的统一展示：空值、数字千分位、布尔中文、对象 JSON。 */
export function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return value.toLocaleString("zh-CN");
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

const UNIT_ZH: Record<string, string> = {
  day: "天",
  days: "天",
  week: "周",
  weeks: "周",
  month: "个月",
  months: "个月",
  year: "年",
  years: "年",
};

const RANGE_ZH: Record<string, string> = {
  today: "今天",
  yesterday: "昨天",
  "this week": "本周",
  "this month": "本月",
  "this year": "今年",
  "previous week": "上周",
  "previous month": "上个月",
  "previous year": "去年",
  "no filter": "全部时间",
};

/** Superset 时间范围是英文短语，图注里换成中文。 */
function formatTimeRange(value: unknown): string {
  const raw = String(value ?? "").trim();
  if (!raw) return "";
  const fixed = RANGE_ZH[raw.toLowerCase()];
  if (fixed) return fixed;
  const relative = raw.match(/^last\s+(\d+)\s+(day|days|week|weeks|month|months|year|years)$/i);
  if (relative) {
    return `最近 ${relative[1]} ${UNIT_ZH[relative[2].toLowerCase()]}`;
  }
  return raw.replace(/\s*:\s*/, " ~ ");
}

/** 图表口径：按哪些维度、什么指标、哪个时间范围（用中文字段名）。 */
const FILTER_OP_TEXT: Record<string, string> = {
  "==": "=",
  "!=": "≠",
  ">": ">",
  ">=": "≥",
  "<": "<",
  "<=": "≤",
  LIKE: "像",
  "NOT LIKE": "不像",
  ILIKE: "像",
  "NOT ILIKE": "不像",
  IN: "属于",
  "NOT IN": "不属于",
  "IS NULL": "为空",
  "IS NOT NULL": "非空",
  "IS TRUE": "为真",
  "IS FALSE": "为假",
};

/** 宿主 `applied_filters` 的可读化；TEMPORAL_RANGE 由「时间」段表达，不重复 */
export function appliedFilterText(
  applied: unknown,
  labels?: Record<string, string>,
): string {
  if (!Array.isArray(applied)) return "";
  const parts = applied
    .filter(
      (item: any) =>
        item && typeof item.col === "string" && item.op !== "TEMPORAL_RANGE",
    )
    .map((item: any) => {
      const name = labels?.[item.col] || item.col;
      const op = FILTER_OP_TEXT[String(item.op)] ?? String(item.op);
      const value = Array.isArray(item.val) ? item.val.join("/") : item.val;
      return value === null || value === undefined || value === ""
        ? `${name} ${op}`
        : `${name} ${op} ${value}`;
    });
  return parts.length ? `过滤 ${parts.join("、")}` : "";
}

export function chartMeta(
  args: unknown,
  labels?: Record<string, string>,
  fields?: ChartFields,
  applied?: unknown,
): string {
  const raw = (args ?? {}) as Record<string, any>;
  const request = (raw.request ?? raw) as Record<string, any>;
  const format = (name: string) => labels?.[name] || name;
  const fromArgs = Array.isArray(request.columns)
    ? (request.columns as string[])
    : [];
  const dimensions = fromArgs.length
    ? fromArgs
    : fields?.dimension
      ? [fields.dimension]
      : [];
  const argMetrics = Array.isArray(request.metrics)
    ? (request.metrics as string[])
    : [];
  const metrics = argMetrics.length ? argMetrics : fields?.metrics ?? [];
  const parts: string[] = [];
  if (dimensions.length) parts.push(`按${dimensions.map(format).join("、")}`);
  if (metrics.length) parts.push(`指标 ${metrics.map(format).join("、")}`);
  const timeRange = formatTimeRange(request.time_range);
  if (timeRange) parts.push(`时间 ${timeRange}`);
  const filterText = appliedFilterText(
    applied ?? request.applied_filters ?? request.filters,
    labels,
  );
  if (filterText) parts.push(filterText);
  return parts.join(" · ");
}

/** 审计里存的是 MCP 原始结果（行在 data 下），会话流里是规范化的 rows，统一成后者。
 *  审计层的工具名是 MCP 名：run_sql 记作 execute_sql，先归一化再判形状。 */
export const QUERY_TOOLS = ["query_dataset", "run_sql", "execute_sql"];

export function isQueryTool(name: string): boolean {
  return QUERY_TOOLS.includes(name);
}

/** 审计行记 MCP 名（execute_sql），parts_json 记 agent 名（run_sql）；图表定位统一按 agent 名。 */
export function canonicalToolName(name: string): string {
  return name === "execute_sql" ? "run_sql" : name;
}

/** 数据集信息：2026-11-03 起审计与实时流都是宿主原始键名，卡片按精简键名渲染。 */
function normalizeDatasetInfo(data: Record<string, any>): Record<string, any> {
  const inner =
    data.result && typeof data.result === "object" ? data.result : data;
  const label = (item: Record<string, any>) => {
    const name = String(item.column_name ?? item.metric_name ?? item.name ?? "");
    const alias = item.verbose_name || item.description || null;
    // 与后端 _label_of 同规则：同名别名和表达式（COUNT(*)）不算口径名
    if (!alias || alias === item.expression || alias.toLowerCase() === name.toLowerCase()) {
      return null;
    }
    return alias;
  };
  const mapEntries = (list: unknown, fallbackName: string) =>
    Array.isArray(list)
      ? list.map((item: any) => {
          if (typeof item === "string") return { name: item };
          const entry = { ...item };
          entry.name = item.name ?? item.column_name ?? item.metric_name ?? fallbackName;
          entry.verbose_name = label(item);
          return entry;
        })
      : [];
  return {
    ...inner,
    name: inner.name ?? inner.table_name ?? "数据集",
    database: inner.database ?? inner.database_name,
    columns: mapEntries(inner.columns, "列"),
    metrics: mapEntries(inner.metrics, "指标"),
  };
}

export function normalizeToolResult(
  name: string,
  raw: unknown,
): Record<string, any> {
  const data = (raw ?? {}) as Record<string, any>;
  if (name === "get_dataset_info") {
    return normalizeDatasetInfo(data);
  }
  if (isQueryTool(name) && !Array.isArray(data.rows) && Array.isArray(data.data)) {
    return {
      ...data,
      rows: data.data,
      row_count: data.row_count ?? data.total_rows ?? data.data.length,
    };
  }
  return data;
}

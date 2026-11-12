export type ChartPayload = {
  rows: Record<string, any>[];
  columns: { name: string; type?: string | null }[];
  labels?: Record<string, string>;
  datasetName: string;
  rowCount?: number;
  query?: unknown;
  /** 宿主实际生效的过滤条件（applied_filters），用于图表口径说明 */
  appliedFilters?: unknown;
  /** 模型建议的图表类型（auto/bar/line/pie），缺省按数据形态自动选 */
  chartType?: string;
  /** 查询所用的数据集 id，决定能否跳到 Superset 图表编辑器 */
  datasetId?: string | number;
};

export type BodyItem =
  | { kind: "text"; text: string }
  | { kind: "chart"; chart: ChartPayload };

/** 服务端落库的正文/工具顺序：text 用长度切片，tool 用工具名定位。 */
export type LayoutPart =
  | { type: "text"; len: number }
  | { type: "tool"; name: string };

export type LayoutEntry =
  | { kind: "text"; text: string }
  | { kind: "tool"; name: string };

export function splitLayout(
  content: string,
  layout: LayoutPart[],
): LayoutEntry[] {
  const totalText = layout.filter((part) => part.type === "text").length;
  const entries: LayoutEntry[] = [];
  let offset = 0;
  let seen = 0;
  for (const part of layout) {
    if (part.type === "text") {
      const text = content.slice(offset, offset + part.len);
      offset += part.len;
      seen += 1;
      if (seen < totalText) offset += 2; // 服务端用 "\n\n" 连接文本段
      entries.push({ kind: "text", text });
    } else {
      entries.push({ kind: "tool", name: part.name });
    }
  }
  return entries;
}

/** 按空行切 Markdown 块；代码块内部的空行不切。 */
export function splitMarkdownBlocks(text: string): string[] {
  if (!text.trim()) return [];
  const blocks: string[] = [];
  let current: string[] = [];
  let fence = false;
  for (const line of text.split("\n")) {
    if (/^\s*```/.test(line)) fence = !fence;
    if (!fence && line.trim() === "") {
      if (current.length) {
        blocks.push(current.join("\n"));
        current = [];
      }
      continue;
    }
    current.push(line);
  }
  if (current.length) blocks.push(current.join("\n"));
  return blocks;
}

/**
 * 图表均匀穿插在正文块之间（第 i 张放在 round((i+1)*B/(C+1)) 块之后），
 * 避免全部堆在回答末尾；正文为空时图表单独成列。
 */
export function interleaveCharts(
  text: string,
  charts: ChartPayload[],
): BodyItem[] {
  const blocks = splitMarkdownBlocks(text);
  if (!charts.length) {
    return blocks.map((block) => ({ kind: "text", text: block }));
  }
  if (!blocks.length) {
    return charts.map((chart) => ({ kind: "chart", chart }));
  }
  const buckets = new Map<number, ChartPayload[]>();
  charts.forEach((chart, index) => {
    const after = Math.min(
      blocks.length,
      Math.max(1, Math.round(((index + 1) * blocks.length) / (charts.length + 1))),
    );
    const list = buckets.get(after - 1) ?? [];
    list.push(chart);
    buckets.set(after - 1, list);
  });
  const items: BodyItem[] = [];
  blocks.forEach((block, index) => {
    items.push({ kind: "text", text: block });
    for (const chart of buckets.get(index) ?? []) {
      items.push({ kind: "chart", chart });
    }
  });
  return items;
}

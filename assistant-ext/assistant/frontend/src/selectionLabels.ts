/** 选区类型的中文标签；聊天、历史、后台审计与 HTML 导出共用同一份。 */
export type SelectionKind = "chart" | "filter" | "block";

export const SELECTION_KIND_LABEL: Record<SelectionKind, string> = {
  chart: "图表",
  filter: "筛选器",
  block: "区块",
};

/** 审计数据里的 kind 可能是历史遗留值，非法时按“区块”展示。 */
export function selectionKindLabel(kind: string | undefined): string {
  return kind === "chart" || kind === "filter" || kind === "block"
    ? SELECTION_KIND_LABEL[kind]
    : "区块";
}

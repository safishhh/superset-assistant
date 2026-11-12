export function byText<T>(key: keyof T) {
  return (a: T, b: T): number =>
    String(a[key] ?? "").localeCompare(String(b[key] ?? ""), "zh-CN");
}

export function byNumber<T>(key: keyof T) {
  return (a: T, b: T): number =>
    Number(a[key] ?? 0) - Number(b[key] ?? 0);
}

export function byBoolean<T>(key: keyof T) {
  return (a: T, b: T): number =>
    Number(Boolean(a[key])) - Number(Boolean(b[key]));
}

export type SortState = {
  field: string;
  order: "asc" | "desc";
};

type AntdSorter = {
  field?: unknown;
  columnKey?: unknown;
  order?: "ascend" | "descend" | null;
};

export function nextSort(
  sorter: AntdSorter | AntdSorter[] | undefined,
): SortState | null {
  const active = Array.isArray(sorter) ? sorter[0] : sorter;
  if (!active?.order) return null;
  const raw =
    active.columnKey ??
    (Array.isArray(active.field) ? active.field[0] : active.field);
  if (typeof raw !== "string" && typeof raw !== "number") return null;
  return {
    field: String(raw),
    order: active.order === "ascend" ? "asc" : "desc",
  };
}

export function sortOrderFor(
  sort: SortState | null,
  field: string,
): "ascend" | "descend" | null {
  if (!sort || sort.field !== field) return null;
  return sort.order === "asc" ? "ascend" : "descend";
}

export function indexColumn<T>(offset = 0, width = 52) {
  return {
    title: "#",
    key: "__index",
    width,
    align: "center" as const,
    className: "row-index",
    render: (_value: unknown, _record: T, index: number) => offset + index + 1,
  };
}

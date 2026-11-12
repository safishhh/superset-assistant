import { sqlLab } from "@apache-superset/core";

export type SelectedBlock = {
  kind: "chart" | "filter" | "block";
  chart_id?: string;
  title: string;
  text?: string;
};

let selectedBlocks: SelectedBlock[] = [];

export function setSelectionContext(blocks: SelectedBlock[]): void {
  selectedBlocks = blocks;
}

function firstMatch(path: string, patterns: RegExp[]): string | undefined {
  for (const pattern of patterns) {
    const match = path.match(pattern);
    if (match?.[1]) return match[1];
  }
  return undefined;
}

function truncate(value: string, length: number): string {
  return value.length > length ? `${value.slice(0, length)}…` : value;
}

function parseJson(value: string | null): Record<string, unknown> | null {
  if (!value) return null;
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

function summarizeFilters(params: URLSearchParams): Record<string, unknown> {
  const summary: Record<string, unknown> = {};
  const timeRange = params.get("time_range");
  if (timeRange) summary.time_range = timeRange;
  const granularity = params.get("granularity_sqla");
  if (granularity) summary.granularity = granularity;

  const formData = parseJson(params.get("form_data"));
  if (formData) {
    for (const key of ["time_range", "granularity_sqla", "metrics", "groupby"]) {
      if (formData[key] !== undefined) summary[key] = formData[key];
    }
    for (const key of ["adhoc_filters", "filters"]) {
      if (Array.isArray(formData[key])) {
        summary[key] = (formData[key] as unknown[]).slice(0, 20);
      }
    }
    if (formData.datasource) summary.datasource = formData.datasource;
  }

  const native = parseJson(params.get("native_filters"));
  if (native) {
    summary.native_filters = Object.entries(native)
      .slice(0, 20)
      .map(([key, value]) => {
        const record =
          value && typeof value === "object"
            ? (value as Record<string, unknown>)
            : {};
        return {
          key,
          label: record.label ?? record.name ?? null,
          values: record.values ?? record.value ?? null,
        };
      });
  } else {
    const nativeKeys: Record<string, string> = {};
    for (const [key, value] of params) {
      if (key.startsWith("native_filter_")) {
        nativeKeys[key] = truncate(value, 200);
      }
    }
    if (Object.keys(nativeKeys).length > 0) {
      summary.native_filter_params = nativeKeys;
    }
  }
  const nativeKey = params.get("native_filters_key");
  if (nativeKey) summary.native_filters_key = nativeKey;
  return summary;
}

export async function collectPageContext(): Promise<Record<string, unknown>> {
  const url = new URL(window.location.href);
  const path = url.pathname;
  const params = url.searchParams;
  const context: Record<string, unknown> = {
    path,
    title: document.title || "Superset",
  };
  if (selectedBlocks.length > 0) {
    context.selection = selectedBlocks;
  }

  if (path.includes("/dashboard/p/")) {
    context.page = "dashboard";
    context.permalink_key = firstMatch(path, [/\/dashboard\/p\/([^/]+)/]);
  } else if (path.includes("/dashboard/")) {
    context.page = "dashboard";
    context.dashboard_id = firstMatch(path, [/\/dashboard\/([^/]+)/]);
  } else if (path.includes("/explore")) {
    context.page = "explore";
  } else if (path.includes("/sqllab")) {
    context.page = "sqllab";
  } else if (path.includes("/tablemodelview") || path.includes("/dataset/")) {
    context.page = "dataset";
  } else {
    context.page = "home";
  }

  const datasetPath = firstMatch(path, [
    /\/dataset\/(?:edit\/)?(\d+)/,
    /\/tablemodelview\/(?:edit|show)\/(\d+)/,
  ]);
  if (datasetPath) context.dataset_id = datasetPath;
  const datasourceId = params.get("datasource_id");
  if (datasourceId) context.dataset_id = datasourceId;
  const datasource = params.get("datasource");
  if (!context.dataset_id && datasource?.includes("__")) {
    context.dataset_id = datasource.split("__")[0];
  }
  const chartId =
    params.get("slice_id") || params.get("chart_id") || params.get("sliceId");
  if (chartId) context.chart_id = chartId;

  const filters: Record<string, string> = {};
  for (const key of [
    "native_filters",
    "native_filters_key",
    "form_data",
    "form_data_key",
    "adhoc_filters",
    "time_range",
    "granularity_sqla",
  ]) {
    const value = params.get(key);
    if (value) filters[key] = truncate(value, 3000);
  }
  for (const [key, value] of params) {
    if (key.startsWith("native_filter_")) {
      filters[key] = truncate(value, 1000);
    }
  }
  if (Object.keys(filters).length > 0) context.filters = filters;

  const filterSummary = summarizeFilters(params);
  if (Object.keys(filterSummary).length > 0) {
    context.filter_summary = filterSummary;
  }

  if (context.page === "sqllab") {
    const tab = sqlLab.getCurrentTab();
    if (tab) {
      const sqlLabContext: Record<string, unknown> = {
        database_id: tab.databaseId,
        schema: tab.schema,
        catalog: tab.catalog,
        tab_title: tab.title,
      };
      try {
        const editor = await tab.getEditor();
        sqlLabContext.sql = truncate(editor.getValue(), 4000);
      } catch {
        // Editor may not be ready; IDs still help.
      }
      context.sql_lab = sqlLabContext;
    }
  }

  return context;
}

export function encodePageContext(context: Record<string, unknown>): string {
  return encodeURIComponent(JSON.stringify(context));
}

type PageObjectKind = "dashboard" | "chart" | "dataset";

export type PageObject = {
  kind: PageObjectKind;
  id?: string;
  permalinkKey?: string;
};

const PAGE_OBJECT_LABEL: Record<PageObjectKind, string> = {
  dashboard: "看板",
  chart: "图表",
  dataset: "数据集",
};

const nameCache = new Map<string, Promise<string | null>>();

export function currentPageObject(): PageObject | null {
  const url = new URL(window.location.href);
  const path = url.pathname;
  const params = url.searchParams;

  if (path.includes("/dashboard/p/")) {
    const permalinkKey = firstMatch(path, [/\/dashboard\/p\/([^/]+)/]);
    return permalinkKey ? { kind: "dashboard", permalinkKey } : null;
  }
  const dashboardId = firstMatch(path, [/\/dashboard\/(\d+)(?:\/|$)/]);
  if (dashboardId) return { kind: "dashboard", id: dashboardId };

  const chartId =
    firstMatch(path, [/\/chart\/(\d+)(?:\/|$)/]) ||
    params.get("slice_id") ||
    params.get("chart_id") ||
    params.get("sliceId");
  if (chartId) return { kind: "chart", id: chartId };

  const datasetId =
    firstMatch(path, [
      /\/dataset\/(?:edit\/)?(\d+)/,
      /\/tablemodelview\/(?:edit|show)\/(\d+)/,
    ]) ||
    params.get("datasource_id") ||
    (params.get("datasource")?.includes("__")
      ? params.get("datasource")!.split("__")[0]
      : undefined);
  if (datasetId) return { kind: "dataset", id: datasetId };

  return null;
}

async function fetchName(
  kind: PageObjectKind,
  id: string,
): Promise<string | null> {
  const key = `${kind}:${id}`;
  let request = nameCache.get(key);
  if (!request) {
    request = (async () => {
      try {
        const response = await fetch(
          `/api/v1/${kind}/${encodeURIComponent(id)}`,
          {
            credentials: "same-origin",
            headers: { Accept: "application/json" },
          },
        );
        if (!response.ok) return null;
        const body = (await response.json()) as Record<string, any>;
        const result = body.result ?? body;
        const name =
          kind === "dashboard"
            ? result.dashboard_title
            : kind === "chart"
              ? result.slice_name
              : result.name ?? result.table_name;
        return typeof name === "string" && name.trim() ? name.trim() : null;
      } catch {
        return null;
      }
    })();
    nameCache.set(key, request);
  }
  return request;
}

async function resolvePermalink(key: string): Promise<string | null> {
  try {
    const response = await fetch(
      `/api/v1/dashboard/permalink/${encodeURIComponent(key)}`,
      {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      },
    );
    if (!response.ok) return null;
    const body = (await response.json()) as Record<string, any>;
    const id = body.dashboardId ?? body.result?.dashboardId;
    return id === undefined || id === null ? null : String(id);
  } catch {
    return null;
  }
}

export async function resolvePageObjectLabel(): Promise<string | null> {
  const object = currentPageObject();
  if (!object) return null;
  const id = object.id ?? (await resolvePermalink(object.permalinkKey ?? ""));
  const name = id ? await fetchName(object.kind, id) : null;
  const type = PAGE_OBJECT_LABEL[object.kind];
  if (id) return `${type} #${id}${name ? ` · ${name}` : ""}`;
  return name ? `${type} · ${name}` : null;
}

import { chartFields, classifyAll } from "./ChartViz";
import type { ChartPayload } from "./chartLayout";

function asNames(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) =>
      typeof item === "string" ? item : String((item as any)?.label ?? ""),
    )
    .filter(Boolean);
}

/**
 * 聊天里的图只是查询结果，Superset 侧并没有对应的已保存图表，
 * 因此按同一口径打开该数据集的图表编辑器（Explore）。
 * SQL 结果没有数据集，返回 null，不显示入口。
 */
export function exploreLink(chart: ChartPayload): string | null {
  const datasetId = String(chart.datasetId ?? "").trim();
  if (!/^\d+$/.test(datasetId)) return null;
  const models = classifyAll(
    chart.rows,
    chart.columns,
    chart.labels,
    chart.chartType,
  );
  const model = models[0];
  if (!model) return null;

  const raw = (chart.query ?? {}) as Record<string, any>;
  const args = (raw.request ?? raw) as Record<string, any>;
  const fields = chartFields(chart.rows, chart.columns);
  const fromArgs = asNames(args.columns);
  const dimensions = fromArgs.length
    ? fromArgs
    : fields.dimension
      ? [fields.dimension]
      : [];
  const vizType =
    model.kind === "pie"
      ? "pie"
      : model.kind === "line"
        ? "echarts_timeseries_line"
        : "echarts_timeseries_bar";
  // 折线/柱状的 X 轴取第一个维度（时序就是时间列），其余维度作为分组系列
  const xColumn =
    vizType === "pie" ? undefined : model.temporal ? fields.dimension : dimensions[0];
  const groupby = dimensions.filter((name) => name !== xColumn);
  const argMetrics = asNames(args.metrics);
  const metrics = argMetrics.length
    ? argMetrics
    : model.metric
      ? [model.metric]
      : [];

  const formData: Record<string, unknown> = {
    datasource: `${datasetId}__table`,
    viz_type: vizType,
    groupby,
  };
  if (vizType === "pie") {
    // 饼图的指标控制项是单数 metric，传 metrics 会缺必填项
    formData.metric = metrics[0];
  } else {
    formData.metrics = metrics;
  }
  if (xColumn) {
    formData.x_axis = xColumn;
    if (model.temporal) formData.granularity_sqla = xColumn;
  }
  const timeRange = typeof args.time_range === "string" ? args.time_range : "";
  if (timeRange) formData.time_range = timeRange;
  const rowLimit = Number(args.row_limit);
  if (Number.isInteger(rowLimit) && rowLimit > 0) formData.row_limit = rowLimit;

  return `/explore/?form_data=${encodeURIComponent(JSON.stringify(formData))}`;
}

/**
 * 同页跳到图表编辑器，不整页刷新。
 *
 * Explore 的控件值只能经 `?form_data=` → 服务端写缓存 → 302 到 `?form_data_key=`
 * 这条链路还原，所以先用一次 HEAD 拿到重定向后的地址，再交给宿主路由切页；
 * 宿主没接住（未登录、缓存写失败等）就退回普通导航。
 */
export async function openExplore(path: string): Promise<void> {
  try {
    const response = await fetch(path, {
      method: "HEAD",
      credentials: "same-origin",
    });
    const target = new URL(response.url, window.location.href);
    if (target.pathname.endsWith("/explore/") && target.searchParams.has("form_data_key")) {
      window.history.pushState({}, "", `${target.pathname}${target.search}`);
      window.dispatchEvent(new PopStateEvent("popstate", { state: {} }));
      return;
    }
  } catch {
    // 网络/权限异常，退回整页导航
  }
  window.location.href = path;
}

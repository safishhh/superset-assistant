import { useEffect, useRef, useState } from "react";

import { exploreLink, openExplore } from "./exploreLink";
import { ChartViz, KpiGrid, chartFields, hasChart, kpiCards } from "./ChartViz";
import { chartMeta, formatCell } from "./toolResult";

const MAX_ROWS = 100;
const ZOOM_WIDTH = 920;

type ChartBlockProps = {
  rows: Record<string, any>[];
  columns: { name: string; type?: string | null }[];
  labels?: Record<string, string>;
  datasetName: string;
  rowCount?: number;
  query?: unknown;
  /** 宿主实际生效的过滤条件（`applied_filters`），比模型入参更可信 */
  appliedFilters?: unknown;
  chartType?: string;
  datasetId?: string | number;
  /** 后台审计跑在 Agent 域名下，相对链接会 404，因此只在宿主内显示入口 */
  openInExplore?: boolean;
};

function RawTable({
  rows,
  columns,
  labels,
}: {
  rows: Record<string, any>[];
  columns: { name: string; type?: string | null }[];
  labels?: Record<string, string>;
}) {
  const names = columns.length
    ? columns.map((column) => column.name)
    : Object.keys(rows[0] ?? {});
  const shown = rows.slice(0, MAX_ROWS);
  return (
    <div className="sa-chart-raw">
      <table>
        <thead>
          <tr>
            {names.map((name) => (
              <th key={name}>{labels?.[name] || name}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((row, index) => (
            <tr key={index}>
              {names.map((name) => (
                <td key={name}>{formatCell(row[name])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > shown.length ? (
        <div className="sa-chart-raw-note">
          共 {rows.length} 行，仅显示前 {shown.length} 行
        </div>
      ) : null}
    </div>
  );
}

function ChartActions({
  detailOpen,
  onToggleDetail,
  link,
}: {
  detailOpen: boolean;
  onToggleDetail: () => void;
  link: string | null;
}) {
  return (
    <div className="sa-chart-actions">
      <button
        type="button"
        className="sa-chart-detail"
        aria-expanded={detailOpen}
        onClick={onToggleDetail}
      >
        {detailOpen ? "收起详情" : "展开详情"}
      </button>
      {link ? (
        <button
          type="button"
          className="sa-chart-open"
          title="在 Superset 图表编辑器（Explore）中按相同口径打开该数据集"
          onClick={() => {
            void openExplore(link);
          }}
        >
          在图表中打开
        </button>
      ) : null}
    </div>
  );
}

function ChartZoom({
  props,
  caption,
  metric,
  link,
  onClose,
}: {
  props: ChartBlockProps;
  caption: string;
  metric: string;
  link: string | null;
  onClose: () => void;
}) {
  const [detailOpen, setDetailOpen] = useState(false);
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const [bodyWidth, setBodyWidth] = useState(0);
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previous;
    };
  }, [onClose]);
  useEffect(() => {
    const el = bodyRef.current;
    if (!el) return undefined;
    const update = () => setBodyWidth(Math.round(el.clientWidth));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return (
    <div
      className="sa-chart-zoom-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="放大查看图表"
      onClick={onClose}
    >
      <div
        className="sa-chart-zoom"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="sa-chart-zoom-head">
          <span className="sa-chart-caption">{caption}</span>
          <button
            type="button"
            className="sa-chart-zoom-close"
            aria-label="关闭"
            onClick={onClose}
          >
            ×
          </button>
        </div>
        <div ref={bodyRef} className="sa-chart-zoom-body">
          <ChartViz
            rows={props.rows}
            columns={props.columns}
            labels={props.labels}
            chartType={props.chartType}
            width={bodyWidth || ZOOM_WIDTH}
            only={metric}
          />
        </div>
        <ChartActions
          detailOpen={detailOpen}
          onToggleDetail={() => setDetailOpen((value) => !value)}
          link={link}
        />
        {detailOpen ? (
          <RawTable
            rows={props.rows}
            columns={props.columns}
            labels={props.labels}
          />
        ) : null}
      </div>
    </div>
  );
}

export function ChartBlock(props: ChartBlockProps) {
  const {
    rows,
    columns,
    labels,
    datasetName,
    rowCount,
    query,
    appliedFilters,
    chartType,
    datasetId,
    openInExplore = true,
  } = props;
  const [open, setOpen] = useState(false);
  const [zoomMetric, setZoomMetric] = useState<string | null>(null);
  const kpis = kpiCards(rows, columns, labels);
  const charts = hasChart(rows, columns, labels);
  if (!charts && !kpis.length) return null;
  const meta = chartMeta(query, labels, chartFields(rows, columns), appliedFilters);
  const caption = [datasetName, meta, rowCount ? `${rowCount} 行` : ""]
    .filter(Boolean)
    .join(" · ");
  const link = openInExplore ? exploreLink(props) : null;
  return (
    <figure className="sa-chart-block">
      {charts ? (
        <div className="sa-chart-canvas">
          <ChartViz
            rows={rows}
            columns={columns}
            labels={labels}
            chartType={chartType}
            onSelectMetric={setZoomMetric}
          />
        </div>
      ) : (
        <KpiGrid cards={kpis} />
      )}
      <figcaption className="sa-chart-caption">{caption}</figcaption>
      <ChartActions
        detailOpen={open}
        onToggleDetail={() => setOpen((value) => !value)}
        link={link}
      />
      {open ? (
        <RawTable rows={rows} columns={columns} labels={labels} />
      ) : null}
      {zoomMetric ? (
        <ChartZoom
          props={props}
          caption={caption}
          metric={zoomMetric}
          link={link}
          onClose={() => setZoomMetric(null)}
        />
      ) : null}
    </figure>
  );
}

export default ChartBlock;

import { useEffect, useState } from "react";
import {
  Card,
  Col,
  DatePicker,
  Row,
  Select,
  Statistic,
  Table,
  message,
} from "antd";
import type { Dayjs } from "dayjs";
import { api } from "../api";
import { byNumber, byText, indexColumn } from "../sorters";
import { Overview } from "../types";

const { RangePicker } = DatePicker;

function number(value: number): string {
  return Number(value || 0).toLocaleString("zh-CN");
}

function cost(value: number): string {
  return `$${Number(value || 0).toFixed(4)}`;
}

function percent(value: number | null | undefined): string {
  return value === null || value === undefined
    ? "—"
    : `${(value * 100).toFixed(1)}%`;
}

export default function OverviewPage() {
  const [days, setDays] = useState(7);
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null);
  const [data, setData] = useState<Overview | null>(null);

  useEffect(() => {
    const params = new URLSearchParams();
    if (range) {
      params.set("from", range[0].format("YYYY-MM-DD"));
      params.set("to", range[1].format("YYYY-MM-DD"));
    } else {
      params.set("days", String(days));
    }
    api<Overview>(`/overview?${params}`)
      .then(setData)
      .catch((exc) => message.error(exc.message));
  }, [days, range]);

  const maxTokens = Math.max(1, ...(data?.daily || []).map((x) => x.tokens));
  const maxTopUser = Math.max(
    1,
    ...(data?.top_users || []).map((x) => x.requests),
  );

  return (
    <div>
      <div className="filters">
        <span className="muted">快捷筛选</span>
        <Select
          value={range ? undefined : days}
          placeholder="自定义"
          style={{ width: 110 }}
          onChange={(value) => {
            setDays(value);
            setRange(null);
          }}
          options={[
            { value: 1, label: "最近 1 天" },
            { value: 7, label: "最近 7 天" },
            { value: 30, label: "最近 30 天" },
            { value: 90, label: "最近 90 天" },
          ]}
        />
        <RangePicker
          value={range}
          format="YYYY-MM-DD"
          placeholder={["开始日期", "结束日期"]}
          onChange={(value) =>
            setRange(
              value?.[0] && value[1] ? [value[0], value[1]] : null,
            )
          }
        />
      </div>

      <Row gutter={[10, 10]} className="stat-row">
        {[
          ["总请求数", number(data?.totals.requests || 0)],
          ["总Token", number(data?.totals.tokens || 0)],
          ["总成本", cost(data?.totals.cost || 0)],
          ["总工具调用", number(data?.totals.tool_calls || 0)],
          ["总错误", number(data?.totals.errors || 0)],
          ["工具成功率", percent(data?.quality?.tool_success_rate)],
          ["对话采纳率", percent(data?.quality?.feedback_adoption_rate)],
        ].map(([label, value]) => (
          <Col xs={12} md={8} xl={4} key={label}>
            <Card size="small" className="stat-card">
              <Statistic title={label} value={value} />
            </Card>
          </Col>
        ))}
      </Row>

      <Row gutter={[10, 10]}>
        <Col xs={24} xl={14}>
          <Card size="small" title="每日 Token / 错误">
            {(data?.daily || []).length === 0 ? (
              <div className="muted">暂无数据</div>
            ) : (
              <>
                <div className="bar-row bar-row-head">
                  <div className="bar-label">日期</div>
                  <div />
                  <div className="bar-fields">
                    <span>Token</span>
                    <span>错误</span>
                  </div>
                </div>
                {(data?.daily || []).map((item) => (
                  <div className="bar-row" key={item.day}>
                    <div className="bar-label">
                      <span className="bar-label-main">{item.day}</span>
                    </div>
                    <div className="bar-track">
                      <div
                        className="bar-fill"
                        style={{ width: `${(item.tokens / maxTokens) * 100}%` }}
                      />
                    </div>
                    <div className="bar-fields">
                      <span>{number(item.tokens)}</span>
                      <span>{item.errors}</span>
                    </div>
                  </div>
                ))}
              </>
            )}
          </Card>
        </Col>
        <Col xs={24} xl={10}>
          <Card size="small" title="Top 用户（请求数）">
            {(data?.top_users || []).length === 0 ? (
              <div className="muted">暂无数据</div>
            ) : (
              <>
                <div className="bar-row bar-row-head">
                  <div className="bar-label">用户</div>
                  <div />
                  <div className="bar-fields bar-fields-rev">
                    <span>请求</span>
                    <span>Token</span>
                  </div>
                </div>
                {(data?.top_users || []).map((item) => (
                  <div className="bar-row" key={item.username}>
                    <div className="bar-label">
                      <span className="bar-label-main">{item.username}</span>
                    </div>
                    <div className="bar-track">
                      <div
                        className="bar-fill"
                        style={{
                          width: `${(item.requests / maxTopUser) * 100}%`,
                        }}
                      />
                    </div>
                    <div className="bar-fields bar-fields-rev">
                      <span>{number(item.requests)}</span>
                      <span>{number(item.tokens)}</span>
                    </div>
                  </div>
                ))}
              </>
            )}
          </Card>
        </Col>
      </Row>

      <Row gutter={[10, 10]} style={{ marginTop: 10 }}>
        <Col xs={24} xl={8}>
          <Card size="small" title="模型使用">
            <Table
              size="small"
              rowKey="model_name"
              pagination={false}
              dataSource={data?.top_models || []}
              columns={[
                indexColumn<Overview["top_models"][number]>(),
                {
                  title: "模型",
                  dataIndex: "model_name",
                  sorter: byText<Overview["top_models"][number]>("model_name"),
                },
                {
                  title: "请求",
                  dataIndex: "requests",
                  align: "right",
                  sorter: byNumber<Overview["top_models"][number]>("requests"),
                },
                {
                  title: "Token",
                  dataIndex: "tokens",
                  align: "right",
                  sorter: byNumber<Overview["top_models"][number]>("tokens"),
                },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} xl={8}>
          <Card size="small" title="工具使用">
            <Table
              size="small"
              rowKey="tool_name"
              pagination={false}
              dataSource={data?.top_tools || []}
              columns={[
                indexColumn<Overview["top_tools"][number]>(),
                {
                  title: "工具",
                  dataIndex: "tool_name",
                  sorter: byText<Overview["top_tools"][number]>("tool_name"),
                },
                {
                  title: "调用",
                  dataIndex: "calls",
                  align: "right",
                  sorter: byNumber<Overview["top_tools"][number]>("calls"),
                },
              ]}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}

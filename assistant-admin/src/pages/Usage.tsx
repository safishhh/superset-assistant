import { useEffect, useState } from "react";
import {
  Card,
  Col,
  DatePicker,
  Row,
  Select,
  Table,
  Tabs,
  message,
} from "antd";
import dayjs, { Dayjs } from "dayjs";
import { api, loadFilters } from "../api";
import { byNumber, byText, indexColumn } from "../sorters";
import { AdminFilters, Usage } from "../types";
import UserSelect from "../UserSelect";

const { RangePicker } = DatePicker;

const HEAD_LABEL: Record<string, string> = {
  detail: "日期",
  day: "日期",
  user: "用户",
  user_model: "用户",
  model: "模型",
  employee: "牛马",
};

function number(value: number): string {
  return Number(value || 0).toLocaleString("zh-CN");
}

function totalsOf(items: Usage["items"]) {
  return items.reduce(
    (acc, item) => ({
      requests: acc.requests + item.requests,
      tokens: acc.tokens + item.tokens,
      cost: acc.cost + item.cost,
      toolCalls: acc.toolCalls + item.tool_calls,
      errors: acc.errors + item.errors,
    }),
    { requests: 0, tokens: 0, cost: 0, toolCalls: 0, errors: 0 },
  );
}

function modelLabel(
  modelName?: string | null,
  providerName?: string | null,
): string {
  const name = modelName || "—";
  return providerName ? `${name}（${providerName}）` : name;
}

function barLabel(
  item: Usage["items"][number],
  groupBy: string,
): { main: string; sub?: string } {
  if (groupBy === "detail") {
    return {
      main: item.day || "—",
      sub: [item.username, modelLabel(item.model_name, item.provider_name)]
        .filter(Boolean)
        .join(" · "),
    };
  }
  if (groupBy === "user_model") {
    return {
      main: item.username || "—",
      sub: modelLabel(item.model_name, item.provider_name),
    };
  }
  if (groupBy === "model") {
    return {
      main: modelLabel(item.model_name || item.key, item.provider_name),
    };
  }
  return { main: item.key || "—" };
}

export default function UsagePage() {
  const [range, setRange] = useState<[Dayjs, Dayjs]>([
    dayjs().subtract(29, "day"),
    dayjs(),
  ]);
  const [groupBy, setGroupBy] = useState("detail");
  const [username, setUsername] = useState("");
  const [modelName, setModelName] = useState("");
  const [employeeId, setEmployeeId] = useState<number | undefined>();
  const [filters, setFilters] = useState<AdminFilters>({
    users: [],
    models: [],
    employees: [],
  });
  const [data, setData] = useState<Usage | null>(null);
  const [rangeData, setRangeData] = useState<Usage | null>(null);
  const [detailPage, setDetailPage] = useState(1);

  useEffect(() => {
    loadFilters()
      .then(setFilters)
      .catch((exc) => message.error(exc.message));
  }, []);

  useEffect(() => {
    const params = new URLSearchParams({
      from: range[0].format("YYYY-MM-DD"),
      to: range[1].format("YYYY-MM-DD"),
      group_by: "day",
    });
    api<Usage>(`/usage?${params}`)
      .then(setRangeData)
      .catch((exc) => message.error(exc.message));
  }, [range]);

  useEffect(() => {
    const params = new URLSearchParams({
      from: range[0].format("YYYY-MM-DD"),
      to: range[1].format("YYYY-MM-DD"),
      group_by: groupBy,
    });
    if (username) params.set("username", username);
    if (modelName) params.set("model_name", modelName);
    if (employeeId) params.set("employee_id", String(employeeId));
    api<Usage>(`/usage?${params}`)
      .then((result) => {
        setData(result);
        setDetailPage(1);
      })
      .catch((exc) => message.error(exc.message));
  }, [range, groupBy, username, modelName, employeeId]);

  const items = data?.items || [];
  const rangeTotals = totalsOf(rangeData?.items || []);
  const rangeLabel = `${range[0].format("YYYY-MM-DD")} ~ ${range[1].format(
    "YYYY-MM-DD",
  )}`;
  const maxRequests = Math.max(1, ...items.map((item) => item.requests));

  const detailColumns = [
    indexColumn<Usage["items"][number]>((detailPage - 1) * 20),
    ...(groupBy === "detail"
      ? [
          {
            key: "day",
            title: "日期",
            dataIndex: "day",
            width: 110,
            sorter: byText<Usage["items"][number]>("day"),
            render: (value: string) => (
              <span className="time-cell">{value || "—"}</span>
            ),
          },
          {
            key: "username",
            title: "用户",
            dataIndex: "username",
            width: 120,
            sorter: byText<Usage["items"][number]>("username"),
          },
          {
            key: "model_name",
            title: "模型",
            dataIndex: "model_name",
            width: 180,
            ellipsis: true,
            sorter: byText<Usage["items"][number]>("model_name"),
          },
          {
            key: "provider_name",
            title: "供应商",
            dataIndex: "provider_name",
            width: 110,
            ellipsis: true,
            sorter: byText<Usage["items"][number]>("provider_name"),
          },
          {
            key: "employee_name",
            title: "牛马",
            dataIndex: "employee_name",
            width: 110,
            ellipsis: true,
            sorter: byText<Usage["items"][number]>("employee_name"),
          },
        ]
      : [
          {
            key: "key",
            title: "分组",
            dataIndex: "key",
            sorter: byText<Usage["items"][number]>("key"),
          },
        ]),
    {
      key: "requests",
      title: "请求",
      dataIndex: "requests",
      align: "right" as const,
      sorter: byNumber<Usage["items"][number]>("requests"),
    },
    {
      key: "tokens",
      title: "Token",
      dataIndex: "tokens",
      align: "right" as const,
      sorter: byNumber<Usage["items"][number]>("tokens"),
      render: number,
    },
    {
      key: "cost",
      title: "成本",
      dataIndex: "cost",
      align: "right" as const,
      sorter: byNumber<Usage["items"][number]>("cost"),
      render: (value: number) => `$${Number(value || 0).toFixed(4)}`,
    },
    {
      key: "tool_calls",
      title: "工具",
      dataIndex: "tool_calls",
      align: "right" as const,
      sorter: byNumber<Usage["items"][number]>("tool_calls"),
    },
    {
      key: "errors",
      title: "错误",
      dataIndex: "errors",
      align: "right" as const,
      sorter: byNumber<Usage["items"][number]>("errors"),
    },
  ];

  return (
    <div>
      <div className="filters">
        <RangePicker
          value={range}
          allowClear={false}
          format="YYYY-MM-DD"
          placeholder={["开始日期", "结束日期"]}
          style={{ width: 230 }}
          onChange={(value) => {
            if (value?.[0] && value[1]) setRange([value[0], value[1]]);
          }}
        />
        <UserSelect
          localUsers={filters.users}
          value={username}
          onChange={setUsername}
        />
        <Select
          placeholder="模型(供应商)"
          value={modelName || undefined}
          onChange={(value) => setModelName(value ?? "")}
          style={{ width: 230 }}
          allowClear
          showSearch
          optionFilterProp="label"
          options={filters.models.map((item) => ({
            value: item,
            label: modelLabel(item, filters.model_providers?.[item]),
          }))}
        />
        <Select
          placeholder="牛马"
          value={employeeId}
          onChange={setEmployeeId}
          style={{ width: 130 }}
          allowClear
          showSearch
          optionFilterProp="label"
          options={filters.employees.map((item) => ({
            value: item.id,
            label: item.name,
          }))}
        />
        <Select
          value={groupBy}
          style={{ width: 264 }}
          onChange={setGroupBy}
          options={[
            { value: "detail", label: "不汇总（用户+天+模型+牛马）" },
            { value: "day", label: "按天汇总" },
            { value: "user", label: "按用户汇总" },
            { value: "model", label: "按模型汇总" },
            { value: "employee", label: "按牛马汇总" },
          ]}
        />
      </div>

      <Row gutter={[10, 10]} className="stat-row">
        {[
          ["总请求数", number(rangeTotals.requests)],
          ["总Token", number(rangeTotals.tokens)],
          ["总成本", `$${rangeTotals.cost.toFixed(4)}`],
          ["总工具调用", number(rangeTotals.toolCalls)],
          ["总错误", number(rangeTotals.errors)],
        ].map(([label, value]) => (
          <Col xs={12} md={8} xl={4} key={label}>
            <Card size="small" className="stat-card usage-stat">
              <div className="usage-stat-label">{label}</div>
              <div className="usage-stat-range" title={rangeLabel}>
                {rangeLabel}
              </div>
              <div className="usage-stat-total">
                {value}
              </div>
            </Card>
          </Col>
        ))}
      </Row>

      <Tabs
        size="small"
        defaultActiveKey="visual"
        items={[
          {
            key: "visual",
            label: "明细可视化",
            children: (
              <Card size="small">
                {items.length === 0 ? (
                  <div className="muted">暂无数据</div>
                ) : (
                  <div className="bar-list">
                    <div className="bar-row bar-row-head">
                      <div className="bar-label">{HEAD_LABEL[groupBy] || "分组"}</div>
                      <div />
                      <div className="bar-fields bar-fields-3">
                        <span>请求</span>
                        <span>错误</span>
                        <span>Token</span>
                      </div>
                    </div>
                    {items.map((item) => {
                      const label = barLabel(item, groupBy);
                      return (
                        <div className="bar-row" key={item.key}>
                          <div
                            className="bar-label"
                            title={`${label.main}${label.sub ? ` · ${label.sub}` : ""}`}
                          >
                            <span className="bar-label-main">{label.main}</span>
                            {label.sub ? (
                              <span className="bar-label-sub">{label.sub}</span>
                            ) : null}
                          </div>
                          <div className="bar-track">
                            <div
                              className="bar-fill"
                              style={{
                                width: `${(item.requests / maxRequests) * 100}%`,
                              }}
                            />
                          </div>
                          <div className="bar-fields bar-fields-3">
                            <span>{number(item.requests)}</span>
                            <span>{item.errors}</span>
                            <span>{number(item.tokens)}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </Card>
            ),
          },
          {
            key: "detail",
            label: "明细",
            children: (
              <Card size="small">
                <Table
                  size="small"
                  rowKey="key"
                  dataSource={items}
                  columns={detailColumns}
                  scroll={{ x: "max-content" }}
                  pagination={{
                    current: detailPage,
                    pageSize: 20,
                    hideOnSinglePage: true,
                    onChange: setDetailPage,
                  }}
                />
              </Card>
            ),
          },
        ]}
      />
    </div>
  );
}

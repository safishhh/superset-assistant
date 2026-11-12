import { useEffect, useState } from "react";
import {
  Card,
  Col,
  DatePicker,
  Row,
  Select,
  Table,
  message,
} from "antd";
import dayjs, { Dayjs } from "dayjs";
import { api, loadFilters } from "../api";
import { byNumber, byText, indexColumn } from "../sorters";
import { AdminFilters, Usage } from "../types";
import UserSelect from "../UserSelect";

const { RangePicker } = DatePicker;

type RankItem = {
  name: string;
  tokens: number;
  requests: number;
};

function number(value: number): string {
  return Number(value || 0).toLocaleString("zh-CN");
}

function modelLabel(
  modelName?: string | null,
  providerName?: string | null,
): string {
  const name = modelName || "—";
  return providerName ? `${name}（${providerName}）` : name;
}

function RankList({ items }: { items: RankItem[] }) {
  if (items.length === 0) {
    return <div className="muted">暂无数据</div>;
  }
  const max = Math.max(1, ...items.map((item) => item.tokens));
  return (
    <div className="rank-list">
      {items.map((item, index) => (
        <div className="rank-row" key={item.name}>
          <span className="rank-index">{index + 1}</span>
          <div className="rank-main">
            <div className="rank-name" title={item.name}>
              {item.name}
            </div>
            <div className="rank-track">
              <div
                className="rank-fill"
                style={{ width: `${(item.tokens / max) * 100}%` }}
              />
            </div>
          </div>
          <div className="rank-value">
            <strong>{number(item.tokens)}</strong>
            <span>{number(item.requests)} 次</span>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function RankingsPage() {
  const [range, setRange] = useState<[Dayjs, Dayjs]>([
    dayjs().subtract(29, "day"),
    dayjs(),
  ]);
  const [username, setUsername] = useState("");
  const [modelName, setModelName] = useState("");
  const [filters, setFilters] = useState<AdminFilters>({
    users: [],
    models: [],
    employees: [],
  });
  const [data, setData] = useState<Usage | null>(null);
  const [tablePage, setTablePage] = useState(1);

  useEffect(() => {
    loadFilters()
      .then(setFilters)
      .catch((exc) => message.error(exc.message));
  }, []);

  useEffect(() => {
    const params = new URLSearchParams({
      from: range[0].format("YYYY-MM-DD"),
      to: range[1].format("YYYY-MM-DD"),
      group_by: "user_model",
    });
    if (username) params.set("username", username);
    if (modelName) params.set("model_name", modelName);
    api<Usage>(`/usage?${params}`)
      .then((result) => {
        setData(result);
        setTablePage(1);
      })
      .catch((exc) => message.error(exc.message));
  }, [range, username, modelName]);

  const topUsers: RankItem[] = (data?.top_users || []).map((item) => ({
    name: item.username,
    tokens: item.tokens,
    requests: item.requests,
  }));
  const topModels: RankItem[] = (data?.top_models || []).map((item) => ({
    name: modelLabel(item.model_name, item.provider_name),
    tokens: item.tokens,
    requests: item.requests,
  }));
  const topEmployees: RankItem[] = (data?.top_employees || []).map((item) => ({
    name: item.employee_name,
    tokens: item.tokens,
    requests: item.requests,
  }));

  const detailColumns = [
    indexColumn<Usage["items"][number]>((tablePage - 1) * 20),
    {
      key: "username",
      title: "用户",
      dataIndex: "username",
      width: 140,
      sorter: byText<Usage["items"][number]>("username"),
    },
    {
      key: "model_name",
      title: "模型",
      dataIndex: "model_name",
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
      key: "requests",
      title: "请求",
      dataIndex: "requests",
      width: 90,
      align: "right" as const,
      sorter: byNumber<Usage["items"][number]>("requests"),
    },
    {
      key: "tokens",
      title: "Token",
      dataIndex: "tokens",
      width: 110,
      align: "right" as const,
      sorter: byNumber<Usage["items"][number]>("tokens"),
      render: number,
    },
    {
      key: "cost",
      title: "成本",
      dataIndex: "cost",
      width: 100,
      align: "right" as const,
      sorter: byNumber<Usage["items"][number]>("cost"),
      render: (value: number) => `$${Number(value || 0).toFixed(4)}`,
    },
    {
      key: "tool_calls",
      title: "工具",
      dataIndex: "tool_calls",
      width: 80,
      align: "right" as const,
      sorter: byNumber<Usage["items"][number]>("tool_calls"),
    },
    {
      key: "errors",
      title: "错误",
      dataIndex: "errors",
      width: 80,
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
      </div>

      <Row gutter={[10, 10]}>
        <Col xs={24} xl={8}>
          <Card size="small" title="Top 用户 · Token">
            <RankList items={topUsers} />
          </Card>
        </Col>
        <Col xs={24} xl={8}>
          <Card size="small" title="Top 模型 · Token">
            <RankList items={topModels} />
          </Card>
        </Col>
        <Col xs={24} xl={8}>
          <Card size="small" title="Top 牛马 · Token">
            <RankList items={topEmployees} />
          </Card>
        </Col>
      </Row>

      <Row style={{ marginTop: 10 }}>
        <Col span={24}>
          <Card size="small" title="按用户、模型分组">
            <Table
              size="small"
              rowKey="key"
              dataSource={data?.items || []}
              columns={detailColumns}
              scroll={{ x: "max-content" }}
              pagination={{
                current: tablePage,
                pageSize: 20,
                hideOnSinglePage: true,
                onChange: setTablePage,
              }}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}

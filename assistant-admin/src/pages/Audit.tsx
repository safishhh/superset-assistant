import { useEffect, useState } from "react";
import {
  Button,
  Card,
  DatePicker,
  Descriptions,
  Drawer,
  Input,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  message,
} from "antd";
import dayjs, { Dayjs } from "dayjs";
import { api, loadFilters } from "../api";
import {
  indexColumn,
  nextSort,
  sortOrderFor,
  type SortState,
} from "../sorters";
import {
  AdminFilters,
  AdminOperation,
  Conversation,
  ConversationDetail,
  Paged,
  WriteAction,
} from "../types";
import UserSelect from "../UserSelect";
import ConversationView from "./ConversationView";

const { RangePicker } = DatePicker;

function time(value: string): string {
  return value ? dayjs(value).format("YYYY-MM-DD HH:mm:ss") : "—";
}

function number(value: number): string {
  return Number(value || 0).toLocaleString("zh-CN");
}

function statusTag(status: string) {
  const color =
    status === "ok" ? "green" : status === "canceled" ? "orange" : "red";
  return <Tag color={color}>{status}</Tag>;
}

function Json({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="muted">—</span>;
  return <pre className="json">{JSON.stringify(value, null, 2)}</pre>;
}

export default function AuditPage() {
  const [tab, setTab] = useState("conversations");
  const [username, setUsername] = useState("");
  const [modelName, setModelName] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<string | undefined>();
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null);
  const [filters, setFilters] = useState<AdminFilters>({
    users: [],
    models: [],
    employees: [],
  });
  const [employeeId, setEmployeeId] = useState<number | undefined>();
  const [data, setData] = useState<Paged<Conversation> | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [convSort, setConvSort] = useState<SortState | null>(null);
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [drawer, setDrawer] = useState(false);

  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");
  const [ops, setOps] = useState<Paged<AdminOperation> | null>(null);
  const [opsPage, setOpsPage] = useState(1);
  const [opsSort, setOpsSort] = useState<SortState | null>(null);
  const [writeActions, setWriteActions] =
    useState<Paged<WriteAction> | null>(null);
  const [writePage, setWritePage] = useState(1);
  const [writeSort, setWriteSort] = useState<SortState | null>(null);

  const loadConversations = (
    nextPage = page,
    nextSize = pageSize,
    sort = convSort,
  ) => {
    const params = new URLSearchParams({
      page: String(nextPage),
      page_size: String(nextSize),
      sort_by: sort?.field ?? "last_at",
      sort_order: sort?.order ?? "desc",
    });
    if (username) params.set("username", username);
    if (modelName) params.set("model_name", modelName);
    if (search) params.set("search", search);
    if (status) params.set("status", status);
    if (employeeId) params.set("employee_id", String(employeeId));
    if (range) {
      params.set("from", range[0].format("YYYY-MM-DD"));
      params.set("to", range[1].format("YYYY-MM-DD"));
    }
    api<Paged<Conversation>>(`/audit/conversations?${params}`)
      .then((result) => {
        setData(result);
        setPage(result.page);
        setPageSize(result.page_size);
      })
      .catch((exc) => message.error(exc.message));
  };

  const loadOperations = (nextPage = opsPage, sort = opsSort) => {
    const params = new URLSearchParams({
      page: String(nextPage),
      page_size: "20",
      sort_by: sort?.field ?? "created_at",
      sort_order: sort?.order ?? "desc",
    });
    if (actor) params.set("actor", actor);
    if (action) params.set("action", action);
    api<Paged<AdminOperation>>(`/audit/operations?${params}`)
      .then((result) => {
        setOps(result);
        setOpsPage(result.page);
      })
      .catch((exc) => message.error(exc.message));
  };

  const loadWriteActions = (nextPage = writePage, sort = writeSort) => {
    const params = new URLSearchParams({
      page: String(nextPage),
      page_size: "20",
      sort_by: sort?.field ?? "created_at",
      sort_order: sort?.order ?? "desc",
    });
    api<Paged<WriteAction>>(`/audit/write-actions?${params}`)
      .then((result) => {
        setWriteActions(result);
        setWritePage(result.page);
      })
      .catch((exc) => message.error(exc.message));
  };

  useEffect(() => {
    if (tab === "conversations") loadConversations(1);
    else if (tab === "operations") loadOperations(1);
    else loadWriteActions(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  useEffect(() => {
    loadFilters()
      .then(setFilters)
      .catch((exc) => message.error(exc.message));
  }, []);

  const openDetail = async (id: string) => {
    try {
      setDetail(await api<ConversationDetail>(`/audit/conversations/${id}`));
      setDrawer(true);
    } catch (exc) {
      message.error((exc as Error).message);
    }
  };

  const conversationColumns = [
    indexColumn<Conversation>((page - 1) * pageSize),
    ...[
      {
        key: "title",
        title: "问题",
        dataIndex: "title",
        ellipsis: true,
        render: (value: string, record: Conversation) => (
          <a onClick={() => openDetail(record.id)}>{value || record.id}</a>
        ),
      },
      { key: "username", title: "用户", dataIndex: "username", width: 90 },
      {
        key: "model_name",
        title: "模型",
        dataIndex: "model_name",
        width: 170,
        ellipsis: true,
      },
      {
        key: "run_count",
        title: "轮次",
        dataIndex: "run_count",
        width: 40,
        align: "right" as const,
      },
      {
        key: "tokens",
        title: "Token",
        width: 90,
        align: "right" as const,
        render: (_: unknown, record: Conversation) =>
          number(record.input_tokens + record.output_tokens),
      },
      {
        key: "cost",
        title: "成本",
        dataIndex: "cost",
        width: 80,
        align: "right" as const,
        render: (value: number) => `$${Number(value || 0).toFixed(4)}`,
      },
      {
        key: "status",
        title: "状态",
        dataIndex: "status",
        width: 120,
        render: (value: string, record: Conversation) => (
          <Space size={4}>
            {statusTag(value)}
            {record.deleted ? <Tag color="red">已删除</Tag> : null}
          </Space>
        ),
      },
      {
        key: "started_at",
        title: "创建时间",
        dataIndex: "started_at",
        width: 145,
        render: (value: string) => (
          <span className="time-cell">{time(value)}</span>
        ),
      },
      {
        key: "last_at",
        title: "最后活动",
        dataIndex: "last_at",
        width: 145,
        render: (value: string) => (
          <span className="time-cell">{time(value)}</span>
        ),
      },
    ].map((column) => ({
      ...column,
      sorter: column.key !== "title",
      sortOrder:
        column.key === "title" ? null : sortOrderFor(convSort, column.key),
    })),
  ];

  const operationColumns = [
    indexColumn<AdminOperation>((opsPage - 1) * 20),
    ...[
      {
        key: "created_at",
        title: "时间",
        dataIndex: "created_at",
        width: 150,
        render: (value: string) => (
          <span className="time-cell">{time(value)}</span>
        ),
      },
      { key: "actor", title: "操作人", dataIndex: "actor", width: 100 },
      { key: "action", title: "动作", dataIndex: "action", width: 180 },
      {
        key: "target_type",
        title: "对象",
        width: 160,
        render: (_: unknown, record: AdminOperation) =>
          `${record.target_type}#${record.target_id}`,
      },
      { key: "ip", title: "IP", dataIndex: "ip", width: 120 },
    ].map((column) => ({
      ...column,
      sorter: true,
      sortOrder: sortOrderFor(opsSort, column.key),
    })),
  ];

  const writeColumns = [
    indexColumn<WriteAction>((writePage - 1) * 20),
    ...[
      {
        key: "created_at",
        title: "时间",
        dataIndex: "created_at",
        width: 150,
        render: (value: string) => (
          <span className="time-cell">{time(value)}</span>
        ),
      },
      { key: "username", title: "用户", dataIndex: "username", width: 100 },
      {
        key: "action_type",
        title: "类型",
        dataIndex: "action_type",
        width: 170,
      },
      {
        key: "risk_level",
        title: "风险",
        dataIndex: "risk_level",
        width: 80,
        render: (value: string) => (
          <Tag color={value === "high" ? "red" : "orange"}>
            {value === "high" ? "高风险" : "中风险"}
          </Tag>
        ),
      },
      {
        key: "status",
        title: "状态",
        dataIndex: "status",
        width: 110,
        render: (value: string) => (
          <Tag
            color={
              value === "executed"
                ? "green"
                : value === "failed" || value === "rollback_failed"
                  ? "red"
                  : value === "rolled_back"
                    ? "purple"
                    : "default"
            }
          >
            {value}
          </Tag>
        ),
      },
      {
        key: "summary",
        title: "摘要",
        dataIndex: "summary",
        ellipsis: true,
      },
      {
        key: "executed_at",
        title: "执行时间",
        dataIndex: "executed_at",
        width: 150,
        render: (value: string | null) => (
          <span className="time-cell">{value ? time(value) : "—"}</span>
        ),
      },
    ].map((column) => ({
      ...column,
      sorter: true,
      sortOrder: sortOrderFor(writeSort, column.key),
    })),
  ];

  return (
    <div>
      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          { key: "conversations", label: "对话审计" },
          { key: "operations", label: "管理操作" },
          { key: "write_actions", label: "AI 写操作" },
        ]}
      />

      {tab === "conversations" ? (
        <Card size="small">
          <div className="filters">
              <UserSelect
                localUsers={filters.users}
                value={username}
                onChange={setUsername}
              />
            <Select
              placeholder="模型"
              value={modelName || undefined}
              onChange={(value) => setModelName(value ?? "")}
              style={{ width: 170 }}
              allowClear
              showSearch
              optionFilterProp="label"
              options={filters.models.map((item) => ({
                value: item,
                label: item,
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
              options={(filters.employees || []).map((item) => ({
                value: item.id,
                label: item.name,
              }))}
            />
            <Input
              placeholder="问题关键词 / 会话 ID"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{ width: 220 }}
              allowClear
            />
            <Select
              placeholder="状态"
              value={status}
              onChange={setStatus}
              style={{ width: 110 }}
              allowClear
              options={[
                { value: "ok", label: "ok" },
                { value: "error", label: "error" },
                { value: "canceled", label: "canceled" },
              ]}
            />
            <RangePicker
              value={range}
              placeholder={["开始日期", "结束日期"]}
              onChange={(value) =>
                setRange(value ? [value[0]!, value[1]!] : null)
              }
            />
            <Button type="primary" onClick={() => loadConversations(1)}>
              查询
            </Button>
          </div>
          <Table
            size="small"
            rowKey="id"
            dataSource={data?.items || []}
            columns={conversationColumns}
            onChange={(pagination, _filters, sorter, extra) => {
              const sorting = extra.action === "sort";
              const next = sorting ? nextSort(sorter) : convSort;
              setConvSort(next);
              loadConversations(
                sorting ? 1 : (pagination.current ?? 1),
                pagination.pageSize ?? pageSize,
                next,
              );
            }}
            pagination={{
              current: data?.page || 1,
              pageSize: data?.page_size || 20,
              total: data?.total || 0,
              showSizeChanger: true,
            }}
          />
        </Card>
      ) : tab === "operations" ? (
        <Card size="small">
          <div className="filters">
            <Input
              placeholder="操作人"
              value={actor}
              onChange={(e) => setActor(e.target.value)}
              style={{ width: 140 }}
              allowClear
            />
            <Input
              placeholder="动作，如 model.update"
              value={action}
              onChange={(e) => setAction(e.target.value)}
              style={{ width: 200 }}
              allowClear
            />
            <Button type="primary" onClick={() => loadOperations(1)}>
              查询
            </Button>
          </div>
          <Table
            size="small"
            rowKey="id"
            dataSource={ops?.items || []}
            expandable={{
              expandedRowRender: (record) => (
                <div>
                  <h4>修改前</h4>
                  <Json value={record.before_json} />
                  <h4>修改后</h4>
                  <Json value={record.after_json} />
                </div>
              ),
            }}
            columns={operationColumns}
            onChange={(pagination, _filters, sorter, extra) => {
              const sorting = extra.action === "sort";
              const next = sorting ? nextSort(sorter) : opsSort;
              setOpsSort(next);
              loadOperations(
                sorting ? 1 : (pagination.current ?? 1),
                next,
              );
            }}
            pagination={{
              current: ops?.page || 1,
              pageSize: 20,
              total: ops?.total || 0,
            }}
          />
        </Card>
      ) : (
        <Card size="small" title="AI 写操作审计">
          <Table
            size="small"
            rowKey="id"
            dataSource={writeActions?.items || []}
            columns={writeColumns}
            scroll={{ x: "max-content" }}
            expandable={{
              expandedRowRender: (record) => (
                <div>
                  <h4>执行计划</h4>
                  <Json value={record.plan} />
                  <h4>执行前快照</h4>
                  <Json value={record.snapshot} />
                  <h4>执行结果</h4>
                  <Json value={record.result} />
                  <h4>回滚方案</h4>
                  <Json value={record.rollback} />
                  {record.error ? (
                    <>
                      <h4>错误</h4>
                      <div className="content-box">{record.error}</div>
                    </>
                  ) : null}
                </div>
              ),
            }}
            onChange={(pagination, _filters, sorter, extra) => {
              const sorting = extra.action === "sort";
              const next = sorting ? nextSort(sorter) : writeSort;
              setWriteSort(next);
              loadWriteActions(
                sorting ? 1 : (pagination.current ?? 1),
                next,
              );
            }}
            pagination={{
              current: writeActions?.page || 1,
              pageSize: 20,
              total: writeActions?.total || 0,
            }}
          />
        </Card>
      )}

      <Drawer
        width={920}
        open={drawer}
        onClose={() => setDrawer(false)}
        title={
          <span className="drawer-title">
            {detail?.title || "对话详情"}
            {detail?.deleted ? <Tag color="red">已删除</Tag> : null}
          </span>
        }
        destroyOnClose
      >
        {detail ? (
          <>
            <Descriptions size="small" column={2} bordered>
              <Descriptions.Item label="会话 ID" span={2}>
                <span className="mono">{detail.id}</span>
              </Descriptions.Item>
              <Descriptions.Item label="用户">{detail.username}</Descriptions.Item>
              <Descriptions.Item label="牛马">
                {detail.employee_name || "默认助手"}
              </Descriptions.Item>
              <Descriptions.Item label="模型">{detail.model_name}</Descriptions.Item>
              <Descriptions.Item label="轮次">{detail.run_count}</Descriptions.Item>
              <Descriptions.Item label="Token">
                {number(detail.input_tokens + detail.output_tokens)}
              </Descriptions.Item>
              <Descriptions.Item label="创建时间">
                {time(detail.started_at)}
              </Descriptions.Item>
              <Descriptions.Item label="最后活动">
                {time(detail.last_at)}
              </Descriptions.Item>
              <Descriptions.Item label="状态" span={2}>
                {detail.deleted ? (
                  <Tag color="red">
                    已删除
                    {detail.deleted_at ? ` · ${time(detail.deleted_at)}` : ""}
                  </Tag>
                ) : (
                  <Tag color="green">正常</Tag>
                )}
              </Descriptions.Item>
            </Descriptions>

            <div className="detail-section">
              <h4>对话</h4>
              <p className="muted" style={{ marginTop: 0 }}>
                与用户端一致：思考过程、执行步骤（展开看参数与完整结果）、图表与正文穿插。
              </p>
              <ConversationView detail={detail} />
            </div>
          </>
        ) : null}
      </Drawer>
    </div>
  );
}

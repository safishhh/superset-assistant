import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Collapse,
  DatePicker,
  Descriptions,
  Drawer,
  Select,
  Space,
  Table,
  Tag,
  message,
} from "antd";
import type { Dayjs } from "dayjs";
import dayjs from "dayjs";
import { api, loadFilters } from "../api";
import {
  indexColumn,
  nextSort,
  sortOrderFor,
  type SortState,
} from "../sorters";
import { ConversationDetail, FeedbackDetail, Paged } from "../types";
import UserSelect from "../UserSelect";

function time(value: string | null | undefined): string {
  return value ? dayjs(value).format("YYYY-MM-DD HH:mm:ss") : "—";
}

function ratingTag(rating: string) {
  if (rating === "up") return <Tag color="green">有帮助</Tag>;
  if (rating === "down") return <Tag color="red">没帮助</Tag>;
  return <Tag>{rating}</Tag>;
}

function Json({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span>—</span>;
  return <pre className="json">{JSON.stringify(value, null, 2)}</pre>;
}

export default function FeedbackPage() {
  const [username, setUsername] = useState("");
  const [filterUsers, setFilterUsers] = useState<string[]>([]);
  const [rating, setRating] = useState<"up" | "down" | undefined>(undefined);
  const [range, setRange] = useState<[Dayjs | null, Dayjs | null] | null>(null);
  const [data, setData] = useState<Paged<FeedbackDetail> | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [sort, setSort] = useState<SortState | null>(null);
  const [active, setActive] = useState<FeedbackDetail | null>(null);
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [drawer, setDrawer] = useState(false);
  const [hitRunId, setHitRunId] = useState("");

  const loadFeedback = (
    nextPage = page,
    nextSize = pageSize,
    nextSort: SortState | null = sort,
    nextRange: [Dayjs | null, Dayjs | null] | null = range,
    nextUsername: string = username,
  ) => {
    const params = new URLSearchParams({
      page: String(nextPage),
      page_size: String(nextSize),
      sort_by: nextSort?.field ?? "created_at",
      sort_order: nextSort?.order ?? "desc",
    });
    if (nextUsername.trim()) params.set("username", nextUsername.trim());
    if (rating) params.set("rating", rating);
    if (nextRange?.[0]) params.set("from", nextRange[0].format("YYYY-MM-DD"));
    if (nextRange?.[1]) params.set("to", nextRange[1].format("YYYY-MM-DD"));
    api<Paged<FeedbackDetail>>(`/feedback?${params}`)
      .then((result) => {
        setData(result);
        setPage(result.page);
        setPageSize(result.page_size);
      })
      .catch((exc) => message.error(exc.message));
  };

  useEffect(() => {
    loadFeedback(1);
    loadFilters()
      .then((data) => setFilterUsers(data.users))
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 按会话 id 现查完整会话（反馈表只存关联 id，不重复存消息）
  const openConversation = async (row: FeedbackDetail) => {
    setActive(row);
    setDetail(null);
    setDrawer(true);
    setHitRunId("");
    try {
      const full = await api<ConversationDetail>(
        `/audit/conversations/${row.conversation_id}`,
      );
      setDetail(full);
      const assistants = full.messages.filter((item) => item.role === "assistant");
      const hit = assistants[row.turn_index - 1];
      setHitRunId(hit?.run_id ?? "");
      if (hit) {
        window.setTimeout(() => {
          document
            .getElementById(`fb-msg-${hit.id}`)
            ?.scrollIntoView({ block: "center" });
        }, 120);
      }
    } catch (exc) {
      message.error((exc as Error).message);
    }
  };

  const closeDrawer = () => {
    setDrawer(false);
    setActive(null);
    setDetail(null);
    setHitRunId("");
  };

  const hitClass =
    active?.rating === "down" ? "fb-hit fb-hit-down" : "fb-hit fb-hit-up";

  const columns = [
    indexColumn<FeedbackDetail>((page - 1) * pageSize),
    ...[
      {
        key: "created_at",
        title: "反馈时间",
        dataIndex: "created_at",
        width: 145,
        render: (value: string) => (
          <span className="time-cell">{time(value)}</span>
        ),
      },
      {
        key: "username",
        title: "用户",
        dataIndex: "username",
        width: 90,
        ellipsis: true,
      },
      {
        key: "rating",
        title: "评分",
        dataIndex: "rating",
        width: 84,
        render: (value: string) => ratingTag(value),
      },
      {
        key: "turn_index",
        title: "轮次",
        dataIndex: "turn_index",
        width: 60,
        align: "right" as const,
      },
      {
        key: "conversation_title",
        title: "会话标题",
        dataIndex: "conversation_title",
        ellipsis: true,
      },
      {
        key: "answer_preview",
        title: "回答预览",
        dataIndex: "answer_preview",
        ellipsis: true,
      },
      {
        key: "conversation_started_at",
        title: "会话创建",
        dataIndex: "conversation_started_at",
        width: 145,
        render: (value: string | null) => (
          <span className="time-cell">{time(value)}</span>
        ),
      },
      {
        key: "conversation_last_at",
        title: "会话更新",
        dataIndex: "conversation_last_at",
        width: 145,
        render: (value: string | null) => (
          <span className="time-cell">{time(value)}</span>
        ),
      },
      {
        key: "action",
        title: "操作",
        width: 100,
        render: (_: unknown, record: FeedbackDetail) => (
          <Button size="small" onClick={() => void openConversation(record)}>
            查看会话
          </Button>
        ),
      },
    ].map((column) => {
      const sortable = [
        "created_at",
        "username",
        "rating",
        "turn_index",
      ].includes(column.key);
      return {
        ...column,
        sorter: sortable,
        sortOrder: sortable ? sortOrderFor(sort, column.key) : null,
      };
    }),
  ];

  return (
    <Card size="small">
      <div className="filters">
        <UserSelect
          localUsers={filterUsers}
          value={username}
          width={140}
          onChange={(value) => {
            setUsername(value);
            loadFeedback(1, pageSize, sort, range, value);
          }}
        />
        <Select<"up" | "down">
          placeholder="评分"
          value={rating}
          onChange={setRating}
          style={{ width: 110 }}
          allowClear
          options={[
            { value: "up", label: "有帮助" },
            { value: "down", label: "没帮助" },
          ]}
        />
        <DatePicker.RangePicker
          value={range}
          onChange={(value) => setRange(value)}
          allowClear
          style={{ width: 250 }}
        />
        <Button type="primary" onClick={() => loadFeedback(1)}>
          查询
        </Button>
      </div>
      <Table
        size="small"
        rowKey="id"
        dataSource={data?.items || []}
        columns={columns}
        onChange={(pagination, _filters, sorter, extra) => {
          const sorting = extra.action === "sort";
          const next = sorting ? nextSort(sorter) : sort;
          setSort(next);
          loadFeedback(
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
      <Drawer
        width={920}
        open={drawer}
        onClose={closeDrawer}
        title={
          <span className="drawer-title">
            {detail?.title || active?.conversation_title || "会话详情"}
            {active ? ratingTag(active.rating) : null}
            {active?.comment ? (
              <Tag color="orange">评价备注：{active.comment}</Tag>
            ) : null}
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
              <Descriptions.Item label="模型">{detail.model_name}</Descriptions.Item>
              <Descriptions.Item label="轮次">{detail.run_count}</Descriptions.Item>
              <Descriptions.Item label="被评轮次">
                #{active?.turn_index ?? "—"} · {active?.rating}
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
              <h4>消息（被评轮次已高亮）</h4>
              {detail.messages.map((item) => {
                const isHit = Boolean(hitRunId) && item.run_id === hitRunId;
                return (
                  <div
                    key={item.id}
                    id={`fb-msg-${item.id}`}
                    className={isHit ? hitClass : "fb-msg"}
                  >
                    <Space size={6}>
                      <Tag color={item.role === "user" ? "blue" : "green"}>
                        {item.role}
                      </Tag>
                      <span className="muted">
                        {time(item.created_at)} ·{" "}
                        {item.input_tokens + item.output_tokens} tok
                        {item.latency_ms ? ` · ${item.latency_ms}ms` : ""}
                      </span>
                      {isHit ? (
                        <Tag color={active?.rating === "up" ? "green" : "red"}>
                          {active?.rating === "up" ? "被评：有帮助" : "被评：没帮助"}
                        </Tag>
                      ) : null}
                    </Space>
                    <div className="content-box" style={{ marginTop: 4 }}>
                      {item.content || item.error || "—"}
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="detail-section">
              <h4>工具调用（完整结果）</h4>
              {detail.tool_calls.length === 0 ? (
                <div className="muted">本轮无工具调用</div>
              ) : (
                <Collapse
                  size="small"
                  items={detail.tool_calls.map((item) => ({
                    key: String(item.id),
                    label: (
                      <div className="tool-head">
                        <Tag color="blue">{item.tool_name}</Tag>
                        <span className="muted">
                          #{item.sequence} · {item.status} · {item.duration_ms}ms ·{" "}
                          {item.row_count} 行 · {time(item.created_at)}
                        </span>
                      </div>
                    ),
                    children: (
                      <div>
                        {item.sql_text ? (
                          <>
                            <h4>SQL</h4>
                            <pre className="json">{item.sql_text}</pre>
                          </>
                        ) : null}
                        <h4>参数</h4>
                        <Json value={item.args_json} />
                        <h4>完整结果</h4>
                        <Json value={item.result_json} />
                        {item.error ? (
                          <>
                            <h4>错误</h4>
                            <div className="content-box">{item.error}</div>
                          </>
                        ) : null}
                      </div>
                    ),
                  }))}
                />
              )}
            </div>
          </>
        ) : (
          <div className="muted">正在加载会话…</div>
        )}
      </Drawer>
    </Card>
  );
}

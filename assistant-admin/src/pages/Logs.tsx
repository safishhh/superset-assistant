import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Button,
  Card,
  Descriptions,
  Drawer,
  Input,
  InputNumber,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  message,
} from "antd";
import dayjs from "dayjs";
import { api } from "../api";
import { indexColumn } from "../sorters";
import type {
  AiCallEntry,
  AiCallsResponse,
  LogFile,
  LogSettings,
  LogTail,
  LogsResponse,
} from "../types";

const INTERVAL_OPTIONS = [2, 5, 10, 30].map((value) => ({
  value,
  label: `${value} 秒`,
}));
const LINE_OPTIONS = [200, 500, 1000, 2000].map((value) => ({
  value,
  label: `${value} 行`,
}));
const LEVEL_OPTIONS = [
  { value: "", label: "全部级别" },
  { value: "CRITICAL", label: "CRITICAL" },
  { value: "ERROR", label: "ERROR" },
  { value: "WARNING", label: "WARNING" },
  { value: "INFO", label: "INFO" },
  { value: "DEBUG", label: "DEBUG" },
];
const CALL_LIMIT_OPTIONS = [100, 200, 500, 1000].map((value) => ({
  value,
  label: `${value} 条`,
}));
const CALL_STATUS_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "ok", label: "成功" },
  { value: "error", label: "失败" },
  { value: "canceled", label: "中断" },
];

const PURPOSE_LABELS: Record<string, string> = {
  chat: "聊天",
  title: "会话标题",
  knowledge: "知识精简",
  labels: "列名翻译",
  delegate: "牛马委派",
};

const STATUS_TAG: Record<string, { color: string; label: string }> = {
  ok: { color: "green", label: "成功" },
  error: { color: "red", label: "失败" },
  canceled: { color: "orange", label: "中断" },
};

function formatSize(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function utcTime(value?: string): string {
  if (!value) return "—";
  return value.slice(0, 19).replace("T", " ");
}

function purposeLabel(value?: string): string {
  if (!value) return "—";
  return PURPOSE_LABELS[value] ?? value;
}

function RuntimeLogs() {
  const [files, setFiles] = useState<LogFile[]>([]);
  const [settings, setSettings] = useState<LogSettings | null>(null);
  const [logDir, setLogDir] = useState("");
  const [file, setFile] = useState("agent.log");
  const [lineCount, setLineCount] = useState(500);
  const [level, setLevel] = useState("");
  const [lines, setLines] = useState<string[]>([]);
  const [size, setSize] = useState(0);
  const [modified, setModified] = useState("");
  const [auto, setAuto] = useState(true);
  const [intervalSeconds, setIntervalSeconds] = useState(5);
  const [follow, setFollow] = useState(true);
  const [filter, setFilter] = useState("");
  const [retention, setRetention] = useState(14);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const preRef = useRef<HTMLPreElement | null>(null);

  const loadMeta = useCallback(async () => {
    try {
      const data = await api<LogsResponse>("/logs");
      setFiles(data.files);
      setSettings(data.settings);
      setLogDir(data.log_dir);
      setRetention(data.settings.retention_days);
      if (data.files.length && !data.files.some((item) => item.name === file)) {
        setFile(
          data.files.find((item) => item.active)?.name || data.files[0].name,
        );
      }
    } catch (exc) {
      message.error((exc as Error).message);
    }
  }, [file]);

  const loadTail = useCallback(
    async (name = file, count = lineCount, quiet = false) => {
      if (!name) return;
      if (!quiet) setLoading(true);
      try {
        const query = new URLSearchParams({
          name,
          lines: String(count),
        });
        if (level) query.set("level", level);
        const data = await api<LogTail>(`/logs/tail?${query.toString()}`);
        setLines(data.lines);
        setSize(data.size);
        setModified(data.modified);
      } catch (exc) {
        if (!quiet) message.error((exc as Error).message);
      } finally {
        if (!quiet) setLoading(false);
      }
    },
    [file, level, lineCount],
  );

  useEffect(() => {
    void loadMeta();
  }, [loadMeta]);

  useEffect(() => {
    void loadTail();
  }, [loadTail]);

  useEffect(() => {
    if (!auto) return undefined;
    const timer = window.setInterval(() => {
      if (document.hidden) return;
      void loadTail(file, lineCount, true);
    }, intervalSeconds * 1000);
    return () => window.clearInterval(timer);
  }, [auto, intervalSeconds, file, lineCount, loadTail]);

  useEffect(() => {
    if (follow && preRef.current) {
      preRef.current.scrollTop = preRef.current.scrollHeight;
    }
  }, [lines, follow]);

  const shown = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return lines;
    return lines.filter((line) => line.toLowerCase().includes(needle));
  }, [lines, filter]);

  const saveRetention = async () => {
    setSaving(true);
    try {
      await api<LogSettings & { pruned: number }>("/log-settings", {
        method: "PUT",
        body: JSON.stringify({ retention_days: retention }),
      });
      message.success(`已保存，保留最近 ${retention} 天的轮转日志`);
      await loadMeta();
    } catch (exc) {
      message.error((exc as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <p className="muted" style={{ marginTop: 0 }}>
        Agent 文件日志位于 <span className="mono">{logDir}</span>（宿主{" "}
        <span className="mono">infra/runtime/logs</span>），按 UTC 天切分并保留最近
        N 天；Docker stdout 仍可用{" "}
        <span className="mono">docker logs assistant-agent</span> 查看。
        Superset / MCP 日志仍在各自容器 stdout；原始审计事件见{" "}
        <span className="mono">infra/runtime/audit.jsonl</span>（90 天）。
      </p>
      <div className="log-toolbar">
        <Select
          showSearch
          value={file}
          onChange={setFile}
          options={files.map((item) => ({
            value: item.name,
            label: `${item.kind === "ai" ? "AI 调用 · " : ""}${item.name}${
              item.active ? "（当前）" : ""
            }`,
          }))}
          style={{ minWidth: 240 }}
          placeholder="选择日志文件"
        />
        <Select
          value={lineCount}
          onChange={setLineCount}
          options={LINE_OPTIONS}
          style={{ width: 100 }}
        />
        <Select
          value={level}
          onChange={setLevel}
          options={LEVEL_OPTIONS}
          style={{ width: 120 }}
          aria-label="日志级别"
        />
        <Input
          allowClear
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="过滤关键词"
          style={{ width: 220 }}
        />
        <Button loading={loading} onClick={() => void loadTail()}>
          刷新
        </Button>
        <Space size={6}>
          <Switch size="small" checked={follow} onChange={setFollow} />
          <span className="muted">跟随最新</span>
        </Space>
        {filter.trim() ? (
          <Tag>
            {shown.length} / {lines.length} 行
          </Tag>
        ) : null}
      </div>
      <div className="log-meta">
        <span className="mono">{file || "—"}</span>
        <span>{formatSize(size)}</span>
        <span>{modified ? dayjs(modified).format("YYYY-MM-DD HH:mm:ss") : "—"}</span>
        <span>时间 UTC</span>
      </div>
      <pre className="log-view" ref={preRef}>
        {shown.length
          ? shown.join("\n")
          : level || filter.trim()
            ? "（没有匹配的日志）"
            : "（暂无日志；Agent 产生日志后会自动出现）"}
      </pre>
      <div className="log-settings">
        <span>轮转日志保留</span>
        <InputNumber
          min={1}
          max={365}
          value={retention}
          onChange={(value) => setRetention(Number(value) || 1)}
          addonAfter="天"
          style={{ width: 130 }}
        />
        <Button type="primary" loading={saving} onClick={() => void saveRetention()}>
          保存
        </Button>
        {settings ? (
          <span className="muted">
            更新：{settings.updated_at ? dayjs(settings.updated_at).format("YYYY-MM-DD HH:mm") : "—"}
            {" · "}
            {settings.updated_by || "—"}
          </span>
        ) : null}
      </div>
    </div>
  );
}

function AiCalls() {
  const [items, setItems] = useState<AiCallEntry[]>([]);
  const [scanned, setScanned] = useState(0);
  const [truncated, setTruncated] = useState(false);
  const [limit, setLimit] = useState(200);
  const [username, setUsername] = useState("");
  const [model, setModel] = useState("");
  const [status, setStatus] = useState("");
  const [keyword, setKeyword] = useState("");
  const [auto, setAuto] = useState(true);
  const [intervalSeconds, setIntervalSeconds] = useState(5);
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState<AiCallEntry | null>(null);
  const filtersRef = useRef({ limit, username, model, status, keyword });
  filtersRef.current = { limit, username, model, status, keyword };

  const load = useCallback(
    async (
      next: {
        limit?: number;
        username?: string;
        model?: string;
        status?: string;
        keyword?: string;
      } = {},
      quiet = false,
    ) => {
      const current = { ...filtersRef.current, ...next };
      const params = new URLSearchParams({
        limit: String(current.limit),
      });
      const user = current.username.trim();
      const modelName = current.model.trim();
      const needle = current.keyword.trim();
      if (user) params.set("username", user);
      if (modelName) params.set("model", modelName);
      if (current.status) params.set("status", current.status);
      if (needle) params.set("q", needle);
      if (!quiet) setLoading(true);
      try {
        const data = await api<AiCallsResponse>(`/ai-calls?${params.toString()}`);
        setItems(data.items);
        setScanned(data.scanned);
        setTruncated(data.truncated);
      } catch (exc) {
        if (!quiet) message.error((exc as Error).message);
      } finally {
        if (!quiet) setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!auto) return undefined;
    const timer = window.setInterval(() => {
      if (document.hidden) return;
      void load({}, true);
    }, intervalSeconds * 1000);
    return () => window.clearInterval(timer);
  }, [auto, intervalSeconds, load]);

  const columns = [
    indexColumn<AiCallEntry>(0, 48),
    {
      title: "时间",
      key: "ts",
      width: 150,
      render: (_: unknown, row: AiCallEntry) => (
        <span className="mono" style={{ fontSize: 12 }}>
          {utcTime(row.ts)}
        </span>
      ),
    },
    { title: "用户", key: "user", dataIndex: "user", width: 100 },
    {
      title: "牛马",
      key: "employee",
      dataIndex: "employee",
      width: 100,
      render: (value?: string) => value || "—",
    },
    {
      title: "模型",
      key: "model",
      dataIndex: "model",
      ellipsis: true,
    },
    {
      title: "用途",
      key: "purpose",
      dataIndex: "purpose",
      width: 96,
      render: (value?: string) => purposeLabel(value),
    },
    {
      title: "耗时",
      key: "latency_ms",
      width: 84,
      align: "right" as const,
      render: (_: unknown, row: AiCallEntry) =>
        row.latency_ms == null ? "—" : `${(row.latency_ms / 1000).toFixed(1)}s`,
    },
    {
      title: "输入 / 输出",
      key: "tokens",
      width: 120,
      align: "right" as const,
      render: (_: unknown, row: AiCallEntry) =>
        `${Number(row.input_tokens || 0).toLocaleString("zh-CN")} / ${Number(
          row.output_tokens || 0,
        ).toLocaleString("zh-CN")}`,
    },
    {
      title: "工具",
      key: "tool_calls",
      width: 140,
      ellipsis: true,
      render: (_: unknown, row: AiCallEntry) =>
        row.tool_calls && row.tool_calls.length ? row.tool_calls.join(", ") : "—",
    },
    {
      title: "状态",
      key: "status",
      dataIndex: "status",
      width: 84,
      render: (value?: string) => {
        const tag = STATUS_TAG[value || ""] || {
          color: "default",
          label: value || "—",
        };
        return <Tag color={tag.color}>{tag.label}</Tag>;
      },
    },
  ];

  return (
    <div>
      <p className="muted" style={{ marginTop: 0 }}>
        每次模型调用一行（聊天、会话标题、知识精简、列名翻译、牛马委派），记录模型、耗时、
        Token、工具与状态；原始文件为{" "}
        <span className="mono">infra/runtime/logs/ai-calls.log</span>（按 UTC 天切分、与运行
        日志同一保留天数），可在「运行日志」页直接看文本。
      </p>
      <div className="log-toolbar">
        <Select
          value={limit}
          onChange={(value) => {
            setLimit(value);
            void load({ limit: value });
          }}
          options={CALL_LIMIT_OPTIONS}
          style={{ width: 100 }}
        />
        <Input
          allowClear
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          onPressEnter={() => void load({ username })}
          placeholder="用户"
          style={{ width: 130 }}
        />
        <Input
          allowClear
          value={model}
          onChange={(event) => setModel(event.target.value)}
          onPressEnter={() => void load({ model })}
          placeholder="模型"
          style={{ width: 180 }}
        />
        <Select
          value={status}
          onChange={(value) => {
            setStatus(value);
            void load({ status: value });
          }}
          options={CALL_STATUS_OPTIONS}
          style={{ width: 120 }}
        />
        <Input
          allowClear
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          onPressEnter={() => void load({ keyword })}
          placeholder="关键词（错误、模型、会话…）"
          style={{ width: 220 }}
        />
        <Button loading={loading} onClick={() => void load()}>
          刷新
        </Button>
        <Space size={6}>
          <span className="muted">自动刷新</span>
          <Switch size="small" checked={auto} onChange={setAuto} />
          <Select
            size="small"
            value={intervalSeconds}
            onChange={setIntervalSeconds}
            options={INTERVAL_OPTIONS}
            style={{ width: 86 }}
            disabled={!auto}
          />
        </Space>
      </div>
      <div className="log-meta">
        <span>{items.length} 条</span>
        <span>扫描 {scanned.toLocaleString("zh-CN")} 行</span>
        {truncated ? <Tag color="blue">已达上限，可缩小筛选</Tag> : null}
        <span>时间 UTC</span>
      </div>
      <Table<AiCallEntry>
        size="small"
        rowKey={(row, index) => `${row.ts || ""}-${index}`}
        columns={columns}
        dataSource={items}
        pagination={false}
        loading={loading}
        scroll={{ y: "calc(100vh - 520px)" }}
        locale={{ emptyText: "暂无 AI 调用记录；产生一次模型请求后会自动出现" }}
        onRow={(row) => ({
          onClick: () => setDetail(row),
          style: { cursor: "pointer" },
        })}
      />
      <Drawer
        open={Boolean(detail)}
        width={720}
        title="AI 调用详情"
        onClose={() => setDetail(null)}
      >
        {detail ? (
          <>
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="时间（UTC）">
                {utcTime(detail.ts)}
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                {STATUS_TAG[detail.status || ""]?.label || detail.status || "—"}
              </Descriptions.Item>
              <Descriptions.Item label="模型">{detail.model || "—"}</Descriptions.Item>
              <Descriptions.Item label="用途">
                {purposeLabel(detail.purpose)}
              </Descriptions.Item>
              <Descriptions.Item label="用户">{detail.user || "—"}</Descriptions.Item>
              <Descriptions.Item label="牛马">
                {detail.employee || "—"}
              </Descriptions.Item>
              <Descriptions.Item label="会话">
                <span className="mono">{detail.conversation_id || "—"}</span>
              </Descriptions.Item>
              <Descriptions.Item label="轮次">
                <span className="mono">{detail.run_id || "—"}</span>
              </Descriptions.Item>
              <Descriptions.Item label="流式">
                {detail.stream ? "是" : "否"}
              </Descriptions.Item>
              <Descriptions.Item label="消息数 / 工具定义">
                {detail.messages ?? "—"} / {detail.tools ?? "—"}
              </Descriptions.Item>
              <Descriptions.Item label="耗时">
                {detail.latency_ms == null ? "—" : `${detail.latency_ms} ms`}
                {detail.ttft_ms != null ? `（首块 ${detail.ttft_ms} ms）` : ""}
              </Descriptions.Item>
              <Descriptions.Item label="Tokens">
                输入 {Number(detail.input_tokens || 0).toLocaleString("zh-CN")} ·
                输出 {Number(detail.output_tokens || 0).toLocaleString("zh-CN")}
                {detail.cache_read_tokens
                  ? ` · 缓存命中 ${detail.cache_read_tokens}`
                  : ""}
              </Descriptions.Item>
              <Descriptions.Item label="本轮工具调用">
                {detail.tool_calls && detail.tool_calls.length
                  ? detail.tool_calls.join(", ")
                  : "—"}
              </Descriptions.Item>
              <Descriptions.Item label="结束原因">
                {detail.finish_reason || "—"}
                {detail.state ? `（${detail.state}）` : ""}
              </Descriptions.Item>
              {detail.error ? (
                <Descriptions.Item label="错误">
                  <span style={{ color: "var(--adm-danger)" }}>{detail.error}</span>
                </Descriptions.Item>
              ) : null}
            </Descriptions>
            <pre className="log-detail-json">{JSON.stringify(detail, null, 2)}</pre>
          </>
        ) : null}
      </Drawer>
    </div>
  );
}

export default function LogsPage() {
  return (
    <Card size="small" title="运行日志">
      <RuntimeLogs />
    </Card>
  );
}

export function AiCallsPage() {
  return (
    <Card size="small" title="AI 调用">
      <AiCalls />
    </Card>
  );
}

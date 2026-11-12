import { useEffect, useState } from "react";
import { Button, Card, Drawer, Switch, Table, Tag, message } from "antd";
import dayjs from "dayjs";
import { api } from "../api";
import type { AdminKnowledge, DirectoryUser } from "../types";

function time(value: string | null | undefined): string {
  return value ? dayjs(value).format("YYYY-MM-DD HH:mm") : "—";
}

export default function UsersPage() {
  const [users, setUsers] = useState<DirectoryUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [active, setActive] = useState<DirectoryUser | null>(null);
  const [knowledge, setKnowledge] = useState<AdminKnowledge[]>([]);
  const [knowledgeLoading, setKnowledgeLoading] = useState(false);
  const [savingUser, setSavingUser] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const data = await api<{ users: DirectoryUser[] }>("/superset-directory");
      setUsers(data.users);
    } catch (exc) {
      message.error((exc as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const openKnowledge = async (record: DirectoryUser) => {
    setActive(record);
    setKnowledge([]);
    setKnowledgeLoading(true);
    try {
      const data = await api<{ items: AdminKnowledge[] }>(
        `/knowledge?username=${encodeURIComponent(record.username)}&page_size=100&sort_by=updated_at&sort_order=desc`,
      );
      setKnowledge(data.items);
    } catch (exc) {
      message.error((exc as Error).message);
    } finally {
      setKnowledgeLoading(false);
    }
  };

  const toggleAi = async (record: DirectoryUser, enabled: boolean) => {
    setSavingUser(record.username);
    try {
      const body = await api<{ ai_enabled: boolean }>(
        `/users/${encodeURIComponent(record.username)}/ai-access`,
        { method: "PUT", body: JSON.stringify({ enabled }) },
      );
      setUsers((current) =>
        current.map((item) =>
          item.username === record.username
            ? { ...item, ai_enabled: body.ai_enabled }
            : item,
        ),
      );
      message.success(
        `${record.username} 的 AI 助手已${body.ai_enabled ? "启用" : "关闭"}`,
      );
    } catch (exc) {
      message.error((exc as Error).message);
    } finally {
      setSavingUser(null);
    }
  };

  const columns = [
    {
      key: "index",
      title: "#",
      width: 56,
      render: (_: unknown, __: DirectoryUser, index: number) => index + 1,
    },
    {
      key: "username",
      title: "用户名",
      dataIndex: "username",
      width: 150,
      render: (value: string, record: DirectoryUser) => (
        <span>
          {value}
          {!record.active ? (
            <Tag style={{ marginLeft: 6 }}>停用</Tag>
          ) : null}
        </span>
      ),
    },
    {
      key: "ai_enabled",
      title: "AI 助手",
      width: 110,
      render: (_: unknown, record: DirectoryUser) => (
        <span title="关闭后该用户的助手入口隐藏，且 AI 接口返回 403">
          <Switch
            size="small"
            checked={record.ai_enabled !== false}
            loading={savingUser === record.username}
            onChange={(checked) => void toggleAi(record, checked)}
          />
          {record.ai_enabled === false ? (
            <Tag color="red" style={{ marginLeft: 6 }}>
              已关闭
            </Tag>
          ) : null}
        </span>
      ),
    },
    {
      key: "roles",
      title: "角色",
      dataIndex: "roles",
      render: (roles: string[]) =>
        roles.length ? (
          roles.map((role) => <Tag key={role}>{role}</Tag>)
        ) : (
          <span className="muted">—</span>
        ),
    },
    {
      key: "groups",
      title: "分组",
      dataIndex: "groups",
      render: (groups: string[]) =>
        groups.length ? (
          groups.map((group) => <Tag color="blue" key={group}>{group}</Tag>)
        ) : (
          <span className="muted">—</span>
        ),
    },
    {
      key: "knowledge",
      title: "用户知识库",
      width: 230,
      render: (_: unknown, record: DirectoryUser) => (
        <span>
          <span className="muted">
            生效 {record.knowledge_active} · 回收站 {record.knowledge_trash}
          </span>
          <Button
            size="small"
            style={{ marginLeft: 8 }}
            onClick={() => void openKnowledge(record)}
          >
            查看
          </Button>
        </span>
      ),
    },
  ];

  return (
    <Card size="small" title="用户" extra={<Button size="small" onClick={() => void load()}>刷新</Button>}>
      <Table<DirectoryUser>
        rowKey="username"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={users}
        pagination={false}
      />
      <Drawer
        width={560}
        open={Boolean(active)}
        onClose={() => setActive(null)}
        title={active ? `${active.username} 的知识库` : "知识库"}
      >
        {knowledgeLoading ? (
          <div className="muted">加载中…</div>
        ) : knowledge.length === 0 ? (
          <div className="muted">该用户没有生效中的知识条目。</div>
        ) : (
          knowledge.map((item) => (
            <Card key={item.id} size="small" style={{ marginBottom: 10 }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <strong>{item.title}</strong>
                <Tag>{item.source === "manual" ? "手动" : "AI 记录"}</Tag>
                <span className="muted">{time(item.updated_at)}</span>
              </div>
              <pre className="json" style={{ whiteSpace: "pre-wrap", marginTop: 8 }}>
                {item.content}
              </pre>
            </Card>
          ))
        )}
      </Drawer>
    </Card>
  );
}

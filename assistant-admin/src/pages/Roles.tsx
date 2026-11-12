import { useEffect, useState } from "react";
import { Card, Checkbox, Table, Tag, message } from "antd";
import { api } from "../api";
import type { DirectoryRole, RoleEmployee, RoleUser } from "../types";

export default function RolesPage() {
  const [roles, setRoles] = useState<DirectoryRole[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [employees, setEmployees] = useState<RoleEmployee[]>([]);
  const [users, setUsers] = useState<RoleUser[]>([]);
  const [loading, setLoading] = useState(false);
  const [savingId, setSavingId] = useState<number | null>(null);

  useEffect(() => {
    api<{ items: DirectoryRole[] }>("/roles")
      .then((data) => {
        setRoles(data.items);
        if (data.items.length > 0) setSelected(data.items[0].name);
      })
      .catch((exc) => message.error((exc as Error).message));
  }, []);

  useEffect(() => {
    if (!selected) return;
    setLoading(true);
    api<{
      items: RoleEmployee[];
      users: RoleUser[];
    }>(`/roles/${encodeURIComponent(selected)}/employees`)
      .then((data) => {
        setEmployees(data.items);
        setUsers(data.users ?? []);
      })
      .catch((exc) => message.error((exc as Error).message))
      .finally(() => setLoading(false));
  }, [selected]);

  const toggle = async (employee: RoleEmployee, checked: boolean) => {
    const next = employees.map((item) =>
      item.id === employee.id ? { ...item, available: checked } : item,
    );
    setEmployees(next);
    setSavingId(employee.id);
    try {
      await api(`/roles/${encodeURIComponent(selected)}/employees`, {
        method: "PUT",
        body: JSON.stringify({
          employee_ids: next.filter((item) => item.available).map((item) => item.id),
        }),
      });
      message.success(
        `${employee.nickname || employee.username} 已${checked ? "对" : "不再对"}该角色可用`,
      );
    } catch (exc) {
      setEmployees(employees);
      message.error((exc as Error).message);
    } finally {
      setSavingId(null);
    }
  };

  const roleColumns = [
    {
      key: "name",
      title: "角色",
      dataIndex: "name",
      render: (value: string) => <strong>{value}</strong>,
    },
    { key: "user_count", title: "用户数", dataIndex: "user_count", width: 80 },
    { key: "group_count", title: "分组数", dataIndex: "group_count", width: 80 },
  ];

  const employeeColumns = [
    {
      key: "avatar",
      title: "头像",
      dataIndex: "avatar",
      width: 56,
      render: (value: string) => <span className="employee-avatar">{value || "🤖"}</span>,
    },
    { key: "nickname", title: "昵称", dataIndex: "nickname", width: 120 },
    { key: "title", title: "职位", dataIndex: "title", ellipsis: true },
    {
      key: "enabled",
      title: "启用",
      dataIndex: "enabled",
      width: 80,
      render: (value: boolean) => (value ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>),
    },
    {
      key: "available",
      title: "可用",
      dataIndex: "available",
      width: 90,
      render: (value: boolean, record: RoleEmployee) => (
        <Checkbox
          checked={value}
          disabled={savingId === record.id}
          onChange={(event) => void toggle(record, event.target.checked)}
        />
      ),
    },
  ];

  const userColumns = [
    {
      key: "index",
      title: "#",
      width: 52,
      render: (_: unknown, __: RoleUser, index: number) => index + 1,
    },
    { key: "username", title: "用户名", dataIndex: "username", width: 140 },
    {
      key: "name",
      title: "姓名",
      render: (_: unknown, record: RoleUser) =>
        [record.first_name, record.last_name].filter(Boolean).join(" ") || "—",
    },
    { key: "email", title: "邮箱", dataIndex: "email", ellipsis: true },
    {
      key: "active",
      title: "状态",
      width: 80,
      render: (_: unknown, record: RoleUser) =>
        record.active ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>,
    },
  ];

  return (
    <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
      <Card size="small" title="角色和权限" style={{ width: 340, flex: "0 0 auto" }}>
        <Table<DirectoryRole>
          rowKey="name"
          size="small"
          columns={roleColumns}
          dataSource={roles}
          pagination={false}
          rowClassName={(record) =>
            record.name === selected ? "ant-table-row-selected" : ""
          }
          onRow={(record) => ({
            onClick: () => setSelected(record.name),
            style: { cursor: "pointer" },
          })}
        />
        <div className="muted" style={{ marginTop: 10, fontSize: 13 }}>
          角色来自 Superset（ab_role）。勾选右侧“可用”表示该角色可以使用对应 AI 牛马；
          “全员”员工首次取消某角色时，会自动改为按角色授权。
        </div>
      </Card>
      <Card
        size="small"
        title={selected ? `「${selected}」可用的 AI 牛马` : "可用的 AI 牛马"}
        style={{ flex: 1, minWidth: 0 }}
      >
        <Table<RoleEmployee>
          rowKey="id"
          size="small"
          loading={loading}
          columns={employeeColumns}
          dataSource={employees}
          pagination={false}
        />
        <div className="muted" style={{ margin: "14px 0 6px", fontWeight: 600 }}>
          该角色下的用户（{users.length}）
        </div>
        <Table<RoleUser>
          rowKey="username"
          size="small"
          loading={loading}
          columns={userColumns}
          dataSource={users}
          pagination={false}
          locale={{ emptyText: "该角色下没有直属用户" }}
        />
      </Card>
    </div>
  );
}

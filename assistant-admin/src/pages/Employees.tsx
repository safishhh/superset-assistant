import { useEffect, useMemo, useState } from "react";
import {
  Button,
  Card,
  Checkbox,
  Form,
  Input,
  Popconfirm,
  Radio,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  message,
} from "antd";
import dayjs from "dayjs";
import { api } from "../api";
import { indexColumn } from "../sorters";
import type {
  AdminEmployee,
  McpTool,
  Model,
  SupersetUser,
} from "../types";

type SkillOption = { id: number; name: string; title: string; enabled: boolean };
type EmployeeKnowledge = {
  id: number;
  title: string;
  content: string;
  updated_at: string;
};

const EMPTY_FORM = {
  username: "",
  nickname: "",
  title: "",
  avatar: "",
  intro: "",
  greeting: "",
  persona: "",
  model_id: undefined as number | undefined,
  model_ids: [] as number[],
  can_delegate: false,
  delegate_employee_ids: [] as number[],
  skill_ids: [] as number[],
  enabled: true,
};

export default function EmployeesPage() {
  const [form] = Form.useForm();
  const watchedModelIds = Form.useWatch("model_ids", form) as
    | number[]
    | undefined;
  const canDelegate = Form.useWatch("can_delegate", form) as
    | boolean
    | undefined;
  const [items, setItems] = useState<AdminEmployee[]>([]);
  const [loading, setLoading] = useState(true);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editing, setEditing] = useState<AdminEmployee | null>(null);
  const [saving, setSaving] = useState(false);
  const [models, setModels] = useState<Model[]>([]);
  const [skills, setSkills] = useState<SkillOption[]>([]);
  const [tools, setTools] = useState<McpTool[]>([]);
  const [unlimitedTools, setUnlimitedTools] = useState(true);
  const [selectedTools, setSelectedTools] = useState<string[]>([]);
  const [userScope, setUserScope] = useState<"all" | "admin" | "custom">("all");
  const [selectedUsers, setSelectedUsers] = useState<string[]>([]);
  const [supersetUsers, setSupersetUsers] = useState<SupersetUser[]>([]);
  const [knowledge, setKnowledge] = useState<EmployeeKnowledge[]>([]);
  const [knowledgeTitle, setKnowledgeTitle] = useState("");
  const [knowledgeContent, setKnowledgeContent] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const data = await api<{ items: AdminEmployee[] }>("/employees");
      setItems(data.items);
    } catch (exc) {
      message.error((exc as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    api<Model[]>("/models").then(setModels).catch(() => undefined);
    api<{ items: SkillOption[] }>("/skills")
      .then((data) => setSkills(data.items))
      .catch(() => undefined);
    api<{ items: McpTool[] }>("/mcp-tools")
      .then((data) => setTools(data.items))
      .catch(() => undefined);
    api<{ items: SupersetUser[] }>("/superset-users")
      .then((data) => setSupersetUsers(data.items))
      .catch(() => undefined);
  }, []);

  const scopeOf = (employee: AdminEmployee) =>
    employee.users === null
      ? "全员"
      : employee.users.length === 0
        ? "仅管理员"
        : `${employee.users.length} 人`;

  const grouped = useMemo(() => {
    const map = new Map<string, McpTool[]>();
    tools.forEach((tool) => {
      const list = map.get(tool.category) ?? [];
      list.push(tool);
      map.set(tool.category, list);
    });
    return [...map.entries()];
  }, [tools]);

  const toolCounts = useMemo(
    () => ({
      mcp: tools.filter((tool) => tool.source === "mcp").length,
      agent: tools.filter((tool) => tool.source === "agent").length,
    }),
    [tools],
  );

  const availableModelOptions = useMemo(() => {
    const allowed = new Set(watchedModelIds ?? []);
    return models.filter((model) => allowed.size === 0 || allowed.has(model.id));
  }, [models, watchedModelIds]);

  const delegateOptions = useMemo(
    () =>
      items
        .filter((item) => item.enabled && item.id !== editing?.id)
        .map((item) => ({
          value: item.id,
          label: `${item.nickname}${item.title ? ` @${item.title}` : ""}（${item.username}）`,
        })),
    [editing, items],
  );

  useEffect(() => {
    const selected = form.getFieldValue("model_id");
    if (
      selected &&
      (watchedModelIds?.length ?? 0) > 0 &&
      !(watchedModelIds ?? []).includes(selected)
    ) {
      form.setFieldValue("model_id", undefined);
    }
  }, [form, watchedModelIds]);

  const loadKnowledge = async (employeeId: number) => {
    try {
      const data = await api<{ items: EmployeeKnowledge[] }>(
        `/employees/${employeeId}/knowledge`,
      );
      setKnowledge(data.items);
    } catch (exc) {
      message.error((exc as Error).message);
    }
  };

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue(EMPTY_FORM);
    setUnlimitedTools(true);
    setSelectedTools([]);
    setUserScope("all");
    setSelectedUsers([]);
    setKnowledge([]);
    setDrawerOpen(true);
  };

  const openEdit = (employee: AdminEmployee) => {
    setEditing(employee);
    form.setFieldsValue({
      username: employee.username,
      nickname: employee.nickname,
      title: employee.title,
      avatar: employee.avatar,
      intro: employee.intro,
      greeting: employee.greeting,
      persona: employee.persona,
      model_id: employee.model_id ?? undefined,
      model_ids: employee.model_ids ?? [],
      can_delegate: employee.can_delegate ?? false,
      delegate_employee_ids: employee.delegate_employee_ids ?? [],
      skill_ids: employee.skill_ids,
      enabled: employee.enabled,
    });
    setUnlimitedTools(employee.tools === null);
    setSelectedTools(employee.tools ?? []);
    setUserScope(
      employee.users === null ? "all" : employee.users.length === 0 ? "admin" : "custom",
    );
    setSelectedUsers(employee.users ?? []);
    setDrawerOpen(true);
    void loadKnowledge(employee.id);
  };

  const save = async () => {
    setSaving(true);
    try {
      const values = await form.validateFields();
      const payload = {
        ...values,
        model_id: values.model_id ?? null,
        model_ids: values.model_ids?.length ? values.model_ids : null,
        can_delegate: Boolean(values.can_delegate),
        delegate_employee_ids:
          values.can_delegate && values.delegate_employee_ids?.length
            ? values.delegate_employee_ids
            : null,
        tools: unlimitedTools ? null : selectedTools,
        users:
          userScope === "all"
            ? null
            : userScope === "admin"
              ? []
              : selectedUsers,
      };
      if (editing) {
        await api(`/employees/${editing.id}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        message.success("AI 牛马已更新");
      } else {
        await api("/employees", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        message.success("AI 牛马已创建");
      }
      setDrawerOpen(false);
      await load();
    } catch (exc) {
      message.error((exc as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const toggleEnabled = async (employee: AdminEmployee, enabled: boolean) => {
    try {
      await api(`/employees/${employee.id}`, {
        method: "PUT",
        body: JSON.stringify({ enabled }),
      });
      await load();
    } catch (exc) {
      message.error((exc as Error).message);
    }
  };

  const remove = async (employee: AdminEmployee) => {
    try {
      await api(`/employees/${employee.id}`, { method: "DELETE" });
      message.success("已删除");
      setDrawerOpen(false);
      await load();
    } catch (exc) {
      message.error((exc as Error).message);
    }
  };

  const addKnowledge = async () => {
    if (!editing) return;
    if (!knowledgeTitle.trim() || !knowledgeContent.trim()) {
      message.warning("标题和内容都要填");
      return;
    }
    try {
      await api(`/employees/${editing.id}/knowledge`, {
        method: "POST",
        body: JSON.stringify({
          title: knowledgeTitle.trim(),
          content: knowledgeContent.trim(),
        }),
      });
      setKnowledgeTitle("");
      setKnowledgeContent("");
      await loadKnowledge(editing.id);
      message.success("知识已保存");
    } catch (exc) {
      message.error((exc as Error).message);
    }
  };

  const removeKnowledge = async (knowledgeId: number) => {
    if (!editing) return;
    try {
      await api(`/employees/${editing.id}/knowledge/${knowledgeId}`, {
        method: "DELETE",
      });
      await loadKnowledge(editing.id);
    } catch (exc) {
      message.error((exc as Error).message);
    }
  };

  const columns = [
    indexColumn<AdminEmployee>(0),
    {
      key: "avatar",
      title: "头像",
      dataIndex: "avatar",
      width: 64,
      render: (value: string) => (
        <span className="employee-avatar">{value || "🤖"}</span>
      ),
    },
    { key: "username", title: "用户名", dataIndex: "username", width: 120 },
    { key: "nickname", title: "昵称", dataIndex: "nickname", width: 120 },
    { key: "title", title: "职位", dataIndex: "title", ellipsis: true },
    {
      key: "can_delegate",
      title: "协调",
      dataIndex: "can_delegate",
      width: 80,
      render: (value: boolean) =>
        value ? <Tag color="purple">领导</Tag> : null,
    },
    {
      key: "users",
      title: "可用范围",
      width: 110,
      render: (_: unknown, record: AdminEmployee) => (
        <Tag
          color={
            record.users === null
              ? "blue"
              : record.users.length === 0
                ? "orange"
                : "green"
          }
        >
          {scopeOf(record)}
        </Tag>
      ),
    },
    {
      key: "models",
      title: "模型",
      width: 190,
      render: (_: unknown, record: AdminEmployee) => {
        const defaultModel = models.find((model) => model.id === record.model_id);
        return (
          <span className="muted">
            {record.model_ids?.length
              ? `可用 ${record.model_ids.length} 个`
              : "全部启用模型"}
            <br />
            默认：{defaultModel?.display_name || "系统默认"}
          </span>
        );
      },
    },
    {
      key: "enabled",
      title: "启用",
      dataIndex: "enabled",
      width: 80,
      render: (value: boolean, record: AdminEmployee) => (
        <Switch
          size="small"
          checked={value}
          onChange={(checked) => void toggleEnabled(record, checked)}
        />
      ),
    },
    {
      key: "action",
      title: "操作",
      width: 90,
      render: (_: unknown, record: AdminEmployee) => (
        <Button size="small" onClick={() => openEdit(record)}>
          编辑
        </Button>
      ),
    },
  ];

  return (
    <Card
      size="small"
      title="AI 牛马"
      extra={
        <Button type="primary" size="small" onClick={openCreate}>
          新建 AI 牛马
        </Button>
      }
    >
      <p className="muted" style={{ marginTop: 0 }}>
        每个 AI 牛马拥有独立的人物设定、模型、技能、工具白名单与知识库；
        小助手顶部选中后按其人设对话，未勾选的工具无法调用。
      </p>
      <Table
        size="small"
        rowKey="id"
        loading={loading}
        dataSource={items}
        pagination={items.length > 20 ? { pageSize: 20 } : false}
        columns={columns}
      />

      {drawerOpen ? (
        <div className="side-drawer-mask" onClick={() => setDrawerOpen(false)}>
          <div
            className="side-drawer"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="side-drawer-head">
              <strong>{editing ? `编辑 AI 员工 · ${editing.nickname}` : "新建 AI 员工"}</strong>
              <span className="side-drawer-spacer" />
              <Button size="small" onClick={() => setDrawerOpen(false)}>
                关闭
              </Button>
            </div>
            <div className="side-drawer-body">
              <Form form={form} layout="vertical" initialValues={EMPTY_FORM}>
                <Tabs
                  size="small"
                  items={[
                    {
                      key: "profile",
                      label: "员工资料",
                      children: (
                        <>
                          <Form.Item
                            name="username"
                            label="用户名"
                            rules={[
                              { required: true, message: "必填" },
                              {
                                pattern: /^[a-z0-9_]{1,64}$/,
                                message: "仅小写字母/数字/下划线",
                              },
                            ]}
                          >
                            <Input disabled={Boolean(editing)} placeholder="atlas" />
                          </Form.Item>
                          <Form.Item
                            name="nickname"
                            label="昵称"
                            rules={[{ required: true, message: "必填" }]}
                          >
                            <Input placeholder="Atlas" maxLength={64} />
                          </Form.Item>
                          <Form.Item
                            name="title"
                            label="职位"
                            extra="AI 员工职责的简短描述"
                          >
                            <Input placeholder="团队领导" maxLength={128} />
                          </Form.Item>
                          <Form.Item name="avatar" label="头像（emoji 或图片 URL）">
                            <Input placeholder="🧑‍✈️" maxLength={256} />
                          </Form.Item>
                          <Form.Item name="intro" label="简介">
                            <Input.TextArea rows={2} maxLength={2000} />
                          </Form.Item>
                          <Form.Item name="greeting" label="问候语">
                            <Input.TextArea rows={2} maxLength={2000} />
                          </Form.Item>
                          <Form.Item
                            name="enabled"
                            label="启用"
                            valuePropName="checked"
                          >
                            <Switch />
                          </Form.Item>
                          <Form.Item
                            label="可见用户"
                            extra="管理员始终可见可用；取消授权后，用户端会自动回到首个可用 AI 牛马"
                          >
                            <Radio.Group
                              size="small"
                              optionType="button"
                              value={userScope}
                              onChange={(event) =>
                                setUserScope(
                                  event.target.value as "all" | "admin" | "custom",
                                )
                              }
                              options={[
                                { label: "全员", value: "all" },
                                { label: "仅管理员", value: "admin" },
                                { label: "指定用户", value: "custom" },
                              ]}
                            />
                          </Form.Item>
                          {userScope === "custom" ? (
                            <div className="user-picker">
                              {supersetUsers.length === 0 ? (
                                <div className="muted">
                                  没有可选用户（Superset 用户列表未取到）
                                </div>
                              ) : (
                                <Checkbox.Group
                                  value={selectedUsers}
                                  onChange={(values) =>
                                    setSelectedUsers(values as string[])
                                  }
                                >
                                  <Space direction="vertical" size={2}>
                                    {supersetUsers.map((user) => (
                                      <Checkbox
                                        key={user.username}
                                        value={user.username}
                                      >
                                        <span className="mono">{user.username}</span>
                                        {user.display_name ? (
                                          <span className="muted">
                                            {" "}
                                            · {user.display_name}
                                          </span>
                                        ) : null}
                                        {user.active ? null : (
                                          <Tag style={{ marginLeft: 6 }}>停用</Tag>
                                        )}
                                      </Checkbox>
                                    ))}
                                  </Space>
                                </Checkbox.Group>
                              )}
                            </div>
                          ) : null}
                        </>
                      ),
                    },
                    {
                      key: "persona",
                      label: "人物设定",
                      children: (
                        <Form.Item
                          name="persona"
                          extra="叠加在系统提示之上；权限与安全规则优先级更高"
                        >
                          <Input.TextArea rows={12} maxLength={8000} />
                        </Form.Item>
                      ),
                    },
                    {
                      key: "model",
                      label: "模型设置",
                      children: (
                        <>
                          <Form.Item
                            name="model_ids"
                            label="可用模型"
                            extra="支持多选；留空表示全部启用模型"
                          >
                            <Select
                              mode="multiple"
                              allowClear
                              placeholder="全部启用模型"
                              options={models.map((model) => ({
                                value: model.id,
                                label: `${model.display_name || model.model_name}${
                                  model.is_default ? "（系统默认）" : ""
                                }`,
                              }))}
                            />
                          </Form.Item>
                          <Form.Item
                            name="model_id"
                            label="默认模型"
                            extra="留空表示跟随系统默认；若系统默认不在可用模型内，则使用第一个可用模型"
                          >
                            <Select
                              allowClear
                              placeholder="跟随系统默认"
                              options={availableModelOptions.map((model) => ({
                                value: model.id,
                                label: `${model.display_name || model.model_name}${
                                  model.is_default ? "（系统默认）" : ""
                                }`,
                              }))}
                            />
                          </Form.Item>
                        </>
                      ),
                    },
                    {
                      key: "delegate",
                      label: "协调",
                      children: (
                        <>
                          <Form.Item
                            name="can_delegate"
                            label="可协调其他 AI 牛马"
                            valuePropName="checked"
                            extra="开启后，该员工可在对话中把子任务交给其他牛马；默认可以使用全部可用牛马"
                          >
                            <Switch />
                          </Form.Item>
                          {canDelegate ? (
                            <Form.Item
                              name="delegate_employee_ids"
                              label="可调用的牛马"
                              extra="留空表示全部可用牛马；实际调用时仍受用户权限和员工启用状态限制"
                            >
                              <Select
                                mode="multiple"
                                allowClear
                                placeholder="全部可用牛马"
                                options={delegateOptions}
                              />
                            </Form.Item>
                          ) : null}
                        </>
                      ),
                    },
                    {
                      key: "skills",
                      label: "技能",
                      children: (
                        <Form.Item name="skill_ids" extra="只注册勾选的技能工具">
                          <Checkbox.Group style={{ display: "block" }}>
                            {skills.length === 0 ? (
                              <span className="muted">还没有技能，可到「技能」页创建</span>
                            ) : (
                              skills.map((skill) => (
                                <div key={skill.id} style={{ marginBottom: 6 }}>
                                  <Checkbox value={skill.id}>
                                    {skill.title || skill.name}
                                    <span className="muted"> · {skill.name}</span>
                                    {skill.enabled ? null : (
                                      <Tag style={{ marginLeft: 6 }}>已停用</Tag>
                                    )}
                                  </Checkbox>
                                </div>
                              ))
                            )}
                          </Checkbox.Group>
                        </Form.Item>
                      ),
                    },
                    {
                      key: "tools",
                      label: "工具",
                      children: (
                        <>
                          <div className="muted" style={{ marginBottom: 6 }}>
                            共 {tools.length} 个：Superset MCP {toolCounts.mcp} 个 ·
                            助手内置 {toolCounts.agent} 个
                          </div>
                          <div
                            className="muted"
                            style={{ fontSize: 12, marginBottom: 6 }}
                          >
                            与 MCP 同名的内置工具只列一次；写操作需同时勾选「生成写操作方案」与具体写工具，mcp_call 需同时勾选目标工具。
                          </div>
                          <Space style={{ marginBottom: 10 }}>
                            <Switch
                              size="small"
                              checked={unlimitedTools}
                              onChange={setUnlimitedTools}
                            />
                            <span className="muted">
                              不限制（允许全部 Superset MCP 与助手内置工具）
                            </span>
                          </Space>
                          {unlimitedTools ? null : (
                            <Checkbox.Group
                              value={selectedTools}
                              onChange={(values) =>
                                setSelectedTools(values as string[])
                              }
                            >
                              <div className="tool-groups">
                                {grouped.map(([category, list]) => (
                                  <div key={category} className="tool-group">
                                    <div className="tool-group-head">
                                      <strong>{category}</strong>
                                      <span className="muted">{list.length} 个</span>
                                    </div>
                                    <Space direction="vertical" size={2}>
                                      {list.map((tool) => {
                                        const aliasHit = tool.aliases.find((alias) =>
                                          selectedTools.includes(alias),
                                        );
                                        return (
                                          <Checkbox
                                            key={tool.name}
                                            value={tool.name}
                                            title={tool.description}
                                          >
                                            <span>{tool.title || tool.name}</span>
                                            <span
                                              className="mono muted"
                                              style={{ marginLeft: 6, fontSize: 12 }}
                                            >
                                              {tool.name}
                                            </span>
                                            {tool.destructive ? (
                                              <Tag
                                                color="red"
                                                style={{ marginLeft: 6 }}
                                              >
                                                破坏性
                                              </Tag>
                                            ) : tool.read_only ? null : (
                                              <Tag style={{ marginLeft: 6 }}>写入</Tag>
                                            )}
                                            {!selectedTools.includes(tool.name) &&
                                            aliasHit ? (
                                              <Tag style={{ marginLeft: 6 }}>
                                                随 {aliasHit} 授权
                                              </Tag>
                                            ) : null}
                                          </Checkbox>
                                        );
                                      })}
                                    </Space>
                                  </div>
                                ))}
                              </div>
                            </Checkbox.Group>
                          )}
                        </>
                      ),
                    },
                    {
                      key: "knowledge",
                      label: "知识库",
                      children: editing ? (
                        <>
                          {knowledge.length === 0 ? (
                            <div className="muted" style={{ marginBottom: 8 }}>
                              还没有知识条目
                            </div>
                          ) : (
                            knowledge.map((item) => (
                              <div key={item.id} className="knowledge-row">
                                <div>
                                  <strong>{item.title}</strong>
                                  <div className="muted" style={{ fontSize: 12 }}>
                                    {dayjs(item.updated_at).format("YYYY-MM-DD HH:mm")}
                                  </div>
                                  <div className="content-box" style={{ marginTop: 4 }}>
                                    {item.content}
                                  </div>
                                </div>
                                <Popconfirm
                                  title="删除该知识条目？"
                                  onConfirm={() => void removeKnowledge(item.id)}
                                >
                                  <Button size="small" type="text" danger>
                                    删除
                                  </Button>
                                </Popconfirm>
                              </div>
                            ))
                          )}
                          <Input
                            placeholder="标题"
                            value={knowledgeTitle}
                            onChange={(event) => setKnowledgeTitle(event.target.value)}
                            style={{ marginTop: 10 }}
                          />
                          <Input.TextArea
                            rows={3}
                            placeholder="内容"
                            value={knowledgeContent}
                            onChange={(event) =>
                              setKnowledgeContent(event.target.value)
                            }
                            style={{ marginTop: 6 }}
                          />
                          <Button
                            size="small"
                            type="primary"
                            onClick={() => void addKnowledge()}
                            style={{ marginTop: 6 }}
                          >
                            添加知识
                          </Button>
                        </>
                      ) : (
                        <div className="muted">保存后可以添加知识条目</div>
                      ),
                    },
                  ]}
                />
              </Form>
            </div>
            <div className="side-drawer-foot">
              {editing ? (
                <Popconfirm
                  title="删除该 AI 员工？"
                  description="其知识库条目会一并删除。"
                  onConfirm={() => void remove(editing)}
                >
                  <Button danger>删除</Button>
                </Popconfirm>
              ) : null}
              <span className="side-drawer-spacer" />
              <Button onClick={() => setDrawerOpen(false)}>取消</Button>
              <Button type="primary" loading={saving} onClick={() => void save()}>
                保存
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </Card>
  );
}

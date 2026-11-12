import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Drawer,
  Form,
  Input,
  Popconfirm,
  Space,
  Switch,
  Table,
  message,
} from "antd";
import dayjs from "dayjs";
import { api } from "../api";

type Skill = {
  id: number;
  name: string;
  title: string;
  description: string;
  instruction: string;
  enabled: boolean;
  created_by: string;
  created_at: string | null;
  updated_at: string | null;
  updated_by: string;
};

function time(value: string | null): string {
  return value ? dayjs(value).format("YYYY-MM-DD HH:mm:ss") : "-";
}

export default function SkillsPage() {
  const [items, setItems] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const [drawer, setDrawer] = useState(false);
  const [editing, setEditing] = useState<Skill | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  const load = async () => {
    setLoading(true);
    try {
      const data = await api<{ items: Skill[]; total: number }>("/skills");
      setItems(data.items);
    } catch (exc) {
      message.error((exc as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ name: "", title: "", description: "", instruction: "", enabled: true });
    setDrawer(true);
  };

  const openEdit = (skill: Skill) => {
    setEditing(skill);
    form.setFieldsValue({
      name: skill.name,
      title: skill.title,
      description: skill.description,
      instruction: skill.instruction,
      enabled: skill.enabled,
    });
    setDrawer(true);
  };

  const submit = async (values: Record<string, unknown>) => {
    setSaving(true);
    try {
      if (editing) {
        await api(`/skills/${editing.id}`, {
          method: "PUT",
          body: JSON.stringify({
            title: values.title,
            description: values.description ?? "",
            instruction: values.instruction,
            enabled: Boolean(values.enabled),
          }),
        });
        message.success("技能已更新");
      } else {
        await api("/skills", {
          method: "POST",
          body: JSON.stringify({
            name: values.name,
            title: values.title,
            description: values.description ?? "",
            instruction: values.instruction,
            enabled: Boolean(values.enabled),
          }),
        });
        message.success("技能已创建");
      }
      setDrawer(false);
      await load();
    } catch (exc) {
      message.error((exc as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const toggleEnabled = async (skill: Skill, enabled: boolean) => {
    try {
      await api(`/skills/${skill.id}`, {
        method: "PUT",
        body: JSON.stringify({ enabled }),
      });
      message.success(enabled ? "技能已启用" : "技能已停用");
      await load();
    } catch (exc) {
      message.error((exc as Error).message);
    }
  };

  const remove = async (skill: Skill) => {
    try {
      await api(`/skills/${skill.id}`, { method: "DELETE" });
      message.success("技能已删除");
      await load();
    } catch (exc) {
      message.error((exc as Error).message);
    }
  };

  return (
    <Card
      size="small"
      title="自定义技能"
      extra={
        <Button type="primary" size="small" onClick={openCreate}>
          新建技能
        </Button>
      }
    >
      <p className="muted" style={{ marginTop: 0 }}>
        技能在助手对话中以 <code>run_skill_&lt;name&gt;</code> 工具形式提供；模型按描述匹配场景后调用，
        按指令文本执行。改动即时生效（每请求读取），停用后模型不再可见。
      </p>
      <Table
        size="small"
        rowKey="id"
        loading={loading}
        dataSource={items}
        pagination={items.length > 20 ? { pageSize: 20 } : false}
        columns={[
          {
            key: "row",
            title: "#",
            width: 48,
            render: (_v, _r, index) => index + 1,
          },
          { key: "name", title: "标识", dataIndex: "name", width: 170 },
          { key: "title", title: "名称", dataIndex: "title", width: 180 },
          {
            key: "description",
            title: "描述",
            dataIndex: "description",
            ellipsis: true,
          },
          {
            key: "tool",
            title: "工具名",
            width: 210,
            render: (_v, record) => (
              <code>run_skill_{record.name}</code>
            ),
          },
          {
            key: "enabled",
            title: "启用",
            dataIndex: "enabled",
            width: 80,
            render: (value: boolean, record) => (
              <Switch
                size="small"
                checked={value}
                onChange={(checked) => void toggleEnabled(record, checked)}
              />
            ),
          },
          {
            key: "updated",
            title: "更新时间",
            dataIndex: "updated_at",
            width: 160,
            render: (value: string, record) => (
              <span className="time-cell">
                {time(value)}
                {record.updated_by ? ` · ${record.updated_by}` : ""}
              </span>
            ),
          },
          {
            key: "actions",
            title: "操作",
            width: 130,
            render: (_v, record) => (
              <Space size={4}>
                <Button size="small" type="text" onClick={() => openEdit(record)}>
                  编辑
                </Button>
                <Popconfirm
                  title="删除该技能？"
                  description="删除后模型立即失去对应工具。"
                  onConfirm={() => void remove(record)}
                >
                  <Button size="small" type="text" danger>
                    删除
                  </Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />
      <Drawer
        width={640}
        open={drawer}
        onClose={() => setDrawer(false)}
        title={editing ? `编辑技能 · ${editing.title}` : "新建技能"}
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={submit}>
          <Form.Item
            name="name"
            label="标识（name）"
            rules={[
              { required: true },
              {
                pattern: /^[a-z0-9_]{1,64}$/,
                message: "仅小写字母/数字/下划线，最长 64",
              },
            ]}
            extra={editing ? "创建后不可修改" : "工具名将为 run_skill_<标识>"}
          >
            <Input disabled={!!editing} placeholder="region_report" />
          </Form.Item>
          <Form.Item name="title" label="名称" rules={[{ required: true }]}>
            <Input placeholder="区域销售周报" maxLength={128} />
          </Form.Item>
          <Form.Item
            name="description"
            label="描述"
            extra="告诉模型什么场景该用这个技能，尽量具体"
          >
            <Input.TextArea rows={2} maxLength={2000} />
          </Form.Item>
          <Form.Item
            name="instruction"
            label="指令"
            rules={[{ required: true }]}
            extra="模型调用技能后会收到这段指令，并按它执行；可引用其他工具（如 query_dataset）"
          >
            <Input.TextArea rows={10} placeholder={"1. …\n2. …"} />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Space>
            <Button type="primary" htmlType="submit" loading={saving}>
              {editing ? "保存" : "创建"}
            </Button>
            <Button onClick={() => setDrawer(false)}>取消</Button>
          </Space>
        </Form>
      </Drawer>
    </Card>
  );
}

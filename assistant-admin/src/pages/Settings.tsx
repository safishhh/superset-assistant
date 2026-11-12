import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Form,
  InputNumber,
  Space,
  Spin,
  Switch,
  message,
} from "antd";
import dayjs from "dayjs";
import { api } from "../api";
import type { KnowledgeSettings } from "../types";

function time(value: string | null | undefined): string {
  return value ? dayjs(value).format("YYYY-MM-DD HH:mm:ss") : "从未保存";
}

const FALLBACK: KnowledgeSettings = {
  user_max_entries: 200,
  auto_max_entries: 500,
  auto_ttl_days: 90,
  trash_retention_days: 30,
  auto_merge_enabled: true,
  updated_at: null,
  updated_by: "",
};

export default function SettingsPage() {
  const [form] = Form.useForm();
  const [config, setConfig] = useState<KnowledgeSettings | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let alive = true;
    api<KnowledgeSettings>("/knowledge-settings")
      .then((data) => {
        if (alive) setConfig(data);
      })
      .catch((exc) => {
        message.error((exc as Error).message);
        if (alive) setConfig(FALLBACK);
      });
    return () => {
      alive = false;
    };
  }, []);

  const submit = async (values: Record<string, number | boolean>) => {
    setSaving(true);
    try {
      const data = await api<KnowledgeSettings>("/knowledge-settings", {
        method: "PUT",
        body: JSON.stringify({
          user_max_entries: Number(values.user_max_entries ?? 0),
          auto_max_entries: Number(values.auto_max_entries ?? 0),
          auto_ttl_days: Number(values.auto_ttl_days ?? 0),
          trash_retention_days: Number(values.trash_retention_days ?? 0),
          auto_merge_enabled: Boolean(values.auto_merge_enabled),
        }),
      });
      setConfig(data);
      form.setFieldsValue(data);
      message.success("知识库设置已保存，下一次请求即生效");
    } catch (exc) {
      message.error((exc as Error).message);
    } finally {
      setSaving(false);
    }
  };

  if (!config) {
    return (
      <Card size="small" title="知识库设置">
        <div style={{ textAlign: "center", padding: 48 }}>
          <Spin />
        </div>
      </Card>
    );
  }

  return (
    <Card
      size="small"
      title="知识库设置"
      extra={
        <span className="muted">
          更新于 {time(config.updated_at)}
          {config.updated_by ? ` · ${config.updated_by}` : ""}
        </span>
      }
    >
      <p className="muted" style={{ marginTop: 0 }}>
        知识库分两类：
        <b>手动</b>＝用户在知识库界面自己填的，系统永不改写、永不归并；
        <b>AI 记录</b>＝模型在对话中沉淀的（含用户说“记住这个口径”），会归并近义条目、
        按使用度检索。0 表示不限制。手动条目达上超时拒绝示用户录入；AI 记录达上限将最久
        未命中的条目自动归档。
      </p>
      <Form
        form={form}
        layout="vertical"
        initialValues={config}
        onFinish={submit}
        style={{ maxWidth: 760 }}
      >
        <Space size={24} wrap>
          <Form.Item
            name="user_max_entries"
            label="手动条目上限"
          >
            <InputNumber min={0} step={10} style={{ width: 180 }} />
          </Form.Item>
          <Form.Item
            name="auto_max_entries"
            label="AI 记录上限"
          >
            <InputNumber min={0} step={10} style={{ width: 180 }} />
          </Form.Item>
          <Form.Item
            name="auto_ttl_days"
            label="AI 记录过期天数"
            extra="零命中且超过该天数进回收站；0=不过期"
          >
            <InputNumber min={0} step={30} style={{ width: 180 }} />
          </Form.Item>
          <Form.Item
            name="trash_retention_days"
            label="回收站保留天数"
            extra="到期归档并物理删除；0=不清理"
          >
            <InputNumber min={0} step={10} style={{ width: 180 }} />
          </Form.Item>
          <Form.Item
            name="auto_merge_enabled"
            label="AI 记录归并近义标题"
            valuePropName="checked"
            extra="关闭后每次沉淀都新建条目"
          >
            <Switch />
          </Form.Item>
        </Space>
        <div>
          <Space size={8}>
            <Button type="primary" htmlType="submit" loading={saving}>
              保存
            </Button>
            <Button onClick={() => form.setFieldsValue(config)}>重置</Button>
          </Space>
        </div>
      </Form>
    </Card>
  );
}

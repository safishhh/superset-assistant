import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Form,
  InputNumber,
  Space,
  Spin,
  message,
} from "antd";
import dayjs from "dayjs";
import { api } from "../api";
import { LimitsConfig } from "../types";

function time(value: string | null): string {
  return value ? dayjs(value).format("YYYY-MM-DD HH:mm:ss") : "从未保存";
}

const FALLBACK: LimitsConfig = {
  rate_per_minute: 0,
  daily_requests: 0,
  daily_tokens: 0,
  daily_cost: 0,
  updated_at: null,
  updated_by: "",
};

export default function LimitsPage() {
  const [form] = Form.useForm();
  const [config, setConfig] = useState<LimitsConfig | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let alive = true;
    api<LimitsConfig>("/limits")
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

  const submit = async (values: Record<string, number>) => {
    setSaving(true);
    try {
      const data = await api<LimitsConfig>("/limits", {
        method: "PUT",
        body: JSON.stringify({
          rate_per_minute: Number(values.rate_per_minute ?? 0),
          daily_requests: Number(values.daily_requests ?? 0),
          daily_tokens: Number(values.daily_tokens ?? 0),
          daily_cost: Number(values.daily_cost ?? 0),
        }),
      });
      setConfig(data);
      form.setFieldsValue({
        rate_per_minute: data.rate_per_minute,
        daily_requests: data.daily_requests,
        daily_tokens: data.daily_tokens,
        daily_cost: data.daily_cost,
      });
      message.success("限额配置已保存");
    } catch (exc) {
      message.error((exc as Error).message);
    } finally {
      setSaving(false);
    }
  };

  if (!config) {
    return (
      <Card size="small" title="用户限流与额度">
        <div style={{ textAlign: "center", padding: 48 }}>
          <Spin />
        </div>
      </Card>
    );
  }

  return (
    <Card
      size="small"
      title="用户限流与额度"
      extra={
        <span className="muted">
          更新于 {time(config.updated_at)}
          {config.updated_by ? ` · ${config.updated_by}` : ""}
        </span>
      }
    >
      <p className="muted" style={{ marginTop: 0 }}>
        0 表示不限制；Admin 角色豁免所有限额；每分钟限流为单进程内存实现，
        多实例部署时各进程独立计数；每日额度基于用量日聚合，在对话入口检查，超限返回 429。
      </p>
      <Form
        form={form}
        layout="vertical"
        initialValues={config}
        onFinish={submit}
        style={{ maxWidth: 760 }}
      >
        <Space size={24} wrap>
          <Form.Item name="rate_per_minute" label="每分钟请求数" extra="单用户滑动窗口限流">
            <InputNumber min={0} step={1} style={{ width: 180 }} />
          </Form.Item>
          <Form.Item name="daily_requests" label="每日请求数" extra="自然日按用量日聚合统计">
            <InputNumber min={0} step={10} style={{ width: 180 }} />
          </Form.Item>
          <Form.Item name="daily_tokens" label="每日 Token 数" extra="输入 + 输出 Token 合计">
            <InputNumber min={0} step={1000} style={{ width: 180 }} />
          </Form.Item>
          <Form.Item name="daily_cost" label="每日成本（$）" extra="按模型单价累计">
            <InputNumber min={0} step={0.5} precision={2} style={{ width: 180 }} />
          </Form.Item>
        </Space>
        <div>
          <Space size={8}>
            <Button type="primary" htmlType="submit" loading={saving}>
              保存
            </Button>
            <Button
              onClick={() => {
                form.setFieldsValue({
                  rate_per_minute: config.rate_per_minute,
                  daily_requests: config.daily_requests,
                  daily_tokens: config.daily_tokens,
                  daily_cost: config.daily_cost,
                });
              }}
            >
              重置
            </Button>
          </Space>
        </div>
      </Form>
    </Card>
  );
}

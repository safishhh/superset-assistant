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
import { AgentLimitsConfig } from "../types";

function time(value: string | null): string {
  return value ? dayjs(value).format("YYYY-MM-DD HH:mm:ss") : "从未保存";
}

const FALLBACK: AgentLimitsConfig = {
  max_tool_calls: 16,
  max_rows: 500,
  superset_sql_max_row: 5000,
  updated_at: null,
  updated_by: "",
};

export default function AgentLimitsPage() {
  const [form] = Form.useForm();
  const [config, setConfig] = useState<AgentLimitsConfig | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let alive = true;
    api<AgentLimitsConfig>("/agent-limits")
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
      const data = await api<AgentLimitsConfig>("/agent-limits", {
        method: "PUT",
        body: JSON.stringify({
          max_tool_calls: Number(values.max_tool_calls ?? 16),
          max_rows: Number(values.max_rows ?? 500),
        }),
      });
      setConfig(data);
      form.setFieldsValue({
        max_tool_calls: data.max_tool_calls,
        max_rows: data.max_rows,
      });
      message.success("运行限制已保存");
    } catch (exc) {
      message.error((exc as Error).message);
    } finally {
      setSaving(false);
    }
  };

  if (!config) {
    return (
      <Card size="small" title="运行限制">
        <div style={{ textAlign: "center", padding: 48 }}>
          <Spin />
        </div>
      </Card>
    );
  }

  const layers = [
    {
      key: "agent",
      layer: "本页设置 · Agent 取数上限",
      value: `${config.max_rows} 行`,
      source:
        "存 ai_app_setting(agent_limits)，每次请求读取，保存即生效。",
    },
    {
      key: "ceiling",
      layer: "Agent 天花板",
      value: `${config.superset_sql_max_row ?? 5000} 行`,
      source:
        "Agent 环境变量 SUPERSET_SQL_MAX_ROW（未设置时代码默认 5000）。它只是宿主配置的镜像值、不会实时读取宿主；本页填得再大也会被它夹住，要放开需同时改 infra/.env 并重建 agent 容器。",
    },
    {
      key: "host",
      layer: "宿主硬上限",
      value: "SQL_MAX_ROW 5000 · ROW_LIMIT 5000",
      source:
        "写在 infra/superset_config.py（Superset 出厂默认分别是 100000 与 50000）。SQL Lab 执行 SQL 时按 SQL_MAX_ROW 夹，图表与数据集查询按 ROW_LIMIT 夹；改完必须 --force-recreate superset/superset-mcp/worker/beat 才生效。",
    },
  ];

  return (
    <Card
      size="small"
      className="limits-card"
      title="运行限制"
      extra={
        <span className="muted">
          更新于 {time(config.updated_at)}
          {config.updated_by ? ` · ${config.updated_by}` : ""}
        </span>
      }
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={config}
        onFinish={submit}
        style={{ maxWidth: 760 }}
      >
        <Space size={24} wrap>
          <Form.Item
            name="max_tool_calls"
            label="单次请求工具调用上限"
            extra="一轮回答内所有工具调用（列表/取数/分析等）的总次数；默认 16；0 = 不限制"
          >
            <InputNumber min={0} step={1} style={{ width: 180 }} />
          </Form.Item>
          <Form.Item
            name="max_rows"
            label="单次查询返回行数上限"
            extra={`一次取数返回的结果行数（聚合查询=分组数，明细查询=明细行数）；默认 500，最大 ${
              config.superset_sql_max_row ?? 5000
            }`}
          >
            <InputNumber
              min={1}
              max={config.superset_sql_max_row ?? 5000}
              step={100}
              style={{ width: 180 }}
            />
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
                  max_tool_calls: config.max_tool_calls,
                  max_rows: config.max_rows,
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

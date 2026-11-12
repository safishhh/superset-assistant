import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Checkbox,
  Col,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  message,
} from "antd";
import { api } from "../api";
import { byBoolean, byNumber, byText, indexColumn } from "../sorters";
import { Model, Provider } from "../types";

export default function ModelsPage() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [models, setModels] = useState<Model[]>([]);
  const [providerOpen, setProviderOpen] = useState(false);
  const [editingProvider, setEditingProvider] = useState<Provider | null>(null);
  const [modelOpen, setModelOpen] = useState(false);
  const [editingModel, setEditingModel] = useState<Model | null>(null);
  const [providerForm] = Form.useForm();
  const [modelForm] = Form.useForm();

  const load = async () => {
    try {
      const [nextProviders, nextModels] = await Promise.all([
        api<Provider[]>("/providers"),
        api<Model[]>("/models"),
      ]);
      setProviders(nextProviders);
      setModels(nextModels);
    } catch (exc) {
      message.error((exc as Error).message);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const openProvider = (record?: Provider) => {
    setEditingProvider(record || null);
    providerForm.resetFields();
    if (record) {
      providerForm.setFieldsValue({ ...record, api_key: "", clear_api_key: false });
    } else {
      providerForm.setFieldsValue({ enabled: true, api_key: "" });
    }
    setProviderOpen(true);
  };

  const submitProvider = async (values: Record<string, unknown>) => {
    try {
      if (editingProvider) {
        await api(`/providers/${editingProvider.id}`, {
          method: "PUT",
          body: JSON.stringify(values),
        });
      } else {
        await api("/providers", {
          method: "POST",
          body: JSON.stringify(values),
        });
      }
      message.success("Provider 已保存");
      setProviderOpen(false);
      await load();
    } catch (exc) {
      message.error((exc as Error).message);
    }
  };

  const openModel = (record?: Model) => {
    setEditingModel(record || null);
    modelForm.resetFields();
    if (record) {
      modelForm.setFieldsValue(record);
    } else {
      modelForm.setFieldsValue({
        supports_tools: true,
        enabled: true,
        is_default: false,
        disable_thinking: false,
        context_window: 200000,
        input_price_per_m: 0,
        output_price_per_m: 0,
      });
    }
    setModelOpen(true);
  };

  const submitModel = async (values: Record<string, unknown>) => {
    try {
      if (editingModel) {
        await api(`/models/${editingModel.id}`, {
          method: "PUT",
          body: JSON.stringify(values),
        });
      } else {
        await api("/models", {
          method: "POST",
          body: JSON.stringify(values),
        });
      }
      message.success("模型已保存");
      setModelOpen(false);
      await load();
    } catch (exc) {
      message.error((exc as Error).message);
    }
  };

  const testProvider = async (record: Provider) => {
    try {
      const result = await api<{
        ok: boolean;
        status: number;
        latency_ms: number;
        message: string;
      }>(`/providers/${record.id}/test`, { method: "POST" });
      if (result.ok) {
        message.success(`连接正常 · ${result.latency_ms}ms`);
      } else {
        message.error(`连接失败 · HTTP ${result.status} · ${result.message}`);
      }
    } catch (exc) {
      message.error((exc as Error).message);
    }
  };

  return (
    <div>
      <Card
        size="small"
        title="Provider"
        extra={
          <Button size="small" type="primary" onClick={() => openProvider()}>
            新增 Provider
          </Button>
        }
        style={{ marginBottom: 12 }}
      >
        <Table
          size="small"
          rowKey="id"
          pagination={false}
          dataSource={providers}
          columns={[
            indexColumn<Provider>(),
            {
              title: "名称",
              dataIndex: "name",
              width: 120,
              sorter: byText<Provider>("name"),
            },
            {
              title: "Base URL",
              dataIndex: "base_url",
              ellipsis: true,
              sorter: byText<Provider>("base_url"),
            },
            {
              title: "API Key",
              width: 140,
              sorter: byText<Provider>("api_key_hint"),
              render: (_: unknown, record: Provider) =>
                record.has_api_key ? (
                  <span className="mono">{record.api_key_hint || "已配置"}</span>
                ) : (
                  <span className="muted">未配置</span>
                ),
            },
            {
              title: "状态",
              dataIndex: "enabled",
              width: 70,
              sorter: byBoolean<Provider>("enabled"),
              render: (value: boolean) => (
                <Tag color={value ? "green" : "default"}>
                  {value ? "启用" : "停用"}
                </Tag>
              ),
            },
            {
              title: "操作",
              width: 210,
              render: (_: unknown, record: Provider) => (
                <Space size={4}>
                  <Button size="small" onClick={() => testProvider(record)}>
                    测试
                  </Button>
                  <Button size="small" onClick={() => openProvider(record)}>
                    编辑
                  </Button>
                  <Popconfirm
                    title="删除 Provider？"
                    description="请先删除它下面的模型。"
                    onConfirm={async () => {
                      try {
                        await api(`/providers/${record.id}`, { method: "DELETE" });
                        message.success("已删除");
                        await load();
                      } catch (exc) {
                        message.error((exc as Error).message);
                      }
                    }}
                  >
                    <Button size="small" danger>
                      删除
                    </Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Card
        size="small"
        title="模型"
        extra={
          <Button
            size="small"
            type="primary"
            disabled={providers.length === 0}
            onClick={() => openModel()}
          >
            新增模型
          </Button>
        }
      >
        <Table
          size="small"
          rowKey="id"
          pagination={false}
          dataSource={models}
          columns={[
            indexColumn<Model>(),
            {
              title: "模型",
              dataIndex: "model_name",
              sorter: byText<Model>("model_name"),
              render: (value: string, record: Model) => (
                <Space size={4}>
                  <span className="mono">{value}</span>
                  {record.is_default ? <Tag color="blue">默认</Tag> : null}
                </Space>
              ),
            },
            {
              title: "Provider",
              dataIndex: "provider_name",
              width: 120,
              sorter: byText<Model>("provider_name"),
            },
            {
              title: "工具",
              dataIndex: "supports_tools",
              width: 60,
              sorter: byBoolean<Model>("supports_tools"),
              render: (value: boolean) => (value ? "是" : "否"),
            },
            {
              title: "Thinking",
              dataIndex: "disable_thinking",
              width: 80,
              sorter: byBoolean<Model>("disable_thinking"),
              render: (value: boolean) => (value ? "关闭" : "开启"),
            },
            {
              title: "上下文",
              dataIndex: "context_window",
              width: 80,
              render: (value: number) =>
                `${Math.round((value || 200000) / 1000)}k`,
            },
            {
              title: "输入价/M",
              dataIndex: "input_price_per_m",
              width: 90,
              align: "right" as const,
              sorter: byNumber<Model>("input_price_per_m"),
              render: (value: number) => `$${Number(value || 0).toFixed(4)}`,
            },
            {
              title: "输出价/M",
              dataIndex: "output_price_per_m",
              width: 90,
              align: "right" as const,
              sorter: byNumber<Model>("output_price_per_m"),
              render: (value: number) => `$${Number(value || 0).toFixed(4)}`,
            },
            {
              title: "状态",
              dataIndex: "enabled",
              width: 60,
              sorter: byBoolean<Model>("enabled"),
              render: (value: boolean) => (
                <Tag color={value ? "green" : "default"}>
                  {value ? "启用" : "停用"}
                </Tag>
              ),
            },
            {
              title: "操作",
              width: 220,
              render: (_: unknown, record: Model) => (
                <Space size={4}>
                  {!record.is_default ? (
                    <Button
                      size="small"
                      onClick={async () => {
                        try {
                          await api(`/models/${record.id}/default`, {
                            method: "POST",
                          });
                          message.success("已设为默认");
                          await load();
                        } catch (exc) {
                          message.error((exc as Error).message);
                        }
                      }}
                    >
                      设为默认
                    </Button>
                  ) : null}
                  <Button size="small" onClick={() => openModel(record)}>
                    编辑
                  </Button>
                  <Popconfirm
                    title="删除模型？"
                    onConfirm={async () => {
                      try {
                        await api(`/models/${record.id}`, { method: "DELETE" });
                        message.success("已删除");
                        await load();
                      } catch (exc) {
                        message.error((exc as Error).message);
                      }
                    }}
                  >
                    <Button size="small" danger>
                      删除
                    </Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        open={providerOpen}
        title={editingProvider ? "编辑 Provider" : "新增 Provider"}
        onCancel={() => setProviderOpen(false)}
        onOk={() => providerForm.submit()}
        destroyOnClose
      >
        <Form form={providerForm} layout="vertical" onFinish={submitProvider}>
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: "请输入名称" }]}
          >
            <Input placeholder="default" />
          </Form.Item>
          <Form.Item
            name="base_url"
            label="Base URL"
            rules={[{ required: true, message: "请输入 Base URL" }]}
          >
            <Input placeholder="https://.../v1" />
          </Form.Item>
          <Form.Item name="api_key" label="API Key">
            <Input.Password
              placeholder={
                editingProvider ? "留空表示不修改" : "输入 API Key"
              }
            />
          </Form.Item>
          {editingProvider ? (
            <Form.Item name="clear_api_key" valuePropName="checked">
              <Checkbox>清空 API Key</Checkbox>
            </Form.Item>
          ) : null}
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={modelOpen}
        title={editingModel ? "编辑模型" : "新增模型"}
        onCancel={() => setModelOpen(false)}
        onOk={() => modelForm.submit()}
        destroyOnClose
      >
        <Form form={modelForm} layout="vertical" onFinish={submitModel}>
          <Form.Item
            name="provider_id"
            label="Provider"
            rules={[{ required: true, message: "请选择 Provider" }]}
          >
            <Select
              options={providers.map((item) => ({
                value: item.id,
                label: item.name,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="model_name"
            label="模型名"
            rules={[{ required: true, message: "请输入模型名" }]}
          >
            <Input placeholder="MiniCPM5-2B" />
          </Form.Item>
          <Form.Item name="display_name" label="显示名">
            <Input placeholder="留空使用模型名" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={6}>
              <Form.Item name="supports_tools" label="支持工具" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item
                name="disable_thinking"
                label="关闭 Thinking"
                valuePropName="checked"
              >
                <Switch />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="is_default" label="设为默认" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="enabled" label="启用" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="context_window"
                label="上下文窗口"
              >
                <Select
                  style={{ width: "100%" }}
                  options={[
                    { value: 200000, label: "200k（默认）" },
                    { value: 400000, label: "400k" },
                    { value: 600000, label: "600k" },
                    { value: 800000, label: "800k" },
                    { value: 1000000, label: "1M" },
                  ]}
                />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="input_price_per_m" label="输入价 / 1M">
                <InputNumber min={0} step={0.01} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="output_price_per_m" label="输出价 / 1M">
                <InputNumber min={0} step={0.01} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </div>
  );
}

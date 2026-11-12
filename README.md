# Superset 悬浮分析助手

基于 **Apache Superset 7.0.0rc2** 的数据分析助手：在 Superset 页面内以悬浮球、浮窗或停靠面板提供自然语言问数、归因分析、图表展示和受确认保护的写操作，并附带仅管理员可用的 AI 管理后台。

本仓库包含 Superset 源码构建、Superset 扩展、Agent 服务、管理后台、初始化脚本和验证脚本，不是独立的数据门户。用户仍从 Superset 进入，数据权限仍由 Superset 控制。

## 能做什么

### 面向 Superset 用户

- **自然语言问数**：发现数据集、读取字段与口径、查询数据，并展示表格、柱状图、折线图、饼图或单值 KPI 大数字卡。
- **固化分析计算**：环比/同比、维度贡献度、结构效应，由 Agent 端 pandas 代码计算。
- **理解当前页面**：携带看板、图表、数据集、筛选和 SQL Lab 上下文；也可主动选中页面上的图表或区块作为下一轮问题的上下文。
- **多轮对话**：保留工具步骤、图表和选区；支持历史会话、继续对话、复制回答、逐轮或整会话导出 Markdown/HTML。
- **后台生成**：关闭面板或断开连接不中断回答；重新打开可续看，点击“停止”才会取消服务端任务。
- **个人知识库**：手动维护或让 AI 沉淀业务口径，支持检索、引用、回收站和配额治理。
- **AI 牛马（AI 员工）**：按用户/角色提供不同人设、模型、技能、工具和知识库；可配置员工间委派。
- **对话控制**：悬浮、停靠或全屏使用；可在员工允许的范围内切换模型，并按请求选择思考强度。
- **受控写操作**：模型只能提出建图、建看板、修改、删除等方案；用户在卡片中确认后执行，可取消或按快照回滚，支持批量二次确认。
- **回答反馈**：逐条点赞/点踩，用于质量评估。

### 面向管理员

管理后台从助手头部的管理入口进入，不另建公共登录入口。主要包括：

- 概览、用量明细/聚合、用户/模型/员工榜单与回答反馈。
- Provider 与模型配置、用户限额、Agent 工具调用/查询行数限制。
- 用户 AI 助手开关、角色与员工授权。
- AI 员工的人设、模型、协调、技能、工具白名单与独立知识库。
- 自定义技能、个人知识库治理参数。
- 对话/工具/写操作/管理操作审计，运行日志与逐次 AI 调用日志。

## 架构与权限边界

```text
浏览器
  └─ Superset :8088
       └─ dataagent.assistant 扩展
            ├─ 悬浮/停靠聊天面板
            ├─ 签发短期用户 JWT
            └─ 管理员一次性 ticket
                  │
                  ▼
           Agent :28088
            ├─ FastAPI + Pydantic AI
            ├─ OpenAI 兼容模型
            ├─ 查询/分析/知识库/写方案工具
            ├─ 管理后台与 MySQL 管理库
            └─ MCP 客户端（按请求携带用户身份）
                  │
                  ▼
           Superset MCP（容器内 :5008）
            └─ 以同一个 Superset 用户执行 RBAC / RLS
```

关键边界：

- **不拥有超越宿主的数据权限**：数据访问通过 Superset MCP，以当前用户身份执行；数据集访问、RBAC 和已配置的 RLS 继续生效。
- **自由 SQL 不是默认能力**：是否可执行由用户自己的 Superset SQL Lab 权限决定；Agent 另做只读 SQL 校验、超时和行数限制。
- **写操作先方案后确认**：模型不能直接执行持久化写工具；确认、批量执行和回滚均由独立 API 完成。
- **管理端仅 Admin**：前端隐藏入口不是安全边界，服务端仍校验 Admin 角色；管理写操作要求 CSRF。
- **凭证不进入审计**：模型密钥加密保存且不回显明文；日志过滤常见密码、Token 和 Authorization 内容。
- **工具结果是不可信数据**：数据值、列名、描述或知识库文本不能覆盖系统指令。

## 快速开始

### 1. 准备环境

需要 Linux、Docker 与 Docker Compose、可访问的 MySQL 8、Node.js、Python 3.11+ 和 Superset 扩展 CLI。Superset 镜像从**你 fork 的 Superset 源码**构建：本仓库不包含 `superset-7.0.0rc2/`，请先把 fork 克隆到仓库根目录（或设置 `SUPERSET_SRC`）。首次构建会编译 Superset 前端并安装 Python 依赖，耗时较长。

```bash
git clone --depth 1 --branch 7.0.0rc2 \
  https://github.com/<你的账号>/superset.git superset-7.0.0rc2
```

完整依赖版本、MySQL 建库、扩展 CLI 安装、网络和生产加固见 [DEPLOY.md](DEPLOY.md)；首次部署请先完成这些准备，再执行下面的命令。

### 2. 配置并启动

```bash
cp infra/.env.example infra/.env
# 编辑 infra/.env：替换所有开发密码/密钥，配置模型与 MySQL 连接

# 构建扩展、管理后台，初始化 MySQL 并启动完整服务栈
bash scripts/init-stack.sh
```

脚本会检测并按需构建 Superset 镜像；也可先单独执行：

```bash
bash scripts/build-superset.sh
bash scripts/build-extension.sh
bash scripts/build-admin.sh
```

### 3. 打开系统

- Superset：`http://<服务器地址>:8088/`（宿主端口可在 `infra/.env` 修改）。
- 助手：登录 Superset 后点击页面边缘的悬浮球。
- 管理后台：Admin 用户在助手头部点击管理入口；直接访问 `/admin` 不等于绕过 Superset 管理票据认证。

### 4. 首次使用流程

1. Admin 从助手头部进入管理后台，在“模型配置”中添加 Provider 和可用模型。
2. 在“AI 牛马”中配置员工的人设、可用模型、技能、工具与可见范围；在“角色和权限”中按角色授权。
3. 普通用户回到 Superset，打开悬浮助手即可提问；需要针对某个图表时，先点“选择区块”，再点击页面图表。
4. 如果回答包含写操作方案，先核对对象、参数和风险，再点“确认执行”；多个方案可使用“全部执行”并二次确认。
5. 在“历史对话”中继续或导出会话，在“个人知识库”中维护可复用口径。

### 5. 验证

服务栈运行时执行：

```bash
bash scripts/verify.sh
python3 scripts/smoke_ai_assistant.py
```

第一条命令覆盖构建/容器状态、Agent 单测和基础鉴权；第二条覆盖助手 API、权限/RLS、管理接口和真实模型链路。全量冒烟依赖 seed/default-admin 等验收假设，会创建测试对话与反馈、临时修改限流并产生真实模型费用，**不要直接对生产环境运行**。

## 配置与工具文档

| 文档 | 用途 |
| --- | --- |
| [控制参数矩阵](superset-feature-matrix-7.0.0rc2.md) | Superset feature flags、本项目使用的 Superset 配置、Agent/扩展/后台环境变量与动态设置；含源码默认值、当前值、建议与生效方式。 |
| [MCP 与 Agent 工具清单](superset-mcp-tools-7.0.0rc2.md) | Superset 内置 MCP 工具和自定义工具的读写属性、权限、RLS 与用途。 |
| [从零部署](DEPLOY.md) | 源码镜像构建、MySQL/Redis/扩展/Agent 初始化、启动、验证、升级与故障排查。 |

修改 `infra/superset_config.py` 或 `infra/.env` 后不要只执行 `docker restart`；配置通过挂载或容器环境读取，需按 [DEPLOY.md](DEPLOY.md) 的说明重建对应容器。后台“设置”中的动态参数则由 Agent 按请求读取，无需重建。

## 目录导览

```text
superset-7.0.0rc2/          Superset 源码（不随仓库分发；fork 后 clone 到此或用 SUPERSET_SRC）
infra/
  Dockerfile.superset7      Superset 多阶段镜像构建
  docker-compose.yml       Superset、MCP、worker、beat、Agent 服务栈
  superset_config.py       Superset/MCP/扩展/Celery/SMTP 配置
  seed_superset.py         演示库、数据集、用户、RLS 与权限初始化
  .env.example             环境变量模板（真实 .env 不应提交）
assistant-ext/assistant/   Superset 扩展：聊天前端 + token/admin ticket 后端
agent-service/             FastAPI、Pydantic AI、工具、管理 API、审计与日志
assistant-admin/           React + antd 管理后台
scripts/                   构建、初始化、迁移、评估与验证脚本
```

## 开发与验证约定

- 扩展前端变更后重新构建扩展 `dist/`；Superset 后端配置或扩展后端变更后重建对应 Superset 容器。
- Agent Python 源码变更后重启 Agent；环境变量或依赖变更后重建/重创建 Agent 容器。
- 管理后台变更后重新执行 `bash scripts/build-admin.sh`。
- 后端测试位于 `agent-service/tests/`，服务栈运行时可执行 `docker exec assistant-agent python -m pytest -q /app/tests`。
- 扩展与管理后台分别提供 TypeScript 类型检查/构建命令。
- 中文语言包 `infra/translations/` 是生成产物（不入库），需要时按 [DEPLOY.md](DEPLOY.md) 的说明重新生成。
- 推送到 GitHub 前执行 `git add -A && bash scripts/check-release.sh`，确认没有密钥、运行数据、构建产物或个人信息被跟踪。
- 不要用生产数据做写操作验证；测试只操作自己创建且可回滚的对象。

## 当前基线

- Superset：**7.0.0rc2**（发布候选版本，生产使用前应评估并固定升级计划）。
- Agent：FastAPI、Pydantic AI、SQLAlchemy、pandas。
- 扩展：React 18、assistant-ui、AI SDK。
- 管理后台：React 18、antd 5、Vite。
- 数据与元数据：MySQL 8；Celery/缩略图缓存使用容器内 Redis。

配置和工具清单以 **2026-10-31 的源码与运行环境复核结果**为准；后续修改 feature flags、MCP 版本或工具策略时，应同步更新对应矩阵。

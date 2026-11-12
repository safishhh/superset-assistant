# Superset 悬浮分析助手：从 0 到 1 部署

本文按当前仓库中的 Dockerfile、Compose、初始化脚本和构建配置编写。所有命令默认在仓库根目录执行；`COMPOSE=(...)` 写法要求使用 Bash。

> **先区分用途**：`scripts/init-stack.sh` 和当前 `infra/docker-compose.yml` 适合开发、测试和内网验收。生产环境可以使用相同的构建与初始化顺序，但必须完成第 9 节的加固，不能沿用示例密码、root MySQL 账号、mock 模型、调试端口和 Agent `--reload`。

## 1. 组件与发布端口

| 组件 | 容器 | 默认宿主地址 | 数据/职责 |
| --- | --- | --- | --- |
| Superset | `assistant-superset` | `http://localhost:8088` | 页面、扩展、元数据库迁移与 seed |
| Agent | `assistant-agent` | `http://localhost:28088` | 聊天 API 与 `/admin` 管理后台 |
| Superset MCP | `assistant-mcp` | `localhost:25008/mcp` | Agent 的内部上游；宿主端口仅供调试 |
| Report worker | `assistant-superset-worker` | 不发布端口 | Alerts & Reports、缩略图等 Celery 任务 |
| Beat | `assistant-superset-beat` | 不发布端口 | Celery 定时调度 |
| Redis | `assistant-redis` | 不发布宿主端口 | Celery broker/backend、缩略图缓存 |

三个 MySQL 数据库默认分别是：

- `assistant_superset`：Superset 元数据。
- `assistant_admin`：对话、模型配置、审计、用量等 Agent 数据。
- `assistant_demo`：seed 创建的 `sales` 演示表。

容器内不能使用 `127.0.0.1` 指向宿主 MySQL。Compose 已配置 `host.docker.internal:host-gateway`，三个 SQLAlchemy URI 都应使用该主机名。

## 2. 准备全新机器

### 2.1 资源与软件

构建 Superset 前端和 Chromium 镜像需要较多时间与磁盘。建议至少 4 核、8 GB 内存并预留约 40 GB 磁盘；这不是脚本强制检查值，构建较大或同时运行多个服务时应增加资源。

需要：

- Linux；以下 apt 命令以 Ubuntu 24.04 为例。
- Docker Engine、Docker Compose v2 和支持 BuildKit 的 Docker 构建器。
- Node.js **22.12+** 与 npm **10.8.2+**。管理后台使用的 Vite 8 要求 Node `^20.19.0 || >=22.12.0`，扩展 CLI 另有 npm 最低版本检查。
- Python **3.11+**、pip 和 venv，用于安装 Superset 扩展 CLI 和运行宿主脚本。
- MySQL **8**，以及 MySQL 客户端。
- `git`、`curl`、`openssl`、`ss`（iproute2）。

Ubuntu 示例：

```bash
sudo apt update
sudo apt install -y \
  git curl openssl ca-certificates iproute2 \
  python3 python3-pip python3-venv \
  mysql-server mysql-client \
  docker.io docker-compose-v2

# Node 22；也可使用组织已有的 Node 镜像源或版本管理器。
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs

sudo systemctl enable --now docker mysql
sudo usermod -aG docker "$USER"
```

`usermod` 后重新登录，或先在当前 shell 使用 `newgrp docker`。然后检查：

```bash
docker version
docker compose version
node --version
npm --version
python3 --version
mysql --version
```

Superset 镜像内的前端构建使用 Node 24，不需要宿主 Node 24；宿主 Node 用于构建扩展和管理后台。

### 2.2 获取项目与 Superset 7.0.0rc2 源码

将本项目放到例如 `/opt/dataagent-app`，然后：

```bash
cd /opt/dataagent-app
```

本仓库**不包含** Superset 源码（`superset-7.0.0rc2/` 已在 `.gitignore` 中），构建脚本默认要求源码树位于 `superset-7.0.0rc2/`，且其中必须有 `setup.py` 和 `superset-frontend/`。请先 fork `apache/superset`，再把你的 fork 克隆到仓库根目录的对应标签：

```bash
# 把 <你的账号> 换成你的 GitHub 用户名
git clone --depth 1 --branch 7.0.0rc2 \
  https://github.com/<你的账号>/superset.git superset-7.0.0rc2
```

不想 fork 也可以直接用上游仓库；fork 的好处是能把本地改动/固定版本都映射到同一个仓库。需要把 Superset 提交固定在仓库里时，可改用 submodule（先删除 `.gitignore` 里的 `superset-7.0.0rc2/` 一行）：

```bash
git submodule add https://github.com/<你的账号>/superset.git superset-7.0.0rc2
git -C superset-7.0.0rc2 checkout 7.0.0rc2
```

也可把已有源码放到其他位置，之后使用：

```bash
SUPERSET_SRC=/absolute/path/to/superset-7.0.0rc2 bash scripts/build-superset.sh
```

`build-superset.sh` 不接受额外的 Docker 构建参数；需要完全手动控制构建时，使用第 5.1 节的 `docker build` 命令。

## 3. 配置宿主 MySQL 8

### 3.1 监听与 Docker 网络

MySQL 必须监听宿主 `3306`，并允许来自 Docker 网关的连接。Ubuntu 的配置通常位于 `/etc/mysql/mysql.conf.d/mysqld.cnf`；将 `bind-address` 设为 Docker 网关地址，或在受控内网设为 `0.0.0.0`，然后：

```bash
sudo systemctl restart mysql
ip -4 addr show docker0
ss -ltnp | grep 3306
```

防火墙只应允许 Docker 网关/必要网段访问 MySQL，不要将 `3306` 暴露到公网。Compose 的 `host-gateway` 在 Linux 上通常映射到 `docker0` 地址（常见为 `172.17.0.1`），实际以本机输出为准。

### 3.2 建库与专用账号

以下是开发/内网示例，账号宿主部分要与容器连接 MySQL 时的**来源网段**一致，而不是 Docker 网关地址。示例假设容器来源为 `172.17.0.0/16`；请按实际 Compose 网络缩小范围。生产请使用独立强密码、最小网段和组织规定的账号管理方式：

```bash
sudo mysql
```

```sql
CREATE DATABASE assistant_superset  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE assistant_admin  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE assistant_demo CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE USER 'assistant'@'172.17.%' IDENTIFIED BY 'REPLACE_WITH_A_STRONG_MYSQL_PASSWORD';
GRANT ALL PRIVILEGES ON assistant_superset.* TO 'assistant'@'172.17.%';
GRANT ALL PRIVILEGES ON assistant_admin.* TO 'assistant'@'172.17.%';
GRANT ALL PRIVILEGES ON assistant_demo.* TO 'assistant'@'172.17.%';
FLUSH PRIVILEGES;
```

`scripts/init_mysql.py` 会读取三个 URI 并执行 `CREATE DATABASE IF NOT EXISTS`。即使提前手工建库，URI 中的账号仍需有相应数据库的 `CREATE` 权限；上面的库级 `ALL PRIVILEGES` 满足这一要求。若改库名，必须同时修改三个 URI 和授权。

不要沿用 `.env.example` 中的 `root/root`。生产也不应把 Superset、Agent 和业务演示库长期共用高权限账号；可在初始化后进一步拆分权限。

## 4. 配置 `infra/.env`

```bash
cd /opt/dataagent-app
cp infra/.env.example infra/.env
chmod 600 infra/.env
```

`.env` 是 Docker Compose env_file，不是 shell 脚本：不要写 `$(openssl ...)`、未加引号的 shell 表达式或 export 语句。用编辑器填入生成的实际值。

可用以下命令分别生成随机值；**每个密钥都要单独生成，不能复用**：

```bash
openssl rand -hex 32
```

### 4.1 必须替换的敏感项

| 变量 | 要求 |
| --- | --- |
| `SUPERSET_SECRET_KEY` | 独立随机长密钥；生产必须稳定保存，轮换会影响 Superset 加密字段和会话 |
| `MCP_JWT_SECRET` | 独立随机长密钥；Superset 与 Agent 通过同一 env_file 共享 |
| `ADMIN_SECRET_KEY` | 独立随机长密钥；用于加密模型 Provider API Key，丢失后已存密钥无法解密 |
| `ADMIN_TICKET_SECRET` | 独立随机长密钥；扩展签发、Agent 验证一次性管理后台 ticket |
| `ADMIN_SESSION_SECRET` | 独立随机长密钥；管理后台会话签名 |
| `SUPERSET_ADMIN_PASSWORD` | 强管理员密码，不能使用示例值 |
| 三个数据库 URI 中的密码 | 使用专用 MySQL 账号；特殊字符必须 URL 编码 |
| `LLM_API_KEY` | **运行期不以此为存储位置**：首次启动且 Provider 表为空时用于 seed，之后加密写入 `assistant_admin.ai_provider.api_key_encrypted`；正常在管理后台更新。如临时写入 `.env`，同样不得提交到版本库或写入文档 |
| `SMTP_PASSWORD` | 真实 SMTP 密码或客户端授权码；不用邮件时也要替换占位配置后再启用发信 |

URI 示例（仅演示格式，不是可用密码）：

```dotenv
SUPERSET_METADATA_URI=mysql+pymysql://assistant:URL_ENCODED_PASSWORD@host.docker.internal:3306/assistant_superset?charset=utf8mb4
DEMO_DB_URI=mysql+pymysql://assistant:URL_ENCODED_PASSWORD@host.docker.internal:3306/assistant_demo?charset=utf8mb4
ADMIN_DB_URL=mysql+pymysql://assistant:URL_ENCODED_PASSWORD@host.docker.internal:3306/assistant_admin?charset=utf8mb4
DEMO_SCHEMA=
```

密码中的 `@`、`:`、`/`、`#`、`?`、 `%` 等字符必须按 URL userinfo 规则编码，否则连接解析会失败。

### 4.2 非敏感基础配置

```dotenv
SUPERSET_HTTP_PORT=8088
AGENT_HTTP_PORT=28088
MCP_HTTP_PORT=25008

REDIS_HOST=redis
REDIS_PORT=6379
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1
WEBDRIVER_BASEURL=http://superset:8088/
WEBDRIVER_BASEURL_USER_FRIENDLY=http://localhost:8088/

MCP_JWT_ALGORITHM=HS256
MCP_JWT_ISSUER=assistant
MCP_JWT_AUDIENCE=superset-mcp
AGENT_TOKEN_TTL=300
AGENT_CORS_ORIGINS=http://localhost:8088,http://127.0.0.1:8088

AGENT_MAX_TOOL_CALLS=16
AGENT_MAX_ROWS=500
AGENT_AUDIT_PATH=/app/runtime/audit.jsonl
AGENT_LOG_DIR=/app/runtime/logs
AGENT_LOG_RETENTION_DAYS=14
AGENT_LOG_LEVEL=INFO

ADMIN_STATIC_DIR=/app/admin_static
ADMIN_SESSION_TTL=1800
ADMIN_COOKIE_SECURE=false
ADMIN_RETENTION_DAYS=90
ADMIN_RETENTION_INTERVAL_SECONDS=86400

SUPERSET_ADMIN_USERNAME=admin
SUPERSET_ADMIN_EMAIL=admin@example.com
```

修改 `SUPERSET_HTTP_PORT` 或对外域名时，必须同步：

- `AGENT_CORS_ORIGINS`：填写浏览器实际使用的完整 Superset origin，不带路径。
- `WEBDRIVER_BASEURL_USER_FRIENDLY`：邮件中用户可访问的 Superset 地址。
- 浏览器默认按“当前 Superset 协议和主机名 + `AGENT_HTTP_PORT`”访问 Agent，因此反向代理必须同时保证该 Agent 地址可访问。

其余可调项以 `infra/.env.example` 和 `agent-service/src/assistant_agent/config.py` 为准，包括用户限额、`LLM_TIMEOUT_SECONDS`、`SUPERSET_SQL_MAX_ROW`、SMTP 和日志保留时间。

### 4.3 模型配置：数据库为主，`.env` 仅用于首次 seed 与后备

**模型密钥的运行期存储位置是 `assistant_admin` 数据库的 `ai_provider` 表**，字段 `api_key_encrypted` 使用 `ADMIN_SECRET_KEY` 加密；后台保存后不会回显明文。`.env` 中的 `LLM_*` 不是日常模型配置来源，只在以下两种情况下使用：

1. Agent 启动时 `ai_provider` 表为空，用 `LLM_MODEL` / `LLM_BASE_URL` / `LLM_API_KEY` seed 默认 Provider/Model，并把密钥加密写入数据库；
2. 数据库中没有启用且可用的运行时模型时，进程回退到 `.env` 的 `LLM_MODEL` 与 `LLM_API_KEY`。

正常聊天按“用户选择的模型（须在员工可用范围内）→ 员工默认模型 → 数据库系统默认模型”解析；只要解析到数据库模型，就不会使用 `.env` 的密钥。**修改 `.env` 的 `LLM_*` 不会覆盖已有 Provider**，日常应在 AI 管理后台“模型配置”中更新。Provider 已存在时，再改 `.env` 也不会重复 seed。

仅做确定性开发验收时可用（前提是数据库中也没有已启用的模型）：

```dotenv
AGENT_MOCK_LLM=true
LLM_MODEL=
LLM_BASE_URL=
LLM_API_KEY=
```

首次初始化时，也可用环境变量预先创建默认 Provider/Model：

```dotenv
AGENT_MOCK_LLM=false
LLM_MODEL=REPLACE_WITH_MODEL_NAME
LLM_BASE_URL=https://REPLACE_WITH_MODEL_ENDPOINT/v1
LLM_API_KEY=REPLACE_WITH_REAL_API_KEY
LLM_DISABLE_THINKING=false
LLM_TIMEOUT_SECONDS=120
```

首次启动并确认后台已出现对应 Provider/Model 后，密钥已加密保存在数据库；后续日常维护只需在管理后台操作。若数据库中没有任何可用模型且 mock 关闭、`.env` 也未配置可用的 `LLM_MODEL`，`/healthz` 会显示 `model_configured=false`，聊天不可用。

## 5. 构建镜像、扩展和管理后台

### 5.1 从源码构建 `dataagent-superset:7.0-mysql`

推荐脚本：

```bash
bash scripts/build-superset.sh
```

它等价于以下核心命令：

```bash
docker build \
  -f infra/Dockerfile.superset7 \
  --target superset-mysql \
  -t dataagent-superset:7.0-mysql \
  superset-7.0.0rc2
```

镜像的实际多阶段构建包括：

1. Node 24 阶段执行 Superset 前端 `npm ci` 和生产构建。
2. Python 3.11 阶段通过 uv 安装 Superset 基础依赖及 postgres/mysql/fastmcp extras。
3. 安装 Playwright 和 Chromium，供报表截图与缩略图使用。
4. 安装 `prophet==1.4.0`，供预测后处理使用。
5. 最终 `superset-mysql` target 安装 PyMySQL 兼容层。

首次构建可能需要较长时间，并需访问 Debian、npm、PyPI 和 Playwright 下载源。Dockerfile 默认使用清华 Debian/PyPI 镜像和 npmmirror；离线或企业镜像环境要先调整这些地址。手动构建时可用 Dockerfile 已声明的参数覆盖 Playwright 下载源，例如：

```bash
docker build \
  --build-arg PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright \
  -f infra/Dockerfile.superset7 \
  --target superset-mysql \
  -t dataagent-superset:7.0-mysql \
  superset-7.0.0rc2
```

### 5.2 安装扩展 CLI

`scripts/build-extension.sh` 默认寻找 `$HOME/.local/bin/superset-extensions`，也可用 `SUPERSET_EXTENSIONS_CLI` 指定绝对路径。为避免污染系统 Python，使用独立 venv：

```bash
python3 -m venv "$HOME/.local/share/assistant-deploy-venv"
"$HOME/.local/share/assistant-deploy-venv/bin/pip" install \
  ./superset-7.0.0rc2/superset-extensions-cli
export SUPERSET_EXTENSIONS_CLI="$HOME/.local/share/assistant-deploy-venv/bin/superset-extensions"
"$SUPERSET_EXTENSIONS_CLI" --help
```

在新 shell 中再次构建扩展前，要重新导出该变量。

### 5.3 构建扩展与管理后台

推荐脚本：

```bash
bash scripts/build-extension.sh
bash scripts/build-admin.sh
```

扩展脚本会安装缺失的前端依赖，执行 CLI `validate`、`build`、`bundle`，生成并复制 `assistant-0.1.0.supx` 到 `infra/extensions/`，同时检查 `assistant-ext/assistant/dist/manifest.json` 和前端 JS 产物。

等价的逐步命令为：

```bash
cd assistant-ext/assistant/frontend
npm ci --registry=https://registry.npmmirror.com
cd ..
"$SUPERSET_EXTENSIONS_CLI" validate
"$SUPERSET_EXTENSIONS_CLI" build
"$SUPERSET_EXTENSIONS_CLI" bundle
mkdir -p ../../infra/extensions
cp assistant-0.1.0.supx ../../infra/extensions/
cd ../..

cd assistant-admin
npm ci --registry=https://registry.npmmirror.com
npm run build
cd ..
```

管理后台构建会先执行 `tsc --noEmit`，再以 base `/admin/` 输出到 `assistant-admin/dist/`。Compose 把该目录只读挂载到 Agent 的 `/app/admin_static`。

> 两个构建脚本只在 `node_modules` 不存在时自动安装依赖。升级 lockfile 后，应先在相应目录手动执行 `npm ci`，再运行构建脚本。

## 6. 初始化并启动全部服务

### 6.1 推荐：一键脚本（开发/验收）

先确认第 4 节配置完成、第 5 节所需 CLI 可用，并保留仓库自带的 `infra/translations/zh-LC-messages.json`，然后：

```bash
cd /opt/dataagent-app
export SUPERSET_EXTENSIONS_CLI="$HOME/.local/share/assistant-deploy-venv/bin/superset-extensions"
bash scripts/init-stack.sh
```

脚本无命令行参数，依次执行：

1. 缺少镜像、扩展 dist 或后台 dist 时构建它们；**已存在时不会自动重建**。
2. 创建 `infra/runtime` 和 `infra/extensions`。
3. 启动 Redis，运行 `init_mysql.py`。
4. 执行 `superset db upgrade`、`superset fab create-admin`、`superset init`。
5. 执行 `seed_superset.py`，创建演示数据、数据集、用户、RLS 和扩展权限。
6. 启动 Superset、MCP、Agent、worker、beat 并等待 HTTP 健康检查。

注意：

- 重复执行会停止当前应用容器再初始化，存在短暂停机。
- 如果旧 `dataagent-superset-1` 占用相同 Superset 宿主端口，脚本会停止旧容器，但不会删除旧数据。
- 脚本会在最终 Ready 输出中显示配置的管理员密码，不要在共享 CI 日志中直接运行生产配置。
- 健康等待循环超时后脚本仍可能继续并打印 Ready，因此必须继续做第 8 节检查。
- 如果 Agent 因宿主 UID 不是 1000 而无法写 `infra/runtime`，先执行 `sudo chown -R 1000:1000 infra/runtime` 再重跑。

### 6.2 逐步手动命令

以下顺序与一键脚本一致，便于生产审计或自定义初始化。先完成第 5 节构建，并执行：

```bash
cd /opt/dataagent-app
mkdir -p infra/runtime infra/extensions
sudo chown -R 1000:1000 infra/runtime
COMPOSE=(docker compose --env-file infra/.env -f infra/docker-compose.yml)

"${COMPOSE[@]}" up -d redis
"${COMPOSE[@]}" run --rm --no-deps \
  -v "$PWD/scripts:/scripts:ro" \
  --entrypoint python superset /scripts/init_mysql.py
"${COMPOSE[@]}" run --rm --no-deps \
  --entrypoint superset superset db upgrade
```

创建管理员和同步权限。下面的 `read_env` 与一键脚本读取 `.env` 的方式一致：

```bash
read_env() {
  grep -E "^$1=" infra/.env | head -n 1 | cut -d= -f2-
}

"${COMPOSE[@]}" run --rm --no-deps --entrypoint superset \
  superset fab create-admin \
  --username "$(read_env SUPERSET_ADMIN_USERNAME)" \
  --firstname Admin --lastname User \
  --email "$(read_env SUPERSET_ADMIN_EMAIL)" \
  --password "$(read_env SUPERSET_ADMIN_PASSWORD)"

"${COMPOSE[@]}" run --rm --no-deps \
  --entrypoint superset superset init
```

管理员已存在时 `fab create-admin` 可能报已存在；确认管理员已存在且密码符合预期后可继续。不要用忽略错误的方式掩盖其他初始化失败。

开发/演示环境执行 seed：

```bash
"${COMPOSE[@]}" run --rm --no-deps --entrypoint python \
  superset /app/pythonpath/seed_superset.py
```

seed 会创建 `sales` 演示表和数据集、`east`/`west` 用户（密码分别与用户名相同）、区域 RLS，以及 Admin 的管理后台扩展权限。生产可以先用它完成首次 RBAC 初始化，但随后必须删除或停用演示账号并替换演示数据；不要在生产保留弱密码账号。

最后启动全部服务：

```bash
"${COMPOSE[@]}" up -d superset superset-mcp superset-worker superset-beat
"${COMPOSE[@]}" up -d --build agent

curl --retry 60 --retry-delay 2 --retry-connrefused --retry-all-errors \
  -fsS "http://localhost:$(read_env SUPERSET_HTTP_PORT)/health"
curl --retry 60 --retry-delay 2 --retry-connrefused --retry-all-errors \
  -fsS "http://localhost:$(read_env AGENT_HTTP_PORT)/healthz"
```

## 7. 中文语言包

正常部署直接使用仓库已有的：

```text
infra/translations/zh-LC-messages.json
```

Compose 将它挂载为 Superset 的 `/app/superset/translations/zh/LC_MESSAGES/messages.json`。`init-stack.sh` 不会自动生成该文件，复制发布包时不能遗漏。

`scripts/build_language_pack.py` 的真实行为是：在**正在运行的 `assistant-superset` 容器**中读取 `messages.po`，用 Babel 转成 jed1.x JSON，再写回宿主文件。当前 Dockerfile 会清理镜像内的 `.po`，所以在新构建镜像中直接运行该脚本通常会找不到 PO。需要从与运行镜像一致的源码重新生成时，可执行：

```bash
cd /opt/dataagent-app
docker cp \
  superset-7.0.0rc2/superset/translations/zh/LC_MESSAGES/messages.po \
  assistant-superset:/app/superset/translations/zh/LC_MESSAGES/messages.po
python3 scripts/build_language_pack.py

docker compose --env-file infra/.env -f infra/docker-compose.yml \
  up -d --force-recreate superset
```

如果 `SUPERSET_SRC` 指向其他目录，PO 的宿主路径也要相应替换。生成后浏览器重新加载页面，再从 Superset 语言菜单切换中文。

## 8. 验证与登录入口

### 8.1 服务检查

```bash
cd /opt/dataagent-app
COMPOSE=(docker compose --env-file infra/.env -f infra/docker-compose.yml)

"${COMPOSE[@]}" ps
curl -fsS http://localhost:8088/health
curl -fsS http://localhost:28088/healthz
"${COMPOSE[@]}" logs --tail=100 \
  superset superset-mcp agent superset-worker superset-beat
```

端口被修改时使用实际端口。`/healthz` 应返回 `status: ok`；真实问答还应确认 `model_configured: true`。

运行仓库验证脚本：

```bash
bash scripts/verify.sh
```

该脚本检查健康、匿名拒绝、管理页、MySQL 连通性并运行 Agent 单元测试；只有 `AGENT_MOCK_LLM=true` 时才额外运行 mock RLS 聊天冒烟。

真实模型全量冒烟：

```bash
python3 scripts/smoke_ai_assistant.py
```

运行前需满足：

- 已配置并启用真实模型。
- 已通过界面或 API 产生至少一条会话；脚本在创建 live 会话之前就会检查历史列表。
- 保留 seed 的演示用户、数据集和默认 `admin` 验收账号；脚本含固定用户、角色及初始对象 ID 的测试假设。

该脚本会创建对话和反馈、临时修改限流配置并测试真实 429，还会调用真实模型产生费用；它不是只读检查，不建议直接对生产数据运行。

### 8.2 浏览器入口

- Superset：`http://localhost:8088/`（或实际域名/端口）。
- 管理员：第 4 节配置的用户名和密码。
- 演示用户：`east/east`、`west/west`，仅用于开发验收。
- AI 管理后台：登录 Admin 后点击助手头部的管理入口；也可访问同源路径 `/extensions/dataagent/assistant/admin-redirect`，由扩展签发一次性 ticket 后跳转。
- Agent 健康：`http://localhost:28088/healthz`。
- MCP：`http://localhost:25008/mcp` 仅用于受控调试，不是浏览器聊天入口。

## 9. 生产部署必须替换或加固的项目

当前代码可直接跑通开发栈，但生产至少需要以下处理：

1. **替换所有开发默认值**：所有随机密钥、管理员密码、MySQL root/root、LLM/SMTP 占位值；关闭 `AGENT_MOCK_LLM`。
2. **移除演示身份与数据**：不得保留 `east/east`、`west/west`；按实际业务重新配置数据库、数据集、角色和 RLS。
3. **HTTPS 与 Cookie**：在反向代理终止 TLS，并将 `ADMIN_COOKIE_SECURE=true`。`infra/superset_config.py` 当前还硬编码 `SESSION_COOKIE_SECURE=False` 和 `TALISMAN_ENABLED=False`，生产应按组织安全基线调整并重建相关容器。
4. **限制网络暴露**：Compose 的端口默认绑定所有宿主接口。MCP 以 debug 模式启动且宿主 `25008` 只供调试，应通过防火墙/Compose 调整禁止公网访问；MySQL、Redis 也不能暴露公网。仅开放经过鉴权和 TLS 的 Superset/Agent 入口。
5. **移除开发运行方式**：Agent compose 命令带 `uvicorn --reload`，并挂载源码；生产应去掉 reload、使用不可变构建产物和固定镜像版本，不要依赖宿主源码热挂载。
6. **数据库连接安全**：`superset_config.py` 当前为本地演示设置 `PREVENT_UNSAFE_DB_CONNECTIONS=False`；生产应评估并恢复安全限制，避免把元数据服务暴露给不可信用户。
7. **配置外部地址**：将 `AGENT_CORS_ORIGINS`、`WEBDRIVER_BASEURL_USER_FRIENDLY` 改为真实域名；必要时设置 `ASSISTANT_ADMIN_URL`，确保 Agent 与管理后台跳转使用同一可访问的 HTTPS 地址。
8. **SMTP**：替换 `SMTP_*`，按服务商要求选择 SSL 或 STARTTLS，再重建 `superset`、`superset-worker`、`superset-beat`。未验证发信前不要创建正式告警。
9. **资源与高可用**：当前是单 Redis、单 Agent、单 Superset/MCP/worker/beat 的本地 Compose 栈，没有自动高可用、外部密钥管理或数据库备份。生产应按可用性目标另做托管 MySQL/Redis、副本、监控和备份设计。
10. **保密运行产物**：保护 `infra/.env`、`infra/runtime/audit.jsonl`、日志与数据库备份。审计和日志可能包含完整业务问题、SQL 与查询结果。
11. **应用加密字段引擎**：当前继承 `SQLALCHEMY_ENCRYPTED_FIELD_ENGINE="aes"`，启动会提示 AES-CBC 无认证告警。全新部署可在首次写入密文前改为 `aes-gcm`；已有部署不能只改配置，必须先备份，再按 Superset 源码 `UPDATING.md` 的 `superset re-encrypt-secrets --engine aes-gcm` 两阶段流程迁移并 recreate。

## 10. 升级代码后的正确构建与重启

**不要只执行 `docker restart`**：它不会重读 `.env`、不会重建镜像；Superset 配置又是单文件 bind mount，编辑后宿主 inode 变化时，restart 仍可能让容器看到旧文件。

通用命令：

```bash
cd /opt/dataagent-app
COMPOSE=(docker compose --env-file infra/.env -f infra/docker-compose.yml)
```

### 10.1 修改 Superset 源码或 `Dockerfile.superset7`

先备份数据库，再显式重建镜像；`init-stack.sh` 发现镜像已存在时不会替你重建：

```bash
bash scripts/build-superset.sh

"${COMPOSE[@]}" stop superset superset-mcp superset-worker superset-beat agent
"${COMPOSE[@]}" run --rm --no-deps \
  --entrypoint superset superset db upgrade
"${COMPOSE[@]}" run --rm --no-deps \
  --entrypoint superset superset init
"${COMPOSE[@]}" up -d --force-recreate \
  superset superset-mcp superset-worker superset-beat agent
```

如果 seed 逻辑也需要同步，在启动前按第 6.2 节重跑 `seed_superset.py`。生产升级前先验证迁移并准备回滚备份。

### 10.2 修改扩展前端或后端

```bash
export SUPERSET_EXTENSIONS_CLI="$HOME/.local/share/assistant-deploy-venv/bin/superset-extensions"
bash scripts/build-extension.sh
"${COMPOSE[@]}" up -d --force-recreate superset superset-mcp
```

### 10.3 修改管理后台前端

```bash
bash scripts/build-admin.sh
"${COMPOSE[@]}" up -d --force-recreate agent
```

### 10.4 修改 Agent Python 代码或依赖

```bash
"${COMPOSE[@]}" up -d --build --force-recreate agent
```

虽然开发 compose 有 `--reload`，升级验收仍应显式重建并 recreate，以确保依赖和镜像一致。

### 10.5 修改 `.env`

按变更影响范围 recreate；不确定时重建全部应用容器：

```bash
"${COMPOSE[@]}" up -d --force-recreate \
  superset superset-mcp superset-worker superset-beat agent
```

端口变更还要同步 CORS、邮件链接、防火墙和反向代理。

### 10.6 只修改 `superset_config.py`

```bash
"${COMPOSE[@]}" up -d --force-recreate \
  superset superset-mcp superset-worker superset-beat
```

Feature flag 在进程启动时读取，之后还要刷新浏览器页面。配置新增权限时，再执行一次 `superset init`。

### 10.7 修改模型、限额等后台配置

管理后台数据库中的 Provider/Model、限额和运行限制按请求读取，通常不需要重启。`.env` 的 `LLM_*` 仅负责首次种子化，不应靠重启覆盖后台已有配置。

## 11. 备份与卸载边界

### 11.1 备份

核心持久数据是三个 MySQL 数据库和 `infra/runtime/`。Redis named volume 主要保存 Celery/缓存状态，不等同于业务数据库。

一致性备份的示例顺序：

```bash
cd /opt/dataagent-app
COMPOSE=(docker compose --env-file infra/.env -f infra/docker-compose.yml)
"${COMPOSE[@]}" stop agent superset superset-mcp superset-worker superset-beat

# 使用有备份权限的账号；密码通过交互提示输入，不写入命令或文档。
mysqldump -h 127.0.0.1 -P 3306 -u REPLACE_WITH_BACKUP_USER -p \
  --single-transaction --routines --triggers \
  --databases assistant_superset assistant_admin assistant_demo \
  > assistant-mysql-backup.sql

tar -C infra -czf assistant-runtime-backup.tgz runtime
"${COMPOSE[@]}" start
```

同时把 `infra/.env` 和部署密钥放入加密备份或密钥管理系统。尤其要保留 `SUPERSET_SECRET_KEY` 和 `ADMIN_SECRET_KEY`，否则恢复数据库后也可能无法解密已存连接信息或模型 API Key。备份文件本身包含敏感数据，应加密、限制访问并定期做恢复演练。

### 11.2 停止与卸载

```bash
COMPOSE=(docker compose --env-file infra/.env -f infra/docker-compose.yml)
"${COMPOSE[@]}" down
```

`down` 删除本项目的容器和默认网络，但保留：

- 宿主 MySQL 三个数据库；
- `infra/runtime/`；
- 镜像和构建产物；
- Compose named volume `redis_data`。

`${COMPOSE[@]} down -v` 会额外删除 Redis volume；不要在需要该数据时使用。删除 MySQL 数据库、`infra/runtime`、镜像或源码目录都是独立的手工操作，当前没有一键卸载/清库脚本。执行任何 `DROP DATABASE` 或目录删除前先完成备份并确认环境，避免误删同宿主上的其他系统数据。

## 12. 常见故障

### `superset source tree not found`

默认源码目录不完整或位置不对。确认 `setup.py` 与 `superset-frontend/` 存在，或使用 `SUPERSET_SRC=/absolute/path ... bash scripts/build-superset.sh`。

### `superset-extensions CLI not found`

确认 Python 3.11+、venv 安装成功，并把 `SUPERSET_EXTENSIONS_CLI` 设为可执行文件的绝对路径。还要检查 npm 至少为 10.8.2。

### 管理后台构建报 Node 版本错误

Vite 8 要求 Node `^20.19.0 || >=22.12.0`。使用 Node 22.12+；lockfile 更新后在对应目录重新执行 `npm ci`。

### Docker 构建卡在 npm、PyPI、Chromium 或 prophet 下载

检查出站网络、DNS、代理和企业镜像源。当前 Dockerfile使用国内镜像地址，但仍需网络可达；Playwright 可在手动 `docker build` 时通过 `--build-arg PLAYWRIGHT_DOWNLOAD_HOST=...` 覆盖。

### MySQL `Access denied`、连接超时或 `CREATE DATABASE` 失败

- URI 主机必须是 `host.docker.internal`，不是容器内的 `127.0.0.1`。
- 检查 MySQL bind-address、3306 防火墙、Docker 网关对应的账号 host 授权。
- 检查密码 URL 编码和库名。
- URI 账号必须能连接并执行 `CREATE DATABASE IF NOT EXISTS`；提前建库不等于可以去掉所有 CREATE 权限。
- 用 `bash scripts/verify.sh` 中的 MySQL 检查或直接在 Agent 容器测试连接。

### Agent 写审计或日志报权限错误

compose 中 Agent 以 UID/GID `1000:1000` 运行。执行：

```bash
sudo chown -R 1000:1000 infra/runtime
docker compose --env-file infra/.env -f infra/docker-compose.yml \
  up -d --force-recreate agent
```

### 端口被占用

```bash
ss -ltnp | grep -E ':(8088|28088|25008)\b'
```

停止占用者，或修改 `.env` 的三个宿主端口。端口改变后同步 CORS、邮件链接和代理；容器内端口保持 8088/28088/5008，不要随意改动。

### 修改配置或密钥后没有生效

不要只 `docker restart`。按第 10 节使用 `up -d --force-recreate`；Agent 依赖变化还要加 `--build`。浏览器再强制刷新。

### 页面没有助手或管理入口 403

- 检查 `assistant-ext/assistant/dist/manifest.json` 是否存在并重新构建扩展。
- 开发 seed 是否成功执行，用户是否有扩展读取权限；管理入口要求 Superset Admin 角色。
- 检查 Agent `/healthz`、`/api/me`、可用 AI 员工和模型配置。
- 管理 ticket 要求 Superset 与 Agent 使用相同 `ADMIN_TICKET_SECRET`、issuer/audience，并保证机器时间同步。
- `ADMIN_COOKIE_SECURE=true` 时不能通过纯 HTTP 建立安全管理会话。

### 中文切换后语言包 404 或界面回退英文

确认宿主 `infra/translations/zh-LC-messages.json` 存在且为合法 JSON，recreate Superset 后刷新页面。重新生成语言包时注意当前镜像可能已删除 PO，按第 7 节从匹配源码复制 PO 后再运行脚本。

### `/healthz` 显示模型未配置

真实模式下先通过管理后台配置启用的 Provider 和默认 Model，或首次启动前正确填写 `LLM_*`。已有 Provider 后改 `.env` 不会自动更新数据库；不要为了修模型配置盲目删除数据库。

### 报表邮件或截图失败

检查 worker/beat 是否运行、Redis 是否可达、SMTP SSL/STARTTLS 是否与服务商匹配，以及两个 WEBDRIVER 地址是否分别从容器和用户浏览器可访问。修改后 recreate `superset`、`superset-worker`、`superset-beat`。镜像中的 Playwright/Chromium 已安装，但仍需检查容器网络与邮件日志。

### 初始化脚本显示 Ready，但服务不可用

一键脚本的健康等待不会在超时后强制退出。继续查看 `docker compose ps`、容器日志和两个健康端点，不要只依据 Ready 横幅判断部署成功。

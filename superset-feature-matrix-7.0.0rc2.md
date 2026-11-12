# Superset 7.0.0rc2 与悬浮分析助手可控制参数矩阵

核对日期：**2026-10-31**。

## 核对口径与生效方式

- 本表直接依据源码、`infra/superset_config.py`、`infra/docker-compose.yml`、助手源码，以及对运行容器和 `assistant_admin` 运行库的只读查询整理；未使用既有矩阵或项目交接文档。
- 下文 `config.py` 指 `superset-7.0.0rc2/superset/config.py`；`mcp_config.py` 指 `superset-7.0.0rc2/superset/mcp_service/mcp_config.py`；`infra` 指 `infra/superset_config.py`。
- **“当前值”优先表示运行中进程/运行库的实际值**，不是仅写在宿主文件里的目标值。敏感连接串只保留协议、主机、端口和库名；密码、API Key、secret 统一只写“已配置/未配置”。
- Feature flag 由 `FeatureFlagManager.init_app()` 在进程启动时合并 `DEFAULT_FEATURE_FLAGS` 与 `FEATURE_FLAGS` 并保存快照（`superset/utils/feature_flag_manager.py:41-61`）。本项目未配置动态 flag callback；修改后需 **recreate `superset`、`superset-mcp`、`superset-worker`、`superset-beat`**，并刷新浏览器，不是热生效。
- `infra/superset_config.py` 是单文件 bind mount。当前容器加载的是旧 inode：宿主新加的 10 个 flag 与 Redis 缩略图缓存**尚未生效**；各行以“待 recreate”标明。
- Agent 环境变量由 `config.py:57-137` 在进程启动时读取。修改 `infra/.env` 后需 **recreate 相应容器**；`docker restart` 不会重读 compose env。后台数据库中的动态设置按请求读取，或通过管理 API 立即应用，无需重建。
- 扩展后端在 Superset 进程启动时加载；前端 `localStorage` 项按浏览器即时生效。扩展前端代码变更需重新构建 `dist` 并重启/recreate Superset，浏览器刷新后加载新资产。

## 1. Superset `DEFAULT_FEATURE_FLAGS` 全量（65/65）

| 参数名 | Superset 默认值 | 当前值 | 值选项（true/false/other） | 作用（干嘛的） | 建议（哪个值） | 配置位置 / 写法 |
| --- | --- | --- | --- | --- | --- | --- |
| AG_GRID_TABLE_ENABLED | false | false（继承） | true/false | 启用 Table V2（AG Grid）图表插件。 | false；若实际使用 Table V2 时间对比则改为 true 并回归 | `config.py:683`；`FEATURE_FLAGS={"AG_GRID_TABLE_ENABLED": True}`；recreate |
| ALERT_REPORT_TABS | false | false（继承） | true/false | Alerts/Reports 的实验性 Tabs UI。 | false | `config.py:686`；infra 未覆盖；recreate |
| CHART_PLUGINS_EXPERIMENTAL | false | **false；宿主已设 true，待 recreate** | true/false | 启用实验性图表插件。 | true（本项目选择；生产前逐图回归） | `config.py:689`；`infra:56` 显式 true；recreate |
| CSV_UPLOAD_PYARROW_ENGINE | false | false（继承） | true/false | CSV 解析改用实验性 PyArrow 引擎，日期/空值行为可能不同。 | false | `config.py:692`；infra 未覆盖；recreate |
| DATASET_FOLDERS | false | **false；宿主已设 true，待 recreate** | true/false | 图表编辑器中把指标和列分组到文件夹。 | true | `config.py:695`；`infra:55` 显式 true；recreate |
| DATE_RANGE_TIMESHIFTS_ENABLED | false | **false；宿主已设 true，待 recreate** | true/false | 除相对时间外，允许日期范围形式的 time shift。 | true | `config.py:699`；`infra:57` 显式 true；recreate |
| **FAB_API_KEY_ENABLED（feature flag）** | false | true（显式） | true/false | 控制用户资料页 API Key 前端面板；后端路由还受同名顶层配置控制。 | true，并与顶层 `FAB_API_KEY_ENABLED=True` 成对配置 | `config.py:703,2117-2122`；`infra:36,78`；recreate 后执行权限同步 |
| <u>GRANULAR_EXPORT_CONTROLS</u> | false | false（继承） | true/false | 将导出权限拆成数据、图片、剪贴板等细粒度权限。 | false，完成角色权限评估后再开 | `config.py:707`；infra 未覆盖；recreate |
| <u>SOFT_DELETE</u> | true | true（继承） | true/false | 图表/看板/数据集软删除及可见性过滤；关闭会恢复已软删记录。 | true；助手写操作回滚依赖它 | `config.py:715`；infra 未覆盖；recreate |
| SEMANTIC_LAYERS | false | false（继承） | true/false | 启用语义层并在数据集旁显示 semantic views。 | false；当前助手面向既有数据集语义层 | `config.py:718`；infra 未覆盖；recreate |
| ENABLE_ADVANCED_DATA_TYPES | false | false（继承） | true/false | 启用高级数据类型支持。 | false，按实际数据库类型需要再开 | `config.py:721`；infra 未覆盖；recreate |
| **ENABLE_EXTENSIONS** | false | true（显式） | true/false | 加载 Superset 扩展，是助手 `.supx`/本地扩展的前置开关。 | true（必需） | `config.py:724`；`infra:35`；recreate |
| MATRIXIFY | false | false（继承） | true/false | 启用 Matrixify 矩阵式图表布局。 | false | `config.py:727`；infra 未覆盖；recreate |
| MOBILE_CONSUMPTION_MODE | false | **false；宿主已设 true，待 recreate** | true/false | 小屏提供只读看板/首页体验，隐藏创作能力。 | true（本项目选择；属 development flag，需移动端回归） | `config.py:732`；`infra:62`；recreate |
| OPTIMIZE_SQL | false | false（继承） | true/false | 实验性 SQL 优化，目前主要是谓词下推。 | false，避免改变查询语义 | `config.py:735`；infra 未覆盖；recreate |
| ~~PRESTO_EXPAND_DATA~~ | false | false（继承） | true/false | 将 Presto 嵌套类型展开为额外列/数组。 | false；当前非 Presto 场景 | `config.py:739`；infra 未覆盖；recreate |
| TABLE_V2_TIME_COMPARISON_ENABLED | false | **false；宿主已设 true，待 recreate** | true/false | Table V2 的时间对比能力。 | true；同时确认 AG Grid Table V2 已启用 | `config.py:742`；`infra:58`；recreate |
| <u>VERSION_HISTORY</u> | true | true（继承） | true/false | Explore/Dashboard 显示版本历史面板；历史写入另受 `ENABLE_VERSIONING_CAPTURE` 控制。 | true | `config.py:748,1704-1709`；infra 未覆盖；recreate |
| <u>ALERT_REPORTS_FILTER</u> | false | false（继承） | true/false | Alerts/Reports 的筛选功能。 | false，按需开启 | `config.py:757`；infra 未覆盖；recreate |
| **ALERT_REPORTS** | false | true（显式） | true/false | 启用告警与报表；需要 Celery worker、beat、邮件和截图配置。 | true（必需） | `config.py:761`；`infra:38`；recreate |
| **ALERT_REPORTS_RETRY** | false | **false；宿主已设 true，待 recreate** | true/false | 失败的报表执行自动重试。 | true | `config.py:764`；`infra:60`；recreate |
| ~~ALERT_REPORT_SLACK_V2~~ | true | false（显式关闭） | true/false | Alerts/Reports 使用 Slack V2 集成。 | false；当前只用 Email | `config.py:773`；`infra:44`；recreate |
| ~~ALERT_REPORT_WEBHOOK~~ | false | false（继承） | true/false | Alerts/Reports 通过 webhook 投递。 | false，未使用 | `config.py:776`；infra 未覆盖；recreate |
| ALLOW_FULL_CSV_EXPORT | false | false（继承） | true/false | 允许表格图表导出全量 CSV，可能造成高内存/计算开销。 | false | `config.py:780`；infra 未覆盖；recreate |
| CACHE_IMPERSONATION | false | false（继承） | true/false | 用户模拟场景按 impersonation key 缓存。 | false，未启用用户模拟 | `config.py:783`；infra 未覆盖；recreate |
| DATE_FORMAT_IN_EMAIL_SUBJECT | false | **false；宿主已设 true，待 recreate** | true/false | 允许邮件主题带日期格式。 | true | `config.py:787`；`infra:61`；recreate |
| DYNAMIC_PLUGINS | false | false（继承） | true/false | 动态加载前端插件。 | false | `config.py:790`；infra 未覆盖；recreate |
| ENABLE_DASHBOARD_SCREENSHOT_ENDPOINTS | false | false（继承） | true/false | 提供看板截图缓存/读取端点，需要 Celery 与缩略图缓存。 | false；当前报表/缩略图不依赖此前端下载入口 | `config.py:794`；infra 未覆盖；recreate |
| ENABLE_DASHBOARD_DOWNLOAD_WEBDRIVER_SCREENSHOT | false | false（继承） | true/false | 通过 Webdriver 下载看板 PDF/JPG，依赖上一项。 | false | `config.py:798`；infra 未覆盖；recreate |
| ~~ENABLE_SUPERSET_META_DB~~ | false | false（继承） | true/false | 允许 `superset://` 元数据库跨库查询，存在额外安全/性能面。 | false | `config.py:804`；infra 未覆盖；recreate |
| ~~ESTIMATE_QUERY_COST~~ | false | false（继承） | true/false | Presto/Postgres/BigQuery 查询成本估算，还需数据库 extra 开关。 | false；当前 MySQL 演示栈不使用 | `config.py:808`；infra 未覆盖；recreate |
| GLOBAL_ASYNC_QUERIES | false | false（继承） | true/false | Dashboard/Explore 经 WebSocket 异步取数，需要 Redis/Celery；开启会派生开启 GTF。 | false | `config.py:813`；`feature_flag_manager.py:24-29,47-72`；recreate |
| IMPERSONATE_WITH_EMAIL_PREFIX | false | false（继承） | true/false | 用户模拟时用邮箱前缀代替用户名。 | false | `config.py:816`；infra 未覆盖；recreate |
| RLS_IN_SQLLAB | false | true（显式） | true/false | SQL Lab 查询经解析/改写应用 RLS。 | true（数据隔离必需；升级后需回归复杂 SQL） | `config.py:820`；`infra:37`；recreate |
| SSH_TUNNELING | false | false（继承） | true/false | 数据库连接允许 SSH tunnel。 | false，未使用 | `config.py:825`；infra 未覆盖；recreate |
| TAGGING_SYSTEM | true | true（继承） | true/false | 资产标签系统。 | true | `config.py:828`；infra 未覆盖；recreate |
| ~~AWS_DATABASE_IAM_AUTH~~ | false | false（继承） | true/false | Aurora/Redshift 等数据库连接使用 AWS IAM/STS。 | false；非 AWS 场景 | `config.py:834`；infra 未覆盖；recreate |
| GLOBAL_TASK_FRAMEWORK | false | false（显式；与默认相同） | true/false | 统一异步任务进度、取消、去重及任务 API/MCP 工具。 | false；`GLOBAL_ASYNC_QUERIES` 开启时会自动变 true | `config.py:837`；`infra:42`；recreate |
| USE_ANALOGOUS_COLORS | false | false（继承） | true/false | 图表使用近似色配色。 | false，按视觉规范选择 | `config.py:840`；infra 未覆盖；recreate |
| DASHBOARD_VIRTUALIZATION | true | true（继承） | true/false | 看板虚拟化渲染以降低大看板前端开销。 | true | `config.py:850`；infra 未覆盖；recreate |
| ALERTS_ATTACH_REPORTS | true | true（继承） | true/false | 告警邮件/Slack 同时带截图与链接；关闭时告警只发链接。 | true | `config.py:861`；infra 未覆盖；recreate |
| ALLOW_ADHOC_SUBQUERY | false | false（继承） | true/false | SQL Lab 允许 ad-hoc 子查询。 | false，按实际需要开放 | `config.py:865`；infra 未覆盖；recreate |
| CACHE_QUERY_BY_USER | false | false（继承） | true/false | Superset 查询缓存按用户隔离。 | false；启用查询缓存且用户结果不同时再评估 true | `config.py:869`；infra 未覆盖；recreate |
| CSS_TEMPLATES | true | false（显式关闭） | true/false | 设置菜单及看板中的 CSS 模板。 | false；未使用 | `config.py:873`；`infra:46`；recreate |
| ENABLE_VIEWERS | false | false（继承） | true/false | 图表/看板的 Subject viewer 显式访问控制。 | false，启用前需完成权限模型评审 | `config.py:878`；infra 未覆盖；recreate |
| ASSIGN_CREATOR_GROUPS_AS_VIEWERS | false | false（继承） | true/false | 新建资产自动共享给创建者所在组；依赖 `ENABLE_VIEWERS`。 | false | `config.py:887`；infra 未覆盖；recreate |
| DASHBOARD_VIRTUALIZATION_DEFER_DATA | false | false（继承） | true/false | 看板与数据同时虚拟化/延迟加载。 | false，大看板性能验证后再开 | `config.py:891`；infra 未覆盖；recreate |
| DATAPANEL_CLOSED_BY_DEFAULT | false | false（继承） | true/false | 图表编辑器默认收起数据面板。 | false | `config.py:895`；infra 未覆盖；recreate |
| DISABLE_EMBEDDED_SUPERSET_LOGOUT | false | false（继承） | true/false | 嵌入式场景隐藏退出按钮。 | false；当前未启用嵌入 | `config.py:900`；infra 未覆盖；recreate |
| <u>DRILL_BY</u> | true | true（继承） | true/false | 图表 drill-by。 | true | `config.py:904`；infra 未覆盖；recreate |
| ~~DRUID_JOINS~~ | false | false（继承） | true/false | Druid JOIN 支持。 | false；非 Druid 场景 | `config.py:908`；infra 未覆盖；recreate |
| **EMBEDDABLE_CHARTS** | true | false（显式关闭） | true/false | 图表“嵌入代码”入口。 | false；未使用 | `config.py:912`；`infra:48`；recreate |
| EMBEDDED_SUPERSET | false | false（继承） | true/false | 嵌入式 Superset/guest token 能力。 | false | `config.py:916`；infra 未覆盖；recreate |
| **ENABLE_TEMPLATE_PROCESSING** | false | **false；宿主已设 true，待 recreate** | true/false | SQL/报表等启用 Jinja 模板处理。 | true（仅给可信作者；本项目已选择） | `config.py:920`；`infra:53`；recreate |
| ESCAPE_MARKDOWN_HTML | false | **false；宿主已设 true，待 recreate** | true/false | Markdown 中 HTML 转义而非渲染。 | true（降低 XSS 面） | `config.py:924`；`infra:54`；recreate |
| FILTERBAR_CLOSED_BY_DEFAULT | false | false（继承） | true/false | 打开看板时默认收起筛选栏。 | false | `config.py:928`；infra 未覆盖；recreate |
| FORCE_GARBAGE_COLLECTION_AFTER_EVERY_REQUEST | false | false（继承） | true/false | 每个请求后强制 GC，用于排查内存问题但损害性能。 | false | `config.py:932`；infra 未覆盖；recreate |
| LISTVIEWS_DEFAULT_CARD_VIEW | false | false（继承） | true/false | 列表页默认卡片视图。 | false | `config.py:936`；infra 未覆盖；recreate |
| <u>MENU_HIDE_USER_INFO</u> | false | false（继承） | true/false | 导航菜单隐藏用户信息。 | false | `config.py:940`；infra 未覆盖；recreate |
| ~~SLACK_ENABLE_AVATARS~~ | false | false（继承） | true/false | 使用 Slack 头像，需调整 CSP。 | false | `config.py:944`；infra 未覆盖；recreate |
| SQLLAB_BACKEND_PERSISTENCE | true | true（继承） | true/false | SQL Lab 查询状态后端持久化。 | true | `config.py:948`；infra 未覆盖；recreate |
| SQLLAB_FORCE_RUN_ASYNC | false | false（继承） | true/false | 不论数据库设置都强制 SQL Lab 经 Celery 异步执行。 | false | `config.py:952`；infra 未覆盖；recreate |
| THUMBNAILS | false | **false；宿主已设 true，待 recreate** | true/false | 图表/看板缩略图计算端点与任务；必须配非 Null 缓存。 | true，并同时应用 Redis `THUMBNAIL_CACHE_CONFIG` | `config.py:957,1283-1287`；`infra:59,67-74`；recreate |
| ENABLE_FACTORY_RESET_COMMAND | false | false（继承） | true/false | 启用 factory-reset CLI，具有破坏性。 | false | `config.py:966`；infra 未覆盖；recreate |
| DRILL_TO_DETAIL | true | true（继承；deprecated） | true/false | 图表钻取明细；该 flag 已弃用，未来会移除。 | true，升级时跟随上游迁移 | `config.py:975`；infra 未覆盖；recreate |

## 2. 本项目实际使用/依赖的重要非 feature-flag Superset 配置

| 参数名 | Superset 默认值 | 当前值 | 值选项（true/false/other） | 作用（干嘛的） | 建议（哪个值） | 配置位置 / 写法 |
| --- | --- | --- | --- | --- | --- | --- |
| SQLALCHEMY_DATABASE_URI / SUPERSET_METADATA_URI | SQLite `~/.superset/superset.db` | `mysql+pymysql://***@host.docker.internal:3306/assistant_superset` | other | Superset 元数据库；Agent 也用同一 URI 只读用户/角色目录。 | 保持 MySQL；生产使用独立最小权限账号 | `config.py:280-295`；`infra:19`；`.env:SUPERSET_METADATA_URI`；recreate 四个 Superset 服务及 agent |
| SECRET_KEY / SUPERSET_SECRET_KEY | 内置 `CHANGE_ME_SECRET_KEY`（不安全） | 已配置 | other | Flask 会话及加密相关根密钥。 | 配置高强度独立密钥并安全轮换 | `config.py:274-278`；`infra:20`；recreate |
| SQLALCHEMY_ENCRYPTED_FIELD_ENGINE | `aes`（AES-CBC，无认证） | `aes`（继承，启动有安全告警） | other（`aes`/`aes-gcm`） | 数据库密码、SSH/OAuth 等应用加密字段的引擎；已有密文不能直接换引擎。 | 新部署用 `aes-gcm`；已有库先备份并执行 re-encrypt 迁移 | `config.py:313-356`；infra 未覆盖；`SQLALCHEMY_ENCRYPTED_FIELD_ENGINE="aes-gcm"`；recreate |
| SQLALCHEMY_ENGINE_OPTIONS | `{}` | `pool_pre_ping=true, pool_recycle=300` | other | 元数据库连接池探活与连接回收。 | 保持 | `config.py:288-295`；`infra:110-117`；recreate |
| APP_NAME | `Superset` | `Superset Assistant` | other | 应用品牌名，也用于 MCP 默认品牌派生。 | 保持 | `config.py:449`；`infra:25`；recreate |
| SUPERSET_LOAD_EXAMPLES | Docker 默认 `yes` | `no` / false | true/false | 初始化时是否加载 Superset 示例数据。 | false | `docker/.env:75`、`docker/docker-init.sh:25,97`；`infra:26`、compose:40；重建初始化容器 |
| REDIS_HOST | 不适用（助手默认：`redis`） | `redis` | other | 本项目构造 Celery/缩略图 Redis 地址的宿主名。 | 保持容器服务名 | `infra:22`；`.env:REDIS_HOST`；recreate |
| REDIS_PORT | 不适用（助手默认：`6379`） | `6379` | other | Redis 容器端口；不映射到宿主。 | 保持 | `infra:23`；`.env:REDIS_PORT`；recreate |
| CeleryConfig.broker_url / CELERY_BROKER_URL | `sqla+sqlite:///celerydb.sqlite` | `redis://redis:6379/0` | other | Celery 任务 broker。 | 保持 Redis db0 | `config.py:1798-1811`；`infra:152-159`；recreate worker/beat/superset |
| CeleryConfig.result_backend / CELERY_RESULT_BACKEND | `db+sqlite:///celery_results.sqlite` | `redis://redis:6379/1` | other | Celery 结果后端。 | 保持 Redis db1 | 同上；`.env:CELERY_RESULT_BACKEND`；recreate |
| CELERYD_CONCURRENCY | 2 | 2 | other | 报表/任务 worker 并发数。 | 2 起步，按 CPU/内存和截图负载调整 | `docker/docker-bootstrap.sh:70-75`；compose:75；recreate worker |
| CACHE_CONFIG | `{"CACHE_TYPE":"NullCache"}` | 继承 NullCache | other | Superset 对象缓存。 | 生产需要缓存时改 Redis；当前可保持 | `config.py:1372-1377`；infra 未覆盖；recreate |
| DATA_CACHE_CONFIG | `{"CACHE_TYPE":"NullCache"}` | 继承 NullCache | other | 数据源元数据和查询结果缓存。 | 保持 NullCache，避免引入跨用户缓存语义；需要时严格评审 | `config.py:1379-1380`；infra 未覆盖；recreate |
| THUMBNAIL_CACHE_CONFIG | NullCache，默认超时 7 天 | **运行中继承 NullCache；宿主 Redis 配置待 recreate** | other | 缩略图存储；NullCache 导致缩略图无法产出。 | Redis db2、7 天 TTL | `config.py:1283-1287`；`infra:67-74`；recreate |
| THUMBNAIL_REDIS_URL | 不适用（助手默认：`redis://redis:6379/2`） | 未显式配置；宿主将使用默认 db2，当前运行尚未加载 | other | 覆盖缩略图 Redis URL。 | 使用独立 db2；生产如加密码用安全注入 | `infra:71-73`；`.env` 可新增；recreate |
| THUMBNAIL_EXECUTORS | `[ExecutorType.CURRENT_USER]` | 继承 CURRENT_USER | other | 以哪个用户身份渲染缩略图。 | 保持 CURRENT_USER，避免越权看到他人数据 | `config.py:1251-1264`；infra 未覆盖；recreate |
| LANGUAGES | `{}`（关闭语言菜单） | `en`、`zh` | other | 可用语言及导航栏语言切换。 | 保持 en/zh，并确保 zh 前端语言包挂载 | `config.py:532-574`；`infra:29-32`、compose:46；recreate + 刷新 |
| BABEL_DEFAULT_LOCALE | `en` | en（继承） | other | 默认界面语言。 | en；中文由用户切换 | `config.py:536`；infra 未覆盖；recreate |
| EXTENSIONS_PATH | `None` | `/app/extensions` | other | 发现打包 `.supx` 的目录。 | 保持 | `config.py:3289-3295`；`infra:83`；recreate |
| LOCAL_EXTENSIONS | `[]` | `["/app/local_extensions/assistant"]`（目录存在时） | other | 从本地目录加载开发扩展，优先于同名 `.supx`。 | 开发保持；生产只用受控 `.supx` | `config.py:3289`；`infra:84-88`、compose:44；recreate |
| MCP_AUTH_ENABLED | false | true | true/false | MCP 传输启用 JWT 等认证。 | true（必需） | `mcp_config.py:524-586`、`auth.py:853`；`infra:90`；recreate MCP |
| MCP_RBAC_ENABLED | true | true | true/false | MCP 工具调用执行 FAB RBAC 检查。 | true（不可关闭） | `mcp_config.py:87-89`；`infra:91`；recreate MCP |
| MCP_JWT_ALGORITHM | 未设时认证工厂回退 `RS256` | `HS256` | other | MCP JWT 验签算法。 | 当前共享密钥模式用 HS256；生产可评估非对称算法 | `mcp_config.py:777-822`；`infra:92`；recreate Superset/MCP/agent |
| MCP_JWT_SECRET | 无；启用 JWT 时必须提供一种验签密钥 | 已配置 | other | HS256 的共享验签密钥，扩展签发与 Agent 续签也使用。 | 已配置高强度密钥，禁止写入文档/日志 | `mcp_config.py:574-586`；`infra:93`；recreate相关容器 |
| MCP_JWT_ISSUER | 未配置 | `assistant` | other | JWT `iss` 校验。 | 保持并确保签发/验证一致 | `mcp_config.py:668-683,780`；`infra:94`；recreate |
| MCP_JWT_AUDIENCE | 未配置；认证模式要求配置 | `superset-mcp` | other | JWT `aud` 校验，将 token 绑定到 MCP。 | 保持 | `mcp_config.py:561-565,780`；`infra:95`；recreate |
| MCP_TOKEN_TTL / AGENT_TOKEN_TTL | 不适用（助手扩展默认：300 秒） | 300 秒 | other | 扩展 `/token` 签发的入口 JWT 寿命；Agent 工具调用会续签同类短期凭证。 | 300 秒 | `infra:96`、扩展 `backend/.../api.py:66-82`；recreate |
| FAB_API_KEY_ENABLED（顶层） | false | true | true/false | 注册 FAB API Key REST 路由；与同名 feature flag 独立。 | true；权限同步后仅授所需角色 | `config.py:2117-2122`；`infra:78`；recreate + `superset init` |
| FAB_API_KEY_PREFIXES | `["sst_"]` | 继承 `["sst_"]` | other | FAB API Key 识别前缀。 | 保持 | `config.py:2122`；infra 未覆盖；recreate |
| MCP_API_KEY_ENABLED | `None`，回退跟随顶层 FAB API Key 开关 | false | true/false/other | MCP 是否接受长期 FAB API Key。 | false；助手 MCP 仅接受短期 JWT | `mcp_config.py:189-194,503-521`；`infra:81`；recreate MCP |
| MCP_STATELESS_HTTP | true | true（继承） | true/false | MCP Streamable HTTP 是否每请求使用无状态传输。 | true；多副本且有状态会话时再评估 | `mcp_config.py:69-85`；recreate MCP |
| MCP_STRUCTURED_OUTPUT_ENABLED | false | false（继承） | true/false | 是否输出 MCP `outputSchema/structuredContent`。 | false，验证客户端兼容后再开 | `mcp_config.py:104-109`；recreate MCP |
| MCP_CACHE_CONFIG | `enabled=false`，跨主体共享=false | 继承关闭 | true/false/other | MCP 工具响应缓存；共享缓存命中可能早于逐请求 RBAC。 | 保持 false | `mcp_config.py:331-386`；recreate MCP |
| MCP_RESPONSE_SIZE_CONFIG | 启用；50,000 bytes；列表截断 100 项 | 继承默认 | other | 限制 MCP 响应大小，避免撑爆模型上下文。 | 保持；Agent 侧再做紧凑化 | `mcp_config.py:388-440`；recreate MCP |
| MCP_TOOL_SEARCH_CONFIG | 启用；BM25；每次 5 项；含 schema | 继承默认 | other | 用 `search_tools/call_tool` 渐进披露工具，避免全量 schema 进入上下文。 | 保持 enabled=true、strategy=bm25 | `mcp_config.py:443-500`；recreate MCP |
| TALISMAN_ENABLED | true | false | true/false | Flask Talisman 安全响应头/CSP。 | 本地 false；生产 true 并配置兼容助手 Agent  Origin 的 CSP | `config.py:2756-2808`；`infra:107`；recreate |
| SESSION_COOKIE_SECURE | false | false | true/false | Superset 会话 Cookie 仅经 HTTPS 发送。 | 本地 false；HTTPS 生产 true | `config.py:2863-2865`；`infra:108`；recreate |
| SESSION_COOKIE_HTTPONLY | true | true（继承） | true/false | 禁止前端 JS 读取 Superset 会话 Cookie。 | true | `config.py:2863`；infra 未覆盖；recreate |
| PREVENT_UNSAFE_DB_CONNECTIONS | true | false | true/false | 阻止高风险数据库连接参数/地址。 | 本地演示 false；生产必须 true 并验证演示库仍可连 | `config.py:2891-2893`；`infra:119-120`；recreate |
| ROW_LIMIT | 50000 | 5000 | other | 图表数据请求默认行数上限。 | 5000，按负载调整 | `config.py:177-178`；`infra:123`；recreate |
| SQL_MAX_ROW | 100000 | 5000 | other | 分析数据库查询的全局硬行数上限；Agent 行数也受其约束。 | 5000 | `config.py:1674-1675`；`infra:124`；recreate |
| DEFAULT_SQLLAB_LIMIT | 1000 | 1000（继承） | other | SQL Lab UI 默认 LIMIT。 | 1000 | `config.py:1690-1692`；infra 未覆盖；recreate |
| DISPLAY_MAX_ROW | 10000 | 10000（继承） | other | SQL Lab 浏览器最大展示行数，不影响 CSV 导出。 | 10000 或更低 | `config.py:1685-1688`；infra 未覆盖；recreate |
| SQLLAB_TIMEOUT | 30 秒 | 30 秒（继承） | other | SQL Lab 同步查询超时。 | 30 秒；重查询走异步 | `config.py:1902`；infra 未覆盖；recreate |
| SUPERSET_WEBSERVER_TIMEOUT | 60 秒 | 120 秒 | other | Superset 应用层 Web 请求超时，应与反向代理/Gunicorn 协调。 | 120 秒，同时提高 Gunicorn timeout | `config.py:215-219`；`infra:125`；recreate |
| GUNICORN_TIMEOUT | 60 秒 | 60（未覆盖） | other | Gunicorn worker 请求超时；当前短于 `SUPERSET_WEBSERVER_TIMEOUT`。 | 至少 120，避免 120 秒应用超时被 60 秒 worker 先截断 | `docker/entrypoints/run-server.sh:30-45`；`.env:GUNICORN_TIMEOUT=120`；recreate superset |
| SMTP_HOST | `localhost` | `smtp.163.com` | other | 告警/报表 SMTP 服务器。 | 保持实际服务商地址 | `config.py:2084`；`infra:130`；recreate superset/worker/beat |
| SMTP_PORT | 25 | 465 | other | SMTP 端口。 | 465 配合 SSL | `config.py:2088`；`infra:131`；recreate |
| SMTP_USER | `superset` | 已配置 | other | SMTP 登录用户。 | 已配置 | `config.py:2087`；`infra:132`；recreate |
| SMTP_PASSWORD | 内置占位 `superset` | 已配置 | other | SMTP 密码/客户端授权码。 | 已配置；不得使用登录密码或写入文档 | `config.py:2089`；`infra:133`；recreate |
| SMTP_MAIL_FROM | `superset@superset.com` | 已配置 | other | 邮件发件人。 | 已配置且与服务商要求一致 | `config.py:2090`；`infra:134`；recreate |
| SMTP_STARTTLS | true | false | true/false | SMTP 明文连接后升级 TLS。 | false（当前 465 SSL）；若用 587 则 true | `config.py:2085`；`infra:135`；recreate |
| SMTP_SSL | false | true | true/false | 建立 SMTP SSL 连接。 | true（当前 465）；不要与 STARTTLS 混用 | `config.py:2086`；`infra:136`；recreate |
| SMTP_SSL_SERVER_AUTH | true | true | true/false | 验证 SMTP 服务器证书和系统 CA。 | true | `config.py:2091-2098`；`infra:137`；recreate |
| SMTP_TIMEOUT | 30 秒 | 30 秒 | other | SMTP socket 超时，避免报表任务无限挂起。 | 30 秒 | `config.py:2099-2103`；`infra:138`；recreate |
| EMAIL_REPORTS_SUBJECT_PREFIX | `[Report] ` | `[前缀]` | other | 告警/报表邮件主题前缀。 | 改成有辨识度的正式前缀 | `config.py:2588-2589`；`infra:139-141`；recreate |
| WEBDRIVER_BASEURL | `http://0.0.0.0:8080/`（MCP 模块另有 9001 默认） | `http://superset:8088/` | other | Playwright 容器内访问 Superset 以截图。 | 保持容器服务名 | `config.py:2644-2647`；`infra:144`；recreate worker/superset |
| WEBDRIVER_BASEURL_USER_FRIENDLY | 等于 `WEBDRIVER_BASEURL` | `http://localhost:8088/` | other | 邮件正文给最终用户的 Superset 链接。 | 生产改为外部 HTTPS 地址；改宿主端口时同步 | 同上；`infra:145-147`；recreate |
| WEBDRIVER_WINDOW | 看板 1600×2000；图表 3000×1200；像素比 1 | 继承默认 | other | 报表截图视口与像素密度。 | 保持，按报表版式调整 | `config.py:2630-2635`；infra 未覆盖；recreate worker |
| SCREENSHOT_PLAYWRIGHT_DEFAULT_TIMEOUT | 60000 ms | 60000 ms（继承） | other | Playwright 浏览器上下文默认操作超时。 | 60 秒，慢看板可适度增加 | `config.py:1342-1346`；infra 未覆盖；recreate worker |
| ENABLE_VERSIONING_CAPTURE | true | true（继承） | true/false | 是否写入实体版本历史；关闭则不再产生新历史且不能 Restore。 | true | `config.py:1704-1709`；recreate |
| SUPERSET_VERSION_HISTORY_RETENTION_DAYS | 30 天 | 30（继承） | other | Celery 清理版本历史的保留期；非正数禁用清理。 | 30 或按合规提高到 90 | `config.py:1711-1752`；recreate worker/beat |
| SOFT_DELETE_RETENTION_DAYS | 30 天；0 禁用定时物理清理 | 30（继承） | other | 软删除资产最终物理清理的保留期。 | 至少覆盖助手需要回滚的业务窗口；建议 30/90 | `config.py:1027-1032`；recreate worker/beat |
| SOFT_DELETE_PURGE_DRY_RUN | false（真正清理） | false（继承） | true/false | 软删除清理是否只记录 `would_purge` 而不删除。 | 上线初期可 true 验证；正式清理 false | `config.py:1027-1032`；recreate worker/beat |

## 3. Agent、扩展、管理后台及 compose 环境变量

第 2 节已经列出的共享变量（数据库、Redis/Celery、SMTP、Webdriver、MCP JWT、宿主扩展 token TTL 等）不重复；它们同样属于 `infra/.env` 环境变量覆盖范围。

| 参数名 | Superset 默认值 | 当前值 | 值选项（true/false/other） | 作用（干嘛的） | 建议（哪个值） | 配置位置 / 写法 |
| --- | --- | --- | --- | --- | --- | --- |
| AGENT_MCP_URL | 不适用（助手默认：`http://superset-mcp:5008/mcp`） | 同默认 | other | Agent 访问 MCP 的容器内地址；浏览器不直连。 | 保持 | Agent `config.py:60`；compose:163；recreate agent |
| AGENT_PORT | 不适用（compose 默认：28088） | 28088（容器内） | other | Agent uvicorn 监听端口。 | 保持容器内 28088 | compose:164,172-179；recreate agent |
| AGENT_HTTP_PORT | 不适用（助手默认：28088） | 28088（宿主发布） | other | 浏览器访问 Agent 的宿主端口，也由 token 端点下发。 | 保持；改端口同步防火墙/CORS | `infra:105`、compose:157；recreate agent/superset |
| SUPERSET_HTTP_PORT | 不适用（compose 默认：8088） | 8088 | other | Superset 宿主发布端口。 | 保持；改时同步 CORS 与报表外链 | compose:31；recreate |
| MCP_HTTP_PORT | 不适用（compose 默认：25008） | 25008 | other | MCP 宿主调试端口，容器内仍 5008；不应暴露给不可信网络。 | 保持仅本机/内网调试；生产可不发布 | compose:124；recreate MCP |
| MCP_PORT | 不适用（Superset bootstrap 默认：5008） | 5008 | other | MCP 容器监听端口。 | 保持 | `docker/docker-bootstrap.sh:109-112`；compose:132；recreate MCP |
| AGENT_MAX_TOOL_CALLS | 不适用（助手默认：16） | 运行进程 bootstrap=16；宿主 `.env=100` 尚未加载；动态值 0 覆盖 | other | 环境变量只提供首次/缺省工具调用上限；动态 `agent_limits` 每请求覆盖，0 不限制。 | 动态值设合理正数（如 16/32）；0 仅受控环境 | Agent `config.py:66`、`main.py:1386-1402`；recreate 只改 bootstrap，后台改动热生效 |
| AGENT_MAX_ROWS | 不适用（助手默认：500） | 500 | other | 单次查询工具默认最大返回行数，动态设置可覆盖但不能超过 Superset 硬上限。 | 500 | Agent `config.py:67`、`deps.py:44-50`；recreate改 bootstrap |
| SUPERSET_SQL_MAX_ROW | 不适用（助手默认：5000） | 5000 | other | Agent 侧记录的 Superset 行数硬上限，用于夹紧动态 `max_rows`。 | 与实际 `SQL_MAX_ROW` 保持一致 | Agent `config.py:68-70`、`main.py:1397-1402`；recreate agent |
| AGENT_AUDIT_PATH | 不适用（助手默认：`/app/runtime/audit.jsonl`） | 同默认 | other | 原始审计 JSONL 路径，随审计保留策略归档/清理。 | 保持持久卷内路径 | Agent `config.py:71-73`；recreate agent |
| AGENT_CORS_ORIGINS | 不适用（助手默认：localhost/127.0.0.1:8088） | 两个默认 Origin | other | 浏览器跨域访问 Agent 的允许来源。 | 与 Superset 实际 HTTP/HTTPS Origin 精确一致，不用 `*` 配凭证 | Agent `config.py:74-81`、`main.py` CORS 配置；recreate agent |
| AGENT_MOCK_LLM | 不适用（助手代码默认：true；示例显式 true） | false | true/false | 是否使用 mock 模型；配置真实模型后应关闭。 | false（生产/真实联调） | Agent `config.py:91`；recreate agent |
| LLM_MODEL | 不适用（助手默认：空） | bootstrap=`MiniCPM5-2B`；运行默认模型由数据库覆盖为 `DeepSeek-V4.1-Flash` | other | 仅用于管理库首次 seed provider/model，不是持续热配置来源。 | 保持可 seed 的模型；日常在后台改默认模型 | Agent `config.py:82`、`admin/store.py:261-285`；recreate仅影响首次 seed |
| LLM_BASE_URL | 不适用（助手默认：空） | `https://developer.amd.com.cn/radeon/api/v1`（bootstrap） | other | 首次 seed 的 OpenAI 兼容端点。 | 保持有效端点；日常在 Provider 后台维护 | Agent `config.py:83`；recreate仅影响首次 seed |
| LLM_API_KEY | 不适用（助手默认：空） | 已配置 | other | 首次 seed 时加密保存的模型 API Key。 | 已配置；日常后台更新，永不回显 | Agent `config.py:84`、`admin/store.py:267-275`；recreate仅首次 seed |
| LLM_DISABLE_THINKING | 不适用（助手默认：false） | bootstrap=true；数据库模型逐行覆盖 | true/false | 首次 seed 模型的 `chat_template_kwargs.enable_thinking=false` 行为。 | 按模型能力配置；日常用模型记录控制 | Agent `config.py:85-87`、`agent.py:104-118`；后台热生效 |
| LLM_TIMEOUT_SECONDS | 不适用（助手默认：120） | 120 秒 | other | 模型 HTTP read timeout；连接/写入/池另有固定超时。 | 120；慢模型适度提高并配合前端空闲超时 | Agent `config.py:88-90`、`agent.py` 模型客户端构造；recreate agent |
| ADMIN_DB_URL | 不适用（助手默认：SQLite `/app/runtime/assistant_admin.db`） | 已配置（`mysql+pymysql://***@host.docker.internal:3306/assistant_admin`） | other | 管理后台、会话、审计、用量和动态设置数据库。 | 保持 MySQL；生产独立最小权限账号 | Agent `config.py:92-95`；recreate agent |
| ADMIN_STATIC_DIR | 不适用（助手默认：`/app/admin_static`） | 同默认 | other | 管理后台前端静态文件目录。 | 保持 | Agent `config.py:96-98`、compose:170；重新构建后台并 recreate agent |
| ADMIN_SECRET_KEY | 不适用（助手默认：空） | 已配置 | other | Provider API Key 的 Fernet 加密密钥。 | 高强度独立密钥；轮换需先迁移密文 | Agent `config.py:99`、`admin/crypto.py`；recreate agent |
| ADMIN_TICKET_SECRET | 不适用（助手默认：空） | Superset 与 Agent 均已配置 | other | 60 秒一次性 Admin ticket 的 HS256 密钥。 | 两端保持同一高强度密钥 | `infra:98`、Agent `config.py:100`；recreate superset/agent |
| ADMIN_TICKET_AUDIENCE | 不适用（助手默认：`assistant-admin`） | `assistant-admin` | other | Admin ticket 的 `aud`。 | 两端一致 | `infra:99-101`、Agent `config.py:101-103`；recreate |
| ADMIN_TICKET_ISSUER | 不适用（助手默认：`assistant`） | `assistant` | other | Admin ticket 的 `iss`。 | 两端一致 | `infra:102`、Agent `config.py:104-106`；recreate |
| ADMIN_SESSION_SECRET | 不适用（助手默认：空） | 已配置 | other | 管理后台 HttpOnly 会话签名密钥。 | 高强度独立密钥 | Agent `config.py:107`；recreate agent |
| ADMIN_SESSION_TTL | 不适用（助手默认：1800 秒） | 1800 秒 | other | 管理后台会话有效期。 | 1800 或更短 | Agent `config.py:108`；recreate agent |
| ADMIN_COOKIE_SECURE | 不适用（助手默认：false） | false | true/false | 管理后台会话 Cookie 是否仅 HTTPS。 | 本地 false；HTTPS 生产 true | Agent `config.py:109-111`；recreate agent |
| ADMIN_RETENTION_DAYS | 不适用（助手默认：90） | 90 天 | other | 会话/消息/工具/管理审计与 JSONL 的归档后清理窗口。 | 90 或按合规调整 | Agent `config.py:112-114`、`main.py:473-488`；recreate agent |
| ADMIN_RETENTION_INTERVAL_SECONDS | 不适用（助手默认：86400） | 86400 秒 | other |  retention 循环间隔；0 禁用循环，实际循环最小 60 秒；启动总会清理一次。 | 86400 | Agent `config.py:115-117`、`main.py:410-437,483-491`；recreate agent |
| AGENT_USER_RATE_PER_MINUTE | 不适用（助手默认：20） | bootstrap=20；动态值 0 覆盖 | other | 进程内每用户滑动窗口速率限制 bootstrap；Admin 豁免，0 不限制。 | 生产 20；当前 0 仅限测试 | Agent `config.py:118-120`、`main.py:305-311,1404`；后台热生效 |
| AGENT_USER_DAILY_REQUESTS | 不适用（助手默认：200） | bootstrap=200；动态值 0 覆盖 | other | 每用户每日请求额度 bootstrap；0 不限制。 | 生产 200 或按配额 | Agent `config.py:121-123`；后台热生效 |
| AGENT_USER_DAILY_TOKENS | 不适用（助手默认：1,000,000） | bootstrap/动态均 1,000,000 | other | 每用户每日 token 额度；0 不限制。 | 按成本预算设置，当前 100 万 | Agent `config.py:124-126`；后台热生效 |
| AGENT_USER_DAILY_COST | 不适用（助手默认：5.0） | bootstrap=5.0；动态值 0 覆盖 | other | 每用户每日估算费用额度；0 不限制，依赖模型单价。 | 配置真实模型单价后设正数预算 | Agent `config.py:127-129`、`main.py:1625-1626`；后台热生效 |
| AGENT_LOG_DIR | 不适用（助手默认：`/app/runtime/logs`） | 同默认 | other | `agent.log` 与 `ai-calls.log` 的 UTC 按天轮转目录。 | 保持持久卷内路径 | Agent `config.py:130`、`logging_setup.py:82-172`；recreate agent |
| AGENT_LOG_RETENTION_DAYS | 不适用（助手默认：14） | bootstrap/动态均 14 天 | other | 两类轮转文件保留天数 bootstrap，合法动态范围 1–365。 | 14 或按合规调整 | Agent `config.py:131-133`、`logging_setup.py:70-75,175-209`；后台热生效 |
| AGENT_LOG_LEVEL | 不适用（助手默认：INFO） | INFO | other | Agent 根日志、控制台及 uvicorn 日志级别；AI 调用日志固定 INFO。 | INFO；排障临时 DEBUG | `logging_setup.py:78-96`；recreate agent |
| ASSISTANT_ADMIN_URL | 不适用（助手默认：空） | 空，按当前 host + `AGENT_HTTP_PORT` 推导 `/admin` | other | 扩展 Admin 跳转的完整外部 URL 覆盖。 | 默认同 host 推导；反向代理时填外部 HTTPS URL | `infra:103`、扩展 `backend/.../api.py:50-56`；recreate superset |
| ASSISTANT_AGENT_PORT | 不适用（助手默认：取 `AGENT_HTTP_PORT=28088`） | 28088 | other | `/token` 返回给前端的 Agent 宿主端口。 | 与发布端口一致 | `infra:105`、扩展 `backend/.../api.py:92`；recreate superset |
| DEMO_DB_URI | 不适用（助手默认：空） | 已配置 | other | seed 创建/更新演示数据库连接。 | 生产使用独立只读账号；不需要演示时停止 seed | `infra/seed_superset.py`；仅运行 seed 时读取 |
| DEMO_SCHEMA | 不适用（助手默认：空） | 空 | other | 演示数据 schema 覆盖。 | 空，使用数据库默认 schema | `infra/seed_superset.py:47`；仅 seed 时读取 |
| SUPERSET_ADMIN_USERNAME | 不适用（seed 默认：admin） | admin | other | 初始化管理员用户名。 | 保持或改为组织管理员 | `infra/seed_superset.py:313`；仅初始化/seed |
| SUPERSET_ADMIN_PASSWORD | 不适用（seed 默认：admin，不安全） | 已配置 | other | 初始化管理员密码。 | 高强度；初始化后通过安全流程轮换 | `infra/seed_superset.py:314`；仅初始化/seed |
| SUPERSET_ADMIN_EMAIL | 不适用（seed 默认：admin@example.com） | admin@example.com | other | 初始化管理员邮箱。 | 改成真实管理邮箱 | `infra/seed_superset.py:315`；仅初始化/seed |
| FLASK_APP | 不适用（compose 显式：`superset.app:create_app()`） | 同显式值 | other | Gunicorn/Flask 应用工厂。 | 保持 | compose:37,73,101,130；recreate |
| SUPERSET_CONFIG_PATH | 不适用（compose 显式容器路径） | `/app/pythonpath/superset_config.py` | other | Superset 加载本项目配置的入口。 | 保持 | `config.py:2072`、compose:38,74,102,131；recreate |
| SUPERSET_PORT | 不适用（Superset Docker 默认：8088） | 8088 | other | Gunicorn 容器监听端口。 | 保持 | `docker/entrypoints/run-server.sh:30-32`、compose:39；recreate |
| PYTHONPATH（agent） | 不适用（compose 显式：`/app/src`） | `/app/src` | other | Agent 源码 import 路径。 | 保持 | compose:165；recreate agent |
| HOME（agent） | 不适用（compose 显式：`/app/runtime`） | `/app/runtime` | other | Agent 运行用户 HOME，供库/工具写缓存。 | 保持可写持久目录 | compose:166；recreate agent |
| Docker json-file `max-size` / `max-file` | Docker daemon 决定 | 全部 compose 服务 `50m` / `5` | other | 容器 stdout/stderr 日志轮转，和 Agent 文件日志保留相互独立。 | 保持或按磁盘预算调整 | compose 各服务 `logging.options`；recreate对应服务 |
| Redis `appendonly` | Redis 默认 no | yes（compose command） | true/false | Redis AOF 持久化。 | yes | compose:13；recreate redis（先备份） |
| Agent uvicorn `--reload` | 不适用（助手 compose 开启） | 开启 | true/false | 源码变更自动 reload，适合开发；不是环境变量热加载。 | 开发 true；生产 false 并固定镜像 | compose:172-179；recreate agent |

## 4. 管理后台数据库中的运行时动态设置

以下当前值来自 2026-10-31 对运行库的只读查询。`ai_app_setting` 的全局项和模型/员工配置均由管理 API 修改；除特别说明外，下一次请求即读取，无需重启。

| 参数名 | Superset 默认值 | 当前值 | 值选项（true/false/other） | 作用（干嘛的） | 建议（哪个值） | 配置位置 / 写法 |
| --- | --- | --- | --- | --- | --- | --- |
| `user_limits.rate_per_minute` | 不适用（助手默认：20） | **0（不限制）** | other | 每用户每分钟聊天请求速率；Admin 豁免。 | 生产 20 | `ai_app_setting[key=user_limits]`；`PUT /admin/api/limits`；热生效 |
| `user_limits.daily_requests` | 不适用（助手默认：200） | **0（不限制）** | other | 每用户每日请求数；Admin 豁免。 | 生产 200 或按配额 | 同上；`admin/schemas.py:43-47`；热生效 |
| `user_limits.daily_tokens` | 不适用（助手默认：1,000,000） | 1,000,000 | other | 每用户每日 token 上限。 | 按预算设置 | 同上；热生效 |
| `user_limits.daily_cost` | 不适用（助手默认：5.0） | **0（不限制）** | other | 每用户每日估算成本上限；当前模型单价均为 0，费用估算也为 0。 | 填真实单价后设正数预算 | 同上；热生效 |
| `agent_limits.max_tool_calls` | 不适用（助手默认：16） | **0（不限制）** | other | 单次回答的 Superset/助手工具调用上限；正整数才截断。 | 16/32；0 只用于受测环境 | `ai_app_setting[key=agent_limits]`；`PUT /admin/api/agent-limits`；热生效 |
| `agent_limits.max_rows` | 不适用（助手默认：500） | 500 | other | `query_dataset/run_sql/mcp_call` 单次查询最大行数；夹紧到 `SUPERSET_SQL_MAX_ROW`。 | 500 | 同上；`main.py:1397-1402`；热生效 |
| `log_settings.retention_days` | 不适用（助手默认：14） | 14 | other | `agent.log*` 与 `ai-calls.log*` 保留天数，范围 1–365。 | 14 或按合规调整 | `ai_app_setting[key=log_settings]`；`PUT /admin/api/log-settings`；立即改 handler 并清理超期文件 |
| `knowledge_settings.user_max_entries` | 不适用（助手默认：200） | 200 | other | 每用户生效中的 manual 知识条目上限，0 表示不限制；Admin 不豁免。 | 200 | `ai_app_setting[key=knowledge_settings]`；`PUT /admin/api/knowledge-settings`；热生效 |
| `knowledge_settings.auto_max_entries` | 不适用（助手默认：500） | 500 | other | 每用户 auto 知识条目上限，0 表示不限制；正数超额时按命中/更新时间软删最久未命中项。 | 500 | 同上；热生效 |
| `knowledge_settings.auto_ttl_days` | 不适用（助手默认：90） | 90 | other | auto 条目零命中过期进入回收站；0 不过期。 | 90 | 同上；启动/每日 retention 执行 |
| `knowledge_settings.trash_retention_days` | 不适用（助手默认：30） | 30 | other | 知识回收站保留天数，到期归档后物理删除；0 不清理。 | 30 | 同上；启动/每日 retention 执行 |
| `knowledge_settings.auto_merge_enabled` | 不适用（助手默认：true） | true | true/false | auto 知识按标题 token 重叠归并，且不覆盖 manual 同名条目。 | true | 同上；热生效 |
| 默认模型（`ai_model.is_default`） | 不适用（助手默认：首次 seed 模型，否则无） | **DeepSeek-V4.1-Flash（id=2）** | other | 未选择模型且员工未指定默认时使用的系统模型。 | 保持可用、支持工具且成本合适的模型 | `ai_model`；后台模型配置；每请求热生效 |
| `ai_model.context_window` | 不适用（助手默认：200000） | 4 个模型均 200000 | other | 历史裁剪档位；聊天历史预算为该值 ×55%，最少 4000 token。 | 按真实模型上下限设置，勿虚高 | `ai_model.context_window`；`admin/schemas.py:35`、`main.py:322-326`；热生效 |
| `ai_model.disable_thinking` | 不适用（助手默认：false） | id=4 `deepseek-v4-flash` 为 true，其余 false | true/false | 对模型发送 `chat_template_kwargs.enable_thinking=false`。 | 仅对需要该参数的模型 true | `ai_model.disable_thinking`；`agent.py:104-118`；热生效 |
| `ai_model.reasoning_effort`（库存字段） | 不适用（助手默认：default） | 全部 default | other | 数据库仍保存 default/low/medium/high，但聊天运行时使用请求头选择，不读取该字段作为默认值。 | 保持 default；在聊天端逐请求选择 | `admin/db.py:66-67`、`main.py:266-268`；字段存储热生效但不控制聊天默认 |
| `ai_model.supports_tools` | 不适用（助手默认：true） | 4 个模型均 true | true/false | 向前端声明模型工具能力，辅助模型选择。 | 仅真实支持工具调用的模型 true | `ai_model.supports_tools`；后台模型配置；热生效 |
| `ai_model.input_price_per_m` | 不适用（助手默认：0） | 全部 0 | other | 每百万输入 token 单价，用于用量成本估算和日费用限额。 | 填真实价格 | `ai_model`；后台模型配置；热生效 |
| `ai_model.output_price_per_m` | 不适用（助手默认：0） | 全部 0 | other | 每百万输出 token 单价。 | 填真实价格 | `ai_model`；后台模型配置；热生效 |
| `ai_model.enabled` | 不适用（助手默认：true） | 4 个模型均 true | true/false | 是否出现在用户可选模型及运行时解析范围。 | 只启用验证通过的模型 | `ai_model.enabled`；后台模型配置；热生效 |
| `ai_model.extra_json` | 不适用（助手默认：null） | 全部 null | other | 可存储扩展模型元数据；当前 Agent 运行时不读取它构造模型参数。 | null，避免误以为会透传 | `ai_model.extra_json`、`admin/store.py:241-258`；存储热生效但无运行时作用 |
| `ai_provider.base_url` | 不适用（助手默认：首次 seed 值） | default=AMD Radeon 端点；amdp=AnruiCloud 端点；gzl=GZL 端点 | other | 各模型实际使用的 OpenAI 兼容 API 地址。 | 保持有效 HTTPS 端点 | `ai_provider`；后台 Provider 配置；每请求热生效 |
| `ai_provider.api_key`（加密存储） | 不适用（助手默认：空） | 3 个 Provider 均已配置 | other | Provider 鉴权密钥，Fernet 加密且不回显。 | 已配置并定期轮换 | `ai_provider.api_key_encrypted`；后台 Provider 配置；热生效 |
| `ai_provider.enabled` | 不适用（助手默认：true） | 3 个 Provider 均 true | true/false | 是否允许该 Provider 下模型参与运行时解析。 | 停用故障 Provider | `ai_provider.enabled`；后台 Provider 配置；热生效 |
| `ai_employee.enabled` | 不适用（助手默认：新建 true） | Atlas、Dex=true；Ellis、Lexi、Vera、Viz=false | true/false | AI 员工是否可被用户选择/自动解析。 | 只启用完成权限与工具验证的员工 | `ai_employee.enabled`；后台 AI 员工；热生效 |
| `ai_employee.model_id` | 不适用（助手默认：null=跟随系统默认） | 全部 null | other | 员工默认模型；用户显式选择优先。 | 按员工任务配置；null 可跟随系统 | `ai_employee.model_id`；后台模型设置；热生效 |
| `ai_employee.model_ids` | 不适用（助手默认：null/空=全部启用模型） | 全部 null | other | 员工可用模型白名单。 | 生产按员工能力设置白名单 | `ai_employee.model_ids`；后台模型设置；热生效 |
| `ai_employee.tools` | 不适用（助手默认：null=不限制；[]=无工具） | 6 个员工均为显式工具白名单（非 null） | other | 限制员工可用 MCP/助手工具；空数组是明确禁用全部。 | 坚持最小权限白名单 | `ai_employee.tools`；后台工具页签；热生效 |
| `ai_employee.users` / `roles` | 不适用（助手默认：两者均 null=全员；Admin 恒可用） | 所有员工均配置了用户/角色限制（并非双 null） | other | 员工按用户名/角色的可见与调用授权，二者取并集。 | 按最小范围授权 | `ai_employee.users/roles`；后台员工资料与角色权限；热生效 |
| `ai_employee.can_delegate` | 不适用（助手默认：false；Atlas seed=true） | Atlas=true，其余 false | true/false | 是否允许该员工协调其他员工。 | 仅领导型员工 true | `ai_employee.can_delegate`；后台协调页签；热生效 |
| `ai_employee.delegate_employee_ids` | 不适用（助手默认：null/空=全部可委派员工） | 全部 null；实际仅 Atlas 开启委派 | other | 可委派员工白名单，仍受目标员工启用及当前用户可见性限制。 | Atlas 保持 null 或按需收窄 | `ai_employee.delegate_employee_ids`；热生效 |
| `ai_skill.enabled` | 不适用（助手默认：新建 true） | `region_report`=false | true/false | 是否把技能注册为 `run_skill_<name>` 工具。 | 只启用审核过的技能 | `ai_skill.enabled`；后台技能页；每请求热生效 |
| `ai_user_ai_access.ai_enabled` | 不适用（助手默认：无记录=true） | 无记录，全部用户按默认可用 | true/false | 用户级 AI 助手总开关；关闭后 Agent `/api/*` 拒绝且前端隐藏入口。 | 默认 true，按用户显式关闭 | `ai_user_ai_access`；后台用户页；热生效 |
| `ai_role_default_employee.employee_id` | 不适用（助手默认：无记录=角色下第一个可用员工） | 无记录 | other | 角色默认 AI 员工；无可用员工时助手入口隐藏且聊天拒绝。 | 为生产角色设置已验证的默认员工 | `ai_role_default_employee`；后台角色权限；热生效 |

## 5. 浏览器侧运行参数与用户首选项

这些值不属于 Superset 服务配置；`localStorage` 当前值按浏览器隔离，不能从运行库得到全局唯一值。

| 参数名 | Superset 默认值 | 当前值 | 值选项（true/false/other） | 作用（干嘛的） | 建议（哪个值） | 配置位置 / 写法 |
| --- | --- | --- | --- | --- | --- | --- |
| `window.__SUPERSET_ASSISTANT_AGENT_URL__` | 不适用（助手默认：空） | 无法确认各浏览器是否覆盖；空时同源 host + token 返回的 28088 | other | 强制覆盖 Agent 完整 Base URL。 | 通常留空；特殊反向代理才设置 | 扩展 `frontend/src/api.ts:17-26`；浏览器运行时覆盖，刷新生效 |
| `localStorage.sa-assistant-employee` / `X-Employee-Id` | 不适用（助手默认：空=自动解析） | 按浏览器，未统一读取 | other | 选择 AI 员工；空时按角色默认员工，再退到第一个可用员工。 | 默认自动，用户按需切换 | 扩展 `ChatPanel.tsx:850,879-887,2842`；即时生效 |
| `localStorage.sa-assistant-model` / `X-Model-Id` | 不适用（助手默认：空=跟随员工/系统默认） | 按浏览器，未统一读取 | other | 在当前员工可用模型内选择本次聊天模型。 | 默认跟随；需要对比时显式选择 | 扩展 `ChatPanel.tsx:851,889-897,2859-2860`；即时生效 |
| `localStorage.sa-assistant-reasoning` / `X-Reasoning-Effort` | 不适用（助手默认：default） | 按浏览器，未统一读取 | other | 每次请求选择 default/low/medium/high；default 不发送额外参数。 | default；复杂任务按需 high | 扩展 `ChatPanel.tsx:852,856-877,2868-2872`、Agent `main.py:266-268`；即时生效 |
| `localStorage.sa-assistant-panel-size-v2` | 不适用（助手默认：宽 26%、高 64%） | 按浏览器；允许宽 16–45%、高 30–95%，最小 320×380 | other | 悬浮面板视口比例尺寸。 | 默认比例，用户拖动持久化 | 扩展 `ChatPanel.tsx:165-252`；即时生效 |
| `localStorage.sa-assistant-trigger-pos` | 不适用（助手默认：右边缘、靠近底部、不半隐藏） | 按浏览器 | other | 悬浮球左右边缘、垂直位置和半隐藏状态。 | 默认右侧，用户拖动持久化 | 扩展 `ChatTrigger.tsx:11-41,129-137`；即时生效 |
| 悬浮球半隐藏延迟 `HIDE_DELAY_MS` | 不适用（助手默认：30000ms） | 30000ms | other | 静止后半隐藏；不是用户设置，需改源码调整。 | 30 秒 | 扩展 `ChatTrigger.tsx:13-14,74-80`；重建扩展 |
| 聊天流空闲超时 `STREAM_IDLE_TIMEOUT_MS` | 不适用（助手默认：200000ms） | 200 秒 | other | 流式响应长期无新数据时中断本地等待。 | 200 秒，需大于模型 read timeout | 扩展 `ChatPanel.tsx:96-110`；重建扩展 |
| 普通用户 API 请求超时 `REQUEST_TIMEOUT_MS` | 不适用（助手默认：30000ms） | 30 秒 | other | 非聊天流用户 API 的 `AbortSignal.timeout`。 | 30 秒 | 扩展 `userApi.ts:137-141`；重建扩展 |
| 管理后台 API 请求超时 `REQUEST_TIMEOUT_MS` | 不适用（助手默认：30000ms） | 30 秒 | other | 管理后台普通 API 请求超时。 | 30 秒 | `assistant-admin/src/api.ts:37-55`；重建后台 |
| 后台运行记录过期 `pendingRun.MAX_AGE_MS` | 不适用（助手默认：2 小时） | 2 小时 | other | `sa-assistant-pending-run` 本地恢复记录的最长保留时间。 | 2 小时 | 扩展 `pendingRun.ts:8-9,28-39`；重建扩展 |
| `localStorage.sa-admin-theme` | 不适用（助手默认：auto） | 按浏览器，未统一读取 | other | 管理后台 auto/light/dark 主题。 | auto | `assistant-admin/src/theme.tsx:13-38,198`；即时生效 |

## 6. 覆盖统计、配置漂移与无法确认项

- **Feature flag：65/65（100%）**。源码默认 true 11 个、false 54 个；宿主 `infra/superset_config.py` 显式配置 18 个（true 14、false 4），其余 47 个继承默认。
- **当前运行后端 flag 快照共 65 项：true 12、false 53**（已对 `assistant-superset` 进程实际 `FeatureFlagManager` 复核）；前端 bootstrap 只暴露其中 58 项（true 12、false 46），另外 7 项不下发到前端，不能把前端子集当成后端完整快照。宿主新增且尚待 recreate 的 true 项共 10 个：`ENABLE_TEMPLATE_PROCESSING`、`ESCAPE_MARKDOWN_HTML`、`DATASET_FOLDERS`、`CHART_PLUGINS_EXPERIMENTAL`、`DATE_RANGE_TIMESHIFTS_ENABLED`、`TABLE_V2_TIME_COMPARISON_ENABLED`、`THUMBNAILS`、`ALERT_REPORTS_RETRY`、`DATE_FORMAT_IN_EMAIL_SUBJECT`、`MOBILE_CONSUMPTION_MODE`；recreate 后若按当前源码与宿主文件加载，后端将为 true 22、false 43。
- **缩略图配置漂移**：运行中仍继承 `THUMBNAIL_CACHE_CONFIG=NullCache`；宿主的 Redis db2 配置与 `THUMBNAILS=true` 必须一起 recreate 后才有效。
- **Agent bootstrap 漂移**：运行进程 `AGENT_MAX_TOOL_CALLS=16`，宿主 `.env` 当前为 100；但动态 `agent_limits.max_tool_calls=0` 在每请求覆盖两者，所以当前实际是不限制。不要只改 `.env` 推断线上行为。
- **当前动态默认值**：系统默认模型 `DeepSeek-V4.1-Flash`；4 个启用模型均 200000 context、单价 0；3 个 Provider 均启用且 API Key 已配置；Atlas/Dex 启用；无用户级 AI 禁用记录、无角色默认员工记录。
- 本文件共有 6 个一级内容分区：全量 flag、重要 Superset 非 flag 配置、环境变量、后台动态设置、浏览器运行参数、统计与未确认项。
- **无法统一确认**：各浏览器 `localStorage` 与 `window.__SUPERSET_ASSISTANT_AGENT_URL__` 的实际值；这些不是服务端全局配置，已标为按浏览器/未统一读取。
- **未逐项做秘密强度或可用性验证**：只确认密钥/密码/API Key 是否配置，不读取、不展示秘密，也未真实发信。另行执行的全量冒烟已验证当前默认模型链路（58 passed），不代表其余 Provider、SMTP 或所有密钥均已验证。
- **建议复核项**：`GUNICORN_TIMEOUT=60` 当前短于 `SUPERSET_WEBSERVER_TIMEOUT=120`；生产还应将 `TALISMAN_ENABLED`、`SESSION_COOKIE_SECURE`、`ADMIN_COOKIE_SECURE`、`PREVENT_UNSAFE_DB_CONNECTIONS` 按 HTTPS/安全基线调整，并把当前为 0 的限额恢复为明确预算。

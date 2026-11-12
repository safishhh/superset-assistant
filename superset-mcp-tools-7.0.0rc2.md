# Superset 7.0.0rc2 MCP 与 Agent 自定义工具清单

## 1. 统计口径、源码依据与实测方法

本文按当前源码和当前运行实例重新枚举，区分四种容易混淆的数量：

| 范围 | 当前数量 | 口径 |
|---|---:|---|
| Superset 源码中的具体 MCP 业务工具 | 70 | 扫描 `superset/mcp_service/**/tool/*.py` 的 `@tool` 注册函数，包含 2 个任务工具 |
| 当前运行实例的具体 MCP 业务工具 | **68** | 当前未启用 `GLOBAL_TASK_FRAMEWORK`，`list_tasks`、`get_task_info` 被配置守卫移除 |
| 当前 Admin 身份协议可见名称 | **70** | 68 个具体工具，加搜索 transform 生成的 `search_tools`、`call_tool`；不是 70 个业务工具 |
| Agent 静态入口 | **14 个常规 + 1 个条件委派** | `attach_tools()` 的实际注册代码，而不是后台展示目录；2026-11-01 删 4 个与 MCP 同名的塑形包装（18→14），2026-11-03 再删 `get_dataset_info`（14→13），2026-11-09 新增 `trend_forecast`（13→14），见第 5 节 |
| Agent 动态技能 | 当前管理库 **0 个启用技能（1 个已定义但停用）** | `region_report` 当前 `enabled=false`，不会注册；启用后工具名为 `run_skill_region_report`，每个请求按员工技能配置重建 |
| `propose_write` 动作类型 | **15** | 是同一个 Agent 工具支持的动作，不是另外 15 个 Agent 工具；2026-11-10 新增 `add_native_filter`（14→15，仅新增原生筛选器），见第 8 节 |

实测采用只读目录查询，没有执行写工具：

1. 在 `assistant-agent` 容器内，以当前 Superset Admin 用户通过扩展 `/token` 的身份链签发 300 秒 JWT，token 保留该用户的 `sub` 和 `roles`，不是服务账号提权。
2. 复用项目的 `MCPClient` 调用标准 `tools/list`，实测返回 4 项：`get_instance_info`、`health_check`、`search_tools`、`call_tool`。
3. 调用合成工具 `search_tools(None)`，实测返回 66 项。常驻具体工具不一定出现在搜索结果中，因此再将 `tools/list` 与搜索结果按名称取并集，得到 **68 个具体工具**；加 2 个合成协议工具得到 70 个协议可见名称。
4. 权限逐项取自 MCP `@tool(class_permission_name=..., method_permission_name=...)`；未声明 method 时源码默认是 `read`，所以权限写作 `can_read on <资源>`。读写语义同时参考实现和 `ToolAnnotations`，不仅凭工具名猜测。
5. Agent 工具来自 `tools.py`、`agent.py` 的实际注册；门控来自 `mcp_policy.py`、`write_actions.py`、`deps.py` 和确认/回滚端点。`tool_catalog.py` 只用于分类交叉检查，其 12 个 Agent 展示项不是完整注册表。
6. 动态技能通过只读查询当前 Agent 管理库核实：`region_report` 已定义但 `enabled=false`，所以当前没有启用的 `run_skill_*` 工具。当前已启用员工的 `skill_ids` 均为空；无员工请求会装入全部启用技能，指定员工请求只装入其 `skill_ids` 中的启用技能。

> **可见数量因身份而异。** 68 是本次 Admin 实测的当前运行全集，不代表每个角色都能看到 68 个。目录期和调用期均会按当前用户过滤/鉴权；Guest、受限 principal、可选 token scope 和数据模型元数据隐私设置还可能进一步缩小范围。

## 2. 通用权限与 RLS 口径

- Agent 每次 MCP 调用仍使用当前登录用户的短时 JWT。Superset 的 `mcp_auth_hook`、`check_tool_permission` 和对象/数据访问检查不会因经过 Agent 而消失。
- 权限列写的是源码声明的 FAB 资源权限，例如 `can_read on Dataset`。对象所有者、数据库/数据集访问、数据模型元数据隐私等还可能在工具内部追加检查。
- **RLS 不是目录过滤。** `list_*`、`get_*_info`、布局、标签、角色等只返回元数据时标为“不适用”；只有真正执行数据查询时才标为“按数据集规则”或“取决于底层工具”。
- “按数据集规则”指 Superset 查询链按当前用户应用数据集 RLS/访问控制，并不表示每个数据集一定配置了 RLS 规则。
- 元数据写入本身不是行过滤；若工具同时生成数据预览，预览取数仍受底层数据集规则约束。

## 3. 当前运行中的 68 个 Superset 具体 MCP 工具

**「调用示例」列的口径**：单元格是 `call_tool` 的 `arguments` 值，配合 `name` 填第一列的工具名即可直接调用，例如 `{"name":"query_dataset","arguments":{"request":{"dataset_id":1,...}}}`。示例按当前实例的 `inputSchema` 构造，对象 ID 用演示数据（`database_id=1`、`dataset_id=1` 即 `sales`、`chart_id/dashboard_id=1`；`sales` 的物理列是 `id/order_date/region/category/channel/amount/quantity`，`total_amount`、`count` 是数据集保存指标，只能在语义层工具里用，`execute_sql` 要写 `SUM(amount)`）。**46 个只读工具的示例已在当前实例逐个真实调用通过**（Admin 身份）；写类工具的示例只按 schema 构造、未实际执行，`delete_*`/`restore_*` 用 `identifier: 99`（不存在）避免误删。

### 3.1 系统（5）

| 工具 | 功能说明 | 读/写 | 权限 | RLS | 作用 | 调用示例 |
|---|---|---|---|---|---|---|
| `find_users` | 按条件查找 Superset 用户，供所有者/负责人选择等场景使用 | 读 | 登录保护；无资源级 FAB 权限声明 | 不适用（用户目录） | 用户发现 | `{"request":{"query":"admin","page_size":5}}` |
| `generate_bug_report` | 汇总实例与错误上下文，生成故障报告 | 读 | `protect=False`，明确豁免常规登录保护；无资源级 FAB 声明 | 不适用 | 诊断 | `{"request":{"tool_name":"query_dataset","error_message":"dataset not found","llm_used":"DeepSeek-V4.1-Flash","steps_to_reproduce":"query_dataset 传 dataset_id=999"}}` |
| `get_instance_info` | 返回 Superset 实例、版本、功能等信息 | 读 | 登录保护；无资源级 FAB 权限声明 | 不适用 | 实例识别；常驻工具 | `{"request":{}}` |
| `get_schema` | 获取 MCP 工具/数据结构的 schema 信息 | 读 | 登录保护；无资源级 FAB 权限声明 | 不适用 | 参数与结构发现 | `{"request":{"model_type":"chart"}}` |
| `health_check` | 检查 MCP/Superset 服务健康状态 | 读 | 登录保护；无资源级 FAB 权限声明 | 不适用 | 运维探活；常驻工具 | `{}` |

### 3.2 数据库（2）

| 工具 | 功能说明 | 读/写 | 权限 | RLS | 作用 | 调用示例 |
|---|---|---|---|---|---|---|
| `list_databases` | 列出当前用户可见的数据库连接 | 读 | `can_read on Database` | 不适用（连接目录） | 发现 `database_id` | `{"request":{"page_size":5}}` |
| `get_database_info` | 返回数据库连接、schema/能力等详情 | 读 | `can_read on Database` | 不适用（连接元数据） | SQL 执行前确认连接 | `{"request":{"identifier":1}}` |

### 3.3 数据集（6）

| 工具 | 功能说明 | 读/写 | 权限 | RLS | 作用 | 调用示例 |
|---|---|---|---|---|---|---|
| `list_datasets` | 列出当前用户可见的数据集 | 读 | `can_read on Dataset` | 不适用（数据集目录，不是行过滤） | 数据集发现 | `{"request":{"search":"sales","page_size":5}}` |
| `get_dataset_info` | 返回列、计算列、已保存指标、主时间列等 | 读 | `can_read on Dataset`；另受数据模型元数据隐私控制 | 不适用（语义元数据） | 查询建模 | `{"request":{"identifier":1,"column_fields":["column_name","type","is_dttm","verbose_name"]}}` |
| `query_dataset` | 使用已保存指标、维度、过滤和时间范围查询数据集 | 读 | `can_read on Dataset`；另受数据模型元数据隐私控制 | **按数据集规则，由 Superset 查询链应用** | 无图表的语义层取数 | `{"request":{"dataset_id":1,"metrics":["count"],"columns":["region"],"row_limit":5}}` |
| `create_dataset` | 将数据库物理表注册为数据集 | 写 | `can_write on Dataset`；另有数据库/表访问检查 | 不适用（元数据写入） | 物理数据集登记 | `{"request":{"database_id":1,"table_name":"sales","schema":"assistant_demo"}}` |
| `create_virtual_dataset` | 从 SQL 创建虚拟数据集 | 写 | `can_write on Dataset`；另有 SQL/数据库访问检查 | 建元数据不适用；以后查询按数据集规则 | 虚拟数据集登记 | `{"request":{"database_id":1,"dataset_name":"v_sales","sql":"SELECT region, order_date, amount FROM sales","schema":"assistant_demo"}}` |
| `update_dataset_metric` | 修改数据集已保存指标的表达式、名称或格式等 | 写 | `can_write on Dataset` | 不适用（指标元数据） | 指标维护 | `{"request":{"dataset_id":1,"metric":1,"verbose_name":"订单数"}}` |

### 3.4 语义层（4）

| 工具 | 功能说明 | 读/写 | 权限 | RLS | 作用 | 调用示例 |
|---|---|---|---|---|---|---|
| `list_metrics` | 发现内置数据集或外部 semantic view 的指标 | 读 | `can_read on Dataset`；另受数据模型元数据隐私控制 | 不适用（指标目录） | 语义查询入口 | `{"request":{"dataset_id":1,"page_size":10}}` |
| `get_compatible_dimensions` | 返回与所选指标兼容的维度 | 读 | `can_read on Dataset`；另受数据模型元数据隐私控制 | 不适用（兼容性元数据） | 避免无效维度组合 | `{"request":{"dataset_id":1,"selected_metrics":["total_amount"]}}` |
| `get_compatible_metrics` | 返回与所选维度兼容的指标 | 读 | `can_read on Dataset`；另受数据模型元数据隐私控制 | 不适用（兼容性元数据） | 避免无效指标组合 | `{"request":{"dataset_id":1,"selected_dimensions":["region"]}}` |
| `get_table` | 查询内置数据集或外部 semantic view，返回表格数据 | 读 | `can_read on Dataset`；外部 view 还执行 `raise_for_access()`；另有元数据隐私控制 | 内置数据集按数据集规则；外部 view **取决于底层语义层/数据源实现** | 统一语义取数 | `{"request":{"dataset_id":1,"metrics":["total_amount"],"dimensions":["region"],"row_limit":5}}` |

### 3.5 图表与 Explore（12）

| 工具 | 功能说明 | 读/写 | 权限 | RLS | 作用 | 调用示例 |
|---|---|---|---|---|---|---|
| `list_charts` | 列出当前用户可见图表 | 读 | `can_read on Chart` | 不适用（图表目录） | 图表发现 | `{"request":{"page_size":5}}` |
| `get_chart_info` | 返回图表配置、数据集、所有者等详情 | 读 | `can_read on Chart` | 不适用（图表元数据） | 修改/预览前检查 | `{"request":{"identifier":1,"select_columns":["slice_name","viz_type","params"]}}` |
| `get_chart_type_schema` | 返回图表类型及配置 schema | 读 | `can_read on Chart` | 不适用 | 构造图表配置 | `{"chart_type":"big_number","include_examples":true}` — 唯一不带 `request` 包装的工具 |
| `get_chart_data` | 执行图表查询并返回 JSON/CSV/Excel 数据 | 读 | `can_read on Chart`；另校验图表数据集访问 | **按图表底层数据集规则** | 图表取数与导出 | `{"request":{"identifier":1,"limit":5,"format":"json"}}` |
| `get_chart_preview` | 生成 URL、ASCII、表格或 Vega-Lite 预览 | 读（URL 模式不取数，其余模式查询） | `can_read on Chart`；另校验数据集访问 | 数据预览按底层数据集规则；纯 URL 不适用 | 不保存对象地检查图表 | `{"request":{"identifier":1,"format":"url"}}` |
| `get_chart_sql` | 返回图表实际查询 SQL | 读 | `can_execute_sql_query on SQLLab` | 不适用（SQL 文本） | 解释/调试查询 | `{"request":{"identifier":1}}` |
| `generate_chart` | 根据数据集和配置生成图表；可预览或保存 | 写（`save_chart=true`）/预览 | 源码声明 `can_read on Chart`；保存路径另有对象/数据访问检查 | 预览按数据集规则；保存元数据本身不适用 | 建图 | `{"request":{"dataset_id":1,"chart_name":"区域销售额","save_chart":false,"generate_preview":true,"config":{"chart_type":"bar","y":[{"name":"total_amount","label":"销售额"}],"group_by":[{"name":"region","label":"区域"}]}}}` |
| `update_chart` | 修改已有图表配置/名称，可生成预览或保存 | 写/预览 | 源码声明 `can_read on Chart`；更新路径另有对象访问检查 | 预览按数据集规则；保存元数据本身不适用 | 改图 | `{"request":{"identifier":1,"chart_name":"新名称"}}` |
| `update_chart_preview` | 更新缓存中的未保存 `form_data` 并生成预览，不保存图表 | 预览/临时缓存 | `can_write on Chart` | 预览取数按数据集规则 | 交互式改图预览 | `{"request":{"dataset_id":1,"config":{"chart_type":"line","temporal_column":"order_date","y":[{"name":"total_amount"}]}}}` |
| `delete_chart` | 删除图表；是否软删除取决于实例配置 | 写 | 源码声明 `can_read on Chart`；删除路径另有对象访问检查 | 不适用（元数据删除） | 图表回收/删除 | `{"request":{"identifier":99}}` |
| `restore_chart` | 从回收状态恢复图表 | 写 | 源码声明 `can_read on Chart`；恢复路径另有对象访问检查 | 不适用 | 图表恢复 | `{"request":{"identifier":99}}` |
| `generate_explore_link` | 根据图表配置生成 Explore 链接和临时表单状态 | 读/临时链接，不保存图表 | `can_read on Explore` | 不适用（仅生成链接；打开后的查询另受控制） | 跳转交互式探索 | `{"request":{"dataset_id":1,"config":{"chart_type":"bar","y":[{"name":"total_amount","aggregate":"SUM"}],"group_by":[{"name":"region"}]}}}` |

> 多个图表写工具的 decorator 没显式写 `method_permission_name="write"`，因此源码默认权限确实是 `can_read on Chart`。这里保留真实声明，不把它擅自改成 `can_write`；这不等于任何只有读权限的角色都必然能完成对象写入，工具内部和对象层检查仍可能拒绝。

### 3.6 看板（15）

| 工具 | 功能说明 | 读/写 | 权限 | RLS | 作用 | 调用示例 |
|---|---|---|---|---|---|---|
| `list_dashboards` | 列出当前用户可见看板 | 读 | `can_read on Dashboard` | 不适用（看板目录） | 看板发现 | `{"request":{"page_size":5}}` |
| `get_dashboard_info` | 返回看板标题、图表、筛选和发布等详情 | 读 | `can_read on Dashboard` | 不适用（看板元数据） | 看板检查 | `{"request":{"identifier":1}}` |
| `get_dashboard_layout` | 返回看板布局/位置结构 | 读 | `can_read on Dashboard` | 不适用 | 布局分析 | `{"request":{"identifier":1}}` |
| `get_dashboard_datasets` | 返回看板图表引用的数据集 | 读 | `can_read on Dashboard` | 不适用（引用关系元数据） | 影响面分析 | `{"request":{"identifier":1}}` |
| `generate_dashboard` | 用一组图表创建看板 | 写 | 源码声明 `can_read on Dashboard`；创建路径另有对象访问检查 | 不适用（元数据写入） | 建板 | `{"request":{"chart_ids":[1],"dashboard_title":"验证用看板"}}` |
| `update_dashboard` | 更新看板布局、主题、CSS 或元数据 | 写 | `can_write on Dashboard` | 不适用 | 看板维护 | `{"request":{"identifier":1,"description":"验证"}}` |
| `duplicate_dashboard` | 复制看板，可选择是否复制图表 | 写 | `can_write on Dashboard` | 不适用 | 看板复用 | `{"request":{"dashboard_id":1,"dashboard_title":"验证副本"}}` |
| `add_chart_to_existing_dashboard` | 将已有图表加入看板/标签页 | 写 | 源码声明 `can_read on Dashboard`；另有对象访问检查 | 不适用 | 看板组装 | `{"request":{"dashboard_id":1,"chart_id":1}}` |
| `remove_chart_from_dashboard` | 从看板布局移除图表，不等于删除图表 | 写 | `can_write on Dashboard` | 不适用 | 看板拆卸 | `{"request":{"dashboard_id":1,"chart_id":1}}` |
| `manage_native_filters` | 新增、修改、删除或重排看板原生筛选器（助手仅开放新增，走 `propose_write` 的 `add_native_filter`，见 7.2/8） | 写 | `can_write on Dashboard` | 不适用（筛选器配置；实际筛选查询另按数据集规则） | 看板筛选维护 | `{"request":{"dashboard_id":1,"add":[{"name":"区域","filter_type":"filter_select","dataset_id":1,"column":"region"}]}}` |
| `manage_dashboard_certification` | 设置或清除看板认证信息 | 写 | `can_write on Dashboard` | 不适用 | 认证管理 | `{"request":{"identifier":1,"certified_by":"验证","certification_details":"验证"}}` |
| `manage_dashboard_owners` | 管理看板所有者 | 写 | `can_write on Dashboard` | 不适用 | 所有权管理 | `{"request":{"identifier":1,"add_owner_ids":[1]}}` |
| `manage_dashboard_roles` | 管理看板访问角色 | 写 | `can_write on Dashboard` | 不适用（这是访问配置，不是行过滤） | 看板授权 | `{"request":{"identifier":1,"add_role_ids":[1]}}` |
| `delete_dashboard` | 删除看板；软删除能力取决于实例配置 | 写 | 源码声明 `can_read on Dashboard`；另有对象访问检查 | 不适用 | 看板回收/删除 | `{"request":{"identifier":99}}` |
| `restore_dashboard` | 从回收状态恢复看板 | 写 | 源码声明 `can_read on Dashboard`；另有对象访问检查 | 不适用 | 看板恢复 | `{"request":{"identifier":99}}` |

### 3.7 SQL Lab（3）

| 工具 | 功能说明 | 读/写 | 权限 | RLS | 作用 | 调用示例 |
|---|---|---|---|---|---|---|
| `execute_sql` | 通过统一 `Database.execute()` 执行 SQL；MCP 自身阻止破坏性 DDL | 读/写（原生能力不止 SELECT；Agent 另行限制只读） | `can_execute_sql_query on SQLLab`；另执行数据库/表访问检查 | **强制经过 Superset RLS 注入管线**；对已注册且当前角色配置了规则的数据集表注入谓词，未配规则的表没有行过滤 | 自由 SQL、dry run、模板查询 | `{"request":{"database_id":1,"sql":"SELECT region, SUM(amount) AS total_amount FROM sales GROUP BY region","limit":5,"timeout":30}}` |
| `open_sql_lab_with_context` | 生成带 SQL、数据库和 schema 上下文的 SQL Lab URL | 读/导航 | `can_read on SQLLab` | 不适用（仅打开编辑器） | 转交人工 SQL 工作 | `{"request":{"database_connection_id":1,"schema":"assistant_demo","sql":"SELECT 1"}}` |
| `save_sql_query` | 将 SQL 保存为 Saved Query | 写 | `can_write on SavedQuery`；另检查数据库访问 | 不适用（保存 SQL 元数据） | 查询收藏/复用 | `{"request":{"database_id":1,"label":"验证查询","sql":"SELECT 1"}}` |

### 3.8 查询历史与 Saved Query（4）

| 工具 | 功能说明 | 读/写 | 权限 | RLS | 作用 | 调用示例 |
|---|---|---|---|---|---|---|
| `list_queries` | 列出当前用户可见的查询历史 | 读 | `can_read on Query` | 不适用（查询元数据） | 执行历史发现 | `{"request":{"page_size":5}}` |
| `get_query_info` | 返回查询状态、SQL、结果关联等详情 | 读 | `can_read on Query` | 不适用（查询元数据） | 查询排障 | `{"request":{"identifier":1}}` |
| `list_saved_queries` | 列出已保存查询 | 读 | `can_read on SavedQuery` | 不适用（目录） | Saved Query 发现 | `{"request":{"page_size":5}}` |
| `get_saved_query_info` | 返回已保存查询的 SQL 和连接信息 | 读 | `can_read on SavedQuery` | 不适用（SQL 元数据） | Saved Query 检查 | `{"request":{"identifier":1}}` — 当前实例没有 Saved Query，返回 not found 属正常（参数形状正确） |

### 3.9 告警与报告（2）

| 工具 | 功能说明 | 读/写 | 权限 | RLS | 作用 | 调用示例 |
|---|---|---|---|---|---|---|
| `list_reports` | 列出告警与报告计划 | 读 | `can_read on ReportSchedule` | 不适用（计划目录） | 报告发现 | `{"request":{"page_size":5}}` |
| `get_report_info` | 返回报告/告警计划配置详情 | 读 | `can_read on ReportSchedule` | 不适用（计划元数据） | 报告检查 | `{"request":{"identifier":1}}` |

### 3.10 注解（4）

| 工具 | 功能说明 | 读/写 | 权限 | RLS | 作用 | 调用示例 |
|---|---|---|---|---|---|---|
| `list_annotation_layers` | 列出注解层 | 读 | `can_read on Annotation` | 不适用 | 注解层发现 | `{"request":{"page_size":5}}` |
| `get_annotation_layer_info` | 返回注解层详情 | 读 | `can_read on Annotation` | 不适用 | 注解层检查 | `{"request":{"id":1}}` |
| `list_layer_annotations` | 列出某注解层中的注解 | 读 | `can_read on Annotation` | 不适用 | 注解发现 | `{"request":{"layer_id":1,"page_size":5}}` |
| `get_layer_annotation_info` | 返回单条注解详情 | 读 | `can_read on Annotation` | 不适用 | 注解检查 | `{"request":{"layer_id":1,"annotation_id":1}}` |

### 3.11 标签与主题（5）

| 工具 | 功能说明 | 读/写 | 权限 | RLS | 作用 | 调用示例 |
|---|---|---|---|---|---|---|
| `list_tags` | 列出标签 | 读 | `can_read on Tag` | 不适用 | 标签发现 | `{"request":{"page_size":5}}` |
| `get_tag_info` | 返回标签及其关联信息 | 读 | `can_read on Tag` | 不适用 | 标签检查 | `{"request":{"identifier":1}}` |
| `list_themes` | 列出主题 | 读 | `can_read on Theme` | 不适用 | 主题发现 | `{"request":{"page_size":5}}` |
| `get_theme_info` | 返回主题配置详情 | 读 | `can_read on Theme` | 不适用 | 主题检查 | `{"request":{"identifier":1}}` |
| `create_theme` | 创建主题 | 写 | `can_write on Theme` | 不适用 | 主题创建 | `{"request":{"theme_name":"验证主题","json_data":"{\"token\":{}}"}}` |

### 3.12 用户、角色与 RLS 配置（6）

| 工具 | 功能说明 | 读/写 | 权限 | RLS | 作用 | 调用示例 |
|---|---|---|---|---|---|---|
| `list_users` | 列出用户 | 读 | `can_get on User` | 不适用 | 用户管理查询 | `{"request":{"page_size":5}}` |
| `get_user_info` | 返回用户详情 | 读 | `can_get on User` | 不适用 | 用户检查 | `{"request":{"identifier":1}}` |
| `list_roles` | 列出角色 | 读 | `can_get on Role` | 不适用 | 角色发现 | `{"request":{"page_size":5}}` |
| `get_role_info` | 返回角色及权限详情 | 读 | `can_get on Role` | 不适用 | 权限检查 | `{"request":{"identifier":1}}` |
| `list_rls_filters` | 列出 RLS 规则配置 | 读 | `can_read on Row Level Security` | 不适用（读取的是 RLS 配置元数据） | RLS 规则发现 | `{"request":{"page_size":5}}` |
| `get_rls_filter_info` | 返回单条 RLS 规则详情 | 读 | `can_read on Row Level Security` | 不适用（同上） | RLS 规则检查 | `{"request":{"identifier":1}}` |

## 4. 两个合成协议工具

它们由搜索 transform 生成，不属于上述 68 个具体业务工具。

| 工具 | 功能说明 | 读/写 | 权限 | RLS | 作用 | 调用示例 |
|---|---|---|---|---|---|---|
| `search_tools` | 按关键词搜索调用者可见的 MCP 工具；空查询返回全部可搜索项 | 读 | 当前 MCP 身份；结果按 RBAC/隐私规则过滤 | 不适用 | 渐进式工具发现 | `{"query":"chart"}` — 省略 `query` 或传 `{}` 返回全部 66 项 |
| `call_tool` | 按名称和参数调用具体 MCP 工具 | 取决于目标 | 当前 MCP 身份 + 目标工具调用期 RBAC | 取决于目标工具 | 避免一次性暴露全部 schema | `{"name":"health_check","arguments":{}}` — 参数名是 `name`，不是 `tool_name` |

常驻具体工具可能只出现在 `tools/list`，所以完整枚举必须做并集；只看到 `tools/list` 的 4 项或只搜索 66 项都不是完整业务目录。

源码中另有 `list_tasks`、`get_task_info`（均为 `can_read on Task`），但当前 `GLOBAL_TASK_FRAMEWORK` 未启用，`app.py` 的配置守卫将二者移除，因此不计入当前 68 个。

## 5. Agent 自定义工具：14 个常规静态入口 + 1 个条件入口

下表逐项覆盖实际注册代码。除条件委派和动态技能的特殊门控外，常规工具都会检查 AI 员工白名单和单轮工具预算；调用 Superset 的包装工具还继承宿主 RBAC/RLS。

新增列「在宿主 MCP 之上新增」写明每个工具包装了第 4 节的哪个合成协议工具、在它之上加了什么。**留空表示与 Superset 无关的纯自定义工具**（四个知识库工具读写的是本地 `ai_knowledge` 表）。共同机制：`MCPClient` 每次调用发的是 JSON-RPC `tools/call` 且 `name="call_tool"`（`mcp_client.py`），只有工具发现走 `search_tools` 与标准 `tools/list`，所以下表所有触达 Superset 的包装都物理骑在第 4 节那两个合成工具之上、共用同一份按请求签发的短期 JWT 身份。

> **2026-11-01 收敛**：`list_datasets`、`get_dashboard_info`、`list_dashboards`、`list_charts` 四个与 MCP 同名的"塑形包装"已删除（它们只做参数包裹、字段裁剪和中文错误提示，没有包装层才能做的副作用），模型改用 `mcp_call` 直调同名 MCP 工具。审计里 `ai_tool_call.tool_name` 仍是 MCP 名，所以后台筛选、历史与导出的中文标签、员工白名单语义都不变。**2026-11-03 又删了 `get_dataset_info`**（A/B 实验证明它只剩参数包裹+字段裁剪，14→13），它唯一独有的"强制 `column_fields` + 别名缓存"副作用搬进 `mcp_call`；现在只剩 `query_dataset` 一个包装，理由见表中"作用"列。

| 工具 | 在宿主 MCP 之上新增 | 功能说明 | 读/写 | 权限 | RLS | 作用 |
|---|---|---|---|---|---|---|
| `search_metadata` | 包装宿主**一次** `list_datasets`（`page_size=100`，`select_columns` 含 `metrics`/`columns`/`main_dttm_col`/`description`），**不再逐个 `get_dataset_info`**（2026-11-03 改造，MCP 调用 4→1）。新增：**本地中文匹配打分**（宿主 `search` 只匹配 `table_name`/`schema`/`sql` 等结构字段，中文口径词必然 0 命中，见 `DatasetRestApi.search_columns`；权重 表名 6/数据集说明 5/指标 4/列 3/schema 2，中文取整串 + 2/3-gram、拉丁按 `_` 切词、噪声词过滤，每字段只计一次）、命中前 3 个给详情（列 60/指标 40 上限）、其余候选进 `candidates` 目录、0 命中回退全量目录并警告"不要回答没有数据"、整个目录的中文别名写进 `deps.dataset_labels`、审计走 `_client_unlogged` + 手动 `record_mcp_call` 只存裁剪版 | 一次调用返回可见数据集目录 + 最相关几个的列与指标（含中文口径名与命中依据） | 读 | Agent 白名单（亦接受 `list_datasets` 别名）；底层 Dataset RBAC | 不适用（元数据） | 一站式元数据探索；提示词把它作为数据集发现的首选 |
| `query_dataset` | 包装宿主同名 `query_dataset`，入参在宿主 12 个之外多一个 `chart_type`、少三个缓存控制项。新增：`row_limit` 默认 100 且硬顶 500、再夹到后台可配 `max_rows` 并按同一上限截断；注入 `chart_type`（宿主无此概念，且必须放进**结果**前端才读得到，入参不被 UI 使用）；中文别名三级链 **缓存 → `_probe_dataset_labels()` 向宿主要权威别名 → 才 `translate_labels` 兜底**；把 `data` 归一成 `rows`、列元数据从 8 键压到 3 键（同参数双跑实测模型侧 1115→527 字符，-53%）；改走 `_client_unlogged` + 手动 `record_mcp_call`，审计存宿主全部 13 键 + `labels` + `chart_type`；`total_rows` 大于实际行数时拒绝。2026-11-05 补上宿主本有的 `filters`/`time_column`/`order_by`/`order_desc`（`DatasetFilter` 的 op 用 Literal 照抄宿主 17 个枚举），并删掉写死 `True` 的 `rls_enforced` 字段 | Agent 专用语义查询包装，限制行数并补充中文标签和图表建议 | 读 | Agent 白名单；宿主 `can_read on Dataset` | **按数据集规则** | 常用分析取数；包装层注入 `chart_type`、把 labels 合并进**审计副本**、行数夹到后台可配 `max_rows`，因此不能被 `mcp_call` 取代 |
| `run_sql` | 包装宿主 `execute_sql`。新增：sqlglot **单语句**校验（只读交给宿主与数据库账号；实测宿主**不拦** `SELECT 1; SELECT 2`（返回 `success:true`，顶层 `rows` 只装最后一条）和 `SHOW TABLES`，而危险函数/文件读写宿主已拦：`SLEEP`/`LOAD_FILE` → `Disallowed SQL functions`、`INTO OUTFILE` → 安全解析失败，所以字符串黑名单已删除，只留宿主不做的部分）、`limit` 夹到 `max_rows`、`timeout=30`（与宿主默认值相同，非差异点）、回填 `statements[0].executed_sql`、列名中文（优先复用同轮 `get_dataset_info` 缓存 `_hint_labels`，否则模型翻译）、注入 `chart_type`、审计 `tool_name` 仍记 `execute_sql` | 将只读 SQL 包装为 MCP `execute_sql`，限制行数和默认 30 秒超时 | 读（Agent 限制） | Agent 白名单（亦接受 `execute_sql`）；sqlglot 单语句护栏（只读由宿主 DML/DDL 拦截 + 只读账号保证）；宿主 `can_execute_sql_query on SQLLab` | 强制经过宿主 RLS 注入管线；是否实际过滤取决于被查表的数据集注册与当前角色规则 | 受控自由 SQL |
| `period_compare` | 包装宿主 `query_dataset`。**按基期、本期分别取数再拼接**（`_fetch_rows`，不再一次取整段——同比跨年的空白月份会占满宿主 50KB 响应体积，整段丢掉本期数据，实测 776 行被截到 599 行）；新增：`row_limit=ANALYSIS_ROW_LIMIT`（20000）+ `total_rows` 截断即拒绝、`dimensions` 数组多列交叉、两期天数/有数据天数不一致自动切日历天日均（`basis`/`basis_reason`）、窗口统计（覆盖率/日均/标准差/CV/极值）、Welch t 检验（`ttest_ind_from_stats` + 手算 df）、按 |变化| 排序并点名“影响最大的成员”；分析结果自己落一条 `period_compare` 审计（内部取数走 `_client_unlogged`，历史/导出不会出现三条重复的 `query_dataset`） | 对两个时间段分别取数并计算期间对比 | 读 | Agent 白名单（亦接受 `query_dataset`）；底层 Dataset RBAC | 取决于底层 `query_dataset`，按数据集规则 | 同比/环比类分析 |
| `dimension_contribution` | 包装宿主 `query_dataset`（基期/本期两次取数）。新增：多列交叉分组、贡献额/贡献率/拉动百分点、**同一份数据汇总出各单维度贡献排名**（`dimension_ranking`，零额外取数）、HHI + 归一化 HHI 与 **Top1 超出均分百分点**共同判定集中度（避免两成员 51/49 被误判为主导）、正负抵消比（`1 - |净|/总变动`）、总变化近 0 时警告贡献率失真（可到 ±1000%）、按 |变化| 排序；分析结果自落一条 `dimension_contribution` 审计 | 对维度成员取数并计算贡献度 | 读 | Agent 白名单（亦接受 `query_dataset`）；底层 Dataset RBAC | 取决于底层 `query_dataset` | 贡献结构分析 |
| `structure_effect` | 包装宿主 `query_dataset`（分子/分母两指标同批取回，基期/本期两次）。新增：结构/效率/交互三项比率分解、`dominant` 主导项与占比、`residual` 闭合校验、每成员权重变化与自身效应、前端瀑布图所需输出形状；多列交叉同样支持；自落一条 `structure_effect` 审计 | 分解结构与增长等因素的影响 | 读 | Agent 白名单（亦接受 `query_dataset`）；底层 Dataset RBAC | 取决于底层 `query_dataset` | 结构效应分析 |
| `trend_forecast` | 包装宿主 `query_dataset`（按历史窗口取日聚合）。新增：日历补齐（缺失日按时间线性插值并披露缺口数/覆盖率）、`scipy.stats.linregress` 趋势检验（斜率/R²/ρ 值，按 4 位有效数字避免 p 值被抹成 0）、`STL(period=7, robust)` 趋势/季节强度（Hyndman 口径）与季节振幅、阻尼加法 Holt-Winters、留出最后 `min(7, n//4)` 天做 MAPE 回测并对比**朴素法/季节朴素法**、`simulate(random_errors="bootstrap")` 1000 次取 95% 分位区间（含左右不对称幅度 `skew_ratio`）、未来每日值与合计/日均、30 天历史尾；历史 <14 天、覆盖率 <50% 或方差为 0 时不预测只说明原因；自落一条 `trend_forecast` 审计 | 日粒度趋势预测（趋势检验 + 季节分解 + 回测 + 预测区间） | 读 | Agent 白名单（亦接受 `query_dataset`）；底层 Dataset RBAC | 取决于底层 `query_dataset` | 未来 N 天/下周走势类问题 |
| `mcp_search` | 包装宿主合成 `search_tools` + 标准 `tools/list`。新增：并入 `search_tools` 不返回的常驻 `health_check`/`get_instance_info`、剔除 `search_tools`/`call_tool` 自身防递归、按员工白名单过滤结果、描述截 200 字、仅 `with_schema=true` 时返回 `compact_schema`（宿主原样返回可达 30 万+ 字符 schema） | 合并 `search_tools` 和 `tools/list`，过滤不可发现项并按员工白名单裁剪，可返回压缩 schema | 读 | Agent `mcp_search` 白名单 + 当前用户目录可见性 + 员工目标工具白名单 | 不适用 | Agent 的通用发现入口 |
| `mcp_call` | 包装宿主合成 `call_tool`。新增：`gate_call` 写门控（18 个 `PROPOSE_WRITE_REQUIRED`、`PREVIEW_SAFE` 强制预览参数、6 个 `NOT_SUPPORTED_BY_PROPOSE_WRITE` 回能力边界说明；`manage_native_filters` 按请求内容单独判定：纯新增指去 `add_native_filter`，改/删/重排回能力边界）、目标工具名二次白名单、对 `execute_sql`/`query_dataset`/`get_dataset_info` **改写 arguments**（只读校验 + 行数夹取 + 超时 + 注入 `column_fields`）、`compact_result` 压到 12K 字符与列表 40 项，但 **`get_dataset_info` 完全跳过压缩**（元数据工具的列表就是载荷本身，2026-11-03 按用户要求放开，实测 80 列全给）、labels 并进审计副本、`get_dataset_info` 成功后把中文别名写进 `deps.dataset_labels` | 通用调用入口，执行写操作门控、目标白名单、SQL/行数护栏和结果压缩 | 取决于目标 | 先检查 `mcp_call`，再检查目标工具名，最后由宿主做目标 RBAC | **取决于底层工具** | 调用专用包装之外的 MCP 能力 |
| `save_knowledge` |  | 将提炼后的知识写入当前用户个人知识库，`source="auto"` | 写 | Agent 白名单 + 当前用户名归属/配额校验 | 不适用 | 个人知识沉淀；不是写员工知识库 |
| `search_knowledge` |  | 搜索当前用户个人知识及当前员工知识，合计最多 5 条，标记 `scope=user\|employee` 并记录审计 | 读 | Agent 白名单 + 用户/员工归属范围 | 不适用 | 回答前检索业务口径 |
| `list_knowledge` |  | 只列当前用户个人知识目录，不返回正文 | 读 | Agent 白名单 + 当前用户名归属 | 不适用 | 知识目录浏览 |
| `delete_knowledge` |  | 软删除当前用户个人知识条目，移入回收站 | 写 | Agent 白名单 + 当前用户名与条目归属校验 | 不适用 | 个人知识删除 |
| `propose_write` | 只读侧包装宿主 `get_chart_info`/`get_dashboard_info` 用于采集改前快照（`collect_snapshot`）；本身不调宿主写工具——确认后由 `/api/write-actions/{id}/confirm` 以同一用户身份执行 plan 里的写工具。新增：15 类动作的 plan 构造、改前快照与回滚方案、相同 pending 方案去重、15 分钟过期 | 构造 15 类写方案、采集快照、去重并保存 15 分钟待确认记录，不直接执行 | 写方案，不写 Superset 对象 | Agent `propose_write` 白名单 + 计划主工具/下一步工具白名单；确认后仍做宿主 RBAC | 方案本身不适用；确认后取决于计划工具，预览取数按数据集规则 | 确认、审计、快照和回滚入口 |
| `delegate_to_employee` | 不直接包装宿主工具；嵌套 Agent 复用同一套包装与同一 Superset 用户身份，最终仍经合成 `call_tool` | 将子任务交给当前可委派的另一名 AI 员工，返回最多 6000 字回答 | 读/写取决于嵌套 Agent 实际行为 | **条件注册**：当前员工 `can_delegate` 且 `delegates` 非空；目标须匹配 username/nickname；180 秒超时；嵌套 Agent 不再注册委派 | 取决于嵌套 Agent 实际调用的底层工具 | 多员工协作 |

三个分析包装工具都只向宿主 `query_dataset` 发**一次**请求：`row_limit=ANALYSIS_ROW_LIMIT=20000`，取回基期开始到本期结束的聚合数据，两期切分与计算全部在本地 pandas 完成（`analysis.py`）。若宿主返回的 `total_rows` 大于实际取回行数，工具直接拒绝继续分析，提示缩小日期范围或增加聚合维度，避免对不完整数据算出错误结论。委派使用目标员工的人设、白名单、技能和默认模型，但保持同一 Superset 用户身份，不会借目标员工提升数据权限。

## 6. 动态技能入口

动态工具名为 `run_skill_<name>`。它们不是固定写在 `tool_catalog.py` 中的工具；每次请求都会根据最新启用技能重新注册。

| 工具 | 功能说明 | 读/写 | 权限 | RLS | 作用 |
|---|---|---|---|---|---|
| `run_skill_region_report` | 返回“区域销售报告”技能指令，供模型随后调用其他工具生成区域销售报告/周报/汇总 | 读（只返回指令；后续行为取决于模型调用） | **当前停用、不会注册**；启用后，无员工时装入全部启用技能，有员工时须在 `skill_ids` 中；另受工具预算 | 不适用（技能本身）；后续取决于底层工具 | 当前唯一定义的动态技能，但不是当前可用工具 |

因此按当前配置计算：常规静态入口为 14 个，当前没有 `run_skill_*` 注册；若再有可委派对象才增加 `delegate_to_employee`。后台启用 `region_report` 后，无员工请求才会增加此技能；有员工请求还须把该技能分配给员工。技能管理变化后数量会热变化。

## 7. `mcp_search` / `mcp_call`、白名单与写操作门控

### 7.1 AI 员工工具白名单

`employee_tool_allowed()` 的精确规则：

- `tools is None`：不限制；未选择员工也不限制。
- `tools == []`：全部拒绝，不等于“不限制”。
- 非空列表：工具名精确匹配才允许。
- 部分 Agent 包装提供 MCP 名称别名：`run_sql` 接受 `execute_sql`；`search_metadata` 接受 `list_datasets`；三个分析工具接受 `query_dataset`。
- `propose_write` 除自身外还检查计划的主 `tool` 和 `next_step.tool`。
- `mcp_search` 会过滤结果；`mcp_call` 会同时检查自身和目标工具，避免“发现不到但直接透传”。

### 7.2 通用调用不是写操作绕过通道

- `mcp_call` 禁止再次调用基础设施 `search_tools`、`call_tool`。
- 18 个 `PROPOSE_WRITE_REQUIRED` 工具会被拒绝直调，模型必须改用 `propose_write`；其中 **12 个有对应的确认动作**，另外 **6 个没有**（见下方"当前能力边界"）。`manage_native_filters` 是混合情况：纯新增请求会被指去 `propose_write` 的 `add_native_filter` 动作，带 `update`/`remove`/`reorder`（含显式 `reorder: []`）的请求回能力边界说明。
- 预览白名单会强制改写参数：`generate_chart.save_chart=false`、`update_chart.generate_preview=true`；`update_chart_preview` 和 `generate_explore_link` 本身不保存持久对象，可放行。
- 未识别但名称以 `create_`、`update_`、`delete_`、`restore_`、`duplicate_`、`manage_`、`save_`、`add_`、`remove_`、`set_`、`clear_`、`grant_`、`revoke_`、`import_`、`install_` 等写前缀开头的工具默认拒绝。
- 直调 `execute_sql` 并未简单封死，而是强制使用与 `run_sql` 相同的单条只读 SQL、行数和超时护栏；直调 `query_dataset` 的显式 `row_limit` 会被夹到 Agent 上限。
- 结果压缩上限为总结果 12000 字符、schema 8000 字符、列表 40 项、长字符串 800 字。

**当前能力边界：** `create_dataset`、`create_virtual_dataset`、`create_theme`、`save_sql_query`、`manage_dashboard_owners`、`manage_dashboard_roles` 在"禁止直调"集合中，但 15 个 `propose_write` 动作并不支持它们，因此模型两条路都走不到，**不能把它们描述成"确认后即可执行"**。2026-11-01 修正：`mcp_policy` 对这 6 个工具返回的是"助手不开放、请在 Superset 界面完成"的文案，不再统一回"必须用 propose_write"——此前两者互相矛盾，模型被踢皮球后只能对用户说"我没有这个工具"，看起来像权限没配好。2026-11-10 起 `manage_native_filters` 移出该集合：**新增**已做成 `add_native_filter` 确认动作，`gate_call` 按请求内容分流——纯新增指去 propose_write，改/删/重排仍回能力边界文案。

**要调用它们只有三条路，按推荐顺序：**

| 目标 | 现在怎么做 | 若要走助手，需要补什么 |
|---|---|---|
| 建/改数据集、虚拟数据集、主题、保存 SQL 查询 | 在 Superset 界面完成（Datasets / Themes / SQL Lab → Save） | rc2 的 MCP **没有** `delete_dataset` / `delete_theme` / `delete_saved_query`，新建对象无法经 MCP 回滚，违反"先方案、后确认、可回滚"红线；要放开必须给写执行器增加一条 REST 回滚步骤（如 `DELETE /api/v1/dataset/{id}`）并单独设计 |
| 改看板 owner / 访问角色 | 在 Superset 界面完成 | **产品红线：权限变更一律不做**，不补动作 |
| 看板原生筛选器 | **新增**走助手 `propose_write` 的 `add_native_filter`（2026-11-10 落地，仅 `filter_select`/`filter_time`，回滚＝对返回的 `added_filter_ids` 执行 `remove`）；改/删/重排在看板编辑器完成 | `update / remove / reorder` 仍不做：改前筛选器配置只在 `json_metadata` 里、常规工具读不回，无法快照还原；数值区间等宿主不支持的类型也无法重建 |

### 7.3 确认、执行和回滚

1. `propose_write` 只生成 pending 方案、采集改前快照并写 Agent 管理库，有效期 15 分钟；相同会话中的相同 pending 方案会去重。
2. 用户通过确认卡调用单个或批量确认端点。单个确认要求方案属于当前用户、状态 pending 且未过期；批量确认按顺序执行，失败即停。
3. 执行时重新以当前用户签 300 秒 MCP token，再调用计划中的真实 MCP 工具。宿主 RBAC 在这一步仍会执行；白名单不是宿主权限替代品。
4. 回滚端点支持单步 `{tool, arguments}` 和复合 `{steps: [...]}`。回滚也是实际 MCP 调用，不保证永久删除等不可逆操作能够恢复。

## 8. `propose_write` 支持的 15 种动作

以下动作共享“Agent 白名单 + 用户确认 + 当前用户宿主 RBAC”权限链。它们修改的是 Superset 元数据，RLS 均为“不适用于写入本身”；若另行生成预览/取数，则按底层数据集规则。创建图表的简化类型仅支持 `bar`、`line`、`area`、`pie`、`table`、`big_number`。

| 工具 | 功能说明 | 读/写 | 权限 | RLS | 作用 |
|---|---|---|---|---|---|
| `create_chart`（medium） | 映射到 `generate_chart(save_chart=true, generate_preview=false)` | 写 | 确认后按当前用户执行 `can_read on Chart` 声明及对象检查 | 不适用（元数据写入） | 建图；回滚删除新图 |
| `create_dashboard`（medium） | 映射到 `generate_dashboard` | 写 | 确认后当前用户宿主 Dashboard 权限 | 不适用 | 建板；回滚删除新板 |
| `add_chart_to_dashboard`（medium） | 映射到 `add_chart_to_existing_dashboard` | 写 | 确认后当前用户宿主 Dashboard 权限 | 不适用 | 加图；回滚从看板移除 |
| `create_chart_and_add_to_dashboard`（medium） | 先建图，再加入已有看板或新建看板 | 写（复合） | 主工具和下一步工具均过白名单；确认后逐步宿主鉴权 | 不适用 | 复合建图建板；按逆序回滚，第二步失败会尝试删除已建图 |
| `update_chart`（medium） | 改图表配置或名称，保存 `form_data` 快照 | 写 | 确认后当前用户宿主 Chart 权限 | 不适用；另行预览才按数据集规则 | 改图；尽量恢复等效简化配置，至少可恢复名称 |
| `update_dataset_metric`（high） | 仅允许 expression、verbose_name、description、d3format、warning_text | 写 | `can_write on Dataset` + 确认门控 | 不适用 | 改指标；回滚旧值 |
| `update_dashboard`（medium） | 仅允许 dashboard_title、description、slug、published | 写 | `can_write on Dashboard` + 确认门控 | 不适用 | 改看板；回滚旧值 |
| `duplicate_dashboard`（medium） | 复制看板；确认动作不允许 `duplicate_slices=true` | 写 | `can_write on Dashboard` + 确认门控 | 不适用 | 复制；回滚删除副本 |
| `set_dashboard_certification`（medium） | 映射到 `manage_dashboard_certification`，可设置或清除认证 | 写 | `can_write on Dashboard` + 确认门控 | 不适用 | 认证；回滚旧认证 |
| `restore_chart`（medium） | 恢复回收状态图表 | 写 | 当前用户宿主 Chart 权限 + 确认门控 | 不适用 | 恢复；回滚为再次删除 |
| `restore_dashboard`（medium） | 恢复回收状态看板 | 写 | 当前用户宿主 Dashboard 权限 + 确认门控 | 不适用 | 恢复；回滚为再次删除 |
| `delete_chart`（high） | 删除图表，软删除或永久删除取决于实例配置 | 写 | 当前用户宿主 Chart 权限 + 确认门控 | 不适用 | 删除；仅软删除生成 `restore_chart` 回滚，永久删除无回滚 |
| `delete_dashboard`（high） | 删除看板，软删除或永久删除取决于实例配置 | 写 | 当前用户宿主 Dashboard 权限 + 确认门控 | 不适用 | 删除；仅软删除可恢复 |
| `remove_chart_from_dashboard`（high） | 从看板移除图表但保留图表对象 | 写 | `can_write on Dashboard` + 确认门控 | 不适用 | 移除；回滚重新加图 |
| `add_native_filter`（medium） | 映射到 `manage_native_filters(add=[spec])`，每卡一个筛选器；仅 `filter_select`（需 `dataset_id`+`column`）与 `filter_time`（可选 `default_time_range`），可选 `scope_chart_ids`；宿主不支持数值区间/时间列/时间粒度类型 | 写 | `can_write on Dashboard` + 确认门控 | 不适用 | 新增筛选器；快照留看板名与新筛选器名，回滚＝对执行返回的 `added_filter_ids` 执行 `remove`；修改/删除/重排已有筛选器不提供 |

## 9. 无法固化为常量的项目

- 非 Admin 用户的实际 MCP 可见数会随角色、对象授权、Guest/隐私/scope 配置变化；本文没有逐角色执行目录查询。
- `delegate_to_employee` 是否注册取决于当次员工及候选委派集，不能宣称每次请求固定有 15 个静态工具。
- 动态技能可后台热更新；本文确认当前 1 个已定义技能处于停用状态、启用技能为 0，不将其当作永久数量。
- 外部 semantic view 的行级行为由具体语义层/数据源实现决定，源码层面只能标为“取决于底层实现”，不能统一承诺与内置数据集完全相同的 RLS 语义。
- 软删除是否启用、永久删除的实际可恢复性属于实例配置；执行结果应以确认时的快照和 Superset 返回为准。

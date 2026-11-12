from __future__ import annotations

from typing import Any

CATEGORY_ASSISTANT = "助手内置"

CATEGORY_ORDER: dict[str, int] = {
    name: index
    for index, name in enumerate(
        (
            CATEGORY_ASSISTANT,
            "系统",
            "数据库",
            "数据集",
            "语义层",
            "图表",
            "看板",
            "SQL Lab",
            "查询与保存查询",
            "告警与报告",
            "注解",
            "标签与主题",
            "任务",
            "用户 / 角色 / RLS",
            "其他",
        )
    )
}

CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("系统", ("health_check", "get_instance_info", "get_schema", "find_users", "generate_bug_report")),
    ("数据库", ("list_databases", "get_database_info")),
    ("数据集", ("list_datasets", "get_dataset_info", "create_dataset", "create_virtual_dataset", "query_dataset", "update_dataset_metric")),
    ("语义层", ("list_metrics", "get_table", "get_compatible_dimensions", "get_compatible_metrics")),
    ("图表", ("list_charts", "get_chart_info", "get_chart_data", "get_chart_preview", "get_chart_sql", "get_chart_type_schema", "generate_chart", "update_chart", "update_chart_preview", "generate_explore_link", "delete_chart", "restore_chart")),
    ("看板", ("list_dashboards", "get_dashboard_info", "get_dashboard_layout", "get_dashboard_datasets", "generate_dashboard", "add_chart_to_existing_dashboard", "remove_chart_from_dashboard", "update_dashboard", "duplicate_dashboard", "manage_dashboard_certification", "manage_dashboard_owners", "manage_dashboard_roles", "manage_native_filters", "delete_dashboard", "restore_dashboard")),
    ("SQL Lab", ("execute_sql", "open_sql_lab_with_context", "save_sql_query")),
    ("查询与保存查询", ("list_queries", "get_query_info", "list_saved_queries", "get_saved_query_info")),
    ("告警与报告", ("list_reports", "get_report_info")),
    ("注解", ("list_annotation_layers", "get_annotation_layer_info", "list_layer_annotations", "get_layer_annotation_info")),
    ("标签与主题", ("list_tags", "get_tag_info", "list_themes", "get_theme_info", "create_theme")),
    ("任务", ("list_tasks", "get_task_info")),
    ("用户 / 角色 / RLS", ("list_users", "get_user_info", "list_roles", "get_role_info", "list_rls_filters", "get_rls_filter_info")),
)

MCP_TOOL_TITLES: dict[str, str] = {
    "health_check": "健康检查",
    "get_instance_info": "获取实例信息",
    "get_schema": "获取工具参数 Schema",
    "find_users": "查找用户",
    "generate_bug_report": "生成问题诊断报告",
    "list_databases": "列出数据库",
    "get_database_info": "获取数据库信息",
    "list_datasets": "列出数据集",
    "get_dataset_info": "获取数据集信息",
    "create_dataset": "创建物理数据集",
    "create_virtual_dataset": "创建虚拟数据集",
    "query_dataset": "查询数据集",
    "update_dataset_metric": "修改数据集指标",
    "list_metrics": "列出指标",
    "get_table": "获取物理表信息",
    "get_compatible_dimensions": "获取可用维度",
    "get_compatible_metrics": "获取可用指标",
    "list_charts": "列出图表",
    "get_chart_info": "获取图表信息",
    "get_chart_data": "获取图表数据",
    "get_chart_preview": "预览图表",
    "get_chart_sql": "获取图表 SQL",
    "get_chart_type_schema": "获取图表类型参数",
    "generate_chart": "创建图表",
    "update_chart": "修改图表",
    "update_chart_preview": "预览修改图表",
    "generate_explore_link": "生成 Explore 链接",
    "delete_chart": "删除图表",
    "restore_chart": "恢复图表",
    "list_dashboards": "列出看板",
    "get_dashboard_info": "获取看板信息",
    "get_dashboard_layout": "获取看板布局",
    "get_dashboard_datasets": "获取看板数据集",
    "generate_dashboard": "创建看板",
    "add_chart_to_existing_dashboard": "添加图表到看板",
    "remove_chart_from_dashboard": "从看板移除图表",
    "update_dashboard": "修改看板",
    "duplicate_dashboard": "复制看板",
    "manage_dashboard_certification": "设置看板认证",
    "manage_dashboard_owners": "管理看板所有者",
    "manage_dashboard_roles": "管理看板角色",
    "manage_native_filters": "管理看板原生筛选器",
    "delete_dashboard": "删除看板",
    "restore_dashboard": "恢复看板",
    "execute_sql": "执行 SQL",
    "open_sql_lab_with_context": "带上下文打开 SQL Lab",
    "save_sql_query": "保存 SQL 查询",
    "list_queries": "列出查询记录",
    "get_query_info": "获取查询记录详情",
    "list_saved_queries": "列出已保存查询",
    "get_saved_query_info": "获取已保存查询详情",
    "list_reports": "列出报告",
    "get_report_info": "获取报告详情",
    "list_annotation_layers": "列出注解层",
    "get_annotation_layer_info": "获取注解层详情",
    "list_layer_annotations": "列出图层注解",
    "get_layer_annotation_info": "获取图层注解详情",
    "list_tags": "列出标签",
    "get_tag_info": "获取标签详情",
    "list_themes": "列出主题",
    "get_theme_info": "获取主题详情",
    "create_theme": "创建主题",
    "list_tasks": "列出后台任务",
    "get_task_info": "获取任务详情",
    "list_users": "列出用户",
    "get_user_info": "获取用户详情",
    "list_roles": "列出角色",
    "get_role_info": "获取角色详情",
    "list_rls_filters": "列出 RLS 规则",
    "get_rls_filter_info": "获取 RLS 规则详情",
}

# 助手内置工具里与 MCP 同名的 1 个（query_dataset）已由 MCP 条目控制，不重复列出；
# 这里只列 MCP 目录里没有的助手工具。
# 2026-11-01：list_datasets / get_dashboard_info / list_dashboards / list_charts 四个纯塑形
# 包装已删除；2026-11-03 再删 get_dataset_info（只剩参数包裹+字段裁剪，别名注入已搬进
# mcp_call 的 guard_dataset_info_arguments），模型改用 mcp_call 直调（审计仍记 MCP 名）。
AGENT_TOOL_SPECS: tuple[dict[str, Any], ...] = (
    {
        "name": "run_sql",
        "title": "执行 SQL",
        "description": "按当前用户的 SQL Lab 权限执行单条 SQL（只读由宿主与数据库账号保证，RLS 生效）",
        "category": CATEGORY_ASSISTANT,
        "read_only": True,
        "destructive": False,
        "aliases": ["execute_sql"],
    },
    {
        "name": "search_metadata",
        "title": "检索数据集元数据",
        "description": "按关键词检索数据集、字段和指标口径",
        "category": CATEGORY_ASSISTANT,
        "read_only": True,
        "destructive": False,
        "aliases": ["list_datasets"],
    },
    {
        "name": "period_compare",
        "title": "环比 / 同比对比",
        "description": "对比基期与本期指标：多维交叉、总量/日均口径自动选择、覆盖率与 Welch 显著性检验",
        "category": CATEGORY_ASSISTANT,
        "read_only": True,
        "destructive": False,
        "aliases": ["query_dataset"],
    },
    {
        "name": "dimension_contribution",
        "title": "维度贡献度分析",
        "description": "多维贡献额/贡献率/拉动百分点，附 HHI 集中度、正负抵消与各单维度解释力排名",
        "category": CATEGORY_ASSISTANT,
        "read_only": True,
        "destructive": False,
        "aliases": ["query_dataset"],
    },
    {
        "name": "structure_effect",
        "title": "结构效应分析",
        "description": "把比率型指标变化拆成结构/效率/交互三项，给出主导项、成员权重变化与闭合残差",
        "category": CATEGORY_ASSISTANT,
        "read_only": True,
        "destructive": False,
        "aliases": ["query_dataset"],
    },
    {
        "name": "trend_forecast",
        "title": "趋势预测",
        "description": "日粒度预测：线性趋势检验、STL 季节分解、阻尼 Holt-Winters、留出回测与 95% 预测区间",
        "category": CATEGORY_ASSISTANT,
        "read_only": True,
        "destructive": False,
        "aliases": ["query_dataset"],
    },
    {
        "name": "mcp_search",
        "title": "发现 MCP 工具",
        "description": "按关键词搜索当前用户可见的 Superset MCP 工具",
        "category": CATEGORY_ASSISTANT,
        "read_only": True,
        "destructive": False,
        "aliases": [],
    },
    {
        "name": "mcp_call",
        "title": "调用 MCP 工具",
        "description": "调用已发现的 Superset MCP 工具（目标工具仍需在白名单内）",
        "category": CATEGORY_ASSISTANT,
        "read_only": True,
        "destructive": False,
        "aliases": [],
    },
    {
        "name": "propose_write",
        "title": "生成写操作方案",
        "description": "生成待用户确认的图表/看板/指标/筛选器写方案，不直接执行",
        "category": CATEGORY_ASSISTANT,
        "read_only": False,
        "destructive": False,
        "aliases": [],
    },
    {
        "name": "save_knowledge",
        "title": "保存知识",
        "description": "把业务口径/规则写入当前用户或 AI 员工的知识库",
        "category": CATEGORY_ASSISTANT,
        "read_only": False,
        "destructive": False,
        "aliases": [],
    },
    {
        "name": "search_knowledge",
        "title": "检索知识库",
        "description": "检索当前用户或 AI 员工的知识库",
        "category": CATEGORY_ASSISTANT,
        "read_only": True,
        "destructive": False,
        "aliases": [],
    },
    {
        "name": "list_knowledge",
        "title": "知识库目录",
        "description": "列出知识库条目标题、来源和更新时间",
        "category": CATEGORY_ASSISTANT,
        "read_only": True,
        "destructive": False,
        "aliases": [],
    },
    {
        "name": "delete_knowledge",
        "title": "删除知识条目",
        "description": "删除知识库中指定条目",
        "category": CATEGORY_ASSISTANT,
        "read_only": False,
        "destructive": False,
        "aliases": [],
    },
)

# 这些助手工具在旧版本不受白名单约束；升级时补进已有员工的清单，
# 避免既有员工能力被静默收回。
LEGACY_UNRESTRICTED_AGENT_TOOLS: tuple[str, ...] = (
    "mcp_search",
    "mcp_call",
    "propose_write",
    "save_knowledge",
    "search_knowledge",
    "list_knowledge",
    "delete_knowledge",
)


def tool_category(name: str) -> str:
    for category, names in CATEGORY_RULES:
        if name in names:
            return category
    return "其他"


def build_tool_catalog(mcp_tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """合并 Superset MCP 工具与助手内置工具，统一带中文标题。"""
    items: list[dict[str, Any]] = []
    mcp_names: set[str] = set()
    for tool in mcp_tools or []:
        if not isinstance(tool, dict) or not tool.get("name"):
            continue
        name = str(tool["name"])
        mcp_names.add(name)
        annotations = tool.get("annotations") or {}
        items.append(
            {
                "name": name,
                "title": MCP_TOOL_TITLES.get(name) or str(tool.get("title") or name),
                "description": str(tool.get("description") or "")[:200],
                "category": tool_category(name),
                "read_only": bool(annotations.get("readOnlyHint")),
                "destructive": bool(annotations.get("destructiveHint")),
                "source": "mcp",
                "aliases": [],
            }
        )
    for spec in AGENT_TOOL_SPECS:
        if spec["name"] in mcp_names:
            continue
        items.append(
            {
                "name": spec["name"],
                "title": spec["title"],
                "description": spec["description"],
                "category": spec["category"],
                "read_only": spec["read_only"],
                "destructive": spec["destructive"],
                "source": "agent",
                "aliases": list(spec["aliases"]),
            }
        )
    items.sort(
        key=lambda item: (
            CATEGORY_ORDER.get(str(item["category"]), len(CATEGORY_ORDER)),
            str(item["name"]),
        )
    )
    return items

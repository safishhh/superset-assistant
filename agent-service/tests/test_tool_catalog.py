from __future__ import annotations

from assistant_agent.tool_catalog import (
    AGENT_TOOL_SPECS,
    CATEGORY_ASSISTANT,
    MCP_TOOL_TITLES,
    build_tool_catalog,
)


def test_build_tool_catalog_merges_mcp_and_agent_tools():
    mcp_tools = [
        {
            "name": "query_dataset",
            "title": "Query Dataset",
            "description": "Run an aggregate query",
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "generate_chart",
            "title": "Generate Chart",
            "description": "Create a chart",
            "annotations": {"destructiveHint": False},
        },
    ]

    items = build_tool_catalog(mcp_tools)
    by_name = {item["name"]: item for item in items}

    assert by_name["query_dataset"]["title"] == "查询数据集"
    assert by_name["query_dataset"]["source"] == "mcp"
    assert by_name["query_dataset"]["read_only"] is True
    assert by_name["generate_chart"]["title"] == "创建图表"
    assert by_name["generate_chart"]["read_only"] is False
    assert items[0]["category"] == CATEGORY_ASSISTANT

    for spec in AGENT_TOOL_SPECS:
        item = by_name[spec["name"]]
        assert item["title"] == spec["title"]
        assert item["description"] == spec["description"]
        assert item["source"] == "agent"
        assert item["category"] == CATEGORY_ASSISTANT
        assert item["aliases"] == spec["aliases"]


def test_every_known_mcp_tool_has_chinese_title():
    names = {
        "health_check",
        "get_instance_info",
        "get_schema",
        "find_users",
        "generate_bug_report",
        "list_databases",
        "get_database_info",
        "list_datasets",
        "get_dataset_info",
        "create_dataset",
        "create_virtual_dataset",
        "query_dataset",
        "update_dataset_metric",
        "list_metrics",
        "get_table",
        "get_compatible_dimensions",
        "get_compatible_metrics",
        "list_charts",
        "get_chart_info",
        "get_chart_data",
        "get_chart_preview",
        "get_chart_sql",
        "get_chart_type_schema",
        "generate_chart",
        "update_chart",
        "update_chart_preview",
        "generate_explore_link",
        "delete_chart",
        "restore_chart",
        "list_dashboards",
        "get_dashboard_info",
        "get_dashboard_layout",
        "get_dashboard_datasets",
        "generate_dashboard",
        "add_chart_to_existing_dashboard",
        "remove_chart_from_dashboard",
        "update_dashboard",
        "duplicate_dashboard",
        "manage_dashboard_certification",
        "manage_dashboard_owners",
        "manage_dashboard_roles",
        "manage_native_filters",
        "delete_dashboard",
        "restore_dashboard",
        "execute_sql",
        "open_sql_lab_with_context",
        "save_sql_query",
        "list_queries",
        "get_query_info",
        "list_saved_queries",
        "get_saved_query_info",
        "list_reports",
        "get_report_info",
        "list_annotation_layers",
        "get_annotation_layer_info",
        "list_layer_annotations",
        "get_layer_annotation_info",
        "list_tags",
        "get_tag_info",
        "list_themes",
        "get_theme_info",
        "create_theme",
        "list_tasks",
        "get_task_info",
        "list_users",
        "get_user_info",
        "list_roles",
        "get_role_info",
        "list_rls_filters",
        "get_rls_filter_info",
    }
    assert names <= set(MCP_TOOL_TITLES)
    assert all(title.strip() for title in MCP_TOOL_TITLES.values())

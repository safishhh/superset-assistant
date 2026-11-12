from __future__ import annotations

from assistant_agent.mcp_policy import (
    MAX_LIST_ITEMS,
    compact_result,
    compact_schema,
    gate_call,
)


def test_gate_blocks_persisting_writes_and_infra():
    for name in ("delete_chart", "update_dashboard", "generate_dashboard",
                 "add_chart_to_existing_dashboard", "update_dataset_metric"):
        allowed, note, _ = gate_call(name, {"request": {"identifier": 1}})
        assert allowed is False, name
        assert "propose_write" in note


def test_gate_distinguishes_writes_without_confirm_action():
    # 禁止直调，但 propose_write 也没有对应动作：不能说成"走 propose_write/确认后可执行"
    for name in ("create_dataset", "create_virtual_dataset", "create_theme",
                 "save_sql_query", "manage_dashboard_owners",
                 "manage_dashboard_roles"):
        allowed, note, _ = gate_call(name, {"request": {"identifier": 1}})
        assert allowed is False, name
        assert "不开放" in note, name
        assert "Superset 界面" in note, name
        assert "必须用 propose_write" not in note, name


def test_gate_native_filters_add_routes_to_confirm_action():
    allowed, note, _ = gate_call(
        "manage_native_filters",
        {"request": {"dashboard_id": 1, "add": [
            {"filter_type": "filter_time", "name": "订单时间"}
        ]}},
    )
    assert allowed is False
    assert "add_native_filter" in note
    assert "propose_write" in note
    assert "不开放" not in note


def test_gate_native_filters_non_add_is_capability_boundary():
    # update/remove/reorder 没有确认动作；显式空 reorder 也算操作（与宿主校验一致）
    for ops in (
        {"remove": ["NATIVE_FILTER-x"]},
        {"update": [{"id": "NATIVE_FILTER-x", "name": "n"}]},
        {"reorder": []},
        {"add": [{"filter_type": "filter_time", "name": "t"}],
         "remove": ["NATIVE_FILTER-x"]},
    ):
        allowed, note, _ = gate_call(
            "manage_native_filters", {"request": {"dashboard_id": 1, **ops}}
        )
        assert allowed is False, ops
        assert "只开放新增" in note, ops
        assert "Superset 看板编辑器" in note, ops
        assert "不要说成没有权限" in note, ops


def test_gate_blocks_infra_tools():
    for name in ("search_tools", "call_tool"):
        allowed, note, _ = gate_call(name, {})
        assert allowed is False
        assert "mcp_search" in note or "mcp_call" in note


def test_gate_forces_preview_on_writable_tools():
    allowed, note, args = gate_call(
        "generate_chart",
        {"request": {"dataset_id": 1, "save_chart": True}},
    )
    assert allowed is True
    assert args["request"]["save_chart"] is False
    assert "预览" in note

    allowed, note, args = gate_call(
        "update_chart",
        {"request": {"identifier": 5, "generate_preview": False}},
    )
    assert allowed is True
    assert args["request"]["generate_preview"] is True
    assert "预览" in note

    # 本来就是预览：放行且不再重复提示
    allowed, note, args = gate_call("update_chart", {"request": {"identifier": 5}})
    assert allowed is True
    assert args["request"]["generate_preview"] is True


def test_gate_allows_readonly_and_blocks_unknown_write_names():
    for name in ("get_chart_data", "list_reports", "get_dashboard_layout",
                 "execute_sql", "open_sql_lab_with_context"):
        allowed, _, _ = gate_call(name, {"request": {}})
        assert allowed is True, name

    # 上游若新增未知写操作，默认要求走 propose_write
    allowed, note, _ = gate_call("create_alert", {"request": {}})
    assert allowed is False
    assert "propose_write" in note


def test_compact_result_bounds_large_payloads():
    rows = [{"region": f"r{i}", "amount": i} for i in range(500)]
    payload, notes = compact_result({"data": rows})
    assert len(payload["data"]) == MAX_LIST_ITEMS
    assert any("截断" in note for note in notes)

    big = {"blob": "x" * 5_000}
    payload, notes = compact_result(big)
    assert len(payload["blob"]) < 5_000

    huge = {"rows": [{"text": "y" * 900} for _ in range(40)]}
    payload, notes = compact_result(huge, max_chars=2_000)
    assert "_preview" in payload
    assert len(payload["_preview"]) <= 2_000


def test_compact_schema_keeps_small_schemas_intact():
    schema = {"type": "object", "properties": {"identifier": {"type": "integer"}}}
    assert compact_schema(schema) == schema


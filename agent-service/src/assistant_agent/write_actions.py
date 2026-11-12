from __future__ import annotations

from typing import Any

from .mcp_client import MCPClient

RISK_LEVELS = {
    "create_chart": "medium",
    "create_dashboard": "medium",
    "add_chart_to_dashboard": "medium",
    "create_chart_and_add_to_dashboard": "medium",
    "update_chart": "medium",
    "update_dataset_metric": "high",
    "update_dashboard": "medium",
    "duplicate_dashboard": "medium",
    "set_dashboard_certification": "medium",
    "restore_chart": "medium",
    "restore_dashboard": "medium",
    "delete_chart": "high",
    "delete_dashboard": "high",
    "remove_chart_from_dashboard": "high",
    "add_native_filter": "medium",
}

METRIC_UPDATE_FIELDS = (
    "expression",
    "verbose_name",
    "description",
    "d3format",
    "warning_text",
)

# 只收录改前能从 get_dashboard_info 读回原值的字段：
# css / position_json / json_metadata_overrides 读不到原值，改了就无法回滚，因此不支持
DASHBOARD_UPDATE_FIELDS = ("dashboard_title", "description", "slug", "published")
DASHBOARD_CERT_FIELDS = ("certified_by", "certification_details")

# 宿主 manage_native_filters 只支持这两种新筛选器；数值区间/时间列/时间粒度不支持。
# 只开放"新增"：add 返回服务端生成的 filter id，回滚＝对同一 id 执行 remove；
# update/remove/reorder 的改前配置只在 json_metadata 里、常规工具读不回，无法快照回滚。
NATIVE_FILTER_TYPES = ("filter_select", "filter_time")
NATIVE_FILTER_SELECT_FIELDS = (
    "multi_select",
    "default_to_first_item",
    "enable_empty_filter",
    "sort_ascending",
    "search_all_options",
)


def risk_level(action_type: str) -> str:
    return RISK_LEVELS.get(action_type, "high")


def _require(value: Any, name: str) -> Any:
    if value is None or value == "":
        raise ValueError(f"{name} 不能为空")
    return value


def _chart_config(payload: dict[str, Any]) -> dict[str, Any]:
    chart_type = str(payload.get("chart_type") or "bar")
    metric = _require(payload.get("metric"), "metric")
    dimension = payload.get("dimension")
    metric_ref = {"name": str(metric), "saved_metric": True}

    if chart_type in {"bar", "line", "area"}:
        config: dict[str, Any] = {
            "chart_type": "xy",
            "kind": chart_type,
            "y": [metric_ref],
        }
        if dimension:
            config["x"] = {"name": str(dimension)}
        return config
    if chart_type == "pie":
        dimension = _require(dimension, "dimension")
        return {
            "chart_type": "pie",
            "dimension": {"name": str(dimension)},
            "metric": metric_ref,
        }
    if chart_type == "table":
        columns = []
        if dimension:
            columns.append({"name": str(dimension)})
        columns.append(metric_ref)
        return {"chart_type": "table", "columns": columns}
    if chart_type == "big_number":
        return {"chart_type": "big_number", "metric": metric_ref}
    raise ValueError(
        "chart_type 只支持 bar/line/area/pie/table/big_number"
    )


def _chart_request(payload: dict[str, Any]) -> dict[str, Any]:
    dataset_id = _require(payload.get("dataset_id"), "dataset_id")
    metric = _require(payload.get("metric"), "metric")
    chart_name = payload.get("chart_name") or f"{metric} 分析"
    return {
        "dataset_id": dataset_id,
        "chart_name": str(chart_name),
        "config": _chart_config({**payload, "metric": metric}),
        "save_chart": True,
        "generate_preview": False,
        "preview_formats": ["url"],
    }


def build_plan(action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if action_type == "create_chart":
        return {
            "tool": "generate_chart",
            "arguments": {"request": _chart_request(payload)},
        }
    if action_type == "create_chart_and_add_to_dashboard":
        dashboard_id = payload.get("dashboard_id")
        dashboard_title = payload.get("dashboard_title")
        if dashboard_id is None and not dashboard_title:
            raise ValueError("必须提供 dashboard_id 或 dashboard_title")
        next_step = (
            {
                "tool": "add_chart_to_existing_dashboard",
                "arguments_template": {
                    "request": {
                        "dashboard_id": int(dashboard_id),
                        "chart_id": "{chart_id}",
                    }
                },
            }
            if dashboard_id is not None
            else {
                "tool": "generate_dashboard",
                "arguments_template": {
                    "request": {
                        "chart_ids": ["{chart_id}"],
                        "dashboard_title": str(dashboard_title),
                    }
                },
            }
        )
        return {
            "tool": "generate_chart",
            "arguments": {"request": _chart_request(payload)},
            "next_step": next_step,
        }
    if action_type == "add_chart_to_dashboard":
        dashboard_id = _require(payload.get("dashboard_id"), "dashboard_id")
        chart_id = _require(payload.get("chart_id"), "chart_id")
        request = {
            "dashboard_id": int(dashboard_id),
            "chart_id": int(chart_id),
        }
        if payload.get("target_tab"):
            request["target_tab"] = str(payload["target_tab"])
        return {
            "tool": "add_chart_to_existing_dashboard",
            "arguments": {"request": request},
        }
    if action_type == "create_dashboard":
        chart_ids = payload.get("chart_ids")
        if not isinstance(chart_ids, list) or not chart_ids:
            raise ValueError("chart_ids 必须是非空数组")
        chart_ids = [int(item) for item in chart_ids]
        title = _require(payload.get("dashboard_title"), "dashboard_title")
        return {
            "tool": "generate_dashboard",
            "arguments": {
                "request": {
                    "chart_ids": chart_ids,
                    "dashboard_title": str(title),
                    "published": bool(payload.get("published", False)),
                }
            },
        }
    if action_type == "update_chart":
        chart_id = _require(payload.get("chart_id"), "chart_id")
        chart_name = payload.get("chart_name")
        metric = payload.get("metric")
        request: dict[str, Any] = {"identifier": int(chart_id)}
        if metric:
            # 改可视化配置：整体替换 config
            request["config"] = _chart_config({**payload, "metric": metric})
            request["generate_preview"] = False
            if chart_name:
                request["chart_name"] = str(chart_name)
        elif chart_name:
            # 仅改名：MCP 允许不带 config
            request["chart_name"] = str(chart_name)
            request["generate_preview"] = False
        else:
            raise ValueError("metric 与 chart_name 至少提供一个")
        return {
            "tool": "update_chart",
            "arguments": {"request": request},
        }
    if action_type == "update_dataset_metric":
        dataset_id = _require(payload.get("dataset_id"), "dataset_id")
        metric = _require(payload.get("metric"), "metric")
        updates = payload.get("updates")
        if not isinstance(updates, dict):
            raise ValueError("updates 必须是对象")
        clean = {
            key: value
            for key, value in updates.items()
            if key in METRIC_UPDATE_FIELDS
        }
        if not clean:
            raise ValueError(
                "updates 至少包含一个字段：" + ", ".join(METRIC_UPDATE_FIELDS)
            )
        return {
            "tool": "update_dataset_metric",
            "arguments": {
                "request": {
                    "dataset_id": dataset_id,
                    "metric": metric,
                    **clean,
                }
            },
        }
    if action_type == "update_dashboard":
        dashboard_id = _require(payload.get("dashboard_id"), "dashboard_id")
        updates = payload.get("updates")
        if not isinstance(updates, dict):
            raise ValueError("updates 必须是对象")
        clean = {
            key: value
            for key, value in updates.items()
            if key in DASHBOARD_UPDATE_FIELDS
        }
        if not clean:
            raise ValueError(
                "updates 至少包含一个字段：" + ", ".join(DASHBOARD_UPDATE_FIELDS)
                + "（css/布局/原生过滤器改前读不到，不提供，避免不可回滚的改动）"
            )
        return {
            "tool": "update_dashboard",
            "arguments": {"request": {"identifier": int(dashboard_id), **clean}},
        }
    if action_type == "duplicate_dashboard":
        dashboard_id = _require(payload.get("dashboard_id"), "dashboard_id")
        if payload.get("duplicate_slices"):
            raise ValueError(
                "duplicate_slices=true 会连图表一起深拷贝，副本无法可靠清理，不提供"
            )
        request: dict[str, Any] = {"dashboard_id": int(dashboard_id)}
        if payload.get("dashboard_title"):
            request["dashboard_title"] = str(payload["dashboard_title"])
        return {"tool": "duplicate_dashboard", "arguments": {"request": request}}
    if action_type == "set_dashboard_certification":
        dashboard_id = _require(payload.get("dashboard_id"), "dashboard_id")
        return {
            "tool": "manage_dashboard_certification",
            "arguments": {
                "request": {
                    "identifier": int(dashboard_id),
                    "certified_by": str(payload.get("certified_by") or ""),
                    "certification_details": str(
                        payload.get("certification_details") or ""
                    ),
                }
            },
        }
    if action_type == "restore_chart":
        return {
            "tool": "restore_chart",
            "arguments": {
                "request": {
                    "identifier": int(_require(payload.get("chart_id"), "chart_id"))
                }
            },
        }
    if action_type == "restore_dashboard":
        return {
            "tool": "restore_dashboard",
            "arguments": {
                "request": {
                    "identifier": int(
                        _require(payload.get("dashboard_id"), "dashboard_id")
                    )
                }
            },
        }
    if action_type == "delete_chart":
        return {
            "tool": "delete_chart",
            "arguments": {
                "request": {"identifier": int(_require(payload.get("chart_id"), "chart_id"))}
            },
        }
    if action_type == "delete_dashboard":
        return {
            "tool": "delete_dashboard",
            "arguments": {
                "request": {
                    "identifier": int(_require(payload.get("dashboard_id"), "dashboard_id"))
                }
            },
        }
    if action_type == "remove_chart_from_dashboard":
        return {
            "tool": "remove_chart_from_dashboard",
            "arguments": {
                "request": {
                    "dashboard_id": int(_require(payload.get("dashboard_id"), "dashboard_id")),
                    "chart_id": int(_require(payload.get("chart_id"), "chart_id")),
                }
            },
        }
    if action_type == "add_native_filter":
        dashboard_id = _require(payload.get("dashboard_id"), "dashboard_id")
        filter_type = str(payload.get("filter_type") or "")
        if filter_type not in NATIVE_FILTER_TYPES:
            raise ValueError(
                "filter_type 只支持 filter_select（下拉筛选）与 filter_time（时间范围）；"
                "数值区间/时间列/时间粒度宿主不支持"
            )
        spec: dict[str, Any] = {
            "filter_type": filter_type,
            "name": str(_require(payload.get("name"), "name")),
        }
        if payload.get("description"):
            spec["description"] = str(payload["description"])
        scope = payload.get("scope_chart_ids")
        if scope is not None:
            if not isinstance(scope, list):
                raise ValueError("scope_chart_ids 必须是图表 ID 数组")
            spec["scope_chart_ids"] = [int(item) for item in scope]
        if filter_type == "filter_select":
            spec["dataset_id"] = int(
                _require(payload.get("dataset_id"), "dataset_id")
            )
            spec["column"] = str(_require(payload.get("column"), "column"))
            for field in NATIVE_FILTER_SELECT_FIELDS:
                if payload.get(field) is not None:
                    spec[field] = bool(payload[field])
        elif payload.get("default_time_range"):
            spec["default_time_range"] = str(payload["default_time_range"])
        return {
            "tool": "manage_native_filters",
            "arguments": {
                "request": {"dashboard_id": int(dashboard_id), "add": [spec]}
            },
        }
    raise ValueError("不支持的写操作类型")


def _ensure_ok(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("MCP 返回了空结果")
    if data.get("error"):
        raise ValueError(str(data["error"]))
    return data


async def _dashboard_info(client: MCPClient, identifier: Any) -> dict[str, Any]:
    return _ensure_ok(
        await client.call_tool(
            "get_dashboard_info", {"request": {"identifier": identifier}}
        )
    )


async def _write_target_snapshot(
    client: MCPClient,
    action_type: str,
    request: dict[str, Any],
) -> dict[str, Any]:
    """改看板类动作的改前快照：只存读得到原值的字段，供回滚回填。"""
    if action_type in {"update_dashboard", "set_dashboard_certification"}:
        identifier = request.get("identifier")
        info = await _dashboard_info(client, identifier)
        snapshot: dict[str, Any] = {"dashboard_id": identifier}
        if action_type == "update_dashboard":
            for field in DASHBOARD_UPDATE_FIELDS:
                if field in request:
                    snapshot[field] = info.get(field)
        else:
            for field in DASHBOARD_CERT_FIELDS:
                snapshot[field] = info.get(field)
        snapshot["dashboard_title"] = info.get("dashboard_title")
        return snapshot
    if action_type == "duplicate_dashboard":
        dashboard_id = request.get("dashboard_id")
        info = await _dashboard_info(client, dashboard_id)
        return {
            "source_dashboard_id": dashboard_id,
            "source_dashboard_title": info.get("dashboard_title"),
        }
    if action_type in {"restore_chart", "restore_dashboard"}:
        # 对象此刻在回收站里，get_*_info 查不到；恢复类不需要改前值
        # （回滚就是再删一次），取不到名称就只留 id。
        identifier = request.get("identifier")
        key = "chart_id" if action_type == "restore_chart" else "dashboard_id"
        name_key = "chart_name" if action_type == "restore_chart" else "dashboard_title"
        snapshot = {key: identifier}
        try:
            if action_type == "restore_chart":
                info = _ensure_ok(
                    await client.call_tool(
                        "get_chart_info",
                        {
                            "request": {
                                "identifier": identifier,
                                "select_columns": ["id", "slice_name", "viz_type"],
                            }
                        },
                    )
                )
                snapshot[name_key] = info.get("slice_name")
                snapshot["viz_type"] = info.get("viz_type")
            else:
                info = await _dashboard_info(client, identifier)
                snapshot[name_key] = info.get("dashboard_title")
        except Exception:  # noqa: BLE001
            pass
        return snapshot


async def collect_snapshot(
    client: MCPClient,
    action_type: str,
    plan: dict[str, Any],
) -> dict[str, Any]:
    request = (plan.get("arguments") or {}).get("request") or {}
    if action_type == "create_dashboard":
        return {"chart_ids": request.get("chart_ids") or []}
    if action_type in {
        "add_chart_to_dashboard",
        "create_chart_and_add_to_dashboard",
    }:
        next_step = plan.get("next_step") or {}
        next_request = next_step.get("arguments_template", {}).get("request", {})
        dashboard_id = request.get("dashboard_id") or next_request.get(
            "dashboard_id"
        )
        snapshot: dict[str, Any] = {}
        if dashboard_id is not None:
            dashboard = _ensure_ok(
                await client.call_tool(
                    "get_dashboard_info",
                    {"request": {"identifier": dashboard_id}},
                )
            )
            snapshot["dashboard_id"] = dashboard_id
            snapshot["dashboard_title"] = dashboard.get("dashboard_title")
        if action_type == "add_chart_to_dashboard":
            snapshot["chart_id"] = request.get("chart_id")
            return snapshot
        chart_snapshot = await collect_snapshot(client, "create_chart", plan)
        snapshot.update(chart_snapshot)
        if next_request.get("dashboard_title"):
            snapshot["new_dashboard_title"] = next_request["dashboard_title"]
        return snapshot
    if action_type in {
        "update_dashboard",
        "duplicate_dashboard",
        "set_dashboard_certification",
        "restore_chart",
        "restore_dashboard",
    }:
        return await _write_target_snapshot(client, action_type, request)
    if action_type == "add_native_filter":
        # 回滚只依赖执行结果里的 added_filter_ids，不需要改前筛选器配置；
        # 快照留看板名与新增筛选器名，供确认卡与审计核对影响对象。
        dashboard_id = request.get("dashboard_id")
        info = await _dashboard_info(client, dashboard_id)
        return {
            "dashboard_id": dashboard_id,
            "dashboard_title": info.get("dashboard_title"),
            "new_filters": [
                {"name": item.get("name"), "filter_type": item.get("filter_type")}
                for item in request.get("add") or []
            ],
        }
    if action_type == "delete_chart":
        chart_id = request.get("identifier")
        info = _ensure_ok(
            await client.call_tool(
                "get_chart_info",
                {
                    "request": {
                        "identifier": chart_id,
                        "select_columns": ["id", "slice_name", "viz_type"],
                    }
                },
            )
        )
        # 只留名称和类型：删除前留证，且看板关联经实测在恢复后仍保留
        return {
            "chart_id": chart_id,
            "chart_name": info.get("slice_name"),
            "viz_type": info.get("viz_type"),
        }
    if action_type in {"delete_dashboard", "remove_chart_from_dashboard"}:
        dashboard_id = request.get("identifier") or request.get("dashboard_id")
        snapshot: dict[str, Any] = {}
        if dashboard_id is not None:
            dashboard = _ensure_ok(
                await client.call_tool(
                    "get_dashboard_info",
                    {"request": {"identifier": dashboard_id}},
                )
            )
            snapshot["dashboard_id"] = dashboard_id
            snapshot["dashboard_title"] = (
                dashboard.get("dashboard_title") or dashboard.get("title")
            )
        if action_type == "remove_chart_from_dashboard":
            snapshot["chart_id"] = request.get("chart_id")
        return snapshot
    if action_type in {"create_chart", "update_chart", "update_dataset_metric"}:
        if action_type == "update_chart":
            request = plan.get("arguments", {}).get("request", {})
            chart_id = request.get("identifier")
            info = _ensure_ok(
                await client.call_tool(
                    "get_chart_info",
                    {
                        "request": {
                            "identifier": chart_id,
                            "select_columns": [
                                "id",
                                "slice_name",
                                "viz_type",
                                "form_data",
                            ],
                        }
                    },
                )
            )
            return {
                "chart_id": chart_id,
                "chart_name": info.get("slice_name"),
                "viz_type": info.get("viz_type"),
                "form_data": info.get("form_data") or {},
            }
        dataset_id = request.get("dataset_id")
        info = _ensure_ok(
            await client.call_tool(
                "get_dataset_info",
                {"request": {"identifier": dataset_id}},
            )
        )
        snapshot = {
            "dataset_id": dataset_id,
            "dataset_name": info.get("table_name") or info.get("name"),
            "metrics": [
                item.get("metric_name")
                for item in info.get("metrics") or []
                if isinstance(item, dict)
            ],
        }
        if action_type == "update_dataset_metric":
            metric_name = str(request.get("metric"))
            metric = next(
                (
                    item
                    for item in info.get("metrics") or []
                    if isinstance(item, dict)
                    and str(item.get("metric_name")) == metric_name
                ),
                None,
            )
            if metric is None:
                raise ValueError(f"数据集上找不到指标 {metric_name}")
            snapshot["metric"] = metric
        return snapshot
    return {}


def _fill_chart_id(value: Any, chart_id: int) -> Any:
    if isinstance(value, dict):
        return {key: _fill_chart_id(item, chart_id) for key, item in value.items()}
    if isinstance(value, list):
        return [_fill_chart_id(item, chart_id) for item in value]
    if value == "{chart_id}":
        return chart_id
    return value


def _chart_id_from_result(result: dict[str, Any]) -> int | None:
    chart = result.get("chart") or {}
    value = chart.get("id") or result.get("chart_id")
    return int(value) if value is not None else None


def _dashboard_id_from_result(result: dict[str, Any]) -> int | None:
    dashboard = result.get("dashboard") or {}
    value = dashboard.get("id") or result.get("dashboard_id")
    return int(value) if value is not None else None


_VIZ_TO_KIND = (
    ("bar", ("echarts_timeseries_bar", "echarts_bar", "bar")),
    ("line", ("echarts_timeseries_line", "line")),
    ("area", ("echarts_timeseries_area", "area")),
    ("pie", ("pie", "echarts_pie")),
    ("table", ("table",)),
    ("big_number", ("big_number", "big_number_total")),
)


def _chart_kind_for_viz(viz_type: str | None) -> str | None:
    if not viz_type:
        return None
    for chart_kind, viz_names in _VIZ_TO_KIND:
        if viz_type in viz_names:
            return chart_kind
    return None


def _rollback_config_from_form_data(form_data: dict[str, Any]) -> dict[str, Any] | None:
    """从改前 form_data 还原一个等效的简化 chart config。

    只覆盖本模块可表达的字段（图表类型、维度、指标、表格列）；高级参数
    无法经 update_chart 的白名单 config 恢复。
    """
    kind = _chart_kind_for_viz(form_data.get("viz_type"))
    if kind is None:
        return None
    metrics = form_data.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        return None
    first = metrics[0]
    metric_name: str | None = None
    if isinstance(first, str):
        metric_name = first
    elif isinstance(first, dict):
        saved = first.get("saved_metric") or (
            first.get("metric_name") and not first.get("expression")
        )
        if saved:
            metric_name = first.get("saved_metric") or first.get("metric_name")
    if not metric_name:
        return None

    if kind in {"bar", "line", "area"}:
        x_axis = form_data.get("x_axis")
        if isinstance(x_axis, str):
            dimension: str | None = x_axis
        elif isinstance(x_axis, dict):
            dimension = x_axis.get("name") or x_axis.get("label")
        else:
            dimension = None
        config: dict[str, Any] = {
            "chart_type": "xy",
            "kind": kind,
            "y": [{"name": str(metric_name), "saved_metric": True}],
        }
        if dimension:
            config["x"] = {"name": str(dimension)}
        return config
    if kind == "pie":
        groupby = form_data.get("groupby") or form_data.get("columns") or []
        dimension = groupby[0] if groupby else None
        if dimension is None:
            return None
        return {
            "chart_type": "pie",
            "dimension": {"name": str(dimension)},
            "metric": {"name": str(metric_name), "saved_metric": True},
        }
    if kind == "table":
        names = [
            col.get("name") if isinstance(col, dict) else col
            for col in (form_data.get("all_columns") or form_data.get("groupby") or [])
        ]
        columns = [{"name": str(name)} for name in names if name]
        if not columns:
            return None
        columns.append({"name": str(metric_name), "saved_metric": True})
        return {"chart_type": "table", "columns": columns}
    if kind == "big_number":
        return {
            "chart_type": "big_number",
            "metric": {"name": str(metric_name), "saved_metric": True},
        }
    return None


def _update_chart_rollback(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    chart_id = snapshot.get("chart_id")
    if chart_id is None:
        return None
    config = _rollback_config_from_form_data(snapshot.get("form_data") or {})
    request: dict[str, Any] = {"identifier": int(chart_id), "generate_preview": False}
    if snapshot.get("chart_name"):
        request["chart_name"] = str(snapshot["chart_name"])
    if config is not None:
        request["config"] = config
    # 改前 form_data 不可解析时，至少还能恢复名称（仅改名场景本就是这种）
    if config is None and not request.get("chart_name"):
        return None
    return {"tool": "update_chart", "arguments": {"request": request}}



def _delete_chart_rollback(
    result: dict[str, Any],
    request: dict[str, Any],
) -> list[dict[str, Any]]:
    """软删除才可回滚；永久删除返回空。

    实测：进回收站再 restore_chart 后，图表与看板的关联保持不变，
    所以回滚只需要恢复对象，不用重新挂看板。
    """
    if not result.get("soft_deleted"):
        return []
    return [
        {
            "tool": "restore_chart",
            "arguments": {"request": {"identifier": request.get("identifier")}},
        }
    ]


async def execute_plan(
    client: MCPClient,
    action_type: str,
    plan: dict[str, Any],
    snapshot: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    request = (plan.get("arguments") or {}).get("request") or {}

    if action_type == "create_chart_and_add_to_dashboard":
        chart_result = _ensure_ok(
            await client.call_tool(
                str(plan.get("tool")),
                plan.get("arguments") or {},
            )
        )
        chart_id = _chart_id_from_result(chart_result)
        if chart_id is None:
            raise ValueError("图表创建成功但未返回 chart_id")
        next_step = plan.get("next_step") or {}
        arguments = _fill_chart_id(
            next_step.get("arguments_template") or {},
            chart_id,
        )
        try:
            dashboard_result = _ensure_ok(
                await client.call_tool(
                    str(next_step.get("tool")),
                    arguments,
                )
            )
        except Exception:
            try:
                await client.call_tool(
                    "delete_chart",
                    {"request": {"identifier": chart_id}},
                )
            except Exception:  # noqa: BLE001
                pass
            raise
        dashboard_id = _dashboard_id_from_result(dashboard_result)
        result = {
            "chart": chart_result.get("chart"),
            "explore_url": chart_result.get("explore_url"),
            "dashboard": dashboard_result.get("dashboard"),
            "dashboard_url": dashboard_result.get("dashboard_url"),
            "chart_id": chart_id,
            "dashboard_id": dashboard_id,
        }
        steps = []
        if dashboard_id is not None and next_step.get("tool") == "add_chart_to_existing_dashboard":
            steps.append(
                {
                    "tool": "remove_chart_from_dashboard",
                    "arguments": {
                        "request": {
                            "dashboard_id": dashboard_id,
                            "chart_id": chart_id,
                        }
                    },
                }
            )
        elif dashboard_id is not None:
            steps.append(
                {
                    "tool": "delete_dashboard",
                    "arguments": {"request": {"identifier": dashboard_id}},
                }
            )
        steps.append(
            {
                "tool": "delete_chart",
                "arguments": {"request": {"identifier": chart_id}},
            }
        )
        return result, {"steps": steps}

    result = _ensure_ok(
        await client.call_tool(
            str(plan.get("tool")),
            plan.get("arguments") or {},
        )
    )
    rollback: dict[str, Any] | None = None
    if action_type == "create_chart":
        chart_id = _chart_id_from_result(result)
        if chart_id is not None:
            rollback = {
                "tool": "delete_chart",
                "arguments": {"request": {"identifier": chart_id}},
            }
    elif action_type == "add_chart_to_dashboard":
        chart_id = int(request.get("chart_id"))
        dashboard_id = int(request.get("dashboard_id"))
        rollback = {
            "tool": "remove_chart_from_dashboard",
            "arguments": {
                "request": {
                    "dashboard_id": dashboard_id,
                    "chart_id": chart_id,
                }
            },
        }
    elif action_type == "create_dashboard":
        dashboard_id = _dashboard_id_from_result(result)
        if dashboard_id is not None:
            rollback = {
                "tool": "delete_dashboard",
                "arguments": {"request": {"identifier": dashboard_id}},
            }
    elif action_type == "update_chart":
        rollback = _update_chart_rollback(snapshot)
    elif action_type == "update_dashboard":
        restore = {"identifier": request.get("identifier")}
        for field in DASHBOARD_UPDATE_FIELDS:
            if field in snapshot:
                restore[field] = snapshot.get(field)
        if len(restore) > 1:
            rollback = {"tool": "update_dashboard", "arguments": {"request": restore}}
    elif action_type == "duplicate_dashboard":
        new_id = _dashboard_id_from_result(result)
        if new_id is not None:
            rollback = {
                "tool": "delete_dashboard",
                "arguments": {"request": {"identifier": new_id}},
            }
    elif action_type == "set_dashboard_certification":
        rollback = {
            "tool": "manage_dashboard_certification",
            "arguments": {
                "request": {
                    "identifier": request.get("identifier"),
                    "certified_by": snapshot.get("certified_by") or "",
                    "certification_details": snapshot.get("certification_details") or "",
                }
            },
        }
    elif action_type == "restore_chart":
        rollback = {
            "tool": "delete_chart",
            "arguments": {"request": {"identifier": request.get("identifier")}},
        }
    elif action_type == "restore_dashboard":
        rollback = {
            "tool": "delete_dashboard",
            "arguments": {"request": {"identifier": request.get("identifier")}},
        }
    elif action_type == "delete_chart":
        steps = _delete_chart_rollback(result, request)
        if steps:
            rollback = {"steps": steps}
    elif action_type == "delete_dashboard":
        if result.get("soft_deleted"):
            rollback = {
                "tool": "restore_dashboard",
                "arguments": {"request": {"identifier": request.get("identifier")}},
            }
    elif action_type == "remove_chart_from_dashboard":
        rollback = {
            "tool": "add_chart_to_existing_dashboard",
            "arguments": {"request": dict(request)},
        }
    elif action_type == "update_dataset_metric":
        metric = snapshot.get("metric") or {}
        if metric:
            updates = {
                field: metric.get(field)
                for field in METRIC_UPDATE_FIELDS
                if field in metric
            }
            rollback = {
                "tool": "update_dataset_metric",
                "arguments": {
                    "request": {
                        "dataset_id": request.get("dataset_id"),
                        "metric": request.get("metric"),
                        **updates,
                    }
                },
            }
    elif action_type == "add_native_filter":
        added = result.get("added_filter_ids") or []
        if added:
            rollback = {
                "tool": "manage_native_filters",
                "arguments": {
                    "request": {
                        "dashboard_id": request.get("dashboard_id"),
                        "remove": list(added),
                    }
                },
            }
    return result, rollback

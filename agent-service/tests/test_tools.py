import asyncio
import json

import pytest

from assistant_agent.mcp_client import MCPClient, MCPError, MCPToolError, _parse_body
from assistant_agent.tools import validate_single_statement


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM sales",
        "SELECT region, SUM(amount) FROM sales GROUP BY region",
        "WITH x AS (SELECT 1) SELECT * FROM x",
        "SELECT 1 UNION SELECT 2",
        "SELECT 1 ;",  # 尾部分号仍是单条，模型常这么写
    ],
)
def test_single_statement_allowed(sql):
    validate_single_statement(sql)


@pytest.mark.parametrize(
    "sql",
    ["SELECT 1; SELECT 2", "SELECT 1; SELECT 2;"]
)
def test_multi_statement_rejected(sql):
    """唯一保留的本地拦截：宿主放行多语句，且顶层 rows 只回最后一条结果。"""
    with pytest.raises(ValueError):
        validate_single_statement(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO sales (region) VALUES ('east')",
        "UPDATE sales SET amount = 0",
        "DELETE FROM sales",
        "DROP TABLE sales",
        "ALTER TABLE sales ADD COLUMN x INT",
        "CREATE TABLE x (id INT)",
        "SHOW TABLES",
    ],
)
def test_non_readonly_statements_delegate_to_superset(sql):
    """只读由 Superset 与数据库账号保证，本地不再重复实现。

    实测宿主：DML -> "DML queries are not allowed on this database"；
    DROP/TRUNCATE/ALTER 被破坏性语句拦截；SHOW TABLES 放行（只读元数据）。
    """
    validate_single_statement(sql)


def test_parse_sse_body():
    body = (
        "event: message\n"
        'data: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n'
    )
    assert _parse_body(body, "text/event-stream")["result"]["ok"] is True


def test_parse_json_body():
    assert _parse_body('{"result": 1}', "application/json")["result"] == 1


def test_parse_empty_stream():
    with pytest.raises(MCPError):
        _parse_body("event: message\n", "text/event-stream")


def test_list_tools_parses_standard_response():
    client = MCPClient("http://mcp/mcp", "token")

    async def fake_rpc(method, params=None):
        assert method == "tools/list"
        return {"tools": [{"name": "health_check"}, "bad"]}

    client._rpc = fake_rpc
    assert asyncio.run(client.list_tools()) == [{"name": "health_check"}]


def test_unwrap_json_text():
    result = {
        "content": [{"type": "text", "text": json.dumps({"rows": [1, 2]})}],
    }
    assert MCPClient._unwrap("query_dataset", result) == {"rows": [1, 2]}


def test_unwrap_plain_text():
    result = {"content": [{"type": "text", "text": "not json"}]}
    assert MCPClient._unwrap("health_check", result) == "not json"


def test_unwrap_error():
    result = {
        "isError": True,
        "content": [{"type": "text", "text": "denied"}],
    }
    with pytest.raises(MCPToolError):
        MCPClient._unwrap("run_sql", result)


def test_clean_labels_from_json_fence():
    from assistant_agent.labels import clean_labels

    raw = '```json\n{"market": "市场", "total_amount": "销售额", "junk": "噪声"}\n```'
    assert clean_labels(raw, ["market", "total_amount"]) == {
        "market": "市场",
        "total_amount": "销售额",
    }


def test_clean_labels_rejects_echo_and_english():
    from assistant_agent.labels import clean_labels

    raw = '{"market": "market", "count": "count of rows"}'
    assert clean_labels(raw, ["market", "count"]) == {}


def test_clean_labels_line_format():
    from assistant_agent.labels import clean_labels

    raw = "market：市场\norder_count = 订单数"
    assert clean_labels(raw, ["market", "order_count"]) == {
        "market": "市场",
        "order_count": "订单数",
    }


def test_label_prompt_contains_context():
    from assistant_agent.labels import build_label_prompt

    prompt = build_label_prompt(
        ["market"], sql="SELECT market FROM sales", sample={"market": "华东"}
    )
    assert "market" in prompt and "SELECT market" in prompt and "华东" in prompt


def test_mcp_execute_sql_guard_clamps_and_validates():
    from assistant_agent.tools import guard_execute_sql_arguments

    args = guard_execute_sql_arguments(
        {"request": {"sql": "SELECT 1", "limit": 5000}}, 500
    )
    assert args["request"]["limit"] == 500
    assert args["request"]["timeout"] == 30

    args = guard_execute_sql_arguments({"request": {"sql": "SELECT 1"}}, 300)
    assert args["request"]["limit"] == 300

    # 非只读语句现在本地放行（宿主以 "DML queries are not allowed" 拒绝），
    # 但行数与超时的护栏照旧生效
    args = guard_execute_sql_arguments(
        {"request": {"sql": "DELETE FROM sales", "limit": 9000}}, 500
    )
    assert args["request"]["limit"] == 500


def test_mcp_query_dataset_row_limit_clamped():
    from assistant_agent.tools import clamp_dataset_row_limit

    args = clamp_dataset_row_limit(
        {"request": {"dataset_id": 1, "row_limit": 9000}}, 500
    )
    assert args["request"]["row_limit"] == 500
    # 未指定时不注入，保持 MCP 默认
    untouched = clamp_dataset_row_limit({"request": {"dataset_id": 1}}, 500)
    assert "row_limit" not in untouched["request"]


def test_query_terms_keeps_business_words_and_drops_noise():
    from assistant_agent.tools import _query_terms

    terms = _query_terms("各区域的销售额 sales_amount")
    assert "销售额" in terms
    assert "sales_amount" in terms
    assert "sales" in terms and "amount" in terms
    assert "多少" not in _query_terms("销售额是多少")
    # 两字母拉丁词误命中率太高
    assert "id" not in _query_terms("order id")


def test_match_datasets_uses_metric_alias_column_note_and_table_name():
    from assistant_agent.tools import _match_datasets

    items = [
        {
            "id": 1,
            "table_name": "sales",
            "columns": [
                {"column_name": "region", "verbose_name": "区域", "description": None}
            ],
            "metrics": [
                {
                    "metric_name": "total_amount",
                    "verbose_name": "销售额",
                    "expression": "SUM(amount)",
                }
            ],
        },
        {
            "id": 2,
            "table_name": "ods_order_detail",
            "columns": [
                {
                    "column_name": "departure_date",
                    "verbose_name": None,
                    "description": "出发日期",
                }
            ],
            "metrics": [
                {"metric_name": "count", "verbose_name": "COUNT(*)", "expression": "COUNT(*)"}
            ],
        },
    ]

    ranked = _match_datasets("销售额", items)
    assert ranked and ranked[0]["item"]["id"] == 1
    assert "指标「销售额」(total_amount)" in ranked[0]["matched_in"]

    # 中文只填在数据库备注里也要命中
    assert _match_datasets("出发日期", items)[0]["item"]["id"] == 2
    # 英文表名
    assert _match_datasets("sales", items)[0]["item"]["id"] == 1
    # 目录里没有的口径：交给调用方回退成全量目录，而不是当成没有数据
    assert _match_datasets("营业额", items) == []


def test_column_and_metric_labels_fall_back_to_description():
    from assistant_agent.tools import _columns, _metrics

    assert _columns([{"column_name": "market", "description": "所属市场"}])[
        0
    ].verbose_name == "所属市场"
    assert _metrics([{"metric_name": "region", "verbose_name": "region"}])[
        0
    ].verbose_name is None
    # COUNT(*) 是表达式不是口径名
    assert _metrics(
        [{"metric_name": "count", "verbose_name": "COUNT(*)", "expression": "COUNT(*)"}]
    )[0].verbose_name is None


def test_detailed_dataset_caps_wide_tables():
    from assistant_agent.tools import METADATA_COLUMN_CAP, _detailed_dataset

    item = {
        "id": 9,
        "table_name": "wide",
        "columns": [{"column_name": f"c{i}"} for i in range(METADATA_COLUMN_CAP + 5)],
        "metrics": [],
    }
    result = _detailed_dataset({"item": item, "matched_in": ["表名 wide"]})
    assert len(result.columns) == METADATA_COLUMN_CAP
    assert result.matched_in == ["表名 wide"]
    assert any("get_dataset_info" in note for note in result.warnings)


def test_item_labels_cacheable_from_directory_row():
    from assistant_agent.tools import _item_labels

    labels = _item_labels(
        {
            "columns": [
                {"column_name": "region", "verbose_name": "区域"},
                {"column_name": "amount", "verbose_name": None, "description": "金额"},
            ],
            "metrics": [{"metric_name": "total_amount", "verbose_name": "销售额"}],
        }
    )
    assert labels == {"region": "区域", "amount": "金额", "total_amount": "销售额"}


def test_mcp_call_injects_dataset_info_column_fields():
    from assistant_agent.tools import (
        DATASET_INFO_COLUMN_FIELDS,
        guard_dataset_info_arguments,
    )

    args = guard_dataset_info_arguments({"request": {"identifier": 2}})
    assert args["request"]["column_fields"] == list(DATASET_INFO_COLUMN_FIELDS)

    # 模型自己给了 column_fields 时不覆盖它
    custom = guard_dataset_info_arguments(
        {"request": {"identifier": 2, "column_fields": ["column_name"]}}
    )
    assert custom["request"]["column_fields"] == ["column_name"]

    # 完全没包 request 时补出 request，让宿主自己报参数错而不是静默丢别名
    bare = guard_dataset_info_arguments({})
    assert bare["request"]["column_fields"] == list(DATASET_INFO_COLUMN_FIELDS)


def test_query_dataset_result_has_no_rls_flag():
    from assistant_agent.models import QueryDatasetResult

    # 宿主不返回 RLS 信息，包装不能替它断言"已过滤"（没配规则的表全量可见）
    assert "rls_enforced" not in QueryDatasetResult.model_fields


def test_dataset_filter_op_enum_and_null_value_dropped():
    from assistant_agent.models import DatasetFilter

    clause = DatasetFilter(col="region", op="IN", val=["east"])
    assert clause.model_dump(exclude_none=True) == {
        "col": "region",
        "op": "IN",
        "val": ["east"],
    }
    is_null = DatasetFilter(col="x", op="IS NULL")
    assert is_null.model_dump(exclude_none=True) == {"col": "x", "op": "IS NULL"}

    with pytest.raises(ValueError):
        DatasetFilter(col="x", op="BETWEEN")


def test_item_labels_accepts_get_dataset_info_shape():
    from assistant_agent.tools import _item_labels

    # _probe_dataset_labels 直接复用宿主 get_dataset_info 的原始键名
    labels = _item_labels(
        {
            "columns": [
                {"column_name": "departure_date", "verbose_name": None, "description": "出发日期"},
                {"column_name": "region", "verbose_name": "区域"},
            ],
            "metrics": [{"metric_name": "total_amount", "verbose_name": "销售额"}],
        }
    )
    assert labels == {
        "departure_date": "出发日期",
        "region": "区域",
        "total_amount": "销售额",
    }


def test_semantic_error_is_recorded_as_failure_in_audit():
    calls: list[tuple[str, str | None]] = []

    client = MCPClient(
        "http://mcp/mcp",
        "token",
        on_call=lambda name, args, result, error, ms: calls.append((name, error)),
    )

    async def fake_rpc(method, params=None):
        # 宿主语义失败：HTTP 成功，错误放在返回体里
        return {"content": [{"type": "text", "text": '{"error": "not found"}'}]}

    client._rpc = fake_rpc
    data = asyncio.run(client.call_tool("get_dataset_info", {"request": {}}))
    assert data["error"] == "not found"  # 调用方拿到的原样不变
    assert calls == [("get_dataset_info", "not found")]  # 审计不再记成成功


def test_success_is_recorded_without_error():
    calls: list[tuple[str, str | None]] = []
    client = MCPClient(
        "http://mcp/mcp",
        "token",
        on_call=lambda name, args, result, error, ms: calls.append((name, error)),
    )

    async def fake_rpc(method, params=None):
        return {"content": [{"type": "text", "text": '{"columns": []}'}]}

    client._rpc = fake_rpc
    asyncio.run(client.call_tool("get_dataset_info", {"request": {}}))
    assert calls == [("get_dataset_info", None)]


def test_query_dataset_result_carries_applied_filters():
    from assistant_agent.models import QueryDatasetResult

    result = QueryDatasetResult(
        dataset_id=1,
        dataset_name="sales",
        applied_filters=[{"col": "region", "op": "==", "val": "east"}],
    )
    assert result.applied_filters[0]["col"] == "region"
    assert QueryDatasetResult(dataset_id=1, dataset_name="sales").applied_filters == []


def test_dangerous_functions_left_to_superset():
    """危险函数/文件读写由宿主拦，包装不再重复维护字符串黑名单。

    实测宿主返回：Disallowed SQL functions: sleep / load_file；
    INTO OUTFILE 在其安全解析阶段就失败（不会写出文件）。
    """
    validate_single_statement("SELECT SLEEP(5)")
    validate_single_statement("SELECT LOAD_FILE('/etc/passwd') AS x FROM sales LIMIT 1")
    # INTO OUTFILE 本地仍被拦，但实测原因是 sqlglot 解析失败（不是结构检查、更不是字符串匹配）
    with pytest.raises(ValueError):
        validate_single_statement("SELECT 'x' FROM sales INTO OUTFILE '/tmp/qoder_probe.txt'")

import { useCallback, useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { AssistantAvatar } from "./AssistantAvatar";
import { ChartBlock } from "./ChartBlock";
import { buildChartPayload } from "./chartPayload";
import { interleaveCharts, type ChartPayload } from "./chartLayout";
import KnowledgeRefs from "./KnowledgeRefs";
import { collectKnowledgeRefs } from "./knowledgeRefs";
import SelectionTag from "./SelectionTag";
import type { SelectedBlock } from "./context";
import { extractThinking, stripThinking } from "./thinking";
import { isQueryTool, normalizeToolResult } from "./toolResult";
import { ToolCard } from "./ToolCard";
import type { ToolLikePart } from "./types";
import {
  UserConversation,
  UserConversationDetail,
  UserMessage,
  UserToolCall,
  deleteConversation,
  getConversation,
  getKnowledgeContent,
  listConversations,
} from "./userApi";

function time(value: string): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? value.slice(0, 16)
    : parsed.toLocaleString("zh-CN", { hour12: false });
}

type Turn = {
  runId: string;
  question: string;
  answer: string;
  error: string;
  tools: UserToolCall[];
  selection?: SelectedBlock[] | null;
};

function buildTurns(detail: UserConversationDetail): Turn[] {
  const turns: Turn[] = [];
  const byRun = new Map<string, Turn>();
  const ensure = (runId: string): Turn => {
    let turn = byRun.get(runId);
    if (!turn) {
      turn = { runId, question: "", answer: "", error: "", tools: [] };
      byRun.set(runId, turn);
      turns.push(turn);
    }
    return turn;
  };
  detail.messages.forEach((message: UserMessage) => {
    const turn = ensure(message.run_id);
    if (message.role === "user") {
      turn.question = message.content;
      turn.selection = message.selection ?? null;
    } else {
      turn.answer = message.content;
      turn.error = message.error;
    }
  });
  detail.tool_calls.forEach((tool) => ensure(tool.run_id).tools.push(tool));
  turns.forEach((turn) => turn.tools.sort((a, b) => a.sequence - b.sequence));
  return turns;
}

const normalizeResult = normalizeToolResult;

const loadKnowledgeContent = (scope: string, id: number) =>
  getKnowledgeContent(scope, id);

function toolPart(tool: UserToolCall): ToolLikePart {
  const failed = tool.status === "error";
  return {
    type: `tool-${tool.tool_name}`,
    toolName: tool.tool_name,
    state: failed ? "output-error" : "output-available",
    input: tool.args_json,
    output: normalizeResult(tool.tool_name, tool.result_json),
    errorText: failed ? tool.error : undefined,
  };
}

function HistoryAnswer({
  text,
  charts,
}: {
  text: string;
  charts: ChartPayload[];
}) {
  const thinking = extractThinking(text);
  const items = interleaveCharts(stripThinking(text), charts);
  return (
    <>
      {thinking ? (
        <details className="sa-think">
          <summary>思考过程</summary>
          <div className="sa-think-body">{thinking}</div>
        </details>
      ) : null}
      {items.length === 0 ? <div className="sa-md">—</div> : null}
      {items.map((item, index) =>
        item.kind === "chart" ? (
          <ChartBlock key={`chart-${index}`} {...item.chart} />
        ) : (
          <div className="sa-md" key={`text-${index}`}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {stripThinking(item.text)}
            </ReactMarkdown>
          </div>
        ),
      )}
    </>
  );
}

function collectTurnCharts(tools: UserToolCall[]): ChartPayload[] {
  const charts: ChartPayload[] = [];
  for (const tool of tools) {
    if (tool.status === "error") continue;
    if (!isQueryTool(tool.tool_name)) continue;
    const chart = buildChartPayload(
      tool.tool_name,
      tool.result_json,
      tool.args_json,
    );
    if (chart) charts.push(chart);
  }
  return charts;
}

function HistoryTurn({ turn }: { turn: Turn }) {
  const [open, setOpen] = useState(false);
  const failed = turn.tools.filter((tool) => tool.status === "error").length;
  const charts = useMemo(() => collectTurnCharts(turn.tools), [turn.tools]);
  const knowledgeRefs = useMemo(
    () =>
      collectKnowledgeRefs(
        turn.tools.map((tool) => ({
          name: tool.tool_name,
          result: tool.result_json,
        })),
      ),
    [turn.tools],
  );

  return (
    <>
      {turn.question ? (
        <div className="sa-msg sa-msg-user">
          <SelectionTag blocks={turn.selection} compact />
          <div className="sa-bubble">{turn.question}</div>
        </div>
      ) : null}
      <div className="sa-msg sa-msg-assistant">
        <div className="sa-assistant-avatar">
          <AssistantAvatar follow={false} />
        </div>
        <div className="sa-assistant-body">
          <SelectionTag blocks={turn.selection} compact />
          {turn.tools.length ? (
            <div className={`sa-steps ${open ? "sa-steps-open" : ""}`}>
              <button
                type="button"
                className="sa-steps-head"
                aria-expanded={open}
                onClick={() => setOpen(!open)}
              >
                <span className="sa-steps-label">执行了 {turn.tools.length} 步</span>
                {failed ? (
                  <span className="sa-steps-fail">{failed} 步失败</span>
                ) : null}
                <span className="sa-steps-caret">
                  {open ? "收起 ▴" : "展开 ▾"}
                </span>
              </button>
              {open ? (
                <div className="sa-steps-body">
                  {turn.tools.map((tool) => (
                    <ToolCard
                      key={tool.id}
                      name={tool.tool_name}
                      part={toolPart(tool)}
                      variant="step"
                      showChart={false}
                    />
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
          {turn.answer ? (
            <HistoryAnswer text={turn.answer} charts={charts} />
          ) : (
            <>
              {turn.error ? (
                <div className="sa-tool-error">{turn.error}</div>
              ) : null}
              {charts.map((chart, index) => (
                <ChartBlock key={`chart-${index}`} {...chart} />
              ))}
            </>
          )}
          <KnowledgeRefs
            items={knowledgeRefs}
            loadContent={loadKnowledgeContent}
          />
        </div>
      </div>
    </>
  );
}

function HistoryTranscript({ detail }: { detail: UserConversationDetail }) {
  const turns = useMemo(() => buildTurns(detail), [detail]);
  if (!turns.length) {
    return <div className="sa-history-empty">这条会话没有记录。</div>;
  }
  return (
    <div className="sa-history-transcript">
      {turns.map((turn) => (
        <HistoryTurn key={turn.runId} turn={turn} />
      ))}
    </div>
  );
}

export default function HistoryView({
  activeConversationId,
  onClose,
  onLoad,
  onDeleted,
  onExport,
}: {
  activeConversationId: string;
  onClose: () => void;
  onLoad: (detail: UserConversationDetail) => void;
  onDeleted: (id: string) => void;
  onExport: (id: string, format: "md" | "html") => void;
}) {
  const [items, setItems] = useState<UserConversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState<UserConversationDetail | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await listConversations();
      setItems(data.items);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const open = async (id: string) => {
    setLoading(true);
    setError("");
    try {
      setDetail(await getConversation(id));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading(false);
    }
  };

  const remove = async (id: string) => {
    try {
      await deleteConversation(id);
      setItems((current) => current.filter((item) => item.id !== id));
      if (detail?.id === id) setDetail(null);
      onDeleted(id);
      setConfirmId(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  };

  const DeleteControls = ({ id }: { id: string }) =>
    confirmId === id ? (
      <span className="sa-history-confirm">
        <button
          type="button"
          className="sa-history-danger"
          onClick={() => void remove(id)}
        >
          确认删除
        </button>
        <button
          type="button"
          className="sa-history-btn"
          onClick={() => setConfirmId(null)}
        >
          取消
        </button>
      </span>
    ) : (
      <button
        type="button"
        className="sa-history-btn sa-history-delete"
        title="软删除；管理员审计中仍保留"
        onClick={() => setConfirmId(id)}
      >
        删除
      </button>
    );

  return (
    <div className="sa-history">
      <div className="sa-history-head">
        <button
          type="button"
          className="sa-history-btn"
          onClick={() => (detail ? setDetail(null) : onClose())}
        >
          {detail ? "返回列表" : "返回对话"}
        </button>
        <strong>{detail ? detail.title || detail.id : "历史对话"}</strong>
        <span className="sa-header-spacer" />
        <button type="button" className="sa-history-btn" onClick={() => void load()}>
          刷新
        </button>
      </div>

      {error ? <div className="sa-error">{error}</div> : null}

      {detail ? (
        <div className="sa-history-body sa-history-body-detail">
          <div className="sa-history-subhead">
            <div className="sa-history-meta">
              {detail.username} · {detail.model_name || "—"} ·{" "}
              {detail.run_count} 轮 ·{" "}
              {(detail.input_tokens + detail.output_tokens).toLocaleString("zh-CN")}{" "}
              Token · {time(detail.last_at)}
            </div>
            <div className="sa-history-actions">
              <button
                type="button"
                className="sa-history-btn sa-history-primary"
                onClick={() => onLoad(detail)}
              >
                继续对话
              </button>
              <button
                type="button"
                className="sa-history-btn"
                onClick={() => onExport(detail.id, "md")}
              >
                导出 MD
              </button>
              <button
                type="button"
                className="sa-history-btn"
                onClick={() => onExport(detail.id, "html")}
              >
                导出 HTML
              </button>
              <DeleteControls id={detail.id} />
            </div>
          </div>

          <HistoryTranscript detail={detail} />
        </div>
      ) : (
        <div className="sa-history-body">
          {loading ? (
            <div className="sa-history-empty">正在加载…</div>
          ) : items.length === 0 ? (
            <div className="sa-history-empty">还没有历史对话。</div>
          ) : (
            <div className="sa-history-list">
              {items.map((item) => (
                <div
                  className={
                    item.id === activeConversationId
                      ? "sa-history-item sa-history-item-active"
                      : "sa-history-item"
                  }
                  key={item.id}
                >
                  <button
                    type="button"
                    className="sa-history-open"
                    onClick={() => void open(item.id)}
                  >
                    <div className="sa-history-title">
                      {item.title || item.id}
                    </div>
                    <div className="sa-history-sub">
                      {item.run_count} 轮 ·{" "}
                      {(item.input_tokens + item.output_tokens).toLocaleString(
                        "zh-CN",
                      )}{" "}
                      Token · {time(item.last_at)}
                    </div>
                  </button>
                  <DeleteControls id={item.id} />
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

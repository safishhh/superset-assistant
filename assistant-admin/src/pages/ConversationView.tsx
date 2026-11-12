import { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { AssistantAvatar } from "../../../assistant-ext/assistant/frontend/src/AssistantAvatar";
import { ChartBlock } from "../../../assistant-ext/assistant/frontend/src/ChartBlock";
import { buildChartPayload } from "../../../assistant-ext/assistant/frontend/src/chartPayload";
import {
  interleaveCharts,
  type ChartPayload,
} from "../../../assistant-ext/assistant/frontend/src/chartLayout";
import KnowledgeRefs from "../../../assistant-ext/assistant/frontend/src/KnowledgeRefs";
import { collectKnowledgeRefs } from "../../../assistant-ext/assistant/frontend/src/knowledgeRefs";
import { selectionKindLabel } from "../../../assistant-ext/assistant/frontend/src/selectionLabels";
import { extractThinking, stripThinking } from "../../../assistant-ext/assistant/frontend/src/thinking";
import { isQueryTool } from "../../../assistant-ext/assistant/frontend/src/toolResult";
import type { ConversationDetail } from "../types";

type AdminMessage = ConversationDetail["messages"][number];
type AdminTool = ConversationDetail["tool_calls"][number];

type Turn = {
  runId: string;
  user?: AdminMessage;
  assistant?: AdminMessage;
  tools: AdminTool[];
};

function buildTurns(detail: ConversationDetail): Turn[] {
  const turns: Turn[] = [];
  const byRun = new Map<string, Turn>();
  const ensure = (runId: string): Turn => {
    let turn = byRun.get(runId);
    if (!turn) {
      turn = { runId, tools: [] };
      byRun.set(runId, turn);
      turns.push(turn);
    }
    return turn;
  };
  for (const message of detail.messages) {
    const turn = ensure(message.run_id || `message-${message.id}`);
    if (message.role === "user") turn.user = message;
    else turn.assistant = message;
  }
  for (const tool of detail.tool_calls) {
    ensure(tool.run_id).tools.push(tool);
  }
  turns.forEach((turn) => turn.tools.sort((a, b) => a.sequence - b.sequence));
  return turns;
}

function selectionLabels(message?: AdminMessage): string[] {
  const blocks = message?.selection;
  if (!Array.isArray(blocks)) return [];
  return blocks.map((block) => {
    return `${selectionKindLabel(block.kind)} · ${block.title || "未命名"}`;
  });
}

function collectCharts(tools: AdminTool[]): ChartPayload[] {
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

function SelectionChips({ labels }: { labels: string[] }) {
  if (!labels.length) return null;
  return (
    <div className="conv-selection">
      <span className="conv-selection-label">选中</span>
      {labels.map((label, index) => (
        <span className="conv-selection-chip" key={`${label}-${index}`}>
          {label}
        </span>
      ))}
    </div>
  );
}

function ToolSteps({ tools }: { tools: AdminTool[] }) {
  if (!tools.length) return null;
  const failed = tools.filter((tool) => tool.status === "error").length;
  return (
    <details className="conv-steps">
      <summary>
        执行了 {tools.length} 步
        {failed ? <span className="conv-steps-fail">{failed} 步失败</span> : null}
      </summary>
      <div className="conv-steps-body">
        {tools.map((tool) => (
          <details className="conv-tool" key={tool.id}>
            <summary>
              <span className="conv-tool-name">{tool.tool_name}</span>
              <span className="conv-tool-meta">
                #{tool.sequence} · {tool.status} · {tool.duration_ms}ms
                {tool.row_count ? ` · ${tool.row_count} 行` : ""}
              </span>
            </summary>
            <div className="conv-tool-body">
              {tool.sql_text ? (
                <>
                  <h4>SQL</h4>
                  <pre className="conv-json">{tool.sql_text}</pre>
                </>
              ) : null}
              <h4>参数</h4>
              <pre className="conv-json">
                {JSON.stringify(tool.args_json ?? {}, null, 2)}
              </pre>
              <h4>完整结果</h4>
              <pre className="conv-json">
                {JSON.stringify(tool.result_json ?? {}, null, 2)}
              </pre>
              {tool.error ? (
                <>
                  <h4>错误</h4>
                  <div className="conv-error">{tool.error}</div>
                </>
              ) : null}
            </div>
          </details>
        ))}
      </div>
    </details>
  );
}

function AssistantBody({ turn }: { turn: Turn }) {
  const text = turn.assistant?.content || "";
  const thinking = extractThinking(text);
  const charts = useMemo(() => collectCharts(turn.tools), [turn.tools]);
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
  const items = useMemo(
    () => interleaveCharts(stripThinking(text), charts),
    [text, charts],
  );
  return (
    <div className="conv-assistant">
      <AssistantAvatar className="conv-avatar" follow={false} />
      <div className="conv-body">
        <SelectionChips labels={selectionLabels(turn.assistant)} />
        {thinking ? (
          <details className="sa-think">
            <summary>思考过程</summary>
            <div className="conv-think-body">{thinking}</div>
          </details>
        ) : null}
        <ToolSteps tools={turn.tools} />
        {turn.assistant?.error && !items.length ? (
          <div className="conv-error">{turn.assistant.error}</div>
        ) : null}
        {items.map((item, index) =>
          item.kind === "chart" ? (
            <ChartBlock
              key={`chart-${index}`}
              {...item.chart}
              openInExplore={false}
            />
          ) : (
            <div className="sa-md" key={`text-${index}`}>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {stripThinking(item.text)}
              </ReactMarkdown>
            </div>
          ),
        )}
        {!items.length && !turn.assistant?.error ? (
          <div className="sa-md">—</div>
        ) : null}
        <KnowledgeRefs items={knowledgeRefs} />
      </div>
    </div>
  );
}

export default function ConversationView({
  detail,
}: {
  detail: ConversationDetail;
}) {
  const turns = useMemo(() => buildTurns(detail), [detail]);
  if (!turns.length) {
    return <div className="conv-empty">这条会话没有记录。</div>;
  }
  return (
    <div className="conv">
      {turns.map((turn) => (
        <div className="conv-turn" key={turn.runId}>
          {turn.user ? (
            <div className="conv-user">
              <SelectionChips labels={selectionLabels(turn.user)} />
              <div className="conv-bubble">{turn.user.content}</div>
            </div>
          ) : null}
          <AssistantBody turn={turn} />
        </div>
      ))}
    </div>
  );
}

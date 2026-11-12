import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useChatRuntime } from "@assistant-ui/react-ai-sdk";
import { DefaultChatTransport } from "ai";
import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useAssistantRuntime,
  useAssistantState,
  useMessage,
  type TextMessagePartProps,
  type ToolCallMessagePartProps,
} from "@assistant-ui/react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { chat } from "@apache-superset/core";

import {
  agentBaseUrl,
  clearToken,
  fetchMe,
  fetchToken,
} from "./api";
import { AssistantAvatar } from "./AssistantAvatar";
import {
  collectPageContext,
  encodePageContext,
  setSelectionContext,
  type SelectedBlock,
} from "./context";
import { SELECTION_KIND_LABEL } from "./selectionLabels";
import HistoryView from "./HistoryView";
import SelectionTag from "./SelectionTag";
import { ChartBlock } from "./ChartBlock";
import { buildChartPayload } from "./chartPayload";
import {
  interleaveCharts,
  type ChartPayload,
} from "./chartLayout";
import KnowledgeView from "./KnowledgeView";
import KnowledgeRefs from "./KnowledgeRefs";
import { collectKnowledgeRefs } from "./knowledgeRefs";
import { useAssistantTheme } from "./theme";
import { extractThinking, stripThinking } from "./thinking";
import { ToolCard } from "./ToolCard";
import { ToolLikePart } from "./types";
import {
  isContinuationText,
  WriteActionCard,
  type WriteProposal,
} from "./WriteActionCard";
import { WriteBatchProvider } from "./WriteBatchContext";
import type { TurnExportData } from "./exportHtml";
import { isQueryTool } from "./toolResult";
import {
  FeedbackRating,
  RunInfo,
  UserConversationDetail,
  UserMessage,
  cancelRun,
  downloadBlob,
  exportConversation,
  getConversation,
  getFeedback,
  getKnowledgeContent,
  getRun,
  saveFeedback,
} from "./userApi";
import {
  clearPendingRun,
  getCurrentRunId,
  readPendingRun,
  writePendingRun,
} from "./pendingRun";
import ResumeView from "./ResumeView";
import { HeaderIcon, ThumbIcon } from "./chatIcons";
import {
  EMPLOYEE_KEY,
  MODEL_KEY,
  REASONING_KEY,
  EmployeeContext,
  EmployeePicker,
  ModelPicker,
  ReasoningPicker,
  SelectionTurnsContext,
  readEmployeeId,
  readModelId,
  readReasoningEffort,
  useTurnSelection,
  type EmployeeInfo,
  type ModelInfo,
  type ReasoningEffort,
} from "./chatControls";
import {
  DEFAULT_PANEL_RATIO,
  SIZE_KEY,
  SUGGESTIONS,
  clampPanelSize,
  guardStreamIdle,
  historyToMessages,
  historyToSelections,
  lastUserText,
  newConversationId,
  newSession,
  ratioOfSize,
  readPanelRatio,
  resolveSelectedBlock,
  useIsDashboard,
  usePageLabel,
  type ChatSession,
  type PanelRatio,
  type ResumeState,
} from "./panelUtils";


function toToolLike(part: ToolCallMessagePartProps): ToolLikePart {
  const status = part.status?.type;
  const failed = Boolean(part.isError) || status === "incomplete";
  let state: string;
  if (failed) {
    state = "output-error";
  } else if (part.result !== undefined || status === "complete") {
    state = "output-available";
  } else {
    state = "input-available";
  }
  const result = part.result;
  const errorText = failed
    ? typeof result === "string"
      ? result
      : result != null
        ? JSON.stringify(result)
        : "工具执行失败"
    : undefined;
  return {
    type: `tool-${part.toolName}`,
    state,
    input: part.args,
    output: result,
    errorText,
  };
}

function UserText({ text }: TextMessagePartProps) {
  return <>{text}</>;
}

function ThinkBlock({ text, running }: { text: string; running: boolean }) {
  if (!text.trim()) return null;
  return (
    <details className="sa-think">
      <summary>
        思考过程
        {running ? <span className="sa-think-running"> 生成中…</span> : null}
      </summary>
      <div className="sa-think-body">{text}</div>
    </details>
  );
}

function BodyMarkdown({ text }: { text: string }) {
  return (
    <div className="sa-md">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
}

function contentText(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .filter(
      (part) =>
        part &&
        typeof part === "object" &&
        (part as { type?: string }).type === "text" &&
        typeof (part as { text?: unknown }).text === "string",
    )
    .map((part) => String((part as { text?: string }).text ?? ""))
    .join("\n");
}

function UserMessage() {
  const selection = useTurnSelection("user");
  const content = useMessage((message) => message.content);
  if (isContinuationText(contentText(content))) return null;
  return (
    <MessagePrimitive.Root className="sa-msg sa-msg-user">
      <SelectionTag blocks={selection} compact />
      <div className="sa-bubble">
        <MessagePrimitive.Parts components={{ Text: UserText }} />
      </div>
    </MessagePrimitive.Root>
  );
}

type FeedbackContextValue = {
  conversationId: string;
  ratings: Record<number, FeedbackRating>;
  busyTurns: Set<number>;
  onRate: (turnIndex: number, rating: FeedbackRating | null) => void;
};

type TurnExportPayload = Omit<TurnExportData, "conversationId">;

const TurnExportContext = createContext<
  ((payload: TurnExportPayload, format: "md" | "html") => void) | null
>(null);

const FeedbackContext = createContext<FeedbackContextValue>({
  conversationId: "",
  ratings: {},
  busyTurns: new Set(),
  onRate: () => {},
});

function AnswerFeedback() {
  const isRunning = useAssistantState(({ thread }) => thread.isRunning);
  const messages = useAssistantState(({ thread }) => thread.messages);
  const message = useMessage();
  const { conversationId, ratings, busyTurns, onRate } = useContext(
    FeedbackContext,
  );

  const turnIndex = useMemo(() => {
    let count = 0;
    for (const item of messages) {
      if (item.role === "assistant") count += 1;
      if (item.id === message.id) break;
    }
    return message.role === "assistant" ? count : 0;
  }, [messages, message.id, message.role]);

  if (isRunning || !conversationId || turnIndex < 1) return null;
  const rating = ratings[turnIndex];
  const busy = busyTurns.has(turnIndex);

  return (
    <div className="sa-msg-actions">
      <button
        type="button"
        className={`sa-action-icon${rating === "up" ? " sa-on-up" : ""}`}
        title={rating === "up" ? "有帮助（再点取消）" : "有帮助"}
        aria-label="有帮助"
        aria-pressed={rating === "up"}
        disabled={busy}
        onClick={() => onRate(turnIndex, rating === "up" ? null : "up")}
      >
        <ThumbIcon up={true} active={rating === "up"} />
      </button>
      <button
        type="button"
        className={`sa-action-icon${rating === "down" ? " sa-on-down" : ""}`}
        title={rating === "down" ? "没帮助（再点取消）" : "没帮助"}
        aria-label="没帮助"
        aria-pressed={rating === "down"}
        disabled={busy}
        onClick={() => onRate(turnIndex, rating === "down" ? null : "down")}
      >
        <ThumbIcon up={false} active={rating === "down"} />
      </button>
    </div>
  );
}

function CopyAnswer() {
  const isRunning = useAssistantState(({ thread }) => thread.isRunning);
  const message = useMessage();
  const [copied, setCopied] = useState(false);
  const parts =
    (message as unknown as { content?: Array<{ type?: string; text?: string }> })
      .content ?? [];
  const text = parts
    .filter((part) => part.type === "text")
    .map((part) => String(part.text ?? ""))
    .join("\n")
    .trim();
  if (isRunning || !text) return null;

  const copy = async () => {
    let ok = false;
    try {
      await navigator.clipboard.writeText(text);
      ok = true;
    } catch {
      const helper = document.createElement("textarea");
      helper.value = text;
      document.body.appendChild(helper);
      helper.select();
      try {
        ok = document.execCommand("copy");
      } catch {
        ok = false;
      }
      helper.remove();
    }
    if (ok) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    }
  };

  return (
    <button
      type="button"
      className="sa-action-icon"
      title={copied ? "已复制" : "复制回答"}
      aria-label="复制回答"
      onClick={() => void copy()}
    >
      {copied ? (
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="m4.5 12.5 5 5 10-11" />
        </svg>
      ) : (
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <rect x="9" y="9" width="11.5" height="11.5" rx="2" />
          <path d="M5.5 15H4.8A1.8 1.8 0 0 1 3 13.2V4.8A1.8 1.8 0 0 1 4.8 3h8.4A1.8 1.8 0 0 1 15 4.8v.7" />
        </svg>
      )}
    </button>
  );
}

function ExportTurnButton() {
  const onExport = useContext(TurnExportContext);
  const isRunning = useAssistantState(({ thread }) => thread.isRunning);
  const messages = useAssistantState(({ thread }) => thread.messages);
  const message = useMessage();
  const parts = (message.content as unknown) as MessagePart[];
  const selection = useTurnSelection("assistant");
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLSpanElement | null>(null);
  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event: PointerEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);
  if (!onExport || isRunning) return null;

  const buildPayload = (): TurnExportPayload | null => {
    const index = messages.findIndex((item) => item.id === message.id);
    if (index < 0) return null;
    const answer = (parts || [])
      .filter(
        (part) =>
          !part.toolName &&
          part.type === "text" &&
          typeof part.text === "string",
      )
      .map((part) => stripThinking(String(part.text)))
      .filter(Boolean)
      .join("\n\n")
      .trim();
    const charts = collectCharts(
      (parts || []).filter((part) => Boolean(part.toolName)),
    );
    const knowledgeRefs = collectKnowledgeRefsOf(
      (parts || []).filter((part) => Boolean(part.toolName)),
    );
    let turnIndex = 0;
    for (const item of messages) {
      if (item.role === "assistant") turnIndex += 1;
      if (item.id === message.id) break;
    }
    const now = new Date();
    const date = [
      now.getFullYear(),
      String(now.getMonth() + 1).padStart(2, "0"),
      String(now.getDate()).padStart(2, "0"),
    ].join("-");
    return {
      answer,
      selection,
      charts,
      knowledgeRefs,
      turnIndex,
      date,
    };
  };

  const exportTurn = (format: "md" | "html") => {
    setOpen(false);
    const payload = buildPayload();
    if (payload) onExport(payload, format);
  };

  return (
    <span className="sa-export-wrap" ref={wrapRef}>
      <button
        type="button"
        className="sa-action-icon"
        title="导出本轮"
        aria-label="导出本轮"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <HeaderIcon name="download" />
      </button>
      {open ? (
        <div className="sa-export-menu sa-export-menu-up" role="menu">
          <button
            type="button"
            className="sa-export-item"
            role="menuitem"
            onClick={() => exportTurn("md")}
          >
            导出本轮 Markdown
          </button>
          <button
            type="button"
            className="sa-export-item"
            role="menuitem"
            onClick={() => exportTurn("html")}
          >
            导出本轮 HTML
          </button>
        </div>
      ) : null}
    </span>
  );
}

type CollectedTool = { toolName: string; args: Record<string, unknown> };

function collectTools(messages: readonly unknown[]): CollectedTool[] {
  const out: CollectedTool[] = [];
  for (const item of messages) {
    const message = item as {
      parts?: Array<Record<string, unknown>>;
    };
    for (const part of message.parts ?? []) {
      const type = String(part.type ?? "");
      const name =
        typeof part.toolName === "string"
          ? part.toolName
          : type.startsWith("tool-")
            ? type.slice(5)
            : undefined;
      if (!name) continue;
      const args = (part.args ?? part.input ?? {}) as Record<string, unknown>;
      out.push({ toolName: name, args });
    }
  }
  return out;
}

function buildSuggestions(
  messages: readonly unknown[],
  pageLabel: string | null,
): string[] {
  const tools = collectTools(messages);
  const asked = new Set(
    messages
      .map((item) => item as { role?: string; parts?: Array<Record<string, unknown>> })
      .filter((item) => item.role === "user")
      .flatMap((item) =>
        (item.parts ?? [])
          .filter((part) => part.type === "text")
          .map((part) => String(part.text ?? "").trim()),
      ),
  );
  const out: string[] = [];
  const push = (value: string) => {
    if (value && !asked.has(value) && !out.includes(value)) out.push(value);
  };

  if (tools.length > 0) {
    const names = new Set(tools.map((tool) => tool.toolName));
    const argsPool =
      tools
        .slice()
        .reverse()
        .find(
          (tool) =>
            tool.args &&
            ("metric" in tool.args ||
              "metrics" in tool.args ||
              "numerator_metric" in tool.args),
        )?.args ?? tools[tools.length - 1].args;
    const metric =
      (argsPool.metric as string | undefined) ??
      (Array.isArray(argsPool.metrics)
        ? String(argsPool.metrics[0])
        : undefined) ??
      (argsPool.numerator_metric as string | undefined);
    const columns = Array.isArray(argsPool.columns)
      ? argsPool.columns
      : [];
    const dimension =
      (argsPool.dimension as string | undefined) ??
      columns
        .map((column) => String(column))
        .find((column) => !/date|日期|时间/i.test(column));

    if (metric) {
      if (!names.has("period_compare")) {
        push(`${metric} 和上一个周期相比变化多少？`);
      }
      if (!names.has("dimension_contribution") && dimension) {
        push(`按 ${dimension} 拆解 ${metric} 的变化贡献`);
      }
      if (!names.has("structure_effect")) {
        push(`拆解 ${metric} 的结构效应与效率效应`);
      }
      push(`把 ${metric}${dimension ? `按 ${dimension}` : ""} 做成一张图表`);
    } else if (names.has("list_dashboards") || names.has("get_dashboard_info")) {
      push("这个看板里有哪些图表？");
      push("当前看板生效了哪些筛选？");
    } else if (names.has("list_charts")) {
      push("把这些图表整理到一个新看板");
    }
  }

  if (out.length < 3) {
    if (pageLabel?.startsWith("看板")) push("总结这个看板的核心指标表现");
    for (const suggestion of SUGGESTIONS) {
      if (out.length >= 3) break;
      push(suggestion);
    }
  }
  return out.slice(0, 3);
}

function FollowUpSuggestions() {
  const pageLabel = useContext(PageLabelContext);
  const isRunning = useAssistantState(({ thread }) => thread.isRunning);
  const messages = useAssistantState(({ thread }) => thread.messages);
  const message = useMessage();
  const items = useMemo(
    () => buildSuggestions(messages, pageLabel),
    [messages, pageLabel],
  );
  if (isRunning || !message.isLast || items.length === 0) return null;
  return (
    <div className="sa-followups">
      <span className="sa-followups-label">接着问</span>
      {items.map((item) => (
        <ThreadPrimitive.Suggestion
          key={item}
          prompt={item}
          send
          className="sa-suggestion sa-suggestion-mini"
        >
          {item}
        </ThreadPrimitive.Suggestion>
      ))}
    </div>
  );
}

const PageLabelContext = createContext<string | null>(null);

type MessagePart = {
  type?: string;
  toolName?: string;
  args?: unknown;
  result?: unknown;
  isError?: boolean;
  status?: { type?: string };
  text?: string;
};

function isFailedPart(part: MessagePart): boolean {
  return Boolean(part.isError) || part.status?.type === "incomplete";
}

function StepGroup({ parts }: { parts: MessagePart[] }) {
  const [manual, setManual] = useState<boolean | null>(null);
  const pending = parts.some((part) => part.result === undefined && !isFailedPart(part));
  const open = manual ?? pending;
  const failed = parts.filter(isFailedPart).length;
  if (parts.length === 0) return null;
  return (
    <div className={`sa-steps ${open ? "sa-steps-open" : ""}`}>
      <button
        type="button"
        className="sa-steps-head"
        aria-expanded={open}
        onClick={() => setManual(!open)}
      >
        <span className="sa-steps-label">
          执行了 {parts.length} 步
        </span>
        {failed > 0 ? (
          <span className="sa-steps-fail">{failed} 步失败</span>
        ) : null}
        {pending ? (
          <span className="sa-steps-running">
            <span className="sa-spinner" /> 进行中
          </span>
        ) : null}
        <span className="sa-steps-caret">{open ? "收起 ▴" : "展开 ▾"}</span>
      </button>
      {open ? (
        <div className="sa-steps-body">
          {parts.map((part, index) => (
            <ToolCard
              key={`${part.toolName}-${index}`}
              name={String(part.toolName)}
              part={toToolLike(part as unknown as ToolCallMessagePartProps)}
              variant="step"
              showChart={false}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

const loadKnowledgeContent = (scope: string, id: number) =>
  getKnowledgeContent(scope, id);

function collectKnowledgeRefsOf(parts: MessagePart[]) {
  return collectKnowledgeRefs(
    parts.map((part) => ({
      name: String(part.toolName ?? ""),
      result: part.result,
    })),
  );
}

function collectCharts(parts: MessagePart[]): ChartPayload[] {
  const charts: ChartPayload[] = [];
  parts.forEach((part) => {
    const name = part.toolName;
    if (!name || !isQueryTool(name)) return;
    if (isFailedPart(part) || part.result === undefined) return;
    const chart = buildChartPayload(name, part.result, part.args);
    if (chart) charts.push(chart);
  });
  return charts;
}

function WriteHighlights({ parts }: { parts: MessagePart[] }) {
  const blocks = parts
    .filter(
      (part) =>
        part.toolName === "propose_write" &&
        !isFailedPart(part) &&
        part.result !== undefined,
    )
    .map((part, index) => (
      <WriteActionCard
        key={`write-${index}`}
        proposal={part.result as WriteProposal}
      />
    ));
  if (blocks.length === 0) return null;
  return <div className="sa-highlights">{blocks}</div>;
}

function AssistantMessage() {
  const content = useMessage(
    (message) => (message.content as unknown) as MessagePart[],
  );
  const isRunning = useAssistantState(({ thread }) => thread.isRunning);
  const toolParts = useMemo(
    () => (content || []).filter((part) => Boolean(part?.toolName)),
    [content],
  );
  const thinking = useMemo(() => {
    const chunks: string[] = [];
    for (const part of content || []) {
      if (part.toolName) continue;
      if (typeof part.text !== "string") continue;
      if (part.type === "reasoning") {
        chunks.push(part.text);
      } else if (part.type === "text") {
        const extracted = extractThinking(part.text);
        if (extracted) chunks.push(extracted);
      }
    }
    return chunks.join("\n").trim();
  }, [content]);
  const charts = useMemo(() => collectCharts(toolParts), [toolParts]);
  const knowledgeRefs = useMemo(
    () => collectKnowledgeRefsOf(toolParts),
    [toolParts],
  );
  const items = useMemo(() => {
    const chunks: string[] = [];
    for (const part of content || []) {
      if (part.toolName) continue;
      if (part.type === "text" && typeof part.text === "string") {
        const cleaned = stripThinking(part.text);
        if (cleaned.trim()) chunks.push(cleaned);
      }
    }
    return interleaveCharts(chunks.join("\n\n"), charts);
  }, [content, charts]);
  return (
    <MessagePrimitive.Root className="sa-msg sa-msg-assistant">
      <div className="sa-assistant-avatar">
        <AssistantAvatar follow={false} />
      </div>
      <div className="sa-assistant-body">
        <SelectionTag blocks={useTurnSelection("assistant")} compact />
        <ThinkBlock text={thinking} running={isRunning} />
        <StepGroup parts={toolParts} />
        {items.map((item, index) =>
          item.kind === "chart" ? (
            <ChartBlock key={`chart-${index}`} {...item.chart} />
          ) : (
            <BodyMarkdown key={`text-${index}`} text={item.text} />
          ),
        )}
        <KnowledgeRefs items={knowledgeRefs} loadContent={loadKnowledgeContent} />
        <WriteHighlights parts={toolParts} />
        <MessagePrimitive.Error>
          <div className="sa-error">回答失败，请检查模型或稍后重试。</div>
        </MessagePrimitive.Error>
        <div className="sa-msg-actions-row">
          <AnswerFeedback />
          <CopyAnswer />
          <ExportTurnButton />
        </div>
        <FollowUpSuggestions />
      </div>
    </MessagePrimitive.Root>
  );
}

function EmptyState() {
  const employee = useContext(EmployeeContext);
  return (
    <div className="sa-empty">
      {employee?.avatar ? (
        <span className="sa-empty-emoji" aria-hidden>
          {employee.avatar}
        </span>
      ) : (
        <AssistantAvatar className="sa-empty-avatar" crop="full" />
      )}
      <div style={{ fontWeight: 650, color: "var(--sa-fg)", fontSize: 14 }}>
        {employee
          ? `${employee.nickname}${employee.title ? ` · ${employee.title}` : ""}`
          : "可以直接问数据"}
      </div>
      <div style={{ marginTop: 4 }}>
        {employee
          ? employee.greeting || employee.intro || "告诉我你的需求。"
          : "助手会先看当前页面的数据集和指标，再生成查询或归因拆解。"}
      </div>
      <div className="sa-suggestions">
        {SUGGESTIONS.map((suggestion) => (
          <ThreadPrimitive.Suggestion
            key={suggestion}
            prompt={suggestion}
            send
            className="sa-suggestion"
          >
            {suggestion}
          </ThreadPrimitive.Suggestion>
        ))}
      </div>
    </div>
  );
}

/** 选择区块只在看板页面有意义；宿主没有页面事件，沿用轮询 URL 的做法。 */
/** 只有具体看板（/dashboard/<id>/ 或 /dashboard/p/<key>/）可选区块，列表页不算。 */

function PanelBody({
  onNewChat,
  canAdmin,
  historyOpen,
  knowledgeOpen,
  onOpenHistory,
  onCloseHistory,
  onOpenKnowledge,
  onCloseKnowledge,
  employees,
  employeeId,
  onEmployeeChange,
  models,
  modelId,
  onModelChange,
  reasoningEffort,
  onReasoningChange,
  selectedBlocks,
  picking,
  onTogglePick,
  onRemoveBlock,
  onLoadConversation,
  onDeletedConversation,
  onExport,
  activeConversationId,
  notice,
  resume,
  stoppingResume,
  onStopResume,
}: {
  onNewChat: () => void;
  canAdmin: boolean;
  historyOpen: boolean;
  knowledgeOpen: boolean;
  onOpenHistory: () => void;
  onCloseHistory: () => void;
  onOpenKnowledge: () => void;
  onCloseKnowledge: () => void;
  employees: EmployeeInfo[];
  employeeId: number | null;
  onEmployeeChange: (value: number) => void;
  models: ModelInfo[];
  modelId: number | null;
  onModelChange: (value: number | null) => void;
  reasoningEffort: ReasoningEffort;
  onReasoningChange: (value: ReasoningEffort) => void;
  selectedBlocks: SelectedBlock[];
  picking: boolean;
  onTogglePick: () => void;
  onRemoveBlock: (index: number) => void;
  onLoadConversation: (detail: UserConversationDetail) => void;
  onDeletedConversation: (id: string) => void;
  onExport: (id: string, format: "md" | "html") => void;
  activeConversationId: string;
  notice: string;
  resume: ResumeState | null;
  stoppingResume: boolean;
  onStopResume: () => void;
}) {
  const isRunning = useAssistantState(({ thread }) => thread.isRunning);
  const onDashboard = useIsDashboard();
  const isEmpty = useAssistantState(
    ({ thread }) => thread.messages.length === 0,
  );
  const assistantRuntime = useAssistantRuntime();
  const wasRunning = useRef(false);
  useEffect(() => {
    if (isRunning) {
      wasRunning.current = true;
      return;
    }
    if (wasRunning.current) {
      // 面板一直开着看到结束：不需要重开续看，清掉待恢复记录
      wasRunning.current = false;
      clearPendingRun();
    }
  }, [isRunning]);
  const stopRun = useCallback(() => {
    const runId = getCurrentRunId();
    if (runId) {
      void cancelRun(runId).catch(() => undefined);
    }
    clearPendingRun();
    assistantRuntime.thread.cancelRun();
  }, [assistantRuntime]);
  const [ratings, setRatings] = useState<Record<number, FeedbackRating>>({});
  const [busyTurns, setBusyTurns] = useState<Set<number>>(new Set());
  const [displayMode, setDisplayMode] = useState(chat.getDisplayMode());
  const [fullscreen, setFullscreen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const exportRef = useRef<HTMLDivElement | null>(null);
  const [ratio, setRatio] = useState<PanelRatio>(readPanelRatio);
  const [viewport, setViewport] = useState({
    width: window.innerWidth,
    height: window.innerHeight,
  });
  const size = useMemo(
    () =>
      clampPanelSize(
        ratio.width * viewport.width,
        ratio.height * viewport.height,
      ),
    [ratio, viewport],
  );
  const themeVars = useAssistantTheme();
  const pageLabel = usePageLabel();
  const currentEmployee = useMemo(
    () => employees.find((item) => item.id === employeeId) ?? null,
    [employees, employeeId],
  );
  const availableModels = useMemo(() => {
    if (!currentEmployee) return models;
    const ids = currentEmployee.model_ids ?? [];
    if (ids.length === 0) return models;
    const allowed = new Set(ids);
    return models.filter((model) => allowed.has(model.id));
  }, [currentEmployee, models]);
  const employeeDefaultModelId =
    currentEmployee?.model_id &&
    availableModels.some((model) => model.id === currentEmployee.model_id)
      ? currentEmployee.model_id
      : null;
  const defaultModelId =
    employeeDefaultModelId ??
    availableModels.find((model) => model.is_default)?.id ??
    availableModels[0]?.id ??
    null;
  const selectedModelId =
    modelId && availableModels.some((model) => model.id === modelId)
      ? modelId
      : null;
  const modelLocked = availableModels.length <= 1;
  const sizeRef = useRef(size);

  useEffect(() => {
    sizeRef.current = size;
  }, [size]);

  useEffect(() => {
    const disposable = chat.onDidChangeDisplayMode((mode) =>
      setDisplayMode(mode),
    );
    return () => disposable.dispose();
  }, []);

  useEffect(() => {
    let alive = true;
    setRatings({});
    setBusyTurns(new Set());
    getFeedback(activeConversationId)
      .then((items) => {
        if (!alive) return;
        const next: Record<number, FeedbackRating> = {};
        for (const item of items) {
          next[item.turn_index] = item.rating;
        }
        setRatings(next);
      })
      .catch(() => {
        // Feedback is optional; the chat remains usable.
      });
    return () => {
      alive = false;
    };
  }, [activeConversationId]);

  const rateAnswer = useCallback(
    async (turnIndex: number, rating: FeedbackRating | null) => {
      setBusyTurns((current) => new Set(current).add(turnIndex));
      try {
        await saveFeedback(activeConversationId, turnIndex, rating);
        setRatings((current) => {
          const next = { ...current };
          if (rating) next[turnIndex] = rating;
          else delete next[turnIndex];
          return next;
        });
      } catch {
        // Keep the previous state when persistence fails.
      } finally {
        setBusyTurns((current) => {
          const next = new Set(current);
          next.delete(turnIndex);
          return next;
        });
      }
    },
    [activeConversationId],
  );

  const feedbackValue = useMemo<FeedbackContextValue>(
    () => ({
      conversationId: activeConversationId,
      ratings,
      busyTurns,
      onRate: (turnIndex, rating) => void rateAnswer(turnIndex, rating),
    }),
    [activeConversationId, ratings, busyTurns, rateAnswer],
  );

  useEffect(() => {
    const onResize = () =>
      setViewport({ width: window.innerWidth, height: window.innerHeight });
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && fullscreen) setFullscreen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [fullscreen]);

  useEffect(() => {
    if (!exportOpen) return undefined;
    const onPointerDown = (event: PointerEvent) => {
      if (!exportRef.current?.contains(event.target as Node)) {
        setExportOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setExportOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [exportOpen]);

  const panelRef = useRef<HTMLDivElement | null>(null);

  // 停靠模式：宿主 Splitter 只限制最小宽度，还会把拖出的宽度存进
  // localStorage（common__resizable_sidebar_widths['chat:panel']）下次还原。
  // 这里钳住存储值 + 用样式类注入 max-width（不写内联、不观察 DOM，
  // 避免与 antd 的样式回写互相触发把主线程打满）。
  useEffect(() => {
    if (displayMode !== "panel" || fullscreen) return undefined;
    const host = panelRef.current?.closest(
      ".ant-splitter-panel",
    ) as HTMLElement | null;
    if (!host) return undefined;
    const cap = () => Math.round(window.innerWidth * 0.45);
    const CLASS = "sa-cap-host";
    let style = document.getElementById("sa-splitter-cap") as HTMLStyleElement | null;
    if (!style) {
      style = document.createElement("style");
      style.id = "sa-splitter-cap";
      style.textContent =
        ".ant-splitter-panel.sa-cap-host{max-width:45vw!important}";
      document.head.appendChild(style);
    }
    const clampStored = () => {
      try {
        const raw = window.localStorage.getItem(
          "common__resizable_sidebar_widths",
        );
        if (!raw) return;
        const map = JSON.parse(raw) as Record<string, unknown>;
        const stored = map["chat:panel"];
        if (typeof stored === "number" && stored > cap()) {
          map["chat:panel"] = cap();
          window.localStorage.setItem(
            "common__resizable_sidebar_widths",
            JSON.stringify(map),
          );
        }
      } catch {
        // Local storage may be unavailable.
      }
    };
    const ensure = () => {
      if (!host.classList.contains(CLASS)) host.classList.add(CLASS);
    };
    ensure();
    clampStored();
    const onInteractEnd = () => {
      ensure();
      clampStored();
    };
    window.addEventListener("resize", onInteractEnd);
    window.addEventListener("pointerup", onInteractEnd, true);
    return () => {
      window.removeEventListener("resize", onInteractEnd);
      window.removeEventListener("pointerup", onInteractEnd, true);
      host.classList.remove(CLASS);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [displayMode, fullscreen]);

  const startResize = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (displayMode === "panel") return;
      event.preventDefault();
      event.stopPropagation();
      const startX = event.clientX;
      const startY = event.clientY;
      const startWidth = sizeRef.current.width;
      const startHeight = sizeRef.current.height;
      let lastRatio = ratioOfSize(sizeRef.current);
      const move = (moveEvent: PointerEvent) => {
        const next = clampPanelSize(
          startWidth - (moveEvent.clientX - startX),
          startHeight - (moveEvent.clientY - startY),
        );
        lastRatio = ratioOfSize(next);
        setRatio(lastRatio);
      };
      const stop = () => {
        try {
          window.localStorage.setItem(SIZE_KEY, JSON.stringify(lastRatio));
        } catch {
          // Local storage may be unavailable.
        }
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", stop);
        window.removeEventListener("pointercancel", stop);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", stop);
      window.addEventListener("pointercancel", stop);
    },
    [displayMode],
  );
  const resetSize = useCallback(() => {
    try {
      window.localStorage.removeItem(SIZE_KEY);
    } catch {
      // Local storage may be unavailable.
    }
    setRatio(DEFAULT_PANEL_RATIO);
  }, []);

  const isPanel = displayMode === "panel";

  const panelStyle = {
    ...themeVars,
    ...(!isPanel && !fullscreen
      ? {
          width: size.width,
          height: size.height,
          maxWidth: "calc(100vw - 88px)",
          maxHeight: "calc(100vh - 96px)",
        }
      : {}),
  } as React.CSSProperties;

  return (
    <div
      ref={panelRef}
      className={`sa-panel${fullscreen ? " sa-fullscreen" : ""}${
        isPanel ? " sa-docked" : ""
      }${picking ? " sa-panel-picking" : ""}`}
      style={panelStyle}
    >
      <div className="sa-header">
        <div className="sa-header-row">
          <div className="sa-brand">
            <AssistantAvatar className="sa-brand-avatar" />
            <div className="sa-header-title">
              <h2 className="sa-title" title={pageLabel ?? "数据分析助手"}>
                {pageLabel ?? "数据分析助手"}
              </h2>
              <div className="sa-subtitle">
                {pageLabel ? "数据分析助手 · RLS 生效" : "基于你的 Superset 权限 · RLS 生效"}
              </div>
            </div>
          </div>
          <div className="sa-header-actions">
            <button
              type="button"
              className="sa-icon-btn"
              title={fullscreen ? "退出全屏" : "全屏"}
              aria-label={fullscreen ? "退出全屏" : "全屏"}
              onClick={() => setFullscreen((current) => !current)}
            >
              <HeaderIcon name={fullscreen ? "compress" : "expand"} />
            </button>
            {!isEmpty && !historyOpen && !knowledgeOpen ? (
              <div className="sa-export-wrap" ref={exportRef}>
                <button
                  type="button"
                  className="sa-icon-btn"
                  title="导出当前会话"
                  aria-label="导出当前会话"
                  aria-expanded={exportOpen}
                  onClick={() => setExportOpen((value) => !value)}
                >
                  <HeaderIcon name="download" />
                </button>
                {exportOpen ? (
                  <div className="sa-export-menu" role="menu">
                    <button
                      type="button"
                      className="sa-export-item"
                      role="menuitem"
                      onClick={() => {
                        setExportOpen(false);
                        onExport(activeConversationId, "md");
                      }}
                    >
                      导出 Markdown
                    </button>
                    <button
                      type="button"
                      className="sa-export-item"
                      role="menuitem"
                      onClick={() => {
                        setExportOpen(false);
                        onExport(activeConversationId, "html");
                      }}
                    >
                      导出 HTML
                    </button>
                  </div>
                ) : null}
              </div>
            ) : null}
            <button
              type="button"
              className="sa-icon-btn"
              title={isPanel ? "切换为浮窗" : "停靠到侧边"}
              aria-label={isPanel ? "切换为浮窗" : "停靠到侧边"}
              onClick={() => chat.setDisplayMode(isPanel ? "floating" : "panel")}
            >
              <HeaderIcon name={isPanel ? "floating" : "panel"} />
            </button>
            <button
              type="button"
              className="sa-icon-btn sa-icon-btn-close"
              title="关闭"
              aria-label="关闭"
              onClick={() => {
                setFullscreen(false);
                chat.close();
              }}
            >
              <HeaderIcon name="close" />
            </button>
          </div>
        </div>
        <div className="sa-header-row sa-header-tools">
          <span className="sa-header-spacer" />
          {canAdmin ? (
            <a
              className="sa-icon-btn"
              href="/extensions/dataagent/assistant/admin-redirect"
              target="_blank"
              rel="noopener"
              title="AI 管理后台"
              aria-label="AI 管理后台"
            >
              <HeaderIcon name="admin" />
            </a>
          ) : null}
          <button
            type="button"
            className={`sa-icon-btn ${historyOpen ? "sa-icon-btn-active" : ""}`}
            title="历史对话"
            aria-label="历史对话"
            aria-pressed={historyOpen}
            onClick={onOpenHistory}
          >
            <HeaderIcon name="history" />
          </button>
          <button
            type="button"
            className={`sa-icon-btn ${knowledgeOpen ? "sa-icon-btn-active" : ""}`}
            title="个人知识库"
            aria-label="个人知识库"
            aria-pressed={knowledgeOpen}
            onClick={onOpenKnowledge}
          >
            <HeaderIcon name="knowledge" />
          </button>
          <button
            type="button"
            className="sa-icon-btn"
            title="新对话"
            aria-label="新对话"
            onClick={onNewChat}
          >
            <HeaderIcon name="plus" />
          </button>
        </div>
      </div>

      {notice ? <div className="sa-notice">{notice}</div> : null}

      {!isPanel && !fullscreen ? (
        <div
          className="sa-resize-handle"
          role="separator"
          aria-label="调整浮窗大小"
          title="拖动调整大小，双击恢复默认"
          onPointerDown={startResize}
          onDoubleClick={resetSize}
        />
      ) : null}

      {historyOpen ? (
        <HistoryView
          activeConversationId={activeConversationId}
          onClose={onCloseHistory}
          onLoad={onLoadConversation}
          onDeleted={onDeletedConversation}
          onExport={onExport}
        />
      ) : knowledgeOpen ? (
        <KnowledgeView onClose={onCloseKnowledge} />
      ) : resume ? (
        <ResumeView
          question={resume.question}
          text={resume.text}
          toolCalls={resume.toolCalls}
          elapsedMs={resume.elapsedMs}
          stopping={stoppingResume}
          onStop={onStopResume}
        />
      ) : (
        <EmployeeContext.Provider value={currentEmployee}>
        <FeedbackContext.Provider value={feedbackValue}>
          <PageLabelContext.Provider value={pageLabel}>
          <ThreadPrimitive.Root className="sa-thread">
          {isEmpty ? (
            <div className="sa-messages sa-messages-empty">
              <EmptyState />
            </div>
          ) : (
            <ThreadPrimitive.Viewport
              className="sa-messages"
              autoScroll
              turnAnchor="bottom"
            >
              <ThreadPrimitive.Messages
                components={{ UserMessage, AssistantMessage }}
              />
              {isRunning ? (
                <div className="sa-thinking">
                  <span className="sa-spinner" />
                  正在分析…
                </div>
              ) : null}
            </ThreadPrimitive.Viewport>
          )}

          <ComposerPrimitive.Root className="sa-composer">
            {selectedBlocks.length > 0 ? (
              <div className="sa-selection-chips">
                <span className="sa-selection-hint">仅对下一条消息生效</span>
                {selectedBlocks.map((block, index) => (
                  <span
                    className="sa-selection-chip"
                    key={`${block.kind}-${block.chart_id || block.title}-${index}`}
                  >
                    <span className="sa-selection-kind">
                      {SELECTION_KIND_LABEL[block.kind]}
                    </span>
                    <span className="sa-selection-title" title={block.title}>
                      {block.title}
                    </span>
                    <button
                      type="button"
                      className="sa-selection-remove"
                      aria-label="移除已选区块"
                      onClick={() => onRemoveBlock(index)}
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            ) : null}
            <div className="sa-composer-box">
              <ComposerPrimitive.Input
                className="sa-textarea"
                placeholder={
                  isRunning ? "正在分析…" : "问数据、问归因，或让助手拆解指标"
                }
                rows={2}
                submitOnEnter
              />
              <div className="sa-composer-bar">
                <button
                  type="button"
                  className={`sa-pick-btn ${picking ? "sa-pick-btn-active" : ""}`}
                  title={
                    picking
                      ? "取消选择区块"
                      : onDashboard
                        ? "选择看板图表或筛选器"
                        : "仅在看板页面可用"
                  }
                  aria-pressed={picking}
                  disabled={!onDashboard}
                  onClick={onTogglePick}
                >
                  <svg
                    viewBox="0 0 24 24"
                    width="14"
                    height="14"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    aria-hidden
                  >
                    <path d="M12 3v3M12 18v3M3 12h3M18 12h3" />
                    <circle cx="12" cy="12" r="4.2" />
                  </svg>
                </button>
                {employees.length > 0 ? (
                  <EmployeePicker
                    employees={employees}
                    value={employeeId}
                    onChange={onEmployeeChange}
                  />
                ) : null}
                <ModelPicker
                  models={availableModels}
                  value={selectedModelId}
                  defaultModelId={defaultModelId}
                  defaultLabel={
                    currentEmployee
                      ? currentEmployee.model_id
                        ? "跟随员工默认"
                        : "跟随默认"
                      : undefined
                  }
                  disabled={modelLocked}
                  onChange={onModelChange}
                />
                <ReasoningPicker
                  value={reasoningEffort}
                  onChange={onReasoningChange}
                />
              {isRunning ? (
                <button
                  type="button"
                  className="sa-send sa-stop"
                  title="停止（会同时停止后台生成）"
                  onClick={stopRun}
                >
                  <svg
                    viewBox="0 0 24 24"
                    width="14"
                    height="14"
                    fill="currentColor"
                  >
                    <rect x="6" y="6" width="12" height="12" rx="2" />
                  </svg>
                </button>
              ) : (
                <ComposerPrimitive.Send className="sa-send" title="发送">
                  <svg
                    viewBox="0 0 24 24"
                    width="16"
                    height="16"
                    fill="currentColor"
                  >
                    <path d="M3.4 20.4 21 12 3.4 3.6 3.4 10l12 2-12 2z" />
                  </svg>
                </ComposerPrimitive.Send>
              )}
              </div>
            </div>
            <div className="sa-hint">
              <span>Enter 发送 · Shift+Enter 换行</span>
              <span>查询以你的 Superset 身份执行</span>
            </div>
          </ComposerPrimitive.Root>
          </ThreadPrimitive.Root>
          </PageLabelContext.Provider>
        </FeedbackContext.Provider>
        </EmployeeContext.Provider>
      )}
    </div>
  );
}

function ChatRuntimeHost({
  session,
  canAdmin,
  historyOpen,
  knowledgeOpen,
  employees,
  employeeId,
  onEmployeeChange,
  onEmployeeRevoked,
  models,
  modelId,
  onModelChange,
  reasoningEffort,
  onReasoningChange,
  selectedBlocks,
  picking,
  onTogglePick,
  onRemoveBlock,
  onSelectionConsumed,
  selectionTurns,
  onNewChat,
  onOpenHistory,
  onCloseHistory,
  onOpenKnowledge,
  onCloseKnowledge,
  onLoadConversation,
  onDeletedConversation,
  onExport,
  onExportTurn,
  notice,
  resume,
  stoppingResume,
  onStopResume,
}: {
  session: ChatSession;
  canAdmin: boolean;
  historyOpen: boolean;
  knowledgeOpen: boolean;
  employees: EmployeeInfo[];
  employeeId: number | null;
  onEmployeeChange: (value: number) => void;
  onEmployeeRevoked: () => void;
  models: ModelInfo[];
  modelId: number | null;
  onModelChange: (value: number | null) => void;
  reasoningEffort: ReasoningEffort;
  onReasoningChange: (value: ReasoningEffort) => void;
  selectedBlocks: SelectedBlock[];
  picking: boolean;
  onTogglePick: () => void;
  onRemoveBlock: (index: number) => void;
  onSelectionConsumed: (blocks: SelectedBlock[]) => void;
  selectionTurns: SelectedBlock[][];
  onNewChat: () => void;
  onOpenHistory: () => void;
  onCloseHistory: () => void;
  onOpenKnowledge: () => void;
  onCloseKnowledge: () => void;
  onLoadConversation: (detail: UserConversationDetail) => void;
  onDeletedConversation: (id: string) => void;
  onExport: (id: string, format: "md" | "html") => void;
  onExportTurn: (data: TurnExportData, format: "md" | "html") => void;
  notice: string;
  resume: ResumeState | null;
  stoppingResume: boolean;
  onStopResume: () => void;
}) {
  const employeeRef = useRef(employeeId);
  useEffect(() => {
    employeeRef.current = employeeId;
  }, [employeeId]);
  const modelRef = useRef(modelId);
  useEffect(() => {
    modelRef.current = modelId;
  }, [modelId]);
  const reasoningRef = useRef(reasoningEffort);
  useEffect(() => {
    reasoningRef.current = reasoningEffort;
  }, [reasoningEffort]);
  const selectedRef = useRef(selectedBlocks);
  useEffect(() => {
    selectedRef.current = selectedBlocks;
  }, [selectedBlocks]);
  const transport = useMemo(
    () =>
      new DefaultChatTransport({
        api: `${agentBaseUrl()}/api/chat`,
        headers: async (): Promise<Record<string, string>> => {
          const token = await fetchToken();
          const pageContext = await collectPageContext();
          const headers: Record<string, string> = {
            Authorization: `Bearer ${token}`,
            "X-Conversation-Id": session.conversationId,
            "X-Superset-Context": encodePageContext(pageContext),
          };
          if (employeeRef.current) {
            headers["X-Employee-Id"] = String(employeeRef.current);
          }
          if (modelRef.current) {
            headers["X-Model-Id"] = String(modelRef.current);
          }
          if (reasoningRef.current !== "default") {
            headers["X-Reasoning-Effort"] = reasoningRef.current;
          }
          // 选区只对刚发出的这条消息生效：上下文已写入，随后记到该轮并清空输入区
          onSelectionConsumed(selectedRef.current);
          return headers;
        },
        fetch: async (input, init) => {
          let response = await fetch(input as RequestInfo, init);
          if (response.status === 403 && employeeRef.current) {
            // 员工被取消授权：本地回退到第一个可用员工，避免每条消息都撞 403
            onEmployeeRevoked();
            return response;
          }
          if (response.status === 401) {
            clearToken();
            const token = await fetchToken(true);
            const headers = new Headers(init?.headers);
            headers.set("Authorization", `Bearer ${token}`);
            headers.set("X-Conversation-Id", session.conversationId);
            if (!headers.has("X-Superset-Context")) {
              headers.set(
                "X-Superset-Context",
                encodePageContext(await collectPageContext()),
              );
            }
            response = await fetch(input as RequestInfo, { ...init, headers });
          }
          if (response.ok) {
            // 记录本轮 run：关面板/断网后重新打开时用来续看，并支持「停止」真正停掉服务端生成
            const runId = response.headers.get("x-run-id");
            if (runId) {
              writePendingRun({
                conversationId: session.conversationId,
                runId,
                question: lastUserText(init),
                startedAt: Date.now(),
              });
            }
          }
          return response.ok ? guardStreamIdle(response) : response;
        },
      }),
    [session.conversationId, onEmployeeRevoked, onSelectionConsumed],
  );

  const runtime = useChatRuntime({
    transport,
    id: session.conversationId,
    messages: session.initialMessages,
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <WriteBatchProvider conversationId={session.conversationId}>
      <SelectionTurnsContext.Provider value={selectionTurns}>
      <TurnExportContext.Provider
        value={(payload, format) =>
          onExportTurn(
            { ...payload, conversationId: session.conversationId },
            format,
          )
        }
      >
      <PanelBody
        onNewChat={onNewChat}
        canAdmin={canAdmin}
        historyOpen={historyOpen}
        knowledgeOpen={knowledgeOpen}
        onOpenHistory={onOpenHistory}
        onCloseHistory={onCloseHistory}
        onOpenKnowledge={onOpenKnowledge}
        onCloseKnowledge={onCloseKnowledge}
        employees={employees}
        employeeId={employeeId}
        onEmployeeChange={onEmployeeChange}
        models={models}
        modelId={modelId}
        onModelChange={onModelChange}
        reasoningEffort={reasoningEffort}
        onReasoningChange={onReasoningChange}
        selectedBlocks={selectedBlocks}
        picking={picking}
        onTogglePick={onTogglePick}
        onRemoveBlock={onRemoveBlock}
        onLoadConversation={onLoadConversation}
        onDeletedConversation={onDeletedConversation}
        onExport={onExport}
        activeConversationId={session.conversationId}
        notice={notice}
        resume={resume}
        stoppingResume={stoppingResume}
        onStopResume={onStopResume}
      />
      </TurnExportContext.Provider>
      </SelectionTurnsContext.Provider>
      </WriteBatchProvider>
    </AssistantRuntimeProvider>
  );
}

export default function ChatPanel() {
  const [session, setSession] = useState<ChatSession>(newSession);
  const [canAdmin, setCanAdmin] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [knowledgeOpen, setKnowledgeOpen] = useState(false);
  const [notice, setNotice] = useState("");
  const [allowed, setAllowed] = useState<boolean | null>(null);
  const [employees, setEmployees] = useState<EmployeeInfo[]>([]);
  const [selectedBlocks, setSelectedBlocks] = useState<SelectedBlock[]>([]);
  const [selectionTurns, setSelectionTurns] = useState<SelectedBlock[][]>(
    session.initialSelections ?? [],
  );
  const [picking, setPicking] = useState(false);
  const [resume, setResume] = useState<ResumeState | null>(null);
  const [stoppingResume, setStoppingResume] = useState(false);

  useEffect(() => {
    setSelectionContext(selectedBlocks);
  }, [selectedBlocks]);

  useEffect(() => {
    setSelectionTurns(session.initialSelections ?? []);
  }, [session.key, session.initialSelections]);

  useEffect(() => {
    let last = window.location.href;
    const timer = window.setInterval(() => {
      if (window.location.href === last) return;
      last = window.location.href;
      setSelectedBlocks([]);
      setPicking(false);
    }, 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!picking) return undefined;
    const box = document.createElement("div");
    box.className = "sa-block-highlight";
    const label = document.createElement("div");
    label.className = "sa-block-highlight-label";
    box.appendChild(label);
    document.body.appendChild(box);

    // 面板在选择态是透明的（要能点到底下的图表），所以提示与取消入口放在 body 级 HUD 上
    const hud = document.createElement("div");
    hud.className = "sa-pick-hud";
    const hudText = document.createElement("span");
    hudText.textContent = "选择中：点击看板的图表或筛选器 · Esc 取消";
    const hudCancel = document.createElement("button");
    hudCancel.type = "button";
    hudCancel.textContent = "取消";
    hudCancel.addEventListener("click", () => setPicking(false));
    hud.append(hudText, hudCancel);
    document.body.appendChild(hud);

    const ignore = (target: Element | null) =>
      !target ||
      target === document.documentElement ||
      target === document.body ||
      Boolean(target.closest(".sa-panel")) ||
      Boolean(target.closest(".sa-pick-hud")) ||
      Boolean(target.closest(".sa-block-highlight"));

    const onMove = (event: MouseEvent) => {
      const target = event.target as Element | null;
      if (ignore(target)) {
        box.style.display = "none";
        return;
      }
      const found = target ? resolveSelectedBlock(target) : null;
      if (!found) {
        box.style.display = "none";
        return;
      }
      const rect = found.rect;
      box.style.display = "block";
      box.style.left = `${Math.max(0, rect.left - 2)}px`;
      box.style.top = `${Math.max(0, rect.top - 2)}px`;
      box.style.width = `${Math.max(0, rect.width + 4)}px`;
      box.style.height = `${Math.max(0, rect.height + 4)}px`;
      label.textContent = `${SELECTION_KIND_LABEL[found.block.kind]} · ${found.block.title}`;
    };

    const onClick = (event: MouseEvent) => {
      const target = event.target as Element | null;
      if (ignore(target)) return;
      const found = target ? resolveSelectedBlock(target) : null;
      if (!found) return;
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      setSelectedBlocks((current) => {
        const key = found.block.chart_id || found.block.title;
        if (
          current.some(
            (item) => (item.chart_id || item.title) === key,
          )
        ) {
          return current;
        }
        return [...current, found.block].slice(0, 3);
      });
      setPicking(false);
    };

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPicking(false);
    };

    document.addEventListener("mousemove", onMove, true);
    document.addEventListener("click", onClick, true);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("mousemove", onMove, true);
      document.removeEventListener("click", onClick, true);
      document.removeEventListener("keydown", onKey, true);
      box.remove();
      hud.remove();
    };
  }, [picking]);

  const removeBlock = useCallback((index: number) => {
    setSelectedBlocks((current) => current.filter((_, i) => i !== index));
  }, []);

  const consumeSelection = useCallback((blocks: SelectedBlock[]) => {
    setSelectionTurns((current) => [...current, blocks]);
    setSelectedBlocks([]);
  }, []);
  const [employeeId, setEmployeeId] = useState<number | null>(readEmployeeId);
  const [firstEmployeeId, setFirstEmployeeId] = useState<number | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [modelId, setModelId] = useState<number | null>(readModelId);
  const [reasoningEffort, setReasoningEffort] =
    useState<ReasoningEffort>(readReasoningEffort);

  useEffect(() => {
    let alive = true;
    // 一次 /api/me 同时决定「是否显示助手」和「是否显示管理入口」
    fetchMe()
      .then((me) => {
        if (!alive) return;
        const allowed =
          me !== null && me.ai_enabled !== false && me.has_employees !== false;
        setAllowed(allowed);
        setCanAdmin(Boolean(me?.can_admin));
        if (!allowed) chat.close();
      })
      .catch(() => {
        if (alive) setAllowed(true);
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const token = await fetchToken();
        const response = await fetch(`${agentBaseUrl()}/api/employees`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!response.ok) return;
        const body = await response.json();
        const list: EmployeeInfo[] = Array.isArray(body.items) ? body.items : [];
        if (!alive) return;
        const fallback = list[0]?.id ?? null;
        setEmployees(list);
        setFirstEmployeeId(fallback);
        // 选中的员工被删除/停用后回退到第一个可用员工
        setEmployeeId((current) => {
          if (current && list.some((item) => item.id === current)) {
            return current;
          }
          if (current) {
            try {
              window.localStorage.removeItem(EMPLOYEE_KEY);
            } catch {
              // ignore
            }
          }
          return fallback;
        });
      } catch {
        // 员工列表失败时保留当前选择
      }
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const token = await fetchToken();
        const response = await fetch(`${agentBaseUrl()}/api/models`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!response.ok) return;
        const body = await response.json();
        const list: ModelInfo[] = Array.isArray(body.items) ? body.items : [];
        if (!alive) return;
        setModels(list);
        setModelId((current) => {
          if (current && !list.some((item) => item.id === current)) {
            try {
              window.localStorage.removeItem(MODEL_KEY);
            } catch {
              // ignore
            }
            return null;
          }
          return current;
        });
      } catch {
        // 模型列表失败时继续使用系统默认模型
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!modelId) return;
    const employee = employees.find((item) => item.id === employeeId);
    const allowed =
      employee?.model_ids && employee.model_ids.length > 0
        ? new Set(employee.model_ids)
        : null;
    if (
      !models.some((item) => item.id === modelId) ||
      (allowed !== null && !allowed.has(modelId))
    ) {
      setModelId(null);
      try {
        window.localStorage.removeItem(MODEL_KEY);
      } catch {
        // ignore
      }
    }
  }, [employeeId, employees, modelId, models]);

  const revokeEmployee = useCallback(() => {
    setEmployeeId(firstEmployeeId);
    try {
      window.localStorage.removeItem(EMPLOYEE_KEY);
    } catch {
      // ignore
    }
    setNotice(
      firstEmployeeId
        ? "该 AI 员工已不可用，已切换到默认 AI 牛马，请重新发送"
        : "当前角色没有可用的 AI 牛马，请联系管理员",
    );
  }, [firstEmployeeId]);

  const changeEmployee = useCallback((value: number) => {
    setEmployeeId(value);
    try {
      window.localStorage.setItem(EMPLOYEE_KEY, String(value));
    } catch {
      // ignore
    }
    // 换员工等于换人设，新开会话避免上下文串人
    clearPendingRun();
    setResume(null);
    setStoppingResume(false);
    setSession(newSession());
    setHistoryOpen(false);
    setKnowledgeOpen(false);
    setNotice("");
  }, []);

  const changeModel = useCallback((value: number | null) => {
    setModelId(value);
    try {
      if (value) window.localStorage.setItem(MODEL_KEY, String(value));
      else window.localStorage.removeItem(MODEL_KEY);
    } catch {
      // ignore
    }
  }, []);

  const changeReasoning = useCallback((value: ReasoningEffort) => {
    setReasoningEffort(value);
    try {
      if (value === "default") {
        window.localStorage.removeItem(REASONING_KEY);
      } else {
        window.localStorage.setItem(REASONING_KEY, value);
      }
    } catch {
      // ignore
    }
  }, []);

  const startNewChat = useCallback(() => {
    clearPendingRun();
    setResume(null);
    setStoppingResume(false);
    setSession(newSession());
    setHistoryOpen(false);
    setKnowledgeOpen(false);
    setNotice("");
  }, []);

  const loadConversation = useCallback((detail: UserConversationDetail) => {
    setSession({
      key: newConversationId(),
      conversationId: detail.id,
      initialMessages: historyToMessages(detail),
      initialSelections: historyToSelections(detail),
    });
    setHistoryOpen(false);
    setKnowledgeOpen(false);
    setNotice("");
  }, []);

  const finishPendingRun = useCallback(
    async (conversationId: string) => {
      const detail = await getConversation(conversationId).catch(() => null);
      setResume(null);
      setStoppingResume(false);
      clearPendingRun();
      if (detail && detail.messages.length) {
        loadConversation(detail);
      }
    },
    [loadConversation],
  );

  // 面板重新打开时恢复「上次没看完的回答」：还在跑就显示后台进度，跑完自动载入完整会话
  useEffect(() => {
    const pending = readPendingRun();
    if (!pending) return undefined;
    let alive = true;
    let timer: number | undefined;

    const poll = async () => {
      let run: RunInfo | null = null;
      try {
        run = await getRun(pending.runId);
      } catch {
        run = null;
      }
      if (!alive) return;
      if (run && run.status === "running") {
        setResume({
          conversationId: pending.conversationId,
          runId: pending.runId,
          question: pending.question || run.question,
          text: run.text,
          toolCalls: run.tool_calls,
          elapsedMs: run.elapsed_ms,
        });
        timer = window.setTimeout(() => void poll(), 2000);
        return;
      }
      await finishPendingRun(pending.conversationId);
    };

    void poll();
    return () => {
      alive = false;
      if (timer) window.clearTimeout(timer);
    };
    // 只在面板挂载时恢复一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const stopResume = useCallback(async () => {
    if (!resume) return;
    setStoppingResume(true);
    try {
      await cancelRun(resume.runId);
    } catch {
      // 轮询会把最终状态收敛掉
    }
  }, [resume]);

  const handleDeleted = useCallback(
    (id: string) => {
      setNotice("对话已删除");
      if (id === session.conversationId) {
        setSession(newSession());
        setHistoryOpen(false);
      }
    },
    [session.conversationId],
  );

  const handleExport = useCallback(
    async (id: string, format: "md" | "html") => {
      try {
        if (format === "html") {
          const detail = await getConversation(id);
          // 导出才加载 renderer（react-dom/server 不进首屏 chunk）
          const { downloadConversationHtml } = await import("./exportHtml");
          downloadConversationHtml(detail);
          setNotice("会话已导出为 HTML");
        } else {
          const { blob, filename } = await exportConversation(id);
          downloadBlob(filename, blob);
          setNotice("会话导出已开始");
        }
      } catch (exc) {
        setNotice(
          exc instanceof Error ? `导出失败：${exc.message}` : "导出失败",
        );
      }
    },
    [],
  );

  const handleExportTurn = useCallback(
    async (data: TurnExportData, format: "md" | "html") => {
      try {
        const mod = await import("./exportHtml");
        if (format === "html") mod.downloadTurnHtml(data);
        else mod.downloadTurnMarkdown(data);
        setNotice(
          `第 ${data.turnIndex} 轮已导出为 ${
            format === "html" ? "HTML" : "Markdown"
          }`,
        );
      } catch (exc) {
        setNotice(
          exc instanceof Error ? `导出失败：${exc.message}` : "导出失败",
        );
      }
    },
    [],
  );

  if (allowed !== true) {
    return null;
  }

  return (
    <ChatRuntimeHost
      key={session.key}
      session={session}
      canAdmin={canAdmin}
      historyOpen={historyOpen}
      knowledgeOpen={knowledgeOpen}
      onNewChat={startNewChat}
      onOpenHistory={() => setHistoryOpen(true)}
      onCloseHistory={() => setHistoryOpen(false)}
      onOpenKnowledge={() => {
        setKnowledgeOpen(true);
        setHistoryOpen(false);
      }}
      onCloseKnowledge={() => setKnowledgeOpen(false)}
      employees={employees}
      employeeId={employeeId}
      onEmployeeChange={changeEmployee}
      onEmployeeRevoked={revokeEmployee}
      models={models}
      modelId={modelId}
      onModelChange={changeModel}
      reasoningEffort={reasoningEffort}
      onReasoningChange={changeReasoning}
      selectedBlocks={selectedBlocks}
      picking={picking}
      onTogglePick={() => setPicking((value) => !value)}
      onRemoveBlock={removeBlock}
      onSelectionConsumed={consumeSelection}
      selectionTurns={selectionTurns}
      onLoadConversation={loadConversation}
      onDeletedConversation={handleDeleted}
      onExport={handleExport}
      onExportTurn={handleExportTurn}
      notice={notice}
      resume={resume}
      stoppingResume={stoppingResume}
      onStopResume={() => void stopResume()}
    />
  );
}

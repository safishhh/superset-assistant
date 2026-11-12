import { useEffect, useState } from "react";
import type { UIMessage } from "ai";

import { splitLayout } from "./chartLayout";
import { resolvePageObjectLabel, type SelectedBlock } from "./context";
import { normalizeToolResult } from "./toolResult";
import type {
  UserConversationDetail,
  UserMessage,
  UserToolCall,
} from "./userApi";

export const SUGGESTIONS = [
  "各区域销售额是多少？",
  "为什么 2026 年 9 月销售额下降？",
  "按品类看销售额贡献",
  "2026 年 10 月和上个月同期相比怎么样？",
];

const STREAM_IDLE_TIMEOUT_MS = 200_000;

/** 兜底：服务端长时间不吐数据时中断流，避免界面永远“生成中”。 */
export function guardStreamIdle(response: Response): Response {
  if (!response.body) return response;
  const reader = response.body.getReader();
  let timer: number | undefined;
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const arm = () => {
        window.clearTimeout(timer);
        timer = window.setTimeout(() => {
          controller.error(new Error("模型长时间无响应，请重试"));
          void reader.cancel().catch(() => undefined);
        }, STREAM_IDLE_TIMEOUT_MS);
      };
      arm();
      const pump = async () => {
        try {
          for (;;) {
            const { done, value } = await reader.read();
            if (done) {
              window.clearTimeout(timer);
              controller.close();
              return;
            }
            arm();
            controller.enqueue(value);
          }
        } catch (error) {
          window.clearTimeout(timer);
          controller.error(error);
        }
      };
      void pump();
    },
    cancel() {
      window.clearTimeout(timer);
      void reader.cancel().catch(() => undefined);
    },
  });
  return new Response(stream, {
    status: response.status,
    statusText: response.statusText,
    headers: response.headers,
  });
}

/** 从请求体里取最后一条用户消息文本，供「后台生成中」续看展示。 */
export function lastUserText(init?: RequestInit): string {
  try {
    const body = JSON.parse(String(init?.body ?? ""));
    const messages = Array.isArray(body?.messages) ? body.messages : [];
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const message = messages[index];
      if (!message || message.role !== "user") continue;
      const parts = Array.isArray(message.parts) ? message.parts : [];
      const text = parts
        .filter((part: any) => part?.type === "text" && typeof part.text === "string")
        .map((part: any) => part.text)
        .join("\n");
      return text.replace(/^\[\[sa-continue\]\]\s*/, "").trim();
    }
  } catch {
    // ignore
  }
  return "";
}

export const SIZE_KEY = "sa-assistant-panel-size-v2";const LEGACY_SIZE_KEY = "sa-assistant-panel-size";
const MIN_PANEL_WIDTH = 320;
const MIN_PANEL_HEIGHT = 380;
// 浮窗尺寸按视口比例记录：1366×768、1920×1080、4K 下保持相近占比
export const DEFAULT_PANEL_RATIO = { width: 0.26, height: 0.64 };
const MAX_PANEL_RATIO = { width: 0.6, height: 0.95 };

export type PanelSize = { width: number; height: number };
export type PanelRatio = { width: number; height: number };

export type ChatSession = {
  key: string;
  conversationId: string;
  initialMessages: UIMessage[];
  initialSelections?: SelectedBlock[][];
};

export type ResumeState = {
  conversationId: string;
  runId: string;
  question: string;
  text: string;
  toolCalls: number;
  elapsedMs: number;
};

export function clampPanelSize(width: number, height: number): PanelSize {
  const maxWidth = Math.max(
    MIN_PANEL_WIDTH,
    Math.min(window.innerWidth * MAX_PANEL_RATIO.width, window.innerWidth - 88),
  );
  const maxHeight = Math.max(
    MIN_PANEL_HEIGHT,
    Math.min(
      window.innerHeight * MAX_PANEL_RATIO.height,
      window.innerHeight - 96,
    ),
  );
  return {
    width: Math.round(Math.min(Math.max(width, MIN_PANEL_WIDTH), maxWidth)),
    height: Math.round(
      Math.min(Math.max(height, MIN_PANEL_HEIGHT), maxHeight),
    ),
  };
}

export function ratioOfSize(size: PanelSize): PanelRatio {
  return {
    width: size.width / Math.max(1, window.innerWidth),
    height: size.height / Math.max(1, window.innerHeight),
  };
}

function normalizeRatio(value: {
  width?: unknown;
  height?: unknown;
}): PanelRatio | null {
  if (
    typeof value.width !== "number" ||
    typeof value.height !== "number" ||
    !Number.isFinite(value.width) ||
    !Number.isFinite(value.height)
  ) {
    return null;
  }
  return {
    width: Math.min(Math.max(value.width, 0.16), MAX_PANEL_RATIO.width),
    height: Math.min(Math.max(value.height, 0.3), MAX_PANEL_RATIO.height),
  };
}

export function readPanelRatio(): PanelRatio {
  try {
    const raw = window.localStorage.getItem(SIZE_KEY);
    if (raw) {
      const ratio = normalizeRatio(JSON.parse(raw) ?? {});
      if (ratio) return ratio;
    }
    const legacy = window.localStorage.getItem(LEGACY_SIZE_KEY);
    if (legacy) {
      const value = JSON.parse(legacy) as { width?: unknown; height?: unknown };
      if (typeof value.width === "number" && typeof value.height === "number") {
        const ratio = normalizeRatio(
          ratioOfSize({ width: value.width, height: value.height }),
        );
        if (ratio) {
          window.localStorage.setItem(SIZE_KEY, JSON.stringify(ratio));
          window.localStorage.removeItem(LEGACY_SIZE_KEY);
          return ratio;
        }
      }
    }
  } catch {
    // Local storage may be unavailable.
  }
  return DEFAULT_PANEL_RATIO;
}

function isDashboardView(): boolean {
  return /\/dashboard\/(?!list\/?$)[^/]+/.test(window.location.pathname);
}

export function useIsDashboard(): boolean {
  const [onDashboard, setOnDashboard] = useState(isDashboardView);
  useEffect(() => {
    const sync = () => setOnDashboard(isDashboardView());
    window.addEventListener("popstate", sync);
    const timer = window.setInterval(sync, 800);
    return () => {
      window.removeEventListener("popstate", sync);
      window.clearInterval(timer);
    };
  }, []);
  return onDashboard;
}

export function usePageLabel(): string | null {
  const [label, setLabel] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    let href = "";
    let loading = false;
    const refresh = async () => {
      const nextHref = window.location.href;
      if (loading || nextHref === href) return;
      href = nextHref;
      loading = true;
      const next = await resolvePageObjectLabel();
      loading = false;
      if (alive) setLabel(next);
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 1200);
    const onPopState = () => void refresh();
    window.addEventListener("popstate", onPopState);
    return () => {
      alive = false;
      window.clearInterval(timer);
      window.removeEventListener("popstate", onPopState);
    };
  }, []);

  return label;
}

export function newConversationId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `conv-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function newSession(): ChatSession {
  return {
    key: newConversationId(),
    conversationId: newConversationId(),
    initialMessages: [],
    initialSelections: [],
  };
}

export function historyToSelections(detail: UserConversationDetail): SelectedBlock[][] {
  return detail.messages
    .filter((message) => message.role === "user")
    .map((message) => message.selection ?? []);
}

type HistoryTurn = {
  runId: string;
  user?: UserMessage;
  assistant?: UserMessage;
};

function buildHistoryTurns(detail: UserConversationDetail): HistoryTurn[] {
  const turns: HistoryTurn[] = [];
  const byRun = new Map<string, HistoryTurn>();
  for (const message of detail.messages) {
    const runId = message.run_id || `message-${message.id}`;
    let turn = byRun.get(runId);
    if (!turn) {
      turn = { runId };
      byRun.set(runId, turn);
      turns.push(turn);
    }
    if (message.role === "user") turn.user = message;
    else turn.assistant = message;
  }
  return turns;
}

export function historyToolPart(tool: UserToolCall): UIMessage["parts"][number] {
  const failed = tool.status === "error";
  const part: Record<string, unknown> = {
    type: `tool-${tool.tool_name}`,
    toolCallId: `history-${tool.id}`,
    state: failed ? "output-error" : "output-available",
    input: tool.args_json ?? {},
  };
  if (failed) {
    part.errorText = tool.error || "工具执行失败";
  } else {
    part.output = normalizeToolResult(tool.tool_name, tool.result_json);
  }
  return part as UIMessage["parts"][number];
}

/** 继续对话：把历史轮次还原成带工具步骤/图表/思考的完整消息。 */
export function historyToMessages(detail: UserConversationDetail): UIMessage[] {
  const toolsByRun = new Map<string, UserToolCall[]>();
  for (const tool of detail.tool_calls) {
    const list = toolsByRun.get(tool.run_id) ?? [];
    list.push(tool);
    toolsByRun.set(tool.run_id, list);
  }
  const messages: UIMessage[] = [];
  for (const turn of buildHistoryTurns(detail)) {
    if (turn.user) {
      messages.push({
        id: `history-u-${turn.user.id}`,
        role: "user",
        parts: [{ type: "text", text: turn.user.content || "" }],
      });
    }
    const tools = (toolsByRun.get(turn.runId) ?? []).sort(
      (a, b) => a.sequence - b.sequence,
    );
    const parts: UIMessage["parts"] = [];
    const assistant = turn.assistant;
    if (assistant?.parts?.length && assistant.content) {
      const queues = new Map<string, UserToolCall[]>();
      for (const tool of tools) {
        const queue = queues.get(tool.tool_name) ?? [];
        queue.push(tool);
        queues.set(tool.tool_name, queue);
      }
      for (const entry of splitLayout(assistant.content, assistant.parts)) {
        if (entry.kind === "text") {
          parts.push({ type: "text", text: entry.text });
        } else {
          const tool = queues.get(entry.name)?.shift();
          if (tool) parts.push(historyToolPart(tool));
        }
      }
      for (const queue of queues.values()) {
        for (const tool of queue) parts.push(historyToolPart(tool));
      }
    } else {
      if (assistant?.content) {
        parts.push({ type: "text", text: assistant.content });
      }
      for (const tool of tools) parts.push(historyToolPart(tool));
    }
    if (turn.assistant || tools.length) {
      messages.push({
        id: `history-a-${turn.assistant?.id ?? turn.runId}`,
        role: "assistant",
        parts,
      });
    }
  }
  return messages;
}

/** 原生筛选器：从标题往上找同时包含当前值的那层容器 */
function resolveFilterBlock(target: Element) {
  const title = target.closest('[data-test="filter-control-name"]') as HTMLElement | null;
  if (!title) return null;
  let host: HTMLElement | null = title.parentElement;
  for (let depth = 0; host && depth < 5; depth += 1) {
    if (host.querySelector('[data-test="form-item-value"]')) break;
    host = host.parentElement;
  }
  const box = host ?? title.parentElement ?? title;
  const value =
    box
      .querySelector('[data-test="form-item-value"]')
      ?.textContent?.replace(/\s+/g, " ")
      .trim() || "";
  const name = title.textContent?.replace(/\s+/g, " ").trim() || "筛选器";
  return {
    block: {
      kind: "filter" as const,
      title: name.slice(0, 80),
      text: `${name}=${value || "未选择"}`.slice(0, 200),
    },
    rect: box.getBoundingClientRect(),
  };
}

export function resolveSelectedBlock(
  target: Element,
): { block: SelectedBlock; rect: DOMRect } | null {
  const filter = resolveFilterBlock(target);
  if (filter) return filter;
  const chart = target.closest(
    '[data-test="chart-grid-component"]',
  ) as HTMLElement | null;
  if (chart) {
    const chartId = chart.getAttribute("data-test-chart-id") || undefined;
    const name = chart.getAttribute("data-test-chart-name") || "";
    return {
      block: {
        kind: "chart",
        chart_id: chartId,
        title: (name || "图表").slice(0, 80),
      },
      rect: chart.getBoundingClientRect(),
    };
  }
  const component = target.closest(".dashboard-component") as HTMLElement | null;
  if (component) {
    const heading =
      component
        .querySelector("h1,h2,h3,h4,h5,.header-title")
        ?.textContent?.trim() || "";
    const text = (component.innerText || "").replace(/\s+/g, " ").trim();
    return {
      block: {
        kind: "block",
        title: (heading || text.slice(0, 40) || "页面区块").slice(0, 80),
        text: text.slice(0, 500),
      },
      rect: component.getBoundingClientRect(),
    };
  }
  const chartContainer = target.closest(
    '[data-test="chart-container"]',
  ) as HTMLElement | null;
  if (chartContainer) {
    const text = (chartContainer.innerText || "").replace(/\s+/g, " ").trim();
    return {
      block: {
        kind: "block",
        title: (text.slice(0, 40) || "图表区块").slice(0, 80),
        text: text.slice(0, 500),
      },
      rect: chartContainer.getBoundingClientRect(),
    };
  }
  return null;
}

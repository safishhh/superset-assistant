import { agentBaseUrl, clearToken, fetchToken } from "./api";

export type UserConversation = {
  id: string;
  title: string;
  username: string;
  model_name: string;
  started_at: string;
  last_at: string;
  status: string;
  run_count: number;
  input_tokens: number;
  output_tokens: number;
  cost: number;
  deleted?: boolean;
};

import type { SelectedBlock } from "./context";

export type UserMessage = {
  id: number;
  run_id: string;
  role: "user" | "assistant";
  content: string;
  model_name: string;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  status: string;
  error: string;
  selection?: SelectedBlock[] | null;
  parts?: Array<
    { type: "text"; len: number } | { type: "tool"; name: string }
  > | null;
  created_at: string;
};

export type UserToolCall = {
  id: number;
  run_id: string;
  sequence: number;
  tool_name: string;
  args_json: unknown;
  result_json: unknown;
  sql_text: string;
  row_count: number;
  duration_ms: number;
  status: string;
  error: string;
  created_at: string;
};

export type UserConversationDetail = UserConversation & {
  messages: UserMessage[];
  tool_calls: UserToolCall[];
};

export type RunInfo = {
  run_id: string;
  conversation_id: string;
  status: "running" | "ok" | "error" | "canceled";
  text: string;
  tool_calls: number;
  question: string;
  model: string;
  employee: string;
  error: string;
  started_at: number;
  finished_at: number;
  elapsed_ms: number;
};

export type PendingWriteAction = {
  id: string;
  action_type: string;
  risk_level: string;
  summary: string;
  expires_at: string;
};

export type BatchActionResult = {
  action_id: string;
  status: string;
  result?: Record<string, any> | null;
  rollback?: Record<string, any> | null;
  error?: string;
  expires_at?: string;
};

export type BatchConfirmResult = {
  results: BatchActionResult[];
  executed: number;
  failed: number;
  remaining: number;
};

export type FeedbackRating = "up" | "down";

export type TurnFeedback = {
  turn_index: number;
  rating: FeedbackRating;
  comment: string;
  updated_at: string;
};

export type Paged<T> = {
  total: number;
  page: number;
  page_size: number;
  items: T[];
};

export type KnowledgeItem = {
  id: number;
  title: string;
  content: string;
  source: string;
  hits?: number;
  content_chars?: number;
  truncated?: boolean;
  last_used_at?: string;
  deleted_at?: string;
  condensed?: boolean;
  created_at: string;
  updated_at: string;
};

export type KnowledgeUsage = {
  manual_used: number;
  manual_max: number;
  auto_used: number;
  auto_max: number;
  trash: number;
};

/** 普通请求超时：避免接口挂起时页面一直 loading（聊天流另有用时兜底）。 */
const REQUEST_TIMEOUT_MS = 30_000;

function withTimeout(init: RequestInit, timeoutMs = REQUEST_TIMEOUT_MS): RequestInit {
  if (init.signal) return init;
  return { ...init, signal: AbortSignal.timeout(timeoutMs) };
}

async function authFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = await fetchToken();
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  let response = await fetch(`${agentBaseUrl()}${path}`, {
    ...withTimeout(init),
    headers,
  });
  if (response.status === 401) {
    clearToken();
    const next = await fetchToken(true);
    const retryHeaders = new Headers(init.headers);
    retryHeaders.set("Authorization", `Bearer ${next}`);
    response = await fetch(`${agentBaseUrl()}${path}`, {
      ...withTimeout(init),
      headers: retryHeaders,
    });
  }
  return response;
}

async function readJson<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.detail || body.error || `HTTP ${response.status}`);
  }
  return body as T;
}

export async function listConversations(): Promise<Paged<UserConversation>> {
  return readJson<Paged<UserConversation>>(
    await authFetch("/api/conversations?page=1&page_size=50"),
  );
}

export async function getConversation(
  id: string,
): Promise<UserConversationDetail> {
  return readJson<UserConversationDetail>(
    await authFetch(`/api/conversations/${encodeURIComponent(id)}`),
  );
}

export async function getRun(runId: string): Promise<RunInfo> {
  return readJson<RunInfo>(
    await authFetch(`/api/runs/${encodeURIComponent(runId)}`),
  );
}

export async function cancelRun(runId: string): Promise<{ stopped: boolean }> {
  return readJson<{ stopped: boolean }>(
    await authFetch(`/api/runs/${encodeURIComponent(runId)}/cancel`, {
      method: "POST",
    }),
  );
}

export async function deleteConversation(id: string): Promise<void> {
  const response = await authFetch(
    `/api/conversations/${encodeURIComponent(id)}`,
    { method: "DELETE" },
  );
  await readJson(response);
}

export async function listPendingWriteActions(
  conversationId: string,
): Promise<PendingWriteAction[]> {
  const body = await readJson<{ items: PendingWriteAction[] }>(
    await authFetch(
      `/api/write-actions/pending?conversation_id=${encodeURIComponent(conversationId)}`,
    ),
  );
  return body.items ?? [];
}

export async function confirmAllWriteActions(
  conversationId: string,
  actionIds: string[],
): Promise<BatchConfirmResult> {
  return readJson<BatchConfirmResult>(
    await authFetch("/api/write-actions/confirm-all", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        conversation_id: conversationId,
        action_ids: actionIds,
      }),
    }),
  );
}

export async function getFeedback(
  conversationId: string,
): Promise<TurnFeedback[]> {
  const body = await readJson<{ items: TurnFeedback[] }>(
    await authFetch(
      `/api/feedback?conversation_id=${encodeURIComponent(conversationId)}`,
    ),
  );
  return body.items ?? [];
}

/** 取知识条目完整正文（回答下方“参考知识库”点开时用）。 */
export async function getKnowledgeContent(
  scope: string,
  id: number,
): Promise<string> {
  const path =
    scope === "employee"
      ? `/api/employee-knowledge/${id}`
      : `/api/knowledge/${id}`;
  const body = await readJson<{ content?: string }>(await authFetch(path));
  return body.content ?? "";
}

export async function saveFeedback(
  conversationId: string,
  turnIndex: number,
  rating: FeedbackRating | null,
): Promise<void> {
  await readJson(
    await authFetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        conversation_id: conversationId,
        turn_index: turnIndex,
        rating,
      }),
    }),
  );
}

export async function exportConversation(
  id: string,
): Promise<{ blob: Blob; filename: string }> {
  const response = await authFetch(
    `/api/conversations/${encodeURIComponent(id)}/export`,
  );
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${response.status}`);
  }
  const disposition = response.headers.get("content-disposition") || "";
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  let filename = `conversation-${id}.md`;
  if (encoded) {
    try {
      filename = decodeURIComponent(encoded[1].trim());
    } catch {
      // 保留默认文件名
    }
  }
  return { blob: await response.blob(), filename };
}

export function downloadBlob(filename: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function listKnowledge(
  tab: "active" | "trash" = "active",
): Promise<{ items: KnowledgeItem[]; usage: KnowledgeUsage }> {
  return readJson<{ items: KnowledgeItem[]; usage: KnowledgeUsage }>(
    await authFetch(`/api/knowledge?tab=${tab}`),
  );
}

export async function deleteKnowledge(
  id: number,
  purge = false,
): Promise<void> {
  const suffix = purge ? "?purge=true" : "";
  const response = await authFetch(
    `/api/knowledge/${encodeURIComponent(String(id))}${suffix}`,
    { method: "DELETE" },
  );
  await readJson(response);
}

export async function restoreKnowledge(id: number): Promise<KnowledgeItem> {
  const response = await authFetch(
    `/api/knowledge/${encodeURIComponent(String(id))}/restore`,
    { method: "POST" },
  );
  return readJson<KnowledgeItem>(response);
}

export async function saveKnowledge(
  title: string,
  content: string,
  mode: "raw" | "summarize" = "raw",
): Promise<KnowledgeItem> {
  const response = await authFetch("/api/knowledge", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, content, mode }),
  });
  return readJson<KnowledgeItem>(response);
}

export async function updateKnowledge(
  id: number,
  title: string,
  content: string,
  mode: "raw" | "summarize" = "raw",
): Promise<KnowledgeItem> {
  const response = await authFetch(`/api/knowledge/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, content, mode }),
  });
  return readJson<KnowledgeItem>(response);
}

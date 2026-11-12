import { useContext, useEffect, useState } from "react";
import { useAssistantApi } from "@assistant-ui/react";

import { agentBaseUrl, fetchToken } from "./api";
import { WriteBatchContext } from "./WriteBatchContext";
import {
  confirmAllWriteActions,
  listPendingWriteActions,
  type BatchConfirmResult,
  type PendingWriteAction,
} from "./userApi";

export const CONTINUATION_MARKER = "[[sa-continue]]";

export function isContinuationText(text: string): boolean {
  return text.trimStart().startsWith(CONTINUATION_MARKER);
}

export type WriteProposal = {
  action_id: string;
  status: string;
  action_type: string;
  risk_level: string;
  summary: string;
  tool: string;
  arguments: Record<string, unknown>;
  snapshot_summary?: Record<string, unknown>;
  expires_at: string;
};

type ActionResult = {
  status?: string;
  result?: Record<string, any> | null;
  rollback?: Record<string, any> | null;
  error?: string;
  expires_at?: string;
};

const STATUS_LABELS: Record<string, string> = {
  pending: "待确认",
  executed: "已执行",
  cancelled: "已取消",
  rolled_back: "已回滚",
  rollback_failed: "回滚失败",
  failed: "执行失败",
};

function riskLabel(level: string): string {
  if (level === "high") return "高风险";
  if (level === "medium") return "中风险";
  return "风险未知";
}

function resultSummary(result: Record<string, any>): string {
  const name =
    result.deleted_name ??
    result.restored_name ??
    result.chart?.slice_name ??
    result.dashboard?.dashboard_title ??
    "";
  if (result.soft_deleted) {
    return `已删除${name ? `「${name}」` : ""}，已进回收站，可回滚`;
  }
  if (result.restored_id || result.restored_name) {
    return `已从回收站恢复${name ? `「${name}」` : ""}`;
  }
  if (Array.isArray(result.added_filter_ids) && result.added_filter_ids.length) {
    return `已新增 ${result.added_filter_ids.length} 个原生筛选器，可回滚移除`;
  }
  if (name) return `已完成：${name}`;
  return "执行完成";
}

function parseUtc(value: string): number {
  if (!value) return Number.NaN;
  return Date.parse(/Z$|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`);
}

function continueHint(result: Record<string, any> | null): string {
  if (!result) return "";
  const chartId = result.chart_id ?? result.chart?.id;
  const dashboardId = result.dashboard_id ?? result.dashboard?.id;
  const bits: string[] = [];
  if (chartId) bits.push(`chart_id=${chartId}`);
  if (dashboardId) bits.push(`dashboard_id=${dashboardId}`);
  return bits.length ? `执行结果：${bits.join("，")}。` : "";
}

function batchPrompt(
  items: PendingWriteAction[],
  outcome: BatchConfirmResult,
): string {
  const results = new Map(
    outcome.results.map((item) => [item.action_id, item]),
  );
  const lines = items.map((item, index) => {
    const result = results.get(item.id);
    let state = "未执行";
    if (result?.status === "executed") {
      state = `已执行。${continueHint(result.result ?? null)}`.trim();
    } else if (result?.status === "failed") {
      state = `失败：${(result.error || "未知错误").slice(0, 200)}`;
    } else if (result) {
      state = `状态：${result.status}`;
    }
    return `${index + 1}. ${item.summary.slice(0, 140)} → ${state}`;
  });
  return [
    "已一次性确认并执行写操作：",
    ...lines,
    outcome.remaining
      ? `还有 ${outcome.remaining} 个方案未执行，仍处于待确认状态。`
      : "",
    "请继续按原计划完成剩余步骤；如果还有未完成的写操作，" +
      "请直接调用 propose_write 生成下一张确认卡，不要重复已执行的方案。" +
      "如果没有剩余步骤，请简要告知已完成。",
  ]
    .filter(Boolean)
    .join("\n");
}

async function fetchAction(actionId: string): Promise<ActionResult> {
  const token = await fetchToken();
  const response = await fetch(
    `${agentBaseUrl()}/api/write-actions/${actionId}`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  const body = (await response.json().catch(() => ({}))) as ActionResult & {
    detail?: string;
  };
  if (!response.ok) {
    throw new Error(body.detail || body.error || `HTTP ${response.status}`);
  }
  return body;
}

async function callAction(
  actionId: string,
  action: "confirm" | "cancel" | "rollback",
): Promise<ActionResult> {
  const token = await fetchToken(true);
  const response = await fetch(
    `${agentBaseUrl()}/api/write-actions/${actionId}/${action}`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    },
  );
  const body = (await response.json().catch(() => ({}))) as ActionResult & {
    detail?: string;
  };
  if (!response.ok) {
    throw new Error(body.detail || body.error || `HTTP ${response.status}`);
  }
  return body;
}

export function WriteActionCard({
  proposal,
}: {
  proposal: WriteProposal;
}) {
  const api = useAssistantApi();
  const batch = useContext(WriteBatchContext);
  const [status, setStatus] = useState(proposal.status || "pending");
  const [expiresAt, setExpiresAt] = useState(proposal.expires_at);
  const [result, setResult] = useState<Record<string, any> | null>(null);
  const [rollback, setRollback] = useState<Record<string, any> | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [continued, setContinued] = useState(false);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkList, setBulkList] = useState<PendingWriteAction[]>([]);
  const [bulkError, setBulkError] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    fetchAction(proposal.action_id)
      .then((body) => {
        if (!alive) return;
        if (body.status) setStatus(body.status);
        if (body.expires_at) setExpiresAt(body.expires_at);
        if (body.result) setResult(body.result);
        if (body.rollback) setRollback(body.rollback);
        if (body.error) setError(body.error);
      })
      .catch(() => {
        // 历史消息里的旧方案可能已清理，保持本地状态即可。
      });
    return () => {
      alive = false;
    };
  }, [proposal.action_id]);

  useEffect(() => {
    if (proposal.status === "pending") void batch?.refresh();
  }, [proposal.action_id, proposal.status, batch?.refresh]);

  useEffect(() => {
    const item = batch?.results[proposal.action_id];
    if (!item) return;
    if (item.status) setStatus(item.status);
    if (item.result) setResult(item.result);
    if (item.rollback) setRollback(item.rollback);
    if (item.error !== undefined) setError(item.error || "");
  }, [batch?.revision, batch?.results, proposal.action_id]);

  const expired =
    status === "pending" && parseUtc(expiresAt) <= Date.now();

  const appendContinuation = (prompt: string) => {
    if (continued) return;
    const thread = api.thread();
    const state = thread.getState();
    if (state.isRunning) return;
    const last = state.messages[state.messages.length - 1];
    if (!last) return;
    thread.append({
      parentId: last.id,
      role: "user",
      content: [{ type: "text", text: `${CONTINUATION_MARKER}${prompt}` }],
    });
    setContinued(true);
  };

  const sendContinue = (currentResult: Record<string, any> | null) => {
    if (continued) return;
    const hint = continueHint(currentResult);
    appendContinuation(
      `已确认执行写操作「${proposal.summary.slice(0, 160)}」。` +
        hint +
        "请继续按原计划完成剩余步骤；如果还有未完成的写操作，" +
        "请直接调用 propose_write 生成下一张确认卡，不要重复已执行的方案。" +
        "如果没有剩余步骤，请简要告知已完成。",
    );
  };

  const run = async (action: "confirm" | "cancel" | "rollback") => {
    setBusy(true);
    setError("");
    try {
      const body = await callAction(proposal.action_id, action);
      setStatus(body.status || (action === "cancel" ? "cancelled" : status));
      if (body.result) setResult(body.result);
      if (body.rollback) setRollback(body.rollback);
      if (body.expires_at) setExpiresAt(body.expires_at);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
      if (action === "confirm") setStatus("failed");
      if (action === "rollback") setStatus("rollback_failed");
    } finally {
      setBusy(false);
      void batch?.refresh();
    }
  };

  const openBulk = async () => {
    if (!batch) return;
    setError("");
    setBulkError("");
    try {
      const items = await listPendingWriteActions(batch.conversationId);
      if (items.length < 2) {
        setError("当前没有足够的待确认方案，请刷新后重试。");
        await batch.refresh();
        return;
      }
      setBulkList(items);
      setBulkOpen(true);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  };

  const runBulk = async () => {
    if (!batch || bulkList.length === 0) return;
    setBulkBusy(true);
    setBulkError("");
    setError("");
    try {
      const outcome = await confirmAllWriteActions(
        batch.conversationId,
        bulkList.map((item) => item.id),
      );
      batch.applyResults(outcome.results);
      await batch.refresh();
      setBulkOpen(false);
      if (outcome.failed) {
        setError(
          `有 ${outcome.failed} 个写操作未完成，已停止后续执行；` +
            `${outcome.remaining ? `剩余 ${outcome.remaining} 个方案仍待确认。` : ""}`,
        );
      }
      appendContinuation(batchPrompt(bulkList, outcome));
    } catch (exc) {
      setBulkError(exc instanceof Error ? exc.message : String(exc));
      void batch?.refresh();
    } finally {
      setBulkBusy(false);
    }
  };

  const canBulk =
    Boolean(batch) &&
    status === "pending" &&
    !expired &&
    (batch?.pending.length ?? 0) >= 2 &&
    Boolean(
      batch?.pending.some((item) => item.id === proposal.action_id),
    );

  const isPending = status === "pending";
  const isExecuted = status === "executed";

  return (
    <div className={`sa-write sa-write-${status}`}>
      <div className="sa-write-top">
        <span className={`sa-write-risk sa-write-risk-${proposal.risk_level}`}>
          {riskLabel(proposal.risk_level)}
        </span>
        <span className="sa-write-status">{STATUS_LABELS[status] || status}</span>
      </div>
      <div className="sa-write-summary">{proposal.summary}</div>
      {proposal.snapshot_summary &&
      Object.keys(proposal.snapshot_summary).length > 0 ? (
        <div className="sa-write-meta">
          对象：
          {JSON.stringify(proposal.snapshot_summary, null, 0)}
        </div>
      ) : null}
      {isPending ? (
        <div className="sa-write-expiry">
          {expired
            ? "方案已过期，请重新提问生成新方案。"
            : "方案 15 分钟内有效，执行前请确认权限和影响范围。"}
        </div>
      ) : null}
      <details className="sa-write-plan">
        <summary>查看执行计划</summary>
        <pre className="sa-sql">
          {JSON.stringify(
            { tool: proposal.tool, arguments: proposal.arguments },
            null,
            2,
          )}
        </pre>
      </details>
      {error ? <div className="sa-tool-error">{error}</div> : null}
      {result ? (
        <>
          <div className="sa-write-result-line">{resultSummary(result)}</div>
          <details className="sa-write-plan">
            <summary>查看执行结果</summary>
            <pre className="sa-sql">{JSON.stringify(result, null, 2)}</pre>
          </details>
        </>
      ) : null}
      {bulkOpen ? (
        <div className="sa-write-bulk">
          <div className="sa-write-bulk-title">
            确认一次性执行 {bulkList.length} 个写操作？
          </div>
          <ol className="sa-write-bulk-list">
            {bulkList.map((item) => (
              <li key={item.id}>
                {item.summary}
                <em>{riskLabel(item.risk_level)}</em>
              </li>
            ))}
          </ol>
          <div className="sa-write-bulk-note">
            将按创建顺序依次执行；任一失败会停止，剩余方案保持待确认。执行后仍可逐个回滚。
          </div>
          {bulkError ? <div className="sa-tool-error">{bulkError}</div> : null}
          <div className="sa-write-actions">
            <button
              type="button"
              className="sa-write-danger"
              disabled={bulkBusy}
              onClick={() => void runBulk()}
            >
              {bulkBusy ? "正在执行…" : "确认全部执行"}
            </button>
            <button
              type="button"
              className="sa-write-secondary"
              disabled={bulkBusy}
              onClick={() => setBulkOpen(false)}
            >
              取消
            </button>
          </div>
        </div>
      ) : null}
      <div className="sa-write-actions">
        {isPending ? (
          <>
            <button
              type="button"
              className="sa-write-primary"
              disabled={busy || expired}
              onClick={() => void run("confirm")}
            >
              {proposal.risk_level === "high"
                ? "确认执行（高风险）"
                : "确认执行"}
            </button>
            {canBulk ? (
              <button
                type="button"
                className="sa-write-batch"
                disabled={busy || expired}
                onClick={() => void openBulk()}
              >
                全部执行（{batch?.pending.length}）
              </button>
            ) : null}
            <button
              type="button"
              className="sa-write-secondary"
              disabled={busy}
              onClick={() => void run("cancel")}
            >
              取消
            </button>
          </>
        ) : null}
        {isExecuted && !continued ? (
          <button
            type="button"
            className="sa-write-secondary"
            disabled={busy}
            onClick={() => sendContinue(result)}
          >
            继续下一步
          </button>
        ) : null}
        {isExecuted && continued ? (
          <span className="sa-write-meta">已继续执行</span>
        ) : null}
        {isExecuted && rollback ? (
          <button
            type="button"
            className="sa-write-danger"
            disabled={busy}
            onClick={() => void run("rollback")}
          >
            回滚
          </button>
        ) : null}
      </div>
    </div>
  );
}

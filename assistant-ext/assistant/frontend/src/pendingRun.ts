export type PendingRun = {
  conversationId: string;
  runId: string;
  question: string;
  startedAt: number;
};

const KEY = "sa-assistant-pending-run";
const MAX_AGE_MS = 2 * 60 * 60 * 1000;

let currentRunId: string | null = null;

export function getCurrentRunId(): string | null {
  return currentRunId;
}

export function writePendingRun(value: PendingRun): void {
  currentRunId = value.runId;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(value));
  } catch {
    // ignore
  }
}

export function readPendingRun(): PendingRun | null {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<PendingRun>;
    if (
      typeof parsed.conversationId !== "string" ||
      typeof parsed.runId !== "string" ||
      typeof parsed.startedAt !== "number"
    ) {
      return null;
    }
    if (Date.now() - parsed.startedAt > MAX_AGE_MS) {
      window.localStorage.removeItem(KEY);
      return null;
    }
    return {
      conversationId: parsed.conversationId,
      runId: parsed.runId,
      question: typeof parsed.question === "string" ? parsed.question : "",
      startedAt: parsed.startedAt,
    };
  } catch {
    return null;
  }
}

export function clearPendingRun(): void {
  currentRunId = null;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // ignore
  }
}

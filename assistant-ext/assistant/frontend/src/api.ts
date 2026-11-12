const TOKEN_PATH = "/extensions/dataagent/assistant/token";

let cachedToken: { token: string; expiresAt: number } | null = null;
// Agent 宿主端口由 Superset token 端点下发（infra/.env 的 AGENT_HTTP_PORT）
let cachedAgentPort: number | null = null;

export class TokenError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "TokenError";
  }
}

export function agentBaseUrl(): string {
  const override = (window as unknown as Record<string, unknown>)
    .__SUPERSET_ASSISTANT_AGENT_URL__;
  if (typeof override === "string" && override.length > 0) {
    return override.replace(/\/$/, "");
  }
  const protocol = window.location.protocol === "https:" ? "https:" : "http:";
  const hostname = window.location.hostname || "localhost";
  return `${protocol}//${hostname}:${cachedAgentPort ?? 28088}`;
}

export function clearToken(): void {
  cachedToken = null;
  inFlightToken = null;
}

// 并发调用共用同一个 token 请求，避免首屏同时打 4-5 次 /token
let inFlightToken: Promise<string> | null = null;

export async function fetchToken(force = false): Promise<string> {
  if (
    !force &&
    cachedToken &&
    cachedToken.expiresAt - Date.now() > 30_000
  ) {
    return cachedToken.token;
  }
  if (inFlightToken) return inFlightToken;
  inFlightToken = requestToken().finally(() => {
    inFlightToken = null;
  });
  return inFlightToken;
}

async function requestToken(): Promise<string> {
  const response = await fetch(TOKEN_PATH, {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new TokenError(
      response.status === 401 || response.redirected
        ? "登录状态已失效，请刷新页面后重试"
        : `身份令牌获取失败（HTTP ${response.status}）`,
      response.redirected ? 401 : response.status,
    );
  }
  const body = await response.json();
  const payload = body?.result ?? body;
  const token = payload?.token;
  if (!token) {
    throw new Error("Superset 没有返回身份令牌");
  }
  const expiresIn = Number(payload?.expires_in ?? 300);
  const agentPort = Number(payload?.agent_port);
  if (Number.isInteger(agentPort) && agentPort > 0) {
    cachedAgentPort = agentPort;
  }
  cachedToken = {
    token,
    expiresAt: Date.now() + Math.max(60, expiresIn) * 1000,
  };
  return token;
}

export type MeInfo = {
  username?: string;
  roles?: string[];
  can_admin?: boolean;
  ai_enabled?: boolean;
  has_employees?: boolean;
};

/** 一次拿到 /api/me（入口判定 + 管理入口共用），401/403 返回 null。 */
export async function fetchMe(): Promise<MeInfo | null> {
  try {
    const token = await fetchToken();
    const response = await fetch(`${agentBaseUrl()}/api/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (response.status === 401 || response.status === 403) return null;
    if (!response.ok) return {};
    return (await response.json()) as MeInfo;
  } catch (exc) {
    if (
      exc instanceof TokenError &&
      (exc.status === 401 || exc.status === 403)
    ) {
      return null;
    }
    throw exc;
  }
}

export async function hasAssistantAccess(): Promise<boolean> {
  try {
    const me = await fetchMe();
    if (me === null) return false;
    return me.ai_enabled !== false && me.has_employees !== false;
  } catch {
    // Agent 暂时不可用时保持入口，避免网络抖动把助手永久隐藏。
    return true;
  }
}

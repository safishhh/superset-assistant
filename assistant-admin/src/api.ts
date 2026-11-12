import type { AdminFilters } from "./types";

export type AdminUser = {
  username: string;
  roles: string[];
};

export async function loadFilters(): Promise<AdminFilters> {
  return api<AdminFilters>("/filters");
}

export async function bootstrapSession(): Promise<boolean> {
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const ticket = hash.get("ticket");
  if (ticket) {
    const response = await fetch("/admin/api/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticket }),
      credentials: "same-origin",
    });
    window.history.replaceState(null, "", window.location.pathname);
    if (!response.ok) {
      return false;
    }
  }
  const me = await fetch("/admin/api/me", { credentials: "same-origin" });
  return me.ok;
}

export function csrfToken(): string {
  const match = document.cookie.match(/(?:^|; )sa_admin_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

/** 普通请求超时：避免后端挂起时表格一直 loading。 */
const REQUEST_TIMEOUT_MS = 30_000;

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const method = (options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers);
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    headers.set("X-CSRF-Token", csrfToken());
  }
  const response = await fetch(`/admin/api${path}`, {
    ...options,
    headers,
    credentials: "same-origin",
    signal: options.signal ?? AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  if (response.status === 401) {
    window.dispatchEvent(new Event("sa-admin-unauthorized"));
    throw new Error("登录已过期，请从 Superset 助手重新进入");
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.detail || body.message || `HTTP ${response.status}`);
  }
  return body as T;
}

export async function logout(): Promise<void> {
  await api("/logout", { method: "POST" });
  window.location.reload();
}

export async function loadMe(): Promise<AdminUser> {
  return api<AdminUser>("/me");
}

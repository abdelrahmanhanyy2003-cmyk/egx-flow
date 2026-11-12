/** REST client. The optional local access token is entered by the user in Settings
 * and kept in sessionStorage - never bundled into the frontend build. */

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000").replace(/\/$/, "");

export function accessToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem("egxflow.token");
  } catch {
    return null;
  }
}

export function setAccessToken(t: string | null) {
  try {
    if (t) window.sessionStorage.setItem("egxflow.token", t);
    else window.sessionStorage.removeItem("egxflow.token");
  } catch {
    /* ignore */
  }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T = any>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const headers: Record<string, string> = { ...(init?.headers as Record<string, string>) };
  const tok = accessToken();
  if (tok) headers["X-EGXFlow-Token"] = tok;
  let body = init?.body;
  if (init?.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.json);
  }
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers, body, cache: "no-store" });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

export const wsUrl = () => {
  const base = API_BASE.replace(/^http/, "ws") + "/ws";
  const tok = accessToken();
  return tok ? `${base}?token=${encodeURIComponent(tok)}` : base;
};

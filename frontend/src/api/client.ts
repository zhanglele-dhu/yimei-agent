let accessToken = sessionStorage.getItem("creator_access_token") || "";

export async function initializeSession(): Promise<void> {
  if (accessToken) return;
  const response = await fetch("/api/local-session", {
    headers: { "X-Studio-Local": "1" },
  });
  if (!response.ok) throw new Error("本地会话初始化失败，请重新启动工作台。");
  const data = (await response.json()) as { access_token: string };
  accessToken = data.access_token;
  sessionStorage.setItem("creator_access_token", accessToken);
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  await initializeSession();
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${accessToken}`);
  if (init.body && !(init.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const response = await fetch(`/api${path}`, { ...init, headers });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      detail?: string;
      error?: string;
      message?: string;
    };
    throw new Error(
      body.detail ||
        body.error ||
        body.message ||
        `请求失败（${response.status}）`,
    );
  }
  return response.json() as Promise<T>;
}

export async function authenticatedFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  await initializeSession();
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${accessToken}`);
  if (init.body && !(init.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  return fetch(`/api${path}`, { ...init, headers });
}

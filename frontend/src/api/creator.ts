import { api, authenticatedFetch } from "./client";
import type { CreatorRecord, OutlinePage } from "./types";

export const createOutline = (topic: string, pageCount: number) =>
  api<{ pages: OutlinePage[]; raw: string }>("/outline", {
    method: "POST",
    body: JSON.stringify({ topic, page_count: pageCount }),
  });
export const createHistory = (
  topic: string,
  outline: { raw: string; pages: OutlinePage[] },
) =>
  api<{ record_id: string }>("/history", {
    method: "POST",
    body: JSON.stringify({ topic, outline }),
  });
export const saveHistory = (id: string, body: Partial<CreatorRecord>) =>
  api<CreatorRecord>(`/history/${id}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
export const getHistory = (id: string) => api<CreatorRecord>(`/history/${id}`);
export const listHistory = (
  page = 1,
  pageSize = 24,
  keyword = "",
  status = "",
) =>
  api<{
    records: CreatorRecord[];
    total: number;
    page: number;
    total_pages: number;
  }>(
    `/history?page=${page}&page_size=${pageSize}&keyword=${encodeURIComponent(keyword)}&status=${encodeURIComponent(status)}`,
  );
export const deleteHistory = (id: string) =>
  api<{ success: boolean }>(`/history/${id}`, { method: "DELETE" });
export const getSettings = () =>
  api<{
    text_model: string;
    text_base_url: string;
    text_key_configured: boolean;
    provider: string;
    model: string;
    image_base_url: string;
    ready: boolean;
    key_configured: boolean;
  }>("/settings");
export const saveSettings = (body: {
  text_base_url: string;
  text_model: string;
  text_api_key?: string;
  image_base_url: string;
  image_model: string;
  image_api_key?: string;
}) =>
  api<{ success: boolean }>("/settings", {
    method: "PUT",
    body: JSON.stringify(body),
  });
export const generateContent = (topic: string, outline: string) =>
  api<{ titles: string[]; copywriting: string; tags: string[] }>("/content", {
    method: "POST",
    body: JSON.stringify({ topic, outline }),
  });
export const regeneratePage = (body: {
  task_id: string;
  page: OutlinePage;
  full_outline: string;
  topic: string;
  record_id: string;
}) =>
  api<{ image_url: string }>("/regenerate", {
    method: "POST",
    body: JSON.stringify(body),
  });

export async function loadImage(path: string): Promise<string> {
  const response = await authenticatedFetch(path.replace(/^\/api/, ""));
  if (!response.ok) throw new Error("读取图片失败。");
  return URL.createObjectURL(await response.blob());
}

export async function generatePages(
  body: {
    task_id: string;
    record_id: string;
    topic: string;
    outline: { raw: string; pages: OutlinePage[] };
  },
  onPage: (event: {
    index: number;
    status: string;
    current?: number;
    total?: number;
    phase?: string;
    image_url?: string;
    error?: string;
  }) => void,
) {
  const response = await authenticatedFetch("/generate", {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (!response.ok || !response.body) throw new Error("无法启动图片生成。");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() || "";
    for (const event of events) {
      const eventName = event.match(/^event: (.+)$/m)?.[1];
      const data = event.match(/^data: (.+)$/m)?.[1];
      if (
        !eventName ||
        !data ||
        !["progress", "complete", "error"].includes(eventName)
      )
        continue;
      onPage(
        JSON.parse(data) as {
          index: number;
          status: string;
          current?: number;
          total?: number;
          phase?: string;
          image_url?: string;
          error?: string;
        },
      );
    }
  }
}

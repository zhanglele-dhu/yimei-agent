export interface OutlinePage {
  index: number;
  type: "cover" | "content" | "summary";
  content: string;
}
export interface GeneratedImage {
  index: number;
  url: string;
  status: "generating" | "done" | "error";
  error?: string;
}
export interface CreatorRecord {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  status: string;
  thumbnail: string | null;
  page_count: number;
  task_id: string | null;
  outline?: { raw: string; pages: OutlinePage[] };
  images?: { task_id: string | null; generated: string[] };
  content?: { titles: string[]; copywriting: string; tags: string[] };
}

import { defineStore } from "pinia";
import { watch } from "vue";
import type { CreatorRecord, GeneratedImage, OutlinePage } from "../api/types";

const STORAGE_KEY = "yimei-creator-state-v1";
interface GeneratorState {
  stage: "input" | "outline" | "generating" | "result";
  topic: string;
  outline: { raw: string; pages: OutlinePage[] };
  images: GeneratedImage[];
  taskId: string | null;
  recordId: string | null;
  content: { titles: string[]; copywriting: string; tags: string[] };
  progress: {
    current: number;
    total: number;
    status: "idle" | "generating" | "done" | "error";
  };
  isSaving: boolean;
  lastSavedAt: string | null;
}
function loadState(): Partial<GeneratorState> {
  try {
    return JSON.parse(
      localStorage.getItem(STORAGE_KEY) || "{}",
    ) as Partial<GeneratorState>;
  } catch {
    return {};
  }
}

export const useGeneratorStore = defineStore("generator", {
  state: (): GeneratorState => {
    const saved = loadState();
    return {
      stage: saved.stage || "input",
      topic: saved.topic || "",
      outline: saved.outline || { raw: "", pages: [] },
      images: saved.images || [],
      taskId: saved.taskId || null,
      recordId: saved.recordId || null,
      content: saved.content || { titles: [], copywriting: "", tags: [] },
      progress: saved.progress || { current: 0, total: 0, status: "idle" },
      isSaving: false,
      lastSavedAt: saved.lastSavedAt || null,
    };
  },
  actions: {
    persistLocal() {
      const { isSaving: _busy, ...data } = this.$state;
      localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
    },
    enableLocalSave() {
      watch(
        () => this.$state,
        () => this.persistLocal(),
        { deep: true },
      );
    },
    setOutline(topic: string, raw: string, pages: OutlinePage[]) {
      this.topic = topic;
      this.outline = { raw, pages };
      this.stage = "outline";
    },
    syncRaw() {
      this.outline.raw = this.outline.pages
        .map((page) => page.content)
        .join("\n\n<page>\n\n");
    },
    addPage() {
      this.outline.pages.push({
        index: this.outline.pages.length,
        type: "content",
        content: "",
      });
      this.syncRaw();
    },
    removePage(index: number) {
      this.outline.pages.splice(index, 1);
      this.reindex();
      this.syncRaw();
    },
    movePage(from: number, to: number) {
      const [page] = this.outline.pages.splice(from, 1);
      this.outline.pages.splice(to, 0, page);
      this.reindex();
      this.syncRaw();
    },
    reindex() {
      this.outline.pages.forEach((page, index) => {
        page.index = index;
      });
    },
    beginGeneration() {
      this.stage = "generating";
      this.progress = {
        current: 0,
        total: this.outline.pages.length,
        status: "generating",
      };
      this.images = this.outline.pages.map((page) => {
        const existing = this.images.find(
          (image) => image.index === page.index,
        );
        return existing?.status === "done"
          ? existing
          : { index: page.index, url: "", status: "generating" };
      });
      this.progress.current = this.images.filter(
        (image) => image.status === "done",
      ).length;
    },
    updateImage(index: number, image: Partial<GeneratedImage>) {
      const current = this.images.find((item) => item.index === index);
      if (current) Object.assign(current, image);
      this.progress.current = this.images.filter(
        (item) => item.status === "done",
      ).length;
      if (this.images.every((item) => item.status === "done")) {
        this.progress.status = "done";
        this.stage = "result";
      }
    },
    restore(record: CreatorRecord) {
      this.topic = record.title;
      this.outline = record.outline || { raw: "", pages: [] };
      this.recordId = record.id;
      this.taskId = record.images?.task_id || null;
      this.content = record.content || {
        titles: [],
        copywriting: "",
        tags: [],
      };
      this.images = this.outline.pages.map((page, index) => {
        const filename = record.images?.generated[index];
        return {
          index: page.index,
          url: filename ? `/api/images/${this.taskId}/${filename}` : "",
          status: filename ? "done" : "error",
        };
      });
      this.progress = {
        current: this.images.filter((image) => image.status === "done").length,
        total: this.images.length,
        status: this.images.every((image) => image.status === "done")
          ? "done"
          : "error",
      };
      this.stage =
        this.images.length && this.progress.status === "done"
          ? "result"
          : "outline";
    },
    saveLocal() {
      this.lastSavedAt = new Date().toISOString();
    },
    reset() {
      this.stage = "input";
      this.topic = "";
      this.outline = { raw: "", pages: [] };
      this.images = [];
      this.taskId = null;
      this.recordId = null;
      this.content = { titles: [], copywriting: "", tags: [] };
      this.progress = { current: 0, total: 0, status: "idle" };
    },
  },
});

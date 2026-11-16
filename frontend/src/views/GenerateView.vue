<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { DEMO_IMAGES } from "../demo/data";
import { useGeneratorStore } from "../stores/generator";

const store = useGeneratorStore();
const router = useRouter();
const error = ref("");
const running = ref(false);
const activePage = ref<number | null>(null);
const activePhase = ref("");
const percent = computed(() =>
  store.progress.total
    ? Math.round((store.progress.current / store.progress.total) * 100)
    : 0,
);

onMounted(async () => {
  if (!store.outline.pages.length || !store.recordId) {
    await router.replace("/");
    return;
  }
  store.beginGeneration();
  running.value = true;
  error.value = "";
  try {
    for (let index = 0; index < store.outline.pages.length; index += 1) {
      activePage.value = index;
      activePhase.value = index === 0 ? "cover" : "content";
      await new Promise((resolve) => window.setTimeout(resolve, 650));
      store.updateImage(index, { status: "done", url: DEMO_IMAGES[index] });
    }
    store.stage = "result";
    await router.replace("/result");
  } catch (reason) {
    error.value =
      reason instanceof Error ? reason.message : "生成过程发生错误。";
    store.progress.status = "error";
  } finally {
    running.value = false;
  }
});
</script>

<template>
  <section class="page-wrap generation-view">
    <div class="eyebrow">STEP 02 / GENERATE</div>
    <h1>
      {{
        running
          ? activePage === null
            ? "正在准备生成…"
            : activePhase === "cover"
              ? "正在生成封面…"
              : `正在生成第 ${activePage + 1} 页…`
          : "生成任务已暂停"
      }}
    </h1>
    <p class="hero-subtitle">{{ store.topic }}</p>
    <div class="progress-panel panel">
      <div class="progress-label">
        <strong
          >{{ store.progress.current }} /
          {{ store.progress.total }} 张已完成</strong
        ><span>{{ percent }}%</span>
      </div>
      <div class="progress-track">
        <div class="progress-value" :style="{ width: `${percent}%` }" />
      </div>
      <p class="muted">生成中请保持页面打开；失败的页面可以单独重试。</p>
    </div>
    <div class="generation-list">
      <div
        v-for="image in store.images"
        :key="image.index"
        class="generation-row panel"
      >
        <span class="row-index">{{
          String(image.index + 1).padStart(2, "0")
        }}</span
        ><strong>第 {{ image.index + 1 }} 页</strong
        ><span class="status-pill" :class="image.status">{{
          image.status === "done"
            ? "已完成"
            : image.status === "error"
              ? "生成失败"
              : "生成中"
        }}</span
        ><span v-if="image.error" class="inline-error">{{ image.error }}</span>
      </div>
    </div>
    <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
    <button v-if="error" class="button primary" @click="router.go(0)">
      重试生成
    </button>
  </section>
</template>

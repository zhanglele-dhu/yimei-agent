<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";
import { DEMO_PAGES, DEMO_TOPIC, makeDemoRecord } from "../demo/data";
import { useGeneratorStore } from "../stores/generator";

const router = useRouter();
const store = useGeneratorStore();
const topic = ref(DEMO_TOPIC);
const pageCount = ref(DEMO_PAGES.length);
const loading = ref(false);
const error = ref("");

async function start() {
  if (loading.value) return;
  loading.value = true;
  error.value = "";
  try {
    store.setOutline(
      DEMO_TOPIC,
      DEMO_PAGES.map((page) => page.content).join("\n\n<page>\n\n"),
      DEMO_PAGES.map((page) => ({ ...page })),
    );
    store.recordId = makeDemoRecord().id;
    store.taskId = "demo-m22";
    await router.push("/outline");
  } catch (reason) {
    error.value =
      reason instanceof Error ? reason.message : "生成失败，请重试。";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <section class="page-wrap home-view">
    <div class="hero-kicker">
      <span class="sparkle">✳</span> 一句话，开始一篇图文
    </div>
    <h1>把灵感，变成一组图。</h1>
    <p class="hero-subtitle">体验固定主题、大纲和图片组成的演示流程。</p>
    <form class="composer panel" @submit.prevent="start">
      <label for="topic">你想创作什么？</label>
      <textarea
        id="topic"
        v-model="topic"
        maxlength="1000"
        readonly
        autofocus
        placeholder="例如：第一次养绿植，最容易忽略的 5 件事"
        @keydown.ctrl.enter="start"
      />
      <div class="composer-foot">
        <span>{{ topic.length }} / 1000</span>
        <div class="composer-actions">
          <label class="page-count"
            >图片数量<select v-model.number="pageCount" disabled>
              <option v-for="count in 8" :key="count" :value="count">
                {{ count }} 张
              </option>
            </select></label
          ><button class="button primary" :disabled="loading || !topic.trim()">
            {{ loading ? "正在整理大纲…" : "生成大纲　→" }}
          </button>
        </div>
      </div>
    </form>
    <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
    <div class="workflow-hint">
      <span>主题</span><i>→</i><span>编辑大纲</span><i>→</i><span>生成图片</span
      ><i>→</i><span>下载作品</span>
    </div>
  </section>
</template>

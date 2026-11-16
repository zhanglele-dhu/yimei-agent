<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { DEMO_COPY, DEMO_IMAGES } from "../demo/data";
import { useGeneratorStore } from "../stores/generator";

const store = useGeneratorStore();
const router = useRouter();
const busyIndex = ref<number | null>(null);
const error = ref("");
const imageUrls = reactive<Record<number, string>>({});
onMounted(() => {
  DEMO_IMAGES.forEach((url, index) => (imageUrls[index] = url));
});
async function createCopy() {
  store.content = { ...DEMO_COPY };
}
async function redraw(index: number) {
  busyIndex.value = index;
  error.value = "";
  try {
    await new Promise((resolve) => window.setTimeout(resolve, 500));
    store.updateImage(index, { url: DEMO_IMAGES[index], status: "done" });
    imageUrls[index] = DEMO_IMAGES[index];
  } catch {
    error.value = "演示图片载入失败。";
  } finally {
    busyIndex.value = null;
  }
}
async function downloadAll() {
  const link = document.createElement("a");
  link.href = `${import.meta.env.BASE_URL}demo/images.zip`;
  link.download = "图文图片.zip";
  link.click();
}
async function downloadOne(image: { url: string; index: number }) {
  const link = document.createElement("a");
  link.href = image.url;
  link.download = `图文-${image.index + 1}.png`;
  link.click();
}
</script>

<template>
  <section class="page-wrap wide-view">
    <header class="page-heading">
      <div>
        <div class="eyebrow">YOUR CREATION</div>
        <h1>这一组图，完成了。</h1>
        <p>共 {{ store.images.length }} 张，可逐页重绘或下载图片。</p>
      </div>
      <div class="heading-actions">
        <button class="button subtle" @click="router.push('/outline')">
          返回大纲</button
        ><button class="button primary" @click="downloadAll">
          下载全部图片 ↓
        </button>
      </div>
    </header>
    <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
    <div class="result-grid">
      <article
        v-for="image in store.images"
        :key="image.index"
        class="result-card panel"
      >
        <div class="result-image">
          <img
            v-if="imageUrls[image.index]"
            :src="imageUrls[image.index]"
            :alt="`第 ${image.index + 1} 张图`"
          />
          <div v-else class="image-empty">
            {{ image.status === "error" ? "图片生成失败" : "正在载入图片…" }}
          </div>
          <div v-if="busyIndex === image.index" class="image-busy">
            正在重绘…
          </div>
        </div>
        <div class="result-caption">
          <strong>第 {{ image.index + 1 }} 张</strong>
          <div>
            <button
              class="text-button"
              :disabled="busyIndex === image.index"
              @click="redraw(image.index)"
            >
              重新生成</button
            ><button class="text-button" @click="downloadOne(image)">
              下载
            </button>
          </div>
        </div>
      </article>
    </div>
    <section class="copy-panel panel">
      <div class="copy-heading">
        <div>
          <div class="eyebrow">POST COPY</div>
          <h2>标题与正文</h2>
        </div>
        <button class="button subtle" @click="createCopy">
          {{ store.content.titles.length ? "重新生成文案" : "生成标题与正文" }}
        </button>
      </div>
      <template v-if="store.content.titles.length"
        ><ol>
          <li v-for="title in store.content.titles" :key="title">
            {{ title }}
          </li>
        </ol>
        <p class="copy-body">{{ store.content.copywriting }}</p>
        <p class="muted">{{ store.content.tags.join("　") }}</p></template
      >
      <p v-else class="muted">图片已完成。需要时再生成配套标题和正文。</p>
    </section>
  </section>
</template>

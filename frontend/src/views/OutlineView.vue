<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { useGeneratorStore } from "../stores/generator";

const router = useRouter();
const store = useGeneratorStore();
const saveMessage = ref("本地已自动保存");
let timer: number | undefined;

watch(
  () => store.outline,
  () => {
    saveMessage.value = "正在同步…";
    window.clearTimeout(timer);
    timer = window.setTimeout(async () => {
      store.syncRaw();
      try {
        store.saveLocal();
        saveMessage.value = "已保存到本地和历史记录";
      } catch {
        saveMessage.value = "本地已保存，云端同步失败";
      }
    }, 700);
  },
  { deep: true },
);

onMounted(() => {
  if (!store.outline.pages.length) router.replace("/");
});
onBeforeUnmount(() => window.clearTimeout(timer));
async function goGenerate() {
  store.syncRaw();
  store.saveLocal();
  await router.push("/generate");
}
</script>

<template>
  <section class="page-wrap wide-view">
    <header class="page-heading">
      <div>
        <div class="eyebrow">STEP 01 / EDIT</div>
        <h1>编辑你的大纲</h1>
        <p>拖动页面卡片调整顺序，也可以直接修改文字。</p>
      </div>
      <span class="save-state">{{ saveMessage }}</span>
    </header>
    <div class="topic-strip">
      <span>创作主题</span><strong>{{ store.topic }}</strong>
    </div>
    <div class="outline-grid">
      <article
        v-for="(page, index) in store.outline.pages"
        :key="page.index"
        class="outline-card panel"
        draggable="true"
        @dragstart="
          (event) => event.dataTransfer?.setData('page-index', String(index))
        "
        @dragover.prevent
        @drop="
          (event) => {
            const from = Number(event.dataTransfer?.getData('page-index'));
            if (Number.isFinite(from)) store.movePage(from, index);
          }
        "
      >
        <div class="card-top">
          <div>
            <span class="page-number">{{
              String(index + 1).padStart(2, "0")
            }}</span
            ><span class="page-type">{{
              page.type === "cover"
                ? "封面"
                : page.type === "summary"
                  ? "收尾"
                  : "内容页"
            }}</span>
          </div>
          <button
            class="icon-button"
            title="删除本页"
            @click="store.removePage(index)"
          >
            ×
          </button>
        </div>
        <textarea
          v-model="page.content"
          :aria-label="`第 ${index + 1} 页大纲`"
          placeholder="写下这一页想表达的内容…"
        />
        <div class="card-foot">
          <span>第 {{ index + 1 }} 张</span
          ><span>{{ page.content.length }} 字</span>
        </div>
      </article>
      <button class="add-page panel" @click="store.addPage()">
        <span>＋</span>添加一页
      </button>
    </div>
    <footer class="bottom-actions">
      <button class="button subtle" @click="router.push('/')">← 返回主题</button
      ><button class="button primary" @click="goGenerate">
        确认大纲并生成　→
      </button>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { makeDemoRecord, DEMO_IMAGES } from "../demo/data";
import type { CreatorRecord } from "../api/types";
import { useGeneratorStore } from "../stores/generator";

const router = useRouter();
const store = useGeneratorStore();
const records = ref<CreatorRecord[]>([]);
const loading = ref(true);
const keyword = ref("");
const error = ref("");
const tab = ref("");
const page = ref(1);
const total = ref(0);
const totalPages = ref(1);
const thumbnails = reactive<Record<string, string>>({});
async function load() {
  loading.value = true;
  error.value = "";
  await new Promise((resolve) => window.setTimeout(resolve, 200));
  const record = makeDemoRecord();
  records.value = keyword.value && !record.title.includes(keyword.value) ? [] : [record];
  total.value = records.value.length;
  totalPages.value = 1;
  thumbnails[record.id] = DEMO_IMAGES[0];
  loading.value = false;
}
async function open(record: CreatorRecord) {
  store.restore(record);
  store.images = store.images.map((image) => ({
    ...image,
    url: DEMO_IMAGES[image.index],
  }));
  await router.push("/result");
}
async function remove(record: CreatorRecord) {
  if (!window.confirm(`删除“${record.title}”？`)) return;
  records.value = [];
  total.value = 0;
}
function chooseTab(value: string) {
  tab.value = value;
  page.value = 1;
  void load();
}
onMounted(load);
onBeforeUnmount(() => Object.values(thumbnails).forEach(URL.revokeObjectURL));
</script>

<template>
  <section class="page-wrap wide-view">
    <header class="page-heading">
      <div>
        <div class="eyebrow">LIBRARY</div>
        <h1>历史创作</h1>
        <p>共 {{ total }} 条作品，可从任意记录恢复编辑。</p>
      </div>
      <RouterLink class="button primary" to="/">＋ 新建图文</RouterLink>
    </header>
    <div class="history-stats">
      <span
        >全部作品 <strong>{{ total }}</strong></span
      ><span
        >当前筛选
        <strong>{{
          tab === "completed" ? "已完成" : tab === "draft" ? "草稿" : "全部"
        }}</strong></span
      >
    </div>
    <div class="history-toolbar">
      <div class="history-tabs">
        <button
          v-for="item in [
            { value: '', label: '全部' },
            { value: 'completed', label: '已完成' },
            { value: 'draft', label: '草稿' },
          ]"
          :key="item.value"
          :class="{ selected: tab === item.value }"
          @click="chooseTab(item.value)"
        >
          {{ item.label }}
        </button>
      </div>
      <form
        class="history-search panel"
        @submit.prevent="
          page = 1;
          load();
        "
      >
        <input v-model="keyword" placeholder="按主题搜索…" /><button
          class="button subtle"
        >
          搜索
        </button>
      </form>
    </div>
    <p v-if="error" class="error-banner">{{ error }}</p>
    <div v-if="loading" class="empty-note">正在读取历史记录…</div>
    <div v-else-if="!records.length" class="empty-note panel">
      还没有作品。输入一句主题，开始第一次创作。
    </div>
    <div v-else class="history-grid">
      <article
        v-for="record in records"
        :key="record.id"
        class="history-card panel"
      >
        <button class="history-thumb" @click="open(record)">
          <img
            v-if="thumbnails[record.id]"
            :src="thumbnails[record.id]"
            :alt="record.title"
          /><span v-else>✳</span>
        </button>
        <div class="history-info">
          <span class="eyebrow">{{
            new Date(record.updated_at).toLocaleDateString()
          }}</span>
          <h2>{{ record.title }}</h2>
          <p>
            {{ record.page_count }} 张 ·
            {{ record.status === "completed" ? "已完成" : "草稿" }}
          </p>
          <div class="history-actions">
            <button class="text-button" @click="open(record)">继续编辑</button
            ><button class="text-button danger" @click="remove(record)">
              删除
            </button>
          </div>
        </div>
      </article>
    </div>
    <div v-if="totalPages > 1" class="history-pagination">
      <button
        class="button subtle"
        :disabled="page === 1"
        @click="
          page--;
          load();
        "
      >
        上一页</button
      ><span>{{ page }} / {{ totalPages }}</span
      ><button
        class="button subtle"
        :disabled="page === totalPages"
        @click="
          page++;
          load();
        "
      >
        下一页
      </button>
    </div>
  </section>
</template>

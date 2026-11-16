<script setup lang="ts">
import { RouterLink, RouterView, useRoute } from "vue-router";
import { useGeneratorStore } from "./stores/generator";

const route = useRoute();
const store = useGeneratorStore();
store.enableLocalSave();

const links = [
  { to: "/", label: "创作中心", icon: "✳" },
  { to: "/history", label: "历史记录", icon: "▤" },
  { to: "/settings", label: "模型设置", icon: "⚙" },
];
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <RouterLink class="brand" to="/" aria-label="返回创作中心">
        <span class="brand-mark">Y</span>
        <span class="brand-copy"
          ><strong>灵感创作台</strong><small>AI 图文工作室</small></span
        >
      </RouterLink>
      <nav class="side-nav" aria-label="主导航">
        <RouterLink
          v-for="item in links"
          :key="item.to"
          :to="item.to"
          class="nav-link"
          :class="{ active: route.path === item.to }"
        >
          <span class="nav-icon" aria-hidden="true">{{ item.icon }}</span
          >{{ item.label }}
        </RouterLink>
      </nav>
      <div class="sidebar-bottom">
        <span class="status-dot"></span><span>静态演示</span>
      </div>
    </aside>
    <main class="main-area">
      <header class="topbar">
        <div>
          <span class="breadcrumb">创作空间</span><span class="slash">/</span
          ><strong>{{ route.meta.title || "创作中心" }}</strong>
        </div>
        <span class="save-state">固定演示数据</span>
      </header>
      <RouterView v-slot="{ Component }"
        ><Transition name="page" mode="out-in"
          ><component :is="Component" /></Transition
      ></RouterView>
    </main>
  </div>
</template>

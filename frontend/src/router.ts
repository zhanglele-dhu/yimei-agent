import { createRouter, createWebHashHistory } from "vue-router";
import HomeView from "./views/HomeView.vue";
import OutlineView from "./views/OutlineView.vue";
import GenerateView from "./views/GenerateView.vue";
import ResultView from "./views/ResultView.vue";
import HistoryView from "./views/HistoryView.vue";
import SettingsView from "./views/SettingsView.vue";

export default createRouter({
  history: createWebHashHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: "/",
      name: "home",
      component: HomeView,
      meta: { title: "创作中心" },
    },
    {
      path: "/outline",
      name: "outline",
      component: OutlineView,
      meta: { title: "编辑大纲" },
    },
    {
      path: "/generate",
      name: "generate",
      component: GenerateView,
      meta: { title: "生成图片" },
    },
    {
      path: "/result",
      name: "result",
      component: ResultView,
      meta: { title: "创作结果" },
    },
    {
      path: "/history",
      name: "history",
      component: HistoryView,
      meta: { title: "历史记录" },
    },
    {
      path: "/settings",
      name: "settings",
      component: SettingsView,
      meta: { title: "模型设置" },
    },
  ],
});

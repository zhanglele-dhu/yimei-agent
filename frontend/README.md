# 灵感创作台前端（Vue 3 + TypeScript）

此目录是唯一的前端源码。页面使用 Vue 单文件组件，路由使用 Vue Router，跨页面创作状态使用 Pinia。旧工作台的 `app.js`、CSS 和 HTML 外壳不再参与运行。

## 从哪里开始看

| 文件 | 负责内容 |
| --- | --- |
| `src/App.vue` | 左侧导航、顶部栏、页面切换动画 |
| `src/router.ts` | URL 与页面的对应关系 |
| `src/views/HomeView.vue` | 输入主题、页数并请求大纲 |
| `src/views/OutlineView.vue` | 编辑/排序大纲、自动保存 |
| `src/views/GenerateView.vue` | 批量生成、逐页显示进度和失败 |
| `src/views/ResultView.vue` | 预览、单页重绘、生成标题正文、下载 ZIP |
| `src/views/HistoryView.vue` | 搜索、打开和删除历史作品 |
| `src/views/SettingsView.vue` | 配置图片模型 |
| `src/stores/generator.ts` | 当前创作数据、Local Storage 自动持久化、服务端同步 |
| `src/api/creator.ts` | 创作与历史 API 请求 |
| `src/api/client.ts` | 本地会话初始化、统一认证和 HTTP 请求 |
| `src/styles.css` | 全站颜色、布局、间距、卡片和响应式样式 |

## 新手修改示例

- 改页面上的标题或按钮文字：在对应 `src/views/*.vue` 搜索这段文字。
- 改页面长什么样：修改 `.vue` 的 `<template>`。
- 改按钮点下去做什么：修改 `<script setup lang="ts">` 中对应函数。
- 改颜色或手机布局：修改 `src/styles.css` 顶部变量或文件末尾的 `@media`。
- 改某个页面路径：修改 `src/router.ts`。
- 改创作数据如何保存：查看 `src/stores/generator.ts`，不要在页面中另写一套 Local Storage。
- 整理 Vue/TypeScript/CSS 缩进：进入 `frontend` 后运行 `npm run format`。

## 本机开发

```powershell
cd E:\aiPM\yimei-agent\frontend
npm ci
npm run dev
```

开发服务器打开后可访问终端显示的本机地址；`/api` 请求会代理到本机 8010 服务。

## 发布给本机启动器

```powershell
cd E:\aiPM\yimei-agent\frontend
npm ci
npm run typecheck
npm run build
```

Vite 将网页编译到 `studio/static/vue-app`。之后用 `start_studio.bat` 启动 Flask 服务即可，不需要单独启动 Vite。

## 保存规则

Pinia 中可恢复的创作状态会写入浏览器 Local Storage；大纲、图片文件名、文案和状态还会通过 `/api/history` 存到本机 SQLite 和图片目录。Local Storage 用于刷新后的快速恢复，后端历史 API 是可搜索、可跨浏览器恢复的持久记录。上传文件对象和 API 密钥不会写入浏览器 Local Storage。

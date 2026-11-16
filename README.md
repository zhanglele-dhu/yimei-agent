# 灵感创作台

一个本地运行的 AI 图文创作工作台。工作流是：输入一句话 → 自动生成多页大纲 → 用户编辑 → 图片模型逐页生成完整图片 → 单页重绘/生成标题正文 → 历史恢复与图片下载。

## 技术结构

- 前端：Vue 3、TypeScript、Vite、Vue Router、Pinia。
- 后端：Flask 应用工厂和功能 Blueprint；入口在 `studio/webapp.py`，接口模块位于 `studio/blueprints/`。
- 文本模型：OpenAI 兼容接口，默认 DeepSeek。
- 图片模型：OpenAI 图片生成兼容接口，默认 Seedream；模型负责生成带文字的完整卡片图片。
- 持久化：Pinia 的可序列化快照保存在 Local Storage；大纲、文案、图片文件和状态由 `/api/history` 保存到 SQLite/本地文件。导出 ZIP 仅包含图片。

## 运行

在项目根目录双击 `start_studio.bat`。开发者首次准备环境时按 [DEPLOYMENT.md](DEPLOYMENT.md) 安装 Python 依赖，并在 `frontend` 目录运行 `npm ci && npm run build`。

在“模型设置”页填写文本和图片模型接口。密钥只写入本机 `.env.card-model`，不会放进 Local Storage、历史记录或前端构建文件。不要在没有授权的情况下调用付费模型；这里只检查代码构建和本地页面，不自动生成图片。

## 维护前端

先从 [frontend/README.md](frontend/README.md) 入门；RedInk Vue 源码的结构分析在 [frontend/REDINK-FRONTEND-ANALYSIS.md](frontend/REDINK-FRONTEND-ANALYSIS.md)。前端源码仅在 `frontend/src`，不要编辑构建后的 `studio/static/vue-app/assets/*`。

## 模块图

```mermaid
flowchart LR
  Browser[Vue + Pinia] --> API[Flask /api Blueprint]
  API --> Outline[outline blueprint]
  API --> Content[content blueprint]
  API --> Generation[generation blueprint]
  API --> History[history blueprint]
  API --> Settings[settings blueprint]
  Outline --> TextModel[文本模型]
  Content --> TextModel
  Generation --> ImageModel[图片模型]
  History --> Store[(SQLite + 图片目录)]
  Browser --> Local[(Local Storage 快照)]
```

## 独立实现边界

RedInk 仓库以 CC BY-NC-SA 4.0 发布。本项目借鉴其产品阶段和前后端职责划分，独立编写代码、文案、Prompt 与视觉，不复制 RedInk 源码、素材或品牌；商业分发前应单独确认适用的授权边界。

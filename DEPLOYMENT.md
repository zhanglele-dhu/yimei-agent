# 本机部署

## 首次准备

1. Python 3.11+ 和 Node.js 20+ 已安装。
2. 在项目根目录创建虚拟环境并安装服务依赖：

   ```powershell
   py -3.13 -m venv .venv-studio
   .\.venv-studio\Scripts\python.exe -m pip install -r requirements-studio.lock.txt
   ```

3. 构建 Vue 页面：

   ```powershell
   cd frontend
   npm ci
   npm run typecheck
   npm run build
   cd ..
   ```

4. 双击 `start_studio.bat`，浏览器打开 `http://127.0.0.1:8010`。后端由 Waitress 运行，网页和 `/api` 使用同源地址。

## 模型配置

在“模型设置”输入文本模型和图片模型的 HTTPS 兼容接口、模型名称与 API Key。凭据保存到 `.env.card-model`；这个文件列入 `.gitignore`。输入后后端会更新当前进程配置，不需要把密钥写进前端。

生成大纲/文案会调用文本模型；生成/重绘图片会调用图片模型并产生费用。浏览器端构建与本地接口检查不执行这些模型调用。

## 数据保存与备份

- 浏览器当前创作状态：Local Storage。
- 服务端历史：`outputs/studio/tasks.sqlite3` 中的 `creator_records` 表。
- 生成图片：`outputs/studio/cards/<task_id>/`。

建议同时备份 SQLite 文件和 `cards` 目录。导出的 ZIP 仅含图片文件。

## 更新前端

修改 `frontend/src` 后，在 `frontend` 文件夹执行 `npm ci`、`npm run typecheck`、`npm run build`。再关闭旧启动窗口，重新双击 `start_studio.bat`。当前 `/healthz` 版本为 `cases-20261104-vue1`。

## 容器

Docker 镜像入口为 `studio.webapp:app`，通过 Waitress 提供 Flask Blueprint API 和 Vue 构建文件。容器持久化时将 `/data` 挂载到可靠存储，并设置 `STUDIO_DATA_DIR=/data` 与 `STUDIO_ACCESS_TOKEN`。容器部署尚未运行验证。

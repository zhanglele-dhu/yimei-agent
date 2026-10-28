# 运行说明

项目面向本机单用户使用。Windows 可参考 README 创建 Python 3.13 虚拟环境、安装依赖及 Playwright Chromium；配置 `.env` 后启动 `start_studio.bat`。`/healthz` 用于查看本机服务状态与版本。

第一次使用需要自行导入案例资料包和配置模型；`outputs/studio/` 存放任务数据库、素材、图片和本地索引，迁移前备份整个目录。`.env` 和 `.env.card-model` 保存模型配置与密钥，不要提交到 Git。

模型请求可能包含所选案例文字、OCR、参考图、写作内容；实拍页排版设计与视觉检查可能向配置的模型服务发送照片。请根据所用供应商检查数据处理设置。

Dockerfile 为部署起点，但本公开快照未验证容器构建或公网部署。公网运行需另外处理身份验证、HTTPS、持久化、资源配额与隐私保护。GitHub Pages 不运行此项目的 Python 后端。

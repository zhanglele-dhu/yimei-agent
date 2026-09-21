# 运行与部署

## 本机

双击start_studio.bat，保持窗口打开。浏览器自动打开并带入本机访问口令；口令保护任务、照片和模型接口，不是个人账户。

新机器：
```powershell
uv venv .venv-studio --python 3.13
uv pip install --python .venv-studio/Scripts/python.exe -r requirements-studio.lock.txt
.\.venv-studio\Scripts\python.exe run_studio.py
```

文字轨：.env 内 LLM_PROVIDER=deepseek 与 DEEPSEEK_API_KEY。视觉/画图轨：VISION_PROVIDER=glm + VISION_API_KEY（智谱 open.bigmodel.cn 的 API Key，视觉与画图共用），可选 STUDIO_VISION_MODEL / STUDIO_IMAGE_MODEL 覆盖默认的 glm-4v-plus / cogview-4。视觉轨未配置时自动降级。不要提交.env。用户实拍仅保存及本地排版，本版本不发送任何模型。

任务与图片在outputs/studio；先备份该目录再迁移机器。多人共用口令会共用数据，本版是单工作区演示。

## 容器

Dockerfile使用requirements-studio.lock.txt及当前studio、knowledge。配置STUDIO_ACCESS_TOKEN（至少24字符）、模型密钥，挂载/data以持久保存数据。公网需要HTTPS、身份和资源配额等部署配置；本次未执行容器构建或上线，不等于微信小程序已发布。

## 检查

```powershell
.\.venv-studio\Scripts\python.exe -m unittest test_studio -v
```

这些是模拟模型的接口测试，不替代真实模型、图片效果、浏览器及容器测试。

## 案例导入与恢复

在装有采集环境的机器上运行 `collector/export_cases.py`（本仓库内的采集器代码快照；带虚拟环境的实时采集目录在本机另处维护），得到案例资料 ZIP。在工作台"案例资料库"选择ZIP并导入；同一包重复导入复用版本。已创建任务保留选中的原版本，不会被新包静默替换。

工作台首页使用 `studio/static/index.html` 的视觉壳，实际交互由 `studio/static/app.js` 调用当前 API。连接后先在首页“案例资料管理”导入 ZIP，再点击“开始”走主题、案例、拆解、共创、导出；拆解中的检索、语言、视觉、资料、写作五步逐一确认，退回时填写建议后通过 `analysis-stage` 重做当前步；右上角“反馈”用于给已有草稿记录平台原文并请求分析。

刷新后恢复最近任务，或从任务列表选择。仅已保存内容持久化在SQLite，照片和输出文件也必须一起备份。模型失败不自动循环调用，显示错误后手动重试；原任务不丢失。

更新后先关闭旧启动窗口，再双击start_studio.bat。healthz应返回版本`cases-20260921-1`。启动器只在版本匹配时自动打开页面；不强制结束其他进程。

2026-09-17已真实调用DeepSeek跑通一条示例，完整运行证据在`outputs/studio/evidence/RUN-20260917_M22_demo/`。当前没有可用浏览器自动化界面，浏览器刷新/点击的实际体验仍待验收；API持久化与恢复已测。容器尚未构建验证。

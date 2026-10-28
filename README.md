# Yimei Agent · 医美图文创作工作台

面向医美科普图文的本地创作工作台。用户输入选题，参考导入的案例分析表达，确认方向与大纲，核对草稿后逐页生成图片并导出。

## 当前功能

- M22 选题调研：基于导入的案例整理方向，展示样本与依据。
- 语气库：按正文与 OCR 中的表达分类，选择语气后用于写作与审稿。
- 同类表达分析：确认本篇目的、受众、叙述与语气后，再补充资料和大纲。
- 图文共创：核对文字、上传实拍、生成和检查成图，导出素材。

## 本机运行

需要 Python 3.13 和网络可访问的模型 API。Windows 示例：

```powershell
python -m venv .venv-studio
.\.venv-studio\Scripts\python.exe -m pip install -r requirements-studio.lock.txt
.\.venv-studio\Scripts\python.exe -m playwright install chromium
```

在项目根目录新建 `.env`，按 `config.example.txt` 填写自己的文字模型设置，密钥不要提交或分享。双击 `start_studio.bat` 或运行 `python run_studio.py`，默认访问本机 `http://127.0.0.1:8010/`。成图设计和视觉检查可在网页“设置设计模型”配置支持图片输入的模型；配置保存在本机 `.env.card-model`。

## 数据和范围

首次使用需自行导入案例资料包；本仓库不包含原始案例、用户任务、图片、模型密钥或本机知识索引。任务和图片默认保存在 `outputs/studio/`，请自行备份。案例 OCR、选择的参考图片可能发送给所配置的模型；实拍页设计或成图视觉检查也可能将照片发送给模型服务商，请在使用前了解所选服务的数据处理方式。

当前项目是本地工作台，不包含小红书自动发布，也不是部署完成的在线服务。运行、数据与 Docker 注意事项见 `DEPLOYMENT.md`。生成内容与来源应由使用者核对。

## 测试

```powershell
.\.venv-studio\Scripts\python.exe -m unittest test_tones test_expression_flow test_writing_style test_research -q
```

第三方组件和技能见 `THIRD_PARTY_NOTICES.md`。

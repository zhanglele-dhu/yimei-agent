# 成品图片：Skill + 模型设计 + 视觉检查

## Seedream 整图生成

文字卡与对话卡支持 `generation_mode=seedream`。本地 `.env` 配置 `ARK_API_KEY` 后可使用。网页推荐并默认选择 AI 视觉排版：豆包模型生成 HTML/CSS，浏览器按已确认文字准确渲染；实拍页同样保留照片原像素。Seedream 整图作为适合短文案的可选模式。

```dotenv
ARK_API_KEY=在本地填写
SEEDREAM_MODEL=doubao-seedream-5-0-260128
ARK_CARD_REVIEW_MODEL=doubao-seed-2-0-lite-260428
```

空白的 `.env.card-model` 不阻止使用 Ark。已有明确的自定义视觉接口仍优先使用它，不会将 Ark 密钥发送到其他平台。

`studio/seedream_card.py` 读取实际小红书 skill、已确认文案与最多两张参考图，通过官方 `/images/generations` 生成 1728×2304 的整张图。Pillow 仅检查尺寸和转换图片编码，不绘制文字或版式。Seedream 开启默认 AI 水印。参考图只供借鉴视觉语言；制作提示不写入成图。

先验证检查模型可调用，再调用绘图模型；实际图片通过视觉模型核对文字与可读性后才保存为成品。检查不通过最多重新绘图一次。失败保留上一张成品，并将已生成但未通过检查的图片存入审计目录，避免当成可发布成品。

火山方舟需分别开通绘图模型和支持图片输入的检查模型。2026-10-24 开通后，带图检查调用已通过。实际 Seedream 长中文成图存在漏字、错字，两轮检查均已拦截；收紧提示后仍有文字错误，因此不作为长文案默认方式。预检包含白色测试图片，避免只测通纯文字接口。

同日实际豆包模型已生成 HTML/CSS 设计，修复本地 `justify-content` 被误当作 `content` 属性的问题后，复用该真实模型设计渲染并重新调用视觉模型，检查通过。结果保存在 `outputs/studio/model-design-review-20261024/live-first.png`，模型与检查记录在同目录 `live-first-meta.json`、`live-first-audit.json`。本机已打开检查实际成图；没有替换用户任务库中的旧图片。检查仅针对文字与版式，不是医学事实核实。

## 实际调用链

`POST /api/tasks/{id}/pages/{number}` 的 `generation_mode` 默认是 `model`。

1. 从仓库内的 `design_skills/xhs-note-creator/SKILL.md` 与 `professional.css` 读取规范，记录 skill 名称与 SHA-256。这两份文件复制自本机已安装的 xhs-note-creator；运行时不依赖用户目录、Codex 或 skill 发布脚本。
2. 把规范、最多两张参考页、本页真实照片（如有）、已确认的文字槽位、页面类型与风格偏好交给视觉模型。模型实际生成 HTML/CSS 和设计说明。
3. 校验模型输出：发布文字槽位必须恰好一次；不允许添加文案、脚本、外链或网络资源。去掉模型误重复的首节点 `id="card"`，系统已提供该根节点；移除并审计模型自创的装饰标签，只注入已确认文字槽位。Chromium 在隔离页面中按 1080×1440 渲染。对文字字号、边界、容器裁切、重叠和照片完整性执行几何检查。
4. 将实际成图交给视觉模型检查。检查失败时最多让模型修改一次；第二次仍不通过则停止。视觉检查针对可读性与版式，不是医学事实认证。
5. 只有检查通过才替换当前成品。失败记录保存到 `outputs/studio/designs/{task_id}` 和运行日志，旧图仍保留。不会自动退回固定模板。

`template` 是用户明确选择的另一种模式，保留原有确定性程序版式、聊天模板和 AI 装饰底图；元数据与界面明确标注没有模型视觉设计。

## 重新生成

2026-10-24 实拍页修复：含八个流程正文块时向设计模型传递标题、照片与正文空间预算，要求紧凑网格和不可收缩的照片区域；系统固定真实照片显示区域为 320px 高并保持 contain，避免模型只给外层 div 设置尺寸而让 img 使用天然小尺寸。仅将模型输出的一个空白 source-photo 图片占位符替换为系统 PHOTO 槽位，外部图片地址和其他标签仍禁止。

视觉检查同时输入成图和原始照片，核对照片完整性。几何失败在页面中显示简短中文，原始 BLOCK/PHOTO 检查信息仍保留在审计中。使用用户第 2 页的原始照片与文案、真实豆包设计返回结果完成 Chromium 渲染和真实视觉检查，结果为通过，位于 `outputs/studio/photo-review-20261024/live-photo.png`；旧任务成品未自动替换。

成品预览右侧的“重新生成”使用当前页已经确认的文字与照片，把上一版 HTML/CSS 带给模型并要求更换构图。只重做当前页，既有文案不被模型改写。有未保存改动时，需要先返回文字核对。

## 配置另一家视觉服务

在预览右侧点击“设置设计模型”，填写支持图片输入的 OpenAI Chat Completions 兼容接口：

- API Base URL：按服务商控制台复制，不包含密钥或查询参数。
- 视觉设计模型名。
- 视觉检查模型名：留空复用设计模型。
- 新平台 API Key：通过本机网页填写，不发送到聊天中。

保存到项目 `.env.card-model`，文件已加入 `.gitignore`。API 不返回密钥；切换 API 地址时必须同时提供新平台密钥，避免旧平台密钥被发送到其他域名。设置保存后即时生效，不改变 DeepSeek 文字模型或原有智谱案例分析/知识库配置。

也可以手动配置：

```dotenv
STUDIO_CARD_PROVIDER=custom
STUDIO_CARD_BASE_URL=https://你的服务商接口/v1
STUDIO_CARD_API_KEY=在本机填写
STUDIO_CARD_DESIGN_MODEL=你的视觉模型名称
STUDIO_CARD_REVIEW_MODEL=你的视觉模型名称
```

可参考阿里云百炼的 [Qwen3-VL-Plus](https://help.aliyun.com/zh/model-studio/qwen3-vl-plus) 和 [兼容接口说明](https://help.aliyun.com/en/model-studio/qwen-api-via-openai-chat-completions)。Base URL、地域、工作空间与密钥应相互匹配；不能据公开文档判断用户账户已有额度。

Docker 用 `STUDIO_CARD_SETTINGS_FILE=/data/card-model.env` 保存到数据卷。镜像构建中安装 Chromium 与所需系统库；本次未构建 Docker 镜像。

## 依赖与验证边界

安装 `requirements-studio.lock.txt` 后运行 `python -m playwright install chromium`。当前本机已安装 Playwright 1.64.1，并复用了匹配版本的本机 Chromium。

- `test_model_card.py` 的模型返回值是离线模拟；浏览器渲染与 API 持久化为真实执行，不能称为真实模型效果验证。
- 2026-10-24 对现有智谱密钥进行了真实调用，返回 429 / 1113（余额不足或无可用资源包），未产生通过模型检查的新成品。
- 已接入火山方舟 Seedream 并真实生成一张图；完整自动检查流程的当前状态见上面的 Seedream 记录。离线测试中的模拟通过不代表实际账户已开通检查模型。

成品元数据记录 `method=skill_model_html`、skill、设计模型、检查模型、设计说明、检查结果、几何检查、源照片摘要和审计文件名；导出的来源记录也保留这些信息。

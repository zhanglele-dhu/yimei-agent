---
name: xhs-note-creator
description: 小红书笔记素材创作技能。当用户需要创建小红书笔记素材时使用这个技能。技能包含：根据用户的需求和提供的资料，撰写小红书笔记内容（标题+正文），生成图片卡片（封面+正文卡片），以及发布小红书笔记。支持 8 种精美排版主题和 4 种智能分页模式。
---

## 本机运行环境（安装时补充）

运行脚本前先读 [LOCAL_SETUP.md](LOCAL_SETUP.md)，使用其中的独立 Python 环境。


# 小红书笔记创作技能

根据用户提供的资料或需求，创作小红书笔记内容、生成精美图片卡片，并可选择发布到小红书。

> 详细参数文档见 `references/params.md`

---

## 工作流程

### 第一步：撰写小红书笔记内容

根据用户需求和资料，创作符合小红书风格的内容：

**科普先判断受众，再写内容**：先根据用户指定的受众、选题和参考帖判断读者已经知道什么、最想弄明白什么，以及读完本篇能获得什么；形成简短的受众与表达方案，作为内部编辑信息，不写进成品。用户未指定时，入门科普可暂按正在了解该项目的非专业读者组织；不臆测年龄、性别、消费能力，不把推测说成平台调研结论。明确面向从业者的选题应保留专业深度。

**把知识变成读者愿意看的介绍**：先讲是什么、有什么特点、不同部分各有什么分工，再解释必要术语。每页聚焦一个问题，优先3到4条，每条用具体易懂的小标题加一到两句解释，段落间空一行。模块介绍要直接讲分工与有来源支持的特点，避免把正文写成术语分类表、连续定义、考试问答或到店提问清单。必要区别随对应要点讲清；次要参数与版本细节仅在选题需要时展开。保留用户明确要求与已确认大纲，不擅自删减，也不靠夸张安利、虚构体验或疗效承诺制造吸引力。

**标题**：不超过 20 字，吸引眼球，可用数字/疑问句/感叹号增强吸引力。

**正文**：段落清晰，点缀少量 Emoji（每段 1-2 个），短句短段，结尾附 5-10 个 SEO 标签。

**科普帖的英文缩写**：面向非专业读者时，每个专业英文缩写在整篇正文（含图中文字）首次出现时，使用“缩写（英文全称，中文名称）”，再用一句短解释说明它是什么；后文可直接使用缩写。标题和封面保持简短，把全称放到首次讲解该概念的正文知识点下。图集中的解释要实际出现在图片上，不能只留在发布文案或制作说明中。英文全称和中文译名按可靠来源核对；产品型号、商标不当作缩写硬展开，不确定的名称先查证。全称较长时分行排版或调整分页，不缩成难读小字；保留用户已确认文字时，先提出解释补充并由用户确认，再成图。

型号识别示例：M22、ResurFX直接保留名称；不能把厂商介绍平台的英文描述当作M22的英文全称。短句不等于省略含义，通俗类比仍须保持技术关系准确。

**分页与成图前检查**：先确定受众和内容方向，再按读者问题规划大纲，一页一个主要问题；常规2到4个要点、至多3个新术语，按阅读负担安排。参考帖页数不决定新图集页数，不为了压页数“信息不丢失”而把多个主题塞进一张。成图前先检查受众适配、问题是否回答、术语密度和来源支持。必改缺陷与可选润色分开；准确的通俗类比不需要来源逐字出现，不因风格偏好反复退回。

---

### 第二步：生成渲染用 Markdown 文档

**注意：此 Markdown 专为图片渲染设计，禁止直接使用上一步的笔记正文。**

文档结构：

```markdown
---
emoji: "🚀"
title: "封面大标题（≤15字）"
subtitle: "封面副标题（≤15字）"
---

# 正文内容...

---

# 第二张卡片内容...（使用 --- 手动分隔时）
```

分页策略选择：
- 内容需精确切分 → 用 `---` 手动分隔，配合 `-m separator`
- 内容长短不稳定 → 生成普通 Markdown，使用 `-m auto-split`

---

### 第三步：渲染图片卡片

```bash
python scripts/render_xhs.py <markdown_file> [options]
```

**默认主题**：`sketch`（手绘素描风格）  
**默认分页**：`separator`（按 `---` 分隔）

常用示例：

```bash
# 默认（sketch 主题 + 手动分页）
python scripts/render_xhs.py content.md

# 自动分页（推荐内容长短不定时）
python scripts/render_xhs.py content.md -m auto-split

# 切换主题
python scripts/render_xhs.py content.md -t playful-geometric -m auto-split

# 固定尺寸自动缩放
python scripts/render_xhs.py content.md -m auto-fit
```

生成结果：`cover.png`（封面）+ `card_1.png`、`card_2.png`...（正文卡片）

**可用主题**（`-t`）：`sketch`、`default`、`playful-geometric`、`neo-brutalism`、`botanical`、`professional`、`retro`、`terminal`

**分页模式**（`-m`）：`separator`、`auto-fit`、`auto-split`、`dynamic`

> 完整参数说明见 `references/params.md`

---

### 第四步：发布小红书笔记（可选）

**前置条件**：安装 Python 与 Node.js 依赖，并配置 `.env` 中的
`XHS_CREATOR_COOKIE`。Cookie 必须来自已登录的
`https://creator.xiaohongshu.com`（详见 `references/params.md`）。

```bash
# 默认仅自己可见（推荐先预览确认）
python scripts/publish_xhs.py --title "笔记标题" --desc "笔记描述" \
  --images cover.png card_1.png card_2.png

# 确认无误后公开发布
python scripts/publish_xhs.py --title "笔记标题" --desc "笔记描述" \
  --images cover.png card_1.png card_2.png --public
```

> **默认以「仅自己可见」发布**，加 `--public` 参数才会公开。
> 发布链路已内置在当前技能中，不依赖外部 API 服务或其他项目目录。

---

## 技能资源

### 脚本
- `scripts/render_xhs.py` — 渲染脚本（主推，8 主题 + 4 分页模式）
- `scripts/render_xhs_v2.py` — 渲染脚本 V2（备用，7 种渐变色彩风格）
- `scripts/publish_xhs.py` — 发布脚本

### 模板与样式
- `assets/cover.html` — 封面 HTML 模板
- `assets/card.html` — 正文卡片 HTML 模板
- `assets/styles.css` — 公共容器样式
- `assets/themes/` — 各主题 CSS 文件

### 参考文档
- `references/params.md` — 完整参数参考（主题/模式/发布参数）

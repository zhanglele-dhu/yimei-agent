import type { CreatorRecord, OutlinePage } from "../api/types";

export const DEMO_TOPIC = "M22医美科普";
export const DEMO_PAGES: OutlinePage[] = [
  {
    index: 0,
    type: "cover",
    content:
      "# 以为只是洗个脸？M22超光子彻底讲透！\n\n别再当医美大冤种！OPT和AOPT到底差在哪？为什么有人做完白成一道光，有人做完反黑又爆痘？\n\n🔬 本期硬核拆解：\n- 光子嫩肤天花板M22的技术底层\n- 7款核心滤光片针对问题全对照\n- 照着做不踩坑的“做前必读清单”\n\n🎨 配图建议：法式复古医学杂志排版，温润暖杏色哑光底色；中央透明晶体三棱镜折射柔和彩虹光谱，搭配皮肤截面细线草图与红色印章“Skin Logic No.22”。",
  },
  {
    index: 1,
    type: "content",
    content:
      "## 💡 一分钟看懂：M22怎么选滤光片？\n\nM22本质是“强脉冲光”，不是激光！关键在**对症选片**：\n\n- **祛红血丝/敏感泛红** 👉 选 `Vascular` / `530nm`，精准封闭异常微血管\n- **晒斑/雀斑/提亮肤色** 👉 选 `560nm` / `590nm`，爆破表层黑色素\n- **抗炎控油/红肿痘痘** 👉 选 `Acne` 滤光片，消灭痤疮丙酸杆菌\n- **毛孔粗大/嫩肤紧致** 👉 选 `640nm` / `695nm`，刺激胶原新生\n\n⚠️ **OPT vs AOPT区别**：AOPT多加了两块专属针对血管和痤疮的超光子滤波片，能量调控更自由、痛感更低！\n\n🎨 配图建议：延续暖杏色哑光纸张与科学手绘风格，以四格玻片图示展示红、蓝、琥珀黄、深紫晶体，标注波长，并用墨绿色箭头指示光热传导。",
  },
  {
    index: 2,
    type: "summary",
    content:
      "## 🚨 做前牢记这3点，效果翻倍不翻车！\n\n1. **认准设备正品验真**：仪器机身、手具、医生都必须支持扫码认证，拒绝山寨“组装机”！\n2. **“医生参数”远大于“仪器本身”**：能量不是越高越好，打到微红微热即止，过度追求疼痛容易屏障受损。\n3. **黄金72小时术后护理**：\n   - 前3天纯物理防晒（帽子口罩）+ 械字号医用敷料\n   - 1周内严禁刷酸、A醇、烟酰胺及蒸桑拿！\n\n赶紧「收藏」这篇，面诊时直接拿出来照着问医生！✨\n\n🎨 配图建议：延续暖杏色与墨绿色的高级杂志风，磨砂玻璃瓶搭配手写避坑清单便签，柔和光斑和轻微菲林颗粒。",
  },
];

export const DEMO_IMAGES = DEMO_PAGES.map(
  (_, index) => `${import.meta.env.BASE_URL}demo/page-${index + 1}.png`,
);
export const DEMO_RECORD_ID = "demo-m22-record";
export const DEMO_COPY = {
  titles: ["M22是什么？3页带你快速看懂", "关于M22，先弄清这几个概念"],
  copywriting:
    "总看到M22却不太清楚它指什么？这篇先从名称、语境和常见理解入手，帮你快速理清。遇到具体说法时，记得结合上下文确认。",
  tags: ["#M22科普", "#知识分享", "#快速了解"],
};

export function makeDemoRecord(): CreatorRecord {
  const now = new Date().toISOString();
  return {
    id: DEMO_RECORD_ID,
    title: DEMO_TOPIC,
    created_at: now,
    updated_at: now,
    status: "completed",
    thumbnail: DEMO_IMAGES[0],
    page_count: DEMO_PAGES.length,
    task_id: "demo-m22",
    outline: {
      raw: DEMO_PAGES.map((page) => page.content).join("\n\n<page>\n\n"),
      pages: DEMO_PAGES,
    },
    images: { task_id: "demo-m22", generated: DEMO_IMAGES },
    content: DEMO_COPY,
  };
}

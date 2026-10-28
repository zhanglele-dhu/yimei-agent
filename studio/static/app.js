const screens = [...document.querySelectorAll('.screen')];
const pageRoot = document.querySelector('.page');
const toast = document.getElementById('toast');
const fragment = new URLSearchParams(location.hash.slice(1));
let token = fragment.get('token') || sessionStorage.getItem('studio_token') || '';
let task = null;
let bundles = [];
let tasks = [];
let screenId = 'home';
let mode = 'high';
let chosenStrategy = '';
let strategyChosen = false;
let busy = false;
let serverReachable = null;
let objectUrls = [];
let setupDraft = null;
let researchState = null;
let tonePresets = [];
let toneData = null;
let selectedTone = "friend-sharing";
let toneSource = null;
let toneAnalyzing = false;
let toneStop = false;
let toneError = "";
let activeNav = 'homeNav';
let modalTrigger = null;

if (fragment.has('token')) history.replaceState(null, '', location.pathname + location.search);

const $ = id => document.getElementById(id);

function ensureStatus() {
  let status = document.getElementById('status');
  if (!status) {
    status = document.createElement('div');
    status.id = 'status';
    status.className = 'status-bar';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    pageRoot.prepend(status);
  }
  return status;
}

function setStatus(message, error = false) {
  const status = ensureStatus();
  status.textContent = message;
  status.classList.toggle('error', error);
}

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}

function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'icon');
  svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', '#icon-' + name);
  svg.append(use);
  return svg;
}

function field(parent, label, value = '', tag = 'textarea') {
  const wrap = el('div', undefined, 'field');
  const lab = el('label', label);
  const input = el(tag);
  input.value = value || '';
  lab.append(input);
  wrap.append(lab);
  parent.append(wrap);
  return input;
}

function check(parent, label, checked = false) {
  const wrap = el('label', undefined, 'inline-check');
  const input = el('input');
  input.type = 'checkbox';
  input.checked = checked;
  wrap.append(input, document.createTextNode(label));
  parent.append(wrap);
  return input;
}

function button(text, handler, cls = 'btn primary') {
  const b = el('button', text, cls);
  b.type = 'button';
  b.addEventListener('click', () => run(handler, text));
  return b;
}

function showToast(message) {
  if (!toast) return;
  toast.textContent = message;
  toast.classList.add('show');
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove('show'), 3000);
}

async function run(handler, actionLabel = '正在处理') {
  if (busy) return;
  busy = true;
  const controls = [...document.querySelectorAll('button')];
  const disabledBefore = controls.map(b => [b, b.disabled]);
  controls.forEach(b => { b.disabled = true; });
  const startedAt = Date.now();
  setStatus(actionLabel + '，请稍候…');
  ensureStatus().classList.add('loading');
  pageRoot.setAttribute('aria-busy', 'true');
  const ticker = window.setInterval(() => {
    const seconds = Math.round((Date.now() - startedAt) / 1000);
    if (seconds >= 10) setStatus('仍在处理中，已等待 ' + seconds + ' 秒。模型设计和图片检查需要一些时间，请勿重复点击。');
  }, 5000);
  try {
    await handler();
    setStatus(['create','tones'].includes(screenId) ? '' : '操作已完成，可检查结果后继续。');
  } catch (error) {
    if (task) {
      try {
        const latest = await request('/tasks/' + task.id);
        if (latest.revision !== task.revision) {
          task = latest;
          await render();
        }
      } catch (_) {}
    }
    setStatus('未完成：' + (error.message || error), true);
    const modal = document.querySelector('.modal.show .modal-box');
    if (modal) {
      let message = modal.querySelector('.modal-error');
      if (!message) {
        message = el('p', '', 'modal-error');
        message.setAttribute('role', 'alert');
        modal.querySelector('header').after(message);
      }
      message.textContent = error.message || String(error);
    }
  } finally {
    window.clearInterval(ticker);
    ensureStatus().classList.remove('loading');
    pageRoot.removeAttribute('aria-busy');
    disabledBefore.forEach(([b, disabled]) => { b.disabled = disabled; });
    busy = false;
  }
}

function connectionError() {
  serverReachable = false;
  $('connectionState').textContent = '本机服务未连接';
  $('connectionState').classList.remove('connected');
  $('retryStartup').textContent = '重新连接'; $('retryStartup').hidden = false;
  const error = new Error('无法连接本机工作台。请重新打开 start_studio.bat 并保持启动窗口运行；恢复后先检查本页成品，再决定是否重新生成。当前编辑文字会在本标签页恢复。');
  error.connectionLost = true;
  return error;
}

async function request(path, method = 'GET', body, binary = false) {
  const headers = { Authorization: 'Bearer ' + token };
  if (body && !(body instanceof FormData)) headers['Content-Type'] = 'application/json';
  let response;
  try { response = await fetch('/api' + path, {
    method,
    headers,
    body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined
  }); } catch (_) {
    throw connectionError();
  }
  serverReachable = true;
  if (!response.ok) {
    let detail = '';
    try {
      const data = await response.json();
      detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
    } catch (_) {
      detail = '服务未返回有效结果，请检查启动窗口。';
    }
    if (response.status === 401) detail = '本机服务验证已失效，请刷新页面。';
    if (response.status === 404 && path === '/card-model-settings') detail = '后端尚未加载AI设计流程，请重新双击 start_studio.bat 更新启动后再试。';
    if (response.status === 404 && path.includes('/analysis-stage')) {
      detail = '当前后端未加载分步确认接口，请关闭旧启动窗口后重新双击 start_studio.bat，再刷新页面。';
    }
    throw new Error(detail);
  }
  return binary ? response.blob() : response.json();
}

async function refreshLists() {
  if (!token) return;
  const result = await Promise.all([request('/tasks'), request('/bundles'), request('/tone-presets')]);
  tasks = result[0];
  bundles = result[1];
  tonePresets = result[2].presets;
}

const STAGE_LABELS_FULL = {
  expression_review: '待确认表达',
  materials_pending: '待检索资料',
  outline_review: '待核对大纲',
  candidate: '案例已选定',
  no_match: '无相关案例',
  analysis_review: '拆解确认中',
  ready_to_write: '待生成草稿',
  making: '逐页制作中',
  ready_to_export: '已可导出'
};

function taskStageBadge(row) {
  if (row.legacy) return '历史任务';
  if (row.exported) return '已确认导出';
  return STAGE_LABELS_FULL[row.stage] || '进行中';
}

async function openTask(id) {
  setupDraft = null;
  task = await request('/tasks/' + id);
  sessionStorage.setItem('studio_task', task.id);
  chosenStrategy = sessionStorage.getItem('studio_strategy_' + task.id) || '';
  strategyChosen = Boolean(chosenStrategy);
  screenId = task.schema_version !== 2 ? 'modes' : (task.copy_review?.confirmed ? 'publish' : task.draft ? 'create' : 'modes');
  await render();
}

async function deleteTask(row) {
  const label = (row.question || '').slice(0, 30);
  if (!window.confirm('删除后任务记录和已生成的图片都无法恢复，确定删除「' + label + '」？')) return;
  await request('/tasks/' + row.id + '?revision=' + row.revision, 'DELETE');
  if (task && task.id === row.id) {
    task = null;
    sessionStorage.removeItem('studio_task');
    screenId = 'home';
  }
  await refreshLists();
  await render();
  showToast('任务已删除');
}

function revokeUrls() {
  objectUrls.forEach(url => URL.revokeObjectURL(url));
  objectUrls = [];
}

function go(next) {
  document.body.classList.toggle('creation-focus', next === 'create');
  document.body.classList.toggle('home-focus', next === 'home');
  document.body.classList.toggle('analysis-focus', next === 'modes' && Boolean(task?.case && !task.draft && !task.confirmed_analysis && mode === 'high' && task.schema_version === 2));
  screenId = next;
  screens.forEach(screen => screen.classList.toggle('active', screen.id === next));
  const labels = { home: '创作概览', topics: '选择主题', modes: '案例拆解', create: '图文共创', publish: '检查与导出', tones: '语气库' };
  $('workspaceTitle').textContent = next === 'modes' && task?.request?.workflow === 'expression-first' ? '表达与创作' : labels[next] || '创作概览';
  $('taskCount').textContent = token ? tasks.length : '—';
  $('connectionState').classList.toggle('connected', Boolean(token) && serverReachable !== false);
  ['homeNav', 'tasksNav', 'libraryBtn', 'tonesNav'].forEach(id => {
    const selected = (next === 'home' && id === activeNav) || (next === 'tones' && id === 'tonesNav');
    $(id).classList.toggle('active', selected);
    if (selected) $(id).setAttribute('aria-current', 'page');
    else $(id).removeAttribute('aria-current');
  });
  window.scrollTo({ top: 0, behavior: 'instant' });
}

function startNewContent() {
  if (busy) return;
  task = null;
  setupDraft = null;
  sessionStorage.removeItem('studio_task');
  chosenStrategy = '';
  strategyChosen = false;
  go('topics');
  render();
  if (!token) setStatus('服务尚未就绪，请刷新页面或重新双击 start_studio.bat。', true);
}

function sourceCard(parent) {
  if (!task || !task.case) return;
  const card = el('div', undefined, 'source-card');
  const left = el('div');
  left.append(
    el('strong', '主要参考：' + (task.case.title || '原帖标题未采到')),
    el('div', String(task.case.likes ?? '未知') + ' 赞 · 采集快照 ' + (task.case.collected_at || '时间未知'), 'source-link')
  );
  const link = el('a', '打开小红书原帖');
  link.href = task.case.url;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  card.append(left, link);
  parent.append(card);
}

async function imageInto(parent, path, alt) {
  try {
    const blob = await request(path, 'GET', null, true);
    const url = URL.createObjectURL(blob);
    objectUrls.push(url);
    const image = el('img');
    image.src = url;
    image.alt = alt;
    image.className = 'preview';
    parent.append(image);
    return image;
  } catch (error) {
    parent.append(el('p', '图片未加载：' + error.message, 'review'));
  }
}

function referencePostLink(label = '在小红书查看原帖') {
  let url;
  try {
    url = new URL(task?.case?.url || '');
    if (!['https:', 'http:'].includes(url.protocol)) return null;
  } catch (_) { return null; }
  const link = el('a', undefined, 'reference-post-link');
  link.href = url.href;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  link.append(icon('external'), el('span', label));
  return link;
}

function openReferencePreview(image, pageNumber, trigger) {
  const dialog = el('dialog', undefined, 'reference-viewer');
  dialog.setAttribute('aria-label', '参考原帖第 ' + pageNumber + ' 页大图');
  const header = el('header', undefined, 'reference-viewer-header');
  const title = el('div', undefined, 'reference-viewer-title');
  title.append(icon('book'), el('h2', '参考原帖 · 第 ' + pageNumber + ' 页'));
  const close = el('button', undefined, 'close');
  close.type = 'button';
  close.setAttribute('aria-label', '关闭参考大图');
  close.append(icon('close'));
  close.addEventListener('click', () => dialog.close());
  header.append(title, close);
  const picture = image.cloneNode(true);
  picture.className = 'reference-viewer-image';
  const body = el('div', undefined, 'reference-viewer-body');
  body.append(picture);
  const footer = el('footer', undefined, 'reference-viewer-footer');
  footer.append(el('p', task?.case?.title || '参考案例', 'reference-case-title'));
  const link = referencePostLink();
  if (link) footer.append(link);
  dialog.append(header, body, footer);
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
  dialog.addEventListener('close', () => {
    dialog.remove();
    if (trigger?.isConnected) trigger.focus();
  });
  document.body.append(dialog);
  dialog.showModal();
}

function referenceThumbnail(image, pageNumber, compact = false) {
  const thumb = el('button', undefined, 'reference-thumbnail' + (compact ? ' compact' : ''));
  thumb.type = 'button';
  thumb.setAttribute('aria-label', '放大查看参考原帖第 ' + pageNumber + ' 页');
  thumb.setAttribute('aria-haspopup', 'dialog');
  const picture = image.cloneNode(true);
  const caption = el('span', undefined, 'reference-thumbnail-caption');
  caption.append(icon('zoom'), document.createTextNode('第 ' + pageNumber + ' 页 · 查看大图'));
  thumb.append(picture, caption);
  thumb.addEventListener('click', () => openReferencePreview(image, pageNumber, thumb));
  return thumb;
}

async function referencePages(parent, title = '查看参考原图与 OCR') {
  if (!task || !task.case) return;
  const details = el('details');
  details.open = !task.analysis;
  details.append(el('summary', title));
  const grid = el('div', undefined, 'case-pages');
  for (const page of task.case.pages) {
    const card = el('article', undefined, 'case-page');
    card.append(el('h3', '原帖第 ' + page.number + ' 页'));
    await imageInto(card, '/tasks/' + task.id + '/reference/' + page.number, '参考原帖第' + page.number + '页');
    card.append(el('pre', page.ocr || '本页未识别出文字，不能断言图中没有文字。'));
    grid.append(card);
  }
  details.append(grid, el('h3', '采集正文'), el('p', task.case.body || '正文缺失'));
  parent.append(details);
}

const ANALYSIS_STAGE_KEYS = ['retrieval', 'language', 'visual', 'facts', 'writing'];
const STAGE_LABELS = { retrieval: '检索案例', language: '语言分析', visual: '视觉分析', facts: '事实资料', writing: '写作规则' };
const analysisViews = new Map();
const stageFeedbackDrafts = new Map();
const writingDrafts = new Map();
let captureWritingDraft = null;

function viewedAnalysisStage() {
  const saved = analysisViews.get(task?.id);
  return saved && (stageState(saved) === 'accepted' || saved === currentAnalysisStage()) ? saved : currentAnalysisStage();
}

async function visitAnalysisStage(stage) {
  if (!stage || (stageState(stage) !== 'accepted' && stage !== currentAnalysisStage())) return;
  if (captureWritingDraft) captureWritingDraft();
  captureWritingDraft = null;
  analysisViews.set(task.id, stage);
  await render();
  document.querySelector('.stage-panel')?.scrollIntoView({ block: 'start' });
}

function stageState(stage) {
  if (!task) return 'blocked';
  const index = ANALYSIS_STAGE_KEYS.indexOf(stage);
  if (index > 0 && ANALYSIS_STAGE_KEYS.slice(0, index).some(previous => stageState(previous) !== 'accepted')) return 'blocked';
  const saved = task.analysis_stages?.[stage]?.status;
  if (saved) return saved;
  if (stage === 'retrieval') return task.case ? 'ready' : 'blocked';
  return task.analysis ? 'ready' : 'blocked';
}

function currentAnalysisStage() {
  return ANALYSIS_STAGE_KEYS.find(stage => stageState(stage) !== 'accepted') || null;
}

function stepStatus(kind) {
  const state = stageState(ANALYSIS_STAGE_KEYS[kind - 1]);
  return { accepted: '已确认', ready: '待你确认', rejected: '已退回', blocked: '等待前一步' }[state] || '待开始';
}

function pipeline(parent, compact = false) {
  const viewed = viewedAnalysisStage();
  const navigable = Boolean(task?.case && !task.draft && viewed);
  if (navigable && !compact) {
    const nav = el('nav', undefined, 'stage-navigation');
    nav.setAttribute('aria-label', '分析步骤导航');
    const index = ANALYSIS_STAGE_KEYS.indexOf(viewed);
    const back = button('返回上一步', () => visitAnalysisStage(ANALYSIS_STAGE_KEYS[index - 1]), 'btn quiet');
    back.disabled = index === 0;
    nav.append(back, el('span', '第 ' + (index + 1) + ' / 5 步 · ' + STAGE_LABELS[viewed], 'stage-navigation-label'));
    if (viewed !== currentAnalysisStage()) {
      nav.append(button('继续下一步', () => visitAnalysisStage(ANALYSIS_STAGE_KEYS[index + 1]), 'btn primary'));
    } else {
      nav.append(el('span', '确认本步后继续', 'step-state'));
    }
    parent.append(nav);
  }
  const wrap = el('div', undefined, 'pipeline');
  const steps = [
    ['1', '检索案例', '相关性 → 点赞快照'],
    ['2', '语言分析', '标题、开头、结构'],
    ['3', '视觉分析', '原图、逐页画面'],
    ['4', '事实资料', '来源与合规边界'],
    ['5', '写作规则', '形成可选方案']
  ];
  steps.forEach(([num, title, hint], index) => {
    const key = ANALYSIS_STAGE_KEYS[index];
    const item = el(navigable ? 'button' : 'div', undefined, 'pipe');
    if (navigable) {
      item.type = 'button';
      item.disabled = stageState(key) !== 'accepted' && key !== currentAnalysisStage();
      item.setAttribute('aria-label', title + '，' + stepStatus(index + 1));
      item.addEventListener('click', () => run(() => visitAnalysisStage(key), '切换步骤'));
      if (key === viewed) item.setAttribute('aria-current', 'step');
    }
    const done = stepStatus(index + 1) === '已确认';
    if (done) item.classList.add('done');
    if (key === viewed) item.classList.add('current');
    item.append(el('div', num, 'pipe-num'), el('b', title), el('small', hint), el('div', stepStatus(index + 1), 'step-state' + (done ? ' done' : '')));
    wrap.append(item);
  });
  parent.append(wrap);
}

// 与 studio/prompts.py 的 DEMO_SHOP_FACTS 保持一致（测试会校验两边一致）
const DEMO_SHOP_FACTS = [
  '【门店与设备｜示例资料：含公开资料参考值，正式使用请替换为门店真实信息】',
  '本店为正规医美机构（演示示例），配备科医人 Lumenis M22 AOPT 超光子平台（第七代强脉冲光，蓝宝石接触冷却），已配齐全部 8 张原厂滤光片：515/560/590/615/640/695nm 六张经典滤光片，以及 VASCULAR 血管专用（530-650+900-1200nm 双波段）与 ACNE 痤疮专用（400-600+800-1200nm 双波段）两张超膜双波滤光片；平台搭载 1565nm ResurFX 非剥脱点阵激光模块。参数来源：厂商官网与公开产品资料。',
  '【医师与资质｜示例表述】',
  '治疗由持证医师操作，主诊医师具备美容主诊医师备案；首次治疗先做皮肤检测与光斑测试，术前签署知情同意书。（示例表述，正式使用以门店实际资质材料为准）',
  '【咨询流程】',
  '线上初步咨询 → 到店登记 → 皮肤检测 → 医生面诊评估 → 讲解适合的滤光片与方案 → 说明价格与套餐 → 预约治疗。',
  '【价格政策｜示例价格，仅演示】',
  '全脸 M22 光子嫩肤单次示例价 1280 元；3 次疗程包示例价 3280 元；VASCULAR/ACNE 专项单次示例价 1580 元。以上为公开行情参考值（全脸单次常见约 1000-3000 元），最终以店内公示与面诊为准。',
  '【顾客最常问（示例答复口径）】',
  '做一次多久：全脸约 20-30 分钟；疼不疼：橡皮筋轻弹感，可敷表麻缓解；做几次：建议 3-5 次为一疗程，间隔 3-4 周；恢复期：术后轻微泛红数小时至 1-2 天，个别有轻微脱皮；术后护理：严格防晒、加强保湿，暂停酸类与磨砂产品 3-5 天。',
  '【门店口径】',
  '效果因人而异，不做疗效承诺；孕期、光敏体质、近期暴晒、皮肤有炎症或口服异维A酸期间需提前告知医生。',
  '【本篇要求】',
  '科普向内容；价格可引用上方示例价，并注明"以门店公示与面诊为准"；结尾引导顾客到店面诊咨询。（本段整体为示例门店资料，正式发布前必须替换为门店真实信息）'
].join('\n');

function setupPanel(parent) {
  const values = setupDraft || task?.request || {};
  const panel = el('details', undefined, 'panel setup-panel');
  panel.open = !task;
  panel.append(el('summary','创作需求与资料 · 展开修改'));
  panel.append(el('h2', '本次主题参数'), el('p', '这些信息用于筛选相关案例，也决定 AI 可以写哪些门店事实。', 'muted'));
  const grid = el('div', undefined, 'form-grid');
  const bundle = field(grid, '案例资料版本', '', 'select');
  bundle.id = 'bundle';
  bundles.forEach(item => {
    const option = el('option', item.version + ' · ' + item.count + '篇');
    option.value = item.bundle_id;
    bundle.append(option);
  });
  if (values.bundle_id) bundle.value = values.bundle_id;
  const voice = field(grid, '表达语气 · 独立于内容方向', '', 'select');
  voice.id = 'writingStyle';
  for (const preset of tonePresets) {const option=el('option',preset.title);option.value=preset.id;voice.append(option);}
  voice.value = values.writing_style || 'friend-sharing';
  const audience = field(grid, '给谁看', values.audience ?? '刚了解该项目的读者', 'input');
  audience.id = 'audience';
  const project = field(grid, '项目（也可以从需求中自动识别）', values.project ?? '自动识别', 'input');
  project.id = 'project';
  const question = field(grid, '告诉 AI 你想做什么', values.question ?? '做一篇 M22 知识科普，讲清是什么、仪器区别和滤片知识，参考同类高赞帖子，不做咨询引流。');
  question.id = 'question';
  question.maxLength = 1000;
  const facts = field(grid, '已有资料（选填）', values.facts ?? '');
  facts.id = 'facts';
  facts.maxLength = 6000;
  const factsWrap = facts.closest('.field');
  if (factsWrap) factsWrap.classList.add('wide');
  panel.append(el('p', 'AI 会识别项目、内容方向和要点，匹配同类参考。科普按知识来讲，咨询按流程来讲。', 'muted'));
  panel.append(grid);
  grid.addEventListener('input', () => { setupDraft = currentRequest(); });
  grid.addEventListener('change', () => { setupDraft = currentRequest(); });
  parent.append(panel);
  return { bundle, audience, question, facts };
}

function currentRequest() {
  return {
    project: document.getElementById('project')?.value.trim() || '自动识别',
    audience: document.getElementById('audience')?.value.trim() || '刚了解该项目的读者',
    question: document.getElementById('question')?.value.trim() || '',
    facts: document.getElementById('facts')?.value.trim() || '',
    writing_style: document.getElementById('writingStyle')?.value || setupDraft?.writing_style || task?.request?.writing_style || 'friend-sharing',
    research_id: setupDraft?.research_id || '',
    bundle_id: document.getElementById('bundle')?.value || bundles[0]?.bundle_id || ''
  };
}

async function startHighWorkflow(override = null) {
  if (!token) {
    setStatus('服务尚未就绪，请刷新页面或重新双击 start_studio.bat。', true);
    return;
  }
  const body = {workflow:'expression-first',writing_style:'friend-sharing', ...(override || currentRequest())};
  if (!body.question) throw new Error('请先写下你想做的内容');
  if (!body.bundle_id) throw new Error('还没有案例资料，请先在案例资料管理中导入 ZIP');
  const sameRequest = task && task.request && ['project', 'audience', 'question', 'facts', 'bundle_id', 'workflow', 'writing_style'].every(key => task.request[key] === body[key]);
  if (!sameRequest || task.stage === 'no_match') {
    task = await request('/tasks', 'POST', body);
    chosenStrategy = '';
    strategyChosen = false;
    sessionStorage.setItem('studio_task', task.id);
    await refreshLists();
    await render();
  }
  if (!task.case) return;
  if (!task.analysis && !task.expression) {
    task = await request('/tasks/' + task.id + '/analyze', 'POST', { revision: task.revision });
    await refreshLists();
    await render();
  }
}

function evidenceRow(parent) {
  const row = el('div', undefined, 'evidence-row');
  [
    '案例：' + (task.case?.likes ?? '未知') + ' 赞',
    '原图：' + (task.case?.pages?.length || 0) + ' 页',
    'OCR：已保存',
    '来源：CASE + GUIDE + K1（如适用）'
  ].forEach(value => row.append(el('span', value, 'evidence')));
  parent.append(row);
}

function sourceEvidence(parent) {
  const trace = [...(task.traces || [])].reverse().find(item => item.sources);
  const sources = trace?.sources || [];
  const box = el('div', undefined, 'evidence-row');
  sources.forEach(source => {
    const item = el('span', undefined, 'evidence');
    item.append(el('b', source.id + ' · '), document.createTextNode(source.type || '未标注类型'));
    box.append(item);
  });
  parent.append(box);
}

async function decideStage(stage, decision, feedback, analysisOverride) {
  if (decision === 'reject' && !(feedback || '').trim()) throw new Error('退回当前结果时必须填写修改建议');
  task = await request('/tasks/' + task.id + '/analysis-stage', 'POST', {
    revision: task.revision,
    stage,
    decision,
    feedback: feedback || ''
  });
  analysisViews.delete(task.id);
  stageFeedbackDrafts.delete(task.id + ':' + stage);
  writingDrafts.delete(task.id);
  captureWritingDraft = null;
  await refreshLists();
  if (decision === 'accept' && stage === 'retrieval' && !task.analysis) {
    task = await request('/tasks/' + task.id + '/analyze', 'POST', { revision: task.revision });
    await refreshLists();
  }
  if (decision === 'accept' && stage === 'writing') {
    task = await request('/tasks/' + task.id + '/confirm-analysis', 'POST', {
      revision: task.revision,
      analysis: analysisOverride || task.analysis
    });
    task = await request('/tasks/' + task.id + '/draft', 'POST', { revision: task.revision });
    await refreshLists();
    screenId = 'create';
  }
  await render();
}

async function rejectRetrieval(feedback) {
  if (!feedback.trim()) throw new Error('退回检索结果时必须填写修改建议');
  const oldRequest = { ...task.request };
  task = await request('/tasks/' + task.id + '/analysis-stage', 'POST', {
    revision: task.revision,
    stage: 'retrieval',
    decision: 'reject',
    feedback
  });
  oldRequest.question = oldRequest.question + '\n检索补充：' + feedback;
  setupDraft = oldRequest;
  task = null;
  sessionStorage.removeItem('studio_task');
  screenId = 'modes';
  await render();
  const question = document.getElementById('question');
  const audience = document.getElementById('audience');
  const facts = document.getElementById('facts');
  const bundle = document.getElementById('bundle');
  if (question) question.value = oldRequest.question;
  if (audience) audience.value = oldRequest.audience;
  if (facts) facts.value = oldRequest.facts;
  if (bundle) bundle.value = oldRequest.bundle_id;
  await startHighWorkflow();
}

function stageDecisionBox(parent, stage, allowAccept = true, acceptHandler) {
  const wrap = el('div', undefined, 'stage-decision');
  const revision = el('details', undefined, 'stage-revision');
  revision.append(el('summary', '提出修改意见'));
  const feedbackKey = task.id + ':' + stage;
  const feedback = field(revision, '希望 AI 怎么修改？', stageFeedbackDrafts.get(feedbackKey) || '');
  feedback.placeholder = '例如：保留设备对比结构，把术语解释得更通俗。';
  feedback.addEventListener('input', () => stageFeedbackDrafts.set(feedbackKey, feedback.value));
  feedback.maxLength = 2000;
  const actions = el('div', undefined, 'page-actions');
  if (allowAccept) actions.append(button('采用这一步结果，进入下一步', () => acceptHandler ? acceptHandler() : decideStage(stage, 'accept', ''), 'btn primary'));
  revision.append(button('不采用，按我的建议重做', () => {
    if (stage === 'retrieval') return rejectRetrieval(feedback.value);
    return decideStage(stage, 'reject', feedback.value);
  }, 'btn quiet'));
  revision.append(el('p', '只重做当前步骤，后续结果重新等待确认。', 'step-state'));
  wrap.append(revision, actions);
  parent.append(wrap);
  return feedback;
}

function renderAcceptedStages(parent, current) {
  const list = el('div');
  ANALYSIS_STAGE_KEYS.filter(stage => stage !== current && stageState(stage) === 'accepted').forEach(stage => {
    const details = el('details');
    details.append(el('summary', '✓ ' + STAGE_LABELS[stage] + '：已确认（展开回看结果）'));
    if (stage === 'retrieval') {
      sourceCard(details);
      details.append(el('p', task.selection.reason, 'muted'));
    } else if (stage === 'language') {
      details.append(el('p', task.analysis.summary, 'muted'));
      details.append(el('p', '借鉴方式：' + task.analysis.borrow.join('；')));
    } else if (stage === 'visual') {
      details.append(el('p', '分析依据：' + task.analysis_basis, 'muted'));
      details.append(el('p', task.analysis.original_pages.map(page => '第' + page.number + '页：' + page.observation).join('\n')));
    } else if (stage === 'facts') {
      sourceEvidence(details);
      details.append(el('p', task.analysis.missing_information.length ? '待核实：' + task.analysis.missing_information.join('；') : '未标出额外待核实项，但仍需人工复核。', 'muted'));
    } else if (stage === 'writing') {
      details.append(el('p', task.analysis.outline.map((item, index) => '第' + (index + 1) + '页：' + item.purpose).join('\n')));
    }
    list.append(details);
  });
  parent.append(list);
}

function renderLanguageStage(parent) {
  const analysis = task.analysis;
  parent.append(el('h3', 'AI 的语言分析结果'));
  parent.append(el('p', analysis.summary, 'muted'));
  const list = el('div', undefined, 'case-pages');
  analysis.original_pages.forEach(page => {
    const card = el('article', undefined, 'case-page');
    card.append(el('h3', '原帖第 ' + page.number + ' 页 · ' + page.form), el('p', page.observation), el('p', '可借鉴的组织方式：' + page.borrow), el('blockquote', page.ocr_quote || '无可引用 OCR 片段'));
    list.append(card);
  });
  parent.append(list);
}

async function renderVisualStage(parent, showReference = true) {
  const analysis = task.analysis;
  parent.append(el('h3', 'AI 的视觉分析结果'));
  parent.append(el('p', '分析依据：' + task.analysis_basis, 'muted'));
  const visualReady = task.analysis_basis === '原图+OCR+正文';
  parent.append(el('p', visualReady ? 'AI 已读取参考原图，下面先看画面与结构，再看本次创作建议。' : '上次看图调用未完成。点击下方按钮，将原图交给当前配置的视觉模型重新分析。', visualReady ? 'muted' : 'review'));
  if (stageState('language') === 'accepted' && !task.confirmed_analysis) {
    parent.append(button('用原图重新分析', () => decideStage('visual', 'reject', '直接观察全部参考原图，识别画面内容、文字层级、图表结构、配色和信息密度；逐页给出借鉴方法，并结合我的创作需求提出下一步逐页创作建议。保留已确认的检索与语言分析。'), 'btn quiet'));
    parent.append(el('p', '重新分析会更新本步及后续创作建议，已确认的前两步保留。', 'step-state'));
  }
  const list = el('div', undefined, 'case-pages');
  analysis.original_pages.forEach(page => {
    const card = el('article', undefined, 'case-page');
    card.append(el('h3', '原帖第 ' + page.number + ' 页'), el('p', page.observation));
    if (page.borrow) card.append(el('p', '本次可借鉴：' + page.borrow, 'muted'));
    if (page.uncertainty) card.append(el('p', '不确定：' + page.uncertainty, 'review'));
    list.append(card);
  });
  parent.append(list);
  const suggestions = el('details');
  suggestions.open = true;
  suggestions.append(el('summary', '下一步怎么创作 · ' + analysis.outline.length + ' 页建议'));
  const outline = el('ol');
  analysis.outline.forEach(item => outline.append(el('li', item.purpose + '：' + item.instruction)));
  suggestions.append(outline);
  parent.append(suggestions);
  if (showReference) await referencePages(parent, '查看 AI 对照的参考原图、OCR 与正文');
}

function renderFactsStage(parent) {
  parent.append(el('h3', '本次实际使用的资料'));
  sourceEvidence(parent);
  const trace = [...(task.traces || [])].reverse().find(item => item.sources);
  (trace?.sources || []).forEach(source => {
    if (['GUIDE','INTENT'].includes(source.id)) return;
    const details = el('details');
    const kbHint = source.id === 'KB' ? '（按本任务问题语义检索，展开逐条核对）' : '';
    const label = { SHOP:'你补充的资料', CASE:'参考原帖', K1:'项目背景资料', KB:'相关知识资料' }[source.id] || '参考资料';
    details.append(el('summary', label + kbHint));
    if (Array.isArray(source.content)) {
      const list = el('ul', undefined, 'kb-hits');
      source.content.forEach(item => list.append(el('li', item)));
      details.append(list);
    } else {
      const content = typeof source.content === 'string' ? source.content : JSON.stringify(source.content, null, 2);
      details.append(el('pre', content.slice(0, 3000), 'scroll-pre'));
    }
    parent.append(details);
  });
  if (task.analysis.missing_information.length) parent.append(el('p', 'AI 标出的缺少信息：' + task.analysis.missing_information.join('；'), 'review'));
  else parent.append(el('p', 'AI 没有标出缺少信息；仍需你核对门店事实和合规边界。', 'muted'));
}

function renderWritingStage(parent) {
  const analysis = task.analysis;
  parent.append(el('h3', 'AI 的写作规则与逐页大纲'));
  const plan = task.editorial_plan;
  if (plan) {
    parent.append(el('p', '写给：' + plan.audience_brief.reader), el('p', '本篇方向：' + plan.direction),
      el('p', '读完能明白：' + plan.reading_goal));
    const reasoning = el('details');
    reasoning.append(el('summary', '查看读者问题与参考借鉴方式'));
    const questions = el('ul');
    plan.audience_brief.questions.forEach(q => questions.append(el('li', q)));
    reasoning.append(questions, el('p', task.editorial_outline?.adaptation || plan.reference_use));
    if (task.editorial_outline) reasoning.append(el('p', '分页依据：' + task.editorial_outline.pagination_reason));
    parent.append(reasoning);
  }
  parent.append(el('p', '这一阶段只决定组织方式，不会把参考帖医学结论直接复制到成品。', 'muted'));
  if (Array.isArray(task.analysis_polish) && task.analysis_polish.length) {
    const polish = el('div', undefined, 'anchor-warning');
    polish.append(el('b', 'AI 产出后程序自动修整了以下内容（详见运行日志）：'));
    const ul = el('ul');
    task.analysis_polish.forEach(note => ul.append(el('li', note)));
    polish.append(ul);
    parent.append(polish);
  }
  const pageCount = task.case?.pages?.length || 0;
  if (pageCount && Math.abs(analysis.outline.length - pageCount) > 1) {
    parent.append(el('p', '注意：原帖共 ' + pageCount + ' 页，本大纲安排了 ' + analysis.outline.length
      + ' 页，超出原帖页数±1的常规范围。可在下方增删页面，或退回让 AI 按原帖页数重做。', 'review anchor-warning'));
  }
  const choices = el('div', undefined, 'choices');
  [['文字图片+少量标题+话题', '纯文字卡路线，适合暂时没有实拍素材'], ['实拍+文字介绍', '保留门店真实画面，逐页上传自己的照片'], ['混合图文', '文字封面与实拍页组合，按页确认']].forEach(([value, hint]) => {
    const choice = el('button', undefined, 'choice' + (chosenStrategy === value ? ' selected' : ''));
    choice.type = 'button';
    choice.append(el('strong', value), el('span', hint));
    choice.addEventListener('click', () => {
      chosenStrategy = value;
      strategyChosen = true;
      if (task) sessionStorage.setItem('studio_strategy_' + task.id, value);
      choices.querySelectorAll('.choice').forEach(item => item.classList.remove('selected'));
      choice.classList.add('selected');
      showToast('已选择：' + value + '；你仍可逐页修改');
    });
    choices.append(choice);
  });
  parent.append(choices);
  const outlineWrap = el('div');
  const edits = [];
  const renumberOutline = () => {
    let n = 0;
    outlineWrap.querySelectorAll('article.outline-page').forEach(node => {
      if (!node.hidden) node.querySelector('h3').textContent = '新内容第 ' + (++n) + ' 页';
    });
  };
  const outlineEditor = item => {
    const box = el('article', undefined, 'outline-page');
    box.append(el('h3', '新内容第 ' + (edits.length + 1) + ' 页'));
    const kind = kindOptions(item.kind);
    const kindLabel = el('label', '页面类型');
    kindLabel.append(kind);
    box.append(kindLabel);
    const purpose = field(box, '本页要讲什么', item.purpose);
    if (item.reader_question) box.append(el('p', '这一页回答：' + item.reader_question, 'muted'));
    if (item.key_points?.length) box.append(el('p', '介绍要点：' + item.key_points.join('；'), 'muted'));
    const instruction = field(box, '制作或拍摄说明', item.instruction);
    box.append(el('div', '借鉴原帖第 ' + item.source_pages.join('、') + ' 页', 'inline-meta'));
    const edit = { item, kind, purpose, instruction, removed: false };
    edits.push(edit);
    const remove = el('button', '移除这一页', 'btn danger');
    remove.addEventListener('click', () => {
      if (edits.filter(e => !e.removed).length <= 1) {
        showToast('至少保留一页');
        return;
      }
      edit.removed = true;
      box.hidden = true;
      renumberOutline();
    });
    box.append(remove);
    return box;
  };
  (writingDrafts.get(task.id)?.outline || analysis.outline).forEach(item => outlineWrap.append(outlineEditor(item)));
  const addPage = el('button', '添加一页（默认文字卡）', 'btn quiet');
  addPage.type = 'button';
  addPage.addEventListener('click', () => {
    outlineWrap.append(outlineEditor({ kind: 'text', purpose: '', instruction: '', visual_spec: '', source_pages: [1] }));
    renumberOutline();
  });
  parent.append(outlineWrap, addPage);
  if (analysis.missing_information.length) parent.append(el('p', '需要补充或回避：' + analysis.missing_information.join('；'), 'review'));
  const confirmed = check(parent, '我已对照原图检查拆解，并确认新内容大纲');
  confirmed.checked = writingDrafts.get(task.id)?.confirmed || false;
  const writingTaskId = task.id;
  captureWritingDraft = () => writingDrafts.set(writingTaskId, {
    outline: edits.filter(e => !e.removed).map(e => ({ ...e.item, kind: e.kind.value, purpose: e.purpose.value, instruction: e.instruction.value })),
    confirmed: confirmed.checked
  });
  stageDecisionBox(parent, 'writing', true, () => {
    if (!strategyChosen) throw new Error('请先选择一种创作形式');
    if (!confirmed.checked) throw new Error('请先核对并勾选确认');
    const kept = edits.filter(e => !e.removed);
    if (!kept.length) throw new Error('至少保留一页');
    if (kept.length > 8) throw new Error('最多 8 页，请精简后再确认');
    if (kept.some(e => !e.purpose.value.trim())) throw new Error('每一页都要填写"本页要讲什么"，不需要的页请移除');
    const next = JSON.parse(JSON.stringify(analysis));
    next.outline = kept.map(e => ({ ...e.item, kind: e.kind.value, purpose: e.purpose.value, instruction: e.instruction.value }));
    return decideStage('writing', 'accept', '', next);
  });
}

async function renderStageFlow(parent, focused = false) {
  const current = viewedAnalysisStage();
  if (!current) return;
  if (!focused) renderAcceptedStages(parent, current);
  const box = el('div', undefined, 'stage-panel');
  const index = ANALYSIS_STAGE_KEYS.indexOf(current) + 1;
  box.append(el('h3', '第 ' + index + ' 步 · ' + STAGE_LABELS[current]));
  if (stageState(current) === 'accepted') {
    box.append(el('p', '已确认 · 正在回看，已有进度保持不变。', 'muted'));
    if (current === 'retrieval') {
      sourceCard(box);
      box.append(el('p', task.selection.reason, 'muted'));
    } else if (current === 'language') renderLanguageStage(box);
    else if (current === 'visual') await renderVisualStage(box, !focused);
    else if (current === 'facts') renderFactsStage(box);
    const redo = el('details');
    redo.append(el('summary', '需要修改这一步？'));
    stageDecisionBox(redo, current, false);
    box.append(redo);
    box.append(button('继续下一步', () => visitAnalysisStage(ANALYSIS_STAGE_KEYS[index]), 'btn primary'));
    parent.append(box);
    return;
  }
  const lastFeedback = task.analysis_stages?.[current]?.feedback;
  if (lastFeedback) {
    if (focused) {
      const changes = el('details');
      changes.append(el('summary', '查看本次修改要求'), el('p', lastFeedback, 'muted'));
      box.append(changes);
    } else box.append(el('p', '本次已按你的建议重做：' + lastFeedback, 'review'));
  }
  if (current !== 'retrieval' && !task.analysis) {
    box.append(el('p', '模型尚未完成拆解，当前进度已保存。请手动重试；不会自动循环调用。', 'review'));
    box.append(button('重试模型拆解', () => mutate('/analyze')));
    parent.append(box);
    return;
  }
  if (current === 'retrieval') {
    sourceCard(box);
    box.append(el('p', task.selection.reason, 'muted'));
    const top3 = task.selection.top3 || [];
    if (top3.length) {
      const list = el('ul');
      top3.forEach((item, index) => list.append(el('li',
        (index + 1) + '. 《' + item.title + '》：相关度 ' + item.relevance + '/10 · ' + item.likes + ' 赞 · 综合 ' + item.final + ' 分')));
      box.append(el('p', '评分前三的候选（当前采用第 1 名）：'), list);
      box.append(el('p', '综合分 = 相关度 × 7 + 点赞加成（满分30）；相关度低于 4 分的候选已被排除。完整名单保留在导出包的来源记录里。', 'step-state'));
    } else {
      box.append(el('p', '共 ' + task.selection.eligible_count + ' 篇相关候选。', 'muted'));
    }
    box.append(button('前四步都没问题，直达第 5 步定大纲', async () => {
      await decideStage('retrieval', 'accept', '');
      await decideStage('language', 'accept', '');
      await decideStage('visual', 'accept', '');
      await decideStage('facts', 'accept', '');
    }, 'btn quiet'));
    box.append(el('p', '案例、语言、视觉、资料四步是逐项核对 AI 的拆解依据。都没问题时可一键采用，仍会到第 5 步由你确认大纲。', 'step-state'));
    stageDecisionBox(box, current);
  } else if (current === 'language') {
    renderLanguageStage(box);
    stageDecisionBox(box, current);
  } else if (current === 'visual') {
    await renderVisualStage(box, !focused);
    stageDecisionBox(box, current);
  } else if (current === 'facts') {
    renderFactsStage(box);
    stageDecisionBox(box, current);
  } else if (current === 'writing') {
    renderWritingStage(box);
  }
  parent.append(box);
}
async function mutate(path, extra = {}) {
  task = await request('/tasks/' + task.id + path, 'POST', { revision: task.revision, ...extra });
  sessionStorage.setItem('studio_task', task.id);
  await refreshLists();
  await render();
}

async function generateDraft() {
  task = await request('/tasks/' + task.id + '/draft', 'POST', { revision: task.revision });
  await refreshLists();
  screenId = 'create';
  await render();
}

const analysisReferenceViews = new Map();

async function renderAnalysisDesk(screen) {
  const current = viewedAnalysisStage();
  const heading = el('header', undefined, 'analysis-heading');
  const title = el('div');
  title.append(el('h1', '对照案例，确定这篇怎么写'), el('p', task.intent?.goal || task.request.question, 'muted'));
  heading.append(title, button('查看创作需求', () => editorSheet('本次创作需求与资料', parent => {
    setupPanel(parent);
    parent.querySelector('details').open = true;
    if (task.intent?.must_cover?.length) parent.append(el('p', '本篇重点：' + task.intent.must_cover.join('、')));
    parent.append(el('p', '修改需求后重新检索会新建任务，当前任务保留。', 'muted'));
    parent.append(button('按修改后的需求重新检索', async () => {
      const nextRequest = currentRequest();
      if (!nextRequest.question.trim()) throw new Error('请先写下你想做的内容');
      parent.closest('dialog').close();
      await startHighWorkflow(nextRequest);
    }));
  }), 'btn quiet'));
  const referenceToggle = el('button', '查看参考原图', 'btn quiet analysis-reference-toggle');
  referenceToggle.type = 'button';
  referenceToggle.setAttribute('aria-expanded', 'false');
  referenceToggle.addEventListener('click', () => {
    const opened = desk.classList.toggle('show-reference');
    referenceToggle.setAttribute('aria-expanded', String(opened));
    referenceToggle.textContent = opened ? '返回当前分析' : '查看参考原图';
  });
  heading.append(referenceToggle);
  screen.append(heading);
  const steps = el('div', undefined, 'analysis-steps');
  pipeline(steps, true);
  screen.append(steps);
  const desk = el('div', undefined, 'analysis-workspace');
  const reference = el('aside', undefined, 'analysis-reference');
  reference.setAttribute('aria-label', '参考原帖');
  const refHeader = el('header', undefined, 'analysis-reference-heading');
  refHeader.append(el('h2', '参考原帖'));
  const link = referencePostLink();
  if (link) refHeader.append(link);
  reference.append(refHeader, el('h3', task.case.title || '原帖标题未采集', 'analysis-reference-title'),
    el('p', String(task.case.likes ?? '未知') + ' 赞 · 采集时记录', 'muted'));
  const pages = task.case.pages || [];
  const selected = analysisReferenceViews.get(task.id);
  const initial = Math.max(0, pages.findIndex(page => page.number === selected));
  const pageLabel = el('label', '查看原帖页码', 'analysis-page-picker');
  const picker = el('select');
  pages.forEach((page, i) => {
    const option = el('option', '第 ' + page.number + ' 页 / 共 ' + pages.length + ' 页');
    option.value = String(i); picker.append(option);
  });
  picker.value = String(initial);
  pageLabel.append(picker);
  const imageArea = el('div', undefined, 'analysis-reference-image');
  const raw = el('details', undefined, 'analysis-reference-text');
  raw.append(el('summary', '查看识别文字与原帖正文'));
  const ocr = el('pre'), body = el('p', task.case.body || '未采集到原帖正文。');
  raw.append(ocr, el('h3', '原帖正文'), body);
  reference.append(pageLabel, imageArea, raw);
  const result = el('section', undefined, 'analysis-current');
  await renderStageFlow(result, true);
  const panel = result.querySelector('.stage-panel');
  const resultBody = el('div', undefined, 'analysis-result-body');
  const footer = el('footer', undefined, 'analysis-actions');
  const nav = el('nav', undefined, 'stage-navigation');
  nav.setAttribute('aria-label', '分析步骤导航');
  const index = ANALYSIS_STAGE_KEYS.indexOf(current);
  const back = button('返回上一步', () => visitAnalysisStage(ANALYSIS_STAGE_KEYS[index - 1]), 'btn quiet');
  back.disabled = index === 0;
  nav.append(back, el('span', (index + 1) + ' / 5', 'stage-navigation-label'));
  footer.append(nav);
  const decision = panel.querySelector(':scope > .stage-decision');
  const next = [...panel.children].find(node => node.tagName === 'BUTTON' && node.textContent === '继续下一步');
  if (decision) footer.append(decision);
  if (next) footer.append(next);
  const stageHeading = panel.firstElementChild;
  stageHeading.classList.add('analysis-current-heading');
  [...panel.children].filter(node => node !== stageHeading && node !== decision && node !== next).forEach(node => resultBody.append(node));
  panel.append(resultBody, footer);
  desk.append(reference, result); screen.append(desk);
  async function showPage() {
    const page = pages[Number(picker.value)];
    if (!page) {
      imageArea.replaceChildren(el('p', '此案例没有原图。可查看原帖链接，或重新选择案例。', 'muted'));
      ocr.textContent = '无识别文字'; picker.disabled = true; return;
    }
    analysisReferenceViews.set(task.id, page.number);
    imageArea.replaceChildren();
    ocr.textContent = page.ocr || '本页未识别出文字，可直接对照原图。';
    const image = await imageInto(imageArea, '/tasks/' + task.id + '/reference/' + page.number, '参考原帖第 ' + page.number + ' 页');
    if (image) {
      const zoom = referenceThumbnail(image, page.number);
      imageArea.replaceChildren(zoom);
    }
    if (['language', 'visual'].includes(current)) {
      resultBody.querySelectorAll('.case-pages > .case-page').forEach((card, i) => { card.hidden = i !== Number(picker.value); });
    }
  }
  picker.addEventListener('change', async () => {
    if (busy) {
      picker.value = String(Math.max(0, pages.findIndex(page => page.number === analysisReferenceViews.get(task.id))));
      return;
    }
    picker.disabled = true;
    try { await run(showPage, '切换参考页'); }
    finally { picker.disabled = pages.length === 0; }
  });
  await showPage();
}

function renderExpressionFlow(screen) {
  const expression=task.expression, accepted=expression?.status==='accepted';
  const heading=el('header',undefined,'section-title');
  const title=el('div');title.append(el('h1',accepted?'资料与大纲':'同类分析 · 表达方案'),
    el('p',accepted?'资料补知识，沿用已确认的目的、叙述方式和语气。':'先确定怎么讲，再查这篇需要的知识。'));
  heading.append(title,button('返回选题',()=>{go('topics');render();},'btn quiet'));screen.append(heading);
  const flow=el('ol',undefined,'expression-progress');flow.setAttribute('aria-label','创作进度');
  for(const [i,label] of ['确认表达方案','资料与大纲','草稿与成图'].entries()) {
    const item=el('li',label);if((!accepted&&i===0)||(accepted&&!task.draft&&i===1)||(task.draft&&i===2))item.setAttribute('aria-current','step');flow.append(item);
  }
  screen.append(flow);
  if(task.draft) {
    const done=el('section',undefined,'panel expression-panel');
    done.append(el('h2','草稿与表达方案已保存'),el('p',expression.objective));
    done.append(button('返回逐页共创',()=>{go('create');render();}));
    done.append(button('重新起草',async()=>{
      if(window.confirm('重新起草将替换本任务草稿和成图，继续吗？'))await generateDraft();
    },'btn quiet'));screen.append(done);return;
  }
  const panel=el('section',undefined,'panel expression-panel');
  if(!expression) {
    panel.append(el('h2','从参考帖提炼表达'),el('p','将合并分析开头、结构、语气与展示方式，形成一份可查看、可修改的写作提示词。'));
    panel.append(button('分析参考表达',()=>mutate('/expression-study')));screen.append(panel);return;
  }
  const e=expression.plan;
  const summary=el(accepted?'details':'div',undefined,'expression-summary');
  if(accepted)summary.append(el('summary','查看已确认的表达方案'));
  summary.append(el('p','所选语气：'+(task.writing_style?.title || task.writing_style?.id || '已确认口吻'),'voice-selected'),el('h2','本篇目的'),el('p',expression.objective));
  const brief=el('dl',undefined,'research-brief');
  for(const [label,value] of [['写给谁',e.audience],['开头怎么讲',e.opening],['叙述顺序',e.structure.join(' → ')],['语气',e.tone],['句式',e.sentence_pattern],['怎样展示',e.presentation]])brief.append(el('dt',label),el('dd',value));
  summary.append(brief);
  const evidence=el('details',undefined,'expression-evidence');evidence.append(el('summary','展开参考原文与表达示例'));
  for(const proof of e.evidence) {
    const source=expression.samples.find(x=>x.sample_id===proof.sample_id);
    evidence.append(el('blockquote',proof.quote),el('p',proof.lesson));
    if(source){const link=el('a','参考原帖：'+source.title);link.href=source.url;link.target='_blank';link.rel='noopener noreferrer';evidence.append(link);}
  }
  evidence.append(el('h3','建议写法'),el('p',e.good_example),el('h3','避免的写法'),el('p',e.bad_example),el('p','分析依据：'+expression.basis,'muted'));summary.append(evidence);
  const promptDetails=el('details',undefined,'expression-prompt');promptDetails.append(el('summary',accepted?'查看 / 下载可复用提示词':'查看 / 修改本篇提示词'));
  const prompt=field(promptDetails,'本篇写作提示词',expression.prompt);prompt.rows=12;prompt.readOnly=accepted;prompt.maxLength=8000;
  promptDetails.append(button('下载 SKILL.md',()=>{
    const blob=new Blob([accepted?expression.prompt:prompt.value],{type:'text/markdown;charset=utf-8'}),url=URL.createObjectURL(blob);
    const link=el('a');link.href=url;link.download='SKILL.md';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  },'btn quiet'));summary.append(promptDetails);panel.append(summary);
  if(!accepted) {
    const revise=el('details');revise.append(el('summary','表达不合适？给出修改意见'));
    const feedback=field(revise,'希望怎样调整','');feedback.maxLength=1000;
    revise.append(button('按意见重做同类分析',()=>{
      if(!feedback.value.trim())throw new Error('请先填写修改意见');
      return mutate('/expression-study?feedback='+encodeURIComponent(feedback.value));
    },'btn quiet'));panel.append(revise);
    const actions=el('footer',undefined,'expression-actions');
    actions.append(button('确认表达方案，查资料',async()=>{
      if(prompt.value.trim().length<40)throw new Error('请保留完整的表达要求');
      await mutate('/confirm-expression',{prompt:prompt.value.trim()});
      await mutate('/prepare-content');
    }));panel.append(actions);
  } else if(!task.analysis) {
    panel.append(el('p','表达方案已保存，按知识清单检索本篇资料。'));
    panel.append(button('检索资料并生成大纲',()=>mutate('/prepare-content')));
  } else {
    const materials=el('details',undefined,'expression-materials');materials.append(el('summary','本篇资料单 · '+task.material_sheet.items.length+' 个知识点'));
    for(const item of task.material_sheet.items) {
      materials.append(el('h3',item.need),el('p',item.answer));if(item.scope)materials.append(el('p',item.scope,'muted'));
      for(const support of item.supports) {
        const source=task.material_sources.find(x=>x.id===support.source_id);
        materials.append(el('blockquote',support.quote));
        const url=source?.content?.url;
        if(url){const link=el('a',source.content.title||support.source_id);link.href=url;link.target='_blank';link.rel='noopener noreferrer';materials.append(link);}
      }
    }
    if(task.material_sheet.missing.length)materials.append(el('h3','需要补充或调整的知识点'),el('p',task.material_sheet.missing.join('；')));
    panel.append(materials,el('h2','按原定表达组织大纲'));
    const next=JSON.parse(JSON.stringify(task.analysis));
    for(const [i,page] of next.outline.entries()) {
      const row=el('div',undefined,'expression-outline');row.append(el('h3','第 '+(i+1)+' 页'));
      const purpose=field(row,'本页讲什么',page.purpose,'input');purpose.addEventListener('input',()=>{page.purpose=purpose.value;});
      const detail=el('details');detail.append(el('summary','查看 / 修改本页介绍方式'));
      const instruction=field(detail,'介绍方式',page.instruction);instruction.addEventListener('input',()=>{page.instruction=instruction.value;});row.append(detail);panel.append(row);
    }
    const actions=el('footer',undefined,'expression-actions');
    actions.append(button(task.confirmed_analysis?'按确认方案起草':'确认大纲并起草',async()=>{
      if(next.outline.some(x=>!x.purpose.trim()))throw new Error('请填写每页内容');
      if(!task.confirmed_analysis)await mutate('/confirm-analysis',{analysis:next});
      await generateDraft();
    }));panel.append(actions);
  }
  screen.append(panel);
}

async function renderModes() {
  const screen = $('modes');
  screen.replaceChildren();
  if (task?.request?.workflow === 'expression-first' && task.case) {
    renderExpressionFlow(screen);return;
  }
  if (task?.schema_version === 2 && task.case && !task.draft && !task.confirmed_analysis && mode === 'high') {
    await renderAnalysisDesk(screen);
    return;
  }
  const crumb = el('div', undefined, 'crumb');
  const topicBack = el('button', '主题选择');
  topicBack.addEventListener('click', () => { go('topics'); render(); });
  crumb.append(topicBack, document.createTextNode(' / ' + (task?.request?.project || '创作需求') + ' / 创作方式'));
  const heading = el('div', undefined, 'section-title');
  const headLeft = el('div');
  headLeft.append(el('h1', '你想怎样开始？'), el('p', '先让 Agent 展示案例依据，再由你决定是否进入共创。'));
  const back = el('button', '返回主题', 'back');
  back.addEventListener('click', () => { go('topics'); render(); });
  heading.append(headLeft, back);
  screen.append(crumb, heading);
  setupPanel(screen);
  if (task?.intent) {
    const understood = el('section', undefined, 'panel intent-summary');
    understood.append(el('h3', 'AI 理解的创作方向'),el('p', task.intent.project + ' · ' + task.intent.content_type),el('p', task.intent.goal));
    if (task.intent.must_cover?.length) understood.append(el('p', '重点：' + task.intent.must_cover.join('、')));
    if (task.intent_understanding?.method === 'rules') understood.append(el('p', '本次为规则识别，可修改需求后重新开始。', 'muted'));
    screen.append(understood);
  }
  const tabs = el('div', undefined, 'mode-tabs');
  [['high', '参考表达创作', '先分析表达，确认后再检索知识资料。'], ['idea', '我有想法，AI 来辅助', '你先写想法，AI 把它拆成下一步行动。']].forEach(([value, title, hint]) => {
    const tab = el('button', undefined, 'mode-tab' + (mode === value ? ' active' : ''));
    tab.append(el('strong', title), el('span', hint));
    tab.setAttribute('aria-pressed', String(mode === value));
    tab.addEventListener('click', () => {
      setupDraft = currentRequest();
      mode = value;
      render();
    });
    tabs.append(tab);
  });
  screen.append(tabs);
  if (mode === 'idea') {
    await renderIdeaMode(screen);
    return;
  }
  const layout = el('div', undefined, 'mode-layout');
  const main = el('div', undefined, 'panel');
  const side = el('aside', undefined, 'panel side-card');
  main.append(el('h2', '参考表达创作'), el('p', '先借鉴参考帖的叙述方式和语气，确认后再查资料、写大纲。', 'muted'));
  if (task && task.request?.workflow !== 'expression-first') pipeline(main);
  if (!task) {
    main.append(el('div', '先填写上方主题参数，再点击开始。检索和拆解结果会逐步展示，等待你的确认。', 'future-box'));
    main.append(button('分析同类表达', startHighWorkflow));
  } else if (!task.case) {
    main.append(el('div', '没有相关案例。请修改主题问题或导入相关资料，不套用其他主题。', 'empty-state'));
    main.append(button('按当前参数重新检索', async () => {
      task = null;
      await startHighWorkflow();
    }, 'btn quiet'));
  } else if (task.draft) {
    if (task.case) sourceCard(main);
    main.append(el('div', '草稿已生成，进入逐页共创。', 'future-box'));
    main.append(button('进入共创', async () => { screenId = 'create'; await render(); }));
    main.append(button('重新生成草稿（按已确认大纲重写）', async () => {
      if (!window.confirm('重新生成会替换当前草稿和已制作的页面图片，确定？')) return;
      await generateDraft();
    }, 'btn quiet'));
    main.append(button('再来一条新内容', async () => {
      task = null;
      setupDraft = null;
      sessionStorage.removeItem('studio_task');
      chosenStrategy = '';
      strategyChosen = false;
      go('topics');
      await render();
    }, 'btn quiet'));
  } else if (task.confirmed_analysis) {
    if (task.case) sourceCard(main);
    main.append(el('h3', '拆解已确认'));
    task.confirmed_analysis.outline.forEach((item, index) => main.append(el('p', String(index + 1) + '. ' + (PAGE_KIND_LABELS[item.kind] || item.kind) + '：' + item.purpose)));
    main.append(button('生成逐页草稿，进入共创', generateDraft));
  } else {
    await renderStageFlow(main);
  }
  side.append(el('h3', '当前 Agent 会做什么'));
  const list = el('ul');
  ['借鉴相关帖子的开头、叙述结构和语气', '先由你确认可复用的表达提示词', '按需要讲的知识检索资料并整理资料单', '资料补知识，不改变原定目的和表达', '核对大纲后起草，并检查表达是否走样'].forEach(item => list.append(el('li', item)));
  const capabilities = el('details');
  capabilities.append(el('summary', '来源与能力说明'), el('p', '本篇表达提示词在确认后保存为 SKILL.md 并传入后续环节；资料检索使用本地知识库，缺少依据时列出具体缺口。', 'muted'));
  side.append(list, capabilities);
  layout.append(main, side);
  screen.append(layout);
}

async function renderIdeaMode(screen) {
  const layout = el('div', undefined, 'mode-layout');
  const main = el('div', undefined, 'panel idea-box');
  main.append(el('h2', '我有想法，AI 来辅助'), el('p', '先用自己的话说出来，不要求一开始就写成帖子。', 'muted'));
  const idea = el('textarea');
  idea.id = 'ideaText';
  idea.placeholder = '例如：参考高赞科普，做一篇讲清 M22 仪器区别和滤片知识的图文，不写咨询流程。';
  main.append(idea);
  main.append(button('按这个想法寻找案例并拆解', async () => {
    if (!idea.value.trim()) throw new Error('先写一句你的想法');
    const question = document.getElementById('question');
    if (question) question.value = idea.value.trim();
    mode = 'high';
    task = null;
    await startHighWorkflow();
  }));
  if (task?.request?.question) main.append(el('p', '当前任务问题：' + task.request.question, 'muted'));
  const side = el('aside', undefined, 'panel side-card');
  side.append(el('h3', '你仍然拥有决定权'));
  const list = el('ul');
  ['AI 只把想法变成下一步行动', '每一页都可以修改、删除或换成实拍', '没有门店事实时会标为待核实', '如果没有相关案例，会明确提示，不强行套用'].forEach(item => list.append(el('li', item)));
  side.append(list);
  layout.append(main, side);
  screen.append(layout);
}

async function renderLegacy() {
  const screen = $('modes');
  screen.replaceChildren();
  const heading = el('div', undefined, 'section-title');
  const left = el('div');
  left.append(el('h1', '历史任务（只读）'), el('p', '旧任务保留用于追溯，不会被新案例流程覆盖。'));
  const back = el('button', '返回首页', 'back');
  back.addEventListener('click', () => { task = null; sessionStorage.removeItem('studio_task'); go('home'); render(); });
  heading.append(left, back);
  const panel = el('div', undefined, 'panel');
  panel.append(el('p', '这条任务使用旧版数据结构，不能在当前流程继续编辑。请新建任务使用案例资料包。', 'review'));
  panel.append(el('pre', JSON.stringify({ request: task.request, plan: task.plan, draft: task.draft }, null, 2), 'scroll-pre'));
  screen.append(heading, panel);
}

const PAGE_KIND_LABELS = { text: '文字卡', photo: '实拍页', chat: '对话卡' };

function chatPrefill(page) {
  if (Array.isArray(page.dialog) && page.dialog.length) {
    return page.dialog.map(t => (t.speaker === 'customer' ? '顾客：' : '门店：') + t.text).join('\n');
  }
  return page.text || '';
}

function rendering_dialogLooksValid(text) {
  const lines = (text || '').split('\n').map(l => l.trim()).filter(Boolean);
  const customer = lines.some(l => /^(顾客|顾|客户|买家|对方|客人|Q|问)[:：]/.test(l));
  const shop = lines.some(l => /^(门店|店|我方|我|商家|机构|A|答)[:：]/.test(l));
  return customer && shop;
}

function kindOptions(kind) {
  const select = el('select');
  [['text', '纯文字卡：直接排版'], ['photo', '实拍页：上传自己的照片'], ['chat', '对话卡：微信聊天样式']].forEach(([value, label]) => {
    const option = el('option', label);
    option.value = value;
    select.append(option);
  });
  select.value = kind;
  return select;
}

const creationSteps = new Map();

function editorSheet(title, fill) {
  const trigger = document.activeElement;
  const dialog = el('dialog', undefined, 'editor-sheet');
  dialog.setAttribute('aria-label', title);
  const heading = el('header');
  const close = el('button', '关闭', 'btn quiet');
  close.type = 'button';
  close.addEventListener('click', () => dialog.close());
  heading.append(el('h2', title), close);
  const content = el('div', undefined, 'editor-sheet-content');
  fill(content, dialog);
  dialog.append(heading, content);
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
  dialog.addEventListener('close', () => { dialog.remove(); if (trigger?.isConnected) trigger.focus(); });
  document.body.append(dialog);
  dialog.showModal();
  return dialog;
}

async function openCardModelSettings() {
  const settings = await request('/card-model-settings');
  editorSheet('设置设计与检查模型', (parent, dialog) => {
    parent.append(el('p', '使用你已有的、支持图片输入的 OpenAI 兼容接口。此设置用于成品设计和视觉检查。', 'muted'));
    const base = field(parent, 'API 地址（Base URL）', settings.provider === 'custom' ? settings.base_url : '', 'input');
    base.placeholder = '填写服务商提供的完整 Base URL';
    const model = field(parent, '视觉设计模型名称', settings.provider === 'custom' ? settings.model : '', 'input');
    const review = field(parent, '视觉检查模型（留空则与设计模型相同）', settings.provider === 'custom' ? settings.review_model : '', 'input');
    const key = field(parent, '该平台 API 密钥', '', 'input'); key.type = 'password'; key.autocomplete = 'new-password';
    key.placeholder = settings.provider === 'custom' && settings.key_configured ? '已配置；同一接口留空可保留' : '仅保存在本机配置文件中';
    const message = el('p', '', 'review'); message.setAttribute('role', 'alert'); parent.append(message);
    parent.append(button('保存模型设置', async () => {
      try {
        await request('/card-model-settings', 'POST', { base_url:base.value.trim(), model:model.value.trim(), review_model:review.value.trim(), api_key:key.value.trim() });
        key.value = ''; dialog.close(); showToast('模型设置已保存，点击“重新生成”使用新接口');
      } catch (error) { message.textContent = error.message; throw error; }
    }));
  });
}

function productionParagraphs(text) {
  const notes = [];
  for (const paragraph of text.trim().split(/\n\s*\n/)) {
    const lines = paragraph.split('\n');
    const index = lines.findIndex(line => /^\s*(?:#{1,6}\s*|[-*]\s*)?(?:实拍建议|拍摄建议|拍摄提示|配图建议|排版说明|制作说明)\s*[:：]/.test(line));
    if (index >= 0) notes.push(lines.slice(index).join('\n'));
  }
  return notes;
}

async function renderCreate() {
  const screen = $('create');
  screen.replaceChildren();
  if (!task?.draft || !task.confirmed_analysis) {
    screen.append(el('div', '请先完成案例拆解和草稿生成。', 'empty-state'));
    return;
  }
  const pages = task.draft.pages;
  const index = Math.max(0, Math.min(task.page_index || 0, pages.length - 1));
  const number = index + 1;
  const outline = task.confirmed_analysis.outline[index];
  const page = pages[index];
  if (!outline || !page) {
    screen.append(el('div', '页面数据不完整，请回到创作方式检查大纲。', 'empty-state'));
    return;
  }
  const key = task.id + ':' + number;
  const phases = outline.kind === 'photo' ? [['photo', '照片'], ['copy', '核对文字'], ['preview', '成品预览']] : [['copy', '核对文字'], ['preview', '成品预览']];
  let phase = creationSteps.get(key) || (outline.kind === 'photo' && !task.assets?.[String(number)] ? 'photo' : 'copy');
  if (!phases.some(([value]) => value === phase)) phase = 'copy';
  let dirty = false;
  let photoDirty = false;
  let asset = task.assets?.[String(number)];
  let upload, caption, photoImage, themeSelect;
  let previewImage = null;
  let previewLoaded = false;

  const heading = el('div', undefined, 'editor-heading');
  const headingText = el('div');
  headingText.append(el('h1', '逐页完成这条图文'), el('p', '一次处理一件事，核对后再生成。'));
  const back = button('返回修改形式', async () => { await saveChanges(); go('modes'); await render(); }, 'back');
  const headingActions=el('div',undefined,'editor-heading-actions');
  const sharingVersion=button('选择语气，创建新版本',async()=>{
    await saveChanges();
    toneSource={id:task.id,revision:task.revision,bundle_id:task.request.bundle_id};
    selectedTone=task.writing_style?.id || 'friend-sharing';
    toneData=null;toneError='';go('tones');await render();
  },'btn quiet');
  sharingVersion.title='按独立语气标准创建新版本，保留当前文案和图片';
  headingActions.append(sharingVersion,back);
  heading.append(headingText,headingActions);
  const board = el('div', undefined, 'editor-board');
  const side = el('aside', undefined, 'editor-pages');
  const completed = Object.keys(task.renders || {}).length;
  side.append(el('h2', '图文页'), el('p', '已生成 ' + completed + ' / ' + pages.length + ' 页', 'muted'));
  const pageList = el('div', undefined, 'editor-page-list');
  pages.forEach((item, i) => {
    const itemButton = button('', () => movePage(i), 'editor-page-item');
    itemButton.setAttribute('aria-label', '切换到第 ' + (i + 1) + ' 页');
    itemButton.setAttribute('aria-current', i === index ? 'page' : 'false');
    itemButton.classList.toggle('active', i === index);
    const copy = el('span');
    copy.append(el('strong', item.title || '第 ' + (i + 1) + ' 页'), el('small', (PAGE_KIND_LABELS[task.confirmed_analysis.outline[i]?.kind] || '') + (task.renders?.[String(i + 1)] ? ' · 已生成' : ' · 待确认')));
    itemButton.append(el('span', String(i + 1).padStart(2, '0'), 'editor-page-number'), copy);
    pageList.append(itemButton);
  });
  side.append(pageList);
  const referenceButton = el('button', undefined, 'editor-reference-button');
  referenceButton.type = 'button';
  referenceButton.append(icon('book'), el('span', '本页参考'), icon('chevron'));
  referenceButton.addEventListener('click', () => editorSheet('本页参考', parent => {
    parent.append(el('h3', task.case?.title || '已选案例'));
    const link = referencePostLink();
    if (link) parent.append(link);
    else parent.append(el('p', '此案例暂无原帖链接。', 'muted'));
    parent.append(el('p', '参考原帖第 ' + (outline.source_pages || []).join('、') + ' 页', 'muted'));
    const gallery = el('div', undefined, 'reference-images');
    parent.append(gallery);
    for (const sourcePage of outline.source_pages || []) {
      const holder = el('div'); gallery.append(holder);
      imageInto(holder, '/tasks/' + task.id + '/reference/' + sourcePage, '参考原帖第' + sourcePage + '页').then(image => {
        if (image) holder.replaceChildren(referenceThumbnail(image, sourcePage));
      });
    }
  }));
  side.append(referenceButton);
  const instructionButton = el('button', '查看本页目标与制作说明', 'text-button');
  instructionButton.type = 'button';
  instructionButton.addEventListener('click', () => editorSheet('本页目标与制作说明', parent => {
    parent.append(el('h3', '这一页想表达什么'), el('p', outline.purpose), el('h3', '制作建议'), el('p', outline.instruction));
  }));
  side.append(instructionButton);

  const panel = el('div', undefined, 'editor-panel');
  const top = el('div', undefined, 'editor-panel-heading');
  top.append(el('h2', '第 ' + number + ' / ' + pages.length + ' 页 · ' + (PAGE_KIND_LABELS[outline.kind] || '内容页')));
  const state = el('span', 'AI 草稿，待你核对', 'editor-review-state');
  top.append(state);
  const tabs = el('div', undefined, 'editor-tabs');
  tabs.setAttribute('role', 'tablist');
  tabs.setAttribute('aria-label', '本页制作步骤');
  const panes = new Map();
  const tabButtons = new Map();
  for (const [value, label] of phases) {
    const tab = el('button', label);
    tab.type = 'button'; tab.id = 'editor-tab-' + value;
    tab.setAttribute('role', 'tab'); tab.setAttribute('aria-controls', 'editor-pane-' + value);
    tab.addEventListener('click', () => { if (!busy) activate(value); });
    tab.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const position = phases.findIndex(([item]) => item === value);
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? phases.length - 1 : (position + (event.key === 'ArrowRight' ? 1 : -1) + phases.length) % phases.length;
      activate(phases[next][0]); tabButtons.get(phases[next][0]).focus();
    });
    tabs.append(tab); tabButtons.set(value, tab);
    const pane = el('div', undefined, 'editor-step editor-step-' + value);
    pane.id = 'editor-pane-' + value; pane.setAttribute('role', 'tabpanel'); pane.setAttribute('aria-labelledby', tab.id);
    pane.tabIndex = 0; panes.set(value, pane);
  }
  panel.append(top, tabs, ...panes.values());

  if (outline.kind === 'photo') {
    const photoPane = panes.get('photo');
    const photoView = el('div', undefined, 'editor-photo-view');
    const photoForm = el('div', undefined, 'editor-photo-form');
    if (asset) photoImage = await imageInto(photoView, '/tasks/' + task.id + '/pages/' + number + '/photo', '已保存实拍照片');
    if (!photoImage) photoView.append(el('p', '选择一张照片，在这里检查画面。', 'muted'));
    upload = el('input'); upload.type = 'file'; upload.accept = 'image/jpeg,image/png,image/webp';
    upload.setAttribute('aria-label', '选择本页实拍照片');
    const uploadLabel = el('label', asset ? '更换照片（可选）' : '选择你的实拍照片', 'editor-upload');
    uploadLabel.append(upload); photoForm.append(uploadLabel);
    caption = field(photoForm, '照片里实际有什么？', asset?.caption || '');
    caption.maxLength = 2000;
    caption.addEventListener('input', () => { photoDirty = true; markChanged(); });
    upload.addEventListener('change', () => {
      if (!upload.files[0]) return;
      photoDirty = true; markChanged();
      const url = URL.createObjectURL(upload.files[0]); objectUrls.push(url);
      photoView.replaceChildren(); photoImage = el('img'); photoImage.src = url; photoImage.alt = '待保存的实拍照片'; photoView.append(photoImage);
    });
    photoForm.append(el('p', '核对画面和说明是否一致；避免出现可识别的顾客信息。', 'muted'), instructionButton.cloneNode(true));
    photoForm.lastChild.addEventListener('click', () => instructionButton.click());
    photoPane.append(photoView, photoForm);
  }

  const copyPane = panes.get('copy');
  const copyFields = el('div', undefined, 'editor-copy-fields');
  const pendingKey = 'studio_unsent_page_' + task.id + '_' + number;
  let unsentCopy = null;
  try { unsentCopy = JSON.parse(sessionStorage.getItem(pendingKey) || 'null'); } catch (_) {}
  const candidateCopy = unsentCopy || (task.content_review_candidate?.page === number ? task.content_review_candidate : page);
  if (candidateCopy !== page) dirty = true;
  const pageTitle = field(copyFields, '图片标题', candidateCopy.title, 'input'); pageTitle.maxLength = 60;
  const pageText = field(copyFields, outline.kind === 'chat' ? '对话内容（每行：顾客：… / 门店：…）' : '图片正文', outline.kind === 'chat' ? chatPrefill(candidateCopy) : candidateCopy.text);
  pageText.maxLength = outline.kind === 'chat' ? 2000 : 700;
  const copyMeter = el('div', undefined, 'editor-copy-meter');
  copyFields.append(copyMeter);
  const preferences = task.render_preferences?.[String(number)] || {};
  const generationMode = field(copyFields, '图片生成方式', '', 'select');
  generationMode.setAttribute('aria-label', '图片生成方式');
  for (const [value, label] of [['model', 'AI 视觉排版（推荐）：保留原文字和照片 → 成图检查'], ['seedream', 'Seedream 视觉设计 + 原文排版（中文保真）'], ['template', '固定模板：不调用设计模型']]) {
    const option = el('option', label); option.value = value; generationMode.append(option);
    if (value === 'seedream' && outline.kind === 'photo') option.disabled = true;
  }
  generationMode.value = preferences.mode_version === 2 ? preferences.generation_mode || 'model' : 'model';
  if (outline.kind === 'photo' && generationMode.value === 'seedream') generationMode.value = 'model';
  generationMode.addEventListener('change', () => {
    if (themeSelect) {
      for (const option of themeSelect.options) option.disabled = generationMode.value !== 'template' && ['ai', 'plain'].includes(option.value);
      if (themeSelect.selectedOptions[0]?.disabled) themeSelect.value = 'minimal';
    }
    dirty = true; markChanged();
  });

  if (outline.kind === 'text') {
    themeSelect = field(copyFields, '设计风格偏好', '', 'select');
    for (const [value, label] of [['minimal', '清爽杂志'], ['soft', '奶油卡片'], ['duotone', '撞色重点'], ['ai', '装饰底图（模板专用）'], ['plain', '纯色（模板专用）']]) {
      const option = el('option', label); option.value = value; themeSelect.append(option);
    }
    themeSelect.value = preferences.card_theme || task.renders?.[String(number)]?.theme || 'minimal';
    for (const option of themeSelect.options) option.disabled = generationMode.value !== 'template' && ['ai', 'plain'].includes(option.value);
    if (themeSelect.selectedOptions[0]?.disabled) themeSelect.value = 'minimal';
    themeSelect.addEventListener('change', () => { dirty = true; markChanged(); });
  }
  const checks = el('aside', undefined, 'editor-checks');
  const contentReviewStatus = el('p', task.draft_content_review?.passed ? '内容检查已通过，生成时会核对文字是否改动。' : '生成前会检查受众、内容方向和阅读负担。', 'muted');
  checks.append(contentReviewStatus);
  const contentReviewBox = el('div'); checks.append(contentReviewBox);
  function updateContentReview() {
    contentReviewBox.replaceChildren();
    if (!task.draft_content_review || task.draft_content_review.passed) return;
    contentReviewStatus.textContent = '内容检查需要调整，修改后可再次生成。';
    const issues = el('details'); issues.open = true;
    issues.append(el('summary', '这些文字需要先调整'));
    const list = el('ul');
    const review = task.draft_content_review;
    [...(review.issues || []), ...(review.pages || []).filter(p => p.number === number).flatMap(p => [...p.issues, ...p.suggestions])]
      .forEach(text => list.append(el('li', text)));
    if (!list.childElementCount) list.append(el('li', review.summary));
    issues.append(list); contentReviewBox.append(issues);
  }
  updateContentReview();
  checks.append(el('h3', '先核对这 3 件事'));
  const list = el('ul');
  ['这一页回答了读者想知道的问题', '要点清楚，必要术语已经解释', '名称、数字和事实与引用资料一致'].forEach(text => list.append(el('li', text)));
  checks.append(list);
  const pending = page.pending || [];
  const pendingSummary = el('div', undefined, pending.length ? 'editor-pending has-pending' : 'editor-pending');
  pendingSummary.append(el('strong', pending.length ? '有 ' + pending.length + ' 项待核实' : 'AI 未列出待核实项'), el('p', pending.length ? pending.join('；') : '仍需你核对，不能据此判断内容正确。'));
  checks.append(pendingSummary);
  const evidence = el('button', '查看文字依据', 'btn quiet'); evidence.type = 'button';
  evidence.addEventListener('click', () => editorSheet('本页文字依据', parent => {
    const trace = [...(task.traces || [])].reverse().find(item => item.sources);
    const ids = page.source_ids || [];
    const sources = (trace?.sources || []).filter(source => ids.includes(source.id));
    parent.append(el('p', '资料是核对依据；下列引用没有经过自动逐句事实验证。', 'muted'));
    if (!sources.length) parent.append(el('p', '没有找到本页可展开的资料，请回到已确认的事实资料核对。', 'review'));
    for (const source of sources) {
      const item = el('details'); item.open = sources.length === 1;
      item.append(el('summary', source.type || '引用资料'));
      item.append(el('pre', typeof source.content === 'string' ? source.content : JSON.stringify(source.content, null, 2), 'editor-evidence-text'));
      parent.append(item);
    }
  }));
  checks.append(evidence);
  const noteButton = el('button', '', 'text-button'); noteButton.type = 'button';
  noteButton.addEventListener('click', () => editorSheet('不进入图片的制作提示', parent => {
    productionParagraphs(pageText.value).forEach(text => parent.append(el('p', text)));
    parent.append(el('p', '编辑原文仍保留，生成时会排除上述制作提示。', 'muted'));
  }));
  checks.append(noteButton);
  const resolutionWrap = el('div', undefined, 'editor-resolution');
  const resolution = el('textarea'); resolution.hidden = true;
  resolution.value = task.page_reviews?.[String(number)]?.resolution || '';
  const resolutionButton = el('button', pending.length ? '处理待核实项' : '补充核对依据（可选）', 'text-button');
  resolutionButton.type = 'button';
  resolutionButton.addEventListener('click', () => editorSheet('待核实项与处理说明', (parent, dialog) => {
    if (pending.length) {
      parent.append(el('h3', '需要核实的内容'));
      pending.forEach(item => parent.append(el('p', item)));
    }
    const input = field(parent, '补充依据，或说明删除了哪些表述', resolution.value);
    input.addEventListener('input', () => {
      resolution.value = input.value; dirty = true; markChanged();
      resolutionButton.textContent = input.value.trim() ? '查看 / 修改处理说明' : pending.length ? '处理待核实项' : '补充核对依据（可选）';
    });
    const done = el('button', '完成，返回核对', 'btn primary'); done.type = 'button';
    done.addEventListener('click', () => dialog.close()); parent.append(done);
  }));
  resolutionWrap.append(resolutionButton, resolution); checks.append(resolutionWrap);
  const confirmation = el('div', undefined, 'editor-footer-confirmation');
  const confirmed = check(confirmation, '我已核对以上内容，未核实项已处理');
  confirmed.addEventListener('change', () => { state.textContent = confirmed.checked ? '已由你勾选核对' : 'AI 草稿，待你核对'; });
  copyPane.append(copyFields, checks);

  const previewPane = panes.get('preview');
  const previewStage = el('div', undefined, 'editor-preview-stage');
  const previewInfo = el('div', undefined, 'editor-preview-info');
  const previewMessage = el('p', '', 'muted');
  previewInfo.append(el('h3', '检查最终阅读效果'), previewMessage);
  const regenerate = button('重新生成', async () => {
    if (dirty || photoDirty) { activate('copy'); throw new Error('有改动，请核对文字并勾选确认后再生成'); }
    await generatePage(true);
  }, 'btn primary editor-regenerate');
  regenerate.setAttribute('aria-label', '重新生成本页图片');
  previewInfo.append(regenerate);
  const pipelineInfo = el('div', undefined, 'editor-pipeline-info'); previewInfo.append(pipelineInfo);
  const modelSettings = button('设置设计模型', openCardModelSettings, 'text-button');
  previewInfo.append(modelSettings);
  const enlarge = el('button', '放大看图', 'btn quiet'); enlarge.type = 'button'; enlarge.hidden = true;
  enlarge.addEventListener('click', () => editorSheet('本页成品大图', parent => { if (previewImage) parent.append(previewImage.cloneNode(true)); }));
  previewInfo.append(enlarge);
  const editAgain = el('button', '返回修改文字', 'text-button'); editAgain.type = 'button'; editAgain.addEventListener('click', () => activate('copy')); previewInfo.append(editAgain);
  previewPane.append(previewStage, previewInfo);

  const footer = el('footer', undefined, 'editor-footer');
  const navigation = el('div', undefined, 'editor-footer-nav');
  const previous = button('上一页', () => movePage(index - 1), 'btn quiet'); previous.disabled = index === 0;
  const next = button('下一页', () => movePage(index + 1), 'btn quiet'); next.disabled = index === pages.length - 1;
  navigation.append(previous, el('span', number + ' / ' + pages.length), next);
  const footerActions = el('div', undefined, 'editor-footer-actions');
  const save = button('保存草稿', async () => { await saveChanges(); await refreshLists(); await render(); showToast('本页改动已保存'); }, 'btn quiet');
  const primary = button('', async () => {
    if (phase === 'photo') { await savePhoto(); activate('copy'); }
    else if (phase === 'copy') await generatePage();
    else if (Object.keys(task.renders || {}).length === pages.length) await reviewPost();
    else if (index < pages.length - 1) await movePage(index + 1);
    else activate('copy');
  });
  footerActions.append(save, primary); footer.append(navigation, confirmation, footerActions);
  board.append(side, panel); screen.append(heading, board, footer);

  function markChanged() {
    confirmed.checked = false; state.textContent = '有未保存改动，请重新核对';
    contentReviewStatus.textContent = '文字已修改，生成前会重新检查内容。';
    if (phase === 'preview') updatePreview();
  }
  function updateCopy() {
    const notes = outline.kind === 'chat' ? [] : productionParagraphs(pageText.value);
    copyMeter.textContent = pageText.value.length + ' / ' + pageText.maxLength + ' 字';
    noteButton.hidden = notes.length === 0;
    noteButton.textContent = '查看 ' + notes.length + ' 段制作提示（不入图）';
  }
  pageTitle.addEventListener('input', () => { dirty = true; markChanged(); });
  pageText.addEventListener('input', () => { dirty = true; markChanged(); updateCopy(); });
  function activate(value) {
    phase = value; creationSteps.set(key, value);
    for (const [item, pane] of panes) {
      pane.hidden = item !== value;
      const tab = tabButtons.get(item); tab.setAttribute('aria-selected', String(item === value)); tab.tabIndex = item === value ? 0 : -1;
    }
    primary.textContent = value === 'photo' ? '保存照片，核对文字' : value === 'copy' ? '确认并生成本页图片' : Object.keys(task.renders || {}).length === pages.length ? '核对整篇，准备导出' : index < pages.length - 1 ? '继续下一页' : '继续核对本页';
    save.hidden = value === 'preview';
    confirmation.hidden = value !== 'copy';
    state.textContent = dirty || photoDirty ? '有改动，请重新核对' : value === 'preview' && task.renders?.[String(number)] ? '图片已生成，请检查效果' : confirmed.checked ? '已由你勾选核对' : 'AI 草稿，待你核对';
    if (value === 'preview') updatePreview();
  }
  async function updatePreview() {
    if (dirty || photoDirty) {
      previewStage.hidden = true; enlarge.hidden = true;
      previewMessage.textContent = '文字或照片有改动。请返回核对并重新生成，以免把旧图当作新成品。'; return;
    }
    previewStage.hidden = false;
    const result = task.renders?.[String(number)];
    regenerate.hidden = !result;
    pipelineInfo.replaceChildren();
    const latestAttempt = (task.generation_attempts || []).filter(item => item.page === number).at(-1);
    if (latestAttempt?.status === 'failed') {
      const textFailure = latestAttempt.mode === 'seedream' && latestAttempt.message?.startsWith('成图检查未通过');
      pipelineInfo.append(el('p', textFailure ? 'Seedream 成图检查未通过，原文和旧图已保留。可继续用 Seedream 重试，或在“核对文字”中手动更换生成方式。' : '上次生成未完成，原图已保留。可展开查看原因。', 'review'));
      pipelineInfo.append(button('查看检查详情', () => editorSheet('本次检查详情', parent => {
        parent.append(el('p', latestAttempt.message));
      }), 'text-button'));
    }
    if (!result) { previewStage.replaceChildren(el('p', '本页尚未生成图片', 'empty-state')); previewMessage.textContent = '先核对文字，再点击底部生成按钮。'; return; }
    if (['skill_model_html', 'skill_seedream_image'].includes(result.method)) {
      previewMessage.textContent = latestAttempt?.status === 'failed' ? '当前显示上次成功成品，本次未通过检查的图片没有替换进来。' : 'AI 已设计本页，视觉模型已检查版式。内容真实性仍需人工核对。';
      const steps = el('p', result.method === 'skill_seedream_image' ? (result.text_rendering === 'browser_exact_slots' ? 'Seedream 视觉素材 → AI 版式设计 → 原文排字 → 成图检查通过' : '小红书 Skill → Seedream 整图生成 → 视觉文字检查通过') : 'Skill 规范 → 模型设计 → 浏览器成图 → 视觉检查通过', 'editor-pipeline-summary');
      if (latestAttempt?.status === 'failed') {
        state.textContent = '本次未完成，显示旧图';
        steps.prepend(document.createTextNode('上次成功：'));
      }
      pipelineInfo.append(steps);
      const detail = el('button', '查看设计与检查结果', 'text-button'); detail.type = 'button';
      detail.addEventListener('click', () => editorSheet('本页设计与检查结果', parent => {
        parent.append(el('p', 'Skill：' + (result.skill?.name || result.skill || '未记录')),
          el('p', '设计模型：' + result.design_model), el('p', '检查模型：' + result.review_model),
          el('h3', '设计说明'), el('p', result.design_direction), el('h3', '版式检查'),
          el('p', result.visual_review?.summary || '未记录'));
        if (result.image_model) parent.append(el('p', '视觉素材模型：' + result.image_model), el('p', '文字处理：按已确认原文排字，未交给绘图模型重绘。'));
        for (const issue of result.visual_review?.issues || []) parent.append(el('p', issue, 'review'));
        parent.append(el('p', '检查针对可读性、遮挡和溢出，不是医学事实认证。', 'muted'));
      }));
      pipelineInfo.append(detail);
    } else {
      previewMessage.textContent = generationMode.value !== 'template' ? '当前是旧版模板成品。点击“重新生成”，将使用所选 AI 方式重新设计和检查。' : '当前为固定模板模式，没有调用模型设计或视觉检查。';
    }
    if (!previewLoaded) {
      previewLoaded = true; previewStage.replaceChildren();
      previewImage = await imageInto(previewStage, '/tasks/' + task.id + '/pages/' + number + '/render', '本页成品预览');
      if (!previewImage) previewLoaded = false;
    }
    enlarge.hidden = !previewImage;
  }
  const editBody = extra => ({ revision: task.revision, title: pageTitle.value, text: pageText.value, resolution: resolution.value, generation_mode: generationMode.value, ...(themeSelect ? { card_theme: themeSelect.value } : {}), ...extra });
  async function savePhoto() {
    if (outline.kind !== 'photo') return;
    if (!asset && !upload.files[0]) throw new Error('请选择本页实拍照片');
    if (photoDirty || !asset) {
      const body = new FormData();
      if (upload.files[0]) body.append('photo', upload.files[0]);
      body.append('caption', caption.value); body.append('revision', task.revision);
      task = await request('/tasks/' + task.id + '/pages/' + number + '/photo', 'POST', body);
      asset = task.assets[String(number)]; photoDirty = false;
      upload.value = ''; previewLoaded = false;
    }
  }
  async function saveChanges() {
    if (photoDirty) await savePhoto();
    if (dirty) {
      task = await request('/tasks/' + task.id + '/pages/' + number, 'POST', editBody({ confirmed: false }));
      sessionStorage.removeItem(pendingKey);
      dirty = false; previewLoaded = false;
    }
  }
  async function movePage(target) {
    if (target < 0 || target >= pages.length || target === index) return;
    await saveChanges();
    await mutate('/progress', { page_index: target });
  }
  async function generatePage(regenerate = false) {
    if (!confirmed.checked && !(regenerate && !dirty && !photoDirty && task.page_reviews?.[String(number)]?.confirmed)) { activate('copy'); throw new Error('请先勾选“我已核对以上内容”'); }
    if (outline.kind === 'chat' && !rendering_dialogLooksValid(pageText.value)) throw new Error('对话需包含顾客和门店，每行一条');
    try { sessionStorage.setItem(pendingKey, JSON.stringify({ title: pageTitle.value, text: pageText.value })); } catch (_) {}
    if (generationMode.value !== 'template') {
      const settings = await request('/card-model-settings');
      if (settings.pipeline !== 'skill_model_html') throw new Error('后端尚未更新AI设计流程，请重新双击 start_studio.bat。');
      if (outline.kind === 'photo' && !settings.original_photo_layout) throw new Error('当前仍在运行修复前的旧服务。请关闭旧的启动窗口，再双击 E:\\aiPM\\yimei-agent\\start_studio.bat，按 Ctrl+F5 刷新后再生成。');
      if (!settings.ready) throw new Error('请先点击成品预览右侧的“设置设计模型”，填写可用的视觉模型接口。');
      if (generationMode.value === 'seedream' && !settings.seedream_ready) throw new Error('Seedream 尚未就绪，请确认本地 .env 中的 ARK_API_KEY 已保存，并重新双击 start_studio.bat。');
    }
    if (outline.kind === 'photo') await savePhoto();
    setStatus('先核对当前文字的内容检查结果，通过后再设计成图，请稍候…');
    try {
      task = await request('/tasks/' + task.id + '/pages/' + number, 'POST', editBody({ confirmed: true, regenerate_background: regenerate, regenerate_design: regenerate }));
    } catch (error) {
      if (error.connectionLost) {
        try { sessionStorage.setItem(pendingKey, JSON.stringify({ title: pageTitle.value, text: pageText.value })); } catch (_) {}
      }
      // Recover the failure revision without rebuilding the form or losing edits.
      try { task = await request('/tasks/' + task.id); } catch (_) {}
      updateContentReview();
      if (task.content_review_candidate?.page === number) {
        confirmed.checked = false; state.textContent = '内容检查需修改'; activate('copy');
      }
      if (phase === 'preview') await updatePreview();
      throw error;
    }

    dirty = false; photoDirty = false; creationSteps.set(key, 'preview');
    sessionStorage.removeItem(pendingKey);
    await refreshLists(); await render(); showToast('本页图片已生成，检查成品后可继续下一页');
  }
  async function reviewPost() {
    await saveChanges();
    if (Object.keys(task.renders || {}).length !== pages.length) throw new Error('本页改动后需要重新生成图片，再核对整篇');
    editorSheet('核对整篇，准备导出', (parent, dialog) => {
      parent.append(el('p', '逐页图片已生成。最后核对帖子标题与正文。', 'muted'));
      const postTitle = field(parent, '帖子标题', task.draft.title, 'input');
      const postBody = field(parent, '帖子正文', task.draft.body);
      if (task.draft.missing_information?.length) parent.append(el('p', '待核实：' + task.draft.missing_information.join('；'), 'review'));
      const postResolution = field(parent, '待核实信息的处理说明', '');
      const postConfirmed = check(parent, '我已审核正文与图片，未核实内容没有混入成品');
      const message = el('p', '', 'review'); message.setAttribute('role', 'alert'); parent.append(message);
      parent.append(button('确认成品，进入导出', async () => {
        try {
          if (!postConfirmed.checked) throw new Error('请先勾选整篇审核确认');
          task = await request('/tasks/' + task.id + '/copy', 'POST', { revision: task.revision, title: postTitle.value, body: postBody.value, confirmed: true, resolution: postResolution.value });
          dialog.close(); screenId = 'publish'; await refreshLists(); await render();
        } catch (error) { message.textContent = error.message; throw error; }
      }));
    });
  }
  updateCopy(); activate(phase);
}

async function renderExport() {
  const screen = $('publish');
  screen.replaceChildren();
  const crumb = el('div', undefined, 'crumb');
  const back = el('button', '共同创作');
  back.addEventListener('click', () => { go('create'); render(); });
  crumb.append(back, document.createTextNode(' / 导出与反馈'));
  const heading = el('div', undefined, 'section-title');
  const left = el('div');
  left.append(el('h1', '成品已确认，导出并记录反馈'), el('p', '发布账号授权暂未接入；你可以下载有序图文包，再由本人登录小红书发布。'));
  const backButton = el('button', '返回共创', 'back');
  backButton.addEventListener('click', () => { go('create'); render(); });
  heading.append(left, backButton);
  const grid = el('div', undefined, 'publish-grid');
  const main = el('div', undefined, 'panel');
  main.append(el('h2', task.draft.title), el('p', task.draft.body, 'draft-body'));
  const thumbs = el('div', undefined, 'thumb-row');
  for (const page of task.draft.pages) await imageInto(thumbs, '/tasks/' + task.id + '/pages/' + page.number + '/render', '成品第' + page.number + '页');
  main.append(thumbs);
  main.append(button('下载完整图文包 ZIP', async () => {
    const blob = await request('/tasks/' + task.id + '/export', 'GET', null, true);
    const url = URL.createObjectURL(blob);
    objectUrls.push(url);
    const link = el('a');
    link.href = url;
    link.download = '图文成品_' + task.id + '.zip';
    link.click();
    showToast('已开始下载图文包');
  }));
  main.append(button('再来一条新内容', async () => {
    task = null;
    sessionStorage.removeItem('studio_task');
    chosenStrategy = '';
    strategyChosen = false;
    go('topics');
    await render();
  }, 'btn quiet'));
  const future = el('div', undefined, 'future-box');
  future.append(el('b', '小红书发布（后续接入）'), el('p', '当前 Agent 没有官方授权或发布接口，不能在这里模拟登录或声称已发布。'));
  main.append(future);
  const side = el('aside', undefined, 'panel side-card');
  side.append(el('h3', '发布后遇到问题？'), el('p', '点击右上角“反馈”，粘贴小红书返回的限流、违规或审核文案。'));
  const insight = el('div', undefined, 'insight');
  insight.append(el('b', '反馈会记录：'), el('br'), el('span', '平台原文、对应帖子、AI 分析假设和下一步人工处理建议。'));
  side.append(insight);
  if (task.feedback?.length) {
    side.append(el('h3', '已有反馈分析'));
    task.feedback.forEach(item => side.append(el('pre', JSON.stringify(item.analysis, null, 2))));
  }
  grid.append(main, side);
  screen.append(crumb, heading, grid);
  const trace = el('details');
  trace.append(el('summary', '资料依据与调用记录'), el('pre', JSON.stringify({
    bundle_id: task.request.bundle_id,
    selection: task.selection,
    analysis_stages: task.analysis_stages,
    analysis_decisions: task.analysis_decisions,
    traces: task.traces,
    failures: task.failures,
    generation_sources: task.generation_sources
  }, null, 2), 'scroll-pre'));
  screen.append(trace);
}

async function renderCatalog(parent) {
  const details=el('details',undefined,'catalog-browser');
  details.append(el('summary','浏览分类案例'));
  parent.append(details);
  const data=await request('/catalog');
  if(data.model_classified<data.total)details.append(button('补全 AI 分类',async()=>{
    for(const bundle of bundles) {
      let last=-1;
      for(let batch=0;batch<Math.ceil(bundle.count/10);batch++) {
        const result=await request('/catalog/classify','POST',{bundle_id:bundle.bundle_id});
        setStatus('正在整理案例：'+result.model_classified+' / '+result.total);
        if(result.model_classified===result.total)break;
        if(result.model_classified===last||result.errors)throw new Error('部分案例分类未完成，已保存结果，可稍后继续。');
        last=result.model_classified;
      }
    }
    await render();showToast('案例分类已更新');
  },'btn quiet'));
  const filters=el('div',undefined,'catalog-filters');
  const project=field(filters,'项目','','select');
  const type=field(filters,'内容类型','','select');
  const search=field(filters,'搜索话题或标题','','input');
  search.placeholder='例如：M22 原理、仪器区别、滤片';
  for(const [select,values,label] of [[project,data.projects,'全部项目'],[type,data.content_types,'全部类型']]) {
    const all=el('option',label);all.value='';select.append(all);
    for(const [name,count] of Object.entries(values)) {const option=el('option',name+' · '+count);option.value=name;select.append(option);}
  }
  const count=el('p','','muted');
  const list=el('div',undefined,'catalog-results');
  const draw=()=>{
    const query=search.value.trim().toLowerCase();
    const items=data.items.filter(item=>(!project.value||item.project===project.value)&&(!type.value||item.content_type===type.value)&&(!query||[item.title,item.summary,...item.topics].join(' ').toLowerCase().includes(query)));
    count.textContent='找到 '+items.length+' / '+data.total+' 篇 · '+data.model_classified+' 篇已由模型分类';
    list.replaceChildren();
    for(const item of items) {
      const card=el('article',undefined,'catalog-case');
      const link=el('a',item.title||'原帖未填写标题');link.href=item.url;link.target='_blank';link.rel='noopener noreferrer';
      card.append(el('p',item.project+' · '+item.content_type+' · '+(item.likes??'未知')+' 赞','muted'),link,el('p',item.summary),el('p',item.topics.join(' · '),'muted'));
      card.append(button('按这个方向创作',async()=>{
        setupDraft={project:item.project,audience:'对'+item.project+'感兴趣的读者',question:'做一篇'+item.project+'的'+item.content_type+'图文，重点讲清'+item.topics.join('、')+'。参考《'+item.title+'》的主题和信息结构。',facts:'',bundle_id:item.bundle_id};
        task=null;mode='high';go('modes');await render();
      },'btn quiet'));
      list.append(card);
    }
    if(!items.length)list.append(el('p','没有符合条件的案例，可换个话题或导入资料。'));
  };
  for(const input of [project,type,search])input.addEventListener('input',draw);
  details.append(filters,count,list);draw();
}

async function renderHome() {
  const screen = $('home');
  screen.replaceChildren();
  const heading = el('div', undefined, 'home-heading');
  const headingText = el('div');
  headingText.append(el('h1', activeNav === 'tasksNav' ? '我的创作' : activeNav === 'libraryBtn' ? '案例资料' : '这次，想分享什么？'),
    el('p', '写下你的想法，从参考案例到图文草稿，一步步完成。'));
  const date = el('time', new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' }), 'date-label');
  heading.append(headingText, date);
  const welcome = el('div', undefined, 'welcome-panel');
  const content = el('div', undefined, 'welcome-content');
  const composer=el('div',undefined,'brief-composer');
  const brief=field(composer,'创作需求','','textarea');
  brief.maxLength=1000;
  brief.placeholder='例如：想做一篇 M22 科普，讲清仪器区别和滤片知识，参考同类高赞图文。';
  const composerActions=el('div',undefined,'brief-actions');
  const inputHint=el('span','先理解方向，再匹配参考','brief-hint');
  const counter=el('span','0 / 1000','brief-counter');
  const begin=async()=>{
    if(!brief.value.trim())throw new Error('请先写下你想做的内容');
    setupDraft={question:brief.value.trim(),project:'自动识别',audience:'刚了解该项目的读者',facts:'',bundle_id:bundles[0]?.bundle_id||''};
    task=null;mode='high';go('modes');
    await startHighWorkflow(setupDraft);
  };
  const start=button('开始创作',begin,'btn primary brief-submit');
  start.setAttribute('aria-label','理解需求并开始');
  start.append(icon('arrow-right'));
  const actionRight=el('div',undefined,'brief-action-right');
  actionRight.append(counter,start);composerActions.append(inputHint,actionRight);
  composer.append(composerActions);content.append(composer);
  brief.addEventListener('input',()=>{counter.textContent=brief.value.length+' / 1000';});
  brief.addEventListener('keydown',event=>{if(event.key==='Enter'&&(event.ctrlKey||event.metaKey)&&!busy){event.preventDefault();run(begin,'开始创作');}});
  const suggestions=el('div',undefined,'brief-suggestions');
  suggestions.append(el('span','试试这些方向','suggestion-label'));
  for(const [label,value] of [['M22 知识科普','做一篇 M22 知识科普，讲清原理和基础知识，参考同类高赞图文。'],['仪器区别对比','做一篇光子嫩肤仪器对比，讲清设备区别与选择维度，参考同类对比图文。'],['术后护理','做一篇光子嫩肤术后护理图文，给第一次了解的读者看，按时间顺序整理重点。']]) {
    suggestions.append(button(label,()=>{brief.value=value;brief.dispatchEvent(new Event('input'));brief.focus();},'suggestion-button'));
  }
  content.append(suggestions);
  const workflow = el('ol', undefined, 'workflow-outline');
  [
    ['理解需求', '明确主题和方向'],
    ['匹配参考', '借鉴同类案例'],
    ['图文共创', '逐页确认内容'],
    ['导出成品', '检查后由你发布']
  ].forEach(([title, hint], index) => {
    const item = el('li');
    const copy = el('div');
    copy.append(el('strong', title), el('small', hint));
    item.append(el('span', String(index + 1), 'step-number'), copy);
    workflow.append(item);
  });
  welcome.append(content, workflow);
  const grid = el('div', undefined, 'home-grid');
  const resume = el('section', undefined, 'workspace-section');
  resume.id = 'recentTasks';
  resume.setAttribute('aria-label', '继续创作');
  const resumeHead = el('div', undefined, 'section-head');
  const resumeTitle = el('h2', activeNav === 'tasksNav' ? '我的创作' : '最近创作');
  if (token) resumeTitle.append(el('span', tasks.length + ' 条内容', 'section-count'));
  resumeHead.append(resumeTitle);
  if (token) resumeHead.append(button('刷新列表', async () => { await refreshLists(); await render(); }, 'text-button'));
  resume.append(resumeHead);
  if (token && tasks.length) {
    const searchWrap = el('div', undefined, 'search-field');
    const search = el('input');
    search.type = 'search';
    search.placeholder = '搜索主题或创作内容';
    search.setAttribute('aria-label', '搜索已有创作');
    searchWrap.append(icon('search'), search);
    const list = el('div', undefined, 'task-list');
    let showAll = activeNav === 'tasksNav';
    const noResult = el('div', undefined, 'empty-state');
    noResult.append(el('h3', '没有匹配的内容'), el('p', '试试其他关键词，或清空搜索查看全部创作。'));
    noResult.hidden = true;
    tasks.forEach(row => {
      const item = el('article', undefined, 'task-row');
      const documentIcon = el('div', undefined, 'task-document');
      documentIcon.append(icon('file'));
      const info = el('div', undefined, 'task-info');
      const title = el('div', row.question || row.project || '未命名内容', 'task-title');
      title.title = row.question || row.project || '';
      const meta = el('div', undefined, 'task-meta');
      const badge = el('span', taskStageBadge(row), 'task-badge' + (row.exported ? ' done' : ''));
      const updated = row.updated_at ? new Date(row.updated_at) : null;
      meta.append(el('span', (row.legacy ? '历史任务 / ' : '') + row.project), badge);
      if (updated && !Number.isNaN(updated.getTime())) meta.append(el('time', updated.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })));
      info.append(title, meta);
      const actions = el('div', undefined, 'task-row-actions');
      const resumeButton = button(row.exported ? '查看' : '继续', () => openTask(row.id), 'btn quiet');
      resumeButton.setAttribute('aria-label', (row.exported ? '查看：' : '继续：') + (row.question || row.project));
      const deleteButton = button('删除', () => deleteTask(row), 'btn danger');
      deleteButton.setAttribute('aria-label', '删除：' + (row.question || row.project));
      actions.append(resumeButton, deleteButton);
      item.append(documentIcon, info, actions);
      list.append(item);
      item.dataset.search = (row.question + ' ' + row.project).toLocaleLowerCase();
    });
    const moreButton = el('button', '', 'text-button task-more');
    moreButton.type = 'button';
    const filterTasks = () => {
      const query = search.value.trim().toLocaleLowerCase();
      let matches = 0;
      list.querySelectorAll('.task-row').forEach((row, index) => {
        row.hidden = query ? !row.dataset.search.includes(query) : (!showAll && index >= 2);
        if (!row.hidden) matches++;
      });
      noResult.hidden = matches > 0;
      moreButton.hidden = Boolean(query) || tasks.length <= 2;
      moreButton.textContent = showAll ? '收起列表' : '查看全部 ' + tasks.length + ' 条内容';
    };
    search.addEventListener('input', filterTasks);
    moreButton.addEventListener('click', () => { showAll = !showAll; filterTasks(); });
    filterTasks();
    resume.append(searchWrap, list, noResult, moreButton, el('p', '任务自动保存在本地，随时回来继续。', 'task-footer'));
  } else {
    const empty = el('div', undefined, 'empty-state');
    empty.append(icon('file'), el('h3', token ? '你的第一条内容，从这里开始' : '正在读取你的创作'), el('p', token ? '创建一个主题，和 AI 一起完成第一篇图文。' : '页面打开后会自动读取已保存的任务。'));
    const action = el('button', token ? '开始创作' : '重新加载', 'btn quiet');
    action.type = 'button';
    action.addEventListener('click', token ? startNewContent : startWorkspace);
    empty.append(action);
    resume.append(empty);
  }
  const aside = el('aside', undefined, 'home-aside');
  const library = el('section', undefined, 'library-panel');
  library.id = 'librarySection';
  const libraryTitle = el('div', undefined, 'library-title');
  libraryTitle.append(icon('folder'), el('h2', '案例资料库'));
  library.append(libraryTitle, el('p', '按项目和话题，找到这次创作的参考。'));
  if (token) {
    const total = bundles.reduce((sum, item) => sum + (Number(item.count) || 0), 0);
    library.append(el('strong', bundles.length ? total + ' 篇案例 / ' + bundles.length + ' 个版本' : '还没有导入案例', 'library-total'));
    const details = el('details');
    details.open = !bundles.length;
    details.append(el('summary', '导入案例资料'));
    const file = el('input');
    file.type = 'file';
    file.accept = '.zip';
    file.id = 'bundleFile';
    file.setAttribute('aria-label', '选择案例 ZIP 资料包');
    const importButton = button('导入 ZIP 资料包', async () => {
      if (!file.files[0]) throw new Error('请选择 xhs 导出的 ZIP');
      const body = new FormData();
      body.append('bundle', file.files[0]);
      await request('/bundles', 'POST', body);
      await refreshLists();
      await render();
      showToast('案例资料已导入');
    }, 'btn quiet');
    details.append(file, importButton, el('p', '使用 xhs 导出的案例 ZIP。原始资料只读保存，创作时可选择版本。', 'muted'));
    library.append(details);
    library.append(el('div','资料保存在本机，可随时补充。','library-version'));
    try { await renderCatalog(library); } catch(error) { library.append(el('p','分类浏览需更新启动后使用。','muted')); }
  } else {
    library.append(el('p', '正在读取案例资料…'));
  }
  aside.append(library);
  grid.append(resume, aside);
  screen.append(heading, welcome, grid);
}

async function loadM22Research() {
  const pending = {status:'loading'};
  researchState = pending;
  await render();
  try {
    const report = await request('/research/m22', 'POST');
    if (researchState !== pending) return;
    researchState = report;
  } catch (error) {
    if (researchState !== pending) return;
    researchState = {status:'error', message:error.message};
  }
  if (screenId === 'topics') {
    await render();
    document.querySelector('.research-card h2')?.focus();
  }
}

function renderResearchCard(screen) {
  const heading = el('div', undefined, 'section-title');
  const title = el('div');
  title.append(el('h1', 'M22 科普'), el('p', '先确定这一篇讲什么，再开始创作。'));
  const back = el('button', '返回选题', 'btn');
  back.addEventListener('click', () => {researchState=null;render();});
  heading.append(title, back);screen.append(heading);
  const card = el('section', undefined, 'panel research-card');
  card.setAttribute('aria-label', '调研结论卡');
  card.setAttribute('aria-busy', String(researchState.status==='loading'));
  const h2 = el('h2', '调研结论卡');h2.tabIndex=-1;card.append(h2);
  if (researchState.status !== 'ready') {
    const message = el('p', researchState.status==='loading' ? '正在对照已导入的 M22 科普帖子，整理本篇方向…' : researchState.message, 'research-message');
    message.setAttribute('role','status');card.append(message);
    if (researchState.status==='error') {
      const retry=el('button','重试调研','btn primary');retry.addEventListener('click',loadM22Research);card.append(retry);
    }
    if (researchState.status==='empty') {
      const library=el('button','导入案例资料','btn primary');
      library.addEventListener('click',()=>document.getElementById('libraryBtn').click());card.append(library);
    }
    screen.append(card);return;
  }
  const report=researchState, a=report.analysis;
  card.append(el('p', '本次分析 '+report.sample_count+' 篇 / 相关案例 '+report.eligible_count+' 篇', 'muted'));
  const proposal=el('div',undefined,'research-proposal');
  proposal.append(el('p','AI 推荐方向','research-label'), el('h3',a.direction));
  const list=el('dl',undefined,'research-brief');
  for(const [label,value] of [['写给谁（AI 建议）',a.audience],['回答什么',a.reader_question],['怎样介绍',a.approach]]) {
    list.append(el('dt',label),el('dd',value));
  }
  proposal.append(list);card.append(proposal);
  const findings=el('details',undefined,'research-evidence');
  findings.append(el('summary','查看样本观察与推荐依据'));
  const observed=el('ul');
  for(const f of a.findings) {
    const row=el('li');row.append(el('p',f.observation));
    const source=report.samples.find(x=>x.sample_id===f.sample_id);
    row.append(el('blockquote',f.quote));
    if(source) {const link=el('a','原帖：'+source.title);link.href=source.url;link.target='_blank';link.rel='noopener noreferrer';row.append(link);}
    observed.append(row);
  }
  findings.append(el('h3','样本内容观察'), observed, el('h3','推荐理由（AI 判断）'),el('p',a.reason));
  const refs=el('ul',undefined,'research-sources');
  for(const source of report.samples) {
    const row=el('li'),link=el('a',source.title);link.href=source.url;link.target='_blank';link.rel='noopener noreferrer';
    row.append(link,el('span',source.likes===null?'点赞未采集':source.likes+' 赞（采集快照）','muted'));refs.append(row);
  }
  findings.append(el('h3','本次参考帖子'),refs,el('p',report.coverage,'muted'),el('p',report.sampling,'muted'));
  card.append(findings);
  const actions=el('div',undefined,'research-actions');
  const adopt=el('button','采用这个方向，继续创作','btn primary');
  adopt.addEventListener('click',()=>{
    setupDraft={project:'M22',audience:a.audience,
      question:'做一篇 M22 科普。方向：'+a.direction+'。重点回答：'+a.reader_question+'。介绍方式：'+a.approach,
      facts:'',bundle_id:report.bundle_id,research_id:report.id};
    task=null;sessionStorage.removeItem('studio_task');mode='high';chosenStrategy='';strategyChosen=false;
    go('modes');render();
  });
  actions.append(adopt,el('span','方向可在下一页修改','muted'));card.append(actions);screen.append(card);
}

async function renderTones() {
  const screen=$('tones');screen.replaceChildren();
  const heading=el('header',undefined,'section-title');
  const title=el('div');title.append(el('h1','语气库'),el('p','内容决定讲什么，语气决定怎么说。选一种口吻，按同一套标准创作。'));
  heading.append(title,button(toneSource?'返回原稿':'返回工作台',()=>{go(toneSource?'create':'home');render();},'btn quiet'));screen.append(heading);
  if(!toneData) {
    const loading=el('p','正在读取语气分类…','muted');loading.setAttribute('role','status');screen.append(loading);
    try {toneData=await request('/tones'+(toneSource?.bundle_id?'?bundle_id='+encodeURIComponent(toneSource.bundle_id):''));} catch(error) {toneError=error.message;}
    if(screenId!=='tones')return;
    if(!toneData){screen.append(el('p',toneError,'review'),button('重试读取',()=>renderTones(),'btn quiet'));return;}
    screen.replaceChildren();screen.append(heading);
  }
  const toolbar=el('div',undefined,'tone-toolbar');
  const bundleWrap=el('label','案例来源','tone-source-picker'),bundle=el('select');bundle.setAttribute('aria-label','语气分析的案例资料包');
    for(const [index,item] of bundles.entries()){
      const name=/^[a-f\d]{12,}$/i.test(item.version||'')?'案例资料包 '+(index+1):item.version;
      const option=el('option',name+' · '+item.count+' 篇');option.value=item.bundle_id;bundle.append(option);
    }
  bundle.value=toneData.bundle_id||'';bundle.disabled=toneAnalyzing||Boolean(toneSource);
  bundle.addEventListener('change',()=>run(async()=>{toneData=await request('/tones?bundle_id='+encodeURIComponent(bundle.value));toneError='';await render();},'读取分类'));
  bundleWrap.append(bundle);toolbar.append(bundleWrap);
  const s=toneData.summary;
  const status=el('p',`${s.total} 篇案例，${s.classified} 篇已归类，${s.uncertain} 篇待判断，${s.excluded} 篇已排除`,'muted');status.setAttribute('role','status');toolbar.append(status);
  if(toneAnalyzing) {
    const stop=el('button','完成本批后停止','btn quiet');stop.type='button';stop.addEventListener('click',()=>{toneStop=true;stop.textContent='正在完成当前批次…';stop.disabled=true;});toolbar.append(stop);
  } else if(s.pending) {
    toolbar.append(button(s.classified?'继续语义分类':'分析案例语气',()=>analyzeToneLibrary(),'btn quiet'));
  }
  screen.append(toolbar);
  if(toneError)screen.append(el('p',toneError,'review'));
  if(!s.total){screen.append(el('p','还没有案例。先导入资料，再根据真实文字分析语气。','empty-state'),button('前往案例资料',()=>showHomeSection('libraryBtn','librarySection'),'btn quiet'));return;}
  if(s.pending)screen.append(el('p',toneAnalyzing?`正在语义分析，还剩 ${s.pending} 篇；已完成结果会保留。`:`还有 ${s.pending} 篇待语义分析，未分析的案例不会冒充已分类。`,'muted'));
  const workspace=el('div',undefined,'tone-workspace');
  const nav=el('nav',undefined,'tone-nav');nav.setAttribute('aria-label','语气类别');
  const choices=[...toneData.presets,{id:'uncertain',title:'待判断',count:s.uncertain},{id:'excluded',title:'已排除',count:s.excluded}];
  const mobile=el('select',undefined,'tone-mobile-picker');mobile.setAttribute('aria-label','选择语气类别');
  for(const preset of choices) {
    const item=el('button',undefined,'tone-option');item.type='button';item.setAttribute('aria-pressed',String(selectedTone===preset.id));
    item.append(el('span',preset.title),el('span',String(preset.count),'tone-count'));
    item.addEventListener('click',()=>{selectedTone=preset.id;render();});nav.append(item);
    const option=el('option',preset.title+' · '+preset.count+' 篇');option.value=preset.id;mobile.append(option);
  }
  mobile.value=selectedTone;mobile.addEventListener('change',()=>{selectedTone=mobile.value;render();});
  const detail=el('section',undefined,'tone-detail');detail.setAttribute('aria-label','语气标准与案例');
  const definition=toneData.presets.find(p=>p.id===selectedTone);
  if(definition) {
    const lead=el('div',undefined,'tone-detail-heading');lead.append(el('h2',definition.title),el('p',definition.summary));detail.append(lead);
    const rules=el('ol',undefined,'tone-rules');definition.criteria.forEach(rule=>rules.append(el('li',rule.text)));detail.append(el('h3','输出必须符合这三条'),rules);
    const examples=el('div',undefined,'tone-example-pair');
    for(const [label,value] of [['这样说',definition.positive_example],['避免这样说',definition.negative_example]]) {
      const item=el('div');item.append(el('h3',label),el('p',value));examples.append(item);
    }
    detail.append(examples,el('p','以上为编辑编写的句式示范；原帖依据见下方。','muted'));
  } else detail.append(el('h2',selectedTone==='excluded'?'已排除的案例':'需要进一步判断'),el('p',selectedTone==='excluded'?'含模板生成提示或重复段落，不作语气正例。':'语气证据不足、置信度偏低或没有明显主语气，不强行归类。'));
  const listDetails=el('details',undefined,'tone-case-section');listDetails.open=!definition;
  const matched=toneData.items.filter(item=>definition?item.status==='classified'&&item.voice_id===selectedTone:item.status===selectedTone);
  listDetails.append(el('summary','查看 '+matched.length+' 篇原帖与分类依据'));
  const query=el('input');query.type='search';query.placeholder='搜索原帖标题或分类理由';query.setAttribute('aria-label','搜索本类原帖');
  const cases=el('div',undefined,'tone-cases');
  function drawCases(){
    cases.replaceChildren();const rows=matched.filter(item=>(item.title+' '+(item.reason||'')).toLocaleLowerCase().includes(query.value.trim().toLocaleLowerCase()));
    for(const item of rows){
      const row=el('article',undefined,'tone-case'),link=el('a',item.title);link.href=item.url;link.target='_blank';link.rel='noopener noreferrer';
      row.append(link,el('p',item.reason||'待核对','muted'));
      for(const proof of item.evidence||[])row.append(el('blockquote',proof.quote));
      if(item.confidence!==undefined)row.append(el('p','语义判断置信度 '+Math.round(item.confidence*100)+'% · '+(item.matched_rules||[]).join('、'),'tone-case-meta'));
      cases.append(row);
    }
    if(!rows.length)cases.append(el('p',matched.length?'没有匹配的原帖。':'尚无已确认属于本类的样本。','muted'));
  }
  query.addEventListener('input',drawCases);listDetails.append(query,cases);drawCases();detail.append(listDetails);
  const scope=el('details',undefined,'tone-scope');scope.append(el('summary','查看分类范围与说明'),el('p',toneData.scope,'muted'),el('p','模型判断语气，不认证医学内容。标准被采用后保存到任务快照，后续写作和审稿逐条核对。','muted'));detail.append(scope);
  if(definition){
    const actions=el('footer',undefined,'tone-actions');
    const use=button(toneSource?'以此语气创建新版本':'用此语气新建图文',async()=>{
      if(toneSource){
        task=await request('/tasks/'+toneSource.id+'/tone-version','POST',{revision:toneSource.revision,writing_style:selectedTone});
        sessionStorage.setItem('studio_task',task.id);toneSource=null;mode='high';await refreshLists();go('modes');await render();await mutate('/expression-study');
      }else{
        const values=setupDraft||task?.request||{};
        setupDraft={...values,writing_style:selectedTone,project:values.project||'M22',question:values.question||'',bundle_id:toneData.bundle_id};
        if(values.bundle_id!==toneData.bundle_id)delete setupDraft.research_id;
        task=null;sessionStorage.removeItem('studio_task');mode='high';go('modes');await render();
      }
    });
    use.disabled=definition.count===0||toneAnalyzing;actions.append(use,el('span','保留内容目的，只选择表达方式。','muted'));detail.append(actions);
  }
  workspace.append(nav,mobile,detail);screen.append(workspace);
}

async function analyzeToneLibrary(){
  if(toneAnalyzing)return;
  toneAnalyzing=true;toneStop=false;toneError='';
  try{
    while(toneData?.summary.pending&&!toneStop){
      const bundleId=toneData.bundle_id;await render();
      toneData=await request('/tones/analyze','POST',{bundle_id:bundleId});
      if(screenId!=='tones')toneStop=true;
    }
  }catch(error){toneError=error.message;}
  finally{toneAnalyzing=false;if(screenId==='tones')await render();}
}

async function renderTopics() {
  const screen = $('topics');
  screen.replaceChildren();
  if (researchState) { renderResearchCard(screen); return; }
  const crumb = el('div', undefined, 'crumb');
  const home = el('button', '首页');
  home.addEventListener('click', () => { go('home'); render(); });
  crumb.append(home, document.createTextNode(' / 选择主题'));
  const heading = el('div', undefined, 'section-title');
  const left = el('div');
  left.append(el('h1', '你想做什么内容？'), el('p', '直接描述需求，AI 会识别项目并匹配同类参考。'));
  const back = el('button', '返回首页', 'back');
  back.addEventListener('click', () => { go('home'); render(); });
  heading.append(left, back);
  const grid = el('div', undefined, 'topic-grid');
  const m22 = el('button', undefined, 'topic');
  m22.append(el('span', '当前开放', 'topic-tag'), el('div', 'M22', 'topic-icon'), el('h2', 'M22'), el('p', 'M22 科普：先看同类内容调研，再确定本篇方向'));
  m22.addEventListener('click', loadM22Research);
  const more = el('div', undefined, 'topic unavailable');
  more.classList.remove('unavailable');
  more.append(icon('plus'), el('h2', '用自己的话开始'), el('p', '科普、对比、护理、体验……输入需求后自动识别项目和方向。'));
  more.setAttribute('role','button');more.tabIndex=0;
  const openIdea = () => { mode='idea';go('modes');render(); };
  more.addEventListener('click',openIdea);
  more.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();openIdea();}});
  grid.append(m22, more);
  screen.append(crumb, heading, grid);
}

async function render() {
  revokeUrls();
  ensureStatus();
  screens.forEach(screen => screen.replaceChildren());
  $('connectionState').textContent = serverReachable === false ? '本机服务未连接' : token ? '本机运行' : '正在加载';
  if (screenId === 'tones') await renderTones();
  if (screenId === 'home') await renderHome();
  if (screenId === 'topics') await renderTopics();
  if (screenId === 'modes') {
    if (task && task.schema_version !== 2) await renderLegacy();
    else await renderModes();
  }
  if (screenId === 'create') await renderCreate();
  if (screenId === 'publish') await renderExport();
  go(screenId);
}

async function submitFeedback() {
  if (!task?.draft) throw new Error('请先完成一条草稿，再记录对应的平台反馈');
  const type = $('feedbackType').value;
  const text = $('feedbackText').value.trim();
  if (!text) throw new Error('请粘贴平台返回的具体文案');
  task = await request('/tasks/' + task.id + '/feedback', 'POST', {
    notice: '反馈类型：' + type + '\n平台原文：\n' + text,
    posted_text: task.draft.body
  });
  $('feedbackText').value = '';
  $('feedbackModal').classList.remove('show');
  screenId = 'publish';
  await render();
  showToast('反馈已保存，AI 分析结果已加入任务记录，仍需人工复核');
}

$('retryStartup').addEventListener('click', startWorkspace);
$('newContentBtn').setAttribute('aria-label', '新建图文');
$('newContentBtn').addEventListener('click', startNewContent);
async function showHomeSection(nav = 'homeNav', section) {
  if (busy) return;
  setStatus('');
  activeNav = nav;
  screenId = 'home';
  await render();
  if (section) $(section)?.scrollIntoView({ behavior: 'instant', block: 'start' });
}
$('homeNav').addEventListener('click', () => showHomeSection());
$('tasksNav').addEventListener('click', () => showHomeSection('tasksNav', 'recentTasks'));
$('tonesNav').addEventListener('click',()=>{toneSource=null;toneData=null;toneError='';go('tones');run(()=>render(),'读取语气库');});
document.querySelector('.brand').addEventListener('click', event => { event.preventDefault(); showHomeSection(); });
document.getElementById('libraryBtn').addEventListener('click', async () => {
  if (!token) { setStatus('服务尚未就绪，请刷新页面或重新双击 start_studio.bat。', true); return; }
  await showHomeSection('libraryBtn', 'librarySection');
  const library = document.querySelector('#librarySection .catalog-browser');
  if (library) library.open = true;
});
document.getElementById('feedbackBtn').addEventListener('click', () => {
  modalTrigger = document.activeElement;
  $('feedbackModal').querySelector('.modal-error')?.remove();
  $('feedbackModal').classList.add('show');
  $('feedbackType').focus();
});
document.getElementById('closeFeedback').addEventListener('click', () => $('feedbackModal').classList.remove('show'));
$('feedbackModal').addEventListener('click', event => { if (event.target === $('feedbackModal')) $('feedbackModal').classList.remove('show'); });

document.addEventListener('keydown', event => {
  const modal = document.querySelector('.modal.show');
  if (!modal) return;
  if (event.key === 'Escape' && !busy) {
    modal.classList.remove('show');
    if (modalTrigger?.isConnected) modalTrigger.focus();
  }
  if (event.key === 'Tab') {
    const controls = [...modal.querySelectorAll('button:not(:disabled), input, select, textarea')];
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }
});
document.getElementById('submitFeedback').addEventListener('click', () => run(submitFeedback));

async function startWorkspace() {
  if (busy) return;
  await render();
  let ready = false;
  await run(async () => {
    const response = await fetch('/api/local-session', { headers: { 'X-Studio-Local': '1' } }).catch(() => { throw connectionError(); });
    if (response.ok) {
      token = (await response.json()).access_token;
      sessionStorage.setItem('studio_token', token);
    } else if (!token) {
      throw new Error('请重新双击 start_studio.bat 启动新版，再刷新页面。');
    }
    await refreshLists();
    const last = sessionStorage.getItem('studio_task');
    if (last) {
      try {
        await openTask(last);
        ready = true;
        return;
      } catch (_) {
        sessionStorage.removeItem('studio_task');
      }
    }
    await render();
    ready = true;
  }, '正在读取创作资料');
  $('retryStartup').hidden = ready;
  if (ready) setStatus('');
  else {
    $('connectionState').textContent = '服务未就绪';
    $('connectionState').classList.remove('connected');
  }
}

startWorkspace();

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
let objectUrls = [];
let autoStarted = false;

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
  b.addEventListener('click', () => run(handler));
  return b;
}

function showToast(message) {
  if (!toast) return;
  toast.textContent = message;
  toast.classList.add('show');
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove('show'), 3000);
}

async function run(handler) {
  if (busy) return;
  busy = true;
  const controls = [...document.querySelectorAll('button')];
  const disabledBefore = controls.map(b => [b, b.disabled]);
  controls.forEach(b => { b.disabled = true; });
  setStatus('正在处理，请稍候。模型请求可能需要一两分钟。');
  try {
    await handler();
    setStatus('已保存，可检查结果后继续。');
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
    setStatus('未完成：' + (error.message || error) + '（已停止，不会自动重试）', true);
  } finally {
    disabledBefore.forEach(([b, disabled]) => { b.disabled = disabled; });
    busy = false;
  }
}

async function request(path, method = 'GET', body, binary = false) {
  const headers = { Authorization: 'Bearer ' + token };
  if (body && !(body instanceof FormData)) headers['Content-Type'] = 'application/json';
  const response = await fetch('/api' + path, {
    method,
    headers,
    body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined
  });
  if (!response.ok) {
    let detail = '';
    try {
      const data = await response.json();
      detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
    } catch (_) {
      detail = '服务未返回有效结果，请检查启动窗口。';
    }
    if (response.status === 401) detail = '访问口令无效或已失效，请重新连接工作台。';
    if (response.status === 404 && path.includes('/analysis-stage')) {
      detail = '当前后端未加载分步确认接口，请关闭旧启动窗口后重新双击 start_studio.bat，再刷新页面。';
    }
    throw new Error(detail);
  }
  return binary ? response.blob() : response.json();
}

function openAccess() {
  $('accessToken').value = token || '';
  $('accessModal').classList.add('show');
  window.setTimeout(() => $('accessToken').focus(), 0);
}

function closeAccess() {
  $('accessModal').classList.remove('show');
}

async function connectWith(value) {
  const candidate = (value || '').trim();
  if (!candidate) throw new Error('请填写访问口令');
  const previous = token;
  token = candidate;
  try {
    await refreshLists();
  } catch (error) {
    token = previous;
    throw error;
  }
  sessionStorage.setItem('studio_token', token);
  closeAccess();
  $('connectionState').textContent = '已连接';
  if (!bundles.length) screenId = 'home';
  showToast('工作台已连接');
  await render();
}

async function refreshLists() {
  if (!token) return;
  const result = await Promise.all([request('/tasks'), request('/bundles')]);
  tasks = result[0];
  bundles = result[1];
}

function revokeUrls() {
  objectUrls.forEach(url => URL.revokeObjectURL(url));
  objectUrls = [];
}

function go(next) {
  screenId = next;
  screens.forEach(screen => screen.classList.toggle('active', screen.id === next));
  window.scrollTo({ top: 0, behavior: 'smooth' });
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
  } catch (error) {
    parent.append(el('p', '图片未加载：' + error.message, 'review'));
  }
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

function pipeline(parent) {
  const wrap = el('div', undefined, 'pipeline');
  const steps = [
    ['1', '检索案例', '相关性 → 点赞快照'],
    ['2', '语言分析', '标题、开头、结构'],
    ['3', '视觉分析', '原图、逐页画面'],
    ['4', '事实资料', '来源与合规边界'],
    ['5', '写作规则', '形成可选方案']
  ];
  steps.forEach(([num, title, hint], index) => {
    const item = el('div', undefined, 'pipe');
    const done = stepStatus(index + 1) === '已确认';
    if (done) item.classList.add('done');
    item.append(el('div', num, 'pipe-num'), el('b', title), el('small', hint), el('div', stepStatus(index + 1), 'step-state' + (done ? ' done' : '')));
    wrap.append(item);
  });
  parent.append(wrap);
}

function setupPanel(parent) {
  const panel = el('div', undefined, 'panel');
  panel.append(el('h2', '本次主题参数'), el('p', '这些信息用于筛选相关案例，也决定 AI 可以写哪些门店事实。', 'muted'));
  const grid = el('div', undefined, 'form-grid');
  const bundle = field(grid, '案例资料版本', '', 'select');
  bundle.id = 'bundle';
  bundles.forEach(item => {
    const option = el('option', item.version + ' · ' + item.count + '篇');
    option.value = item.bundle_id;
    bundle.append(option);
  });
  if (task && task.request) bundle.value = task.request.bundle_id;
  const audience = field(grid, '给谁看', task?.request?.audience || '第一次了解 M22 的顾客', 'input');
  audience.id = 'audience';
  const question = field(grid, '这篇想回答什么？', task?.request?.question || '第一次了解 M22，应该先问清哪些信息？');
  question.id = 'question';
  question.maxLength = 1000;
  const facts = field(grid, '你能确认的门店事实或资料', task?.request?.facts || '');
  facts.id = 'facts';
  facts.maxLength = 6000;
  const factsWrap = facts.closest('.field');
  if (factsWrap) factsWrap.classList.add('wide');
  panel.append(grid);
  parent.append(panel);
  return { bundle, audience, question, facts };
}

function currentRequest() {
  return {
    project: 'M22',
    audience: document.getElementById('audience')?.value.trim() || '第一次了解 M22 的顾客',
    question: document.getElementById('question')?.value.trim() || '第一次了解 M22，应该先问清哪些信息？',
    facts: document.getElementById('facts')?.value.trim() || '',
    bundle_id: document.getElementById('bundle')?.value || bundles[0]?.bundle_id || ''
  };
}

async function startHighWorkflow() {
  if (!token) {
    openAccess();
    return;
  }
  const body = currentRequest();
  if (!body.bundle_id) throw new Error('还没有案例资料，请先在案例资料管理中导入 ZIP');
  const sameRequest = task && task.request && ['project', 'audience', 'question', 'facts', 'bundle_id'].every(key => task.request[key] === body[key]);
  if (!sameRequest || task.stage === 'no_match') {
    task = await request('/tasks', 'POST', body);
    chosenStrategy = '';
    strategyChosen = false;
    sessionStorage.setItem('studio_task', task.id);
    await refreshLists();
    await render();
  }
  if (!task.case) return;
  if (!task.analysis) {
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
  const feedback = field(wrap, '如果不采用，请写出具体修改建议', '');
  feedback.maxLength = 2000;
  const actions = el('div', undefined, 'page-actions');
  if (allowAccept) actions.append(button('采用这一步结果，进入下一步', () => acceptHandler ? acceptHandler() : decideStage(stage, 'accept', ''), 'btn primary'));
  actions.append(button('不采用，按我的建议重做', () => {
    if (stage === 'retrieval') return rejectRetrieval(feedback.value);
    return decideStage(stage, 'reject', feedback.value);
  }, 'btn quiet'));
  wrap.append(actions, el('p', '退回只重做当前步骤，后续结果会重新等待确认。', 'step-state'));
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

async function renderVisualStage(parent) {
  const analysis = task.analysis;
  parent.append(el('h3', 'AI 的视觉分析结果'));
  parent.append(el('p', '分析依据：' + task.analysis_basis, 'muted'));
  parent.append(el('p', '请同时对照下方原图。没有视觉输入时，AI 只能根据 OCR 和正文推测，不能把配色、构图或画面元素当成事实。', 'review'));
  const list = el('div', undefined, 'case-pages');
  analysis.original_pages.forEach(page => {
    const card = el('article', undefined, 'case-page');
    card.append(el('h3', '原帖第 ' + page.number + ' 页'), el('p', page.observation));
    if (page.uncertainty) card.append(el('p', '不确定：' + page.uncertainty, 'review'));
    list.append(card);
  });
  parent.append(list);
  await referencePages(parent, '查看 AI 对照的参考原图、OCR 与正文');
}

function renderFactsStage(parent) {
  parent.append(el('h3', '本次实际使用的资料'));
  sourceEvidence(parent);
  const trace = [...(task.traces || [])].reverse().find(item => item.sources);
  (trace?.sources || []).forEach(source => {
    const details = el('details');
    details.append(el('summary', source.id + ' · ' + (source.type || '未标注类型')));
    const content = typeof source.content === 'string' ? source.content : JSON.stringify(source.content, null, 2);
    details.append(el('pre', content.slice(0, 3000)));
    parent.append(details);
  });
  if (task.analysis.missing_information.length) parent.append(el('p', 'AI 标出的缺少信息：' + task.analysis.missing_information.join('；'), 'review'));
  else parent.append(el('p', 'AI 没有标出缺少信息；仍需你核对门店事实和合规边界。', 'muted'));
}

function renderWritingStage(parent) {
  const analysis = task.analysis;
  parent.append(el('h3', 'AI 的写作规则与逐页大纲'));
  parent.append(el('p', '这一阶段只决定组织方式，不会把参考帖医学结论直接复制到成品。', 'muted'));
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
  const edits = [];
  analysis.outline.forEach((outline, index) => {
    const box = el('article', undefined, 'outline-page');
    box.append(el('h3', '新内容第 ' + (index + 1) + ' 页'));
    const kind = el('select');
    [['text', '纯文字卡：直接排版'], ['photo', '实拍页：上传自己的照片']].forEach(([value, label]) => {
      const option = el('option', label);
      option.value = value;
      kind.append(option);
    });
    kind.value = outline.kind;
    const kindLabel = el('label', '页面类型');
    kindLabel.append(kind);
    box.append(kindLabel);
    const purpose = field(box, '本页要讲什么', outline.purpose);
    const instruction = field(box, '制作或拍摄说明', outline.instruction);
    box.append(el('div', '借鉴原帖第 ' + outline.source_pages.join('、') + ' 页', 'inline-meta'));
    const edit = { kind, purpose, instruction, removed: false };
    edits.push(edit);
    const remove = el('button', '移除这一页', 'btn danger');
    remove.addEventListener('click', () => {
      if (edits.filter(item => !item.removed).length <= 1) {
        showToast('至少保留一页');
        return;
      }
      edit.removed = true;
      box.hidden = true;
    });
    box.append(remove);
    parent.append(box);
  });
  if (analysis.missing_information.length) parent.append(el('p', '需要补充或回避：' + analysis.missing_information.join('；'), 'review'));
  const confirmed = check(parent, '我已对照原图检查拆解，并确认新内容大纲');
  stageDecisionBox(parent, 'writing', true, () => {
    if (!strategyChosen) throw new Error('请先选择一种创作形式');
    if (!confirmed.checked) throw new Error('请先核对并勾选确认');
    const next = JSON.parse(JSON.stringify(analysis));
    next.outline = next.outline.map((item, index) => ({
      ...item,
      kind: edits[index].kind.value,
      purpose: edits[index].purpose.value,
      instruction: edits[index].instruction.value
    })).filter((_, index) => !edits[index].removed);
    return decideStage('writing', 'accept', '', next);
  });
}

async function renderStageFlow(parent) {
  const current = currentAnalysisStage();
  if (!current) return;
  renderAcceptedStages(parent, current);
  const box = el('div', undefined, 'stage-panel');
  const index = ANALYSIS_STAGE_KEYS.indexOf(current) + 1;
  box.append(el('h3', '第 ' + index + ' 步 · ' + STAGE_LABELS[current]));
  const lastFeedback = task.analysis_stages?.[current]?.feedback;
  if (lastFeedback) box.append(el('p', '本次已按你的建议重做：' + lastFeedback, 'review'));
  if (current !== 'retrieval' && !task.analysis) {
    box.append(el('p', '模型尚未完成拆解，当前进度已保存。请手动重试；不会自动循环调用。', 'review'));
    box.append(button('重试模型拆解', () => mutate('/analyze')));
    parent.append(box);
    return;
  }
  if (current === 'retrieval') {
    box.append(el('p', task.selection.reason + ' 共 ' + task.selection.eligible_count + ' 篇相关候选，当前展示点赞快照最高的一篇。', 'muted'));
    const candidates = task.selection.candidate_ids || [];
    if (candidates.length) box.append(el('p', '候选编号：' + candidates.join('、'), 'source-link'));
    stageDecisionBox(box, current);
  } else if (current === 'language') {
    renderLanguageStage(box);
    stageDecisionBox(box, current);
  } else if (current === 'visual') {
    await renderVisualStage(box);
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

async function renderModes() {
  const screen = $('modes');
  screen.replaceChildren();
  const crumb = el('div', undefined, 'crumb');
  const topicBack = el('button', '主题选择');
  topicBack.addEventListener('click', () => { go('topics'); render(); });
  crumb.append(topicBack, document.createTextNode(' / M22 / 创作方式'));
  const heading = el('div', undefined, 'section-title');
  const headLeft = el('div');
  headLeft.append(el('div', 'STEP 02 · MODE', 'hero-kicker'), el('h1', '你想怎样开始？'), el('p', '先让 Agent 展示案例依据，再由你决定是否进入共创。'));
  const back = el('button', '返回主题', 'back');
  back.addEventListener('click', () => { go('topics'); render(); });
  heading.append(headLeft, back);
  screen.append(crumb, heading);
  setupPanel(screen);
  const tabs = el('div', undefined, 'mode-tabs');
  [['high', '小红书高赞仿写', '先筛选相关案例中点赞最高的一篇，再展示逐页拆解。'], ['idea', '我有想法，AI 来辅助', '你先写想法，AI 把它拆成下一步行动。']].forEach(([value, title, hint]) => {
    const tab = el('button', undefined, 'mode-tab' + (mode === value ? ' active' : ''));
    tab.append(el('strong', title), el('span', hint));
    tab.addEventListener('click', () => {
      mode = value;
      render();
      if (value === 'high' && token && bundles.length && !task && !autoStarted) {
        autoStarted = true;
        window.setTimeout(() => run(startHighWorkflow), 100);
      }
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
  main.append(el('h2', '小红书高赞仿写'), el('p', '当前 Agent 会按规则筛选相关案例，再用模型完成逐页拆解。模型不会自动替你确认成品。', 'muted'));
  pipeline(main);
  if (task?.case) sourceCard(main);
  if (!task) {
    main.append(el('div', '连接工作台并选择案例资料版本后，点击开始；如果已有资料，会自动进入案例检索。', 'future-box'));
    main.append(button('开始检索并拆解', startHighWorkflow));
  } else if (!task.case) {
    main.append(el('div', '没有相关案例。请修改主题问题或导入相关资料，不套用其他主题。', 'empty-state'));
    main.append(button('按当前参数重新检索', async () => {
      task = null;
      autoStarted = true;
      await startHighWorkflow();
    }, 'btn quiet'));
  } else if (task.draft) {
    main.append(el('div', '草稿已生成，进入逐页共创。', 'future-box'));
    main.append(button('进入共创', async () => { screenId = 'create'; await render(); }));
    main.append(button('重新生成草稿（按已确认大纲重写）', async () => {
      if (!window.confirm('重新生成会替换当前草稿和已制作的页面图片，确定？')) return;
      await generateDraft();
    }, 'btn quiet'));
    main.append(button('再来一条新内容', async () => {
      task = null;
      sessionStorage.removeItem('studio_task');
      chosenStrategy = '';
      strategyChosen = false;
      autoStarted = false;
      go('topics');
      await render();
    }, 'btn quiet'));
  } else if (task.confirmed_analysis) {
    main.append(el('h3', '拆解已确认'));
    task.confirmed_analysis.outline.forEach((item, index) => main.append(el('p', String(index + 1) + '. ' + (item.kind === 'text' ? '文字卡' : '实拍页') + '：' + item.purpose)));
    main.append(button('生成逐页草稿，进入共创', generateDraft));
  } else {
    await renderStageFlow(main);
  }
  side.append(el('h3', '当前 Agent 会做什么'));
  const list = el('ul');
  ['从已导入案例库筛选主题相关内容', '展示原图、OCR 和逐页结构', '使用 GUIDE、门店事实和 K1 资料做来源约束', '保留 CASE 作为结构参考，不把竞品结论当门店事实', '让你确认大纲后再生成逐页草稿'].forEach(item => list.append(el('li', item)));
  side.append(list, el('hr', undefined, 'subtle-rule'), el('p', '当前代码是来源直接注入，不是向量数据库 top-k；写作约束也在模型提示中，尚未独立成可安装 Skill。', 'muted'));
  layout.append(main, side);
  screen.append(layout);
}

async function renderIdeaMode(screen) {
  const layout = el('div', undefined, 'mode-layout');
  const main = el('div', undefined, 'panel idea-box');
  main.append(el('h2', '我有想法，AI 来辅助'), el('p', '先用自己的话说出来，不要求一开始就写成帖子。', 'muted'));
  const idea = el('textarea');
  idea.id = 'ideaText';
  idea.placeholder = '例如：我想告诉顾客，来店里咨询 M22 时应该问哪些问题……';
  main.append(idea);
  main.append(button('按这个想法寻找案例并拆解', async () => {
    if (!idea.value.trim()) throw new Error('先写一句你的想法');
    const question = document.getElementById('question');
    if (question) question.value = idea.value.trim();
    mode = 'high';
    task = null;
    autoStarted = true;
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
  left.append(el('div', 'HISTORY · READ ONLY', 'hero-kicker'), el('h1', '历史任务（只读）'), el('p', '旧任务保留用于追溯，不会被新案例流程覆盖。'));
  const back = el('button', '返回首页', 'back');
  back.addEventListener('click', () => { task = null; sessionStorage.removeItem('studio_task'); go('home'); render(); });
  heading.append(left, back);
  const panel = el('div', undefined, 'panel');
  panel.append(el('p', '这条任务使用旧版数据结构，不能在当前流程继续编辑。请新建任务使用案例资料包。', 'review'));
  panel.append(el('pre', JSON.stringify({ request: task.request, plan: task.plan, draft: task.draft }, null, 2)));
  screen.append(heading, panel);
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
  const crumb = el('div', undefined, 'crumb');
  const backModes = el('button', '创作方式');
  backModes.addEventListener('click', () => { go('modes'); render(); });
  crumb.append(backModes, document.createTextNode(' / M22 / 共创'));
  const title = el('div', undefined, 'section-title');
  const left = el('div');
  left.append(el('div', 'STEP 03 · CO-CREATE', 'hero-kicker'), el('h1', '和 AI 一起完成这条内容'), el('p', '你选择了：' + (chosenStrategy || '自定义逐页形式') + '；每一页都以真实资料和你的确认结果为准。'));
  const back = el('button', '返回修改形式', 'back');
  back.addEventListener('click', () => { go('modes'); render(); });
  title.append(left, back);
  const grid = el('div', undefined, 'creation-grid');
  const side = el('aside', undefined, 'panel');
  side.append(el('h2', '创作进度'));
  const progress = el('div', undefined, 'progress');
  const bar = el('i');
  bar.style.width = Math.round((Object.keys(task.renders || {}).length / pages.length) * 100) + '%';
  progress.append(bar);
  side.append(progress);
  [['已选定创作形式', '你可以随时回到大纲'], ['确认每一页内容', 'AI 建议，你来修改'], ['检查标题与正文', '来源和待核实项单独显示']].forEach(([head, hint], i) => {
    const row = el('div', undefined, 'check-row');
    row.append(el('div', i === 0 ? '✓' : String(i + 1), 'check-icon'));
    const content = el('div');
    content.append(el('b', head), el('span', hint));
    row.append(content);
    side.append(row);
  });
  const source = el('div', undefined, 'collab');
  source.append(el('b', '本页参考'), el('p', '小红书案例：' + (task.case?.title || '已选案例')), el('p', '借鉴原帖第 ' + outline.source_pages.join('、') + ' 页'));
  side.append(source);
  const panel = el('div', undefined, 'panel');
  panel.append(el('h2', '第 ' + number + ' / ' + pages.length + ' 页 · ' + (outline.kind === 'text' ? '文字卡' : '实拍页')));
  panel.append(el('p', outline.purpose), el('p', outline.instruction, 'muted'));
  const refs = el('div', undefined, 'thumb-row');
  for (const sourcePage of outline.source_pages) {
    await imageInto(refs, '/tasks/' + task.id + '/reference/' + sourcePage, '参考原帖第' + sourcePage + '页');
  }
  panel.append(el('div', '参考原帖第 ' + outline.source_pages.join('、') + ' 页', 'source-link'), refs);
  if (outline.kind === 'photo') {
    const asset = task.assets[String(number)];
    if (asset) {
      panel.append(el('p', '已保存实拍：' + asset.caption));
      await imageInto(panel, '/tasks/' + task.id + '/pages/' + number + '/photo', '已保存实拍照片');
    }
    const upload = el('input');
    upload.type = 'file';
    upload.accept = 'image/jpeg,image/png,image/webp';
    const uploadLabel = el('label', '上传你自己的照片');
    uploadLabel.append(upload);
    panel.append(uploadLabel);
    const caption = field(panel, '这张照片实际展示什么？', asset?.caption || '');
    panel.append(button('保存实拍照片', async () => {
      if (!upload.files[0]) throw new Error('请选择照片');
      const body = new FormData();
      body.append('photo', upload.files[0]);
      body.append('caption', caption.value);
      body.append('revision', task.revision);
      task = await request('/tasks/' + task.id + '/pages/' + number + '/photo', 'POST', body);
      await refreshLists();
      await render();
    }, 'btn quiet'));
  } else {
    panel.append(el('div', '这是纯文字卡，不需要伪造实拍照片。AI 只负责排版，事实仍由你确认。', 'future-box'));
  }
  const pageTitle = field(panel, '本页标题（可以修改）', page.title, 'input');
  pageTitle.maxLength = 60;
  const pageText = field(panel, '本页文字（可以修改）', page.text);
  pageText.maxLength = 700;
  if (page.pending?.length) panel.append(el('p', '本页待核实：' + page.pending.join('；'), 'review'));
  const resolution = field(panel, '有待核实内容时：填写依据，或说明删除了哪些未证实表述', task.page_reviews?.[String(number)]?.resolution || '');
  const confirmed = check(panel, '我已核对文字，未核实内容已补依据或移除');
  let dirty = false;
  pageTitle.addEventListener('input', () => { dirty = true; });
  pageText.addEventListener('input', () => { dirty = true; });
  const actions = el('div', undefined, 'page-actions');
  actions.append(
    button('保存文字草稿', () => mutate('/pages/' + number, { title: pageTitle.value, text: pageText.value, confirmed: false, resolution: resolution.value }), 'btn quiet'),
    button('确认并生成本页图片', () => {
      if (!confirmed.checked) throw new Error('请先勾选文字确认');
      return mutate('/pages/' + number, { title: pageTitle.value, text: pageText.value, confirmed: true, resolution: resolution.value });
    })
  );
  if (task.renders?.[String(number)]) await imageInto(panel, '/tasks/' + task.id + '/pages/' + number + '/render', '本页成品预览');
  panel.append(actions);
  const navigation = el('div', undefined, 'page-actions');
  if (index > 0) navigation.append(button('上一页', async () => {
    if (dirty) throw new Error('文字有改动，请先保存');
    await mutate('/progress', { page_index: index - 1 });
  }, 'btn quiet'));
  if (index < pages.length - 1) navigation.append(button('下一页', async () => {
    if (dirty) throw new Error('文字有改动，请先保存');
    await mutate('/progress', { page_index: index + 1 });
  }, 'btn quiet'));
  navigation.append(el('span', '已确认生成 ' + Object.keys(task.renders || {}).length + ' / ' + pages.length + ' 页', 'step-state'));
  panel.append(navigation);
  if (Object.keys(task.renders || {}).length === pages.length) {
    const review = el('details');
    review.open = true;
    review.append(el('summary', '第 4 步 · 核对标题正文'));
    const postTitle = field(review, '帖子标题', task.draft.title, 'input');
    const postBody = field(review, '帖子正文', task.draft.body);
    if (task.draft.missing_information?.length) review.append(el('p', '待核实：' + task.draft.missing_information.join('；'), 'review'));
    const postResolution = field(review, '待核实信息的处理说明', '');
    const postConfirmed = check(review, '我已审核正文与图片，确认未核实内容没有混入成品');
    review.append(button('确认成品，进入导出', async () => {
      if (dirty) throw new Error('本页文字有改动，请先保存');
      if (!postConfirmed.checked) throw new Error('请先确认审核');
      await mutate('/copy', { title: postTitle.value, body: postBody.value, confirmed: true, resolution: postResolution.value });
      screenId = 'publish';
      await render();
    }));
    panel.append(review);
  }
  grid.append(side, panel);
  screen.append(crumb, title, grid);
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
  left.append(el('div', 'STEP 04 · EXPORT', 'hero-kicker'), el('h1', '成品已确认，导出并记录反馈'), el('p', '发布账号授权暂未接入；你可以下载有序图文包，再由本人登录小红书发布。'));
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
  }, null, 2)));
  screen.append(trace);
}

async function renderHome() {
  const screen = $('home');
  screen.replaceChildren();
  const hero = el('div', undefined, 'hero');
  const content = el('div');
  content.append(el('div', 'WANG WEI MEDICAL BEAUTY · CONTENT ASSISTANT', 'hero-kicker'), el('h1'));
  content.querySelector('h1').append(document.createTextNode('王伟医美自媒体'), document.createElement('br'), document.createTextNode('一键发布小助手'));
  content.append(el('p', '从一个主题开始，和 AI 一起完成案例研究、拆解和图文共创，再由你本人发布。'));
  const start = el('button', undefined, 'start-tile');
  start.append(el('strong', '开始'), el('span', '创建一条新的内容'));
  start.addEventListener('click', () => {
    if (!token) openAccess();
    task = null;
    sessionStorage.removeItem('studio_task');
    chosenStrategy = '';
    strategyChosen = false;
    autoStarted = false;
    go('topics');
    render();
  });
  content.append(start, el('div', '工作台 · 案例、模型、导出和反馈均走当前 Agent 接口', 'review-note'));
  hero.append(content);
  screen.append(hero);
  if (token) {
    const library = el('details');
    library.open = true;
    library.append(el('summary', '案例资料管理'), el('p', '导入 xhs 导出的案例 ZIP。资料包只读保存，任务会记录使用的版本。', 'muted'));
    const file = el('input');
    file.type = 'file';
    file.accept = '.zip';
    file.id = 'bundleFile';
    const importButton = button('导入案例资料', async () => {
      if (!file.files[0]) throw new Error('请选择 xhs 导出的 ZIP');
      const body = new FormData();
      body.append('bundle', file.files[0]);
      await request('/bundles', 'POST', body);
      file.value = '';
      await refreshLists();
      await render();
      showToast('案例资料已导入');
    }, 'btn quiet');
    const bundleStatus = el('p', bundles.length ? '已有 ' + bundles.length + ' 个资料版本' : '还没有案例资料，请先导入 ZIP', 'muted');
    library.append(file, importButton, bundleStatus);
    screen.append(library);
    const resume = el('div', undefined, 'panel');
    resume.append(el('h2', '继续已有任务'));
    if (!tasks.length) {
      resume.append(el('p', '当前还没有保存的任务。', 'muted'));
    } else {
      const select = el('select');
      select.append(el('option', '选择一个任务继续'));
      tasks.forEach(row => {
        const option = el('option', (row.legacy ? '[历史] ' : '') + row.project + ' · ' + row.question);
        option.value = row.id;
        select.append(option);
      });
      select.addEventListener('change', () => run(async () => {
        if (!select.value) return;
        task = await request('/tasks/' + select.value);
        sessionStorage.setItem('studio_task', task.id);
        chosenStrategy = sessionStorage.getItem('studio_strategy_' + task.id) || '';
        strategyChosen = Boolean(chosenStrategy);
        screenId = task.schema_version !== 2 ? 'modes' : (task.copy_review?.confirmed ? 'publish' : task.draft ? 'create' : 'modes');
        await render();
      }));
      resume.append(select, el('p', '刷新页面后，任务仍从数据库恢复。', 'muted'));
    }
    resume.append(button('刷新任务与案例资料', async () => {
      await refreshLists();
      await render();
    }, 'btn quiet'));
    screen.append(resume);
  } else {
    screen.append(el('p', '请点击“连接工作台”后再开始，访问口令只保存在当前浏览器会话。', 'review'));
  }
}

async function renderTopics() {
  const screen = $('topics');
  screen.replaceChildren();
  const crumb = el('div', undefined, 'crumb');
  const home = el('button', '首页');
  home.addEventListener('click', () => { go('home'); render(); });
  crumb.append(home, document.createTextNode(' / 选择主题'));
  const heading = el('div', undefined, 'section-title');
  const left = el('div');
  left.append(el('div', 'STEP 01 · TOPIC', 'hero-kicker'), el('h1', '你想做什么主题？'), el('p', '当前先用 M22 跑通一条真实工作流。'));
  const back = el('button', '返回首页', 'back');
  back.addEventListener('click', () => { go('home'); render(); });
  heading.append(left, back);
  const grid = el('div', undefined, 'topic-grid');
  const m22 = el('button', undefined, 'topic');
  m22.append(el('span', '当前开放', 'topic-tag'), el('div', 'M22', 'topic-icon'), el('h2', 'M22'), el('p', '光子设备科普、到店咨询问题和门店内容创作'));
  m22.addEventListener('click', () => {
    go('modes');
    render();
    if (token && bundles.length && !task && !autoStarted) {
      autoStarted = true;
      window.setTimeout(() => run(startHighWorkflow), 100);
    }
  });
  const more = el('div', undefined, 'topic');
  more.style.opacity = '.45';
  more.append(el('div', '＋', 'topic-icon'), el('h2', '更多主题'), el('p', '后续可增加超皮秒、脱毛等项目'));
  grid.append(m22, more);
  screen.append(crumb, heading, grid);
}

async function render() {
  revokeUrls();
  ensureStatus();
  screens.forEach(screen => screen.replaceChildren());
  $('connectionState').textContent = token ? '已连接' : '未连接';
  if (screenId === 'home') await renderHome();
  if (screenId === 'topics') await renderTopics();
  if (screenId === 'modes') {
    if (task?.schema_version !== 2) await renderLegacy();
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

document.getElementById('connectBtn').addEventListener('click', openAccess);
document.getElementById('libraryBtn').addEventListener('click', async () => {
  if (!token) { openAccess(); return; }
  screenId = 'home';
  await render();
  const library = document.querySelector('#home details');
  if (library) { library.open = true; library.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
});
document.getElementById('closeAccess').addEventListener('click', closeAccess);
document.getElementById('saveAccess').addEventListener('click', () => run(() => connectWith($('accessToken').value)));
$('accessModal').addEventListener('click', event => { if (event.target === $('accessModal')) closeAccess(); });
document.getElementById('feedbackBtn').addEventListener('click', () => $('feedbackModal').classList.add('show'));
document.getElementById('closeFeedback').addEventListener('click', () => $('feedbackModal').classList.remove('show'));
$('feedbackModal').addEventListener('click', event => { if (event.target === $('feedbackModal')) $('feedbackModal').classList.remove('show'); });
document.getElementById('submitFeedback').addEventListener('click', () => run(submitFeedback));

if (token) {
  run(async () => {
    await refreshLists();
    const last = sessionStorage.getItem('studio_task');
    if (last) {
      try {
        task = await request('/tasks/' + last);
        chosenStrategy = sessionStorage.getItem('studio_strategy_' + task.id) || '';
        strategyChosen = Boolean(chosenStrategy);
        screenId = task.schema_version !== 2 ? 'modes' : (task.copy_review?.confirmed ? 'publish' : task.draft ? 'create' : 'modes');
      } catch (_) {
        sessionStorage.removeItem('studio_task');
      }
    }
    await render();
  });
} else {
  render();
}

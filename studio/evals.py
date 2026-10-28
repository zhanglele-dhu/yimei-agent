"""批量评测器（评测地基）：让"Bad Case 率"从口号变成可复现的统计。

评测范围：创建任务 → 检索 → 拆解 → 五步确认 → 草稿 → 逐页文字卡确认。
制卡渲染与导出不在此范围（纯本地确定性代码，无模型不确定性）。

三级 Bad Case 标签：
  L1 环节：retrieval / analyze / draft / make_page（坏在哪个部门）
  L2 现象：model_call_failed / contract_rejected / placeholder_echo /
           page_count_drift / quote_mismatch / degraded_vision / degraded_fallback
  L3 根因：model_capability / prompt_design / data_quality / token_budget / integration

状态口径（诚实分级，不把"降级成功"算成完美成功）：
  success           全程无异常、无降级、无自动修整
  success_degraded  完成了，但发生过降级/占位符清洗/大纲压缩等"系统兜底"
  bad_case          某环节硬失败，任务未能走完
真机基线（会产生真实 API 费用，先确认再跑）：
    .venv-studio/Scripts/python.exe -m studio.evals --questions evals/questions_m22.json
"""
import argparse
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

L1_STAGES = ('retrieval', 'analyze', 'draft', 'make_page')
L2_SYMPTOMS = ('model_call_failed', 'contract_rejected', 'placeholder_echo', 'page_count_drift',
               'quote_mismatch', 'degraded_vision', 'degraded_fallback')
L3_ROOTS = ('model_capability', 'prompt_design', 'data_quality', 'token_budget', 'integration')


def load_questions(path):
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    out = []
    for i, q in enumerate(raw, 1):
        out.append({'id': f'q{i:02d}', 'question': q['question'],
                    'audience': q.get('audience', '第一次了解的顾客')})
    return out


def classify(task, steps_ok, error=None):
    """按任务数据与失败记录打三级标签。返回 (status, l1, l2, l3, note)。"""
    l1 = next((s for s in reversed(L1_STAGES) if not steps_ok.get(s, True)), 'retrieval')
    l2, l3, notes = [], [], []
    failures = task.get('failures') or []
    if error is not None:
        text = str(error)
        if '1210' in text or '16384' in text:
            l2, l3 = ['model_call_failed'], ['token_budget']
        elif 'ValidationError' in type(error).__name__ or 'validation' in text.lower():
            l2, l3 = ['contract_rejected'], ['model_capability']
        else:
            l2, l3 = ['model_call_failed'], ['model_capability']
        for f in failures[-1:]:
            if f.get('error_type') == 'BadRequestError':
                l3 = ['token_budget']
        notes.append(f'{l1} 环节失败：{text[:120]}')
        return 'bad_case', l1, l2 or ['model_call_failed'], l3 or ['model_capability'], notes

    if not task.get('case'):
        return 'bad_case', 'retrieval', ['degraded_fallback'], ['data_quality'], ['没有匹配案例（题与库不匹配或数据不足）']

    basis = task.get('analysis_basis') or ''
    if '降级' in basis:
        l2.append('degraded_vision')
        l3.append('model_capability')
        notes.append('视觉轨失败，已降级文字轨完成拆解')
    polish = task.get('analysis_polish') or []
    for n in polish:
        if '占位' in n:
            l2.append('placeholder_echo'); l3.append('prompt_design')
        if '压缩' in n or '超出' in n:
            l2.append('page_count_drift'); l3.append('model_capability')
        notes.append(n)
    if failures:
        kinds = {f.get('action') for f in failures}
        if 'generate_background' in kinds:
            l2.append('degraded_fallback'); l3.append('integration')
            notes.append('底图生成失败已降级')
    if l2:
        return 'success_degraded', l1, l2, list(dict.fromkeys(l3)), notes
    return 'success', l1, [], [], ['全程无异常']


def run_suite(api_module, questions, token, generation_mode='model'):
    """依次跑题集。api_module 需已按目标环境完成初始化（含 TestClient）。"""
    from fastapi.testclient import TestClient
    client = TestClient(api_module.app)
    client.headers['Authorization'] = 'Bearer ' + token
    results = []
    for q in questions:
        rec = {'id': q['id'], 'question': q['question'], 'status': None,
               'l1': None, 'l2': [], 'l3': [], 'notes': [], 'case': None,'generation_mode':generation_mode}
        steps_ok = {'retrieval': False, 'analyze': False, 'draft': False, 'make_page': True}
        task = None
        try:
            r = client.post('/api/tasks', json={
                'project': 'M22', 'audience': q['audience'], 'question': q['question'],
                'facts': '', 'bundle_id': client.get('/api/bundles').json()[0]['bundle_id']})
            if r.status_code != 200:
                raise RuntimeError(f'create {r.status_code}: {r.text[:120]}')
            task = r.json()
            if not task.get('case'):
                steps_ok['retrieval'] = False
                raise RuntimeError('没有匹配案例')
            steps_ok['retrieval'] = True
            rec['case'] = task['case']['title']

            r = client.post(f"/api/tasks/{task['id']}/analysis-stage",
                            json={'revision': task['revision'], 'stage': 'retrieval', 'decision': 'accept'})
            if r.status_code != 200:
                raise RuntimeError(f'retrieval accept {r.status_code}: {r.text[:120]}')
            task = r.json()
            r = client.post(f"/api/tasks/{task['id']}/analyze", json={'revision': task['revision']})
            if r.status_code != 200:
                raise RuntimeError(f'analyze {r.status_code}: {r.text[:120]}')
            task = r.json()
            steps_ok['analyze'] = True

            for stage in ('language', 'visual', 'facts', 'writing'):
                r = client.post(f"/api/tasks/{task['id']}/analysis-stage",
                                json={'revision': task['revision'], 'stage': stage, 'decision': 'accept'})
                if r.status_code != 200:
                    raise RuntimeError(f'{stage} accept {r.status_code}: {r.text[:120]}')
                task = r.json()
            r = client.post(f"/api/tasks/{task['id']}/confirm-analysis",
                            json={'revision': task['revision'], 'analysis': task['analysis']})
            if r.status_code != 200:
                raise RuntimeError(f'confirm {r.status_code}: {r.text[:120]}')
            task = r.json()
            r = client.post(f"/api/tasks/{task['id']}/draft", json={'revision': task['revision']})
            if r.status_code != 200:
                raise RuntimeError(f'draft {r.status_code}: {r.text[:120]}')
            task = r.json()
            steps_ok['draft'] = True

            for page in task['draft']['pages']:
                kind = task['confirmed_analysis']['outline'][page['number'] - 1]['kind']
                if kind != 'text':
                    continue  # 实拍/对话页不在评测范围（无照片来源）
                r = client.post(f"/api/tasks/{task['id']}/pages/{page['number']}",
                                json={'revision': task['revision'], 'title': page['title'],
                                      'text': page['text'], 'confirmed': True, 'resolution': '评测自动确认',
                                      'generation_mode':generation_mode})
                if r.status_code != 200:
                    steps_ok['make_page'] = False
                    raise RuntimeError(f'page {page["number"]} {r.status_code}: {r.text[:120]}')
                task = r.json()
        except Exception as exc:  # 单题失败不阻断整批
            status, l1, l2, l3, notes = classify(task or {}, steps_ok, error=exc)
            rec.update(status=status, l1=l1, l2=l2, l3=l3, notes=notes,
                       detail=str(exc)[:200])
        else:
            status, l1, l2, l3, notes = classify(task, steps_ok)
            rec.update(status=status, l1=l1, l2=l2, l3=l3, notes=notes)
        results.append(rec)
    return results


def summarize(results):
    total = len(results) or 1
    counts = {'success': 0, 'success_degraded': 0, 'bad_case': 0}
    tags = {}
    for r in results:
        counts[r['status']] = counts.get(r['status'], 0) + 1
        for t in set(r['l2']):
            tags[t] = tags.get(t, 0) + 1
        for t in set(r['l3']):
            tags['L3:' + t] = tags.get('L3:' + t, 0) + 1
    return {'total': len(results), **counts,
            'bad_case_rate': round(counts['bad_case'] / total * 100, 1),
            'degraded_rate': round(counts['success_degraded'] / total * 100, 1),
            'tags': dict(sorted(tags.items(), key=lambda kv: -kv[1]))}


def write_report(results, out_dir, label=''):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).astimezone().strftime('%Y%m%d-%H%M%S')
    summary = summarize(results)
    payload = {'label': label, 'generated_at': stamp, 'summary': summary, 'results': results}
    (out / f'eval_{stamp}.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = [f'# 评测报告 {label} · {stamp}', '',
             f"- 题数 {summary['total']}｜success {summary['success']}｜"
             f"success_degraded {summary['success_degraded']}｜bad_case {summary['bad_case']}",
             f"- **Bad Case 率 {summary['bad_case_rate']}%**｜降级率 {summary['degraded_rate']}%",
             f"- 标签分布：{summary['tags']}", '',
             '| 题 | 状态 | 案例 | 标签 | 备注 |', '|---|---|---|---|---|']
    for r in results:
        tags = '、'.join(r['l2'] + ['L3:' + t for t in r['l3']]) or '-'
        lines.append(f"| {r['id']} {r['question'][:18]} | {r['status']} | "
                     f"{(r.get('case') or '-')[:16]} | {tags} | {'；'.join(r['notes'])[:80] or '-'} |")
    report = out / f'eval_{stamp}.md'
    report.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return report, summary


def main():
    parser = argparse.ArgumentParser(description='批量评测（真机，产生真实 API 费用）')
    parser.add_argument('--questions', default=str(ROOT / 'evals/questions_m22.json'))
    parser.add_argument('--limit', type=int, default=0, help='只跑前 N 题（0=全部）')
    parser.add_argument('--generation-mode', choices=('model','template'), default='model')
    args = parser.parse_args()

    questions = load_questions(args.questions)
    if args.limit:
        questions = questions[:args.limit]
    print(f'真机评测 {len(questions)} 题，成品模式：{args.generation_mode}。AI模式还会调用视觉设计与成图检查，会产生真实费用。')

    data_dir = Path(tempfile.mkdtemp(prefix='yimei-eval-'))
    os.environ['STUDIO_DATA_DIR'] = str(data_dir)
    os.environ.setdefault('STUDIO_ACCESS_TOKEN', 'eval-local-token-0123456789abcdef')
    bundles_src = ROOT / 'outputs/studio/bundles'
    if bundles_src.exists():
        shutil.copytree(bundles_src, data_dir / 'bundles', dirs_exist_ok=True)

    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    sys_path_setup()
    from studio import api

    results = run_suite(api, questions, os.environ['STUDIO_ACCESS_TOKEN'],generation_mode=args.generation_mode)
    report, summary = write_report(results, data_dir / 'evals', label='真机基线')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print('报告：', report)
    print('评测任务写在临时目录，不影响 outputs/studio 的真实任务数据。')


def sys_path_setup():
    import sys
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


if __name__ == '__main__':
    main()

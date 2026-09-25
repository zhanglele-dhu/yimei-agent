"""运行日志：每个任务一个 Markdown 文件，按时间记录"用户输入了什么、调用了什么模型、输出了什么"。

位置：outputs/studio/runlogs/
命名：创建时间_任务号_问题摘要.md —— 文件名按时间排序即是任务时间线。
读者两类：AI 回溯（排查问题的事实依据）与人工核对（看每步发生了什么）。

设计口径：
  - 只追加不修改，与任务数据库同源（数据库仍是权威记录，本文件是可读投影）；
  - 模型调用记录耗时/token/重试链，正文摘要截断防膨胀；
  - 每个事件一行时间戳标题，人眼扫时间线即可。
"""
import re
from datetime import datetime, timezone
from pathlib import Path


def _now():
    return datetime.now(timezone.utc).astimezone()


def _slug(text, n=24):
    text = re.sub(r'[\\/:*?"<>|\s]+', '', (text or ''))[:n]
    return text or '任务'


def file_for(task, data_root: Path) -> Path:
    """任务对应日志文件；文件名存在 task['runlog']，首次写入时定名并随任务持久化。"""
    folder = data_root / 'runlogs'
    folder.mkdir(parents=True, exist_ok=True)
    name = task.get('runlog')
    if name:
        return folder / name
    stamp = _now().strftime('%Y%m%d-%H%M%S')
    name = f"{stamp}_{task['id'][:8]}_{_slug(task.get('request', {}).get('question', ''))}.md"
    task['runlog'] = name
    return folder / name


def header(task):
    req = task.get('request', {})
    facts = req.get('facts', '') or ''
    facts_line = (f"门店事实（{len(facts)}字）：{facts[:200]}…" if len(facts) > 200 else f"门店事实：{facts}")
    return [f"# 运行日志 · {req.get('project', '')}",
            f"- 任务号：{task['id']}（创建于 {_now().strftime('%Y-%m-%d %H:%M:%S')}）",
            f"- 问题：{req.get('question', '')}",
            f"- 受众：{req.get('audience', '')}",
            f"- {facts_line}",
            f"- 案例包：{req.get('bundle_id', '')}", '']


def trace_summary(trace):
    """单次模型调用的可读摘要。"""
    if not isinstance(trace, dict):
        return str(trace)
    usage = trace.get('usage') or {}
    attempts = [a.get('outcome', '?') for a in trace.get('attempts', [])] or ['-']
    extra = f" 清洗占位符{trace.get('placeholder_sanitized')}" if trace.get('placeholder_sanitized') else ''
    return (f"{trace.get('provider', '?')} 耗时{(trace.get('elapsed_ms') or 0) / 1000:.1f}s "
            f"输入{usage.get('prompt_tokens', '?')}tok 输出{usage.get('completion_tokens', '?')}tok "
            f"重试链[{'→'.join(attempts)}]{extra}")


def event(task, data_root: Path, title: str, sections: dict):
    """追加一条事件。sections 的键是小标题（输入/调用/输出…），值为字符串或字符串列表。"""
    try:
        path = file_for(task, data_root)
        lines = header(task) if not path.exists() else []
        lines.append(f"\n## {_now().strftime('%H:%M:%S')} {title}\n")
        for head, body in (sections or {}).items():
            lines.append(f"**{head}**")
            if isinstance(body, str):
                lines.append(body)
            else:
                lines.extend(f"- {item}" for item in body)
        old = path.read_text(encoding='utf-8') if path.exists() else ''
        path.write_text(old + '\n'.join(lines) + '\n', encoding='utf-8')
    except OSError:
        pass  # 日志失败不阻断业务流程；数据库仍是最权威记录

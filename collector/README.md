# 图文参考笔记采集

双击 `collect_notes.bat`，输入搜索词；浏览器出现后手动登录，在终端按回车。搜索页确认结果已出现后，再按回车开始采集。

结果在 `data/reference_notes/`，CSV 可用 Excel 打开，JSON 保存完整字段和失败原因。包含标题、正文、原帖链接、作者、日期、标签、图片链接以及点赞/收藏/评论数。图片链接可能失效，程序不下载图片、不读取评论正文、不抓视频、不发布帖子、不调用模型。

计数缺失时 CSV 留空、JSON 为 null；页面显示“1.2万”等缩略数时保留原文，同时换算为近似整数。候选按搜索结果顺序处理，不承诺爆款排名或采满条数。未知类型跳过。遇到验证或访问限制停止，不自动绕过。

登录保存在独立 `data/collector_profile/`，每次仍需人工确认是否有效。不要分享该目录。无需复制原项目或 MCP 的 Cookie。

首次环境安装（本机已由助手执行时可跳过）：

```powershell
uv venv .venv-collector --python 3.13
uv pip install --python .venv-collector/Scripts/python.exe playwright
.\.venv-collector\Scripts\python.exe -m playwright install chromium
```

自定义运行：

```powershell
.\.venv-collector\Scripts\python.exe collect_notes.py --keyword "M22 科普" --count 10 --scrolls 5
```

本版基于已有采集代码与页面结构编写，仅完成离线验证。实际页面选择器和登录采集须在用户账号环境中验证；若结果为空，请查看 JSON 的 errors。

采集200条的目标命令（搜索滚动50次，不保证搜索结果足够）：

```powershell
.\.venv-collector\Scripts\python.exe collect_notes.py --keyword "M22 科普" --count 200 --scrolls 50
```

count支持1–200，scrolls支持1–100。数量为目标上限，图文数量不足、登录失效或访问限制均可能提前结束。

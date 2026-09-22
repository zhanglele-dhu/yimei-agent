"""Local-only launcher. Production starts uvicorn with an explicit access token."""
import os
import secrets
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
token_path = ROOT / 'outputs' / 'studio' / 'access_token.txt'
token_path.parent.mkdir(parents=True, exist_ok=True)
if not token_path.exists():
    token_path.write_text(secrets.token_urlsafe(32), encoding='utf-8')
os.environ.setdefault('STUDIO_ACCESS_TOKEN', token_path.read_text(encoding='utf-8').strip())

def _pause():
    """双击场景暂停窗口便于阅读；在无标准输入的环境（如后台启动）静默跳过。"""
    try:
        input('按回车键关闭本窗口...')
    except EOFError:
        pass


if __name__ == '__main__':
    import socket
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(('127.0.0.1', 8010))
    except OSError:
        # 端口被占：如果是本工作台已在运行（healthz 可识别），直接打开页面即可
        import json as _json
        try:
            with urllib.request.urlopen('http://127.0.0.1:8010/healthz', timeout=2) as resp:
                info = _json.load(resp)
            if resp.status == 200 and str(info.get('version', '')).startswith('cases-'):
                print('工作台已经在运行了，无需重复启动，直接为你打开页面。')
                opened = webbrowser.open(
                    'http://127.0.0.1:8010/?v=' + str(info['version']) + '#token=' + os.environ['STUDIO_ACCESS_TOKEN'])
                if not opened:
                    print('请手动在浏览器打开：http://127.0.0.1:8010')
                _pause()
                raise SystemExit(0)
        except Exception:
            pass
        print('端口 8010 被其他程序占用，且不是本工作台。')
        print('请关闭占用该端口的程序后重新双击 start_studio.bat。')
        _pause()
        raise SystemExit(1)
    finally:
        probe.close()

    import uvicorn
    print('门店拍摄与图文助手：http://127.0.0.1:8010')
    print('本机访问口令（粘贴到网页）：' + os.environ['STUDIO_ACCESS_TOKEN'])
    print('文字轨：DeepSeek。视觉/画图轨：智谱GLM-4V与CogView，在.env配置VISION_API_KEY后自动启用。')
    def open_when_ready():
        for _ in range(40):
            try:
                with urllib.request.urlopen('http://127.0.0.1:8010/healthz', timeout=1) as response:
                    import json
                    if response.status == 200 and json.load(response).get('version') == 'cases-20260922-1':
                        webbrowser.open('http://127.0.0.1:8010/?v=cases-20260922-1#token=' + os.environ['STUDIO_ACCESS_TOKEN'])
                        return
            except OSError:
                time.sleep(0.5)
    threading.Thread(target=open_when_ready, daemon=True).start()
    uvicorn.run('studio.api:app', host='127.0.0.1', port=8010)

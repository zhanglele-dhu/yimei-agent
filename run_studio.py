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

if __name__ == '__main__':
    import uvicorn
    print('门店拍摄与图文助手：http://127.0.0.1:8010')
    print('本机访问口令（粘贴到网页）：' + os.environ['STUDIO_ACCESS_TOKEN'])
    print('用户实拍只做本地排版；Anthropic模式可能发送参考原图做拆解。')
    def open_when_ready():
        for _ in range(40):
            try:
                with urllib.request.urlopen('http://127.0.0.1:8010/healthz', timeout=1) as response:
                    import json
                    if response.status == 200 and json.load(response).get('version') == 'cases-20260920-1':
                        webbrowser.open('http://127.0.0.1:8010/?v=cases-20260920-1#token=' + os.environ['STUDIO_ACCESS_TOKEN'])
                        return
            except OSError:
                time.sleep(0.5)
    threading.Thread(target=open_when_ready, daemon=True).start()
    uvicorn.run('studio.api:app', host='127.0.0.1', port=8010)

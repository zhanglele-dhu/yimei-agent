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
CURRENT_VERSION = 'cases-20261027-3'
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


def _runtime_logging():
    """Keep startup, HTTP errors and shutdown evidence after the console closes."""
    import copy
    from uvicorn.config import LOGGING_CONFIG
    directory = ROOT / 'outputs' / 'studio' / 'runtime'
    directory.mkdir(parents=True, exist_ok=True)
    config = copy.deepcopy(LOGGING_CONFIG)
    config['formatters']['runtime'] = {'format': '%(asctime)s %(levelname)s %(name)s %(message)s'}
    config['handlers']['runtime'] = {
        'class': 'logging.handlers.RotatingFileHandler',
        'filename': str(directory / 'studio.log'), 'encoding': 'utf-8',
        'maxBytes': 2_000_000, 'backupCount': 3, 'formatter': 'runtime',
    }
    config['loggers']['uvicorn']['handlers'].append('runtime')
    config['loggers']['uvicorn.access']['handlers'].append('runtime')
    return config


def _parse_listener_pid(netstat_text, port):
    """从 netstat -ano 输出里找监听指定端口的进程 PID（Windows 格式）；找不到返回 None。"""
    for line in netstat_text.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3] == 'LISTENING' and parts[1].endswith(':' + str(port)):
            try:
                return int(parts[4])
            except ValueError:
                continue
    return None


def _find_listener_pid(port):
    import subprocess
    try:
        out = subprocess.run(['netstat', '-ano'], capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return None
    return _parse_listener_pid(out, port)


def _stop_stale_instance(port):
    """关闭占用端口的旧版工作台进程（仅限本工作台场景调用）。返回是否成功。"""
    if os.name != 'nt':
        return False
    import subprocess
    pid = _find_listener_pid(port)
    if pid is None:
        return False
    try:
        result = subprocess.run(['taskkill', '/PID', str(pid), '/F'], capture_output=True, text=True, timeout=15)
        return result.returncode == 0
    except Exception:
        return False


if __name__ == '__main__':
    os.environ['STUDIO_LOCAL_SESSION'] = '1'
    import socket
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(('127.0.0.1', 8010))
    except OSError:
        # 端口被占：healthz 可识别时是本工作台。同版本→直接开页面；旧版本→自动升级。
        import json as _json
        upgraded = False
        try:
            with urllib.request.urlopen('http://127.0.0.1:8010/healthz', timeout=2) as resp:
                info = _json.load(resp)
            version = str(info.get('version', ''))
            if resp.status == 200 and version.startswith('cases-'):
                if version == CURRENT_VERSION:
                    print('工作台已经在运行了（同一版本），无需重复启动，直接为你打开页面。')
                    opened = webbrowser.open(
                        'http://127.0.0.1:8010/')
                    if not opened:
                        print('请手动在浏览器打开：http://127.0.0.1:8010')
                    _pause()
                    raise SystemExit(0)
                print(f'检测到旧版本（{version}）还在运行，正在自动升级到 {CURRENT_VERSION}。')
                print('任务数据保存在数据库里，升级不会丢失任何内容。')
                if _stop_stale_instance(8010):
                    time.sleep(1.0)
                    verify = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    try:
                        verify.bind(('127.0.0.1', 8010))
                    except OSError:
                        print('旧进程未能关闭，请手动关闭旧的启动窗口后重新双击 start_studio.bat。')
                        _pause()
                        raise SystemExit(1)
                    finally:
                        verify.close()
                    print('旧版本已关闭，继续启动新版本…')
                    upgraded = True
                else:
                    print('无法自动关闭旧进程（权限不足或系统不支持）。')
                    print('请手动关闭旧的启动窗口，然后重新双击 start_studio.bat。')
                    _pause()
                    raise SystemExit(1)
        except SystemExit:
            raise
        except Exception:
            pass
        if not upgraded:
            print('端口 8010 被其他程序占用，且不是本工作台。')
            print('请关闭占用该端口的程序后重新双击 start_studio.bat。')
            _pause()
            raise SystemExit(1)
    finally:
        probe.close()

    import uvicorn
    print('门店拍摄与图文助手：http://127.0.0.1:8010')
    print('正在打开创作页面，无需输入访问口令。')
    print('成品设计与检查：在网页“设置设计模型”中配置可用视觉模型。文字轨：DeepSeek。')
    def open_when_ready():
        for _ in range(40):
            try:
                with urllib.request.urlopen('http://127.0.0.1:8010/healthz', timeout=1) as response:
                    import json
                    if response.status == 200 and json.load(response).get('version') == CURRENT_VERSION:
                        webbrowser.open('http://127.0.0.1:8010/')
                        return
            except OSError:
                time.sleep(0.5)
    threading.Thread(target=open_when_ready, daemon=True).start()
    uvicorn.run('studio.api:app', host='127.0.0.1', port=8010, log_config=_runtime_logging())

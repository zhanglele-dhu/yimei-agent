"""Flask application shell; feature APIs are registered as independent blueprints."""
import os
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory
from dotenv import load_dotenv
from .blueprints import register_blueprints

ROOT = Path(__file__).resolve().parents[1]
DIST = Path(__file__).parent / 'static' / 'vue-app'
load_dotenv(ROOT / '.env', override=False)
load_dotenv(Path(os.getenv('STUDIO_CARD_SETTINGS_FILE', str(ROOT / '.env.card-model'))), override=True)
VERSION = 'cases-20261104-vue1'


def create_app():
    app = Flask(__name__, static_folder=str(DIST), static_url_path='')
    app.config['MAX_CONTENT_LENGTH'] = 12 * 1024 * 1024
    register_blueprints(app)

    @app.get('/healthz')
    def health():
        return {'status':'ok', 'version':VERSION}

    @app.get('/api/local-session')
    def local_session():
        local_hosts = ('127.0.0.1', 'localhost', '::1')
        host = request.host.rsplit(':', 1)[0].strip('[]')
        if os.getenv('STUDIO_LOCAL_SESSION') != '1' or request.remote_addr not in local_hosts or host not in local_hosts or request.headers.get('X-Studio-Local') != '1':
            return jsonify({'error':'仅允许从本机页面打开'}),403
        token = os.getenv('STUDIO_ACCESS_TOKEN','')
        if len(token) < 24:
            return jsonify({'error':'本地访问口令配置无效'}),503
        return jsonify({'access_token':token})

    @app.get('/')
    def home():
        if not (DIST / 'index.html').exists():
            return '前端文件尚未构建，请在 frontend 目录运行 npm ci 和 npm run build。', 503
        return send_from_directory(DIST, 'index.html')

    @app.errorhandler(404)
    def spa_fallback(error):
        if request.path.startswith('/api/'):
            return jsonify({'error':'接口不存在。'}),404
        if (DIST / 'index.html').exists():
            return send_from_directory(DIST,'index.html')
        return '前端文件尚未构建。',404

    @app.after_request
    def security_headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        return response

    return app


app = create_app()

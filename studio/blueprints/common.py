from functools import wraps
import hmac
import os
from flask import jsonify, request


def auth_required(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        expected = 'Bearer ' + os.getenv('STUDIO_ACCESS_TOKEN', '')
        if not hmac.compare_digest(request.headers.get('Authorization', ''), expected):
            return jsonify({'error': '本机访问验证已失效，请刷新页面'}), 401
        return function(*args, **kwargs)
    return wrapped


def error_response(error, status=400):
    return jsonify({'error': str(error)}), status


def safe_error(error, limit=400):
    message = str(error)
    for name in ('DEEPSEEK_API_KEY', 'ARK_API_KEY', 'STUDIO_CARD_API_KEY'):
        secret = os.getenv(name, '')
        if secret:
            message = message.replace(secret, '[redacted]')
    return message[:limit]

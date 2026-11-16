"""功能分组的 Flask 蓝图：文本、大纲、图片、历史和设置。"""
from flask import Blueprint

from .content import content_blueprint
from .generation import generation_blueprint
from .history import history_blueprint
from .outline import outline_blueprint
from .settings import settings_blueprint


def register_blueprints(app):
    api = Blueprint('api', __name__, url_prefix='/api')
    for feature in (outline_blueprint, content_blueprint, generation_blueprint, history_blueprint, settings_blueprint):
        api.register_blueprint(feature)
    app.register_blueprint(api)

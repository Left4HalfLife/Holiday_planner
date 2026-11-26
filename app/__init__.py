import os
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from . import database
from .validation import ValidationError


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE=os.environ.get(
            "DATABASE_PATH", str(Path(__file__).resolve().parent.parent / "data/holidays.db")
        ),
        LLM_BASE_URL=os.environ.get("LLM_BASE_URL", "http://host.docker.internal:1234/v1"),
        LLM_API_KEY=os.environ.get("LLM_API_KEY", "lm-studio"),
        LLM_MODEL=os.environ.get("LLM_MODEL", ""),
        MAX_CONTENT_LENGTH=256 * 1024,
        JSON_SORT_KEYS=False,
    )
    if test_config:
        app.config.update(test_config)
    database.init_app(app)

    from .main import bp

    app.register_blueprint(bp)

    @app.before_request
    def protect_writes():
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("Origin")
            expected = urlsplit(request.host_url)
            actual = urlsplit(origin) if origin else None
            if (
                request.headers.get("Sec-Fetch-Site") == "cross-site"
                or (actual and (actual.scheme, actual.netloc) != (expected.scheme, expected.netloc))
                or request.headers.get("X-Requested-With") != "HolidayPlanner"
                or not request.is_json
            ):
                return jsonify(error="A same-origin JSON request is required."), 403

    @app.after_request
    def secure_response(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(ValidationError)
    def validation_error(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(HTTPException)
    def http_error(error):
        if request.path.startswith("/api/"):
            return jsonify(error=error.description), error.code
        return error

    @app.errorhandler(Exception)
    def unexpected_error(error):
        app.logger.exception("Unhandled application error")
        return jsonify(error="An unexpected error occurred. Please try again."), 500

    return app

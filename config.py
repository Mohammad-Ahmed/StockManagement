import os


class Config:
    SECRET_KEY = os.environ.get(
        "SECRET_KEY",
        ""
    )

    LOGIN_USER_ID = os.environ.get(
        "LOGIN_USER_ID",
        "admin"
    )

    LOGIN_PASSWORD = os.environ.get(
        "LOGIN_PASSWORD",
        ""
    )

    SESSION_PERMANENT = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    SESSION_COOKIE_SECURE = (
        os.environ.get(
            "FLASK_ENV",
            "development"
        ).lower()
        == "production"
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False
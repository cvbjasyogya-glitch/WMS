import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:

    # ==========================
    # ENVIRONMENT
    # ==========================
    ENV = os.getenv("FLASK_ENV", "production")
    DEBUG = ENV == "development"
    IS_PRODUCTION = ENV == "production"

    # ==========================
    # SECURITY
    # ==========================
    SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret-key")

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = IS_PRODUCTION  # auto ON jika production

    PERMANENT_SESSION_LIFETIME = 60 * 60  # 1 jam

    # ==========================
    # DATABASE (SINGLE SOURCE)
    # ==========================
    DATABASE = os.getenv(
        "DATABASE_PATH",
        os.path.join(BASE_DIR, "database.db")
    )

    # ==========================
    # PAGINATION
    # ==========================
    PRODUCTS_PER_PAGE = 50

    # ==========================
    # STOCK
    # ==========================
    MIN_STOCK_ALERT = int(os.getenv("MIN_STOCK_ALERT", 10))

    # ==========================
    # SEARCH
    # ==========================
    SEARCH_LIMIT = int(os.getenv("SEARCH_LIMIT", 20))

    # ==========================
    # CHART
    # ==========================
    CHART_DAYS = int(os.getenv("CHART_DAYS", 7))
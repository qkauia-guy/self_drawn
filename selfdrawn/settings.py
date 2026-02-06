import os
import dj_database_url
from pathlib import Path

# 1. 基本路徑設定
BASE_DIR = Path(__file__).resolve().parent.parent

# 2. 環境變數讀取 (從 .env 載入)
# 建議確保在啟動 Gunicorn 前已 export 變數，或在服務中載入 EnvironmentFile
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    # 正式環境若沒設定 SECRET_KEY 必須報錯退出，確保安全性
    raise ValueError(
        "DJANGO_SECRET_KEY environment variable is required. Please set it in your environment."
    )

# 預設為 False，只有環境變數明確設為 "True" 時才開啟
DEBUG = os.environ.get("DEBUG", "False") == "True"

# 3. 網域與信任來源設定
ALLOWED_HOSTS_ENV = os.environ.get("ALLOWED_HOSTS")
if ALLOWED_HOSTS_ENV:
    ALLOWED_HOSTS = [host.strip() for host in ALLOWED_HOSTS_ENV.split(",")]
else:
    # 預設支援你的 DigitalOcean IP 與網域
    ALLOWED_HOSTS = ["yibahu-order.it.com", "167.99.64.109", "localhost", "127.0.0.1"]

CSRF_TRUSTED_ORIGINS_ENV = os.environ.get("CSRF_TRUSTED_ORIGINS")
if CSRF_TRUSTED_ORIGINS_ENV:
    CSRF_TRUSTED_ORIGINS = [
        origin.strip() for origin in CSRF_TRUSTED_ORIGINS_ENV.split(",")
    ]
else:
    # 預設信任你的正式網域 (HTTPS)
    CSRF_TRUSTED_ORIGINS = ["https://yibahu-order.it.com"]

# 4. 應用程式定義
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",  # WhiteNoise 輔助
    "django.contrib.staticfiles",
    "rest_framework",
    "ordering",  # 你的訂單邏輯
    "django_json_widget",  # 管理後台 UI
]

# 5. 中間件 (WhiteNoise 必須放在 Security 之後)
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "selfdrawn.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "selfdrawn.wsgi.application"

# 6. 資料庫設定 (優先讀取 DATABASE_URL)
# 支援 PostgreSQL (正式) 或 SQLite (開發)
DATABASES = {
    "default": dj_database_url.config(
        default=f'sqlite:///{BASE_DIR / "db.sqlite3"}', conn_max_age=600
    )
}

# 7. 語言與時區 (設定為台灣)
LANGUAGE_CODE = "zh-Hant"
TIME_ZONE = "Asia/Taipei"
USE_I18N = True
USE_TZ = True

# 8. 靜態檔案 (WhiteNoise 設定)
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [
    BASE_DIR / "selfdrawn" / "static",
]
# 啟用壓縮與快取，優化讀取速度
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# 9. 安全標頭與 HTTPS 設定 (當 DEBUG=False 時啟用)
if not DEBUG:
    # 強制將所有 HTTP 請求重定向至 HTTPS
    SECURE_SSL_REDIRECT = True
    # 透過 Nginx 轉發時，讓 Django 辨識 HTTPS
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

    # Cookie 安全性
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    # 瀏覽器防禦
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"

    # HSTS 啟動 (告訴瀏覽器這一年內都只能用 HTTPS 連線)
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# 10. Session 安全
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 3600  # 1 小時後過期
SESSION_SAVE_EVERY_REQUEST = True

# 11. REST Framework 設定 (加入 API 流量限制)
REST_FRAMEWORK = {
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {"anon": "100/hour", "user": "1000/hour"},  # 防止惡意刷單
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_REDIRECT_URL = "/owner/"

# settings.py

# ... (其他的設定)

# 12. Logging 設定 (讓 logger.info 能顯示在 Console)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",  # 設定為 INFO，這樣 logger.info 才會出現
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        # 這是您的 App 名稱，確保這裡能抓到 views.py 的 log
        "ordering": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": True,
        },
    },
}

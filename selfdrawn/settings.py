import os
import dj_database_url

from pathlib import Path

# 1. 基本路徑設定
BASE_DIR = Path(__file__).resolve().parent.parent

# 2. 安全設定
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("DJANGO_SECRET_KEY environment variable is required. Please set it in your environment.")

DEBUG = os.environ.get("DEBUG", "False") == "True"


# 3. 應用程式定義
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "ordering",
    "django_json_widget",
]

# 4. 中間件 (加入 WhiteNoise 修復 CSS)
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # <--- 必須在 SecurityMiddleware 之後
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

# 5. 資料庫 (目前使用 SQLite)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# 6. 密碼驗證
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# 7. 語言與時區
LANGUAGE_CODE = "zh-Hant"
TIME_ZONE = "Asia/Taipei"
USE_I18N = True
USE_TZ = True
LOGIN_REDIRECT_URL = "/owner/"

# 8. 靜態檔案設定 (修復 CSS 與 Icon 的核心)
STATIC_URL = "static/"

# 告訴 Django 收集所有靜態檔案到此資料夾，讓 WhiteNoise 讀取
STATIC_ROOT = BASE_DIR / "staticfiles"

# 你的原始靜態檔案存放位置
STATICFILES_DIRS = [
    BASE_DIR / "selfdrawn" / "static",
]

# 啟用 WhiteNoise 的壓縮與緩存功能
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ALLOWED_HOSTS 設定（支援環境變數）
ALLOWED_HOSTS_ENV = os.environ.get("ALLOWED_HOSTS")
if ALLOWED_HOSTS_ENV:
    ALLOWED_HOSTS = [host.strip() for host in ALLOWED_HOSTS_ENV.split(",")]
else:
    ALLOWED_HOSTS = ["localhost", "127.0.0.1", "self-drawn.onrender.com"]

# 信任的來源 (解決 CSRF 403 錯誤)
# 注意：一定要有 https:// 開頭
CSRF_TRUSTED_ORIGINS_ENV = os.environ.get("CSRF_TRUSTED_ORIGINS")
if CSRF_TRUSTED_ORIGINS_ENV:
    CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in CSRF_TRUSTED_ORIGINS_ENV.split(",")]
else:
    CSRF_TRUSTED_ORIGINS = [
        "https://self-drawn.onrender.com",
    ]


# ...

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# 如果有讀取到 DATABASE_URL 環境變數 (代表在 Render 上)，就改用 PostgreSQL
db_from_env = dj_database_url.config(conn_max_age=600)
DATABASES["default"].update(db_from_env)

# ==========================================
# 安全標頭與 HTTPS 設定
# ==========================================
if not DEBUG:
    # HTTPS 強制重定向
    SECURE_SSL_REDIRECT = True
    # Cookie 安全性
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # 瀏覽器安全標頭
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
    # HSTS (HTTP Strict Transport Security)
    SECURE_HSTS_SECONDS = 31536000  # 1 年
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    # 其他安全設定
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Session 安全性設定
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 3600  # 1 小時
SESSION_SAVE_EVERY_REQUEST = True  # 每次請求更新 session

# ==========================================
# REST Framework 設定（加入 Rate Limiting）
# ==========================================
REST_FRAMEWORK = {
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle'
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',  # 匿名使用者每小時 100 次請求
        'user': '1000/hour'  # 登入使用者每小時 1000 次請求
    },
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    # 預設權限設為 AllowAny，讓各個 ViewSet 自己決定權限
    # 這樣可以更靈活地控制每個端點的存取權限
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',
    ],
}

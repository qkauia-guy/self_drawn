import os
from pathlib import Path

# 1. 基本路徑設定
BASE_DIR = Path(__file__).resolve().parent.parent

# 2. 安全設定
SECRET_KEY = 'django-insecure-^_t%rbjt44ez9*qf7)bcp**=!gw&_404(bs1g4^4m8-$g*e6!_'
DEBUG = True  # 建議部署成功後改為 False
ALLOWED_HOSTS = ['*']

# 3. 應用程式定義
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'ordering',
]

# 4. 中間件 (加入 WhiteNoise 修復 CSS)
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # <--- 必須在 SecurityMiddleware 之後
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'selfdrawn.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'selfdrawn.wsgi.application'

# 5. 資料庫 (目前使用 SQLite)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# 6. 密碼驗證
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# 7. 語言與時區
LANGUAGE_CODE = 'zh-Hant'
TIME_ZONE = 'Asia/Taipei'
USE_I18N = True
USE_TZ = True
LOGIN_REDIRECT_URL = '/owner/'

# 8. 靜態檔案設定 (修復 CSS 與 Icon 的核心)
STATIC_URL = 'static/'

# 告訴 Django 收集所有靜態檔案到此資料夾，讓 WhiteNoise 讀取
STATIC_ROOT = BASE_DIR / "staticfiles"

# 你的原始靜態檔案存放位置
STATICFILES_DIRS = [
    BASE_DIR / "selfdrawn" / "static",
]

# 啟用 WhiteNoise 的壓縮與緩存功能
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
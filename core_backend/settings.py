import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv('SECRET_KEY')
DEBUG = os.getenv('DEBUG', 'False') == 'True'

ALLOWED_HOSTS = []

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'shop',  # Thêm dòng này vào
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core_backend.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'shop.context_processors.customer_info',
                'shop.context_processors.global_cart',
                'shop.context_processors.shop_global_settings',
            ],
        },
    },
]

WSGI_APPLICATION = 'core_backend.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# =============== SESSION SECURITY ===============

# Session timeout: 30 minutes of inactivity
SESSION_COOKIE_AGE = 1800

# Delete session when browser is closed
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# Use secure cookies only (HTTPS)
SESSION_COOKIE_SECURE = False  # Set to True in production with HTTPS

# Prevent JavaScript access to session cookie
SESSION_COOKIE_HTTPONLY = True

# Restrict cookie to same-site requests only (CSRF protection)
SESSION_COOKIE_SAMESITE = 'Strict'

# Use database for session storage (more secure than file-based)
SESSION_ENGINE = 'django.contrib.sessions.backends.db'

# Session key randomization
SESSION_SERIALIZER = 'django.contrib.sessions.serializers.JSONSerializer'

# =============== PASSWORD VALIDATION ===============

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {
            'min_length': 8,  # Minimum 8 characters
        }
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Password hashing algorithm
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.Argon2PasswordHasher',  # Better security
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
]

# =============== SECURITY HEADERS ===============

SECURE_HSTS_SECONDS = 31536000  # 1 year (production only)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_SSL_REDIRECT = False  # Set to True with HTTPS
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_SECURITY_POLICY = {
    "default-src": ("'self'",),
}

LANGUAGE_CODE = 'vi'

USE_I18N = True

# Chuyển giá trị này thành False để Django không ép dùng định dạng quốc tế (dấu phẩy)
USE_L10N = False

# Thêm dòng này để định dạng phân cách hàng nghìn bằng dấu chấm
NUMBER_GROUPING = 3
THOUSAND_SEPARATOR = '.'

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'shop', 'static'),
]
# Đường dẫn URL để truy cập vào ảnh (ví dụ: http://127.0.0.1:8000/media/products/abc.jpg)
MEDIA_URL = '/media/'

# Thư mục thực tế trên ổ cứng của bạn để lưu file ảnh
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

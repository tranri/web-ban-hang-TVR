from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-5#v0b04#m$09xmzjg3^tpj2ats4r%blxxxvgky131at%$&+9tx'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

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

# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

# Tìm các dòng này trong file settings.py và cập nhật giá trị:
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

import os

# Đường dẫn URL để truy cập vào ảnh (ví dụ: http://127.0.0.1:8000/media/products/abc.jpg)
MEDIA_URL = '/media/'

# Thư mục thực tế trên ổ cứng của bạn để lưu file ảnh
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

TELEGRAM_BOT_TOKEN = '8807230702:AAFsFeWiRzFO-ywiLrEu2bdAf8Or7JJgaNE'
TELEGRAM_CHAT_ID = '8690363581'

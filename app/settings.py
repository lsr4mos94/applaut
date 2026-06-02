from pathlib import Path
import os
import mimetypes
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(os.path.join(BASE_DIR, '.env'))

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'desenvolvimento-safe-key-123')

DEBUG = os.environ.get('DJANGO_DEBUG', 'True') == 'True'
ALLOWED_HOSTS = ['149.57.32.44', 'localhost', '127.0.0.1', 'app.lautbeer.com.br', '192.168.184.24', 'aroma-sullen-evaluate.ngrok-free.dev']

USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'http')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'app',
    'usuarios',
    'cadastros',
    'solicitacoes',
    'adm',
    'integracoes',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'app.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
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

WSGI_APPLICATION = 'app.wsgi.application'

PROTHEUS_CIEC = {
    'ENGINE': 'mssql',
    'NAME': 'MP12OFICIALP',
    'USER': os.environ.get('PROTHEUS_USER'),
    'PASSWORD': os.environ.get('PROTHEUS_PASSWORD'),
    'HOST': os.environ.get('PROTHEUS_HOST'),
    'PORT': '1433',
    'OPTIONS': {
        'driver': 'ODBC Driver 17 for SQL Server',
    },
}

PROTHEUS_WRP = {
    'ENGINE': 'mssql',
    'NAME': 'MP12OFICIALX',
    'USER': os.environ.get('PROTHEUS_USER'),
    'PASSWORD': os.environ.get('PROTHEUS_PASSWORD'),
    'HOST': os.environ.get('PROTHEUS_HOST'),
    'PORT': '1432',
    'OPTIONS': {
        'driver': 'ODBC Driver 17 for SQL Server',
    },
}

if DEBUG:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        },
        'protheus_ciec': PROTHEUS_CIEC,
        'protheus_wrp': PROTHEUS_WRP,
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('DB_NAME'),
            'USER': os.environ.get('DB_USER'),
            'PASSWORD': os.environ.get('DB_PASSWORD'),
            'HOST': os.environ.get('DB_HOST'),
            'PORT': os.environ.get('DB_PORT'),
        },
        'protheus_ciec': PROTHEUS_CIEC,
        'protheus_wrp': PROTHEUS_WRP,
    }

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

LANGUAGE_CODE = 'pt-br'

TIME_ZONE = 'America/Sao_Paulo'

USE_I18N = True

USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = r'E:\applaut\staticfiles'

STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = True

LOGIN_REDIRECT_URL = 'home'

LOGOUT_REDIRECT_URL = 'login'

LOGIN_URL = 'login'

EMAIL_HOST = 'saturno.onexdatacenter.com.br'
EMAIL_PORT = 465
EMAIL_USE_TLS = False
EMAIL_USE_SSL = True
EMAIL_HOST_USER = 'workflow@lautbeer.com.br'
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_PASSWORD')
DEFAULT_FROM_EMAIL = 'Workflow Laut Beer <workflow@lautbeer.com.br>'
SERVER_EMAIL = 'lorrane.ramos@lautbeer.com.br'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

mimetypes.add_type("image/png", ".png", True)
mimetypes.add_type("image/svg+xml", ".svg", True)

SITE_URL = "http://app.lautbeer.com.br"

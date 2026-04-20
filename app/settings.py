from pathlib import Path
import os
import mimetypes

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'django-insecure-2m%w6zvng#t3qf2h6!68$&-va)esch1#y&wg3xf4n&^ljlnc+o'

DEBUG = True
ALLOWED_HOSTS = ['149.57.32.44', 'localhost', '127.0.0.1', 'app.lautbeer.com.br', '192.168.184.24', 'aroma-sullen-evaluate.ngrok-free.dev']

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

DATABASES = {
    'default': {
        'ENGINE':   'django.db.backends.postgresql',
        'NAME':     'salesapp',
        'USER':     'postgres',
        'PASSWORD': 'Bw)reThOXV8mcel',
        'HOST':     '149.57.32.44',
        'PORT':     '5432',
    },
    'protheus_ciec': {
        'ENGINE': 'mssql',
        'NAME': 'MP12OFICIALP',
        'USER': 'user_app',
        'PASSWORD': 'q+E6XkpwwLsh',
        'HOST': '149.57.32.44',
        'PORT': '1433',
        'OPTIONS': {
            'driver': 'ODBC Driver 17 for SQL Server',
        },
    },
    'protheus_wrp': {
        'ENGINE': 'mssql',
        'NAME': 'MP12OFICIALX',
        'USER': 'user_app',
        'PASSWORD': 'q+E6XkpwwLsh',
        'HOST': '149.57.32.44',
        'PORT': '1432',
        'OPTIONS': {
            'driver': 'ODBC Driver 17 for SQL Server',
        },
    }
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

EMAIL_HOST =          'saturno.onexdatacenter.com.br'
EMAIL_PORT =          465
EMAIL_USE_TLS =       False
EMAIL_USE_SSL =       True
EMAIL_HOST_USER =     'workflow@lautbeer.com.br'
EMAIL_HOST_PASSWORD = 'cTavQf2HvtlKGh'
DEFAULT_FROM_EMAIL =  'Workflow Laut Beer <workflow@lautbeer.com.br>'
SERVER_EMAIL =        'lorrane.ramos@lautbeer.com.br'


DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

mimetypes.add_type("image/png", ".png", True)
mimetypes.add_type("image/svg+xml", ".svg", True)

SITE_URL = "http://applaut.com.br:8000"

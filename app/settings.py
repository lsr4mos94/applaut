from pathlib import Path
import os
import mimetypes
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(os.path.join(BASE_DIR, '.env'))

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'desenvolvimento-safe-key-123')

DEBUG = os.environ.get('DJANGO_DEBUG', 'True') == 'True'
ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'app.lautbeer.com.br', '192.168.184.24', '149.57.32.44', '149.57.32.233']

USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
# Endereços de onde o formulário de login pode ser enviado quando o site estiver em HTTPS
CSRF_TRUSTED_ORIGINS = ['https://app.lautbeer.com.br']

# Em produção (DEBUG=False) a chave secreta precisa vir do .env
if not DEBUG and SECRET_KEY == 'desenvolvimento-safe-key-123':
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured("Defina DJANGO_SECRET_KEY no .env do servidor.")

# Quando o site passar a usar HTTPS, basta DJANGO_HTTPS=True no .env
if os.environ.get('DJANGO_HTTPS', 'False') == 'True':
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
SESSION_COOKIE_HTTPONLY = True

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
        'driver': 'ODBC Driver 18 for SQL Server',
        'extra_params': 'TrustServerCertificate=yes;',
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
        'driver': 'ODBC Driver 18 for SQL Server',
        'extra_params': 'TrustServerCertificate=yes;',
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
EMAIL_TIMEOUT = 20  # segundos: o servidor de e-mail lento não trava a tela


def _emails(variavel, padrao):
    """Lista de e-mails do .env (separados por vírgula), com o valor atual como padrão."""
    return [e.strip() for e in os.environ.get(variavel, padrao).split(',') if e.strip()]


# Quem recebe cada aviso do sistema (dá para trocar no .env sem mexer no código)
EMAILS_CADASTRO_CLIENTES = _emails('EMAILS_CADASTRO_CLIENTES', 'cadastroclientes@lautbeer.com.br')
EMAILS_COBRANCA = _emails('EMAILS_COBRANCA', 'cobranca@lautbeer.com.br')
EMAILS_VERBA_NOVA = _emails('EMAILS_VERBA_NOVA', 'controladoria@lautbeer.com.br,alexsandra@lautbeer.com.br,financeiro@lautbeer.com.br')
EMAILS_VERBA_APROVADA = _emails('EMAILS_VERBA_APROVADA', 'contasapagar@lautbeer.com.br,alexsandra@lautbeer.com.br,keylla.oliveira@lautbeer.com.br')
EMAILS_BONIF_ACORDO_PENDENTE = _emails('EMAILS_BONIF_ACORDO_PENDENTE', 'admcomercial@lautbeer.com.br')
EMAILS_BONIF_NEGOCIACAO = _emails('EMAILS_BONIF_NEGOCIACAO', 'wellington@lautbeer.com.br')
EMAILS_BONIF_SAC = _emails('EMAILS_BONIF_SAC', 'admcomercial@lautbeer.com.br')
EMAILS_BONIF_CHOPP = _emails('EMAILS_BONIF_CHOPP', 'adm1@lautbeer.com.br')
EMAILS_BONIF_GERAL = _emails('EMAILS_BONIF_GERAL', 'admcomercial@lautbeer.com.br')
SERVER_EMAIL = 'lorrane.ramos@lautbeer.com.br'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

mimetypes.add_type("image/png", ".png", True)
mimetypes.add_type("image/svg+xml", ".svg", True)

SITE_URL = os.environ.get('SITE_URL', "http://app.lautbeer.com.br")

# Integração WhatsApp (Zenvia): o token fica só no .env
ZENVIA_API_TOKEN = os.environ.get('ZENVIA_API_TOKEN', '')
ZENVIA_REMETENTE = os.environ.get('ZENVIA_REMETENTE', '553190004411')
ZENVIA_DESTINO_PLANTAO = os.environ.get('ZENVIA_DESTINO_PLANTAO', '5531998357400')
ZENVIA_TEMPLATE_PLANTAO = os.environ.get('ZENVIA_TEMPLATE_PLANTAO', '358e7517-8beb-4161-af5f-8086fe7c6c91')
# Chave que a Zenvia envia no cabeçalho X-API-KEY ao chamar o webhook de plantão
WEBHOOK_PLANTAO_TOKEN = os.environ.get('WEBHOOK_PLANTAO_TOKEN', '')

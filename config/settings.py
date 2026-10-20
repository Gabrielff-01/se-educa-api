"""
Configurações do projeto SE Educa API.

Tudo que muda entre o seu PC e o servidor (senha do banco, chave secreta, DEBUG...)
vem de VARIÁVEIS DE AMBIENTE. No seu PC nada precisa ser configurado: os valores
padrão abaixo já funcionam com o SQLite. No Render, as variáveis ficam no painel
(veja o render.yaml e o .env.example).
"""

import os
from datetime import timedelta
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Se existir um arquivo .env na raiz do projeto, as variáveis dele são carregadas.
# Ele é opcional e NÃO vai pro Git (está no .gitignore).
load_dotenv(BASE_DIR / ".env")


def env_lista(nome, padrao=""):
    """Lê uma variável com vários valores separados por vírgula. Ex.: "a.com,b.com"."""
    return [item.strip() for item in os.environ.get(nome, padrao).split(",") if item.strip()]


# DEBUG mostra os erros detalhados. Ótimo no seu PC, perigoso no servidor.
DEBUG = os.environ.get("DEBUG", "True") == "True"

# Chave usada para assinar sessões e tokens. No servidor ela vem do Render.
SECRET_KEY = os.environ.get("SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError("Defina a variável SECRET_KEY no servidor.")
    SECRET_KEY = "django-insecure-so-para-desenvolvimento-local"

ALLOWED_HOSTS = ["localhost", "127.0.0.1"] + env_lista("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env_lista("CSRF_TRUSTED_ORIGINS")

# O Render informa sozinho o endereço do serviço (ex.: se-educa-api.onrender.com).
RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_EXTERNAL_HOSTNAME}")


# Aplicativos instalados

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Bibliotecas de fora
    "rest_framework",
    "corsheaders",
    # Apps do SE Educa
    "contas",
    "rede",
    "regulacao",
    "calendario",
    "rh",
    "academico",
    "auditoria",
    "solicitacoes",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # serve o CSS do admin no Render
    "corsheaders.middleware.CorsMiddleware",  # tem que vir antes do CommonMiddleware
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

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

WSGI_APPLICATION = "config.wsgi.application"


# Banco de dados
# Sem DATABASE_URL usa o SQLite do seu PC. No Render, DATABASE_URL aponta pro Neon
# (PostgreSQL), no formato postgresql://usuario:senha@endereco/banco?sslmode=require

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
    )
}


# Senhas

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Usuário customizado do SE Educa (precisa existir ANTES da primeira migration)
AUTH_USER_MODEL = "contas.Usuario"


# Idioma e fuso horário

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Maceio"  # o fuso de Sergipe (sem horário de verão)
USE_I18N = True
USE_TZ = True


# Arquivos estáticos (CSS e JS do admin)
# No servidor, o "collectstatic" junta tudo em staticfiles/ e o WhiteNoise entrega.

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}


# E-mail (por enquanto só aparece no terminal)

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
    },
}


# API (Django REST Framework)

REST_FRAMEWORK = {
    # Quem é o usuário: o token JWT (React) ou a sessão do admin (navegador).
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    # Por padrão, tudo exige login. Cada tela da API diz quem pode mudar o quê.
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "EXCEPTION_HANDLER": "config.api.tratar_erros",
}

# Token JWT ("crachá"): o de acesso vale 8 horas, um turno de trabalho.
# O de renovação vale 7 dias e serve pra pegar um novo de acesso sem digitar a senha.
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=8),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
}


# CORS: quais sites podem chamar a API pelo navegador.
# Sem isso, o navegador bloqueia o React (em outro endereço) de falar com o Django.

CORS_ALLOWED_ORIGINS = [
    "http://localhost:8443",  # npm run dev do se-educa-front
    "http://127.0.0.1:8443",
    "http://localhost:5173",  # porta padrão do Vite, se um dia mudar
] + env_lista("CORS_ALLOWED_ORIGINS")
# Versões de Preview da Vercel mudam de endereço a cada push: liberamos pelo padrão do nome.
CORS_ALLOWED_ORIGIN_REGEXES = [r"^https://se-educa-front[a-z0-9-]*\.vercel\.app$"]


# Segurança extra quando está no servidor (HTTPS)

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

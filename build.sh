#!/usr/bin/env bash
# Roda no Render a cada deploy (é o "Build Command": bash build.sh).
set -o errexit  # se um comando falhar, o deploy para (e o site antigo continua no ar)

pip install -r requirements.txt
python manage.py collectstatic --no-input  # junta o CSS/JS do admin em staticfiles/
python manage.py migrate                   # cria/atualiza as tabelas no Neon
python manage.py popular_demo              # usuários de demonstração (aluno1/aluno...)

# Superusuário do admin: só se as variáveis DJANGO_SUPERUSER_* estiverem no Render.
# O "|| true" ignora o erro quando ele já existe.
if [ -n "$DJANGO_SUPERUSER_USERNAME" ]; then
  python manage.py createsuperuser --no-input || true
fi

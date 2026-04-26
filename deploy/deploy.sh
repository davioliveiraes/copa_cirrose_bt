#!/bin/bash
set -e

VPS_USER="${VPS_USER:-root}"
VPS_IP="${VPS_IP:?Informe o IP da VPS. Ex: VPS_IP=1.2.3.4 bash deploy/deploy.sh}"
PROJECT_DIR="${PROJECT_DIR:-/home/copa_cirrose_bt}"

echo "Iniciando deploy..."

# Envia codigo (exclui arquivos locais)
ssh "$VPS_USER@$VPS_IP" "mkdir -p $PROJECT_DIR"
rsync -avz \
    --exclude 'venv' \
    --exclude '__pycache__' \
    --exclude '.env' \
    --exclude 'db.sqlite3' \
    --exclude 'staticfiles' \
    --exclude '.git' \
    ./ "$VPS_USER@$VPS_IP:$PROJECT_DIR/"

# Setup remoto
ssh "$VPS_USER@$VPS_IP" "PROJECT_DIR='$PROJECT_DIR' bash -s" << 'ENDSSH'
set -e
cd "$PROJECT_DIR"

# Dependencias do sistema
apt update
apt install -y python3-pip python3-venv nginx

# Venv + deps Python
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# .env
if [ ! -f .env ]; then
    SECRET=$(python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())")
    cat > .env <<EOF
SECRET_KEY=$SECRET
DEBUG=False
ALLOWED_HOSTS=*
FORCE_SCRIPT_NAME=/copa_cirrose_bt
EOF
fi

set_env_var() {
    KEY="$1"
    VALUE="$2"
    if grep -q "^${KEY}=" .env; then
        sed -i "s|^${KEY}=.*|${KEY}=${VALUE}|" .env
    else
        printf '%s=%s\n' "$KEY" "$VALUE" >> .env
    fi
}

set_env_var DEBUG False
set_env_var ALLOWED_HOSTS '*'
set_env_var FORCE_SCRIPT_NAME /copa_cirrose_bt

# Migrations + collectstatic
python manage.py migrate --noinput
python manage.py collectstatic --noinput

# Permissoes
chown -R www-data:www-data "$PROJECT_DIR"

# Systemd + Nginx
cp deploy/gunicorn.service /etc/systemd/system/copa.service
cp deploy/nginx.conf /etc/nginx/sites-available/copa
ln -sf /etc/nginx/sites-available/copa /etc/nginx/sites-enabled/copa
rm -f /etc/nginx/sites-enabled/default

systemctl daemon-reload
systemctl enable copa
systemctl restart copa
nginx -t && systemctl reload nginx

ufw allow 80/tcp 2>/dev/null || true

echo "Deploy concluido!"
ENDSSH

echo ""
echo "Aplicacao no ar em: http://$VPS_IP/copa_cirrose_bt/"

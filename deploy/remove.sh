#!/bin/bash
set -e

VPS_USER="${VPS_USER:-root}"
VPS_IP="${VPS_IP:?Informe o IP da VPS. Ex: VPS_IP=1.2.3.4 bash deploy/remove.sh}"
PROJECT_DIR="${PROJECT_DIR:-/home/copa_cirrose_bt}"

echo "Removendo Copa Cirrose BT do servidor..."

ssh "$VPS_USER@$VPS_IP" "PROJECT_DIR='$PROJECT_DIR' bash -s" << 'ENDSSH'
set -e

systemctl stop copa 2>/dev/null || true
systemctl disable copa 2>/dev/null || true
rm -f /etc/systemd/system/copa.service
systemctl daemon-reload

rm -f /etc/nginx/sites-enabled/copa
rm -f /etc/nginx/sites-available/copa
nginx -t && systemctl reload nginx

rm -rf "$PROJECT_DIR"

echo "Removido!"
ENDSSH

echo ""
echo "Servidor limpo. Confirma em http://$VPS_IP — deve dar 404."

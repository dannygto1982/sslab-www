#!/bin/bash
# SSLAB Admin Platform - Deploy Script
set -e

DEPLOY_DIR="/opt/sslab-admin"

echo "=== SSLAB Admin Platform Deployment ==="

# Create directories
mkdir -p $DEPLOY_DIR/{data,uploads,static}

# Copy files
cp main.py config.py models.py auth.py requirements.txt $DEPLOY_DIR/

# Copy static frontend
cp static/index.html $DEPLOY_DIR/static/

# Setup Python venv
if [ ! -d "$DEPLOY_DIR/venv" ]; then
    echo "[+] Creating virtual environment..."
    python3 -m venv $DEPLOY_DIR/venv
fi

echo "[+] Installing dependencies..."
$DEPLOY_DIR/venv/bin/pip install -r $DEPLOY_DIR/requirements.txt -q

# Setup systemd service
cp sslab-admin.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable sslab-admin
systemctl restart sslab-admin

# Setup nginx
cp nginx_sslab_admin.conf /etc/nginx/sites-available/sslab-admin
ln -sf /etc/nginx/sites-available/sslab-admin /etc/nginx/sites-enabled/
# Remove default site if exists
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo ""
echo "=== Deployment Complete ==="
echo "Backend: http://127.0.0.1:8080"
echo "Frontend: http://$(curl -s ifconfig.me 2>/dev/null || echo 'YOUR_IP'):80"
echo "Login: admin / admin123"
systemctl status sslab-admin --no-pager -l

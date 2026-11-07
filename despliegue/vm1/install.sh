#!/bin/bash
# ---------------------------------------------------------------------------
# Instalador PortoCaribe para VM1 (debian3 / 192.168.137.54)
#
#   Monitor PortoCaribe  -> /opt/portocaribe-monitor   (usuario: monitor)
#   Portal de Clientes   -> /opt/portal                (usuario: portal)
#   Apache 2.4 + TLS     -> :443 proxy a 127.0.0.1:8080
#   Muestreo             -> timer systemd cada 5 min; CSV diario a las 23:59
#
# Uso (como root, desde cualquier copia del repositorio):
#     bash despliegue/vm1/install.sh [RAIZ_DEL_REPOSITORIO]
#
# Es idempotente: se puede volver a ejecutar para actualizar código o
# configuración sin perder datos (snapshots, JSONL, CSV ni portal.db).
# ---------------------------------------------------------------------------
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export DEBIAN_FRONTEND=noninteractive

BASE="$(cd "$(dirname "$0")" && pwd)"
RAIZ="$(cd "${1:-$BASE/../..}" && pwd)"
DATOS=/var/lib/portocaribe-monitor/datos
ENTRADAS=$DATOS/entradas/local
SSL_DIR=/etc/apache2/ssl
IP_PUBLICA="${IP_PUBLICA:-192.168.137.54}"

paso() { printf '\n=== %s ===\n' "$*"; }
[ -d "$RAIZ/monitor" ] && [ -d "$RAIZ/portal" ] || {
    echo "ERROR: $RAIZ no parece la raíz del repositorio (faltan monitor/ y portal/)"; exit 2; }

paso "1/12 Paquetes (apache2, openssl)"
apt-get update -qq
apt-get install -y --no-install-recommends apache2 openssl >/dev/null
apache2 -v | head -1

paso "2/12 Usuarios de servicio"
id monitor >/dev/null 2>&1 || useradd --system --user-group \
    --home-dir /var/lib/portocaribe-monitor --shell /usr/sbin/nologin monitor
id portal >/dev/null 2>&1 || useradd --system --user-group \
    --home-dir /var/lib/portal --shell /usr/sbin/nologin portal
# `adm` permite leer el journal (auth.log / kern.log) sin root
usermod -aG adm monitor
id monitor
id portal

paso "3/12 Directorios y permisos"
install -d -m 0755 /opt/portocaribe-monitor /opt/portal /etc/monitor /etc/portal
install -d -m 0755 /var/lib/portocaribe-monitor
install -d -m 0755 "$DATOS"
install -d -m 0755 -o root -g root "$DATOS/entradas" "$ENTRADAS"
install -d -m 0750 -o portal -g portal /var/lib/portal
chown -R monitor:monitor "$DATOS"

paso "4/12 Código de las aplicaciones (desde $RAIZ)"
rm -rf /opt/portocaribe-monitor/monitor /opt/portal/portal
cp -a "$RAIZ/monitor" /opt/portocaribe-monitor/monitor
cp -a "$RAIZ/portal" /opt/portal/portal
chown -R root:root /opt/portocaribe-monitor /opt/portal
find /opt/portocaribe-monitor /opt/portal -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

paso "5/12 Configuración y collector"
install -m 0644 "$BASE/etc/monitor.toml" /etc/monitor/monitor.toml
install -m 0644 "$BASE/etc/portal.toml"  /etc/portal/portal.toml
install -m 0755 "$BASE/usr/local/bin/portocaribe-snapshots-local" /usr/local/bin/portocaribe-snapshots-local

paso "6/12 Validación del monitor y del portal"
(cd /opt/portocaribe-monitor && \
    runuser -u monitor -- /usr/bin/python3 -m monitor validate --config /etc/monitor/monitor.toml) \
    || { echo "ERROR: configuración del monitor inválida"; exit 2; }
(cd /opt/portal && \
    runuser -u portal -- /usr/bin/python3 -m portal --config /etc/portal/portal.toml --check)

paso "7/12 Certificado TLS autofirmado"
if [ ! -s "$SSL_DIR/portal.crt" ] || [ ! -s "$SSL_DIR/portal.key" ]; then
    install -d -m 0750 "$SSL_DIR"
    openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
        -keyout "$SSL_DIR/portal.key" -out "$SSL_DIR/portal.crt" \
        -subj "/C=CO/ST=Bolivar/L=Cartagena/O=PortoCaribe S.A./CN=portal.portocaribe.local" \
        -addext "subjectAltName=DNS:portal.portocaribe.local,DNS:localhost,IP:127.0.0.1,IP:$IP_PUBLICA" \
        -addext "basicConstraints=critical,CA:FALSE" \
        -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
        -addext "extendedKeyUsage=serverAuth" 2>/dev/null
    chmod 0640 "$SSL_DIR/portal.key"
    chown root:www-data "$SSL_DIR/portal.key" "$SSL_DIR/portal.crt"
fi
openssl x509 -in "$SSL_DIR/portal.crt" -noout -subject -enddate

paso "8/12 Apache (módulos, sitio, TLS)"
a2enmod -q ssl proxy proxy_http headers rewrite
install -m 0644 "$BASE/etc/apache-portal.conf" /etc/apache2/sites-available/portal-portocaribe.conf
a2ensite -q portal-portocaribe
a2dissite -q 000-default 2>/dev/null || true
apache2ctl configtest
systemctl enable apache2 >/dev/null
systemctl restart apache2

paso "9/12 Firewall (ufw): 80 y 443"
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
    ufw allow 80/tcp  comment 'Portal PortoCaribe (redireccion a HTTPS)' >/dev/null
    ufw allow 443/tcp comment 'Portal PortoCaribe (HTTPS)' >/dev/null
    ufw status | sed -n '1,10p'
else
    echo "ufw inactivo o ausente: no se modifica el firewall"
fi

paso "10/12 Unidades systemd"
install -m 0644 "$BASE/systemd/portal.service" \
                 "$BASE/systemd/portocaribe-monitor.service" \
                 "$BASE/systemd/portocaribe-export.service" /etc/systemd/system/
install -m 0644 "$BASE/systemd/portocaribe-muestreo.timer" \
                 "$BASE/systemd/portocaribe-cierre.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now portal.service
systemctl enable --now portocaribe-muestreo.timer portocaribe-cierre.timer

paso "11/12 Nombre local del portal"
grep -q 'portal.portocaribe.local' /etc/hosts || echo "127.0.0.1 portal.portocaribe.local" >> /etc/hosts

paso "12/12 Verificación rápida"
sleep 2
systemctl is-active portal apache2
/usr/local/bin/portocaribe-snapshots-local
cd /opt/portocaribe-monitor
runuser -u monitor -- /usr/bin/python3 -m monitor run --config /etc/monitor/monitor.toml || true
runuser -u monitor -- /usr/bin/python3 -m monitor export --config /etc/monitor/monitor.toml || true
echo
echo "Instalación completada."

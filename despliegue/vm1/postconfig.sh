#!/bin/bash
# ---------------------------------------------------------------------------
# Post-configuración de VM1 tras crear VM2:
#   - clave ed25519 del monitor + known_hosts de VM2
#   - pgpass del rol PostgreSQL
#   - captura DSCP de QoS (tcpdump cada 5 min)
#   - monitor.toml e inventario.csv de la topología nueva
#
# Uso (root, con la copia del repo en /tmp/pa6desp):
#   bash despliegue/vm1/postconfig.sh [RAIZ]
# ---------------------------------------------------------------------------
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

BASE="$(cd "$(dirname "$0")" && pwd)"
RAIZ="$(cd "${1:-$BASE/../..}" && pwd)"
IP_VM2="${IP_VM2:-192.168.100.59}"
DATOS=/var/lib/portocaribe-monitor/datos
PUB_LOCAL=/tmp/monitor_key.pub
PG_TMP=/tmp/pg_monitor.pass

paso() { printf '\n=== %s ===\n' "$*"; }

paso "1/6 Configuración e inventario"
install -m 0644 "$BASE/etc/monitor.toml" /etc/monitor/monitor.toml
install -m 0644 "$RAIZ/inventario.csv" /etc/monitor/inventario.csv

paso "2/6 Código del monitor"
if [ -d "$RAIZ/monitor" ]; then
  rm -rf /opt/portocaribe-monitor/monitor
  cp -a "$RAIZ/monitor" /opt/portocaribe-monitor/monitor
  chown -R root:root /opt/portocaribe-monitor
  find /opt/portocaribe-monitor -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
fi

paso "3/6 Clave SSH del monitor"
install -d -m 0755 /etc/monitor
if [ ! -s /etc/monitor/id_ed25519 ]; then
  ssh-keygen -q -t ed25519 -N '' -C 'monitor@vm1' -f /etc/monitor/id_ed25519
fi
chown monitor:monitor /etc/monitor/id_ed25519
chmod 0600 /etc/monitor/id_ed25519
ssh-keygen -y -f /etc/monitor/id_ed25519 > "$PUB_LOCAL"
chmod 0644 "$PUB_LOCAL"
echo "Clave pública del monitor lista en $PUB_LOCAL"

paso "4/6 known_hosts de VM2"
if ! ssh-keyscan -T 5 -t ed25519 "$IP_VM2" > /etc/monitor/known_hosts 2>/dev/null || [ ! -s /etc/monitor/known_hosts ]; then
  echo "AVISO: no se pudo obtener la huella de $IP_VM2"
else
  chmod 0644 /etc/monitor/known_hosts
  ssh-keygen -lf /etc/monitor/known_hosts
fi

paso "5/6 pgpass"
if [ -s "$PG_TMP" ]; then
  install -m 0600 -o monitor -g monitor /dev/null /etc/monitor/pgpass
  printf '%s:5432:portocaribe:monitor:%s\n' "$IP_VM2" "$(tr -d '\n' < "$PG_TMP")" > /etc/monitor/pgpass
  chown monitor:monitor /etc/monitor/pgpass
  chmod 0600 /etc/monitor/pgpass
  echo "pgpass instalado para monitor@$IP_VM2"
else
  echo "AVISO: no existe $PG_TMP; el módulo de BD quedará en ERROR hasta copiarlo"
fi

paso "6/6 QoS, servicio y verificación"
install -d -m 0755 -o monitor -g monitor "$DATOS/capturas"
install -m 0644 "$BASE/systemd/portocaribe-monitor.service" /etc/systemd/system/
install -m 0644 "$BASE/systemd/portocaribe-qos-captura.service" \
                 "$BASE/systemd/portocaribe-qos-captura.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now portocaribe-qos-captura.timer

cd /opt/portocaribe-monitor
runuser -u monitor -- /usr/bin/python3 -m monitor validate --config /etc/monitor/monitor.toml

echo
echo "Post-configuración de VM1 completada."

#!/bin/bash
# Prueba de la recolección SSH desde VM1 hacia VM2 (como usuario monitor).
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
cd /opt/portocaribe-monitor
echo "== clave e identificadores =="
ls -l /etc/monitor/id_ed25519 /etc/monitor/known_hosts /etc/monitor/pgpass
echo "== recolectar vm2 =="
runuser -u monitor -- /usr/bin/python3 -m monitor recolectar --config /etc/monitor/monitor.toml --host vm2
echo "rc=$?"
echo "== snapshots =="
ls -la /var/lib/portocaribe-monitor/datos/entradas/vm2 2>&1
echo "== prueba directa ssh (receta apache) =="
runuser -u monitor -- ssh -i /etc/monitor/id_ed25519 -o BatchMode=yes -o StrictHostKeyChecking=yes \
  -o UserKnownHostsFile=/etc/monitor/known_hosts -o ConnectTimeout=5 monitor@192.168.100.59 apache
echo "rc_ssh=$?"

#!/bin/bash
# Corrida real del monitor en VM1 con todos los módulos habilitados.
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PAGER=cat PSQL_PAGER=cat SYSTEMD_PAGER=cat
cd /opt/portocaribe-monitor
set -a
. /etc/monitor/ami.env
set +a
echo "== prueba psql como monitor =="
runuser -u monitor -- env PGPASSFILE=/etc/monitor/pgpass \
  psql -w -tAc "SELECT 1" -h 192.168.100.59 -p 5432 -U monitor -d portocaribe
echo "== corrida =="
systemctl start --no-block portocaribe-qos-captura.service || true
sleep 2
runuser -u monitor -- env ASTERISK_AMI_SECRET="$ASTERISK_AMI_SECRET" \
  /usr/bin/python3 -m monitor run --config /etc/monitor/monitor.toml --verbose
echo "rc=$?"
echo "== último JSONL =="
archivo="$(ls -t /var/lib/portocaribe-monitor/datos/raw/*/*.jsonl 2>/dev/null | head -1)"
echo "$archivo"
python3 - "$archivo" <<'EOF'
import json, sys, collections
ruta = sys.argv[1]
filas = [json.loads(l) for l in open(ruta, encoding="utf-8") if l.strip()]
print("filas:", len(filas))
print(collections.Counter(f["estado"] for f in filas))
for f in filas:
    print(f"{f['modulo']:10} {f['estado']:9} {str(f['recurso_target'])[:24]:24} {str(f['detalle'])[:80]}")
EOF

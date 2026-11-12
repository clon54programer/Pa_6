#!/bin/bash
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
cd /opt/portocaribe-monitor
set -a; . /etc/monitor/ami.env; set +a
runuser -u monitor -- env ASTERISK_AMI_SECRET="$ASTERISK_AMI_SECRET" \
  /usr/bin/python3 -m monitor run --config /etc/monitor/monitor.toml --solo dhcp
archivo="$(ls -t /var/lib/portocaribe-monitor/datos/raw/*/*.jsonl | head -1)"
python3 - "$archivo" <<'PY'
import json, sys
for linea in open(sys.argv[1], encoding="utf-8"):
    fila = json.loads(linea)
    print(fila["modulo"], fila["estado"], "|", fila["detalle"])
PY

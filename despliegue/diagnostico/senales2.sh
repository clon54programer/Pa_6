#!/bin/bash
# SIGTERM enviado directamente al proceso Python del monitor.
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
cd /opt/portocaribe-monitor
set -a; . /etc/monitor/ami.env; set +a
runuser -u monitor -- env ASTERISK_AMI_SECRET="$ASTERISK_AMI_SECRET" \
  /usr/bin/python3 -m monitor run --config /etc/monitor/monitor.toml > /tmp/senal.out 2>&1 &
rpid=$!
sleep 9
cpid="$(pgrep -P "$rpid" | head -1)"
echo "python pid=$cpid"
kill -TERM "$cpid" 2>/dev/null
wait "$rpid"; rc=$?
echo "rc=$rc"
tail -3 /tmp/senal.out
archivo="$(ls -t /var/lib/portocaribe-monitor/datos/raw/*/*.jsonl | head -1)"
echo "JSONL: $archivo"
python3 - "$archivo" <<'PY'
import json, sys, collections
filas = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
print("filas:", len(filas), collections.Counter(f["estado"] for f in filas))
for f in filas:
    print(" ", f["modulo"], f["estado"], f["detalle"][:60])
PY

#!/bin/bash
# Evidencia de señales (SIGTERM) y de logs JSON.
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
cd /opt/portocaribe-monitor
set -a; . /etc/monitor/ami.env; set +a

echo "== 1) SIGTERM durante una corrida =="
runuser -u monitor -- env ASTERISK_AMI_SECRET="$ASTERISK_AMI_SECRET" \
  /usr/bin/python3 -m monitor run --config /etc/monitor/monitor.toml > /tmp/senal.out 2>&1 &
pid=$!
sleep 4
kill -TERM "$pid" 2>/dev/null
wait "$pid"; rc=$?
echo "rc=$rc"
tail -4 /tmp/senal.out
echo "último JSONL:"
ls -t /var/lib/portocaribe-monitor/datos/raw/*/*.jsonl | head -1

echo
echo "== 2) --json-logs (simulación en /tmp) =="
sed 's#^directorio_datos = .*#directorio_datos = "/tmp/simdatos"#' /etc/monitor/monitor.toml > /tmp/simconfig.toml
rm -rf /tmp/simdatos
runuser -u monitor -- /usr/bin/python3 -m monitor run --simulate --solo camaras --json-logs \
  --config /tmp/simconfig.toml 2>&1 | head -6

echo
echo "== 3) validación con inventario y NTP =="
runuser -u monitor -- /usr/bin/python3 -m monitor validate --config /etc/monitor/monitor.toml

#!/bin/bash
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
cd /opt/portocaribe-monitor
a=$(sha256sum /var/lib/portocaribe-monitor/datos/csv/metricas_$(date +%F).csv | cut -d' ' -f1)
runuser -u monitor -- /usr/bin/python3 -m monitor export --config /etc/monitor/monitor.toml >/dev/null
b=$(sha256sum /var/lib/portocaribe-monitor/datos/csv/metricas_$(date +%F).csv | cut -d' ' -f1)
runuser -u monitor -- /usr/bin/python3 -m monitor export --config /etc/monitor/monitor.toml >/dev/null
c=$(sha256sum /var/lib/portocaribe-monitor/datos/csv/metricas_$(date +%F).csv | cut -d' ' -f1)
echo "antes:     $a"
echo "export 1:  $b"
echo "export 2:  $c"
[ "$b" = "$c" ] && echo "IDEMPOTENTE: si" || echo "IDEMPOTENTE: NO"
echo "filas: $(($(wc -l < /var/lib/portocaribe-monitor/datos/csv/metricas_$(date +%F).csv) - 1))"

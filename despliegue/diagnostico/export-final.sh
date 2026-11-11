#!/bin/bash
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
cd /opt/portocaribe-monitor
runuser -u monitor -- /usr/bin/python3 -m monitor export --config /etc/monitor/monitor.toml
archivo=/var/lib/portocaribe-monitor/datos/csv/metricas_$(date +%F).csv
echo "lineas: $(wc -l < "$archivo")"
sha256sum "$archivo"
echo "jsonl hoy: $(find /var/lib/portocaribe-monitor/datos/raw/$(date +%F) -name '*.jsonl' | wc -l)"
echo "jsonl desde 18:00: $(find /var/lib/portocaribe-monitor/datos/raw/$(date +%F) -name '*.jsonl' -newermt "$(date +%F) 18:00" | wc -l)"
echo "ultima captura: $(stat -c '%y %s bytes' /var/lib/portocaribe-monitor/datos/capturas/qos.pcap 2>/dev/null)"

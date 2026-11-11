#!/bin/bash
# Verificación final de VM1: servicios, muestra real, export idempotente y dataset.
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PAGER=cat PSQL_PAGER=cat SYSTEMD_PAGER=cat
DATOS=/var/lib/portocaribe-monitor/datos
cd /opt/portocaribe-monitor

echo "===== SERVICIOS VM1 ====="
systemctl is-active portal apache2 asterisk portocaribe-muestreo.timer portocaribe-cierre.timer \
  portocaribe-qos-captura.timer 2>&1 | paste -sd' ' -
echo "===== PUERTOS ====="
ss -lntup | awk 'NR==1 || /:(22|80|443|5038|5060|5201)\b/' | head -12
echo "===== NTP ====="
timedatectl show -p NTPSynchronized --value

echo "===== MUESTRA REAL ====="
set -a; . /etc/monitor/ami.env; set +a
runuser -u monitor -- env ASTERISK_AMI_SECRET="$ASTERISK_AMI_SECRET" \
  /usr/bin/python3 -m monitor run --config /etc/monitor/monitor.toml
echo "rc=$?"

echo "===== EXPORT IDEMPOTENTE ====="
runuser -u monitor -- /usr/bin/python3 -m monitor export --config /etc/monitor/monitor.toml
sha1=$(sha256sum "$DATOS"/csv/metricas_$(date +%F).csv | cut -d' ' -f1)
runuser -u monitor -- /usr/bin/python3 -m monitor export --config /etc/monitor/monitor.toml
sha2=$(sha256sum "$DATOS"/csv/metricas_$(date +%F).csv | cut -d' ' -f1)
echo "sha256 1: $sha1"
echo "sha256 2: $sha2"
[ "$sha1" = "$sha2" ] && echo "IDEMPOTENTE: si" || echo "IDEMPOTENTE: NO"

echo "===== DATASET DE HOY ====="
echo "JSONL hoy: $(find "$DATOS/raw/$(date +%F)" -name '*.jsonl' | wc -l)"
echo "JSONL desde 18:00: $(find "$DATOS/raw/$(date +%F)" -name '*.jsonl' -newermt "$(date +%F) 18:00" | wc -l)"
echo "CSV: $(wc -l < "$DATOS/csv/metricas_$(date +%F).csv") líneas (con cabecera)"
echo "Snapshots VM2: $(find "$DATOS/entradas/vm2" -type f | wc -l) archivos"
echo "Captura QoS: $(ls -l "$DATOS/capturas/qos.pcap" 2>/dev/null | awk '{print $5" bytes"}')"
echo "Timers:"
systemctl list-timers --all --no-pager 2>/dev/null | grep -i portocaribe

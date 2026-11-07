#!/bin/bash
# Estado final consolidado del despliegue en VM1
set -u
D=/var/lib/portocaribe-monitor/datos
echo "== servicios =="
for u in apache2 portal.service portocaribe-muestreo.timer portocaribe-cierre.timer; do
    printf '  %-32s %s / %s\n' "$u" "$(systemctl is-active $u)" "$(systemctl is-enabled $u 2>/dev/null)"
done
echo
echo "== HTTPS =="
python3 - <<'PY'
import ssl, urllib.request, time
c = ssl.create_default_context(); c.check_hostname = False; c.verify_mode = ssl.CERT_NONE
for u in ("https://127.0.0.1/", "https://192.168.137.54/"):
    t = time.perf_counter()
    r = urllib.request.urlopen(u, context=c, timeout=10)
    print(f"  {u:28s} {r.status} {r.headers.get('Content-Type')} {(time.perf_counter()-t)*1000:.0f}ms")
PY
echo
echo "== dataset =="
ls -1 "$D"/raw/*/*.jsonl | wc -l | xargs printf '  jsonl: %s archivos\n'
ls -1t "$D"/raw/*/*.jsonl | head -2 | sed 's/^/    /'
ls -lh "$D"/csv/*.csv | awk '{print "  csv:", $9, $5}'
echo
echo "== contenido del CSV de hoy =="
python3 - "$D"/csv/metricas_2026-11-07.csv <<'PY'
import csv, sys, collections
filas = list(csv.DictReader(open(sys.argv[1], encoding='utf-8-sig')))
print(f"  filas={len(filas)} columnas={len(filas[0])}")
for f in filas:
    print(f"   {f['timestamp']} {f['modulo']:10s} {f['recurso_target']:16s} {f['estado']:5s} {f['http_status']:>3s} {f['tiempo_respuesta_ms']:>6s}ms")
PY
echo
echo "== proximas ejecuciones =="
systemctl list-timers --all --no-pager | grep -E 'NEXT|portocaribe-muestreo|portocaribe-cierre'

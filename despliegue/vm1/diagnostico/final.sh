#!/bin/bash
# Comprobación final: seguimiento real, timers y muestras acumuladas
set -u
D=/var/lib/portocaribe-monitor/datos

python3 - <<'PY'
import http.cookiejar, json, ssl, urllib.request
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
jar = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPSHandler(context=CTX),
                                 urllib.request.HTTPCookieProcessor(jar))
B = "https://127.0.0.1"
op.open(urllib.request.Request(B + "/api/login",
        data=json.dumps({"usuario": "cliente.demo", "password": "Porto2026*"}).encode(),
        headers={"Content-Type": "application/json"}), timeout=10).read()
for q in ("BL-2026-001", "OD-2026-001", "CSQU3054383", "NO-EXISTE"):
    try:
        r = op.open(B + "/api/track?q=" + q, timeout=10)
        d = json.loads(r.read())
        if "contenedores" in d:
            print(f"  {q:14s} -> {r.status} {len(d['contenedores'])} resultado(s): "
                  + ", ".join(c.get('numero','?') for c in d['contenedores'][:3]))
        else:
            print(f"  {q:14s} -> {r.status} {str(d)[:120]}")
    except urllib.error.HTTPError as e:
        print(f"  {q:14s} -> {e.code} {e.read()[:110]}")
PY

echo
echo "== timers (ultima y proxima ejecucion) =="
systemctl list-timers --all --no-pager | grep -E 'NEXT|portocaribe'
echo
echo "== muestras del dia =="
ls -1 "$D"/raw/*/*.jsonl | wc -l
systemctl show -p Result --value portocaribe-monitor.service
journalctl -u portocaribe-monitor.service --no-pager -o cat | tail -4
echo
echo "== CSV =="
cd /opt/portocaribe-monitor
runuser -u monitor -- /usr/bin/python3 -m monitor export --config /etc/monitor/monitor.toml
python3 - "$D"/csv/metricas_2026-11-07.csv <<'PY'
import csv, sys
filas = list(csv.DictReader(open(sys.argv[1], encoding='utf-8-sig')))
print(f"{len(filas)} filas, {len(filas[0]) if filas else 0} columnas")
for f in filas[-4:]:
    print(f"  {f['timestamp']} {f['modulo']:10s} {f['recurso_target']:8s} {f['estado']:5s} {f['tiempo_respuesta_ms']:>7s}ms http={f['http_status']}")
PY

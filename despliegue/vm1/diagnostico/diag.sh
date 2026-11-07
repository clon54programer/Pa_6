#!/bin/bash
# Diagnóstico del despliegue PortoCaribe en VM1
D=/var/lib/portocaribe-monitor/datos
echo "== unidades =="
systemctl is-active portal apache2 portocaribe-muestreo.timer portocaribe-cierre.timer
echo
echo "== timers =="
systemctl list-timers --all --no-pager | grep -E 'NEXT|portocaribe' || true
echo
echo "== muestra mas reciente =="
F=$(ls -1t "$D"/raw/*/*.jsonl 2>/dev/null | head -1)
echo "$F"
if [ -n "$F" ]; then
    python3 - "$F" <<'PY'
import json, sys, collections
filas = [json.loads(l) for l in open(sys.argv[1], encoding='utf-8') if l.strip()]
print(f"filas={len(filas)}")
for f in filas[:12]:
    print(f["modulo"], "|", f["recurso_target"], "|", f["estado"], "|", f["fuente"], "|", f["detalle"])
print("--- conteo ---")
for (m, e), n in sorted(collections.Counter((f["modulo"], f["estado"]) for f in filas).items()):
    print(f"{m:12s} {e:10s} {n}")
PY
fi
echo
echo "== portal por HTTPS (python) =="
python3 - <<'PY'
import ssl, urllib.request, time
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
for url in ("https://127.0.0.1/", "https://127.0.0.1/api/estado", "http://127.0.0.1/"):
    t = time.perf_counter()
    try:
        r = urllib.request.urlopen(url, context=ctx, timeout=10)
        cuerpo = r.read(120)
        print(f"{url} -> {r.status} {r.headers.get('Content-Type')} {len(cuerpo)}B TLS={r.fp.raw._sock.version() if hasattr(r.fp,'raw') else '?'} {round((time.perf_counter()-t)*1000)}ms")
    except Exception as e:
        print(f"{url} -> ERROR {e}")
PY
echo
echo "== backend directo =="
python3 - <<'PY'
import urllib.request
r = urllib.request.urlopen("http://127.0.0.1:8080/", timeout=5)
print("8080 ->", r.status, len(r.read()))
PY
echo
echo "== ultimas lineas de logs =="
journalctl -u portal -n 15 --no-pager -o cat
tail -5 /var/log/apache2/portal-error.log 2>/dev/null || true

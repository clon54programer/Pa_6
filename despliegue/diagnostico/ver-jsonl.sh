#!/bin/bash
# Muestra las filas del último JSONL y el estado de la captura QoS.
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
archivo="$(ls -t /var/lib/portocaribe-monitor/datos/raw/*/*.jsonl | head -1)"
echo "ARCHIVO: $archivo"
python3 - "$archivo" <<'PY'
import json, sys, collections
filas = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
print("filas:", len(filas))
print("modulos:", collections.Counter(f["modulo"] for f in filas))
print("estados:", collections.Counter(f["estado"] for f in filas))
for f in filas:
    extra = ""
    if f.get("paquetes_delta"): extra += f" +{f['paquetes_delta']}pkt/{f.get('bytes_delta')}B"
    if f.get("evento_seguridad"): extra += f" [{f['evento_seguridad']}]"
    if f.get("sip_code"): extra += f" sip={f['sip_code']}"
    if f.get("duracion_llamada_s") is not None: extra += f" dur={f['duracion_llamada_s']}s"
    if f.get("llamadas_activas") is not None: extra += f" canales={f['llamadas_activas']}"
    if f.get("dscp") is not None: extra += f" dscp={f['dscp']}"
    print(f"{f['modulo']:10} {f['estado']:9} {str(f['recurso_target'])[:22]:22} {str(f['detalle'])[:70]}{extra}")
PY
echo "== capturas =="
ls -la /var/lib/portocaribe-monitor/datos/capturas/ 2>&1
echo "== timer captura =="
systemctl status portocaribe-qos-captura --no-pager 2>&1 | head -8

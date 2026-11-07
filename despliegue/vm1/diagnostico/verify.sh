#!/bin/bash
# Verificación funcional completa en VM1
set -u
D=/var/lib/portocaribe-monitor/datos
IP=192.168.137.54

echo "== 1. TLS en la IP de LAN (como lo vería un cliente remoto) =="
echo | timeout 10 openssl s_client -connect $IP:443 -servername portal.portocaribe.local 2>/dev/null \
  | grep -E 'subject=|issuer=|Protocol|Cipher|Verify return code' | head -6

echo
echo "== 2. contadores de ufw para 80/443 =="
iptables -L ufw-user-input -v -n 2>/dev/null | awk 'NR==1 || /dpt:(80|443)/'

echo
echo "== 3. unidades habilitadas y calendario =="
systemctl is-enabled portal.service portocaribe-muestreo.timer portocaribe-cierre.timer
systemctl list-timers --all --no-pager | grep -E 'NEXT|portocaribe'

echo
echo "== 4. JSONL del dia =="
ls -1 $D/raw/*/*.jsonl 2>/dev/null | wc -l
ls -1t $D/raw/*/*.jsonl 2>/dev/null | head -3

echo
echo "== 5. export idempotente =="
cd /opt/portocaribe-monitor
runuser -u monitor -- /usr/bin/python3 -m monitor export --config /etc/monitor/monitor.toml >/dev/null
A=$(sha256sum $D/csv/metricas_*.csv | cut -d' ' -f1)
runuser -u monitor -- /usr/bin/python3 -m monitor export --config /etc/monitor/monitor.toml >/dev/null
B=$(sha256sum $D/csv/metricas_*.csv | cut -d' ' -f1)
echo "sha1=$A"
echo "sha2=$B"
[ "$A" = "$B" ] && echo "RESULTADO: export idempotente OK" || echo "RESULTADO: export idempotente FALLA"

echo
echo "== 6. objetivo inexistente -> OFFLINE, sin traza =="
mkdir -p /tmp/verify/inc
cat > /tmp/verify/inc/monitor.toml <<'TOML'
[general]
directorio_datos = "/tmp/verify/inc/datos"
timeout_s = 2

[camaras]
habilitado = true
ping_paquetes = 2

[[camaras.lista]]
ip = "192.0.2.99"
nombre = "No_Existe"
vlan = 30
zona = "prueba"

[portal]
habilitado = false

[seguridad]
habilitado = false

[dhcp]
habilitado = false

[base_datos]
habilitado = false

[voip]
habilitado = false
TOML
PYTHONPATH=/opt/portocaribe-monitor python3 -m monitor run --config /tmp/verify/inc/monitor.toml
echo "rc=$?"
python3 - <<'PY'
import json, glob
for f in glob.glob('/tmp/verify/inc/datos/raw/*/*.jsonl'):
    for l in open(f):
        d = json.loads(l)
        print(f"  {d['modulo']} {d['recurso_target']} -> {d['estado']} ({d['fuente']}): {d['detalle']}")
PY

echo
echo "== 7. simulacion (dataset demostrable) =="
mkdir -p /tmp/verify/sim
cat > /tmp/verify/sim/monitor.toml <<'TOML'
[general]
directorio_datos = "/tmp/verify/sim/datos"
zona_horaria = "America/Bogota"

[camaras]
habilitado = true

[[camaras.lista]]
ip = "10.30.30.12"
nombre = "Cam_Muelle_1"
vlan = 30
zona = "muelles"

[[camaras.lista]]
ip = "10.30.30.13"
nombre = "Cam_Perimetro_1"
vlan = 30
zona = "perimetro"

[portal]
habilitado = true

[base_datos]
habilitado = true

[voip]
habilitado = true

[seguridad]
habilitado = true

[dhcp]
habilitado = true

[qos]
habilitado = false
TOML
PYTHONPATH=/opt/portocaribe-monitor python3 -m monitor run --config /tmp/verify/sim/monitor.toml --simulate
echo "rc=$?"
PYTHONPATH=/opt/portocaribe-monitor python3 -m monitor export --config /tmp/verify/sim/monitor.toml
python3 - <<'PY'
import csv, glob, collections
f = glob.glob('/tmp/verify/sim/datos/csv/*.csv')[0]
filas = list(csv.DictReader(open(f, encoding='utf-8-sig')))
print("columnas:", len(filas[0]), "| filas:", len(filas))
print("modulos:", dict(collections.Counter(x['modulo'] for x in filas)))
PY

echo
echo "== 8. pruebas unitarias del proyecto (Linux) =="
rm -rf /opt/portocaribe-monitor/tests_monitor
cp -a /tmp/pa6-deploy/tests_monitor /opt/portocaribe-monitor/tests_monitor 2>/dev/null || echo "(sin tests en el bundle)"
cd /opt/portocaribe-monitor
python3 -m unittest discover -s tests_monitor -t . 2>&1 | tail -5
rm -rf /opt/portocaribe-monitor/tests_monitor

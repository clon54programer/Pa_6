#!/bin/bash
# Depura la conexión AMI y el CDR de Asterisk tal como los ve el monitor.
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
cd /opt/portocaribe-monitor
set -a; . /etc/monitor/ami.env; set +a
runuser -u monitor -- env ASTERISK_AMI_SECRET="$ASTERISK_AMI_SECRET" python3 - <<'PY'
import os, socket
secreto = os.environ["ASTERISK_AMI_SECRET"]
s = socket.create_connection(("127.0.0.1", 5038), timeout=5)
s.settimeout(5)
saludo = s.recv(1024)
print("SALUDO:", saludo[:120])
s.sendall(f"Action: Login\r\nUsername: monitor\r\nSecret: {secreto}\r\nEvents: off\r\n\r\n".encode())
import time; time.sleep(0.5)
print("LOGIN:", s.recv(4096)[:300])
s.sendall(b"Action: CoreShowChannels\r\n\r\n")
time.sleep(1)
datos = b""
try:
    while True:
        bloque = s.recv(65536)
        if not bloque:
            break
        datos += bloque
        if b"CoreShowChannelsComplete" in datos:
            break
except socket.timeout:
    print("TIMEOUT esperando CoreShowChannelsComplete")
print("CORESHOW (%d bytes):" % len(datos))
print(datos[:800].decode("utf-8", "replace"))
s.sendall(b"Action: Logoff\r\n\r\n")
s.close()
PY
echo "== CDR primeras líneas =="
runuser -u monitor -- head -2 /var/log/asterisk/cdr-csv/Master.csv
echo "== permisos =="
ls -l /var/log/asterisk/cdr-csv/Master.csv

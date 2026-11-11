#!/bin/bash
# Ajusta Asterisk para el monitor: CDR en hora local, AMI con lectura completa
# (usuario local, solo lectura) y verificación de CoreShowChannels.
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

cat > /etc/asterisk/cdr.conf <<'EOF'
[general]
enable = yes
unanswered = no
congestion = no
usegmtime = no
loguniqueid = yes
loguserfield = yes
EOF
chown asterisk:asterisk /etc/asterisk/cdr.conf
chmod 0640 /etc/asterisk/cdr.conf

sed -i 's/^read = .*/read = all/' /etc/asterisk/manager.conf
sed -i 's/^write = .*/write = call/' /etc/asterisk/manager.conf

asterisk -rx "module reload cdr" >/dev/null 2>&1 || true
asterisk -rx "cdr reload" >/dev/null 2>&1 || true
asterisk -rx "manager reload" >/dev/null 2>&1 || true
sleep 1
asterisk -rx "manager show user monitor" | sed -n '1,10p'

echo "== CoreShowChannels como monitor =="
set -a; . /etc/monitor/ami.env; set +a
cd /opt/portocaribe-monitor
runuser -u monitor -- env ASTERISK_AMI_SECRET="$ASTERISK_AMI_SECRET" python3 - <<'PY'
import os, socket, time
s = socket.create_connection(("127.0.0.1", 5038), timeout=5)
s.settimeout(5)
s.recv(1024)
s.sendall(f"Action: Login\r\nUsername: monitor\r\nSecret: {os.environ['ASTERISK_AMI_SECRET']}\r\nEvents: off\r\n\r\n".encode())
time.sleep(0.4)
print(s.recv(4096).decode("utf-8", "replace").strip())
s.sendall(b"Action: CoreShowChannels\r\n\r\n")
time.sleep(0.6)
datos = b""
try:
    while b"CoreShowChannelsComplete" not in datos:
        bloque = s.recv(65536)
        if not bloque:
            break
        datos += bloque
except socket.timeout:
    pass
print(datos.decode("utf-8", "replace")[:600])
s.close()
PY

echo "== llamada de prueba y CDR =="
asterisk -rx "channel originate Local/1000@demo application Wait 2" >/dev/null || true
sleep 4
tail -2 /var/log/asterisk/cdr-csv/Master.csv

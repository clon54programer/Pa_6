#!/bin/bash
# Prueba de extremo a extremo de Asterisk en VM1.
#   bash prueba-asterisk.sh
# Ejecutar como root (usa el secreto AMI de /etc/monitor/ami.env).
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
cd /opt/portocaribe-monitor
set -a; . /etc/monitor/ami.env; set +a

echo "===== 1. Servicio y versión ====="
systemctl is-active asterisk
asterisk -rx "core show version" | head -1

echo "===== 2. Puertos SIP/AMI ====="
ss -lunp | grep ':5060' || echo "SIP 5060 no escucha"
ss -lntp | grep ':5038' || echo "AMI 5038 no escucha"

echo "===== 3. SIP OPTIONS (401 esperado) ====="
runuser -u monitor -- python3 - <<'PY'
import socket
mensaje = (
    "OPTIONS sip:127.0.0.1 SIP/2.0\r\n"
    "Via: SIP/2.0/UDP 127.0.0.1:5060;branch=z9hG4bK-prueba\r\n"
    "Max-Forwards: 70\r\n"
    "From: <sip:monitor@vm1>;tag=prueba\r\n"
    "To: <sip:127.0.0.1>\r\n"
    "Call-ID: prueba@vm1\r\n"
    "CSeq: 1 OPTIONS\r\n"
    "Contact: <sip:monitor@127.0.0.1>\r\n"
    "Content-Length: 0\r\n\r\n"
).encode()
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(3)
s.sendto(mensaje, ("127.0.0.1", 5060))
print(s.recvfrom(4096)[0].split(b"\r\n")[0].decode())
PY

echo "===== 4. AMI CoreShowChannels ====="
runuser -u monitor -- env ASTERISK_AMI_SECRET="$ASTERISK_AMI_SECRET" python3 - <<'PY'
import os, socket, time
s = socket.create_connection(("127.0.0.1", 5038), timeout=5)
s.settimeout(5)
s.recv(1024)
s.sendall(
    f"Action: Login\r\nUsername: monitor\r\nSecret: {os.environ['ASTERISK_AMI_SECRET']}\r\n"
    "Events: off\r\n\r\n".encode()
)
time.sleep(0.4)
print(s.recv(4096).decode("utf-8", "replace").split("\r\n")[0])
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
print("canales:", datos.count(b"Event: CoreShowChannel\r\n"))
print("completo:", b"CoreShowChannelsComplete" in datos)
s.close()
PY

echo "===== 5. Llamada de prueba y CDR ====="
asterisk -rx "channel originate Local/1000@demo application Wait 2" >/dev/null 2>&1
sleep 4
tail -1 /var/log/asterisk/cdr-csv/Master.csv

echo "===== 6. Filas VoIP del monitor ====="
runuser -u monitor -- env ASTERISK_AMI_SECRET="$ASTERISK_AMI_SECRET" \
  /usr/bin/python3 -m monitor run --config /etc/monitor/monitor.toml --solo voip

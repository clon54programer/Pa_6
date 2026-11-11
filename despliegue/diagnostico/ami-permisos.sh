#!/bin/bash
# Busca la clase mínima de escritura AMI para CoreShowChannels y revisa el CDR.
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

echo "== usegmtime en /etc/asterisk =="
grep -rn 'usegmtime' /etc/asterisk/ 2>/dev/null | head
echo "== cdr show status =="
asterisk -rx "cdr show status" 2>&1 | head -20
echo "== timezone del proceso =="
tr '\0' '\n' < /proc/$(pgrep -o asterisk)/environ | grep -i '^TZ=' || echo "(sin TZ)"

set -a; . /etc/monitor/ami.env; set +a
probar() {
  runuser -u monitor -- env ASTERISK_AMI_SECRET="$ASTERISK_AMI_SECRET" python3 - <<'PY'
import os, socket, time, sys
try:
    s = socket.create_connection(("127.0.0.1", 5038), timeout=4)
    s.settimeout(4)
    s.recv(1024)
    s.sendall(f"Action: Login\r\nUsername: monitor\r\nSecret: {os.environ['ASTERISK_AMI_SECRET']}\r\nEvents: off\r\n\r\n".encode())
    time.sleep(0.3); s.recv(4096)
    s.sendall(b"Action: CoreShowChannels\r\n\r\n")
    time.sleep(0.5)
    datos = b""
    while b"CoreShowChannelsComplete" not in datos:
        bloque = s.recv(65536)
        if not bloque: break
        datos += bloque
    print("OK" if b"CoreShowChannelsComplete" in datos else datos.decode("utf-8", "replace").replace("\r\n", " ")[:80])
    s.close()
except Exception as exc:
    print("ERROR", exc)
PY
}

for clases in "system" "call" "reporting" "system,call,reporting" "all"; do
  sed -i "s/^write = .*/write = $clases/" /etc/asterisk/manager.conf
  asterisk -rx "manager reload" >/dev/null 2>&1
  sleep 2
  resultado="$(probar)"
  echo "write=$clases -> $resultado"
  case "$resultado" in OK*) break ;; esac
done

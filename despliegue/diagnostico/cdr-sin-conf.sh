#!/bin/bash
# Sin cdr.conf (valores por defecto de Asterisk): ¿vuelve el CDR?
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
echo "== bytes del cdr.conf actual =="
od -c /etc/asterisk/cdr.conf | head -5
mv /etc/asterisk/cdr.conf /root/cdr.conf.prueba 2>/dev/null || true
systemctl restart asterisk
sleep 6
echo "== errores cdr =="
grep -i 'cdr.conf\|cdr_csv' /var/log/asterisk/messages | tail -4
echo "== módulo =="
asterisk -rx "module show like cdr_csv" | tail -2
echo "== llamada =="
asterisk -rx "channel originate Local/1000@demo application Wait 2" >/dev/null 2>&1
sleep 5
echo "== CDR =="
tail -1 /var/log/asterisk/cdr-csv/Master.csv
date '+ahora: %Y-%m-%d %H:%M:%S'

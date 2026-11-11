#!/bin/bash
# Prueba cdr.conf mínimo (solo usegmtime) y verifica que el CDR vuelva a escribirse.
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
cp -a /etc/asterisk/cdr.conf /root/cdr.conf.roto 2>/dev/null || true
printf '[general]\nusegmtime = no\n' > /etc/asterisk/cdr.conf
chown asterisk:asterisk /etc/asterisk/cdr.conf
chmod 0640 /etc/asterisk/cdr.conf
systemctl restart asterisk
sleep 6
echo "== errores de cdr.conf =="
grep -i 'cdr.conf\|cdr_csv' /var/log/asterisk/messages | tail -5
echo "== módulo =="
asterisk -rx "module show like cdr_csv" | tail -2
echo "== llamada =="
asterisk -rx "channel originate Local/1000@demo application Wait 2" >/dev/null 2>&1
sleep 5
echo "== CDR =="
tail -2 /var/log/asterisk/cdr-csv/Master.csv
date '+ahora: %Y-%m-%d %H:%M:%S'

#!/bin/bash
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
echo "== cdr_csv module =="
asterisk -rx "module show like cdr_csv"
echo "== cargar a mano =="
asterisk -rx "module load cdr_csv.so"
sleep 1
asterisk -rx "module show like cdr_csv"
echo "== cdr_csv.conf =="
cat /etc/asterisk/cdr_csv.conf 2>&1 | grep -v '^;' | grep -v '^$' | head -20
echo "== mensajes sobre cdr =="
grep -i 'cdr' /var/log/asterisk/messages | tail -10
echo "== prueba llamada =="
asterisk -rx "channel originate Local/1000@demo application Wait 2" >/dev/null 2>&1
sleep 4
tail -1 /var/log/asterisk/cdr-csv/Master.csv

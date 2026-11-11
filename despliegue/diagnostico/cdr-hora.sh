#!/bin/bash
# Reinicia Asterisk para aplicar cdr.conf y comprueba la hora del CDR.
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
systemctl restart asterisk
sleep 5
asterisk -rx "cdr show status" | head -8
echo "== hora local =="
date '+%Y-%m-%d %H:%M:%S %Z'
echo "== llamada y CDR =="
asterisk -rx "channel originate Local/1000@demo application Wait 2" >/dev/null || true
sleep 4
tail -2 /var/log/asterisk/cdr-csv/Master.csv

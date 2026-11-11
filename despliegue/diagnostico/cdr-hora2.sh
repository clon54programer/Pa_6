#!/bin/bash
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
echo "== uptime =="; asterisk -rx "core show uptime"
echo "== localtime =="; ls -l /etc/localtime; cat /etc/timezone
echo "== originate =="
asterisk -rx "channel originate Local/2000@demo application Wait 2"
sleep 5
echo "== CDR (últimas 3, mtime) =="
ls -l --time-style=full-iso /var/log/asterisk/cdr-csv/Master.csv
tail -3 /var/log/asterisk/cdr-csv/Master.csv
echo "== ahora =="; date '+%Y-%m-%d %H:%M:%S %Z (%z)'

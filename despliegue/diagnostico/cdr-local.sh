#!/bin/bash
# Debian trae usegmtime=yes en la sección [csv]; se pasa a hora local.
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
sed -i 's/^usegmtime=yes/usegmtime=no/' /etc/asterisk/cdr.conf
grep -n '^usegmtime' /etc/asterisk/cdr.conf
systemctl restart asterisk
sleep 6
asterisk -rx "module show like cdr_csv" | tail -1
asterisk -rx "channel originate Local/1000@demo application Wait 2" >/dev/null 2>&1
sleep 5
tail -1 /var/log/asterisk/cdr-csv/Master.csv
date '+ahora: %Y-%m-%d %H:%M:%S'

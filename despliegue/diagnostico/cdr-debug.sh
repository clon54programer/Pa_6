#!/bin/bash
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
echo "== módulos local =="; asterisk -rx "module show like chan_local" | head -5
echo "== originate verbose =="
asterisk -rx "channel originate Local/1000@demo application Wait 3" 2>&1 | head -5
sleep 2
echo "== canales activos =="; asterisk -rx "core show channels" | head -8
sleep 3
echo "== CDR mtime y cola =="
ls -l --time-style=+%H:%M:%S /var/log/asterisk/cdr-csv/Master.csv
tail -2 /var/log/asterisk/cdr-csv/Master.csv
echo "== log asterisk =="; tail -15 /var/log/asterisk/messages 2>/dev/null || journalctl -u asterisk -n 15 --no-pager

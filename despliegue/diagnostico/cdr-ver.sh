#!/bin/bash
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
echo "== cdr.conf (sin comentarios) =="
grep -v '^;' /etc/asterisk/cdr.conf | grep -v '^$'
echo "== usegmtime =="
grep -n 'usegmtime' /etc/asterisk/cdr.conf

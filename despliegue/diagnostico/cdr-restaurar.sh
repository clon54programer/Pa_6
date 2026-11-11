#!/bin/bash
# Restaura el cdr.conf original del paquete Debian y verifica el CDR.
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export DEBIAN_FRONTEND=noninteractive
cd /tmp
rm -rf astcfg cdr-pkg
mkdir -p cdr-pkg astcfg
cd cdr-pkg
apt-get download asterisk-config >/dev/null 2>&1
dpkg-deb -x asterisk-config_*.deb /tmp/astcfg
if [ -f /tmp/astcfg/etc/asterisk/cdr.conf ]; then
  install -m 0640 -o asterisk -g asterisk /tmp/astcfg/etc/asterisk/cdr.conf /etc/asterisk/cdr.conf
  echo "cdr.conf original restaurado"
else
  echo "ERROR: el paquete no trae cdr.conf"; exit 2
fi
systemctl restart asterisk
sleep 6
echo "== módulo =="
asterisk -rx "module show like cdr_csv" | tail -2
echo "== llamada =="
asterisk -rx "channel originate Local/1000@demo application Wait 2" >/dev/null 2>&1
sleep 5
echo "== CDR =="
tail -1 /var/log/asterisk/cdr-csv/Master.csv
date '+ahora: %Y-%m-%d %H:%M:%S'

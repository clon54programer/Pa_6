#!/bin/bash
# ---------------------------------------------------------------------------
# Asterisk de VM1 para el monitor PortoCaribe:
#   SIP 5060 (transporte pjsip), AMI 5038 en 127.0.0.1 y CDR en Master.csv.
#
# Uso (root):  bash despliegue/vm1/install-asterisk.sh
# Idempotente: conserva los .conf originales en /etc/asterisk/original/
# ---------------------------------------------------------------------------
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

BASE="$(cd "$(dirname "$0")" && pwd)"
SECRETOS=/etc/portocaribe-lab
AMI_FILE=$SECRETOS/ami.secret
SIP_FILE=$SECRETOS/sip_demo.secret

paso() { printf '\n=== %s ===\n' "$*"; }

paso "1/5 Secretos de Asterisk"
install -d -m 0700 "$SECRETOS"
[ -s "$AMI_FILE" ] || { umask 077; openssl rand -hex 16 > "$AMI_FILE"; }
[ -s "$SIP_FILE" ] || { umask 077; openssl rand -hex 8 > "$SIP_FILE"; }
AMI_SECRET="$(cat "$AMI_FILE")"
SIP_SECRET="$(cat "$SIP_FILE")"

install -d -m 0600 /etc/monitor
cat > /etc/monitor/ami.env <<EOF
ASTERISK_AMI_SECRET=$AMI_SECRET
EOF
chmod 0600 /etc/monitor/ami.env

paso "2/5 Configuración (respaldo de los .conf originales)"
install -d -m 0755 /etc/asterisk/original
for archivo in manager.conf pjsip.conf extensions.conf; do
  if [ -f "/etc/asterisk/$archivo" ] && [ ! -f "/etc/asterisk/original/$archivo" ]; then
    cp -a "/etc/asterisk/$archivo" "/etc/asterisk/original/$archivo"
  fi
done
sed "s/__AMI_SECRET__/$AMI_SECRET/" "$BASE/asterisk/manager.conf" > /etc/asterisk/manager.conf
sed "s/__SIP_SECRET__/$SIP_SECRET/" "$BASE/asterisk/pjsip.conf" > /etc/asterisk/pjsip.conf
install -m 0644 "$BASE/asterisk/extensions.conf" /etc/asterisk/extensions.conf
# Debian trae usegmtime=yes en [csv]: el CDR debe ir en hora local para que el
# monitor pueda filtrar por el día y comparar con los logs de VM2.
if [ -f /etc/asterisk/cdr.conf ]; then
  sed -i 's/^usegmtime=yes/usegmtime=no/' /etc/asterisk/cdr.conf
fi
chown asterisk:asterisk /etc/asterisk/manager.conf /etc/asterisk/pjsip.conf /etc/asterisk/extensions.conf
chmod 0640 /etc/asterisk/manager.conf

paso "3/5 Servicio"
systemctl enable --now asterisk
systemctl restart asterisk
sleep 4
asterisk -rx "core show version" | head -1
asterisk -rx "manager show user monitor" | sed -n '1,12p'

paso "4/5 Puertos y permisos del CDR"
ss -lunp | grep ':5060' || true
ss -lntp | grep ':5038' || true
install -d -m 0750 /var/log/asterisk/cdr-csv
chgrp -R asterisk /var/log/asterisk 2>/dev/null || true
chmod -R g+rX /var/log/asterisk 2>/dev/null || true
id monitor >/dev/null 2>&1 && usermod -aG asterisk monitor
ls -ld /var/log/asterisk /var/log/asterisk/cdr-csv

paso "5/5 Llamada de prueba -> CDR"
asterisk -rx "channel originate Local/1000@demo application Wait 2" >/dev/null || true
sleep 4
if [ -s /var/log/asterisk/cdr-csv/Master.csv ]; then
  tail -2 /var/log/asterisk/cdr-csv/Master.csv
else
  echo "AVISO: Master.csv aún no existe"
fi
echo
echo "Asterisk listo."

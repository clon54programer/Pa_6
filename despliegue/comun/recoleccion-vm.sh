#!/bin/sh
# Instala la recolección SSH de solo lectura en una VM de servicio.
#
#   sh recoleccion-vm.sh <IP_DEL_MONITOR> [clave_publica]
#
# Deja: usuario monitor con shell /bin/sh, authorized_keys restringida
# (from=, restrict, command=), wrapper /usr/local/bin/monitor-readonly y
# /etc/sudoers.d/monitor con la lista cerrada de comandos (plan §8).
set -eu
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

IP_MONITOR="${1:?uso: recoleccion-vm.sh <IP_MONITOR> [clave_publica]}"
PUB="${2:-/tmp/monitor_key.pub}"
USUARIO=monitor
CASA=/var/lib/portocaribe-monitor

[ -s "$PUB" ] || { echo "ERROR: falta la clave pública $PUB"; exit 2; }
id "$USUARIO" >/dev/null 2>&1 || {
  echo "ERROR: no existe el usuario $USUARIO (ejecute antes el instalador del monitor)"; exit 2; }

# Shell utilizable: sshd ejecuta el command= forzado a través del shell del usuario.
usermod -s /bin/sh "$USUARIO"
usermod -aG adm,systemd-journal "$USUARIO"

install -d -m 0700 -o "$USUARIO" -g "$USUARIO" "$CASA/.ssh"
CLAVE="$(cat "$PUB")"
printf 'from="%s",restrict,command="/usr/local/bin/monitor-readonly" %s\n' \
  "$IP_MONITOR" "$CLAVE" > "$CASA/.ssh/authorized_keys"
chown "$USUARIO:$USUARIO" "$CASA/.ssh/authorized_keys"
chmod 0600 "$CASA/.ssh/authorized_keys"

cat > /usr/local/bin/monitor-readonly <<'EOF'
#!/bin/sh
# Wrapper de solo lectura para la recolección del monitor PortoCaribe.
set -eu
case "${SSH_ORIGINAL_COMMAND:-}" in
  cdr)         exec sudo -n /usr/bin/cat /var/log/asterisk/cdr-csv/Master.csv ;;
  apache)      exec sudo -n /usr/bin/systemctl is-active apache2 ;;
  iptables)    exec sudo -n /usr/sbin/iptables-save -c ;;
  fail2ban)    exec sudo -n /usr/bin/fail2ban-client status sshd ;;
  fail2banlog) exec sudo -n /usr/bin/tail -n 5000 /var/log/fail2ban.log ;;
  auth)        exec sudo -n /usr/bin/journalctl -u ssh -n 5000 -o short-iso --no-pager ;;
  kern)        exec sudo -n /usr/bin/journalctl -k -n 5000 -o short-iso --no-pager ;;
  netstat)     exec /usr/bin/cat /proc/net/netstat ;;
  snmp)        exec /usr/bin/cat /proc/net/snmp ;;
  dhcp_leases) exec sudo -n /usr/bin/cat /var/lib/dhcp/dhcpd.leases ;;
  dhcp_estado) ( sudo -n /usr/bin/systemctl is-active isc-dhcp-server || true )
               sudo -n /usr/bin/stat -c %Y /var/lib/dhcp/dhcpd.leases 2>/dev/null || echo 0 ;;
  *) echo "receta no permitida" >&2; exit 2 ;;
esac
EOF
chmod 0755 /usr/local/bin/monitor-readonly
chown root:root /usr/local/bin/monitor-readonly

cat > /etc/sudoers.d/monitor <<'EOF'
# PortoCaribe: solo las recetas del wrapper, sin comodines ni editores.
monitor ALL=(root) NOPASSWD: /usr/bin/cat /var/log/asterisk/cdr-csv/Master.csv, \
  /usr/bin/systemctl is-active apache2, /usr/bin/systemctl is-active isc-dhcp-server, \
  /usr/sbin/iptables-save -c, /usr/bin/fail2ban-client status sshd, \
  /usr/bin/tail -n 5000 /var/log/fail2ban.log, \
  /usr/bin/journalctl -u ssh -n 5000 -o short-iso --no-pager, \
  /usr/bin/journalctl -k -n 5000 -o short-iso --no-pager, \
  /usr/bin/cat /var/lib/dhcp/dhcpd.leases, /usr/bin/stat -c %Y /var/lib/dhcp/dhcpd.leases
EOF
chmod 0440 /etc/sudoers.d/monitor
visudo -cf /etc/sudoers.d/monitor

install -d -m 0755 /var/lib/dhcp
touch /var/lib/dhcp/dhcpd.leases
chown root:root /var/lib/dhcp/dhcpd.leases

echo "recoleccion-vm: usuario $USUARIO listo para $IP_MONITOR"

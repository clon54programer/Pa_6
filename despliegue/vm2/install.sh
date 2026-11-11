#!/bin/bash
# ---------------------------------------------------------------------------
# Instalador PortoCaribe para VM2 (192.168.100.59)
#
#   PostgreSQL 15        -> base portocaribe, rol monitor (solo SELECT 1)
#   fail2ban             -> jails sshd y apache-auth
#   iptables             -> reglas VLAN30-DROP / VLAN40-DROP persistentes
#   isc-dhcp-server      -> dummy0 10.30.50.5/24 (aislado de la red real)
#   iperf3               -> servidor QoS en :5201
#   Portal secundario    -> Apache TLS con SAN de la IP nueva
#   Recolección SSH      -> usuario monitor + wrapper + sudoers
#
# Uso (como root):
#   IP_VM1=192.168.100.60 bash despliegue/vm2/install.sh [RAIZ]
# ---------------------------------------------------------------------------
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export DEBIAN_FRONTEND=noninteractive
# psql/systemctl/journalctl no deben abrir paginador dentro de un script.
export PAGER=cat PSQL_PAGER=cat PGPAGER=cat SYSTEMD_PAGER=cat

BASE="$(cd "$(dirname "$0")" && pwd)"
RAIZ="$(cd "${1:-$BASE/../..}" && pwd)"
IP_VM1="${IP_VM1:-192.168.100.60}"
IP_VM2="${IP_VM2:-192.168.100.59}"
SECRETOS=/etc/portocaribe-lab
PGPASS_FILE=$SECRETOS/pg_monitor.pass
SSL_DIR=/etc/apache2/ssl

paso() { printf '\n=== %s ===\n' "$*"; }

paso "1/8 PostgreSQL: rol, base y escucha"
systemctl enable --now postgresql
install -d -m 0700 "$SECRETOS"
if [ ! -s "$PGPASS_FILE" ]; then
  umask 077
  openssl rand -hex 16 > "$PGPASS_FILE"
fi
PG_PASS="$(cat "$PGPASS_FILE")"
su postgres -c "cd /tmp && psql -X -q -P pager=off -v ON_ERROR_STOP=1" <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'monitor') THEN
    CREATE ROLE monitor LOGIN PASSWORD '$PG_PASS';
  ELSE
    ALTER ROLE monitor WITH LOGIN PASSWORD '$PG_PASS';
  END IF;
END
\$\$;
SELECT 'CREATE DATABASE portocaribe OWNER monitor'
 WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'portocaribe')\gexec
ALTER SYSTEM SET listen_addresses = 'localhost,$IP_VM2';
SELECT pg_reload_conf();
SQL

HBA=/etc/postgresql/15/main/pg_hba.conf
for linea in \
  "host portocaribe monitor $IP_VM1/32 scram-sha-256" \
  "host portocaribe monitor 127.0.0.1/32 scram-sha-256"; do
  grep -qxF "$linea" "$HBA" || echo "$linea" >> "$HBA"
done
systemctl restart postgresql
sleep 2
su postgres -c "cd /tmp && psql -X -tAc \"SELECT datname FROM pg_database WHERE datname='portocaribe'\""
ss -lntp | grep 5432 || true

paso "2/8 fail2ban"
install -m 0644 "$BASE/etc/fail2ban/jail.local" /etc/fail2ban/jail.local
fail2ban-client -t >/dev/null
systemctl enable --now fail2ban
sleep 2
fail2ban-client status sshd | sed -n '1,8p'

paso "3/8 iptables VLAN30/VLAN40"
install -d -m 0755 /etc/iptables
install -m 0644 "$BASE/etc/iptables/rules.v4" /etc/iptables/rules.v4
iptables-restore < /etc/iptables/rules.v4
netfilter-persistent reload || true
iptables-save -c | grep -E 'VLAN(30|40)-DROP' | head -8 || true

paso "4/8 DHCP en dummy0 (aislado)"
if ! nmcli -t -f NAME con show 2>/dev/null | grep -qx 'portocaribe-dummy'; then
  nmcli con add type dummy con-name portocaribe-dummy ifname dummy0 \
    ipv4.method manual ipv4.addresses 10.30.50.5/24 ipv6.method disabled >/dev/null
fi
nmcli con up portocaribe-dummy >/dev/null
ip -4 -br addr show dummy0
install -m 0755 "$BASE/usr/local/bin/portocaribe-dhcp-veth" /usr/local/bin/portocaribe-dhcp-veth
install -m 0644 "$BASE/systemd/portocaribe-dhcp-veth.service" /etc/systemd/system/portocaribe-dhcp-veth.service
systemctl daemon-reload
systemctl enable --now portocaribe-dhcp-veth.service
install -m 0644 "$BASE/etc/dhcp/dhcpd.conf" /etc/dhcp/dhcpd.conf
sed -i 's/^INTERFACESv4=.*/INTERFACESv4="dummy0 veth-dhcp"/' /etc/default/isc-dhcp-server
grep -q '^INTERFACESv4="dummy0 veth-dhcp"' /etc/default/isc-dhcp-server || \
  echo 'INTERFACESv4="dummy0 veth-dhcp"' >> /etc/default/isc-dhcp-server
dhcpd -t -cf /etc/dhcp/dhcpd.conf
systemctl enable isc-dhcp-server >/dev/null 2>&1 || true
systemctl restart isc-dhcp-server
sleep 2
systemctl is-active isc-dhcp-server
install -m 0755 "$BASE/usr/local/bin/portocaribe-dhcp-lease" /usr/local/bin/portocaribe-dhcp-lease
install -m 0644 "$BASE/systemd/portocaribe-dhcp-lease.service" \
                 "$BASE/systemd/portocaribe-dhcp-lease.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now portocaribe-dhcp-lease.timer
systemctl start portocaribe-dhcp-lease.service || true
sleep 2
echo "leases activos: $(grep -c 'binding state active' /var/lib/dhcp/dhcpd.leases || true)"

paso "5/8 iperf3 (servidor QoS)"
install -m 0644 "$BASE/systemd/iperf3.service" /etc/systemd/system/iperf3.service
systemctl daemon-reload
systemctl enable --now iperf3.service
ss -lntp | grep 5201 || true

paso "6/8 Certificado TLS del portal secundario"
if ! openssl x509 -in "$SSL_DIR/portal.crt" -noout -text 2>/dev/null | grep -q "IP Address:$IP_VM2"; then
  install -d -m 0750 "$SSL_DIR"
  openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
    -keyout "$SSL_DIR/portal.key" -out "$SSL_DIR/portal.crt" \
    -subj "/C=CO/ST=Bolivar/L=Cartagena/O=PortoCaribe S.A./CN=portal.portocaribe.local" \
    -addext "subjectAltName=DNS:portal.portocaribe.local,DNS:localhost,IP:127.0.0.1,IP:$IP_VM2" \
    -addext "basicConstraints=critical,CA:FALSE" \
    -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
    -addext "extendedKeyUsage=serverAuth" 2>/dev/null
  chmod 0640 "$SSL_DIR/portal.key"
  chown root:www-data "$SSL_DIR/portal.key" "$SSL_DIR/portal.crt"
fi
openssl x509 -in "$SSL_DIR/portal.crt" -noout -subject -ext subjectAltName
apache2ctl configtest
systemctl restart apache2
systemctl is-active apache2 portal
grep -q 'portal.portocaribe.local' /etc/hosts || echo "127.0.0.1 portal.portocaribe.local" >> /etc/hosts

paso "7/8 Recolección SSH"
if [ -s /tmp/monitor_key.pub ]; then
  sh "$BASE/../comun/recoleccion-vm.sh" "$IP_VM1" /tmp/monitor_key.pub
else
  echo "AVISO: /tmp/monitor_key.pub no existe; se omite la recolección SSH"
fi

paso "8/8 Verificación"
ss -lntp | grep -E ':(22|80|443|5432|5201)\b' | sort -u
echo
echo "Instalación de VM2 completada."
echo "Contraseña del rol PostgreSQL: $PGPASS_FILE (copiar a /etc/monitor/pgpass en VM1)"

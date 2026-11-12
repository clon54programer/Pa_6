#!/bin/bash
# Prueba de extremo a extremo de VM2 (portal, PostgreSQL, fail2ban, iptables,
# DHCP, iperf3 y recolección). Ejecutar como root en 192.168.100.59.
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PAGER=cat PSQL_PAGER=cat SYSTEMD_PAGER=cat
IP_PRUEBA=203.0.113.99

echo "===== 1. Servicios ====="
systemctl is-active postgresql fail2ban isc-dhcp-server apache2 portal iperf3 portocaribe-dhcp-veth \
  | paste -sd' ' -

echo "===== 2. Portal por HTTPS (local) ====="
runuser -u nobody -- python3 - <<'PY'
import http.client, ssl
c = http.client.HTTPSConnection("127.0.0.1", 443, timeout=10, context=ssl._create_unverified_context())
c.request("GET", "/")
r = c.getresponse()
print("GET / ->", r.status, r.getheader("Content-Type"))
r.read()
c.close()
PY

echo "===== 3. PostgreSQL ====="
su postgres -c "cd /tmp && psql -X -tAc \"SELECT datname FROM pg_database WHERE datname='portocaribe'\""
su postgres -c "cd /tmp && psql -X -d portocaribe -tAc 'SELECT 1'"
grep '^host portocaribe' /etc/postgresql/15/main/pg_hba.conf

echo "===== 4. fail2ban: ban y desbaneo de $IP_PRUEBA ====="
fail2ban-client set sshd banip "$IP_PRUEBA" >/dev/null
sleep 1
fail2ban-client status sshd | grep -E 'Currently banned|Banned IP'
iptables -S | grep "$IP_PRUEBA" || echo "(sin regla en iptables)"
fail2ban-client set sshd unbanip "$IP_PRUEBA" >/dev/null
fail2ban-client status sshd | grep -E 'Currently banned|Banned IP'

echo "===== 5. iptables VLAN30/VLAN40 ====="
iptables -S INPUT | grep -E 'VLAN(30|40)-DROP'
iptables-save -c | grep -E 'VLAN(30|40)-DROP.*-j (DROP|LOG)'

echo "===== 6. DHCP ====="
systemctl is-active isc-dhcp-server portocaribe-dhcp-lease.timer
systemctl start portocaribe-dhcp-lease.service
sleep 2
echo "IPs con lease activo (distintas): $(awk '/^lease /{ip=$2} /binding state active/{print ip}' /var/lib/dhcp/dhcpd.leases | sort -u | wc -l)"
echo "bloques activos en el archivo (incluye renovaciones): $(grep -c 'binding state active' /var/lib/dhcp/dhcpd.leases)"
grep -A4 'lease 10.30.60' /var/lib/dhcp/dhcpd.leases | head -5
ip netns exec clientes ip -4 -br addr show veth-cli

echo "===== 7. iperf3 (servidor) ====="
ss -lntp | grep ':5201' || echo "iperf3 no escucha"

echo "===== 8. Wrapper de recolección (local) ====="
SSH_ORIGINAL_COMMAND=apache runuser -u monitor -- /usr/local/bin/monitor-readonly
SSH_ORIGINAL_COMMAND=inventada runuser -u monitor -- /usr/local/bin/monitor-readonly; echo "rc_receta_invalida=$?"

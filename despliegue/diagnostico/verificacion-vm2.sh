#!/bin/bash
# Verificación final de VM2.
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PAGER=cat PSQL_PAGER=cat SYSTEMD_PAGER=cat
echo "===== SERVICIOS VM2 ====="
systemctl is-active postgresql fail2ban isc-dhcp-server apache2 portal iperf3 portocaribe-dhcp-veth 2>&1 | paste -sd' ' -
echo "===== PUERTOS ====="
ss -lntu | grep -E ':(22|80|443|5432|5201)\b' | awk '{print $1, $5}'
echo "===== POSTGRESQL ====="
su postgres -c "psql -X -tAc 'SELECT version()'" | cut -c1-60
su postgres -c "psql -X -tAc \"SELECT datname FROM pg_database WHERE datname='portocaribe'\""
grep -c '^host portocaribe' /etc/postgresql/15/main/pg_hba.conf
echo "===== FAIL2BAN ====="
fail2ban-client status sshd | grep -E 'Currently banned|Banned IP'
echo "===== IPTABLES ====="
iptables -S INPUT | grep VLAN | head -6
iptables-save -c | grep -E 'VLAN(30|40)-DROP.*-j (DROP|LOG)' | head -4
echo "===== DHCP ====="
systemctl is-active portocaribe-dhcp-lease.timer
grep -c 'binding state active' /var/lib/dhcp/dhcpd.leases
grep -A6 'lease 10.30.60' /var/lib/dhcp/dhcpd.leases | head -10
echo "===== PORTAL SECUNDARIO ====="
curl -sk -o /dev/null -w 'https 127.0.0.1 -> %{http_code}\n' https://127.0.0.1/ 2>/dev/null || \
  python3 -c "import ssl,http.client;c=http.client.HTTPSConnection('127.0.0.1',443,context=ssl._create_unverified_context());c.request('GET','/');print('https ->',c.getresponse().status)"
echo "===== COLECTOR (usuario monitor) ====="
ls -l /usr/local/bin/monitor-readonly /etc/sudoers.d/monitor
grep -c 'from=' /var/lib/portocaribe-monitor/.ssh/authorized_keys

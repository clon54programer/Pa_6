#!/bin/sh
# Paquetes de VM2: PostgreSQL, fail2ban, DHCP, QoS y persistencia de iptables.
set -e
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export DEBIAN_FRONTEND=noninteractive

sh "${LAB:-/tmp/pa6desp/despliegue/comun/apt-lab.sh}"

# iptables-persistent pregunta si guardar reglas: se responde por debconf
echo "iptables-persistent iptables-persistent/autosave_v4 boolean false" | debconf-set-selections
echo "iptables-persistent iptables-persistent/autosave_v6 boolean false" | debconf-set-selections

apt-get install -y -qq --no-install-recommends \
  postgresql postgresql-client fail2ban isc-dhcp-server \
  netfilter-persistent iptables iptables-persistent \
  iperf3 tcpdump ca-certificates python3-systemd

echo "== versiones =="
psql --version
fail2ban-client --version
dhcpd --version 2>&1 | head -1 || true
iperf3 --version | head -1

#!/bin/sh
# Paquetes de VM1: Asterisk (VoIP), iperf3/tcpdump (QoS) y cliente PostgreSQL.
set -e
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export DEBIAN_FRONTEND=noninteractive

sh "${LAB:-/tmp/pa6desp/despliegue/comun/apt-lab.sh}"

apt-get install -y -qq --no-install-recommends \
  iperf3 tcpdump postgresql-client ca-certificates

# asterisk ya no existe en bookworm: se instala el build de bullseye con -t bullseye
apt-get install -y -qq -t bullseye asterisk

echo "== versiones =="
asterisk -V
iperf3 --version | head -1
tcpdump --version 2>&1 | head -1
psql --version

#!/bin/bash
# Exporta la contraseña del rol PostgreSQL a /tmp para copiarla a VM1.
set -euo pipefail
install -m 0644 /etc/portocaribe-lab/pg_monitor.pass /tmp/pg_monitor.pass
[ -f /etc/iptables/rules.v6 ] || { echo "# sin reglas IPv6" > /etc/iptables/rules.v6; chmod 0644 /etc/iptables/rules.v6; }
echo "pgpass exportado: $(wc -c < /tmp/pg_monitor.pass) bytes"

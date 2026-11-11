#!/bin/bash
# Banea una IP de prueba (TEST-NET-3, no usada en el laboratorio) para que el
# módulo de seguridad tenga un evento real de fail2ban que leer.
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
fail2ban-client set sshd banip 203.0.113.50
fail2ban-client status sshd
iptables-save -c | grep -i '203.0.113.50' | head -3

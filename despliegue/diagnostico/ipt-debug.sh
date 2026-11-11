#!/bin/bash
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
set +e
echo "== iptables-restore --test =="
iptables-restore --test -v /etc/iptables/rules.v4
echo "rc=$?"
echo "== netfilter-persistent reload =="
netfilter-persistent reload
echo "rc=$?"
echo "== iptables-save (VLAN) =="
iptables-save -c | grep -E 'VLAN(30|40)-DROP' | head -8
echo "grep_rc=$?"
echo "== reglas INPUT =="
iptables -S INPUT | head -10

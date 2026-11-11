#!/bin/sh
# Repositorios de red para el laboratorio PortoCaribe (Debian 12 + asterisk de bullseye).
# El ISO cdrom original no está montado; se usa deb.debian.org por HTTPS.
set -e
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export DEBIAN_FRONTEND=noninteractive

if [ -f /etc/apt/sources.list ] && grep -q '^deb cdrom:' /etc/apt/sources.list; then
  cp -n /etc/apt/sources.list /etc/apt/sources.list.portocaribe.bak
  sed -i 's/^deb cdrom:/#deb cdrom:/' /etc/apt/sources.list
fi

cat > /etc/apt/sources.list.d/portocaribe-lab.list <<'EOF'
# PortoCaribe: repositorios de red del laboratorio (2026-11)
deb https://deb.debian.org/debian bookworm main
deb https://security.debian.org/debian-security bookworm-security main
# bullseye solo aporta asterisk (retirado de bookworm); el pin lo mantiene a 100
deb https://deb.debian.org/debian bullseye main
EOF

cat > /etc/apt/preferences.d/portocaribe-bullseye.pref <<'EOF'
Package: *
Pin: release n=bullseye
Pin-Priority: 100
EOF

apt-get update -qq
echo "apt-lab: repositorios listos"

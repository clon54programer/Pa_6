#!/bin/bash
# Genera tráfico con origen falsificado de VLAN30/VLAN40 hacia VM2 para que las
# reglas VLAN30-DROP / VLAN40-DROP incrementen sus contadores (laboratorio).
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
python3 - <<'PY'
import socket, struct

def paquete(src, dst, puerto=9999):
    carga = b"portocaribe-prueba"
    total = 20 + 8 + len(carga)
    ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, total, 1, 0, 64, 17, 0,
                     socket.inet_aton(src), socket.inet_aton(dst))
    udp = struct.pack("!HHHH", 12345, puerto, 8 + len(carga), 0) + carga
    return ip + udp

s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW)
s.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
for _ in range(6):
    s.sendto(paquete("10.30.30.12", "192.168.100.59"), ("192.168.100.59", 0))
for _ in range(4):
    s.sendto(paquete("10.30.40.77", "192.168.100.59"), ("192.168.100.59", 0))
print("enviados 10 paquetes con origen VLAN30/VLAN40")
PY
sleep 1

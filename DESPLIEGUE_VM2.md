# Despliegue en VM2 — Portal, PostgreSQL, fail2ban, iptables y DHCP

Guía del despliegue realizado el **2026-11-11** en `192.168.100.59` (Debian 12
"bookworm", Python 3.11, PostgreSQL 15.19), dentro del segundo sprint del proyecto.

> **Alcance.** VM2 es la máquina de servicios del caso: publica el **portal principal**
> por Apache/TLS, aloja **PostgreSQL**, aplica **fail2ban** e **iptables** con las reglas
> `VLAN30-DROP`/`VLAN40-DROP`, sirve **DHCP** de laboratorio y ejecuta el **servidor
> iperf3** del módulo QoS. La VM nació como clon de VM1, así que conserva también una
> copia del portal; el monitor mide la de VM2 como principal.

---

## 1. Qué quedó funcionando

| Servicio | Puerto | Comprobación |
|---|---|---|
| Apache + portal (proxy a `127.0.0.1:8080`) | 80/443 | `https://192.168.100.59/` → **200**, TLS 1.3 |
| PostgreSQL 15 | 5432 (solo `192.168.100.59` y loopback) | base `portocaribe`, rol `monitor`, `SELECT 1` desde VM1 |
| fail2ban | — | jails `sshd` y `apache-auth`; ban real de `203.0.113.50` |
| iptables (`netfilter-persistent`) | — | reglas VLAN persistidas en `/etc/iptables/rules.v4` |
| isc-dhcp-server | 67/udp en `dummy0` y `veth-dhcp` | arrendamiento real `10.30.60.100` |
| iperf3 | 5201 | servidor del módulo QoS |
| Recolección SSH | 22 | usuario `monitor` con wrapper y `sudoers` |

Certificado TLS autofirmado con SAN `portal.portocaribe.local`, `localhost`,
`127.0.0.1` y **`192.168.100.59`**.

---

## 2. Rutas y usuarios

| Elemento | Ruta |
|---|---|
| Código del portal | `/opt/portal/portal/` |
| Configuración del portal | `/etc/portal/portal.toml` |
| Base SQLite del portal | `/var/lib/portal/portal.db` |
| Credenciales del rol PostgreSQL | `/etc/portocaribe-lab/pg_monitor.pass` (600, root) |
| Reglas de firewall | `/etc/iptables/rules.v4` |
| Configuración DHCP | `/etc/dhcp/dhcpd.conf`, `/var/lib/dhcp/dhcpd.leases` |
| Jail de fail2ban | `/etc/fail2ban/jail.local` |
| Recolección SSH | `/usr/local/bin/monitor-readonly`, `/etc/sudoers.d/monitor`, `~monitor/.ssh/authorized_keys` |
| Unidades | `/etc/systemd/system/iperf3.service`, `portocaribe-dhcp-veth.service`, `portocaribe-dhcp-lease.{service,timer}` |

Usuarios existentes: `monitor` (shell `/bin/sh`, grupos `adm`, `systemd-journal`,
`asterisk`), `portal` y `postgres`.

---

## 3. Instalación

Los artefactos viven en [`despliegue/vm2/`](vm2/) y los comparte con VM1
[`despliegue/comun/`](comun/).

```bash
# desde el equipo de trabajo
tar czf pa6.tgz despliegue monitor portal tests_monitor inventario.csv monitor.toml
scp pa6.tgz vboxuser@192.168.100.59:/tmp/
ssh vboxuser@192.168.100.59
mkdir -p /tmp/pa6desp && tar xzf /tmp/pa6.tgz -C /tmp/pa6desp
su -                     # root (la contraseña del aula)
bash /tmp/pa6desp/despliegue/vm2/packages.sh   # repos de red + paquetes
bash /tmp/pa6desp/despliegue/vm2/install.sh    # servicios y configuración
```

`packages.sh` usa [`comun/apt-lab.sh`](comun/apt-lab.sh), que añade
`deb.debian.org`/`security.debian.org` por HTTPS y un pin 100 para bullseye (de ahí sale
`python3-systemd`, que fail2ban necesita para el backend `systemd`).

El instalador de VM2:

1. Crea el rol `monitor` con contraseña aleatoria, la base `portocaribe`, ajusta
   `listen_addresses` y `pg_hba` para `192.168.100.60/32`.
2. Instala `jail.local` y habilita fail2ban.
3. Carga `rules.v4` con `iptables-restore`, persiste con `netfilter-persistent` y añade
   `iptables-persistent` para el arranque.
4. Crea `dummy0` (10.30.50.5/24), el veth `10.30.60.1/24` con un cliente DHCP en el
   namespace `clientes`, y sirve DHCP en ambas interfaces.
5. Habilita el servidor iperf3.
6. Regenera el certificado si el SAN no incluye `192.168.100.59` y reinicia Apache.
7. Instala la recolección SSH con [`comun/recoleccion-vm.sh`](comun/recoleccion-vm.sh)
   (necesita `/tmp/monitor_key.pub`, la clave pública que genera VM1).

> **Orden importante:** primero se ejecuta `postconfig.sh` en VM1 (genera
> `/tmp/monitor_key.pub`), luego se copia esa clave a VM2 y se instala VM2. Después se
> lleva `/etc/portocaribe-lab/pg_monitor.pass` a `/etc/monitor/pgpass` en VM1 y se
> relanza `postconfig.sh`.

---

## 4. Operación

```bash
# estado
systemctl status postgresql fail2ban isc-dhcp-server apache2 portal iperf3
systemctl list-timers --all | grep portocaribe

# PostgreSQL
su postgres -c "psql -tAc \"SELECT datname FROM pg_database WHERE datname='portocaribe'\""
su postgres -c "psql -d portocaribe -c 'SELECT 1'"

# seguridad
fail2ban-client status sshd
iptables-save -c | grep -E 'VLAN(30|40)-DROP'

# DHCP
grep -c 'binding state active' /var/lib/dhcp/dhcpd.leases
ip netns exec clientes ip -4 -br addr show veth-cli

# logs
journalctl -u fail2ban -n 50 --no-pager
tail -50 /var/log/apache2/portal-error.log
```

Pruebas reproducibles en [`despliegue/diagnostico/`](diagnostico/):
`verificacion-vm2.sh` (servicios, puertos, PostgreSQL, fail2ban, iptables, DHCP) y
`ban-prueba.sh` (ban de una IP TEST-NET).

---

## 5. Decisiones y límites

- **DHCP aislado.** `isc-dhcp-server` escucha en `dummy0` (10.30.50.0/24) y en
  `veth-dhcp` (10.30.60.0/24). No se configura en `enp0s3` para no repartir direcciones
  en la red real del aula ni competir con su router.
- **El arrendamiento es real**, no un archivo simulado: el namespace `clientes` ejecuta
  `dhclient` contra el servidor y deja `binding state active;` en `dhcpd.leases`. Un
  timer renueva cada 5 minutos.
- **fail2ban no banea a VM1.** El ban de prueba usa `203.0.113.50` (TEST-NET-3) para no
  cortar la sesión de administración.
- **Tráfico VLAN sintético.** Para que los contadores de `VLAN30-DROP`/`VLAN40-DROP`
  suban, VM1 envía paquetes con origen `10.30.30.12`/`10.30.40.77`; es una prueba de la
  regla, no una medición de cámaras.
- **Sin cámaras reales:** la VLAN 30 sigue sin equipos; el módulo `camaras` está
  deshabilitado en `monitor.toml`.

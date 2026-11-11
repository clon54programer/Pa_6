# Despliegue en VM1 — Monitor, Asterisk y portal de respaldo

Guía de la máquina `192.168.100.60` (Debian 12 "bookworm", Python 3.11.2). El despliegue
inicial del portal y del monitor fue el **2026-11-07**; el **2026-11-11** se actualizó a la
red del segundo sprint y se añadieron Asterisk, la recolección SSH y la captura de QoS.

> **Alcance.** VM1 ejecuta el **monitor**, el **Asterisk** del caso (SIP/AMI/CDR) y
> conserva un **portal de respaldo** con Apache/TLS. El portal principal y los servicios
> de seguridad viven en [VM2](DESPLIEGUE_VM2.md) (`192.168.100.59`).

---

## 1. Qué quedó funcionando

| Aplicación | Cómo se accede | Servicio |
|---|---|---|
| **Monitor** | sin interfaz; escribe el dataset | `portocaribe-muestreo.timer` cada 5 min |
| **Cierre diario del CSV** | — | `portocaribe-cierre.timer` a las 23:59 |
| **Captura DSCP** | — | `portocaribe-qos-captura.timer` cada 5 min (tcpdump UDP/5201) |
| **Asterisk** | SIP `5060/udp`, AMI `127.0.0.1:5038` | `asterisk.service` |
| **Portal de respaldo** | `https://192.168.100.60/` | `portal.service` + Apache `:443` |
| **Recolección SSH** | hacia VM2 en cada muestra | clave `monitor` + wrapper cerrado |

Credenciales demo del portal: **`cliente.demo` / `Porto2026*`**.
El certificado TLS es autofirmado (SAN con `portal.portocaribe.local`, `localhost`,
`127.0.0.1` y `192.168.100.60`).

El secreto AMI **no está en el TOML ni en el repositorio**: se genera en
`/etc/monitor/ami.env` (600, root) y `portocaribe-monitor.service` lo carga con
`EnvironmentFile=-/etc/monitor/ami.env`.

---

## 2. Rutas en la máquina

| Elemento | Ruta | Propietario |
|---|---|---|
| Código del monitor | `/opt/portocaribe-monitor/monitor/` | `root:root` |
| Configuración del monitor | `/etc/monitor/monitor.toml` | `root:root` |
| Inventario (dimensión) | `/etc/monitor/inventario.csv` | `root:root` |
| Clave SSH del monitor | `/etc/monitor/id_ed25519` | `monitor:monitor` (600) |
| `known_hosts` de VM2 | `/etc/monitor/known_hosts` | `root:root` (644) |
| `pgpass` | `/etc/monitor/pgpass` | `monitor:monitor` (600) |
| Secreto AMI | `/etc/monitor/ami.env` | `root:root` (600) |
| Dataset | `/var/lib/portocaribe-monitor/datos/` | `monitor:monitor` |
| · JSONL | `datos/raw/AAAA-MM-DD/HHMMSS_<run_id>.jsonl` | |
| · CSV | `datos/csv/metricas_AAAA-MM-DD.csv` | |
| · snapshots VM2 | `datos/entradas/vm2/` | |
| · captura QoS | `datos/capturas/qos.pcap` | `monitor` |
| Configuración de Asterisk | `/etc/asterisk/{pjsip,manager,extensions,cdr}.conf` | `asterisk:asterisk` |
| CDR | `/var/log/asterisk/cdr-csv/Master.csv` | `asterisk:asterisk` |
| Portal de respaldo | `/opt/portal/portal/`, `/etc/portal/portal.toml` | `root:root` |

---

## 3. Cómo se generó el despliegue

Artefactos en [`despliegue/vm1/`](vm1/) y [`despliegue/comun/`](comun/):

```
despliegue/vm1/
├── install.sh                      # base: usuario, código, Apache, TLS, timers
├── packages.sh                     # iperf3, tcpdump, psql, Asterisk (bullseye)
├── install-asterisk.sh             # SIP/AMI/CDR + secreto AMI
├── postconfig.sh                   # clave SSH, known_hosts, pgpass, QoS, TOML
├── asterisk/{pjsip,manager,extensions}.conf
├── systemd/portocaribe-qos-captura.{service,timer}
├── etc/{monitor.toml,portal.toml,apache-portal.conf}
└── usr/local/bin/portocaribe-snapshots-local
```

```bash
# desde el equipo de trabajo
tar czf pa6.tgz despliegue monitor portal tests_monitor inventario.csv monitor.toml
scp pa6.tgz vboxuser@192.168.100.60:/tmp/
ssh vboxuser@192.168.100.60
mkdir -p /tmp/pa6desp && tar xzf /tmp/pa6.tgz -C /tmp/pa6desp
su -
bash /tmp/pa6desp/despliegue/vm1/packages.sh       # repos de red + paquetes
bash /tmp/pa6desp/despliegue/vm1/install.sh        # base (idempotente)
bash /tmp/pa6desp/despliegue/vm1/install-asterisk.sh
bash /tmp/pa6desp/despliegue/vm1/postconfig.sh     # requiere VM2 ya instalada
```

> **Asterisk y Debian 12.** `asterisk` fue retirado de bookworm. `packages.sh` añade
> bullseye con pin 100 y lo instala con `-t bullseye` (Asterisk 16.28), sin degradar el
> resto del sistema. Es una deuda técnica anotada en [`PENDIENTES.md`](PENDIENTES.md).
>
> **`su -` obligatorio.** El usuario `vboxuser` no está en `sudoers`; para ejecutar como
> root desde un script no interactivo se usa
> `script -qec "su -c '…'" /dev/null` (ver `despliegue/diagnostico/`).

---

## 4. Operación diaria

```bash
# muestra manual (como root)
systemctl start portocaribe-monitor.service

# estado y programación
systemctl list-timers --all | grep portocaribe
systemctl status portal apache2 asterisk portocaribe-muestreo.timer

# como usuario monitor
cd /opt/portocaribe-monitor
runuser -u monitor -- python3 -m monitor validate  --config /etc/monitor/monitor.toml
runuser -u monitor -- python3 -m monitor recolectar --config /etc/monitor/monitor.toml --host vm2
runuser -u monitor -- python3 -m monitor export --config /etc/monitor/monitor.toml --fecha 2026-11-11
runuser -u monitor -- python3 -m monitor prune --config /etc/monitor/monitor.toml

# Asterisk
asterisk -rx "core show version"
asterisk -rx "manager show user monitor"
asterisk -rx "channel originate Local/1000@demo application Wait 2"   # genera CDR
tail -3 /var/log/asterisk/cdr-csv/Master.csv
```

> La muestra manual necesita el secreto AMI:
> `set -a; . /etc/monitor/ami.env; set +a` antes de `runuser … -m monitor run`.
> El timer lo carga solo desde la unidad.

### 4.1 Logs y datos

```bash
journalctl -u portocaribe-monitor --since today --no-pager
journalctl -u portocaribe-qos-captura -n 20 --no-pager
journalctl -u asterisk -n 50 --no-pager
tail -30 /var/log/apache2/portal-error.log
```

El monitor no escribe archivo propio: systemd captura su salida en el journal. Cada sonda
deja una línea con su duración y el conteo de estados; `--json-logs` produce una línea
JSON por registro.

Traer datos al PC:

```powershell
scp vboxuser@192.168.100.60:/var/lib/portocaribe-monitor/datos/csv/metricas_2026-11-11.csv .
scp -r vboxuser@192.168.100.60:/var/lib/portocaribe-monitor/datos/raw/2026-11-11 .
```

---

## 5. Qué mide hoy VM1

| Módulo | Estado | Fuente |
|---|---|---|
| **PortalWeb** | activo | HTTPS a `https://192.168.100.59/` + snapshot de Apache de VM2 |
| **Base de datos** | activo | TCP 5432 + `psql SELECT 1` contra VM2 |
| **VoIP** | activo | SIP OPTIONS 5060, AMI 5038 y CDR local |
| **QoS** | activo | `iperf3` UDP 20M con DSCP EF contra VM2 + pcap |
| **Seguridad** | activo | snapshots de VM2 (iptables, fail2ban, auth, kernel, netstat/SNMP) |
| **DHCP** | activo | snapshots de VM2 (estado y leases) |
| **Cámaras** | deshabilitado | no hay cámaras/VLAN 30 en la red del aula |

Una muestra completa reciente dejó **39 filas, todas OK** (0 con problema).

---

## 6. Verificación ejecutada (2026-11-11 18:42 -05)

| Comprobación | Resultado |
|---|---|
| `portal`, `apache2`, `asterisk`, timers | `active` |
| `https://192.168.100.59/` desde VM1 | `200`, TLS 1.3 |
| `psql SELECT 1` como `monitor` | OK (PostgreSQL 15.19) |
| SIP OPTIONS | `401` (Asterisk responde) |
| AMI `CoreShowChannels` | OK, 0 canales |
| CDR del día | 8 llamadas `ANSWERED` de 2 s |
| `iperf3` + captura DSCP | 20 Mbps, 3998/4000 paquetes DSCP 46 |
| Seguridad | deltas VLAN30/40 (+5/+6/+4/+4) y 1 ban de fail2ban |
| DHCP | 1 lease activo (`10.30.60.100`) |
| `export` dos veces | mismo SHA-256 (`88e77c47…b451ac`) |
| JSONL del día | 19 archivos; 15 desde las 18:00 |
| Pruebas | **32/32** en Linux |
| Señal `SIGTERM` | JSONL escrito y salida **1** |

Scripts en [`despliegue/diagnostico/`](diagnostico/): `verificacion-vm1.sh`,
`corrida-completa.sh`, `ver-jsonl.sh`, `probar-recoleccion.sh`, `senales2.sh`,
`generar-trafico-vlan.sh`, `ami-permisos.sh`, `cdr-*.sh`.

---

## 7. Correcciones aplicadas al código

| Síntoma | Causa | Corrección |
|---|---|---|
| `AttributeError: 'function' object has no attribute 'client'` | `sondas.py` definía `http(...)` y tapaba el módulo `http.client` | importar como `http_cliente` |
| AMI respondía `Permission denied` | `CoreShowChannels` exige la clase de **escritura** `system` | `write = system` en `manager.conf` |
| CDR «sin llamadas hoy» | `Master.csv` de Asterisk **no trae cabecera** y `csv.DictReader` la inventaba | parser por posición con detección opcional de cabecera |
| CDR con hora UTC | Debian trae `usegmtime=yes` en `[csv]` de `cdr.conf` | `sed` a `usegmtime=no` en `install-asterisk.sh` |
| Reglas de fail2ban etiquetadas como `VLAN40_BLOCKED` | el módulo de seguridad comparaba **todas** las reglas | filtrar por `prefijos_iptables` antes de calcular deltas |

---

## 8. Pendientes y advertencias

> El detalle completo está en [`PENDIENTES.md`](PENDIENTES.md).

- **Cámaras:** sin equipos en la VLAN 30; el módulo queda deshabilitado.
- **Certificado autofirmado:** sustituir por CA/dominio para producción.
- **IP dinámica:** si `enp0s3` cambia, hay que regenerar el SAN, el `known_hosts` y el
  `pgpass`.
- **Sin backups** de `portal.db`, PostgreSQL ni del dataset.
- **Nadie vigila al monitor:** falta una alerta cuando `run` devuelve 1 o 3.
- **Asterisk de bullseye:** deuda técnica mientras bookworm no lo tenga.

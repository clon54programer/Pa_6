# Pendientes del proyecto PortoCaribe

Estado al **2026-11-11**, segundo sprint, sobre la red `192.168.100.0/24`:

| Máquina | IP | Rol |
|---|---|---|
| **VM1** | `192.168.100.60` | monitor + Asterisk (SIP/AMI/CDR) + portal de respaldo + captura QoS |
| **VM2** | `192.168.100.59` | portal principal (Apache/TLS) + PostgreSQL + fail2ban + iptables + DHCP |

> **Resumen:** la topología de dos VM ya existe y **todos los módulos del monitor miden
> datos reales** (portal, base de datos, VoIP, QoS, seguridad y DHCP). La recolección SSH
> funciona de punta a punta, la robustez del §11 está implementada y probada (32/32), y el
> dataset del día se está acumulando. Quedan fuera únicamente las **cámaras VLAN 30**
> (no hay hardware) y el **día completo de 24 h** con su tablero `.pbix`.

---

## 1. Qué se cerró en este sprint

### 1.1 Infraestructura

| Pendiente anterior | Estado | Evidencia |
|---|---|---|
| **VM2** con portal secundario | **Hecho** | `https://192.168.100.59/` → `200`, TLS 1.3, SAN con la IP nueva |
| **PostgreSQL** | **Hecho** | PostgreSQL 15.19, base `portocaribe`, rol `monitor`, `pg_hba` para `192.168.100.60/32`; `SELECT 1` desde VM1 |
| **fail2ban** | **Hecho** | jails `sshd` y `apache-auth`; un ban real de `203.0.113.50` visible en `fail2ban-client status sshd` |
| **iptables VLAN30/40** | **Hecho** | reglas `VLAN30-DROP:`/`VLAN40-DROP:` persistentes en `/etc/iptables/rules.v4`, con LOG al kernel y contadores |
| **DHCP** | **Hecho** | `isc-dhcp-server` en `dummy0` (10.30.50.5/24) y un **arrendamiento real** `10.30.60.100` vía veth + netns (aislado de la red del aula) |
| **Asterisk / VoIP** | **Hecho** | Asterisk 16.28 en VM1: SIP 5060, AMI 5038 (usuario `monitor`), `Master.csv` con llamadas reales; CDR en hora local |
| **QoS** | **Hecho** | `iperf3` cliente en VM1 y servidor en VM2:5201, marcado DSCP EF (`-S 0xB8`) y captura `tcpdump` cada 5 min → 3998/4000 paquetes DSCP 46 |

### 1.2 Recolección SSH (F0/F8)

| Pendiente | Estado | Evidencia |
|---|---|---|
| Clave ed25519 del monitor | **Hecho** | `/etc/monitor/id_ed25519` (600, `monitor:monitor`) |
| `authorized_keys` con `from=`, `restrict`, `command=` | **Hecho** | `/var/lib/portocaribe-monitor/.ssh/authorized_keys` en VM2 |
| Wrapper `monitor-readonly` | **Hecho** | `/usr/local/bin/monitor-readonly` con las 11 recetas cerradas |
| `sudoers` acotado | **Hecho** | `/etc/sudoers.d/monitor` validado con `visudo -cf` |
| `known_hosts` fijado | **Hecho** | huella `SHA256:bqVa5D8xo8MW9v44fw9Z2wZZ7gkYel7+7G0CnRd5f8k` |
| `recolectar --host vm2` | **Hecho** | 10 snapshots traídos en una corrida (Apache, iptables, fail2ban, auth, kern, netstat, snmp, leases, estado) |

### 1.3 Robustez del monitor (§11)

| Carencia anterior | Estado | Dónde |
|---|---|---|
| Reintentos con backoff 0,5 s / 1 s + jitter | **Hecho** | `monitor/reintentos.py`, aplicado en todas las sondas |
| SIGTERM/SIGINT | **Hecho** | `runner._instalar_manejadores`; `kill -TERM` escribe el JSONL y sale con **1** |
| `timeout_total_s = 120` | **Hecho** | `deadline` por corrida, cancelación y filas `ERROR` para lo no terminado |
| Verificación NTP | **Hecho** | `sondas.ntp_sincronizado`; el resumen muestra `ntp=sincronizado` |
| `inventario.csv` como dimensión | **Hecho** | `monitor/inventario.py`; nombre/VLAN/zona salen del CSV y el TOML avisa si lo contradice |
| `--json-logs` | **Hecho** | `cli.py`, formateador JSON de una línea |
| Compresión `.gz` en `prune` | **Hecho** | `escritura.podar` comprime JSONL de más de `comprimir_dias` (7) y `export` lee `.jsonl.gz` |
| `recolectar` en paralelo (máx. 8) | **Hecho** | `recoleccion.MAX_PARALELO = 8` con `ThreadPoolExecutor` |

### 1.4 Calidad

- **32/32 pruebas** en Linux (`python3 -m unittest discover -s tests_monitor`), incluidas
  las nuevas: sonda HTTP real con `ThreadingHTTPServer`, reintentos, deadline/sondas
  interrumpidas, compresión `.gz` y lectura de inventario.
- La sonda HTTP que provocó el bug de `http.client` en el primer sprint ya tiene prueba.

### 1.5 Entrega para Power BI

- [`powerbi/README.md`](powerbi/README.md): carga del CSV, modelo (Metricas, Calendario,
  Inventario), páginas sugeridas y refresco.
- [`powerbi/medidas.dax`](powerbi/medidas.dax): disponibilidad, latencia P95, pérdida,
  jitter, bloqueos VLAN30/40, baneos, llamadas y frescura del dataset.

---

## 2. Evidencia verificada (2026-11-11, 18:42 -05)

| Comprobación | Resultado |
|---|---|
| Muestra real completa | **39 filas, 39 OK, 0 con problema**, `rc=0`, `ntp=sincronizado` |
| Módulos en la muestra | PortalWeb (2), BaseDatos (1), VoIP (10), QoS (3), Seguridad (22), DHCP (1) |
| `export` dos veces | mismo SHA-256 `88e77c47…b451ac` → **idempotente** |
| JSONL del día | **19** archivos; **15 desde las 18:00** (timers + corridas manuales) |
| CSV del día | 130 líneas (cabecera + **129 filas**) |
| Snapshots de VM2 | 10 archivos en `datos/entradas/vm2/` |
| Captura QoS | `qos.pcap` de 447 938 bytes; 3998/4000 paquetes con DSCP 46 |
| Servicios VM1 | `portal`, `apache2`, `asterisk`, muestreo, cierre y captura: **active** |
| Servicios VM2 | `postgresql`, `fail2ban`, `isc-dhcp-server`, `apache2`, `portal`, `iperf3`, veth DHCP: **active** |
| Seguridad | reglas VLAN con contadores, 1 ban de fail2ban y eventos `VLAN30_BLOCKED`/`VLAN40_BLOCKED` en el CSV |
| Señales | `SIGTERM` a mitad de corrida → JSONL escrito, `interrumpida=si`, salida **1** |
| Pruebas | **32/32 OK** |

---

## 3. Lo que sigue pendiente

| Pendiente | Por qué sigue abierto | Cómo se cierra |
|---|---|---|
| **Cámaras VLAN 30** | No hay cámaras ni VLAN 30 en la red del aula; `camaras.habilitado = false` | Conectar los equipos, poner sus IPs en `inventario.csv` y activar el módulo |
| **Día completo (288 JSONL)** | El muestreo arrancó el 2026-11-11 a las 18:30; el primer día completo es el **2026-11-12** | Dejar correr los timers y ejecutar `export --fecha 2026-11-12` |
| **Tablero `.pbix`** | El repo entrega medidas y guía; el binario se arma en Power BI Desktop | Montar el modelo con [`powerbi/`](powerbi/) sobre el CSV real |
| **Certificado TLS** | Autofirmado (SAN con `192.168.100.59`/`.60`) | Sustituir por CA o dominio real |
| **Backups** | Sin respaldo de `portal.db`, PostgreSQL ni el dataset | `pg_dump` diario + copia del CSV/JSONL |
| **Alertas del monitor** | Si un timer falla solo queda el journal | Healthcheck/correo cuando `run` devuelva 1 o 3 |
| **IP fija** | `enp0s3` sigue por DHCP; si cambia, el SAN y `known_hosts` dejan de cuadrar | Reserva DHCP o IP estática |
| **Portal en PostgreSQL** | El portal sigue con SQLite; PostgreSQL atiende el módulo de BD | Migrar `datos.py` si el alcance lo pide |
| **Asterisk 16 (bullseye)** | Debian 12 retiró `asterisk`; se instaló el build de bullseye con pin 100 | Migrar a un Asterisk de bookworm/trixie o compilarlo |

> **Credenciales:** las máquinas comparten el usuario de laboratorio y la contraseña de
> root del aula. No se versionan en el repositorio; el acceso del monitor usa su propia
> clave ed25519 y `sudo` acotado.

---

## 4. Criterios de terminado v1 (§12)

| # | Criterio | Estado |
|---|---|---|
| 1 | `run --simulate` con esquema v1 y ≥1 fila por módulo | **Cumple** (14 filas, 6 módulos, 27 columnas) |
| 2 | `export` dos veces da el mismo SHA-256 | **Cumple** (verificado en VM1) |
| 3 | Objetivo inexistente → `OFFLINE`/`ERROR`, sin traza | **Cumple** |
| 4 | Snapshot sin actualizar → `STALE` | **Cumple** (cubierto por `leer_snapshot`) |
| 5 | Releer `auth.log` no duplica eventos | **Cumple** (huella estable) |
| 6 | Deltas de `iptables` suman lo esperado | **Cumple**: +5/+6/+4/+4 paquetes tras inyectar tráfico VLAN30/40 |
| 7 | `unittest discover` sin red | **Cumple** (32/32 en Linux) |
| 8 | Solo stdlib en `monitor/` | **Cumple** (sin dependencias externas; `pyproject.toml` sin `requires`) |
| 9 | Una hora de muestreo deja 12 JSONL | **En curso**: timers activos cada 5 min; 15 JSONL desde las 18:00 (incluye corridas manuales) |
| 10 | README con configuración, programación, SSH, columnas y límites | **Cumple** (README, `monitor/README`, `DESPLIEGUE_VM1/VM2`) |

---

## 5. Cómo verificar cada bloque

```bash
# VM1 (192.168.100.60), como root
cd /opt/portocaribe-monitor
runuser -u monitor -- python3 -m monitor validate --config /etc/monitor/monitor.toml
runuser -u monitor -- env ASTERISK_AMI_SECRET="$(sed 's/.*=//' /etc/monitor/ami.env)" \
  python3 -m monitor run --config /etc/monitor/monitor.toml
runuser -u monitor -- python3 -m monitor recolectar --config /etc/monitor/monitor.toml --host vm2
runuser -u monitor -- python3 -m monitor export --config /etc/monitor/monitor.toml
systemctl list-timers --all | grep portocaribe
```

```bash
# VM2 (192.168.100.59), como root
systemctl is-active postgresql fail2ban isc-dhcp-server apache2
fail2ban-client status sshd
iptables-save -c | grep -E 'VLAN(30|40)-DROP'
grep -c 'binding state active' /var/lib/dhcp/dhcpd.leases
```

Scripts reproducibles en [`despliegue/diagnostico/`](despliegue/diagnostico/):
`verificacion-vm1.sh`, `verificacion-vm2.sh`, `corrida-completa.sh`,
`probar-recoleccion.sh`, `senales2.sh`, `generar-trafico-vlan.sh` y `ban-prueba.sh`.

---

## 6. Notas de operación

- **`su -` sigue siendo obligatorio** para root: el usuario de laboratorio no está en
  `sudoers`; desde un script no interactivo se usa `script -qec "su -c '…'"`.
- **Repositorios APT**: las VM no traen red en `/etc/apt/sources.list` (solo el ISO), así
  que [`despliegue/comun/apt-lab.sh`](despliegue/comun/apt-lab.sh) añade
  `deb.debian.org` y `security.debian.org` por HTTPS con pin de bullseye para Asterisk.
- **DHCP aislado**: `isc-dhcp-server` escucha en `dummy0` (10.30.50.5/24) y en el veth
  `10.30.60.1/24`; **nunca** en `192.168.100.0/24`, para no competir con el router del aula.
- **Tráfico de prueba VLAN**: `generar-trafico-vlan.sh` envía paquetes con origen
  `10.30.30.12`/`10.30.40.77` a VM2 para ejercitar las reglas; es tráfico sintético de
  laboratorio, no una medición de cámaras reales.
- **Portal de respaldo**: VM1 conserva su portal+TLS; el monitor mide el de VM2 (principal).

# Plan de implementación — Monitor PortoCaribe (Python, stdlib-first) — v3.1

> **Decisiones confirmadas (2026-11-06)**
>
> - **Ejecución:** una VM de monitoreo dentro de la topología.
> - **Servicios:** Asterisk, fail2ban y DHCP corren en VMs reales.
> - **Entrega:** CSV + JSONL. PostgreSQL no es destino de carga.
> - **Muestreo:** cada **5 minutos**; cierre y export del CSV **una vez al día a las 23:59**.
> - **Alcance:** solo el dataset; las medidas y gráficos de Power BI los elabora otra persona.

Documento de trabajo para construir el script descrito en
[`plan_de_script_python.md`](plan_de_script_python.md). El objetivo es un monitor
ejecutable por CLI, sin dependencias obligatorias fuera de la biblioteca estándar,
que produzca un dataset plano listo para Power BI.

---

## 1. Objetivo y alcance

**Objetivo.** Implementar `python -m monitor` (Python ≥ 3.11) que muestree cada 5
minutos la infraestructura de PortoCaribe y deje:

- `data/raw/YYYY-MM-DD/HHMMSS_<run_id>.jsonl` — evidencia cruda, una línea por resultado.
- `data/csv/metricas_YYYY-MM-DD.csv` — dataset del día, reconstruido a las 23:59.

**Dentro del alcance**

- Sondas activas por red: ICMP, TCP (RTSP 554, PostgreSQL 5432), HTTP/HTTPS, DNS y SIP 5060.
- Asterisk por **AMI** (TCP 5038) y CDR publicado desde la VM de telefonía.
- Lectura de archivos publicados por las VMs reales: estado de Apache, `fail2ban`,
  `auth.log`, log de kernel, contadores de `iptables`, `/proc/net/*` y leases de DHCP.
- QoS opcional: `iperf3 -J` y DSCP a partir de capturas `pcap`.
- Subcomando `publicar` para que cada VM de servicio deposite sus datos locales en la
  carpeta compartida (mismo paquete, sin dependencias).
- Modo `--simulate` para demo e informe sin topología levantada.
- Pruebas con `unittest` y fixtures, sin red.

**Fuera del alcance**

- Carga a PostgreSQL, dashboard, medidas DAX o gráficos (los asume otra persona).
- Construcción de la topología, reglas de firewall o servicios.
- Agente distribuido con demonio: el muestreo se dispara por cron/timer.

**Supuestos**

1. VM Linux con Python 3.12 y `tomllib` (verificado: 3.12.3).
2. La VM tiene ruta a las VLAN 30/40/50/60; se valida en F0 con `ip route` y `ping`.
3. Asterisk, fail2ban, iptables y DHCP existen en VMs reales; sus discos no son
   accesibles desde la VM de monitoreo (ver §8).
4. `ping` y `psql` existen; `iperf3`, `tcpdump` y `fail2ban-client` pueden faltar.
5. Zona horaria `America/Bogota` (sin horario de verano); relojes sincronizados por NTP.
6. Muestreo cada 5 min por cron; export diario a las 23:59.

---

## 2. Principios de diseño

1. **Stdlib primero.** Todo se resuelve con la biblioteca estándar; el proyecto queda
   con `dependencies = []`.
2. **Adaptadores con degradación.** Toda herramienta o archivo externo se encapsula;
   si falta o está viejo, la sonda devuelve `SKIPPED`/`STALE` con motivo, no una excepción.
3. **Configuración declarativa.** IPs, rutas y umbrales en TOML; el código no contiene
   infraestructura ni credenciales.
4. **Un fallo no detiene la corrida.** Timeout por sonda, reintentos acotados y
   `try/except` por objetivo; siempre se escribe resumen y código de salida.
5. **Crudo inmutable + derivado reconstruible.** El JSONL es la evidencia; el CSV del
   día se regenera desde los JSONL (idempotente, sin base de datos).
6. **Procedencia explícita.** Cada fila declara si el dato vino de red, de AMI, de un
   archivo publicado o de una simulación (`fuente`).
7. **Deduplicación estable.** Las métricas se identifican por corrida; los eventos de
   log, por su contenido, para que releer un archivo no duplique filas.
8. **Seguro por defecto.** `subprocess` sin `shell=True`, secretos por entorno,
   timeouts explícitos, sin volcar cuerpos de respuesta a logs.

---

## 3. Arquitectura

```
 config/monitor.toml + inventario.csv
                │
          cli.py (argparse)
                │
          runner.py ── ThreadPoolExecutor (sondas en paralelo)
                │
   ┌────────────┼───────────────┬──────────────┬──────────────┐
 cámaras      portal        servicios       QoS          seguridad
 (ICMP/TCP)  (HTTP/TLS)   (PG/SIP/AMI)  (iperf3/pcap)  (red/archivos)
   └────────────┴───────────────┴──────────────┴──────────────┘
                │  Resultado (dataclass) normalizado
                ▼
   JSONL por corrida (crudo) ──► CSV del día (23:59, reconstruido)
                ▲
                │  /srv/monitor/entradas (NFS, solo lectura para el monitor)
   ┌────────────┴─────────────┬──────────────────┬─────────────────┐
 VM Asterisk              VM firewall        VM gateway        VM1 portal
 cdr.csv                  iptables.save      dhcpd.leases      apache.txt
                          fail2ban.*         dhcp_estado.json
                          auth/kern.log
                          netstat/snmp
                          (AMI directo: TCP 5038)
```

**Capas**

| Capa | Responsabilidad | Archivos |
|---|---|---|
| Presentación | CLI, subcomandos, códigos de salida | `cli.py`, `__main__.py` |
| Dominio | Modelos, validación, registro de sondas | `modelos.py`, `config.py` |
| Sondas | Medición pura, sin escritura | `sondas/*.py` |
| Publicación | Recolectar datos locales en cada VM de servicio | `publicacion.py` |
| Salida | JSONL crudo y reconstrucción del CSV | `writers.py`, `exportacion.py` |
| Soporte | Lock, estado de contadores, reintentos, tiempo | `bloqueo.py`, `utils/*.py` |

---

## 4. Mapa de la biblioteca estándar

| Necesidad | Módulo stdlib | Uso concreto |
|---|---|---|
| CLI y subcomandos | `argparse` | `run`, `export`, `publicar`, `prune`, `validate` |
| Configuración | `tomllib` | Lectura de `monitor.toml` (solo lectura) |
| Modelos y enums | `dataclasses`, `enum`, `typing` | `Resultado`, `Objetivo`, `Estado` |
| Tiempo | `datetime`, `zoneinfo`, `time` | UTC + local; `perf_counter()` para latencias |
| Concurrencia | `concurrent.futures`, `threading` | Sondas I/O en paralelo; evento de parada |
| ICMP | `subprocess` | `ping -n -q -c 4 -W 1` (stdlib no hace ICMP sin root) |
| TCP | `socket` | 554, 5432, 5060/TCP |
| UDP / SIP | `socket`, `secrets` | OPTIONS a Asterisk; `branch` y `Call-ID` aleatorios |
| AMI Asterisk | `socket` | Texto sobre TCP 5038 (`CoreShowChannels`) |
| HTTP/HTTPS | `http.client`, `ssl` | Código, TTFB, tiempo total, versión TLS |
| DNS | `socket.getaddrinfo` | Disponibilidad y latencia de resolución |
| CSV / JSON | `csv`, `json` | Dataset, evidencia y estado de contadores |
| Archivos | `pathlib`, `tempfile`, `os.replace`, `shutil` | Escritura atómica, `which()` y copia |
| Estado | `json`, `os.stat` | Deltas de contadores y frescura por `mtime` |
| Logs | `logging`, `logging.handlers` | `RotatingFileHandler` (5 MB × 5) |
| Instancia única | `fcntl` | `flock` sobre `data/.lock` |
| Apagado limpio | `signal` | SIGINT/SIGTERM → cerrar y escribir resumen |
| IDs y huellas | `uuid`, `hashlib` | `run_id`; SHA-256 para deduplicar |
| IPs y VLANs | `ipaddress` | Validar inventario y mapear CIDR → VLAN |
| Capturas pcap | `struct` | Leer cabeceras y extraer DSCP sin `tshark` |
| Pruebas | `unittest`, `unittest.mock` | Fixtures y servidores locales |
| Sistema | `os`, `sys`, `subprocess` | Comandos de los publicadores y `psql` |

**Dependencias de terceros: ninguna.** No hay `psycopg`, `scapy`, `requests` ni
`pandas`; PostgreSQL se monitorea con `psql`, no se usa como destino.

---

## 5. Dependencias externas y degradación

| Herramienta | Uso | Si falta |
|---|---|---|
| `ping` (iputils) | Estado y RTT de cámaras/servidores | Sonda `SKIPPED`; el resto continúa |
| `psql` | `SELECT 1` y estado de la base | Se reporta solo el puerto TCP 5432 |
| `iperf3` (–J) | Pérdida, jitter, ancho de banda | `SKIPPED`, columnas QoS nulas |
| `tcpdump` | Captura pcap para DSCP | `SKIPPED`; QoS queda solo con iperf3 |
| `iptables-save` | Solo en la VM que publica | Publica `iptables -L -v -n -x` |
| `fail2ban-client` | Solo en la VM que publica | Publica el log de fail2ban |
| `journalctl` | Solo en la VM que publica | Publica `/var/log/*.log` |
| `systemctl` | Solo en la VM que publica (Apache/DHCP) | Publica el estado como texto |

Cada sonda declara `requiere: tuple[str, ...]`; el runner consulta `shutil.which()`
antes de ejecutarla y registra el motivo del `SKIPPED`.

---

## 6. Modelo de datos

### 6.1 Tabla canónica (una fila por sonda y objetivo)

Se conservan los campos pedidos en el documento y se agregan columnas opcionales.

| Campo | Tipo | Obligatorio | Ejemplo / notas |
|---|---|---|---|
| `timestamp` | DATETIME local | sí | `2026-11-06 23:55:07` |
| `timestamp_utc` | DATETIME UTC | sí | `2026-11-07 04:55:07` |
| `run_id` | TEXT | sí | UUID4; prefijo `sim-` en modo simulado |
| `modulo` | TEXT | sí | `Camaras`, `PortalWeb`, `BaseDatos`, `VoIP`, `QoS`, `Seguridad` |
| `recurso_target` | TEXT | sí | IP o nombre del recurso |
| `nombre_recurso` | TEXT | no | `Cam_Muelle_1`, `Portal_Clientes` |
| `vlan` | INTEGER | no | 30, 40, 50, 60 |
| `zona` | TEXT | no | `muelles`, `perimetro`, `core` |
| `estado` | TEXT | sí | `ONLINE`, `OFFLINE`, `OK`, `DEGRADED`, `ERROR`, `DROPPED`, `SKIPPED`, `STALE` |
| `tiempo_respuesta_ms` | REAL | no | Latencia ICMP o tiempo HTTP total |
| `perdida_paquetes_pct` | REAL | no | 0–100, dos decimales |
| `jitter_ms` | REAL | no | VoIP/video |
| `ancho_banda_mbps` | REAL | no | iperf3 |
| `http_status` | INTEGER | no | 200, 500, 504 |
| `puerto` | INTEGER | no | 554, 5060, 5432 |
| `ip_origen` | TEXT | no | IP de origen en un evento de seguridad |
| `ip_destino` | TEXT | no | IP de destino en un evento de seguridad |
| `evento_seguridad` | TEXT | no | `SSH_FAIL`, `VLAN30_BLOCKED`, `FAIL2BAN_BAN`, `SYN_FLOOD` |
| `sip_code` | INTEGER | no | 200, 401, 403, 408 |
| `llamadas_activas` | INTEGER | no | Conteo simultáneo |
| `duracion_llamada_s` | REAL | no | Desde el CDR |
| `dscp` | INTEGER | no | 46 (EF), 34 (AF41) |
| `paquetes_delta` | INTEGER | no | Paquetes del intervalo en una regla de firewall |
| `bytes_delta` | INTEGER | no | Bytes del intervalo en una regla de firewall |
| `detalle` | TEXT | no | Texto corto (≤200 caracteres) para diagnóstico |
| `fuente` | TEXT | sí | `ping`, `tcp`, `http`, `psql`, `sip`, `ami`, `asterisk-cdr`, `iperf3`, `pcap`, `archivo`, `simulado` |
| `schema_version` | INTEGER | sí | `1` |

**Reglas**

- Unidades fijas: ms, %, Mbps, segundos; sin sufijos en los valores.
- `estado` es texto enumerado, nunca booleano (mejor para Power BI).
- `timestamp` local sin offset (para el modelo) + `timestamp_utc` (auditoría).
- En eventos de seguridad, `timestamp` es la **hora del evento** (del log), no la de
  recolección; así el gráfico refleja cuándo ocurrió el intento.
- Celdas no aplicables quedan vacías (`null` en JSONL), no en cero.

### 6.2 Dimensión `inventario.csv`

| Campo | Ejemplo |
|---|---|
| `recurso` | `10.30.30.12` |
| `nombre` | `Cam_Muelle_1` |
| `tipo` | `camara`, `web`, `db`, `sip`, `dns` |
| `vlan` | `30` |
| `zona` | `muelles` |
| `puerto` | `554` |
| `criticidad` | `alta` |
| `habilitado` | `true` |

Permite que Power BI calcule disponibilidad por zona/VLAN sin repetir metadatos en
cada fila.

### 6.3 JSONL, CSV y reconstrucción

Cada corrida escribe su JSONL en un archivo temporal y lo renombra con `os.replace`
cuando termina; un lector nunca ve una corrida a medias.

```json
{"huella":"9a1e...","run_id":"4f1c...","timestamp":"2026-11-06 23:55:07","timestamp_utc":"2026-11-07 04:55:07","modulo":"Camaras","recurso_target":"10.30.30.12","nombre_recurso":"Cam_Muelle_1","vlan":30,"zona":"muelles","estado":"ONLINE","tiempo_respuesta_ms":2.41,"perdida_paquetes_pct":0.0,"jitter_ms":null,"ancho_banda_mbps":null,"http_status":null,"puerto":554,"ip_origen":null,"ip_destino":null,"evento_seguridad":null,"sip_code":null,"llamadas_activas":null,"duracion_llamada_s":null,"dscp":null,"paquetes_delta":null,"bytes_delta":null,"detalle":"4/4 paquetes; RTSP 554 abierto","fuente":"ping","schema_version":1}
```

- `huella` es interna (no va al CSV): identifica la fila para deduplicar.
  - Métricas: `sha256(run_id|modulo|recurso|timestamp_utc|fuente)`.
  - Eventos de log: `sha256(fuente|timestamp_evento|linea_normalizada)`, sin `run_id`,
    para que releer el mismo archivo no duplique el evento.
- JSONL: `json.dumps(..., ensure_ascii=False)`, `flush` + `os.fsync`, luego `os.replace`.
- CSV: `utf-8-sig` (Excel y Power BI), `csv.DictWriter`, encabezado fijo, `\r\n`.
- `export --fecha YYYY-MM-DD` lee todos los JSONL de esa fecha, deduplica por
  `huella`, ordena por `timestamp_utc, modulo, recurso` y reescribe el CSV completo.
- Escritura atómica: temporal en el mismo directorio + `os.replace`.
- Exportar dos veces la misma fecha produce un CSV idéntico (mismo SHA-256).

`data/` queda fuera de git (`.gitignore`) salvo `data/.gitkeep`.

---

## 7. Módulos y sondas

| Módulo | Sonda | Técnica stdlib | Salida principal |
|---|---|---|---|
| `Camaras` | Ping | `subprocess` + `ping -n -q -c 4 -W 1` | `estado`, `tiempo_respuesta_ms`, `perdida_paquetes_pct` |
| `Camaras` | RTSP 554 | `socket.create_connection` | `estado`, `puerto`, latencia |
| `PortalWeb` | HTTP/HTTPS | `http.client` + `ssl` + `perf_counter` | `http_status`, tiempos, TLS |
| `PortalWeb` | Apache | Archivo publicado | `estado` |
| `BaseDatos` | PostgreSQL | `socket` + `psql -w -tAc "SELECT 1"` | `estado`, latencia |
| `VoIP` | SIP 5060 | UDP OPTIONS con `socket` | `sip_code`, `estado` |
| `VoIP` | Asterisk AMI | Texto sobre TCP 5038 | `llamadas_activas` |
| `VoIP` | CDR | `csv` sobre el archivo publicado | `duracion_llamada_s`, `sip_code` |
| `QoS` | iperf3 | `iperf3 -J` + `json` | `perdida_paquetes_pct`, `jitter_ms`, `ancho_banda_mbps` |
| `QoS` | DSCP | `tcpdump -w` + parser `struct` | `dscp` |
| `Seguridad` | iptables | `iptables-save -c` publicado | `evento_seguridad`, `paquetes_delta`, `bytes_delta` |
| `Seguridad` | fail2ban/SSH | Estado y logs publicados | `evento_seguridad`, IPs |
| `Seguridad` | Inundaciones | `/proc/net/*` y kernel publicados | `SYN_FLOOD`, `ICMP_FLOOD` |

### 7.1 Cámaras (VLAN 30)

- Ping con 4 paquetes y `LC_ALL=C`; pérdida y RTT desde la línea de resumen.
- `ONLINE` si responde al menos un paquete **y** el puerto 554 abre en < 3 s;
  `DEGRADED` si hay ICMP pero el puerto falla; `OFFLINE` si no hay ICMP.
- OPTIONS RTSP opcional: `OPTIONS rtsp://IP:554/ RTSP/1.0`; `200/401/403` = servicio vivo.

### 7.2 Portal web (VM1)

- Medición por etapas: DNS, conexión TCP, handshake TLS, TTFB y total.
- `DEGRADED` si el total supera 10 s (hipótesis del caso) o el código es 5xx;
  `OK` para 2xx/3xx.
- Apache: el publicador de VM1 deja `systemctl is-active apache2` en
  `portal/apache.txt`; el monitor lo lee y marca `OK`/`ERROR`. Si el archivo falta o
  está viejo, `SKIPPED`/`STALE`.
- Sin redirecciones automáticas (máximo 1 salto, configurable).

### 7.3 PostgreSQL como objetivo

- **Aclaración:** la base de datos es un servicio monitoreado, no el destino del
  dataset. No se escribe nada en PostgreSQL.
- TCP 5432 como chequeo rápido; si `psql` está, `SELECT 1` cronometrado con
  `PGCONNECT_TIMEOUT` y `PGPASSFILE` (600).
- DNS: `getaddrinfo` de un nombre de control y latencia.

### 7.4 VoIP

- SIP OPTIONS por UDP con retransmisión T1 (500 ms, 2 intentos); `200/401/403` = vivo.
- **AMI:** conectar a TCP 5038, `Login`, `Action: CoreShowChannels`, contar eventos
  `CoreShowChannel` hasta `CoreShowChannelsComplete`, `Logoff`. Es la vía limpia desde
  otra VM, sin SSH ni CLI local.
- **CDR:** el publicador copia `Master.csv` a `asterisk/cdr.csv`. El monitor lee el
  archivo completo (es pequeño), filtra por `start` y deduplica por `uniqueid`; el
  volumen de llamadas del proyecto no justifica offsets.
- Si AMI falla, solo queda la disponibilidad SIP; `llamadas_activas` y
  `duracion_llamada_s` quedan nulas (no se inventan).

### 7.5 QoS

- `iperf3 -c HOST -u -b 20M -t 10 -J`; leer `end.sum_received.loss_percent`,
  `.jitter_ms` y `end.sum_sent.bits_per_second`, tolerando variantes del JSON.
- DSCP sin `tshark`: `tcpdump -i IFACE -w captura.pcap -c 500` y parser propio con
  `struct` (magic `0xa1b2c3d4`/`0xa1b23c4d`, Ethernet + 802.1Q, IPv4, TOS → `tos >> 2`).
  Conteos por DSCP (EF=46, AF41=34); se descartan paquetes no-IP.
- Deshabilitada por defecto (genera tráfico); se ejecuta con `--solo qos` en ventana
  controlada.

### 7.6 Seguridad

- **iptables:** el publicador ejecuta `iptables-save -c` y el monitor parsea las reglas
  con contadores `[pkts:bytes]`; la clave es la especificación de la regla y el valor es
  el delta contra la muestra anterior. Se recomienda `-m comment --comment "VLAN30-DROP"`
  para identificar cada regla sin ambigüedad.
- **Paquetes bloqueados:** las reglas deben usar `-j LOG --log-prefix "VLAN30-DROP: "`;
  el parser busca ese prefijo en el log de kernel publicado y extrae IP origen/destino,
  puerto, interfaz y VLAN.
- **fail2ban:** se parsea el estado publicado (`Currently banned`, `Total banned`,
  `Banned IP list`) y el log (`Ban`, `Unban`) para los eventos con hora.
- **SSH:** líneas del log publicado (`Failed password for .* from (\S+)`), con la hora
  del propio log; se deduplican por huella estable.
- **Inundaciones:** `possible SYN flooding` en el log de kernel, `ListenOverflows`/
  `ListenDrops` de `/proc/net/netstat` y deltas de `/proc/net/snmp`, publicados desde la
  VM del firewall.

---

## 8. Servicios reales: AMI, carpeta compartida y publicadores

Las VMs de Asterisk, firewall, gateway y portal son reales, pero **la VM de monitoreo no
puede leer sus discos**. Por eso se combinan dos mecanismos:

1. **AMI** para lo que ya se expone por red (llamadas activas de Asterisk).
2. **Carpeta compartida** para los datos que solo existen en archivos locales (CDR,
   estado de Apache, `fail2ban`, `auth.log`, kernel, contadores de `iptables`,
   `/proc/net/*` y leases de DHCP).

### 8.1 Diseño de la carpeta compartida

- El **monitor** exporta `/srv/monitor/entradas` por NFS a las VMs de servicio
  (solo las IPs del laboratorio) y lo lee como directorio local.
- Cada VM de servicio ejecuta el subcomando `publicar` cada 5 minutos; este deja copias
  atómicas (`.tmp` + `os.replace`) en la carpeta.
- El monitor **solo lee**; nunca escribe en la carpeta.
- Los publicadores reescriben el archivo cada 5 minutos aunque el contenido no cambie,
  de modo que `mtime` indica la última publicación y no la última novedad.
- `frescura_max_s = 900`: si un archivo tiene más de 15 minutos sin publicarse, la sonda
  emite `STALE` con el motivo, en lugar de datos viejos disfrazados de actuales.

### 8.2 Qué publica cada VM

| VM | Perfil | Archivo en `/srv/monitor/entradas` | Origen local |
|---|---|---|---|
| Asterisk | `asterisk` | `asterisk/cdr.csv` | `/var/log/asterisk/cdr-csv/Master.csv` |
| VM1 portal | `portal` | `portal/apache.txt` | `systemctl is-active apache2` |
| Firewall (o `srv-core`) | `seguridad` | `seguridad/iptables.save` | `iptables-save -c` |
| Firewall | `seguridad` | `seguridad/fail2ban.txt` | `fail2ban-client status sshd` |
| Firewall | `seguridad` | `seguridad/fail2ban.log` | `/var/log/fail2ban.log` (cola) |
| Firewall | `seguridad` | `seguridad/auth.log` | `journalctl -u ssh` (cola) |
| Firewall | `seguridad` | `seguridad/kern.log` | `journalctl -k` (cola) |
| Firewall | `seguridad` | `seguridad/netstat.txt` | `/proc/net/netstat` |
| Firewall | `seguridad` | `seguridad/snmp.txt` | `/proc/net/snmp` |
| Gateway | `dhcp` | `dhcp/dhcpd.leases` | `/var/lib/dhcp/dhcpd.leases` |
| Gateway | `dhcp` | `dhcp/estado.json` | `systemctl is-active isc-dhcp-server` + `stat` |

### 8.3 AMI en Asterisk

- Habilitar en `/etc/asterisk/manager.conf` un usuario de solo lectura para las
  acciones necesarias (`CoreShowChannels`), con `permit` limitado a la IP de la VM de
  monitoreo:

  ```ini
  [monitor]
  secret = <secreto>
  read = call
  write = call
  permit = 10.30.50.5/255.255.255.255
  ```

- El secreto se pasa al monitor por variable de entorno (`ASTERISK_AMI_SECRET`), nunca
  en TOML ni en el repositorio. Si `AMI` no está habilitado, la sonda reporta `SKIPPED`.
- Validar permisos con `asterisk -rx "manager show user monitor"` antes de la entrega.

### 8.4 Subcomando `publicar`

Se ejecuta **en cada VM de servicio**, con el mismo paquete (copia del repo o montaje
de solo lectura) y sin dependencias externas:

```bash
python3 -m monitor publicar --perfil asterisk --destino /srv/monitor/entradas
python3 -m monitor publicar --perfil portal   --destino /srv/monitor/entradas
python3 -m monitor publicar --perfil seguridad --jail sshd --destino /srv/monitor/entradas
python3 -m monitor publicar --perfil dhcp     --destino /srv/monitor/entradas
```

Comportamiento:

- Ejecuta solo los comandos del perfil, con `subprocess` sin `shell=True`.
- Escribe cada archivo en `.tmp` y lo renombra al final; si un comando falla, deja el
  archivo anterior intacto y registra el error en el journal.
- No contiene lógica de análisis: solo copia/exporta datos crudos; el parseo y la
  normalización viven en el monitor y se prueban con fixtures.

Cron sugerido en cada VM (5 minutos, alineado con el muestreo):

```cron
*/5 * * * * root cd /opt/portocaribe-monitor && /usr/bin/python3 -m monitor publicar --perfil asterisk >> /var/log/monitor-publicar.log 2>&1
```

### 8.5 Lectura y deduplicación

- Cada corrida lee los archivos publicados completos; los logs vienen acotados a las
  últimas 5 000 líneas, así que el costo es bajo y no hay offsets que se invaliden
  cuando el publicador reemplaza el archivo.
- Los eventos de log se deduplican por `huella` estable (`fuente|timestamp|linea`), de
  modo que releer el mismo `auth.log` en cada muestra no infla el CSV.
- `iptables.save` se compara contra `data/estado/contadores.json` (clave = regla) para
  calcular `paquetes_delta` y `bytes_delta`; la primera corrida guarda la línea base y
  emite delta 0.
- Los eventos de seguridad usan la hora del log; si no se puede parsear, se usa la hora
  de recolección y se anota en `detalle`.
- El CDR se lee completo y se deduplica por `uniqueid`.

### 8.6 Alternativas si NFS no es viable

| Alternativa | Cuándo | Costo |
|---|---|---|
| NFS/SMB (recomendada) | laboratorio con VMs en la misma red | montar y exportar |
| `rsyslog` centralizado | solo logs (auth, kernel, fail2ban) | configurar clientes syslog |
| SSH puntual desde el monitor | no se quiere compartir carpeta | claves, `sudo`, más superficie |
| `scp` programado | copias diarias simples | no es tiempo real |

La lógica de sondas no cambia: solo cambia de dónde salen los archivos. Si no hay
ninguna fuente, el módulo queda `SKIPPED` y se documenta.

### 8.7 Seguridad

- La exportación NFS se limita por IP a las VMs del laboratorio; evitar
  `no_root_squash` si se puede publicar con un usuario dedicado.
- El monitor monta/lee en modo de solo lectura.
- El usuario AMI no tiene `command`, `system` ni `originate`; solo lo necesario para
  consultar canales.
- Los archivos publicados pueden contener IPs internas: no salen del laboratorio.

---

## 9. Configuración (TOML)

```toml
[general]
zona_horaria = "America/Bogota"
timeout_s = 5
timeout_total_s = 120
reintentos = 2
max_workers = 12
directorio_datos = "data"
retencion_dias = 180
intervalo_s = 300
frescura_max_s = 900
version_esquema = 1

[salida]
csv = true
jsonl = true
codificacion = "utf-8-sig"

[camaras]
habilitado = true
ping_paquetes = 4
rtsp_puerto = 554

[portal]
habilitado = true
url = "https://10.30.50.5/"
timeout_s = 15
umbral_degradado_s = 10.0
estado_apache = "/srv/monitor/entradas/portal/apache.txt"

[base_datos]              # objetivo monitoreado; no es destino de escritura
habilitado = true
host = "10.30.50.5"
puerto = 5432
base = "portocaribe"
usuario = "monitor"
pgpassfile = "/etc/monitor/pgpass"

[voip]
habilitado = true
host = "10.30.60.10"
sip_puerto = 5060
ami = true
ami_puerto = 5038
ami_usuario = "monitor"
ami_secreto_env = "ASTERISK_AMI_SECRET"
cdr = "/srv/monitor/entradas/asterisk/cdr.csv"

[qos]
habilitado = false
servidor_iperf = "10.30.50.20"
duracion_s = 10
ancho_banda = "20M"
interfaz = "eth1"

[seguridad]
habilitado = true
modo = "archivo"          # local | archivo | simulado
entradas = "/srv/monitor/entradas/seguridad"
iptables_save = "/srv/monitor/entradas/seguridad/iptables.save"
fail2ban_estado = "/srv/monitor/entradas/seguridad/fail2ban.txt"
fail2ban_log = "/srv/monitor/entradas/seguridad/fail2ban.log"
auth_log = "/srv/monitor/entradas/seguridad/auth.log"
kern_log = "/srv/monitor/entradas/seguridad/kern.log"
netstat = "/srv/monitor/entradas/seguridad/netstat.txt"
snmp = "/srv/monitor/entradas/seguridad/snmp.txt"
prefijos_iptables = ["VLAN30-DROP:", "VLAN40-DROP:"]
jail = "sshd"

[dhcp]
habilitado = true
modo = "archivo"
entradas = "/srv/monitor/entradas/dhcp"
leases = "/srv/monitor/entradas/dhcp/dhcpd.leases"
estado = "/srv/monitor/entradas/dhcp/estado.json"

[[camaras.lista]]
ip = "10.30.30.12"
nombre = "Cam_Muelle_1"
vlan = 30
zona = "muelles"
criticidad = "alta"

[[camaras.lista]]
ip = "10.30.30.13"
nombre = "Cam_Perimetro_1"
vlan = 30
zona = "perimetro"
criticidad = "media"
```

Validación al arrancar: IPs con `ipaddress`, puertos 1–65535, rutas y directorios
existentes, timeouts > 0, zona horaria válida y al menos un módulo habilitado.

---

## 10. Flujo de ejecución y programación

```
1. parsear CLI y cargar TOML + inventario
2. validar configuración (fallo ⇒ exit 2)
3. adquirir lock (si está ocupado ⇒ exit 0 con aviso)
4. crear run_id e inicio de corrida
5. construir sondas habilitadas × objetivos
6. ejecutar en ThreadPoolExecutor; cada sonda aplica timeout y reintentos
7. excepción ⇒ ERROR con detalle, sin abortar el resto
8. escribir JSONL temporal y renombrarlo (fsync + os.replace)
9. imprimir resumen y liberar lock
10. exit 0 si todo OK; 1 si hubo fallos/degradación; 3 si fallo fatal
```

El CSV no se genera en `run`: lo produce el comando `export` del cierre diario.

**Muestreo cada 5 minutos y cierre diario a las 23:59.** La última muestra del día es
la de las 23:55; el `export` de las 23:59 reconstruye el CSV con las 288 muestras del
día, sin carreras con la corrida siguiente (el límite total de corrida es 120 s).

```cron
# /etc/cron.d/portocaribe-monitor
*/5 * * * * monitor cd /opt/portocaribe-monitor && /usr/bin/python3 -m monitor run >> data/logs/cron.log 2>&1
59 23 * * * monitor cd /opt/portocaribe-monitor && /usr/bin/python3 -m monitor export --fecha "$(date +\%F)" >> data/logs/cron.log 2>&1
```

```ini
# programacion/portocaribe-muestreo.timer  (alternativa a cron)
[Unit]
Description=Monitor PortoCaribe (muestreo)

[Timer]
OnCalendar=*:0/5
```

```ini
# programacion/portocaribe-cierre.timer
[Unit]
Description=Monitor PortoCaribe (cierre diario)

[Timer]
OnCalendar=*-*-* 23:59:00 America/Bogota
Persistent=true
```

> **Zona horaria:** si la VM está en `America/Bogota`, el cron funciona tal cual; si
> está en UTC, usa el timer con zona explícita o ajusta la zona de la VM. `CRON_TZ`
> solo existe en algunas implementaciones de cron.

> **Volumen esperado.** 288 corridas/día × ~30 objetivos ≈ 8 600 filas/día; el CSV
> diario ronda 2 MB y 180 días de retención ~360 MB. Si se prefiere muestrear cada 10
> o 15 minutos, solo cambia el cron (y `intervalo_s`/`frescura_max_s`); el resto no se
> toca.

Subcomandos:

| Comando | Efecto |
|---|---|
| `run` | Ejecuta sondas y escribe el JSONL de la corrida |
| `export` | Reconstruye el CSV de una fecha desde sus JSONL |
| `publicar` | En cada VM de servicio: copia datos locales a la carpeta compartida |
| `prune` | Borra JSONL/CSV anteriores a `retencion_dias` |
| `validate` | Solo valida configuración e inventario |

Opciones: `--config`, `--solo`, `--dry-run`, `--simulate`, `--verbose`, `--json-logs`.

---

## 11. Robustez y operación

- **Timeouts:** 5 s por sonda, 15 s HTTP, 20 s iperf3; límite total de 120 s por corrida
  (una corrida que lo exceda se corta y escribe lo recolectado).
- **Reintentos:** solo ante timeout/error transitorio; 2 intentos con backoff
  exponencial (0.5 s, 1 s) y jitter.
- **Instancia única:** `flock` no bloqueante sobre `data/.lock`; si una corrida se
  solapa, la nueva sale con aviso.
- **Señales:** SIGTERM/SIGINT activan un `threading.Event`; se escribe lo recolectado
  y se sale con código 1.
- **Reloj:** `timedatectl show -p NTPSynchronized` y aviso si no está sincronizado;
  todas las VMs deben usar NTP para que los eventos de log sean comparables.
- **Retención:** `prune` por días; compresión `.gz` de JSONL antiguos.
- **Logs:** `monitor.log` rotativo; una línea por sonda con duración y resultado, sin
  credenciales ni cuerpos de respuesta.
- **Códigos de salida:** 0 todo OK, 1 parcial/degradado, 2 configuración inválida, 3 fatal.

---

## 12. Pruebas y criterios de aceptación

| Nivel | Qué se prueba | Cómo (sin red) |
|---|---|---|
| Unitario | Parsers de `ping`, AMI, iperf3, CDR, fail2ban, auth.log, kernel, iptables, pcap | Fixtures en `tests/fixtures/` |
| Unitario | Huellas estables, dedupe de eventos releídos, deltas de contadores, `STALE` | Archivos temporales |
| Unitario | Normalización, enums, validación TOML | `unittest` |
| Integración | Sondas TCP/HTTP | `socket` local y `http.server.ThreadingHTTPServer` en `127.0.0.1:0` |
| Integración | Export idempotente | JSONL temporales + doble `export` |
| Extremo a extremo | `run --simulate` | `tmp_path` + `subprocess` |
| Manual | Topología real, VLANs, AMI y carpeta compartida | Lista de verificación del laboratorio |

**Definición de terminado (v1)**

1. `python -m monitor run --simulate` genera JSONL válido y un CSV con las columnas
   exactas del esquema v1 y al menos una fila por módulo habilitado.
2. `export --fecha` dos veces produce el mismo CSV byte a byte (mismo SHA-256).
3. Un objetivo inexistente produce `OFFLINE`/`ERROR`, no una traza.
4. Un archivo publicado desactualizado produce `STALE`, no datos viejos.
5. Releer el mismo `auth.log` no duplica eventos en el CSV.
6. Los deltas de `iptables` suman lo esperado entre dos snapshots consecutivos.
7. `python -m unittest discover -s tests` pasa sin acceso a red.
8. `grep -RhE "^(from|import) " monitor/` solo muestra stdlib.
9. Una hora de muestreo deja 12 JSONL y el CSV del día se genera a las 23:59.
10. README con configuración, programación, publicación, columnas y límites.

---

## 13. Plan por fases

| Fase | Entregable | Horas | Criterio de cierre |
|---|---|---|---|
| **F0. Relevamiento** | Inventario, NFS, usuario AMI, VM de seguridad | 2 | Rutas, IPs, NFS y AMI validados |
| **F1. Esqueleto** | Paquete, config TOML, modelos, logging, lock, writers, CLI, 5 tests | 3 | `validate` y `run --dry-run` funcionan |
| **F2. Sondas núcleo** | ICMP, TCP, RTSP, HTTP/TLS, concurrencia y reintentos | 4 | Cámaras y portal reales en JSONL |
| **F3. Export** | JSONL atómico, reconstrucción CSV, `prune` | 2 | Export idempotente y CSV válido |
| **F4. Asterisk y portal** | SIP, AMI, CDR, `publicar --perfil asterisk/portal` | 3 | `llamadas_activas`, duraciones y Apache |
| **F5. Seguridad** | Dedupe, iptables, fail2ban, auth/kernel, `publicar --perfil seguridad` | 3 | Eventos con IP y delta de contadores |
| **F6. DHCP + QoS** | Leases/estado, `publicar --perfil dhcp` y QoS opcional | 3 | Estado DHCP y QoS en el dataset |
| **F7. Calidad** | Fixtures, `--simulate`, frescura y dedupe | 2 | Suite verde y simulación reproducible |
| **F8. Operación** | Cron 5 min, cierre 23:59, publicadores, README y runbook | 3 | Un día completo de muestras y CSV |

**Total estimado: ~25 h.** Ruta mínima demostrable (F0–F3 + `--simulate`): ~11 h.

Orden sugerido: F0 → F1 → F2 → F3 → F4 → F5 → F7 → F8 → F6. QoS al final porque es
la única sonda que altera el tráfico del laboratorio.

---

## 14. Estructura de archivos propuesta

```
pa/
├── monitor/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── config.py
│   ├── modelos.py
│   ├── runner.py
│   ├── writers.py
│   ├── exportacion.py
│   ├── publicacion.py         # subcomando publicar (perfiles)
│   ├── bloqueo.py
│   ├── sondas/
│   │   ├── __init__.py        # registro y metadatos (requiere, módulo)
│   │   ├── icmp.py
│   │   ├── tcp.py
│   │   ├── http.py
│   │   ├── postgres.py
│   │   ├── sip.py
│   │   ├── asterisk.py        # AMI + CDR
│   │   ├── iperf.py
│   │   ├── pcap.py
│   │   ├── seguridad.py
│   │   └── dhcp.py
│   └── utils/
│       ├── tiempo.py
│       ├── red.py
│       ├── estado.py          # contadores y frescura
│       └── reintentos.py
├── config/
│   ├── monitor.ejemplo.toml
│   └── inventario.ejemplo.csv
├── programacion/
│   ├── portocaribe-muestreo.timer
│   ├── portocaribe-cierre.timer
│   ├── cron.monitor
│   ├── cron.publicar-asterisk
│   ├── cron.publicar-portal
│   ├── cron.publicar-seguridad
│   └── cron.publicar-dhcp
├── tests/
│   ├── fixtures/
│   └── test_*.py
├── data/                      # generado, ignorado por git
├── pyproject.toml             # dependencies = []
└── README.md
```

`pyproject.toml` declara `requires-python = ">=3.11"` y `dependencies = []`.

---

## 15. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Carpeta compartida caída o sin permisos | Datos locales ausentes | `SKIPPED`/`STALE`, reintento en la siguiente corrida, alerta en el resumen |
| Publicador que no corre | Métricas desactualizadas | `frescura_max_s`, estado `STALE`, no se parsea |
| Relojes desincronizados entre VMs | Eventos fuera de orden | NTP/chrony en todas las VMs; verificación en el resumen |
| Reemplazo/rotación de archivos | Duplicados o pérdidas | Lectura completa + huella estable; logs acotados a 5 000 líneas |
| Volumen de `auth.log` mayor a 5 000 líneas/5 min | Eventos perdidos | Subir el límite o centralizar con `rsyslog` |
| CDR crece sin límite | Copia cada vez más pesada | Rotación diaria de `Master.csv` en Asterisk |
| AMI expuesto | Acceso no autorizado a Asterisk | Usuario de solo lectura, secreto por entorno, `permit` por IP |
| `iperf3`/`tcpdump` ausentes | Sin métricas QoS | Adaptador `SKIPPED`, columnas nulas |
| Parseo de `ping` por idioma | Pérdida de latencias | `LC_ALL=C` y fixtures en inglés/español |
| ICMP/`tcpdump` requieren privilegios | Sonda no ejecuta | `setcap cap_net_raw+ep` o servicio con permisos |
| CSV abierto en Excel | Escritura fallida | Temporal + `os.replace`; reintento y aviso |
| 288 JSONL/día | Muchos archivos | Retención y compresión mensual opcional |
| Topología caída | Sin evidencia | `--simulate` determinista y `--dry-run` |

**Nota de alcance:** el script solo debe apuntar a activos del laboratorio y de la
topología del proyecto; no se ejecuta contra redes de terceros.

---

## 16. Decisiones y pendientes

**Confirmadas**

- VM de monitoreo dentro de la topología.
- Asterisk, fail2ban y DHCP en VMs reales.
- Muestreo cada 5 minutos; CSV diario a las 23:59.
- Entrega en CSV + JSONL, sin PostgreSQL como destino.
- Solo dataset; medidas y gráficos los elabora otra persona.

**Pendiente**

- ¿En qué VM corre `fail2ban` (y `iptables`): en el firewall, en `srv-core` o en otra?
  El perfil `seguridad` se instala en esa VM.
- ¿La carpeta compartida por NFS es viable en el laboratorio? Si no, se usa `rsyslog`
  centralizado o SSH puntual (§8.6).

## 17. Siguiente paso

Cerrar F0 (NFS + usuario AMI + confirmar la VM de seguridad) e implementar F1–F3:
esqueleto, sondas ICMP/TCP/HTTP y export CSV/JSONL, con `--simulate` para tener el
dataset demostrable antes de conectar las fuentes reales.

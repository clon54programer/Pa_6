# Plan de implementación — Monitor PortoCaribe (Python, stdlib-first) — v2

> **Decisiones confirmadas (2026-11-06)**
>
> - **Ejecución:** una VM de monitoreo dentro de la topología.
> - **Entrega:** CSV + JSONL. PostgreSQL no es destino de carga.
> - **Frecuencia:** una corrida diaria a las **23:00** (America/Bogota).
> - **Alcance:** solo el dataset; las medidas y gráficos de Power BI los elabora otra persona.
> - **Pendiente:** definir si Asterisk / fail2ban / DHCP son servicios reales o datos
>   simulados (ver §8).

Documento de trabajo para construir el script descrito en
[`plan_de_script_python.md`](plan_de_script_python.md). El objetivo es un monitor
ejecutable por CLI, sin dependencias obligatorias fuera de la biblioteca estándar,
que produzca un dataset plano listo para Power BI.

---

## 1. Objetivo y alcance

**Objetivo.** Implementar `python -m monitor` (Python ≥ 3.11) que ejecute sondas de
disponibilidad, rendimiento, QoS y seguridad sobre la infraestructura de PortoCaribe,
normalice los resultados y los deje en:

- `data/raw/YYYY-MM-DD/HHMMSS_<run_id>.jsonl` — evidencia cruda, una línea por resultado.
- `data/csv/metricas_YYYY-MM-DD.csv` — dataset del día, columnas fijas.

**Dentro del alcance**

- Sondas activas por red: ICMP, TCP (RTSP 554, PostgreSQL 5432), HTTP/HTTPS, DNS y SIP 5060.
- Lectura de fuentes locales o compartidas: CDR de Asterisk, `fail2ban`, `auth.log`,
  contadores de `iptables`, leases de DHCP.
- QoS opcional: `iperf3 -J` y DSCP a partir de capturas `pcap`.
- Modo `--simulate` para demo e informe sin topología levantada.
- Pruebas con `unittest` y fixtures, sin red.

**Fuera del alcance**

- Carga a PostgreSQL, dashboard, medidas DAX o gráficos (los asume otra persona).
- Construcción de la topología, reglas de firewall o servicios.
- Agente distribuido multi-host: v1 es un proceso en una sola VM.

**Supuestos**

1. VM Linux con Python 3.12 y `tomllib` (verificado: 3.12.3).
2. La VM tiene ruta a las VLAN 30/40/50/60; se valida en F0 con `ip route` y `ping`.
3. `ping` y `psql` existen; `iperf3`, `tcpdump`, `fail2ban-client` y `asterisk` pueden faltar.
4. Zona horaria `America/Bogota` (sin horario de verano); se guarda local y UTC.
5. Una corrida diaria a las 23:00, lanzada por cron o `systemd` timer.

---

## 2. Principios de diseño

1. **Stdlib primero.** Todo se resuelve con la biblioteca estándar; el proyecto queda
   con `dependencies = []`.
2. **Adaptadores con degradación.** Toda herramienta o archivo externo se encapsula;
   si falta, la sonda devuelve `SKIPPED` con motivo, no una excepción.
3. **Configuración declarativa.** IPs, rutas y umbrales en TOML; el código no contiene
   infraestructura ni credenciales.
4. **Un fallo no detiene la corrida.** Timeout por sonda, reintentos acotados y
   `try/except` por objetivo; siempre se escribe resumen y código de salida.
5. **Crudo inmutable + derivado reconstruible.** El JSONL es la evidencia; el CSV del
   día se regenera desde los JSONL (idempotente, sin base de datos).
6. **Procedencia explícita.** Cada fila declara si el dato vino de red, de un archivo,
   de AMI o de una simulación (`fuente`). Nada simulado se mezcla en silencio.
7. **Seguro por defecto.** `subprocess` sin `shell=True`, credenciales por variable de
   entorno o `PGPASSFILE`, timeouts explícitos, sin volcar cuerpos de respuesta a logs.

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
 (ICMP/TCP)  (HTTP/TLS)   (PG/SIP/DNS)  (iperf3/pcap)  (red/archivo)
   └────────────┴───────────────┴──────────────┴──────────────┘
                │  Resultado (dataclass) normalizado
                ▼
   JSONL por corrida (crudo) ──► CSV del día (reconstruido, idempotente)
                │
                ▼
        logs + resumen de corrida + exit code
```

**Capas**

| Capa | Responsabilidad | Archivos |
|---|---|---|
| Presentación | CLI, subcomandos, códigos de salida | `cli.py`, `__main__.py` |
| Dominio | Modelos, validación, registro de sondas | `modelos.py`, `config.py` |
| Sondas | Medición pura, sin escritura | `sondas/*.py` |
| Salida | JSONL crudo y reconstrucción del CSV | `writers.py`, `exportacion.py` |
| Soporte | Lock, reintentos, tiempo, red | `bloqueo.py`, `utils/*.py` |

---

## 4. Mapa de la biblioteca estándar

| Necesidad | Módulo stdlib | Uso concreto |
|---|---|---|
| CLI y subcomandos | `argparse` | `run`, `export`, `prune`, `validate` |
| Configuración | `tomllib` | Lectura de `monitor.toml` (solo lectura) |
| Modelos y enums | `dataclasses`, `enum`, `typing` | `Resultado`, `Objetivo`, `Estado` |
| Tiempo | `datetime`, `zoneinfo`, `time` | UTC + local; `perf_counter()` para latencias |
| Concurrencia | `concurrent.futures`, `threading` | Sondas I/O en paralelo; evento de parada |
| ICMP | `subprocess` | `ping -n -q -c 4 -W 1` (stdlib no hace ICMP sin root) |
| TCP | `socket` | 554, 5432, 5060/TCP |
| UDP / SIP | `socket`, `secrets` | OPTIONS a Asterisk; `branch` y `Call-ID` aleatorios |
| AMI Asterisk | `socket` | Protocolo de texto sobre TCP 5038 (`CoreShowChannels`) |
| HTTP/HTTPS | `http.client`, `ssl` | Código, TTFB, tiempo total, versión TLS |
| DNS | `socket.getaddrinfo` | Disponibilidad y latencia de resolución |
| CSV / JSON | `csv`, `json` | Dataset y evidencia |
| Logs | `logging`, `logging.handlers` | `RotatingFileHandler` (5 MB × 5) |
| Archivos | `pathlib`, `tempfile`, `os.replace`, `gzip` | Escritura atómica y retención |
| Instancia única | `fcntl` | `flock` sobre `data/.lock` |
| Apagado limpio | `signal` | SIGINT/SIGTERM → cerrar y escribir resumen |
| IDs y huellas | `uuid`, `hashlib` | `run_id`; SHA-256 para deduplicar |
| IPs y VLANs | `ipaddress` | Validar inventario y mapear CIDR → VLAN |
| Capturas pcap | `struct` | Leer cabeceras y extraer DSCP sin `tshark` |
| Pruebas | `unittest`, `unittest.mock` | Fixtures y servidores locales |
| Sistema | `os`, `sys`, `shutil`, `subprocess` | `systemctl`, `journalctl`, `psql`, `iperf3` |

**Dependencias de terceros: ninguna.** No hay `psycopg`, `scapy`, `requests` ni
`pandas`; PostgreSQL se monitorea con `psql` (cliente del sistema), no se usa como destino.

---

## 5. Dependencias externas y degradación

| Herramienta | Uso | Si falta |
|---|---|---|
| `ping` (iputils) | Estado y RTT de cámaras/servidores | Sonda `SKIPPED`; el resto continúa |
| `psql` | `SELECT 1` y estado de la base | Se reporta solo el puerto TCP 5432 |
| `iperf3` (–J) | Pérdida, jitter, ancho de banda | `SKIPPED`, columnas QoS nulas |
| `tcpdump` | Captura pcap para DSCP | `SKIPPED`; QoS queda solo con iperf3 |
| `asterisk` CLI | Llamadas activas en el propio host | Se usa AMI (red) o solo el CDR |
| `fail2ban-client` | Baneos en el propio host | Se parsea el log exportado |
| `systemctl` / `journalctl` | Estado de Apache/DHCP y logs de kernel | Se leen archivos en `/var/log` |

Cada sonda declara `requiere: tuple[str, ...]`; el runner consulta `shutil.which()`
antes de ejecutarla y registra el motivo del `SKIPPED`.

---

## 6. Modelo de datos

### 6.1 Tabla canónica (una fila por sonda y objetivo)

Se conservan los campos pedidos en el documento y se agregan columnas opcionales.

| Campo | Tipo | Obligatorio | Ejemplo / notas |
|---|---|---|---|
| `timestamp` | DATETIME local | sí | `2026-11-06 23:00:07` |
| `timestamp_utc` | DATETIME UTC | sí | `2026-11-07 04:00:07` |
| `run_id` | TEXT | sí | UUID4; prefijo `sim-` en modo simulado |
| `modulo` | TEXT | sí | `Camaras`, `PortalWeb`, `BaseDatos`, `VoIP`, `QoS`, `Seguridad` |
| `recurso_target` | TEXT | sí | IP o nombre del recurso |
| `nombre_recurso` | TEXT | no | `Cam_Muelle_1`, `Portal_Clientes` |
| `vlan` | INTEGER | no | 30, 40, 50, 60 |
| `zona` | TEXT | no | `muelles`, `perimetro`, `core` |
| `estado` | TEXT | sí | `ONLINE`, `OFFLINE`, `OK`, `DEGRADED`, `ERROR`, `DROPPED`, `SKIPPED` |
| `tiempo_respuesta_ms` | REAL | no | Latencia ICMP o tiempo HTTP total |
| `perdida_paquetes_pct` | REAL | no | 0–100, dos decimales |
| `jitter_ms` | REAL | no | VoIP/video |
| `ancho_banda_mbps` | REAL | no | iperf3 |
| `http_status` | INTEGER | no | 200, 500, 504 |
| `puerto` | INTEGER | no | 554, 5060, 5432 |
| `evento_seguridad` | TEXT | no | `SSH_FAIL`, `VLAN30_BLOCKED`, `FAIL2BAN_BAN`, `SYN_FLOOD` |
| `sip_code` | INTEGER | no | 200, 401, 403, 408 |
| `llamadas_activas` | INTEGER | no | Conteo simultáneo |
| `duracion_llamada_s` | REAL | no | Desde el CDR |
| `dscp` | INTEGER | no | 46 (EF), 34 (AF41) |
| `detalle` | TEXT | no | Texto corto (≤200 caracteres) para diagnóstico |
| `fuente` | TEXT | sí | `ping`, `tcp`, `http`, `psql`, `sip`, `ami`, `asterisk-cdr`, `iperf3`, `pcap`, `journal`, `archivo`, `systemd`, `simulado` |
| `schema_version` | INTEGER | sí | `1` |

**Reglas**

- Unidades fijas: ms, %, Mbps, segundos; sin sufijos en los valores.
- `estado` es texto enumerado, nunca booleano (mejor para Power BI).
- `timestamp` local sin offset (para el modelo) + `timestamp_utc` (auditoría).
- Celdas no aplicables quedan vacías (`null` en JSONL), no en cero.
- Nombres de archivo y columnas en español, estables y documentados.

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

Un archivo JSONL por corrida:

```json
{"run_id":"4f1c...","timestamp":"2026-11-06 23:00:07","timestamp_utc":"2026-11-07 04:00:07","modulo":"Camaras","recurso_target":"10.30.30.12","nombre_recurso":"Cam_Muelle_1","vlan":30,"zona":"muelles","estado":"ONLINE","tiempo_respuesta_ms":2.41,"perdida_paquetes_pct":0.0,"jitter_ms":null,"ancho_banda_mbps":null,"http_status":null,"puerto":554,"evento_seguridad":null,"sip_code":null,"llamadas_activas":null,"duracion_llamada_s":null,"dscp":null,"detalle":"4/4 paquetes; RTSP 554 abierto","fuente":"ping","schema_version":1}
```

- JSONL: `json.dumps(..., ensure_ascii=False)` + salto de línea, `flush` + `os.fsync`.
- CSV: `utf-8-sig` (Excel y Power BI), `csv.DictWriter`, encabezado fijo, `\r\n`.
- `export --fecha YYYY-MM-DD` lee todos los JSONL de esa fecha, deduplica por
  `sha256(run_id|modulo|recurso|timestamp_utc|evento|fuente)`, ordena por
  `timestamp_utc, modulo, recurso` y reescribe el CSV completo.
- Escritura atómica: archivo temporal en el mismo directorio + `os.replace`.
- Exportar dos veces la misma fecha produce un CSV idéntico (mismo hash).

`data/` queda fuera de git (`.gitignore`) salvo `data/.gitkeep`.

---

## 7. Módulos y sondas

| Módulo | Sonda | Técnica stdlib | Salida principal |
|---|---|---|---|
| `Camaras` | Ping | `subprocess` + `ping -n -q -c 4 -W 1` | `estado`, `tiempo_respuesta_ms`, `perdida_paquetes_pct` |
| `Camaras` | RTSP 554 | `socket.create_connection` | `estado`, `puerto`, latencia |
| `PortalWeb` | HTTP/HTTPS | `http.client` + `ssl` + `perf_counter` | `http_status`, tiempos, TLS |
| `BaseDatos` | PostgreSQL | `socket` + `psql -w -tAc "SELECT 1"` | `estado`, latencia |
| `VoIP` | SIP 5060 | UDP OPTIONS con `socket` | `sip_code`, `estado` |
| `VoIP` | Asterisk AMI | Texto sobre TCP 5038 | `llamadas_activas` |
| `VoIP` | CDR | `csv` sobre `Master.csv` | `duracion_llamada_s`, `sip_code` |
| `QoS` | iperf3 | `iperf3 -J` + `json` | `perdida_paquetes_pct`, `jitter_ms`, `ancho_banda_mbps` |
| `QoS` | DSCP | `tcpdump -w` + parser `struct` | `dscp` |
| `Seguridad` | iptables | `journalctl -k` o log exportado | `evento_seguridad`, IPs, VLAN |
| `Seguridad` | fail2ban/SSH | `fail2ban-client`, `auth.log` | `evento_seguridad`, IPs |
| `Seguridad` | Inundaciones | `/proc/net/snmp`, `/proc/net/netstat` | `SYN_FLOOD`, `ICMP_FLOOD` |

### 7.1 Cámaras (VLAN 30)

- Ping con 4 paquetes y `LC_ALL=C`; pérdida y RTT desde la línea de resumen.
- `ONLINE` si responde al menos un paquete **y** el puerto 554 abre en < 3 s;
  `DEGRADED` si hay ICMP pero el puerto falla; `OFFLINE` si no hay ICMP.
- OPTIONS RTSP opcional: `OPTIONS rtsp://IP:554/ RTSP/1.0`; `200/401/403` = servicio vivo.

### 7.2 Portal web (VM1)

- Medición por etapas: DNS, conexión TCP, handshake TLS, TTFB y total.
- `DEGRADED` si el total supera 10 s (hipótesis del caso) o el código es 5xx;
  `OK` para 2xx/3xx.
- Apache con `systemctl is-active apache2` (o `httpd`), como fila aparte
  (`fuente = systemd`).
- Sin redirecciones automáticas (máximo 1 salto, configurable).

### 7.3 PostgreSQL como objetivo

- **Aclaración:** la base de datos es un servicio monitoreado, no el destino del
  dataset. No se escribe nada en PostgreSQL.
- TCP 5432 como chequeo rápido; si `psql` está, `SELECT 1` cronometrado con
  `PGCONNECT_TIMEOUT` y `PGPASSFILE` (600).
- DNS: `getaddrinfo` de un nombre de control y latencia.

### 7.4 VoIP

- SIP OPTIONS por UDP con retransmisión T1 (500 ms, 2 intentos); `200/401/403` = vivo.
- **AMI** (si está habilitado): conectar a TCP 5038, `Login`, `Action: CoreShowChannels`,
  contar eventos `CoreShowChannel` y cerrar. Es la vía limpia desde otra VM, sin SSH.
- **CDR** (si el archivo es accesible): parsear `Master.csv`, filtrar por fecha y agregar
  duración y `disposition` (`ANSWERED`, `BUSY`, `FAILED`, `NO ANSWER`).
- Si no hay AMI ni CDR: solo disponibilidad SIP; `llamadas_activas` y `duracion_llamada_s`
  quedan nulas.

### 7.5 QoS

- `iperf3 -c HOST -u -b 20M -t 10 -J`; leer `end.sum_received.loss_percent`,
  `.jitter_ms` y `end.sum_sent.bits_per_second`, tolerando variantes del JSON.
- DSCP sin `tshark`: `tcpdump -i IFACE -w captura.pcap -c 500` y parser propio con
  `struct` (magic `0xa1b2c3d4`/`0xa1b23c4d`, Ethernet + 802.1Q, IPv4, TOS → `tos >> 2`).
  Conteos por DSCP (EF=46, AF41=34); se descartan paquetes no-IP.
- Deshabilitada por defecto (genera tráfico); se ejecuta con `--solo qos` en ventana
  controlada.

### 7.6 Seguridad

- **iptables:** las reglas del escenario deben usar prefijos de log
  (`VLAN30-DROP: `, `VLAN40-DROP: `); el parser los busca en el log de kernel local o
  en la copia exportada, y extrae IP origen/destino, puerto, interfaz y VLAN.
- **Contadores:** `iptables -t filter -L INPUT -v -n -x`; se guarda el acumulado y el
  delta contra la corrida anterior (el delta es lo que se grafica).
- **fail2ban:** `fail2ban-client status sshd` (baneadas actuales/totales) o el log
  (`Ban`, `Unban`) según el modo configurado.
- **SSH:** `auth.log` o `journalctl -u ssh` con `Failed password for .* from (\S+)`.
- **Inundaciones:** `possible SYN flooding`, `ListenOverflows`/`ListenDrops` de
  `/proc/net/netstat` y delta de `/proc/net/snmp`.

---

## 8. Fuentes locales vs. red (aclaración de la pregunta 3)

La VM de monitoreo **no puede leer archivos locales de otras VMs**. Eso aplica a
Asterisk, fail2ban, iptables y DHCP: sus datos viven en el host donde corre el servicio.

### 8.1 Qué se alcanza y qué no

| Dato | Dónde vive | ¿Desde la VM de monitoreo? |
|---|---|---|
| Ping, puertos, HTTP, DNS, SIP 5060 | red | **Sí**, sin credenciales |
| Llamadas activas | Asterisk (CLI local / AMI por red) | CLI **no**; AMI **sí** (TCP 5038) |
| CDR (`Master.csv`) | disco del host Asterisk | **No**, salvo export/SSH |
| Baneos de fail2ban | host protegido | **No**, salvo export/SSH |
| Contadores de iptables | firewall | **No**, salvo export/SSH |
| Leases/estado de DHCP | gateway | **No**; DHCP es broadcast y no cruza VLAN |

### 8.2 Opciones para los datos locales

| Opción | Ventaja | Costo | Cuándo usarla |
|---|---|---|---|
| **Sonda de red** | simple, sin credenciales | solo alcanza lo expuesto | siempre que exista |
| **AMI de Asterisk** | nativo, stdlib, sin SSH | habilitar usuario de solo lectura | Asterisk real |
| **SSH puntual** | accede a CLI y archivos | claves, `sudo`, más superficie de ataque | hosts administrados |
| **Archivo exportado** | simple y robusto | NFS/SMB o `cron` + `scp` en el host | CDR, fail2ban, iptables, DHCP |
| **Simulación** | demo sin infraestructura | datos no reales | plantilla o evidencia |

**Qué significa “simular con archivos”:** no se finge la red; se preparan archivos de
ejemplo con el **formato real** (`Master.csv`, `fail2ban.log`, líneas de `iptables`,
salida de `fail2ban-client`) y el script los procesa igual que a los reales. Así se
desarrollan y prueban los parsers sin la infraestructura. Para el informe, esas filas
salen con `fuente = simulado` y `run_id` con prefijo `sim-`, de modo que se puedan
filtrar y no se confundan con mediciones reales.

### 8.3 Recomendación para el proyecto

1. **Cámaras, portal, PostgreSQL, DNS y SIP:** sondas de red reales desde la VM.
2. **Asterisk:** habilitar AMI con usuario de solo lectura si es una VM real; si no,
   dejar solo SIP 5060 y marcar el resto como no recolectado.
3. **fail2ban / iptables / DHCP:** si la VM de monitoreo no es el host del servicio,
   usar un export diario a una carpeta compartida (un `cron` pequeño en ese host) o
   simulación etiquetada. La tercera opción es omitirlos y documentarlo.
4. **Nunca** reportar datos simulados como si fueran mediciones: la columna `fuente`
   existe justamente para eso.

---

## 9. Configuración (TOML)

```toml
[general]
zona_horaria = "America/Bogota"
timeout_s = 5
reintentos = 2
max_workers = 12
directorio_datos = "data"
retencion_dias = 180
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
ami = false
ami_puerto = 5038
ami_usuario = "monitor"
ami_secreto_env = "ASTERISK_AMI_SECRET"
cdr = ""                  # ruta local o compartida; vacío = no recolectar

[qos]
habilitado = false
servidor_iperf = "10.30.50.20"
duracion_s = 10
ancho_banda = "20M"
interfaz = "eth1"

[seguridad]
habilitado = true
modo = "archivo"          # local | archivo | simulado
entradas = "/srv/monitor/entradas"
prefijos_iptables = ["VLAN30-DROP:", "VLAN40-DROP:"]
jail = "sshd"

[dhcp]
habilitado = false
modo = "archivo"
host = "10.30.40.1"

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
8. escribir JSONL de la corrida (fsync)
9. si --exportar: reconstruir data/csv/metricas_YYYY-MM-DD.csv
10. imprimir resumen, cerrar corrida y liberar lock
11. exit 0 si todo OK; 1 si hubo fallos/degradación; 3 si fallo fatal
```

**Programación diaria a las 23:00.** Cron (zona horaria de la VM en
`America/Bogota`) o `systemd` timer:

```cron
# /etc/cron.d/portocaribe-monitor
CRON_TZ=America/Bogota
0 23 * * * monitor cd /opt/portocaribe-monitor && /usr/bin/python3 -m monitor run --exportar >> data/logs/cron.log 2>&1
```

```ini
# programacion/portocaribe-monitor.timer
[Unit]
Description=Monitor PortoCaribe diario

[Timer]
OnCalendar=*-*-* 23:00:00 America/Bogota
Persistent=true

[Install]
WantedBy=timers.target
```

> **Sobre una sola muestra diaria.** Con una corrida a las 23:00, cada recurso aporta
> **una fila por día**: la “disponibilidad” que se calcule en Power BI será un
> **indicador puntual** (100 % o 0 % por día), no un porcentaje de uptime. Si el
> informe necesita disponibilidad real, basta cambiar el cron a cada 5–15 minutos y
> exportar una vez al día; el CSV acumula las muestras y Power BI calcula el %. El
> script soporta ambos escenarios sin cambios: la frecuencia es solo programación.

Subcomandos:

| Comando | Efecto |
|---|---|
| `run` | Ejecuta sondas, escribe JSONL y, con `--exportar`, el CSV del día |
| `export` | Reconstruye el CSV de una fecha desde sus JSONL |
| `prune` | Borra JSONL/CSV anteriores a `retencion_dias` |
| `validate` | Solo valida configuración e inventario |

Opciones: `--config`, `--solo`, `--dry-run`, `--simulate`, `--exportar`,
`--verbose`, `--json-logs`.

---

## 11. Robustez y operación

- **Timeouts:** 5 s por sonda, 15 s HTTP, 20 s iperf3; además un límite total de corrida.
- **Reintentos:** solo ante timeout/error transitorio; 2 intentos con backoff
  exponencial (0.5 s, 1 s) y jitter.
- **Instancia única:** `flock` no bloqueante sobre `data/.lock`.
- **Señales:** SIGTERM/SIGINT activan un `threading.Event`; se escribe lo recolectado
  y se sale con código 1.
- **Reloj:** `timedatectl show -p NTPSynchronized` y aviso si no está sincronizado;
  un reloj desfasado distorsiona el histórico.
- **Retención:** `prune` por días; compresión `.gz` de JSONL antiguos.
- **Logs:** `monitor.log` rotativo; una línea por sonda con duración y resultado, sin
  credenciales ni cuerpos de respuesta.
- **Códigos de salida:** 0 todo OK, 1 parcial/degradado, 2 configuración inválida, 3 fatal.

---

## 12. Pruebas y criterios de aceptación

| Nivel | Qué se prueba | Cómo (sin red) |
|---|---|---|
| Unitario | Parsers de `ping`, iperf3, CDR, fail2ban, auth.log, iptables, pcap | Fixtures en `tests/fixtures/` |
| Unitario | Normalización, huellas, enums, validación TOML | `unittest` |
| Integración | Sondas TCP/HTTP | `socket` local y `http.server.ThreadingHTTPServer` en `127.0.0.1:0` |
| Integración | Export idempotente | JSONL temporales + doble `export` |
| Extremo a extremo | `run --simulate` | `tmp_path` + `subprocess` |
| Manual | Topología real, VLANs y servicios | Lista de verificación del laboratorio |

**Definición de terminado (v1)**

1. `python -m monitor run --simulate` genera JSONL válido y un CSV con las columnas
   exactas del esquema v1 y al menos una fila por módulo habilitado.
2. `export --fecha` dos veces produce el mismo CSV byte a byte (mismo SHA-256).
3. Un objetivo inexistente produce `OFFLINE`/`ERROR`, no una traza.
4. `python -m unittest discover -s tests` pasa sin acceso a red.
5. `grep -RhE "^(from|import) " monitor/` solo muestra stdlib.
6. Una corrida con 20 objetivos de red termina en < 15 s (sin QoS).
7. El timer/cron de las 23:00 deja CSV, JSONL y log del día.
8. README con configuración, programación, columnas y límites.

---

## 13. Plan por fases

| Fase | Entregable | Horas | Criterio de cierre |
|---|---|---|---|
| **F0. Relevamiento** | Inventario real (IPs, VLANs, rutas) y decisión de fuentes locales | 1 | Inventario validado y §8 resuelto |
| **F1. Esqueleto** | Paquete, config TOML, modelos, logging, lock, writers, CLI, 5 tests | 3 | `validate` y `run --dry-run` funcionan |
| **F2. Sondas núcleo** | ICMP, TCP, RTSP, HTTP/TLS, concurrencia y reintentos | 4 | Cámaras y portal reales en CSV |
| **F3. Export** | JSONL, reconstrucción CSV, `prune`, escritura atómica | 2 | Export idempotente y CSV válido |
| **F4. Servicios** | PostgreSQL, SIP, AMI/CDR, DNS | 3 | Filas con `sip_code`, `llamadas_activas` |
| **F5. Seguridad** | iptables/journal, fail2ban, SSH, contadores | 3 | Eventos con IP origen/destino |
| **F6. QoS** | iperf3 `-J` y parser pcap/DSCP | 3 | Pérdida, jitter y DSCP en el dataset |
| **F7. Calidad** | Fixtures completos, `--simulate`, fallos inyectados | 2 | Suite verde y simulación reproducible |
| **F8. Operación** | `systemd`/cron, README, runbook y evidencias | 2 | Timer de las 23:00 activo |

**Total estimado: ~23 h.** Ruta mínima demostrable (F0–F3 + `--simulate`): ~10 h.

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
│   │   └── sistema.py
│   └── utils/
│       ├── tiempo.py
│       ├── red.py
│       └── reintentos.py
├── config/
│   ├── monitor.ejemplo.toml
│   └── inventario.ejemplo.csv
├── programacion/
│   ├── portocaribe-monitor.service
│   ├── portocaribe-monitor.timer
│   └── cron.ejemplo
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
| Una sola muestra diaria | Disponibilidad puntual, no % real | Documentarlo; si se requiere %, subir la frecuencia del cron |
| Fuentes locales inaccesibles | Sin CDR, fail2ban ni contadores | Export compartido, AMI o simulación etiquetada (`fuente`) |
| Parseo de `ping` por idioma | Pérdida de latencias | `LC_ALL=C` y fixtures en inglés/español |
| ICMP/`tcpdump` requieren privilegios | Sonda no ejecuta | `setcap cap_net_raw+ep` o servicio con permisos; degradar |
| `iperf3`/`tcpdump` ausentes | Sin métricas QoS | Adaptador `SKIPPED`, columnas nulas |
| Formatos de log variables | Eventos vacíos | Prefijos fijos en `iptables`, regex configurable, fixtures |
| Reloj o zona horaria mal | Fechas inconsistentes | Verificación NTP y `timedatectl` en el resumen |
| CSV abierto en Excel | Escritura fallida | Temporal + `os.replace`; reintento y aviso |
| Credenciales | Exposición | Variables de entorno / `PGPASSFILE` 600; nunca en TOML |
| Topología caída | Sin evidencia | `--simulate` determinista y `--dry-run` |

**Nota de alcance:** el script solo debe apuntar a activos del laboratorio y de la
topología del proyecto; no se ejecuta contra redes de terceros.

---

## 16. Decisiones y pendientes

**Confirmadas**

- VM de monitoreo dentro de la topología.
- Entrega en CSV + JSONL, sin PostgreSQL como destino.
- Una corrida diaria a las 23:00 (America/Bogota).
- Solo dataset; medidas y gráficos los elabora otra persona.

**Pendiente**

- ¿Asterisk, fail2ban y DHCP son servicios reales en VMs de la topología, o se
  representan con archivos de ejemplo? De esto depende si §8 usa AMI/export o
  simulación. Mientras se define, F0 los deja configurados como `modo = "archivo"` y
  el resto del script no cambia.

## 17. Siguiente paso

Cerrar F0 (inventario + decisión de fuentes) e implementar F1–F3: esqueleto, sondas
ICMP/TCP/HTTP y export CSV/JSONL, con `--simulate` para tener el dataset demostrable
antes de tocar los servicios locales.

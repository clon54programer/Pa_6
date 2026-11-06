# Plan de implementación — Monitor PortoCaribe (Python, stdlib-first)

Documento de trabajo para construir el script descrito en
[`plan_de_script_python.md`](plan_de_script_python.md). El objetivo es un monitor
ejecutable por CLI, sin dependencias obligatorias fuera de la biblioteca estándar,
que produzca un dataset plano (CSV/JSONL/SQLite y, opcionalmente, PostgreSQL) listo
para Power BI.

---

## 1. Objetivo y alcance

**Objetivo.** Implementar `python -m monitor` (Python ≥ 3.11) que ejecute sondas de
disponibilidad, rendimiento, QoS y seguridad sobre la infraestructura de
PortoCaribe, normalice los resultados en un esquema único y los exporte para analítica.

**Dentro del alcance**

- Sondas activas: ICMP, TCP (RTSP 554, SIP 5060, PostgreSQL 5432), HTTP/HTTPS, DNS.
- Lectura pasiva: CDR de Asterisk, `fail2ban`, `auth.log`/journal, contadores de `iptables`.
- QoS: `iperf3` en modo JSON y análisis de DSCP a partir de capturas `pcap`.
- Persistencia: JSONL crudo → SQLite → CSV/JSONL → carga opcional a PostgreSQL.
- Modo `--simulate` para demo e informe sin topología levantada.
- Pruebas unitarias con `unittest` y fixtures (sin red).

**Fuera del alcance**

- Construcción de la topología, reglas de firewall o servicios (se asume existente).
- Dashboard de Power BI (solo se entrega el dataset y las medidas sugeridas).
- Agente distribuido multi-host (v1 es un solo proceso; el diseño deja la puerta abierta).

**Supuestos**

1. Linux con Python 3.12 (verificado en el entorno: 3.12.3) y `tomllib` disponible.
2. El script se ejecuta en una VM con ruta a las VLAN 30/40/50/60 del laboratorio.
3. `ping`, `psql` y `tcpdump` existen; `iperf3`, `tshark` y `fail2ban-client` pueden faltar.
4. Zona horaria `America/Bogota`; se almacena UTC y se muestra local.
5. Frecuencia objetivo: cada 1–5 minutos vía cron/systemd timer.

---

## 2. Principios de diseño

1. **Stdlib primero.** Cada requisito se resuelve con la biblioteca estándar; solo se
   acepta un tercero (`psycopg`) como extra opcional para PostgreSQL.
2. **Adaptadores con degradación.** Toda herramienta externa se encapsula; si falta,
   la sonda devuelve `SKIPPED` con motivo, nunca una excepción que tumbe la corrida.
3. **Configuración declarativa.** Objetivos, umbrales y rutas en TOML; el código no
   contiene IPs ni credenciales.
4. **Un fallo no detiene el monitoreo.** Timeout por sonda, reintentos acotados y
   `try/except` por objetivo; al final siempre se escribe resumen y código de salida.
5. **Crudo inmutable + ETL idempotente.** Cada corrida deja un JSONL propio; SQLite
   deduplica por huella; el CSV se regenera desde SQLite.
6. **Seguro por defecto.** `subprocess` sin `shell=True`, credenciales por
   `PGPASSFILE`, timeouts explícitos, sin volcar cuerpos de respuesta a los logs.
7. **El monitor también se observa.** Logs rotativos, resumen por corrida, `run_id`,
   versión de esquema y verificación de reloj.

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
 (ICMP/TCP)  (HTTP/TLS)   (PG/SIP/DNS)  (iperf3/pcap)  (logs/iptables)
   └────────────┴───────────────┴──────────────┴──────────────┘
                │  Resultado (dataclass) normalizado
                ▼
   JSONL crudo → SQLite (huella única) → CSV/JSONL → COPY a PostgreSQL (opcional)
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
| Persistencia | JSONL, SQLite, export, reportes | `writers.py`, `etl/*.py` |
| Soporte | Lock, reintentos, tiempo, red | `bloqueo.py`, `utils/*.py` |

---

## 4. Mapa de la biblioteca estándar

| Necesidad | Módulo stdlib | Uso concreto |
|---|---|---|
| CLI y subcomandos | `argparse` | `run`, `export`, `report`, `prune`, `validate` |
| Configuración | `tomllib` | Lectura de `monitor.toml` (solo lectura, 3.11+) |
| Modelos y enums | `dataclasses`, `enum`, `typing` | `Resultado`, `Objetivo`, `Modulo`, `Estado` |
| Tiempo | `datetime`, `zoneinfo`, `time` | UTC + local; `perf_counter()` para latencias |
| Concurrencia | `concurrent.futures`, `threading` | Sondas I/O en paralelo; evento de parada |
| ICMP | `subprocess` | `ping -n -q -c 4 -W 1` (stdlib no hace ICMP sin root) |
| TCP | `socket` | Conectar a 554, 5060/TCP, 5432 |
| UDP / SIP | `socket`, `secrets` | OPTIONS a Asterisk, `branch`/`Call-ID` aleatorios |
| HTTP/HTTPS | `http.client`, `ssl` | Código, TTFB, tiempo total, versión TLS |
| DNS | `socket.getaddrinfo` | Disponibilidad y latencia de resolución |
| CSV / JSON | `csv`, `json` | Export y JSONL de evidencia |
| Buffer y ETL | `sqlite3` | Histórico, deduplicación, vistas de disponibilidad |
| Logs | `logging`, `logging.handlers` | `RotatingFileHandler` (5 MB × 5) |
| Archivos | `pathlib`, `gzip`, `shutil` | Retención y compresión |
| Instancia única | `fcntl` | `flock` sobre `data/.lock` |
| Apagado limpio | `signal` | SIGINT/SIGTERM → terminar corrida y escribir resumen |
| Estadística | `statistics` | Promedio, mediana, p95 por recurso |
| IDs y huellas | `uuid`, `hashlib` | `run_id`; SHA-256 para deduplicar |
| Correo | `smtplib`, `email.message` | Alertas opcionales (solo stdlib) |
| IPs y VLANs | `ipaddress` | Validar inventario y mapear CIDR → VLAN |
| Capturas pcap | `struct` | Leer cabeceras y extraer DSCP sin `tshark` |
| Pruebas | `unittest`, `unittest.mock` | Fixtures de parsers y servidores locales |
| Sistema | `os`, `sys`, `subprocess` | `systemctl`, `journalctl`, `psql`, `iperf3` |

**Única dependencia opcional:** `psycopg[binary]` para escribir directo en PostgreSQL;
si no está, se usa `psql` + `COPY` desde CSV (ruta 100 % stdlib).

---

## 5. Dependencias externas y degradación

| Herramienta | Uso | Si falta |
|---|---|---|
| `ping` (iputils) | Estado y RTT de cámaras/servidores | Sonda `SKIPPED`; el resto continúa |
| `iperf3` (–J) | Pérdida, jitter, ancho de banda | `SKIPPED`, columnas QoS nulas |
| `tcpdump` | Captura pcap para DSCP | `SKIPPED`; QoS queda solo con iperf3 |
| `psql` | `SELECT 1` y `COPY` a PostgreSQL | Se reporta solo el puerto TCP 5432 |
| `asterisk` CLI | Llamadas activas y canales | Se usa solo el CDR (`Master.csv`) |
| `fail2ban-client` | IPs baneadas | Se parsea `/var/log/fail2ban.log` |
| `systemctl`/`journalctl` | Estado de Apache, DHCP, logs de kernel | Se leen archivos en `/var/log` |

Cada sonda declara `requiere: tuple[str, ...]`; el runner consulta `shutil.which()`
antes de ejecutarla y registra el motivo del `SKIPPED`.

---

## 6. Modelo de datos

### 6.1 Tabla canónica `metricas` (formato largo)

Se conservan **exactamente** los campos pedidos en el documento y se agregan columnas
opcionales; en Power BI las nulas simplemente no participan en cada visual.

| Campo | Tipo | Obligatorio | Ejemplo / notas |
|---|---|---|---|
| `timestamp` | DATETIME local | sí | `2026-11-06 08:30:00` (America/Bogota) |
| `timestamp_utc` | DATETIME UTC | sí | `2026-11-06 13:30:00` |
| `run_id` | TEXT | sí | UUID4 de la corrida |
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
| `fuente` | TEXT | sí | `ping`, `http`, `psql`, `asterisk-cdr`, `journal`, `pcap` |
| `schema_version` | INTEGER | sí | `1` |

**Reglas de normalización**

- Unidades fijas: ms, %, Mbps, segundos; sin sufijos en los valores.
- Booleanos nunca: `estado` es enumeración de texto (mejor para Power BI).
- `timestamp` local sin offset (para el modelo) + `timestamp_utc` (para auditoría).
- `detalle` sin saltos de línea ni comas problemáticas (el CSV igual va citado).
- `evento_seguridad` vacío para filas que no son de seguridad.

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

Permite que Power BI calcule disponibilidad por zona/VLAN sin duplicar metadatos en
cada fila de métricas.

### 6.3 Esquema SQLite

```sql
CREATE TABLE IF NOT EXISTS corridas (
  run_id TEXT PRIMARY KEY,
  inicio_utc TEXT NOT NULL,
  fin_utc TEXT,
  host TEXT NOT NULL,
  exit_code INTEGER,
  version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS metricas (
  id INTEGER PRIMARY KEY,
  huella TEXT NOT NULL UNIQUE,
  run_id TEXT NOT NULL REFERENCES corridas(run_id),
  ts_utc TEXT NOT NULL,
  ts_local TEXT NOT NULL,
  modulo TEXT NOT NULL,
  recurso TEXT NOT NULL,
  nombre TEXT,
  vlan INTEGER,
  zona TEXT,
  estado TEXT NOT NULL,
  latencia_ms REAL,
  perdida_pct REAL,
  jitter_ms REAL,
  ancho_banda_mbps REAL,
  http_status INTEGER,
  puerto INTEGER,
  evento_seguridad TEXT,
  sip_code INTEGER,
  llamadas_activas INTEGER,
  duracion_llamada_s REAL,
  dscp INTEGER,
  detalle TEXT,
  fuente TEXT NOT NULL,
  schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_metricas_ts ON metricas(ts_utc);
CREATE INDEX IF NOT EXISTS idx_metricas_recurso ON metricas(modulo, recurso);

CREATE VIEW IF NOT EXISTS v_disponibilidad_diaria AS
SELECT date(ts_local) AS fecha,
       modulo,
       recurso,
       COUNT(*) AS chequeos,
       SUM(CASE WHEN estado IN ('ONLINE','OK') THEN 1 ELSE 0 END) AS exitosos,
       ROUND(100.0 * SUM(CASE WHEN estado IN ('ONLINE','OK') THEN 1 ELSE 0 END)
             / COUNT(*), 2) AS disponibilidad_pct,
       ROUND(AVG(latencia_ms), 2) AS latencia_prom_ms,
       ROUND(MAX(latencia_ms), 2) AS latencia_max_ms
FROM metricas
GROUP BY 1, 2, 3;
```

La `huella` es `sha256(run_id|modulo|recurso|ts_utc|evento_seguridad)` para que
reingestar el mismo JSONL no duplique filas.

---

## 7. Módulos y sondas

| Módulo | Sonda | Técnica stdlib | Salida principal |
|---|---|---|---|
| `Camaras` | Ping | `subprocess` + `ping -n -q -c 4 -W 1` | `estado`, `tiempo_respuesta_ms`, `perdida_paquetes_pct` |
| `Camaras` | RTSP 554 | `socket.create_connection` (y OPTIONS opcional) | `estado`, `puerto`, latencia de conexión |
| `PortalWeb` | HTTP/HTTPS | `http.client` + `ssl` + `perf_counter` | `http_status`, tiempos, TLS |
| `BaseDatos` | PostgreSQL | `socket` + `psql -w -tAc "SELECT 1"` | `estado`, latencia |
| `VoIP` | SIP 5060 | UDP OPTIONS con `socket` | `sip_code`, `estado` |
| `VoIP` | Asterisk | `asterisk -rx "core show calls"` + CDR | `llamadas_activas`, `duracion_llamada_s`, `sip_code` |
| `QoS` | iperf3 | `iperf3 -J` parseado con `json` | `perdida_paquetes_pct`, `jitter_ms`, `ancho_banda_mbps` |
| `QoS` | DSCP | `tcpdump -w` + parser `pcap` con `struct` | `dscp`, conteos por clase |
| `Seguridad` | iptables | `journalctl -k` o `/var/log/kern.log` con prefijos | `evento_seguridad`, IP origen/destino, VLAN |
| `Seguridad` | fail2ban/SSH | `fail2ban-client status <jail>`, `auth.log` | `evento_seguridad`, IPs |
| `Seguridad` | Inundaciones | `/proc/net/snmp`, `/proc/net/netstat`, pcap | `SYN_FLOOD`, `ICMP_FLOOD` |

### 7.1 Cámaras (VLAN 30)

- Ping con 4 paquetes, `LC_ALL=C` para parsear siempre en inglés; pérdida y RTT
  promedio desde la línea de resumen.
- `estado = ONLINE` si responde al menos un paquete **y** el puerto 554 abre en < 3 s;
  `DEGRADED` si hay respuesta pero el puerto falla; `OFFLINE` si no hay ICMP.
- OPTIONS RTSP opcional (fase 2): enviar `OPTIONS rtsp://IP:554/ RTSP/1.0` y aceptar
  `200`, `401` o `403` como servicio vivo.

### 7.2 Portal web (VM1)

- Medición por etapas con `perf_counter`: resolución DNS, conexión TCP, handshake TLS,
  primer byte (TTFB) y total.
- `estado = DEGRADED` si `tiempo_respuesta_ms > 10 000` (hipótesis del caso) o si el
  código es 5xx; `OK` para 2xx/3xx.
- Verificación del servicio Apache con `systemctl is-active apache2` (o `httpd`),
  registrada como fila aparte con `fuente = systemd`.
- Sin seguir redirecciones automáticamente (máximo 1 salto, configurable).

### 7.3 PostgreSQL, DNS y DHCP

- TCP 5432 como chequeo rápido; si `psql` está disponible, `SELECT 1` cronometrado.
- Credenciales vía `PGPASSFILE` (permisos 600); nunca en TOML ni en la línea de comandos.
- DNS: `getaddrinfo` de un nombre de control y latencia; error → `ERROR`.
- DHCP: `systemctl is-active isc-dhcp-server` o `isc-dhcp-server6` y fecha de
  modificación del archivo de leases; sin cliente DHCP en stdlib, se documenta la limitación.

### 7.4 VoIP

- SIP OPTIONS por UDP con retransmisión T1 (500 ms, 2 intentos); `200/401/403` = vivo.
- `core show calls` entrega llamadas activas; `core show channels concise` permite
  contar canales y detectar llamadas de muelle/garita por contexto.
- CDR: parsear `Master.csv` con `csv`, filtrar por fecha y agregar duración/`disposition`;
  el código SIP se infiere del `disposition` (`ANSWERED`, `BUSY`, `FAILED`, `NO ANSWER`).

### 7.5 QoS

- `iperf3 -c HOST -u -b 20M -t 10 -J` y lectura de `end.sum_received`
  (`loss_percent`, `jitter_ms`) y `end.sum_sent.bits_per_second`; tolerar variantes del JSON.
- DSCP sin `tshark`: `tcpdump -i IFACE -w captura.pcap -c 500` y parser propio con
  `struct` (magic `0xa1b2c3d4`/`0xa1b23c4d`, Ethernet + 802.1Q, IPv4, TOS → `tos >> 2`).
  Se agregan conteos por DSCP (EF=46, AF41=34) y se descartan paquetes no-IP.
- Es la única sonda que genera tráfico pesado: deshabilitada por defecto y ejecutable
  con `--solo qos` en ventana controlada.

### 7.6 Seguridad

- **iptables:** las reglas del escenario deben usar prefijos de log
  (`VLAN30-DROP: `, `VLAN40-DROP: `); el parser los busca en `journalctl -k` o
  `/var/log/kern.log` y extrae IP origen/destino, puerto, interfaz y VLAN (mapa
  interfaz→VLAN en configuración).
- **Contadores:** `iptables -t filter -L INPUT -v -n -x`; se guardan los acumulados y
  el delta por corrida (el delta es lo que se grafica en Power BI).
- **fail2ban:** `fail2ban-client status sshd` (baneadas actuales/totales) y respaldo
  con `/var/log/fail2ban.log` (`Ban`, `Unban`).
- **SSH:** `auth.log`/`journalctl -u ssh` con regex `Failed password for .* from (\S+)`.
- **Inundaciones:** líneas `possible SYN flooding` y contadores `ListenOverflows`/
  `ListenDrops` de `/proc/net/netstat`; ICMP por delta de `/proc/net/snmp`.

---

## 8. Configuración (TOML)

```toml
[general]
zona_horaria = "America/Bogota"
timeout_s = 5
reintentos = 2
max_workers = 12
directorio_datos = "data"
retencion_dias = 90
version_esquema = 1

[camaras]
habilitado = true
ping_paquetes = 4
rtsp_puerto = 554
verificar_rtsp = true

[portal]
habilitado = true
url = "https://10.30.50.5/"
timeout_s = 15
umbral_degradado_s = 10.0

[base_datos]
habilitado = true
host = "10.30.50.5"
puerto = 5432
base = "portocaribe"
usuario = "monitor"
pgpassfile = "/etc/monitor/pgpass"

[voip]
habilitado = true
host_asterisk = "10.30.60.10"
sip_puerto = 5060
cdr = "/var/log/asterisk/cdr-csv/Master.csv"

[qos]
habilitado = false
servidor_iperf = "10.30.50.20"
duracion_s = 10
ancho_banda = "20M"
interfaz_captura = "eth1"
dscp = { voz = 46, video = 34 }

[seguridad]
habilitado = true
prefijos_iptables = ["VLAN30-DROP:", "VLAN40-DROP:"]
log_fail2ban = "/var/log/fail2ban.log"
jail = "sshd"

[[camaras.lista]]
ip = "10.30.30.12"
nombre = "Cam_Muelle_1"
vlan = 30
zona = "muelles"
criticidad = "alta"
```

Validación al arrancar: IPs con `ipaddress`, puertos 1–65535, rutas existentes,
timeouts > 0, zonas horarias con `zoneinfo`, y al menos un módulo habilitado.

---

## 9. Flujo de ejecución

```
1. parsear CLI y cargar TOML + inventario
2. validar configuración (fallo ⇒ exit 2)
3. adquirir lock (si está ocupado ⇒ exit 0 con aviso)
4. crear registro de corrida (run_id, inicio, host)
5. construir lista de sondas habilitadas × objetivos
6. ejecutar en ThreadPoolExecutor; cada sonda aplica timeout y reintentos
7. recolectar Resultado; excepción ⇒ ERROR con detalle, sin abortar
8. escribir data/raw/YYYY-MM-DD/<run_id>.jsonl (fsync)
9. ingestar en SQLite (INSERT OR IGNORE por huella)
10. si --exportar: regenerar CSV diario/semanal desde SQLite
11. imprimir resumen (OK/parcial), cerrar corrida y liberar lock
12. exit 0 si todo OK; 1 si hubo fallos/degradación; 3 si fallo fatal
```

Pseudocódigo del núcleo:

```python
with bloqueo(ruta_lock):
    run_id = uuid.uuid4().hex
    resultados = []
    with ThreadPoolExecutor(max_workers=cfg.max_workers) as pool:
        futuros = {pool.submit(ejecutar, objetivo, cfg): objetivo
                   for objetivo in objetivos(cfg, args)}
        for futuro in as_completed(futuros):
            objetivo = futuros[futuro]
            try:
                resultados.append(futuro.result())
            except Exception as exc:
                resultados.append(resultado_error(objetivo, exc))
    escribir_jsonl(run_id, resultados)
    ingestar_sqlite(run_id, resultados)
    if args.exportar:
        exportar_csv(desde=args.desde, hasta=args.hasta)
    return 0 if resumen.todo_ok else 1
```

Subcomandos:

| Comando | Efecto |
|---|---|
| `run` | Ejecuta sondas, escribe JSONL, ingesta y (opcional) exporta |
| `export` | Regenera CSV/JSONL desde SQLite con filtros de fecha/módulo |
| `report` | Genera `resumen_diario.csv`, `incidentes.csv` y p95 por recurso |
| `prune` | Borra JSONL y filas anteriores a `retencion_dias` |
| `validate` | Solo valida configuración e inventario |

Opciones transversales: `--config`, `--solo`, `--dry-run`, `--simulate`,
`--exportar`, `--verbose`, `--json-logs`.

---

## 10. Robustez y operación

- **Timeouts:** por sonda (5 s por defecto, 15 s HTTP, 20 s iperf3) y total por corrida.
- **Reintentos:** solo ante timeout/error transitorio, 2 intentos con backoff
  exponencial (0.5 s, 1 s) y jitter; una conexión rechazada no se reintenta 5 veces.
- **Instancia única:** `flock` no bloqueante sobre `data/.lock`; si otra corrida está
  activa se omite y se registra.
- **Señales:** SIGTERM/SIGINT activan un `threading.Event`; se deja de lanzar sondas,
  se escribe lo recolectado y se sale con código 1.
- **Reloj:** `timedatectl show -p NTPSynchronized` (o `adjtimex` vía `/proc`) y aviso si
  no está sincronizado; sin reloj confiable el histórico de Power BI se distorsiona.
- **Disco:** verificar espacio libre antes de capturas pcap; borrar temporales en `finally`.
- **Retención:** `prune` por días y compresión `.gz` de JSONL antiguos.
- **Logs:** `monitor.log` rotativo; una línea por sonda con duración y resultado.
- **Códigos de salida:** 0 todo OK, 1 parcial/degradado, 2 configuración inválida, 3 fatal.

---

## 11. Pruebas y criterios de aceptación

| Nivel | Qué se prueba | Cómo (sin red) |
|---|---|---|
| Unitario | Parsers de `ping`, iperf3, CDR, fail2ban, auth.log, iptables, pcap | Fixtures en `tests/fixtures/` |
| Unitario | Normalización, huella, enums, validación TOML | `unittest` |
| Integración | Sonda TCP/HTTP | `socket` local y `http.server.ThreadingHTTPServer` en `127.0.0.1:0` |
| Integración | ETL idempotente (reingesta no duplica) | SQLite temporal |
| Extremo a extremo | `run --simulate` produce CSV válido | `tmp_path` + `subprocess` |
| Manual | Topología real, VLANs y servicios | Lista de verificación del laboratorio |

**Definición de terminado (v1)**

1. `python -m monitor run --simulate` genera CSV con al menos una fila por módulo y
   columnas exactas del esquema v1.
2. En topología real, una corrida con 20 objetivos termina en < 30 s y escribe resumen.
3. Un objetivo inexistente produce `OFFLINE`/`ERROR`, no una traza.
4. `python -m unittest discover -s tests` pasa sin acceso a red.
5. `grep -RhE "^(from|import) " monitor/` solo muestra stdlib (más `psycopg` opcional).
6. Reingestar el mismo JSONL no duplica filas en SQLite.
7. README con configuración, cron/systemd, interpretación de columnas y límites.

---

## 12. Plan por fases

| Fase | Entregable | Horas | Criterio de cierre |
|---|---|---|---|
| **F0. Relevamiento** | Inventario real (IPs, VLANs, servicios, rutas), esquema v1 congelado | 1 | Inventario validado con el documento y la topología |
| **F1. Esqueleto** | Paquete, config TOML, modelos, logging, lock, writer JSONL, CLI, 5 tests | 3 | `validate` y `run --dry-run` funcionan |
| **F2. Sondas núcleo** | ICMP, TCP, RTSP, HTTP/TLS, concurrencia y reintentos | 4 | Cámaras y portal reales en CSV |
| **F3. Servicios** | PostgreSQL, SIP, DNS, Asterisk/CDR | 3 | Filas con `sip_code`, `duracion_llamada_s`, `llamadas_activas` |
| **F4. QoS** | iperf3 `-J` y parser pcap/DSCP | 4 | Pérdida, jitter y DSCP en el dataset |
| **F5. Seguridad** | Parseo de iptables/journal, fail2ban, SSH y contadores | 4 | Eventos con IP origen/destino y delta de contadores |
| **F6. Persistencia** | SQLite, huella, export CSV/JSONL, reporte diario, `prune` | 3 | Export idempotente y vistas de disponibilidad |
| **F7. Calidad** | Fixtures completos, `--simulate`, inyección de fallos | 3 | Suite verde y corrida simulada reproducible |
| **F8. Operación** | `systemd` unit/timer, README, runbook y evidencias | 2 | Timer activo y documentación entregada |

**Total estimado: ~27 h.** Ruta mínima para demo (F0–F2 + `--simulate` + CSV): ~10 h.

**Sugerencia de orden:** F0 → F1 → F2 → F6 (para tener CSV cuanto antes) → F3 → F5 →
F4 → F7 → F8. QoS al final porque es la única que altera el tráfico del laboratorio.

---

## 13. Estructura de archivos propuesta

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
│   ├── bloqueo.py
│   ├── sondas/
│   │   ├── __init__.py        # registro y metadatos (requiere, módulo)
│   │   ├── icmp.py
│   │   ├── tcp.py
│   │   ├── http.py
│   │   ├── postgres.py
│   │   ├── sip.py
│   │   ├── asterisk.py
│   │   ├── iperf.py
│   │   ├── pcap.py
│   │   ├── seguridad.py
│   │   └── sistema.py
│   ├── etl/
│   │   ├── sqlite.py
│   │   ├── export.py
│   │   └── reporte.py
│   └── utils/
│       ├── tiempo.py
│       ├── red.py
│       └── reintentos.py
├── config/
│   ├── monitor.ejemplo.toml
│   └── inventario.ejemplo.csv
├── sql/
│   ├── schema_sqlite.sql
│   └── schema_postgres.sql
├── tests/
│   ├── fixtures/
│   └── test_*.py
├── data/                      # generado, ignorado por git
├── pyproject.toml             # sin dependencias obligatorias
└── README.md
```

`pyproject.toml` declara `requires-python = ">=3.11"` y
`dependencies = []`; `psycopg[binary]` va en `[project.optional-dependencies].pg`.

---

## 14. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Parseo de `ping` dependiente del idioma | Pérdida de latencias | `LC_ALL=C` y fixtures en inglés/español |
| ICMP/tcpdump requieren privilegios | Sonda no ejecuta | `setcap cap_net_raw+ep` o corrida como servicio; degradar a TCP |
| `iperf3`/`tshark` ausentes | Sin métricas QoS | Adaptador `SKIPPED`, columnas nulas, alternativa pcap+`tcpdump` |
| Formatos de log variables | Eventos de seguridad vacíos | Prefijos fijos en `iptables`, regex en configuración, fixtures |
| Reloj desincronizado | Series temporales inconsistentes | Verificación NTP y advertencia en el resumen |
| Solapamiento de corridas | Filas duplicadas/archivos corruptos | `flock` + huella única en SQLite |
| Credenciales de PostgreSQL | Exposición | `PGPASSFILE` 600, sin secretos en TOML ni en argumentos |
| CSV abierto en Excel durante el export | Escritura fallida | Export a archivo nuevo con marca de tiempo; reintento y aviso |
| Volumen de datos | Crecimiento del disco | Retención 90 días, compresión y tabla de agregados |
| Demo sin topología | No hay evidencia | `--simulate` determinista (semilla fija) y modo `--dry-run` |

**Nota de alcance:** el script solo debe apuntar a activos del laboratorio y de la
topología del proyecto; no se debe ejecutar contra redes de terceros.

---

## 15. Decisiones pendientes

1. ¿El script correrá dentro de una VM de la topología (con acceso a VLAN 30/50/60) o
   desde el host? ¿Tendrá privilegios para ICMP crudo y `tcpdump`?
2. ¿La entrega final debe cargar en PostgreSQL o basta CSV/JSONL? Si es PostgreSQL,
   ¿se autoriza `psycopg` como única dependencia opcional?
3. ¿Los servicios de Asterisk, fail2ban y DHCP ya existen en el escenario o se simulan
   con archivos de ejemplo?
4. ¿Frecuencia y ventana de recolección para el informe (p. ej. cada 5 min durante 7 días)?
5. ¿Se requiere que el script genere también los gráficos/medidas de Power BI o solo el
   dataset y la documentación de medidas?

## 16. Siguiente paso

Cerrar F0 con el inventario real y luego implementar F1 (esqueleto + configuración +
writer JSONL + `--dry-run`). Con eso se valida el contrato de datos antes de escribir
cualquier sonda.

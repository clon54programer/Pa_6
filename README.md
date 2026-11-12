# PortoCaribe Logística S.A. — Proyecto de Aula

Implementación del proyecto para la bodega de **Mamonal, Cartagena**: un **monitor de
infraestructura** y un **portal de clientes de demostración**, ambos con Python y
biblioteca estándar, más la documentación de diseño que los respalda.

El objetivo académico es demostrar cómo se pueden medir disponibilidad, rendimiento,
QoS y seguridad con herramientas livianas, y cómo el portal puede mejorar la experiencia
del cliente frente a los problemas originales: consultas superiores a 10 segundos,
poca visibilidad de la carga y necesidad de controles de acceso.

> **Estado:** monitor implementado y probado (**34 pruebas**), portal validado,
> documentación y artefactos de despliegue listos. Los datos del portal son ficticios.
>
> **Desplegado en dos VM** (red `192.168.100.0/24`, 2026-11-11):
>
> - **VM1 `192.168.100.60`:** monitor + **Asterisk** (SIP 5060, AMI 5038, CDR) + captura
>   QoS + portal de respaldo. Detalles en [`DESPLIEGUE_VM1.md`](DESPLIEGUE_VM1.md).
> - **VM2 `192.168.100.59`:** portal principal, **PostgreSQL**, **fail2ban**,
>   **iptables** (VLAN30/40-DROP) y **DHCP**. Detalles en
>   [`DESPLIEGUE_VM2.md`](DESPLIEGUE_VM2.md).
>
> El monitor mide **datos reales** de portal, base de datos, VoIP, QoS, seguridad y DHCP;
> solo las **cámaras VLAN 30** siguen fuera de alcance (no hay hardware). Estado y
> evidencias en [`PENDIENTES.md`](PENDIENTES.md); medidas de Power BI en
> [`powerbi/`](powerbi/).

---

## 1. Componentes del proyecto

| Componente | Qué hace | Dónde |
|---|---|---|
| **Monitor** | Sondea cámaras, portal, PostgreSQL, Asterisk, seguridad y DHCP; escribe JSONL y exporta CSV para Power BI | [`monitor/`](monitor/) |
| **Portal demo** | Login, rastreo de contenedores por número/BL/orden, timeline, avisos y widget de rendimiento | [`portal/`](portal/) |
| **Planes** | Requisitos y diseño del monitor y de la landing | [`plan_de_script_python.md`](plan_de_script_python.md), [`plan_implementacion_monitor.md`](plan_implementacion_monitor.md), [`landing_pages_plan.md`](landing_pages_plan.md), [`plan_implementacion_landing.md`](plan_implementacion_landing.md) |
| **Dataset** | Muestra del monitor en CSV/JSONL | [`data/csv/metricas_2026-11-06.csv`](data/csv/metricas_2026-11-06.csv), [`data/raw/2026-11-06/`](data/raw/2026-11-06/) |
| **Despliegue** | Apache, systemd, cron/timers y recolección SSH | [`apache/`](apache/), [`programacion/`](programacion/), [`config/ssh/`](config/ssh/) |
| **Despliegue en VM1** | Instalador idempotente, Asterisk, QoS y units del monitor | [`despliegue/vm1/`](despliegue/vm1/), [`DESPLIEGUE_VM1.md`](DESPLIEGUE_VM1.md) |
| **Despliegue en VM2** | Portal, PostgreSQL, fail2ban, iptables y DHCP | [`despliegue/vm2/`](despliegue/vm2/), [`DESPLIEGUE_VM2.md`](DESPLIEGUE_VM2.md) |
| **Power BI** | Medidas DAX y guía del tablero | [`powerbi/`](powerbi/) |
| **Pendientes** | Estado, brechas y prioridades | [`PENDIENTES.md`](PENDIENTES.md) |

---

## 2. Arquitectura

```
                    ┌──────────────────────────────────┐
                    │ VM1  192.168.100.60              │
                    │ python -m monitor                │
                    │  · sondas de red                 │
                    │  · SSH de solo lectura a VM2     │
                    │  · JSONL → CSV                   │
                    │ Asterisk: SIP 5060, AMI 5038,CDR │
                    │ tcpdump QoS (DSCP)               │
                    └───────┬──────────────────────────┘
                            │ SSH (monitor, sudo acotado)
                            │ HTTPS 443 · psql 5432 · SIP/AMI
                    ┌───────▼──────────────────────────┐
                    │ VM2  192.168.100.59              │
                    │ Portal (Apache + Python)         │
                    │ PostgreSQL, fail2ban,            │
                    │ iptables VLAN30/40-DROP, DHCP    │
                    │ iperf3 :5201                     │
                    └──────────────────────────────────┘
```

- **VM1:** monitor y Asterisk. Consulta SIP/AMI localmente, lee el CDR y captura DSCP;
  trae de VM2 los snapshots de seguridad/DHCP/Apache.
- **VM2:** portal principal, PostgreSQL, fail2ban, iptables y DHCP. Responde HTTP/HTTPS y
  PostgreSQL al monitor.
- **NFS se descartó**; la recolección es por SSH con clave dedicada, wrapper cerrado y
  `sudoers` restringido.
- El portal se publica con **Apache en 443** y este hace proxy a `127.0.0.1:8080`.

Flujo del monitor:

```
config TOML + inventario
        │
   run (cada 5 min) ──► JSONL crudo (data/raw/AAAA-MM-DD/)
        │
   export (23:59) ────► CSV del día (data/csv/)
        │
   Power BI (medidas y gráficos los elabora otra persona)
```

---

## 3. Monitor

### Qué mide

| Módulo | Fuente | Datos principales |
|---|---|---|
| Cámaras | `ping` + TCP 554 | estado, latencia, pérdida, RTSP |
| Portal | HTTP/HTTPS + snapshot Apache | código, tiempos, estado del servicio |
| Base de datos | TCP 5432 + `psql` | disponibilidad y `SELECT 1` |
| VoIP | SIP OPTIONS + AMI + CDR | código SIP, llamadas activas, duración |
| QoS | `iperf3 -J` + pcap | pérdida, jitter, ancho de banda, DSCP |
| Seguridad | iptables, fail2ban, auth, kernel | IPs, reglas, baneos, SYN/ICMP flood |
| DHCP | estado + leases | servicio activo y leases |

Módulos activos en el laboratorio: **portal, base de datos, VoIP, QoS, seguridad y DHCP**.
Cámaras queda deshabilitado hasta que exista la VLAN 30.

### Salidas

- **JSONL crudo:** `data/raw/YYYY-MM-DD/HHMMSS_<run_id>.jsonl`, escrito de forma atómica.
- **CSV del día:** `data/csv/metricas_YYYY-MM-DD.csv`, 27 columnas, `utf-8-sig`.
- **Deduplicación:** cada fila lleva una `huella` interna; los eventos de log usan una
  huella estable para que releerlos no duplique filas.
- **Cierre diario:** `export` reconstruye el CSV y es idempotente (mismo SHA-256).
- **Retención:** `prune` comprime a `.gz` los JSONL de más de `comprimir_dias` (7) y borra
  lo que excede `retencion_dias` (180); `export` lee también los `.gz`.

### Ejecución

```bash
python3 -m monitor validate --config monitor.toml
python3 -m monitor run --config monitor.toml --simulate
python3 -m monitor export --config monitor.toml
python3 -m monitor recolectar --config monitor.toml --host vm2
```

- `--simulate` genera una muestra determinista sin tocar la red.
- `--solo camaras,portal` limita los módulos.
- `--dry-run` muestra el plan sin ejecutar.
- `--json-logs` emite una línea JSON por registro.
- `recolectar` trae snapshots por SSH en paralelo (máx. 8); `prune` aplica retención.

### Robustez (§11)

- Reintentos con backoff 0,5 s / 1 s + jitter en todas las sondas.
- `timeout_total_s = 120` por corrida: lo que no termina se reporta como `ERROR`.
- `SIGTERM`/`SIGINT` cierran la corrida, escriben el JSONL y salen con 1.
- Chequeo NTP (`timedatectl`) en cada corrida; el resumen muestra `ntp=…`.
- `inventario.csv` es la dimensión de nombre/VLAN/zona; el TOML solo describe qué medir.

La muestra incluida se generó con `--simulate` (el directorio `data/` no se versiona;
se regenera con los comandos anteriores):

- **14 filas**, 6 módulos, 27 columnas.
- 2 cámaras, 2 filas de portal (HTTP + Apache), 1 base de datos, 5 VoIP (SIP + AMI + 3 CDR),
  3 eventos de seguridad y 1 DHCP.
- Pruebas: **34/34 OK** en [`tests_monitor/`](tests_monitor/) (incluye sonda HTTP real,
  reintentos, señales, gzip e inventario).

Para la operación real: activar `recoleccion.habilitado = true`, desplegar la clave y el
wrapper de [`config/ssh/`](config/ssh/), y programar
[`programacion/cron.monitor`](programacion/cron.monitor) o los timers.

---

## 4. Portal de clientes (demo)

### Funcionalidades

- Login con `scrypt`, sesiones con TTL, CSRF y rate limit de 5 intentos/10 min.
- Bloqueo temporal visible con cuenta regresiva.
- Búsqueda por número de contenedor (ISO 6346), BL u orden de despacho.
- Estado actual, detalles de la carga y timeline desde el buque hasta la garita.
- Avisos operativos y canal de soporte (datos de demostración).
- Widget de rendimiento con medición del servidor (`perf_counter`) y del navegador
  (`performance.now`), sin depender del monitor.
- Interfaz responsive, accesible y sin frameworks ni CDN.

### Ejecución local

```bash
python3 -m portal --config portal.dev.toml
```

Abre `http://127.0.0.1:8080`.

- Usuario: `cliente.demo`
- Contraseña: `Porto2026*`

Pruebas del portal:

```bash
python3 -m unittest discover -s tests -v
```

### Producción

- Configuración: [`portal.toml`](portal.toml).
- Apache/TLS: [`apache/portal-portocaribe.conf`](apache/portal-portocaribe.conf).
- Servicio: [`programacion/portal.service`](programacion/portal.service).
- La base es SQLite para no tocar la PostgreSQL real; la capa `datos.py` está separada
  para migrarla después.

---

## 5. Seguridad implementada

**Portal**

- `scrypt` (n=2¹⁴, r=8, p=1) con sal; comparación en tiempo constante.
- Cookie `HttpOnly; Secure; SameSite=Strict` en producción.
- CSRF en `POST /api/logout`.
- Rate limit por usuario/IP y bloqueo de 120 s.
- CSP, HSTS (Apache), `nosniff`, `X-Frame-Options`, `Referrer-Policy`.
- Validación de entrada, SQL parametrizado, rutas estáticas confinadas y cuerpo máximo.

**Monitor**

- SSH con clave ed25519, `from=`, `restrict` y `command=` a un wrapper de recetas.
- `sudoers` con comandos exactos; sin `shell=True`.
- Snapshots atómicos y estado `STALE` si el archivo no se actualiza.
- Secretos AMI por variable de entorno (`/etc/monitor/ami.env`), nunca en TOML.
- AMI con `permit = 127.0.0.1` y solo las clases necesarias (`read = call,reporting`,
  `write = system` para `CoreShowChannels`).

---

## 6. Estructura del repositorio

```
.
├── monitor/                  # Código del monitor y su README
├── portal/                   # Portal demo (backend + web/)
├── tests/                    # Pruebas del portal
├── tests_monitor/            # Pruebas del monitor
├── apache/                   # VirtualHost con TLS y proxy
├── config/ssh/               # Wrapper, authorized_keys y sudoers
├── programacion/             # systemd, timers y cron
├── despliegue/
│   ├── comun/                # Repos APT y recolección SSH compartida
│   ├── vm1/                  # Instaladores, Asterisk, QoS y units
│   ├── vm2/                  # PostgreSQL, fail2ban, iptables, DHCP, iperf3
│   └── diagnostico/          # Scripts de verificación usados en el laboratorio
├── powerbi/                  # Medidas DAX y guía del tablero
├── data/                     # Generado: raw/, csv/, entradas/, estado/
├── monitor.toml              # Configuración del monitor
├── portal.toml               # Configuración de producción del portal
├── portal.dev.toml           # Configuración local del portal
├── inventario.csv            # Dimensión de recursos
├── pyproject.toml            # Sin dependencias
├── plan_*.md / landing_*.md  # Documentación de diseño
└── README.md                 # Este documento
```

---

## 7. Documentación

| Documento | Contenido |
|---|---|
| [`PENDIENTES.md`](PENDIENTES.md) | Estado del proyecto, evidencia y pendientes reales |
| [`GUIA_PRUEBAS.md`](GUIA_PRUEBAS.md) | Guía paso a paso para probar Asterisk y los servicios de VM2 |
| [`DESPLIEGUE_VM1.md`](DESPLIEGUE_VM1.md) | Monitor, Asterisk, QoS y portal de respaldo |
| [`DESPLIEGUE_VM2.md`](DESPLIEGUE_VM2.md) | Portal, PostgreSQL, fail2ban, iptables y DHCP |
| [`powerbi/README.md`](powerbi/README.md) | Carga del CSV, modelo y páginas del tablero |
| [`plan_de_script_python.md`](plan_de_script_python.md) | Métricas y dataset solicitados para el monitor |
| [`plan_implementacion_monitor.md`](plan_implementacion_monitor.md) | Diseño del monitor: sondas, SSH, CSV, fases y pruebas |
| [`landing_pages_plan.md`](landing_pages_plan.md) | Requisitos de la landing del portal |
| [`plan_implementacion_landing.md`](plan_implementacion_landing.md) | Diseño del portal demo, API, seguridad y despliegue |
| [`monitor/README.md`](monitor/README.md) | Uso y operación del monitor |
| [`portal/README.md`](portal/README.md) | Uso y despliegue del portal |
| [`firewall/README.md`](firewall/README.md) | Firewall/router ASA 5505: configuración, pruebas y reconexión |

---

## 8. Decisiones y alcance

- **Solo biblioteca estándar** en Python; sin Flask, Django, pandas ni requests.
- **Muestreo cada 5 minutos** y cierre diario a las 23:59; el CSV se reconstruye desde
  los JSONL.
- **Dos VMs de servicio** (VM1 y VM2) y el monitor en VM1.
- **NFS descartado** a favor de SSH de solo lectura.
- **TLS en Apache**, no en Python; el backend escucha solo en loopback.
- **Power BI** consume el CSV; las medidas y la guía están en [`powerbi/`](powerbi/).
- **Datos ficticios** en el portal; soporte, logo y colores son placeholders.

## 9. Límites conocidos

- El portal usa SQLite y sesiones en memoria; reiniciar el servicio cierra sesiones.
- El certificado de laboratorio es autofirmado.
- **Cámaras VLAN 30:** no hay equipos en la red del aula; el módulo está deshabilitado.
- **Asterisk 16** proviene de bullseye (bookworm lo retiró); es deuda técnica.
- El primer **día completo** de dataset será el 2026-11-12.
- Sin backups automáticos ni alertas si el monitor falla.

## 10. Siguientes pasos

1. Dejar correr los timers y cerrar el primer día completo (288 JSONL) con `export`.
2. Montar el tablero `.pbix` con [`powerbi/`](powerbi/) sobre el CSV real.
3. Incorporar las cámaras de la VLAN 30 y activar el módulo.
4. Añadir backups (`pg_dump`, `portal.db`, CSV) y una alerta cuando `run` devuelva 1 o 3.
5. Sustituir el certificado autofirmado y fijar la IP (o usar DNS).
6. Si el alcance lo pide, migrar la capa de datos del portal de SQLite a PostgreSQL.

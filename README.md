# PortoCaribe Logística S.A. — Proyecto de Aula

Implementación del proyecto para la bodega de **Mamonal, Cartagena**: un **monitor de
infraestructura** y un **portal de clientes de demostración**, ambos con Python y
biblioteca estándar, más la documentación de diseño que los respalda.

El objetivo académico es demostrar cómo se pueden medir disponibilidad, rendimiento,
QoS y seguridad con herramientas livianas, y cómo el portal puede mejorar la experiencia
del cliente frente a los problemas originales: consultas superiores a 10 segundos,
poca visibilidad de la carga y necesidad de controles de acceso.

> **Estado:** monitor implementado y probado (18 pruebas), portal implementado y validado
> funcionalmente, documentación y artefactos de despliegue listos. Los datos del portal
> son ficticios y el dataset del monitor que se incluye proviene de una corrida
> simulada.
>
> **Desplegado en VM1** (`192.168.137.54`, Debian 12) el 2026-11-07: el portal se publica
> con Apache en `https://192.168.137.54/` y el monitor muestrea cada 5 minutos con
> `systemd` (cierre diario del CSV a las 23:59). Detalles, rutas, operación y
> verificación en [`DESPLIEGUE_VM1.md`](DESPLIEGUE_VM1.md). VM2, cámaras y VoIP siguen
> fuera de alcance.

---

## 1. Componentes del proyecto

| Componente | Qué hace | Dónde |
|---|---|---|
| **Monitor** | Sondea cámaras, portal, PostgreSQL, Asterisk, seguridad y DHCP; escribe JSONL y exporta CSV para Power BI | [`monitor/`](monitor/) |
| **Portal demo** | Login, rastreo de contenedores por número/BL/orden, timeline, avisos y widget de rendimiento | [`portal/`](portal/) |
| **Planes** | Requisitos y diseño del monitor y de la landing | [`plan_de_script_python.md`](plan_de_script_python.md), [`plan_implementacion_monitor.md`](plan_implementacion_monitor.md), [`landing_pages_plan.md`](landing_pages_plan.md), [`plan_implementacion_landing.md`](plan_implementacion_landing.md) |
| **Dataset** | Muestra del monitor en CSV/JSONL | [`data/csv/metricas_2026-11-06.csv`](data/csv/metricas_2026-11-06.csv), [`data/raw/2026-11-06/`](data/raw/2026-11-06/) |
| **Despliegue** | Apache, systemd, cron/timers y recolección SSH | [`apache/`](apache/), [`programacion/`](programacion/), [`config/ssh/`](config/ssh/) |
| **Despliegue en VM1** | Instalador idempotente, configs y units de la máquina real | [`despliegue/vm1/`](despliegue/vm1/), [`DESPLIEGUE_VM1.md`](DESPLIEGUE_VM1.md) |
| **Pendientes** | Brechas de alcance, robustez, dataset y prioridades | [`PENDIENTES.md`](PENDIENTES.md) |

---

## 2. Arquitectura

```
                         ┌──────────────────────────────┐
                         │ VM de monitoreo              │
                         │ python -m monitor            │
                         │  · sondas de red             │
                         │  · SSH de solo lectura       │
                         │  · JSONL → CSV               │
                         └───────┬──────────────┬───────┘
                                 │ SSH          │ HTTP / SIP / AMI
                 ┌───────────────▼───┐      ┌───▼────────────────────────┐
                 │ VM1               │      │ VM2                        │
                 │ Asterisk + cámaras│      │ Portal (Apache + Python)   │
                 │ CDR               │      │ PostgreSQL, fail2ban,      │
                 │ AMI: TCP 5038     │      │ iptables, DHCP             │
                 └───────────────────┘      └────────────────────────────┘
```

- **VM1:** Asterisk y el servicio de cámaras. El monitor consulta AMI y SIP, y trae el
  CDR por SSH.
- **VM2:** portal, PostgreSQL, fail2ban, iptables y DHCP. El monitor consulta HTTP/HTTPS
  y trae snapshots de Apache, seguridad y DHCP por SSH.
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

### Salidas

- **JSONL crudo:** `data/raw/YYYY-MM-DD/HHMMSS_<run_id>.jsonl`, escrito de forma atómica.
- **CSV del día:** `data/csv/metricas_YYYY-MM-DD.csv`, 27 columnas, `utf-8-sig`.
- **Deduplicación:** cada fila lleva una `huella` interna; los eventos de log usan una
  huella estable para que releerlos no duplique filas.
- **Cierre diario:** `export` reconstruye el CSV y es idempotente (mismo SHA-256).

### Ejecución

```bash
python3 -m monitor validate --config monitor.toml
python3 -m monitor run --config monitor.toml --simulate
python3 -m monitor export --config monitor.toml
```

- `--simulate` genera una muestra determinista sin tocar la red.
- `--solo camaras,portal` limita los módulos.
- `--dry-run` muestra el plan sin ejecutar.
- `recolectar` trae snapshots por SSH; `prune` aplica retención.

La muestra incluida se generó con `--simulate` (el directorio `data/` no se versiona;
se regenera con los comandos anteriores):

- **14 filas**, 6 módulos, 27 columnas.
- 2 cámaras, 2 filas de portal (HTTP + Apache), 1 base de datos, 5 VoIP (SIP + AMI + 3 CDR),
  3 eventos de seguridad y 1 DHCP.
- Pruebas: **18/18 OK** en [`tests_monitor/`](tests_monitor/).

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
- Secretos AMI por variable de entorno, nunca en TOML.

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
| [`plan_de_script_python.md`](plan_de_script_python.md) | Métricas y dataset solicitados para el monitor |
| [`plan_implementacion_monitor.md`](plan_implementacion_monitor.md) | Diseño del monitor: sondas, SSH, CSV, fases y pruebas |
| [`landing_pages_plan.md`](landing_pages_plan.md) | Requisitos de la landing del portal |
| [`plan_implementacion_landing.md`](plan_implementacion_landing.md) | Diseño del portal demo, API, seguridad y despliegue |
| [`monitor/README.md`](monitor/README.md) | Uso y operación del monitor |
| [`portal/README.md`](portal/README.md) | Uso y despliegue del portal |

---

## 8. Decisiones y alcance

- **Solo biblioteca estándar** en Python; sin Flask, Django, pandas ni requests.
- **Muestreo cada 5 minutos** y cierre diario a las 23:59; el CSV se reconstruye desde
  los JSONL.
- **Dos VMs de servicio** (VM1 y VM2) y una VM de monitoreo.
- **NFS descartado** a favor de SSH de solo lectura.
- **TLS en Apache**, no en Python; el backend escucha solo en loopback.
- **Solo dataset** para Power BI; las medidas y gráficos los elabora otra persona.
- **Datos ficticios** en el portal; soporte, logo y colores son placeholders.

## 9. Límites conocidos

- El portal usa SQLite y sesiones en memoria; reiniciar el servicio cierra sesiones.
- El certificado de laboratorio es autofirmado.
- El monitor real necesita acceso a VM1/VM2, clave SSH y snapshots publicados; la
  muestra incluida es simulada.
- QoS está deshabilitado por defecto porque genera tráfico.
- La corrida simulada no demuestra carga concurrente de múltiples buques; para eso está
  el histórico del monitor en el laboratorio.

## 10. Siguientes pasos

1. Desplegar el portal en VM2 con Apache y systemd.
2. Desplegar la clave/wrapper en VM1 y VM2, activar `recoleccion.habilitado` y probar
   `recolectar`.
3. Programar el muestreo cada 5 minutos y el cierre de las 23:59.
4. Acumular varios días de CSV y entregarlos al responsable de Power BI.
5. Si se requiere, migrar la capa de datos del portal de SQLite a PostgreSQL.

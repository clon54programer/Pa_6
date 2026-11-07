# Pendientes del proyecto PortoCaribe

Estado de brechas al **2026-11-07**, tras desplegar el portal y el monitor en VM1
(`192.168.137.54`). Se contrasta el código y la máquina real contra
[`plan_implementacion_monitor.md`](plan_implementacion_monitor.md),
[`plan_implementacion_landing.md`](plan_implementacion_landing.md) y el runbook
[`DESPLIEGUE_VM1.md`](DESPLIEGUE_VM1.md).

> **Resumen en una línea:** los dos aplicativos funcionan y están verificados en VM1; lo
> que falta es la **topología** (VM2, cámaras, Asterisk, QoS, DHCP), la **recolección SSH**
> entre máquinas, algunas **garantías de robustez** que el plan exige y que el código no
> implementa, y la **entrega de Power BI**.

---

## 1. Panorama

| Bloque | Estado |
|---|---|
| Portal de clientes (login, rastreo, avisos, rendimiento) | **Desplegado y verificado** en VM1 |
| Publicación Apache + TLS | **Desplegado** (certificado autofirmado) |
| Monitor: muestreo cada 5 min y CSV diario | **Desplegado y verificado** (timers systemd) |
| Monitor: módulo Portal | **Activo** (HTTP/HTTPS + estado Apache) |
| Monitor: seguridad, cámaras, VoIP, BD, DHCP, QoS | **Código listo, sin infraestructura** (deshabilitados en VM1) |
| Recolección SSH VM1/VM2 | **Código y plantillas listos, nunca ejecutados** |
| Robustez (§11 del plan: reintentos, señales, timeout total, NTP) | **No implementado** |
| Dataset real de 24 h y Power BI | **Pendiente** (primer CSV completo: 2026-11-08) |

---

## 2. Bloques de alcance que aún no existen

| Falta | Qué implica | Depende de |
|---|---|---|
| **VM2** | portal secundario y PostgreSQL, fail2ban, iptables con reglas `VLAN30-DROP`/`VLAN40-DROP`, DHCP | otra VM |
| **Recolección SSH** | usuario `monitor` + `authorized_keys` con `from=`/`restrict`/`command=`, wrapper `/usr/local/bin/monitor-readonly`, `/etc/sudoers.d/monitor`, `known_hosts` fijado y clave ed25519 600 | VM1/VM2 |
| **Cámaras VLAN 30** | ping + RTSP 554; no hay ningún equipo en esa VLAN (los `10.30.30.12/13` del TOML son de ejemplo) | topología |
| **Asterisk / VoIP** | SIP OPTIONS 5060, AMI 5038 con usuario de solo lectura y `permit` por IP, CDR `Master.csv` | VM1 del plan / Asterisk |
| **QoS** | `iperf3` y `tcpdump` **no están instalados** en VM1; la sonda DSCP nunca vio un pcap real | VM2 / equipo de medición |
| **DHCP** | `isc-dhcp-server` no existe; VM1 usa NetworkManager | VM2 |

Ninguno se resuelve programando: son máquinas y servicios que todavía no están en el
laboratorio.

---

## 3. Brechas del monitor contra su propio plan (§11 y §12)

El monitor opera, pero varias garantías del documento **no están implementadas**. Se
verificaron por búsqueda sobre [`monitor/`](monitor/):

| Carencia | Evidencia | Impacto | Esfuerzo |
|---|---|---|---|
| **Reintentos con backoff** (0,5 s / 1 s + jitter) | `reintentos = 2` solo aparece en [`config.py`](monitor/config.py): nadie lo consume | un timeout transitorio se reporta como `ERROR` definitivo | 3 h |
| **Manejo de SIGTERM/SIGINT** | no hay `import signal` en el paquete | una corrida cortada no escribe resumen ni libera ordenadamente | 2 h |
| **`timeout_total_s = 120`** | se valida en [`config.py`](monitor/config.py) pero no se aplica | una sonda colgada puede estirar la corrida más de lo previsto | 2 h |
| **Verificación de reloj NTP** | no hay referencia a `timedatectl` | eventos de log fuera de orden sin aviso | 1 h |
| **`inventario.csv` como dimensión** | el archivo existe y **ningún módulo lo lee**; `vlan`/`zona` se repiten en el TOML | metadatos duplicados y riesgo de inconsistencia para Power BI | 2 h |
| **`--json-logs`** | opción prometida en §10, ausente en [`cli.py`](monitor/cli.py) | sin logs estructurados para operación | 1 h |
| **Compresión `.gz` de JSONL antiguos** | `prune` solo borra por fecha ([`escritura.py`](monitor/escritura.py)) | retención de 180 días ocupa más disco del previsto | 1 h |
| **`recolectar` en paralelo (máx. 8)** | [`recoleccion.py`](monitor/recoleccion.py) recorre las recetas en serie | cada muestra puede tardar 10× más de lo diseñado | 2 h |

Cobertura de pruebas: **18/18 pasan** en Linux, pero ninguna cubre la sonda HTTP (por eso
el bug `http.client` llegó a producción) ni la recolección SSH. Faltan fixtures para
`http` y pruebas de integración del portal en la VM.

---

## 4. Dataset y entrega para Power BI

- Hoy cada muestra deja **2 filas** (portal + Apache) → 576 filas/día. El escenario del
  plan (≈8 600 filas/día) requiere VM2, cámaras y Asterisk.
- **Seguridad sigue deshabilitada** en VM1: sus fuentes son de VM2 y, con las reglas `ufw`
  locales, el módulo etiquetaría tráfico `ACCEPT` como `VLAN40_BLOCKED`.
- **No existe todavía un día completo**: el primer `export` de 24 h será el del
  **2026-11-08 23:59** (288 JSONL, criterio 9 de §12).
- Falta el **entregable de Power BI**: medidas DAX y gráficos. El plan los asigna a otra
  persona; el CSV y el JSONL ya están en el formato acordado (`utf-8-sig`, 27 columnas).
- La muestra del repositorio (`data/`) es de simulación, no evidencia de la topología.

---

## 5. Operación y hardening

- **IP dinámica:** `enp0s3` toma `192.168.137.54` por DHCP. Si cambia, el certificado
  (SAN con la IP) y el destino del monitor dejan de cuadrar → fijar IP o usar DNS.
- **Certificado autofirmado:** sirve para la demo; para producción hace falta CA o
  dominio real (`portal.portocaribe.local` solo resuelve dentro de la VM).
- **Sin backups** de `/var/lib/portal/portal.db` ni del dataset (180 días de retención sin
  respaldo).
- **Nadie vigila al monitor:** si un timer falla, el único rastro es `journalctl -u`.
  Falta una alerta (correo/telegram/healthcheck) cuando `run` devuelve 1 o 3.
- **Portal:** tiene CSRF, cookies `Secure`, límite de intentos y CSP propios, pero no
  fail2ban (previsto para VM2).
- **`sudo` no existe en VM1:** toda tarea de root va con `su -`; conviene documentarlo para
  quien retome el proyecto.

---

## 6. Trazabilidad con las fases del plan

| Fase | Entregable | Estado |
|---|---|---|
| **F0** Relevamiento | inventario, claves SSH, wrapper/sudoers, usuario AMI, dos VMs | **Parcial**: inventario y plantillas; faltan las VMs y las claves instaladas |
| **F1** Esqueleto | paquete, TOML, modelos, logging, lock, writers, CLI, 5 tests | **Hecho** |
| **F2** Sondas núcleo | ICMP, TCP, RTSP, HTTP/TLS, concurrencia y reintentos | **Parcial**: sondas OK; reintentos no |
| **F3** Export | JSONL atómico, CSV reconstruible, prune | **Hecho** (prune sin gzip) |
| **F4** Asterisk y portal | SIP, AMI, CDR y `recolectar` de VM1/VM2 | **Código hecho**, sin infraestructura ni prueba real |
| **F5** Seguridad | dedupe, iptables, fail2ban, auth/kern, `recolectar` VM2 | **Código hecho**, deshabilitado en VM1 |
| **F6** DHCP + QoS | leases/estado y QoS opcional | **Código hecho**, sin infraestructura |
| **F7** Calidad | fixtures, `--simulate`, frescura y dedupe | **Casi**: 18 tests; falta cobertura de la sonda HTTP |
| **F8** Operación | cron 5 min, cierre 23:59, recolección SSH, README y runbook | **Parcial**: timers y runbook hechos; recolección SSH no |

---

## 7. Criterios de terminado v1 (§12 del plan)

| # | Criterio | Estado |
|---|---|---|
| 1 | `run --simulate` genera JSONL válido y CSV con el esquema v1 y ≥1 fila por módulo | **Cumple** (14 filas, 6 módulos, 27 columnas) |
| 2 | `export --fecha` dos veces da el mismo SHA-256 | **Cumple** (verificado en VM1) |
| 3 | Objetivo inexistente → `OFFLINE`/`ERROR`, sin traza | **Cumple** (`192.0.2.99` → `OFFLINE`) |
| 4 | Snapshot sin actualizar → `STALE` | **Implementado**, sin prueba dedicada en VM1 |
| 5 | Releer el mismo `auth.log` no duplica eventos | **Implementado** (huella estable), sin prueba en VM1 |
| 6 | Deltas de `iptables` suman lo esperado | **Unit test OK**, sin reglas `VLAN30-DROP` reales |
| 7 | `python -m unittest discover` pasa sin red | **Cumple** (18/18 en Linux) |
| 8 | Solo stdlib en `monitor/` | **Cumple** (28 módulos, todos estándar) |
| 9 | Una hora de muestreo deja 12 JSONL | **Pendiente de verificar** (el timer corre; conteo en curso) |
| 10 | README con configuración, programación, recolección SSH, columnas y límites | **Parcial**: README + runbook; falta documentar la recolección SSH real |

---

## 8. Prioridad y siguiente iteración

**P0 — desbloquea el resto (≈12 h)**
1. Crear VM2 y replicar el despliegue del portal (o mover PostgreSQL + fail2ban + iptables).
2. Instalar la recolección SSH: clave ed25519, usuario `monitor`, `monitor-readonly`,
   `sudoers`, `known_hosts`; probar `python3 -m monitor recolectar --host vm2`.
3. Habilitar `seguridad` apuntando a `data/entradas/vm2` con las reglas `VLAN30-DROP`.

**P1 — completa los módulos del caso (≈8 h)**
4. Cámaras VLAN 30 (ping + RTSP) con IPs reales en el TOML.
5. Asterisk: SIP OPTIONS, AMI (`manager.conf`) y CDR por SSH.

**P2 — medición (≈4 h)**
6. `iperf3` + `tcpdump` para QoS; `isc-dhcp-server` en VM2 para leases.

**P3 — calidad y entrega (≈10 h)**
7. Reintentos con backoff, señales, `timeout_total_s`, chequeo NTP.
8. `inventario.csv` como dimensión (o eliminar la duplicación del TOML).
9. `--json-logs`, compresión `.gz` en `prune`, `recolectar` en paralelo.
10. Un día completo de muestras + medidas y gráficos de Power BI.

---

## 9. Cómo cerrar cada pendiente (verificación)

| Pendiente | Cómo se comprueba que quedó cerrado |
|---|---|
| VM2 y recolección SSH | `python3 -m monitor recolectar --host vm2` sin errores y un `vm2/iptables.save` con contadores |
| Seguridad | dos muestras seguidas: la primera guarda línea base, la segunda reporta solo deltas reales |
| Cámaras | fila `Camaras` en `ONLINE` y `puerto = 554` en el JSONL |
| VoIP | `sip_code = 200/401/403` y `llamadas_activas` con valor (no nulo) |
| Reintentos | simular un timeout transitorio y ver `2 intentos` en el log, sin `ERROR` |
| Señales | `kill -TERM` durante una corrida: el JSONL se escribe y el proceso sale con 1 |
| NTP | `timedatectl show -p NTPSynchronized` = `yes` y aviso en el resumen si no |
| Un día completo | 288 JSONL en `data/raw/AAAA-MM-DD/` y un CSV con todas las filas |
| Power BI | dashboard con disponibilidad por VLAN/zona y latencia media por módulo |

> **Nota de alcance:** el proyecto solo mide activos del laboratorio y de la topología del
> curso; no se ejecuta contra redes de terceros.

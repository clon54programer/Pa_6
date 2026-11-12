# Monitor PortoCaribe

Monitor de disponibilidad, rendimiento, QoS y seguridad, con solo biblioteca estándar.
Implementa el plan [`plan_implementacion_monitor.md`](../plan_implementacion_monitor.md).

## Uso rápido

```bash
python3 -m monitor validate --config monitor.toml
python3 -m monitor run --config monitor.toml --simulate
python3 -m monitor export --config monitor.toml --fecha 2026-11-11
```

- `run` escribe un JSONL por corrida en `data/raw/YYYY-MM-DD/`.
- `export` reconstruye `data/csv/metricas_YYYY-MM-DD.csv` y deduplica por `huella`.
- `--solo camaras,portal` limita los módulos.
- `--dry-run` muestra el plan sin ejecutar sondas.
- `--json-logs` emite una línea JSON por registro (ideal para journald/ELK).
- `recolectar` trae snapshots por SSH en paralelo (máx. 8); `prune` aplica retención y
  comprime a `.gz` los JSONL antiguos.

En Windows hace falta `tzdata` (para `zoneinfo`); el bloqueo de corridas usa `msvcrt`
en lugar de `fcntl`. El resto del monitor está pensado para Linux.

## Módulos

| Módulo | Sonda |
|---|---|
| Cámaras | `ping` + TCP 554 (RTSP) |
| Portal | HTTP/HTTPS + snapshot de Apache |
| Base de datos | TCP 5432 + `psql -c "SELECT 1"` |
| VoIP | SIP OPTIONS + AMI (`CoreShowChannels`) + CDR |
| QoS | `iperf3 -J` (DSCP EF) y parser pcap para DSCP |
| Seguridad | iptables, fail2ban, auth, kernel, net/SNMP |
| DHCP | estado del servicio y leases |

En el laboratorio están activos todos menos **Cámaras** (no hay equipos en la VLAN 30).

## Robustez

- Reintentos con backoff 0,5 s / 1 s + jitter (`reintentos.py`), solo en fallos
  transitorios.
- `timeout_total_s` por corrida: lo que no termina se reporta como `ERROR` en el JSONL.
- `SIGTERM`/`SIGINT`: se escribe lo recolectado y se sale con código 1.
- Chequeo NTP con `timedatectl`; el resumen incluye `ntp=sincronizado|desincronizado`.
- `inventario.csv` es la dimensión de nombre/VLAN/zona; el TOML solo dice qué medir y el
  programa avisa si ambos se contradicen.

## Recolección SSH

Ver [`config/ssh/`](../config/ssh) y [`despliegue/comun/recoleccion-vm.sh`](../despliegue/comun/recoleccion-vm.sh):

- `monitor-readonly` va en `/usr/local/bin/` de la VM de servicio.
- `authorized_keys` restringe la clave por IP y por receta (`from=`, `restrict`,
  `command=`).
- `sudoers.monitor` permite solo los comandos de lectura.

## Programación

- [`programacion/cron.monitor`](../programacion/cron.monitor): cada 5 min y cierre 23:59.
- Timers en [`despliegue/vm1/systemd/`](../despliegue/vm1/systemd/): muestreo, cierre y
  captura DSCP.

## Pruebas

```bash
python3 -m unittest discover -s tests_monitor -v
```

34 pruebas: parsers, HTTP real, reintentos, señales, `.gz`, inventario y `--simulate`.

## Estructura

```
monitor/
├── cli.py            # subcomandos y --json-logs
├── config.py         # TOML + validación + inventario
├── runner.py         # orquestación, deadline, señales, simulación
├── sondas.py         # ping, TCP, HTTP, psql, SIP, AMI, CDR, iperf, pcap, NTP
├── seguridad.py      # parsers de iptables/fail2ban/auth/kernel
├── recoleccion.py    # SSH de solo lectura en paralelo
├── escritura.py      # JSONL, CSV, retención y gzip
├── reintentos.py     # backoff exponencial con jitter
├── inventario.py     # inventario.csv como dimensión
└── modelos.py        # fila canónica y huella
```

# Monitor PortoCaribe

Monitor de disponibilidad, rendimiento, QoS y seguridad, con solo biblioteca estándar.
Implementa el plan [`plan_implementacion_monitor.md`](../plan_implementacion_monitor.md).

## Uso rápido

```bash
python3 -m monitor validate --config monitor.toml
python3 -m monitor run --config monitor.toml --simulate
python3 -m monitor export --config monitor.toml --fecha 2026-11-06
```

- `run` escribe un JSONL por corrida en `data/raw/YYYY-MM-DD/`.
- `export` reconstruye `data/csv/metricas_YYYY-MM-DD.csv` y deduplica por `huella`.
- `--solo camaras,portal` limita los módulos.
- `--dry-run` muestra el plan sin ejecutar sondas.
- `recolectar` trae snapshots por SSH (requiere clave y VM1/VM2).
- `prune` aplica la retención.

En Windows hace falta `tzdata` (para `zoneinfo`); el bloqueo de corridas usa `msvcrt`
en lugar de `fcntl`. El resto del monitor está pensado para Linux.

## Módulos

| Módulo | Sonda |
|---|---|
| Cámaras | `ping` + TCP 554 (RTSP) |
| Portal | HTTP/HTTPS + snapshot de Apache |
| Base de datos | TCP 5432 + `psql -c "SELECT 1"` |
| VoIP | SIP OPTIONS + AMI (`CoreShowChannels`) + CDR |
| QoS | `iperf3 -J` y parser pcap para DSCP |
| Seguridad | iptables, fail2ban, auth, kernel, net/SNMP |
| DHCP | estado del servicio y leases |

Las sondas reales usan las IPs de `monitor.toml`. Para el laboratorio, la recolección
SSH está deshabilitada por defecto: actívala cuando la clave y los snapshots estén
listos. Sin infraestructura, `--simulate` genera una muestra completa y determinista.

## Recolección SSH

Ver [`config/ssh/`](../config/ssh):
- `monitor-readonly` va en `/usr/local/bin/` de VM1 y VM2.
- `authorized_keys.ejemplo` restringe la clave por IP y por receta.
- `sudoers.monitor` permite solo los comandos de lectura.

## Programación

- [`programacion/cron.monitor`](../programacion/cron.monitor): cada 5 min y cierre 23:59.
- [`programacion/portocaribe-muestreo.timer`](../programacion/portocaribe-muestreo.timer)
  y [`portocaribe-cierre.timer`](../programacion/portocaribe-cierre.timer).

## Pruebas

```bash
python3 -m unittest discover -s tests_monitor -v
```

## Estructura

```
monitor/
├── cli.py            # subcomandos
├── config.py         # TOML + validación
├── runner.py         # orquestación y simulación
├── sondas.py         # ping, TCP, HTTP, psql, SIP, AMI, CDR, iperf, pcap
├── seguridad.py      # parsers de iptables/fail2ban/auth/kernel
├── recoleccion.py    # SSH de solo lectura
├── escritura.py      # JSONL, CSV, retención
└── modelos.py        # fila canónica y huella
```

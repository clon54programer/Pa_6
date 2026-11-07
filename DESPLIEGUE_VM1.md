# Despliegue en VM1 — Monitor + Portal PortoCaribe

Guía del despliegue realizado el **2026-11-07** en la máquina del laboratorio
`vboxuser@192.168.137.54` (Debian 12 "bookworm", `debian3`, Python 3.11.2).

> **Alcance de esta entrega.** Todo lo que corre en VM1 está instalado, habilitado y
> verificado: el **portal de clientes** publicado por Apache con TLS y el **monitor** que
> lo muestrea cada 5 minutos. **VM2, las cámaras y VoIP quedan fuera** (no existen en esta
> máquina todavía), igual que PostgreSQL, DHCP, fail2ban y la recolección SSH.

---

## 1. Qué quedó funcionando

| Aplicación | Cómo se accede | Servicio |
|---|---|---|
| **Portal de clientes** | `https://192.168.137.54/` (también `https://portal.portocaribe.local/` desde la VM) | `portal.service` (Python en `127.0.0.1:8080`) + Apache `:443` |
| Redirección HTTP | `http://192.168.137.54/` → 301 a HTTPS | Apache `:80` |
| **Monitor** | sin interfaz; escribe el dataset | `portocaribe-muestreo.timer` cada 5 min |
| **Cierre diario del CSV** | — | `portocaribe-cierre.timer` a las 23:59 |

Credenciales demo del portal: **`cliente.demo` / `Porto2026*`**
(contenedores de ejemplo: `CSQU3054383`, `BL-2026-001`, `OD-2026-001`).

El certificado TLS es **autofirmado** (SAN: `portal.portocaribe.local`, `localhost`,
`127.0.0.1`, `192.168.137.54`). El navegador mostrará la advertencia habitual; para
quitarla hay que sustituir `/etc/apache2/ssl/portal.{crt,key}` por un certificado de una
CA de confianza.

---

## 2. Rutas en la máquina

| Elemento | Ruta | Propietario |
|---|---|---|
| Código del monitor | `/opt/portocaribe-monitor/monitor/` | `root:root` |
| Configuración del monitor | `/etc/monitor/monitor.toml` | `root:root` |
| Código del portal | `/opt/portal/portal/` | `root:root` |
| Configuración del portal | `/etc/portal/portal.toml` | `root:root` |
| Base de datos del portal (SQLite) | `/var/lib/portal/portal.db` | `portal:portal` |
| Dataset del monitor | `/var/lib/portocaribe-monitor/datos/` | `monitor:monitor` |
| · evidencia cruda | `datos/raw/AAAA-MM-DD/HHMMSS_<run_id>.jsonl` | |
| · CSV del día | `datos/csv/metricas_AAAA-MM-DD.csv` | |
| · snapshots locales | `datos/entradas/local/*.txt` | `root` (los escribe el collector) |
| Snapshots (collector) | `/usr/local/bin/portocaribe-snapshots-local` | `root:root` |
| Sitio Apache | `/etc/apache2/sites-available/portal-portocaribe.conf` | `root:root` |
| Certificado TLS | `/etc/apache2/ssl/portal.crt`, `portal.key` | `root:www-data` |
| Unidades systemd | `/etc/systemd/system/portal.service`, `portocaribe-*.service`, `portocaribe-*.timer` | `root:root` |

Usuarios de servicio (sin login): `monitor` (grupos `monitor`, `adm`) y
`portal` (grupo `portal`).

---

## 3. Cómo se generó el despliegue

Los artefactos viven en el repositorio, en [`despliegue/vm1/`](vm1/):

```
despliegue/vm1/
├── install.sh                     # instalador idempotente (root)
├── etc/
│   ├── monitor.toml               # configuración del monitor para VM1
│   ├── portal.toml                # configuración del portal para VM1
│   └── apache-portal.conf         # VirtualHost :80 (301) y :443 (proxy TLS)
├── systemd/
│   ├── portal.service
│   ├── portocaribe-monitor.service
│   ├── portocaribe-export.service
│   ├── portocaribe-muestreo.timer
│   └── portocaribe-cierre.timer
├── usr/local/bin/portocaribe-snapshots-local   # snapshots locales (root)
└── diagnostico/                   # scripts de verificación usados
```

Instalación o actualización (no destructiva: conserva JSONL, CSV y `portal.db`):

```bash
# desde el equipo de trabajo
tar czf pa6.tar.gz --exclude=__pycache__ monitor portal despliegue
scp pa6.tar.gz vboxuser@192.168.137.54:/tmp/
ssh vboxuser@192.168.137.54
mkdir -p /tmp/pa6 && tar xzf /tmp/pa6.tar.gz -C /tmp/pa6
su -            # root
bash /tmp/pa6/despliegue/vm1/install.sh /tmp/pa6
```

El instalador: instala `apache2`/`openssl`, crea los usuarios, copia el código y las
configuraciones, valida ambos TOML, genera el certificado, habilita módulos y sitio de
Apache, abre 80/443 en `ufw`, instala y habilita las unidades, y cierra con una muestra
real más el export del día.

---

## 4. Operación diaria

```bash
# muestra manual (con snapshots previos, igual que el timer)
sudo systemctl start portocaribe-monitor.service

# estado y programación
systemctl list-timers --all | grep portocaribe
systemctl status portal apache2 portocaribe-muestreo.timer

# reconstruir el CSV de un día
cd /opt/portocaribe-monitor
sudo -u monitor python3 -m monitor export --config /etc/monitor/monitor.toml --fecha 2026-11-07

# validar configuración / simular el dataset completo (sin infraestructura)
sudo -u monitor python3 -m monitor validate --config /etc/monitor/monitor.toml
sudo -u monitor python3 -m monitor run --simulate --config /etc/monitor/monitor.toml

# retención (180 días por defecto)
sudo -u monitor python3 -m monitor prune --config /etc/monitor/monitor.toml

# logs
journalctl -u portal -f
journalctl -u portocaribe-monitor.service --since today
```

> `sudo` **no está disponible** en esta máquina: para tareas de root usar `su -`
> (o `su - -c 'orden'`). El usuario `monitor` no tiene privilegios y solo lee los
> snapshots y escribe su propio directorio de datos.

El CSV diario se produce a las 23:59 con todas las muestras del día; `export` es
idempotente, así que puede relanzarse sin miedo. El CSV usa `utf-8-sig` (Excel/Power BI),
27 columnas del esquema v1 y las celdas no aplicables quedan vacías.

---

## 5. Qué mide hoy y qué falta

| Módulo | Estado en VM1 | Motivo |
|---|---|---|
| **PortalWeb** (HTTP/HTTPS + estado Apache) | **activo** | el portal vive en esta máquina |
| Seguridad (iptables, fail2ban, auth, kernel, net/snmp) | deshabilitado | sus reglas `VLAN30-DROP`/`VLAN40-DROP`, fail2ban y los snapshots son de VM2; con las reglas `ufw` locales el módulo etiquetaría tráfico `ACCEPT` como `VLAN40_BLOCKED` |
| Cámaras (ICMP + RTSP 554) | deshabilitado | VLAN 30 no desplegada |
| Base de datos (TCP 5432 + `psql`) | deshabilitado | PostgreSQL no existe en VM1; el portal usa SQLite |
| VoIP (SIP, AMI, CDR) | deshabilitado | Asterisk no existe en VM1 |
| DHCP (leases/estado) | deshabilitado | VM1 usa NetworkManager, no `isc-dhcp-server` |
| QoS (iperf3, pcap) | deshabilitado | genera tráfico y requiere VM2/equipo de medición |

Cada módulo se activa editando `/etc/monitor/monitor.toml` (el archivo ya trae las rutas
esperadas como comentario/plantilla) y reiniciando el timer. Las sondas que no encuentran
su fuente reportan `SKIPPED`/`STALE` en vez de fallar, así que se pueden habilitar de a una.

Con el alcance actual cada muestra deja **2 filas** (portal + Apache); 288 muestras/día
≈ 576 filas y un CSV de ~100 KB. El dataset completo de la topología (≈8 600 filas/día)
aparece cuando se incorporen VM2, las cámaras y Asterisk.

---

## 6. Verificación ejecutada (2026-11-07)

| Comprobación | Resultado |
|---|---|
| `portal.service` y `apache2` | `active` (arrancan solos en el boot) |
| `GET https://127.0.0.1/` | `200 text/html`, TLS 1.3, ~5 ms |
| `GET https://192.168.137.54/` | `200`, certificado correcto (SAN con la IP) |
| `http://…/` | `301` a HTTPS |
| Estáticos (`/css`, `/js`, `/assets`) | `200` con el `Content-Type` correcto |
| `POST /api/login` (`cliente.demo`) | `200` + cookie `sid` `Secure` |
| `/api/estado` autenticado | `200` `{"estado": "OK", …}` |
| `/api/track` por contenedor/BL/orden | `200` con el contenedor; `404` si no existe |
| Muestra real del monitor | `filas=2 ok=2 con_problema=0` |
| Timer de muestreo | disparó solo a las 13:00 y dejó su JSONL |
| `export` dos veces | mismo SHA-256 (idempotente) |
| Objetivo inexistente (`192.0.2.99`) | `OFFLINE` con detalle, sin traza y `rc=1` |
| `run --simulate` | 14 filas, 6 módulos, 27 columnas |
| Pruebas unitarias (`tests_monitor`) | **18/18 OK** en Linux |
| `ufw` | `80/tcp` y `443/tcp` permitidos (contadores con tráfico) |

Scripts reproducibles en [`despliegue/vm1/diagnostico/`](vm1/diagnostico/):
`diag.sh` (estado y último JSONL), `verify.sh` (criterios de aceptación),
`pruebas.sh` (tests), `e2e_portal.sh` y `final.sh` (portal por HTTPS y timers).

---

## 7. Corrección aplicada al código

Durante la puesta en marcha la sonda HTTP del monitor fallaba con
`AttributeError: 'function' object has no attribute 'client'`:
`monitor/sondas.py` importaba `http.client` y, más abajo, definía una función
`http(...)` que reemplazaba ese nombre en el módulo, de modo que
`http.client.HTTPSConnection` se resolvía contra la función.

Corrección en [`monitor/sondas.py`](../monitor/sondas.py): el módulo se importa como
`http_cliente` y la sonda usa `http_cliente.HTTPSConnection`, `http_cliente.HTTPConnection`
y `http_cliente.HTTPException`. No se cambió la interfaz pública (`sondas.http(...)`).
Las 18 pruebas unitarias siguen pasando; ninguna cubría esa ruta, por eso el fallo solo
apareció al ejecutar contra un portal real.

---

## 8. Pendientes y advertencias

- **IP dinámica.** `enp0s3` toma `192.168.137.54` por DHCP desde el equipo anfitrión. Si
  cambia, hay que regenerar el certificado (el SAN lleva la IP) o fijar la dirección.
- **`su -` obligatorio**: el usuario `vboxuser` no tiene `sudo`, y las tareas de root
  (instalar, reiniciar Apache, tocar `ufw`) se hacen con `su -` y la contraseña de root.
- **VM2 pendiente**: portal secundario, PostgreSQL, fail2ban, iptables con las reglas
  `VLAN30-DROP`/`VLAN40-DROP`, DHCP y la recolección SSH con clave + wrapper
  `monitor-readonly` + `sudoers` (secciones §8 del plan del monitor). Cuando exista, se
  activan los módulos correspondientes en `monitor.toml` y `recoleccion.habilitado = true`.
- **Cámaras y VoIP**: se habilitan cuando existan VLAN 30 y Asterisk; AMI necesita
  `ASTERISK_AMI_SECRET` en el entorno del servicio.
- **`--simulate`** escribe en el mismo `directorio_datos`; para demos conviene usar una
  copia del TOML con otro directorio (como en `diagnostico/verify.sh`).

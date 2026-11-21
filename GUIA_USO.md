# Guía de uso — PortoCaribe

Guía operativa del laboratorio de dos VM: acceso, servicios, monitor, portal, pruebas y
mantenimiento. Para el detalle paso a paso de cada comprobación está
[`GUIA_PRUEBAS.md`](GUIA_PRUEBAS.md); para el estado y los pendientes,
[`PENDIENTES.md`](PENDIENTES.md).

> **Red actual:** `192.168.137.0/24`.
>
> | VM | IP | Rol |
> |---|---|---|
> | **VM1** | `192.168.137.93` | monitor, Asterisk, captura QoS, portal de respaldo |
> | **VM2** | `192.168.137.8` | portal principal, PostgreSQL, fail2ban, iptables, DHCP, iperf3 |
>
> Si cambias de red, revisa la [sección 8](#8-cambiar-de-red-o-de-ip).

---

## 1. Acceso

Desde el PC, por SSH en el puerto 22:

```powershell
ssh -p 22 vboxuser@192.168.137.93    # VM1
ssh -p 22 vboxuser@192.168.137.8     # VM2
```

Dentro de la VM, las tareas de root se hacen con `su -` y la contraseña de laboratorio:

```bash
su -
```

> El usuario `vboxuser` no está en `sudoers`; por eso se usa `su -`. Si automatizas algo
> sin TTY, la guía de pruebas explica el truco con `script`.

Credenciales de demostración del portal: **`cliente.demo` / `Porto2026*`**.

---

## 2. Qué corre en cada VM

### VM1 — `192.168.137.93`

| Servicio | Para qué | Comprobación |
|---|---|---|
| `portocaribe-muestreo.timer` | lanza el monitor cada 5 min | `systemctl list-timers \| grep portocaribe` |
| `portocaribe-qos-captura.timer` | `tcpdump` de UDP/5201 | `systemctl status portocaribe-qos-captura.service` |
| `portocaribe-cierre.timer` | `export` del CSV a las 23:59 | `systemctl status portocaribe-cierre.timer` |
| `asterisk` | SIP 5060/udp y AMI 127.0.0.1:5038 | `asterisk -rx "core show version"` |
| `portal` + `apache2` | portal de respaldo en 443 | `https://192.168.137.93/` |

Datos del monitor:

```text
/var/lib/portocaribe-monitor/datos/
├── raw/AAAA-MM-DD/HHMMSS_<run_id>.jsonl   # crudo
├── csv/metricas_AAAA-MM-DD.csv            # export del día
├── entradas/vm2/                          # snapshots traídos por SSH
├── capturas/qos.pcap                      # captura DSCP
└── estado/                                # contadores y cursores
```

### VM2 — `192.168.137.8`

| Servicio | Para qué | Comprobación |
|---|---|---|
| `apache2` + `portal` | portal principal | `https://192.168.137.8/` |
| `postgresql` | base `portocaribe` | `psql ... SELECT 1` |
| `fail2ban` | jails `sshd` y `apache-auth` | `fail2ban-client status sshd` |
| `iptables` | reglas VLAN30/40 | `iptables -S INPUT \| grep VLAN` |
| `isc-dhcp-server` | DHCP aislado en `dummy0`/`veth-dhcp` | `systemctl is-active isc-dhcp-server` |
| `portocaribe-dhcp-veth` | crea el veth del cliente | `ip netns exec clientes ip -4 -br addr` |
| `iperf3` | servidor QoS en 5201 | `ss -lntp \| grep 5201` |

PostgreSQL escucha en `127.0.0.1` y `192.168.137.8:5432`; el `pg_hba` solo permite al
usuario `monitor` desde `192.168.137.93/32` y desde loopback.

---

## 3. Portal de clientes

### Entrar

1. Abre `https://192.168.137.8/` (principal) o `https://192.168.137.93/` (respaldo).
2. Acepta el aviso de certificado autofirmado.
3. Entra con `cliente.demo` / `Porto2026*`.

### Buscar

La barra de búsqueda acepta:

- número de contenedor ISO 6346, por ejemplo `CSQU3054383`;
- BL, por ejemplo `BL-2026-001`;
- orden de despacho, por ejemplo `OD-2026-001`.

El resultado muestra estado, importador, buque, arribo, muelle y el timeline.

### Servicio y base

```bash
su -
systemctl status portal
systemctl restart portal        # reinicia el backend (cierra sesiones)
systemctl reload apache2        # recarga TLS/proxy
```

- Configuración: `/etc/portal/portal.toml`.
- Base SQLite: `/var/lib/portal/portal.db`.
- Apache: `/etc/apache2/sites-available/portal-portocaribe.conf`.
- El backend escucha solo en `127.0.0.1:8080`; Apache termina TLS en 443.

### Si no aparecen avisos

Los avisos son datos de demostración con fecha `desde`/`hasta`; si el laboratorio se
queda varios días sin resembrar, vencen. Se pueden refrescar sin borrar nada:

```bash
su -
python3 - <<'PY'
import sqlite3
from datetime import date, timedelta
hoy = date.today()
con = sqlite3.connect('/var/lib/portal/portal.db')
for titulo, (desde, hasta) in {
    'Congestión en Muelle 2': (hoy - timedelta(days=1), hoy + timedelta(days=5)),
    'Ventana de despacho extendida': (hoy, hoy + timedelta(days=7)),
    'Mantenimiento de la red de muelles': (hoy - timedelta(days=1), hoy + timedelta(days=3)),
}.items():
    con.execute('UPDATE avisos SET desde=?, hasta=? WHERE titulo=?',
                (desde.isoformat(), hasta.isoformat(), titulo))
con.commit()
PY
```

---

## 4. Monitor de infraestructura

### Configuración

- `/etc/monitor/monitor.toml`: qué medir y a qué IPs.
- `/etc/monitor/inventario.csv`: nombres, VLAN, zona y criticidad.
- `/etc/monitor/ami.env`: secreto AMI (600, root; no está en el repo).
- `/etc/monitor/id_ed25519`, `known_hosts`, `pgpass`: recolección SSH y PostgreSQL.

### Comandos útiles

Siempre como `monitor` y desde `/opt/portocaribe-monitor`:

```bash
su -
cd /opt/portocaribe-monitor
set -a; . /etc/monitor/ami.env; set +a

# Validar configuración
runuser -u monitor -- python3 -m monitor validate --config /etc/monitor/monitor.toml

# Muestra simulada (no toca la red)
runuser -u monitor -- python3 -m monitor run --config /etc/monitor/monitor.toml --simulate

# Muestra real completa
runuser -u monitor -- env ASTERISK_AMI_SECRET="$ASTERISK_AMI_SECRET" \
  python3 -m monitor run --config /etc/monitor/monitor.toml

# Solo algunos módulos
runuser -u monitor -- env ASTERISK_AMI_SECRET="$ASTERISK_AMI_SECRET" \
  python3 -m monitor run --config /etc/monitor/monitor.toml --solo portal,base_datos

# Traer snapshots de VM2
runuser -u monitor -- python3 -m monitor recolectar --config /etc/monitor/monitor.toml --host vm2

# Reconstruir el CSV del día
runuser -u monitor -- python3 -m monitor export --config /etc/monitor/monitor.toml

# Exportar otro día
runuser -u monitor -- python3 -m monitor export --config /etc/monitor/monitor.toml --fecha 2026-11-20

# Retención: comprime >7 días y borra >180
runuser -u monitor -- python3 -m monitor prune --config /etc/monitor/monitor.toml
```

Módulos: `camaras`, `portal`, `base_datos`, `voip`, `qos`, `seguridad`, `dhcp`.
En este laboratorio `camaras` está deshabilitado (no hay VLAN 30).

### Interpretar la salida

```text
run_id=... filas=28 ok=28 con_problema=0 ntp=sincronizado
```

- `ok` incluye `ONLINE`, `OK` y `DROPPED`; un `DROPPED` de seguridad **no** es un fallo.
- `con_problema > 0` suele ser `ERROR`, `STALE` o `SKIPPED`.
- Un `SKIPPED` típico es VoIP «sin llamadas hoy»: haz una llamada de prueba y vuelve a
  ejecutar.
- Salida `1` si hay problemas o si se interrumpe por señal.

### Timers y logs

```bash
systemctl list-timers --all | grep portocaribe
systemctl status portocaribe-monitor.service
journalctl -u portocaribe-monitor.service -n 80 --no-pager
journalctl -u portocaribe-qos-captura.service -n 40 --no-pager
```

- `portocaribe-muestreo.timer`: cada 5 minutos.
- `portocaribe-qos-captura.timer`: cada 5 minutos, captura 40 s o 4000 paquetes.
- `portocaribe-cierre.timer`: 23:59, ejecuta `export`.

### Leer la última corrida

```bash
f=$(ls -t /var/lib/portocaribe-monitor/datos/raw/*/*.jsonl | head -1)
python3 - "$f" <<'PY'
import json, sys, collections
filas = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
print("archivo:", sys.argv[1])
print("filas:", len(filas), collections.Counter(f["estado"] for f in filas))
for f in filas:
    print(f"{f['modulo']:10} {f['estado']:9} {str(f['detalle'])[:100]}")
PY
```

---

## 5. Asterisk y VoIP

```bash
su -
systemctl status asterisk
asterisk -rx "core show version"
ss -lunp | grep ':5060'
ss -lntp | grep ':5038'
```

- SIP: `0.0.0.0:5060/udp`.
- AMI: `127.0.0.1:5038/tcp`, usuario `monitor`.
- Secreto AMI: `/etc/monitor/ami.env`.
- CDR: `/var/log/asterisk/cdr-csv/Master.csv` (sin cabecera, hora local).

Llamada de prueba:

```bash
asterisk -rx "channel originate Local/1000@demo application Wait 2"
sleep 4
tail -1 /var/log/asterisk/cdr-csv/Master.csv
```

Debe aparecer `ANSWERED`. Luego:

```bash
cd /opt/portocaribe-monitor
set -a; . /etc/monitor/ami.env; set +a
runuser -u monitor -- env ASTERISK_AMI_SECRET="$ASTERISK_AMI_SECRET" \
  python3 -m monitor run --config /etc/monitor/monitor.toml --solo voip
```

Esperado: 4 filas (SIP, AMI y las dos patas del CDR) y `con_problema=0`.

### Llamada real desde el PC con MicroSIP

MicroSIP es la opción más rápida en Windows: es portable, no requiere instalador y usa
UDP 5060 por defecto. Descarga el ZIP desde <https://www.microsip.org/downloads> y
descomprímelo, por ejemplo, en `%LOCALAPPDATA%\MicroSIP` o en una carpeta de trabajo.

La cuenta SIP de demostración es **`1001`**. La contraseña se lee en VM1:

```bash
ssh -t vboxuser@192.168.137.93 "su -c 'cat /etc/portocaribe-lab/sip_demo.secret'"
```

En MicroSIP, abre el menú (flecha a la derecha de las pestañas o clic derecho en la
franja inferior) y elige **Add account...**:

| Campo | Valor |
|---|---|
| Account name | `1001` |
| SIP server | `192.168.137.93` |
| SIP proxy | vacío |
| Username | `1001` |
| Domain | `192.168.137.93` |
| Auth ID | `1001` (o vacío) |
| Password | la que devolvió el comando anterior |
| Transport | `UDP` |
| Port | `5060` (si el campo no aparece, déjalo así: MicroSIP usa 5060) |
| STUN / ICE | desactivados |
| Register | activado |

En VM1 hay que permitir SIP y RTP en `ufw` (el monitor usa loopback y no lo necesita,
pero el softphone viene desde la LAN):

```bash
su -
ufw allow from 192.168.137.0/24 to any port 5060 proto udp comment 'SIP laboratorio'
ufw allow from 192.168.137.0/24 to any port 10000:20000 proto udp comment 'RTP laboratorio'
ufw reload
```

Guarda la cuenta y espera a que MicroSIP quede **Online** (si el estado dice
`Do Not Disturb`, pulsa el botón **DND** para desactivarlo; las llamadas salientes
funcionan igual, pero DND rechaza las entrantes).

Marca:

- **`1000`**: contesta, espera 2 s y cuelga.
- **`2000`**: contesta y reproduce `demo-congrats` (para probar audio).

Verifica el CDR y el monitor:

```bash
tail -2 /var/log/asterisk/cdr-csv/Master.csv
cd /opt/portocaribe-monitor
set -a; . /etc/monitor/ami.env; set +a
runuser -u monitor -- env ASTERISK_AMI_SECRET="$ASTERISK_AMI_SECRET" \
  python3 -m monitor run --config /etc/monitor/monitor.toml --solo voip
```

El CDR debe mostrar `1001 -> 1000` con `ANSWERED`; el monitor debe incluir la fila
`1001 -> 1000 (ANSWERED)` y terminar con `con_problema=0`.

### Segundo usuario SIP: `1002`

Para llamar desde **otro Windows**, usa la cuenta `1002`. Su contraseña está en VM1:

```bash
ssh -t vboxuser@192.168.137.93 "su -c 'cat /etc/portocaribe-lab/sip_demo2.secret'"
```

Configura MicroSIP en el otro PC exactamente igual que el `1001`, cambiando:

| Campo | Valor |
|---|---|
| Account name | `1002` |
| Username | `1002` |
| Auth ID | `1002` (o vacío) |
| Password | la de `/etc/portocaribe-lab/sip_demo2.secret` |

El resto es igual: servidor/dominio `192.168.137.93`, UDP, puerto 5060 (por defecto),
STUN/ICE desactivados y registro activado.

Los usuarios `1001` y `1002` pueden llamarse entre sí y llamar a las extensiones de
demostración:

- `1000`: contesta y cuelga a los 2 s.
- `2000`: reproduce `demo-congrats`.
- `1001` / `1002`: llamada entre los dos softphones.

No hace falta abrir más puertos: `ufw` ya permite SIP y RTP desde `192.168.137.0/24`.
Si ejecutas los dos MicroSIP en el **mismo PC**, cambia el puerto local del segundo a
`5061` (o usa otro equipo); en PCs distintos ambos pueden usar 5060 sin problema.

> **Si MicroSIP dice `Request Timeout`:** revisa `ufw status` en VM1 y que el puerto
> 5060/udp esté permitido. Si dice `404 Not Found`, el AOR de Asterisk no coincide:
> debe ser `1001@192.168.137.93` (ver [`despliegue/vm1/asterisk/pjsip.conf`](despliegue/vm1/asterisk/pjsip.conf)).
> Si dice `401`, la contraseña SIP es incorrecta.

---

## 6. PostgreSQL, QoS, DHCP y seguridad

### PostgreSQL

Desde VM1, como `monitor`:

```bash
su -
cd /tmp
runuser -u monitor -- env PGPASSFILE=/etc/monitor/pgpass \
  psql -w -tAc "SELECT 1" -h 192.168.137.8 -p 5432 -U monitor -d portocaribe
```

Esperado: `1`.

Si cambias la IP de VM1 o VM2, ajusta `pg_hba.conf` y `listen_addresses` en VM2 y
reinicia PostgreSQL (ver sección 8).

### QoS / iperf3

En VM2 el servidor debe escuchar:

```bash
ss -lntp | grep ':5201'
```

Prueba desde VM1 (20 Mbps UDP, DSCP EF, 5 s):

```bash
iperf3 -c 192.168.137.8 -u -b 20M -t 5 -S 0xB8
```

El monitor ejecuta su propia prueba de 10 s y lee `qos.pcap`; la captura debe tener
~3998/4000 paquetes con DSCP 46.

### DHCP

En VM2:

```bash
systemctl is-active isc-dhcp-server portocaribe-dhcp-lease.timer
systemctl start portocaribe-dhcp-lease.service
awk '/^lease /{ip=$2} /binding state active/{print ip}' /var/lib/dhcp/dhcpd.leases | sort -u
ip netns exec clientes ip -4 -br addr show veth-cli
```

Esperado: 1 IP (`10.30.60.100`) y `veth-cli` con esa dirección. El DHCP escucha solo en
`dummy0` y `veth-dhcp`, nunca en `192.168.137.0/24`.

### fail2ban

Prueba controlada con una IP TEST-NET (no existe en el aula):

```bash
fail2ban-client set sshd banip 203.0.113.99
fail2ban-client status sshd
iptables -S | grep 203.0.113.99
fail2ban-client set sshd unbanip 203.0.113.99
fail2ban-client status sshd
```

Esperado: `Currently banned: 1` → regla `f2b-sshd` → `Currently banned: 0`.

### iptables VLAN30/40

```bash
iptables -S INPUT | grep -E 'VLAN(30|40)-DROP'
iptables-save -c | grep -E 'VLAN(30|40)-DROP'
```

Para que suban los contadores, desde VM1 como root:

```bash
bash /tmp/generar-trafico-vlan.sh
```

Luego, en VM1:

```bash
cd /opt/portocaribe-monitor
set -a; . /etc/monitor/ami.env; set +a
runuser -u monitor -- env ASTERISK_AMI_SECRET="$ASTERISK_AMI_SECRET" \
  python3 -m monitor recolectar --config /etc/monitor/monitor.toml --host vm2
runuser -u monitor -- env ASTERISK_AMI_SECRET="$ASTERISK_AMI_SECRET" \
  python3 -m monitor run --config /etc/monitor/monitor.toml --solo seguridad
```

Deben salir filas `Seguridad DROPPED` con `VLAN30_BLOCKED`/`VLAN40_BLOCKED`,
`paquetes_delta` y `bytes_delta`.

---

## 7. Pruebas

### Suites unitarias

En las VM Debian (entorno real). Copia el árbol de pruebas y ejecuta:

Desde el PC (PowerShell):

```powershell
tar czf pa6-tests.tgz monitor tests_monitor portal tests monitor.toml portal.dev.toml inventario.csv pyproject.toml
scp pa6-tests.tgz vboxuser@192.168.137.93:/tmp/

# scripts de diagnóstico para VM1
scp despliegue/diagnostico/prueba-asterisk.sh despliegue/diagnostico/corrida-completa.sh despliegue/diagnostico/export-idempotente.sh despliegue/diagnostico/senales2.sh despliegue/diagnostico/probar-dhcp.sh despliegue/diagnostico/generar-trafico-vlan.sh vboxuser@192.168.137.93:/tmp/

# para VM2
scp despliegue/diagnostico/prueba-vm2.sh vboxuser@192.168.137.8:/tmp/
```

Luego, dentro de la VM:

```bash
mkdir -p /tmp/pa6-tests && tar xzf /tmp/pa6-tests.tgz -C /tmp/pa6-tests
cd /tmp/pa6-tests
python3 -m unittest discover -s tests_monitor -v   # 34 pruebas
python3 -m unittest discover -s tests -v           # 35 pruebas
```

Esperado: `OK` en ambas. En Windows hace falta `tzdata` (`python -m pip install tzdata`).

### Scripts de diagnóstico

Cópialos a `/tmp` (bloque anterior) y ejecútalos como root:

Dentro de cada VM:

```bash
su -
bash /tmp/prueba-asterisk.sh       # VM1
bash /tmp/prueba-vm2.sh            # VM2
bash /tmp/corrida-completa.sh      # VM1
bash /tmp/export-idempotente.sh    # VM1
bash /tmp/senales2.sh              # VM1
bash /tmp/probar-dhcp.sh           # VM1
bash /tmp/generar-trafico-vlan.sh  # VM1, tráfico de prueba VLAN
```

Desde el PC:

```powershell
python .\despliegue\diagnostico\portal-login.py 192.168.137.8
python .\despliegue\diagnostico\portal-login.py 192.168.137.93
```

### Resultados de referencia (2026-11-21)

| Prueba | Resultado |
|---|---|
| `prueba-asterisk.sh` | SIP 401, AMI Success, llamada ANSWERED |
| `prueba-vm2.sh` | 7 servicios activos, portal 200, `psql` 1, fail2ban 1→0, 4 reglas VLAN, 1 lease, iperf3 5201, wrapper OK |
| `corrida-completa.sh` | 28 filas, 28 OK, 0 problemas |
| `export-idempotente.sh` | mismo SHA-256, idempotente |
| `senales2.sh` | `rc=1` y JSONL escrito |
| `probar-dhcp.sh` | 1 lease activo |
| Suites | 34/34 monitor, 35/35 portal |
| Portal PC | login 200, cookie Secure, tracking por número/BL/orden, 3 avisos |

---

## 8. Cambiar de red o de IP

Si las VM cambian de IP, actualiza **cuatro** puntos: configuración del monitor,
`pg_hba`/`listen_addresses`, `authorized_keys` y `known_hosts`.

### VM1

```bash
su -
# Sustituye las IPs viejas por las nuevas en estos tres archivos:
sed -i 's/192\.168\.137\.8/NUEVA_IP_VM2/g; s/192\.168\.137\.93/NUEVA_IP_VM1/g' \
  /etc/monitor/monitor.toml /etc/monitor/inventario.csv /etc/monitor/pgpass

# Clave del host nuevo de VM2:
ssh-keyscan -t ed25519 NUEVA_IP_VM2 > /etc/monitor/known_hosts
chmod 644 /etc/monitor/known_hosts

# Comprueba:
runuser -u monitor -- ssh -i /etc/monitor/id_ed25519 \
  -o IdentitiesOnly=yes -o UserKnownHostsFile=/etc/monitor/known_hosts \
  -o StrictHostKeyChecking=yes monitor@NUEVA_IP_VM2 apache
cd /tmp && runuser -u monitor -- env PGPASSFILE=/etc/monitor/pgpass \
  psql -w -tAc "SELECT 1" -h NUEVA_IP_VM2 -U monitor -d portocaribe
```

### VM2

```bash
su -
# 1) Permitir a VM1 en pg_hba.conf
sed -i 's|^host portocaribe monitor .*|host portocaribe monitor NUEVA_IP_VM1/32 scram-sha-256|' \
  /etc/postgresql/15/main/pg_hba.conf

# 2) Escuchar en la IP nueva
su postgres -c "cd /tmp && psql -X -c \"ALTER SYSTEM SET listen_addresses = 'localhost,NUEVA_IP_VM2'\""

# 3) Autorizar la clave del monitor desde la IP nueva
sed -i 's|from="[^"]*"|from="NUEVA_IP_VM1"|' \
  /var/lib/portocaribe-monitor/.ssh/authorized_keys

systemctl restart postgresql
ss -lntp | grep ':5432'
```

También actualiza en el repo `monitor.toml`, `inventario.csv`, las plantillas de
`despliegue/` y los scripts de `despliegue/diagnostico/`. Los instaladores aceptan
variables: `IP_PUBLICA` (VM1), `IP_VM1`/`IP_VM2` (VM2).

### Certificado TLS

Si quieres que el navegador valide el nombre, regenera el certificado con la IP actual:

```bash
su -
openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
  -keyout /etc/apache2/ssl/portal.key -out /etc/apache2/ssl/portal.crt \
  -subj "/C=CO/ST=Bolivar/L=Cartagena/O=PortoCaribe S.A./CN=portal.portocaribe.local" \
  -addext "subjectAltName=DNS:portal.portocaribe.local,DNS:localhost,IP:127.0.0.1,IP:192.168.137.8" \
  -addext "basicConstraints=critical,CA:FALSE" \
  -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
  -addext "extendedKeyUsage=serverAuth"
chmod 0640 /etc/apache2/ssl/portal.key
chown root:www-data /etc/apache2/ssl/portal.key /etc/apache2/ssl/portal.crt
apache2ctl configtest && systemctl reload apache2
```

En VM1 cambia `IP:192.168.137.8` por `IP:192.168.137.93`. El certificado seguirá siendo
autofirmado; el navegador pedirá aceptarlo.

---

## 9. Problemas frecuentes

| Síntoma | Causa probable | Solución |
|---|---|---|
| El monitor da `ERROR … timed out` | IP vieja, servicio caído o firewall | Revisa `monitor.toml`, `systemctl status` y `ss -lntp` |
| `psql: no pg_hba.conf entry` | falta la línea para la IP de VM1 | Añade la línea y `systemctl restart postgresql` |
| `password authentication failed` | `pgpass` desactualizado | Copia la contraseña de `/etc/portocaribe-lab/pg_monitor.pass` a `/etc/monitor/pgpass` |
| La recolección SSH falla | clave, `known_hosts` o `from=` | Revisa `/etc/monitor/id_ed25519`, `ssh-keyscan` y `authorized_keys` |
| El portal da 502 | backend `portal` caído | `systemctl status portal`; `journalctl -u portal` |
| El login no persiste | estás en HTTP y la cookie es `Secure` | Usa `https://` |
| No hay lease DHCP | veth o timer detenido | `systemctl start portocaribe-dhcp-veth portocaribe-dhcp-lease.service` |
| QoS sin captura | timer detenido o iperf3 caído | `systemctl start portocaribe-qos-captura.service`; `ss -lntp \| grep 5201` |
| `run` devuelve 1 pero todo está `OK` | hay un `SKIPPED` (VoIP sin llamadas) | Haz una llamada y repite `--solo voip` |
| Muchas filas `FAIL2BAN_BAN` antiguas | el log conserva baneos históricos | Es ruido; el CSV deduplica. Rota `/var/log/fail2ban.log` si quieres limpiarlo |
| Aviso de certificado | autofirmado y/o SAN viejo | Acepta el aviso o regenera el SAN (sección 8) |

---

## 10. Checklist rápido

En VM1:

```bash
su -
systemctl is-active apache2 portal asterisk
systemctl list-timers --all | grep portocaribe
cd /opt/portocaribe-monitor
set -a; . /etc/monitor/ami.env; set +a
runuser -u monitor -- python3 -m monitor validate --config /etc/monitor/monitor.toml
runuser -u monitor -- env ASTERISK_AMI_SECRET="$ASTERISK_AMI_SECRET" \
  python3 -m monitor run --config /etc/monitor/monitor.toml
```

En VM2:

```bash
su -
systemctl is-active postgresql fail2ban isc-dhcp-server apache2 portal iperf3
fail2ban-client status sshd
ss -lntp | grep -E ':(443|5201|5432) '
```

En el PC:

```powershell
python .\despliegue\diagnostico\portal-login.py 192.168.137.8
```

Si todo está en `active` y la corrida termina con `con_problema=0`, el laboratorio está
operativo.

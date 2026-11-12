# Guía de pruebas — Asterisk (VM1) y servicios de VM2

Guía práctica para comprobar, de punta a punta, lo desplegado en el segundo sprint:

| Máquina | IP | Qué se prueba |
|---|---|---|
| **VM1** | `192.168.100.60` | Asterisk: SIP 5060, AMI 5038, CDR, llamadas y filas VoIP del monitor |
| **VM2** | `192.168.100.59` | portal TLS, PostgreSQL, fail2ban, iptables VLAN30/40, DHCP, iperf3 y recolección SSH |

Las salidas que aparecen en cada paso son las obtenidas en el laboratorio el
**2026-11-11**; los valores concretos (IPs, puertos, contadores, fechas) pueden variar.

---

## 0. Antes de empezar

### 0.1 Acceso

Desde el PC (PowerShell), con el usuario de laboratorio:

```powershell
ssh vboxuser@192.168.100.60     # VM1
ssh vboxuser@192.168.100.59     # VM2
```

Dentro de la VM, las tareas de root se hacen con `su -` y la contraseña del aula
(el usuario `vboxuser` no está en `sudoers`):

```bash
su -
```

> **Si un script necesita root pero no hay TTY** (por ejemplo desde una automatización),
> se usa el truco con `script`:
> `{ sleep 3; printf 'CLAVE\n'; } | script -qec "su -c 'orden'" /dev/null`.
> Para una persona basta con `su -` normal.

### 0.2 Llevar los scripts de prueba a las VM

Los scripts viven en [`despliegue/diagnostico/`](despliegue/diagnostico/). Se copian por
red (nada de carpetas compartidas de VirtualBox):

```powershell
# VM1: los que se usan en esta guía
$vm1 = "prueba-asterisk.sh","corrida-completa.sh","ver-jsonl.sh","export-idempotente.sh",
       "senales2.sh","probar-dhcp.sh","generar-trafico-vlan.sh"
foreach ($s in $vm1) { scp ".\despliegue\diagnostico\$s" vboxuser@192.168.100.60:/tmp/ }

# VM2
scp .\despliegue\diagnostico\prueba-vm2.sh vboxuser@192.168.100.59:/tmp/
```

Y se ejecutan como root:

```bash
su -
bash /tmp/prueba-asterisk.sh     # en VM1
bash /tmp/prueba-vm2.sh          # en VM2
```

### 0.3 Nota sobre `curl` en este PC

El `curl.exe` de Windows usa Schannel y en este equipo falla con
`SEC_E_NO_CREDENTIALS`. Para probar el portal desde el PC use **Python** (sección 2.2) o
el navegador; `Invoke-WebRequest` de PowerShell tampoco valida el certificado autofirmado.

---

## 1. Asterisk en VM1 (`192.168.100.60`)

El script completo es [`prueba-asterisk.sh`](despliegue/diagnostico/prueba-asterisk.sh);
abajo se explica cada paso para poder hacerlo a mano.

### 1.1 Servicio y versión

```bash
systemctl is-active asterisk
asterisk -rx "core show version"
```

Esperado:

```
active
Asterisk 16.28.0~dfsg-0+deb11u4 built by nobody @ buildd.debian.org ...
```

### 1.2 Puertos

```bash
ss -lunp | grep ':5060'
ss -lntp | grep ':5038'
```

Esperado: `0.0.0.0:5060` en UDP (transporte SIP) y `127.0.0.1:5038` en TCP (AMI, solo
escucha local).

### 1.3 SIP OPTIONS (debe responder 401)

Asterisk no está abierto a registro anónimo: contesta `401 Unauthorized`, que es la señal
de que el servicio está vivo.

```bash
runuser -u monitor -- python3 - <<'PY'
import socket
mensaje = (
    "OPTIONS sip:127.0.0.1 SIP/2.0\r\n"
    "Via: SIP/2.0/UDP 127.0.0.1:5060;branch=z9hG4bK-prueba\r\n"
    "Max-Forwards: 70\r\n"
    "From: <sip:monitor@vm1>;tag=prueba\r\n"
    "To: <sip:127.0.0.1>\r\n"
    "Call-ID: prueba@vm1\r\n"
    "CSeq: 1 OPTIONS\r\n"
    "Contact: <sip:monitor@127.0.0.1>\r\n"
    "Content-Length: 0\r\n\r\n"
).encode()
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(3)
s.sendto(mensaje, ("127.0.0.1", 5060))
print(s.recvfrom(4096)[0].split(b"\r\n")[0].decode())
PY
```

Esperado: `SIP/2.0 401 Unauthorized` (también vale `200`).

### 1.4 AMI: login y canales activos

El secreto está en `/etc/monitor/ami.env` y el usuario `monitor` solo puede leer eventos y
ejecutar `CoreShowChannels` desde `127.0.0.1`.

```bash
set -a; . /etc/monitor/ami.env; set +a
runuser -u monitor -- env ASTERISK_AMI_SECRET="$ASTERISK_AMI_SECRET" python3 - <<'PY'
import os, socket, time
s = socket.create_connection(("127.0.0.1", 5038), timeout=5)
s.settimeout(5)
s.recv(1024)
s.sendall(
    f"Action: Login\r\nUsername: monitor\r\nSecret: {os.environ['ASTERISK_AMI_SECRET']}\r\n"
    "Events: off\r\n\r\n".encode()
)
time.sleep(0.4)
print(s.recv(4096).decode("utf-8", "replace").split("\r\n")[0])
s.sendall(b"Action: CoreShowChannels\r\n\r\n")
time.sleep(0.6)
datos = b""
try:
    while b"CoreShowChannelsComplete" not in datos:
        bloque = s.recv(65536)
        if not bloque:
            break
        datos += bloque
except socket.timeout:
    pass
print("canales:", datos.count(b"Event: CoreShowChannel\r\n"))
print("completo:", b"CoreShowChannelsComplete" in datos)
s.close()
PY
```

Esperado:

```
Response: Success
canales: 0
completo: True
```

> Si responde `Response: Error / Message: Permission denied`, falta
> `write = system` en `/etc/asterisk/manager.conf` (es lo que exige
> `CoreShowChannels`).

### 1.5 Llamada de prueba y CDR

```bash
asterisk -rx "channel originate Local/1000@demo application Wait 2"
sleep 4
tail -1 /var/log/asterisk/cdr-csv/Master.csv
```

Esperado: una línea con `"1000","demo"`, `Wait`, `2`, `2`, `"ANSWERED"` y fecha/hora
**local** (America/Bogota). Ejemplo real:

```
"","","1000","demo",""""" <>","Local/1000@demo-00000001;2","","Wait","2","2026-11-11 19:08:03","2026-11-11 19:08:03","2026-11-11 19:08:05",2,2,"ANSWERED","DOCUMENTATION","1794442083.5",""
```

El archivo **no tiene cabecera**; por eso el monitor lo lee por posición.

### 1.6 Filas VoIP del monitor

```bash
set -a; . /etc/monitor/ami.env; set +a
cd /opt/portocaribe-monitor
runuser -u monitor -- env ASTERISK_AMI_SECRET="$ASTERISK_AMI_SECRET" \
  python3 -m monitor run --config /etc/monitor/monitor.toml --solo voip
```

Esperado:

```
VoIP/127.0.0.1 OK=12 en 9 ms
run_id=... filas=12 ok=12 con_problema=0 ntp=sincronizado
```

Las 12 filas son: 1 de SIP, 1 de AMI (canales) y 10 de CDR (una por `uniqueid`; cada
llamada Local genera dos patas).

Para ver el detalle:

```bash
archivo="$(ls -t /var/lib/portocaribe-monitor/datos/raw/*/*.jsonl | head -1)"
python3 - "$archivo" <<'PY'
import json, sys
for linea in open(sys.argv[1], encoding="utf-8"):
    f = json.loads(linea)
    print(f"{f['modulo']:8} {f['estado']:6} sip={f['sip_code']} dur={f['duracion_llamada_s']} {f['detalle'][:60]}")
PY
```

### 1.7 Problemas frecuentes de Asterisk

| Síntoma | Causa probable | Solución |
|---|---|---|
| `SIP/2.0 408` | Asterisk no escucha o el módulo pjsip no cargó | `ss -lunp \| grep 5060`; `asterisk -rx "module show like pjsip"` |
| AMI `Permission denied` | falta `write = system` | editar `manager.conf` y `asterisk -rx "manager reload"` |
| AMI no conecta | `permit` no incluye la IP o AMI escucha en otra interfaz | `grep -A5 '\[monitor\]' /etc/asterisk/manager.conf` |
| CDR sin filas nuevas | `cdr_csv` no cargó o `usegmtime` | `asterisk -rx "module show like cdr_csv"`; `grep '^usegmtime' /etc/asterisk/cdr.conf` |
| CDR con hora UTC | `usegmtime=yes` en `[csv]` | `sed -i 's/^usegmtime=yes/usegmtime=no/' /etc/asterisk/cdr.conf` y reiniciar |
| El monitor dice «sin llamadas hoy» | la llamada es de otro día o de otra zona | comparar `date` con la columna `start` del CDR |

---

## 2. Servicios de VM2 (`192.168.100.59`)

El script completo es [`prueba-vm2.sh`](despliegue/diagnostico/prueba-vm2.sh). Cada bloque
se puede ejecutar por separado.

### 2.1 Servicios activos

```bash
systemctl is-active postgresql fail2ban isc-dhcp-server apache2 portal iperf3 portocaribe-dhcp-veth | paste -sd' ' -
```

Esperado: `active active active active active active active`.

### 2.2 Portal por HTTPS

**Desde el PC** (recomendado, prueba la red real):

```powershell
python .\despliegue\diagnostico\portal-login.py
```

Salida real:

```
GET /        -> 200 text/html
POST login   -> 200
cookie       -> sid=<valor> (Secure)
GET /api/estado -> 200 {"estado": "OK", "latencia_ms": 0.23, ...}
```

También sirve abrir `https://192.168.100.59/` en el navegador y entrar con
`cliente.demo` / `Porto2026*` (el aviso de certificado es esperado: es autofirmado).

**Desde VM2** (sin salir de la máquina):

```bash
python3 - <<'PY'
import http.client, ssl
c = http.client.HTTPSConnection("127.0.0.1", 443, timeout=10, context=ssl._create_unverified_context())
c.request("GET", "/"); r = c.getresponse()
print("GET / ->", r.status, r.getheader("Content-Type")); r.read(); c.close()
PY
```

### 2.3 PostgreSQL

```bash
su postgres -c "cd /tmp && psql -X -tAc \"SELECT datname FROM pg_database WHERE datname='portocaribe'\""
su postgres -c "cd /tmp && psql -X -d portocaribe -tAc 'SELECT 1'"
grep '^host portocaribe' /etc/postgresql/15/main/pg_hba.conf
```

Esperado: `portocaribe`, `1` y las dos líneas de `pg_hba` (una para
`192.168.100.60/32` y otra para `127.0.0.1/32`).

La prueba que hace el monitor es remota, desde VM1 y como usuario `monitor`:

```bash
# en VM1
runuser -u monitor -- env PGPASSFILE=/etc/monitor/pgpass \
  psql -w -tAc "SELECT 1" -h 192.168.100.59 -p 5432 -U monitor -d portocaribe
```

Esperado: `1`. La contraseña del rol está en `/etc/portocaribe-lab/pg_monitor.pass`
(VM2) y en `/etc/monitor/pgpass` (VM1, 600 `monitor`).

### 2.4 fail2ban: ban y desbaneo controlado

Se usa una IP **TEST-NET-3** (`203.0.113.99`), que no existe en el aula; **nunca** se
banea la IP del PC ni la de VM1.

```bash
fail2ban-client set sshd banip 203.0.113.99
fail2ban-client status sshd
iptables -S | grep 203.0.113.99
fail2ban-client set sshd unbanip 203.0.113.99
fail2ban-client status sshd
```

Esperado:

```
Currently banned: 1
Banned IP list: 203.0.113.99
-A f2b-sshd -s 203.0.113.99/32 -j REJECT --reject-with icmp-port-unreachable
Currently banned: 0
```

El monitor refleja ese ban como fila `Seguridad … FAIL2BAN_BAN` (la recolección trae
`fail2ban-client status sshd` y `fail2ban.log`).

### 2.5 iptables VLAN30 / VLAN40

```bash
iptables -S INPUT | grep -E 'VLAN(30|40)-DROP'
iptables-save -c | grep -E 'VLAN(30|40)-DROP'
```

Esperado: cuatro reglas (LOG + DROP por cada VLAN) con el comentario y el prefijo de log.
Los contadores se ven como `[paquetes:bytes]` y **empiezan en 0** tras cada recarga de
reglas.

Para que suban, se inyecta tráfico sintético desde VM1 (origen falsificado
`10.30.30.12` y `10.30.40.77`):

```bash
# en VM1, como root
bash /tmp/generar-trafico-vlan.sh
```

Salida: `enviados 10 paquetes con origen VLAN30/VLAN40`.

De vuelta en VM2:

```bash
iptables-save -c | grep -E 'VLAN(30|40)-DROP'
```

Esperado: contadores > 0 en las reglas `DROP` (por ejemplo `[5:230]` y `[4:184]`).

Después, en VM1, una corrida del módulo de seguridad debe reportar los deltas:

```bash
cd /opt/portocaribe-monitor
set -a; . /etc/monitor/ami.env; set +a
runuser -u monitor -- env ASTERISK_AMI_SECRET="$ASTERISK_AMI_SECRET" \
  python3 -m monitor run --config /etc/monitor/monitor.toml --solo seguridad
bash /tmp/ver-jsonl.sh        # o el snippet de la sección 1.6
```

Esperado: filas `Seguridad DROPPED` con `VLAN30_BLOCKED`/`VLAN40_BLOCKED`,
`paquetes_delta` y `bytes_delta`, además de los eventos de kernel con el prefijo
`VLAN30-DROP:`.

> Es tráfico **de prueba**: no hay cámaras reales en la VLAN 30.

### 2.6 DHCP

```bash
systemctl is-active isc-dhcp-server portocaribe-dhcp-lease.timer
systemctl start portocaribe-dhcp-lease.service
awk '/^lease /{ip=$2} /binding state active/{print ip}' /var/lib/dhcp/dhcpd.leases | sort -u | wc -l
grep -A4 'lease 10.30.60' /var/lib/dhcp/dhcpd.leases | head -5
ip netns exec clientes ip -4 -br addr show veth-cli
```

Esperado:

```
active
active
1
lease 10.30.60.100 {
  starts 3 ...;
  ends 3 ...;
  ...
veth-cli@if5     UP             10.30.60.100/24
```

> `dhcpd.leases` guarda **un bloque por renovación**, así que
> `grep -c 'binding state active'` puede dar 6 aunque haya 1 solo IP. El monitor
> deduplica por IP (por eso reporta `1 leases activos`).

El servidor DHCP escucha solo en `dummy0` (10.30.50.5/24) y `veth-dhcp`
(10.30.60.1/24), **nunca** en `192.168.100.0/24`.

### 2.7 iperf3 (QoS)

En VM2 solo se comprueba que el servidor escucha:

```bash
ss -lntp | grep ':5201'
```

Prueba real desde VM1 (20 Mbps UDP, 10 s, DSCP EF):

```bash
iperf3 -c 192.168.100.59 -u -b 20M -t 5 -S 0xB8
```

Esperado: resumen con `sender`/`receiver`, pérdida cercana a 0 % y `Jitter`. El monitor
lo ejecuta solo en cada muestra y además lee `datos/capturas/qos.pcap`.

### 2.8 Recolección SSH

Desde VM1, como `monitor`:

```bash
cd /opt/portocaribe-monitor
runuser -u monitor -- python3 -m monitor recolectar --config /etc/monitor/monitor.toml --host vm2
ls -la /var/lib/portocaribe-monitor/datos/entradas/vm2/
```

Esperado: sin errores y 10 archivos (`apache.txt`, `iptables.save`, `fail2ban.txt`,
`fail2ban.log`, `auth.log`, `kern.log`, `netstat.txt`, `snmp.txt`, `dhcpd.leases`,
`dhcp_estado.txt`).

El wrapper solo acepta recetas cerradas; una receta inventada debe fallar:

```bash
# en VM2
SSH_ORIGINAL_COMMAND=inventada runuser -u monitor -- /usr/local/bin/monitor-readonly
echo "rc=$?"
```

Esperado: `receta no permitida` y `rc=2`. Una receta válida:

```bash
SSH_ORIGINAL_COMMAND=apache runuser -u monitor -- /usr/local/bin/monitor-readonly
```

Esperado: `active`.

### 2.9 Problemas frecuentes de VM2

| Síntoma | Causa probable | Solución |
|---|---|---|
| `psql` se queda colgado | el paginador espera en un TTY | `PAGER=cat PSQL_PAGER=cat` o `psql -P pager=off` |
| `psql: no pg_hba.conf entry` | falta la línea para `192.168.100.60/32` | revisar `pg_hba.conf` y `systemctl restart postgresql` |
| `password authentication failed` | `pgpass` desactualizado | copiar de nuevo `/etc/portocaribe-lab/pg_monitor.pass` a `/etc/monitor/pgpass` |
| fail2ban no arranca | backend `systemd` sin `python3-systemd` | `apt-get install -y python3-systemd` |
| Las reglas VLAN no aparecen | `netfilter-persistent reload` sin plugin | `iptables-restore < /etc/iptables/rules.v4` |
| Contadores VLAN en 0 | no ha pasado tráfico desde la última recarga | inyectar con `generar-trafico-vlan.sh` |
| DHCP no arranca | falta `dummy0`/veth o la subred | `systemctl start portocaribe-dhcp-veth` y revisar `dhcpd -t` |
| No hay lease | el cliente no pidió dirección | `systemctl start portocaribe-dhcp-lease.service` |
| La recolección SSH falla | clave, `known_hosts` o `from=` | `ls -l /etc/monitor/id_ed25519`; `ssh-keygen -lf /etc/monitor/known_hosts` |

---

## 3. Prueba integrada (todo junto)

En VM1, como root:

```bash
bash /tmp/corrida-completa.sh
```

Hace: captura DSCP, corrida completa del monitor, resumen y volcado de filas. Esperado
(2026-11-11):

```
run_id=... filas=39 ok=39 con_problema=0 ntp=sincronizado
BaseDatos  OK  192.168.100.59  SELECT 1 OK
DHCP       OK  isc-dhcp-server servicio active; 1 leases activos
PortalWeb  OK  192.168.100.59  HTTP 200 · TLS TLSv1.3; TTFB ...
QoS        OK  192.168.100.59  iperf3 UDP 20M
QoS        OK  captura        3998 paquetes de 4000 con DSCP 46
Seguridad  DROPPED  ... VLAN30_BLOCKED / VLAN40_BLOCKED / FAIL2BAN_BAN
VoIP       OK  127.0.0.1       SIP 401
VoIP       OK  Asterisk        ... (ANSWERED)
VoIP       OK  Asterisk AMI    0 canales activos
```

Cierre del CSV e idempotencia:

```bash
bash /tmp/export-idempotente.sh
```

Esperado: tres SHA-256 iguales y `IDEMPOTENTE: si`.

Otras pruebas de robustez:

```bash
bash /tmp/senales2.sh     # SIGTERM: JSONL escrito y salida 1
bash /tmp/probar-dhcp.sh  # fila DHCP con "1 leases activos"
```

---

## 4. Lista de verificación

| # | Prueba | Esperado | ✔ |
|---|---|---|---|
| 1 | `systemctl is-active asterisk` | `active` | |
| 2 | SIP OPTIONS a 5060 | `401` o `200` | |
| 3 | AMI login + `CoreShowChannels` | `Success`, `completo: True` | |
| 4 | Llamada `Local/1000@demo` | fila `ANSWERED` en `Master.csv` | |
| 5 | Monitor `--solo voip` | 12 filas, 0 problemas | |
| 6 | Portal `https://192.168.100.59/` | `200` + login `cliente.demo` | |
| 7 | `psql` remoto como `monitor` | `1` | |
| 8 | Ban/unban de `203.0.113.99` | 1 → regla `f2b-sshd` → 0 | |
| 9 | Reglas VLAN30/40 | 4 reglas con comentario | |
| 10 | Tráfico VLAN inyectado | contadores > 0 y filas `DROPPED` | |
| 11 | DHCP | 1 IP con lease activo, `veth-cli` con 10.30.60.100 | |
| 12 | iperf3 desde VM1 | ~20 Mbps, pérdida ~0 % | |
| 13 | `recolectar --host vm2` | 10 snapshots | |
| 14 | Receta inválida en el wrapper | `receta no permitida`, rc 2 | |
| 15 | Corrida completa | 37–39 filas, `con_problema=0` | |
| 16 | `export` dos veces | mismo SHA-256 | |

---

## 5. Limpieza

- Desbanear cualquier IP de prueba: `fail2ban-client set sshd unbanip 203.0.113.99`.
- El tráfico VLAN es efímero; no queda nada que borrar.
- El lease `10.30.60.100` es del cliente aislado en `clientes`; se renueva solo cada
  5 minutos y no afecta a la red del aula.
- No detenga `portocaribe-*` si quiere seguir acumulando el dataset del día.

> **Alcance:** todas las pruebas son sobre el laboratorio propio. No se envía tráfico a
> redes de terceros y el DHCP no se publica en la red real.

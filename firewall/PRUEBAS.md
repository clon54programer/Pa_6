# Plan de pruebas — ASA 5505 PortoCaribe

Tres niveles, de menos a más infraestructura. Con el nivel 2 se valida toda la política
sin necesidad de servidores; el nivel 3 valida el tráfico real.

---

## 0. Antes de empezar

Cableado mínimo:

| Puerto ASA | VLAN | Conectar a |
|---|---|---|
| Et0/0 | outside (Vlan2) | Segmento del "ISP" con servidor DHCP |
| Et0/1 – Et0/4 | inside (Vlan1) | Switch/host de servidores (10.30.50.0/24) |
| Et0/5 – Et0/7 | dmz (Vlan3) | Switch/host de cámaras (10.30.30.0/24) |

Consola: `COM3`, 9600 8N1. Si pide login: `admin` / `Porto2026*`; luego `enable` /
`Porto2026*`.

> `packet-tracer` exige que las interfaces de entrada y salida estén `up`. Basta con que
> el puerto tenga enlace (switch encendido o cable a otro equipo); no hace falta que haya
> hosts respondiendo.

---

## 1. Enlaces y VLANs

```bash
show interface ip brief
show switch vlan
```

Esperado:

```
Vlan1   10.30.50.1   up/up     (cuando Et0/1-0/4 tengan enlace)
Vlan2   <DHCP>       up/up     (cuando Et0/0 tenga enlace y lease)
Vlan3   10.30.30.1   up/up     (cuando Et0/5-0/7 tengan enlace)
```

y

```
VLAN 1  inside   Et0/1, Et0/2, Et0/3, Et0/4
VLAN 2  outside  Et0/0
VLAN 3  dmz      Et0/5, Et0/6, Et0/7
```

Si un puerto sigue `down`: revisa cable/switch. Si está en la VLAN equivocada:
`show switch vlan`.

---

## 2. Outside: DHCP, ruta por defecto y NAT

Cuando Et0/0 tenga enlace y el segmento tenga DHCP:

```bash
show interface Vlan2
show route
show nat
```

Esperado:

- `Vlan2` con una IP entregada por DHCP (distinta de la vieja `192.168.8.1`).
- Ruta por defecto: `S*  0.0.0.0 0.0.0.0 [1/0] via <gateway>, outside`.
- La regla NAT `(inside) to (outside) source dynamic NET-SERVIDORES interface`.

Si no hay ruta por defecto, el ASA no recibió DHCP o el servidor no entregó puerta de
enlace. Si el ISP es estático, hay que cambiar `ip address dhcp setroute` por IP fija y
`route outside 0.0.0.0 0.0.0.0 <gateway>`.

---

## 3. Política con `packet-tracer` (sin hosts)

Cada comando simula el paquete por el pipeline del ASA (ruta, NAT, niveles, inspección,
`no forward`) y devuelve `Action: allow` o `Action: drop` con el motivo.

| # | Comando | Esperado |
|---|---|---|
| 1 | `packet-tracer input inside icmp 10.30.50.10 8 0 10.30.30.12 detailed` | **allow** (inside → DMZ) |
| 2 | `packet-tracer input inside tcp 10.30.50.10 12345 10.30.30.12 554 detailed` | **allow** (RTSP) |
| 3 | `packet-tracer input inside icmp 10.30.50.10 8 0 8.8.8.8 detailed` | **allow** con NAT a la IP de outside |
| 4 | `packet-tracer input dmz icmp 10.30.30.12 8 0 10.30.50.10 detailed` | **drop** (nivel 50 → 100) |
| 5 | `packet-tracer input dmz icmp 10.30.30.12 8 0 8.8.8.8 detailed` | **drop** (`no forward interface Vlan2`) |
| 6 | `packet-tracer input outside icmp 203.0.113.10 8 0 10.30.50.5 detailed` | **drop** (nivel 0 → 100) |
| 7 | `packet-tracer input outside icmp 203.0.113.10 8 0 10.30.30.12 detailed` | **drop** (nivel 0 → 50 / no forward) |

Notas:

- El test 3 solo da `allow` si ya existe la ruta por defecto (DHCP). Sin ruta, el motivo
  será `no route`.
- El test 5 debe mostrar el motivo relacionado con `no-forward` (o `acl-drop`); lo
  importante es que sea `drop`.
- Si el test 1 da `drop`, revisa que Vlan1 y Vlan3 estén `up`, que los security-level
  sean 100 y 50, y que la inspección ICMP esté aplicada (`show run policy-map`).

---

## 4. Pruebas con hosts reales

### 4.1 Montaje

| Equipo | IP | Máscara | Gateway | Puerto ASA |
|---|---|---|---|---|
| "Monitor" (PC/VM) | 10.30.50.10 | 255.255.255.0 | 10.30.50.1 | Et0/1 |
| "Cámara" (PC/VM) | 10.30.30.12 | 255.255.255.0 | 10.30.30.1 | Et0/5 |

En Windows (con la interfaz conectada al ASA):

```powershell
netsh interface ip set address name="Ethernet" static 10.30.50.10 255.255.255.0 10.30.50.1
# En el equipo "cámara":
netsh interface ip set address name="Ethernet" static 10.30.30.12 255.255.255.0 10.30.30.1
```

Si usas la misma PC con dos adaptadores, no cambies la IP de gestión: agrega una IP
secundaria y una ruta, por ejemplo:

```powershell
netsh interface ip add address name="Ethernet 2" 10.30.50.10 255.255.255.0
route add 10.30.0.0 mask 255.255.0.0 10.30.50.1
```

Para simular la cámara, en el equipo 10.30.30.12 levanta un listener TCP en 554:

```powershell
python -m http.server 554 --bind 0.0.0.0
```

(o `nc -l -p 554`). Habilita ICMP y el puerto 554 en el firewall local del equipo de
prueba.

### 4.2 Pruebas desde "inside" (10.30.50.10)

```powershell
ping 10.30.30.12
Test-NetConnection 10.30.30.12 -Port 554
ping 8.8.8.8
```

Esperado: ping y TCP 554 a la cámara **OK**; ping a Internet **OK** (si outside tiene
DHCP y el ISP enruta). En el ASA:

```bash
show nat          # translate_hits debe subir
show conn         # sesiones abiertas
show arp
```

### 4.3 Pruebas desde "dmz" (10.30.30.12)

```powershell
ping 10.30.50.10                  # debe fallar
Test-NetConnection 10.30.50.10 -Port 443   # debe fallar
ping 8.8.8.8                      # debe fallar
```

Esperado: los tres **fallan**. Si el ping a inside funciona, revisa el security-level de
la DMZ y que no haya una ACL permisiva.

### 4.4 Prueba desde outside (opcional)

Desde un equipo en el segmento del ISP:

```powershell
ping 10.30.50.5      # debe fallar
ping 10.30.30.12     # debe fallar
```

El ASA no publica nada hacia inside/dmz; solo permite el retorno de conexiones iniciadas
desde inside.

---

## 5. Logs y contadores

```bash
show logging
show nat
show conn
show interface
```

- `show logging`: eventos de configuración, enlaces y denies (si se agrega ACL con `log`).
- `show nat`: `translate_hits`/`untranslate_hits`; deben incrementar con el ping a
  Internet desde inside.
- `show conn`: sesiones TCP/UDP/ICMP activas.
- `show interface`: errores, drops, velocidad/duplex.

---

## 6. Diagnóstico rápido

| Síntoma | Revisar |
|---|---|
| Vlan1/Vlan3 `down` | Cable/switch; `show switch vlan`; puerto en la VLAN correcta |
| Vlan2 sin IP DHCP | Servidor DHCP en el segmento; `show interface Vlan2`; probar IP fija |
| `packet-tracer` test 1 `drop` | `show run interface Vlan1/Vlan3`; security-level; `no forward` |
| Test 3 `drop` por `no route` | `show route`; DHCP sin puerta de enlace |
| NAT no traduce | `show nat`; outside up; objeto `NET-SERVIDORES` |
| Cámara alcanza inside | Security-level DMZ distinto de 50 o ACL permisiva |
| Ping a cámara falla pero TCP 554 funciona | `inspect icmp` no aplicado; `show run policy-map` |

---

## 7. Criterio de "funciona"

1. `show interface ip brief` con Vlan1/Vlan2/Vlan3 `up/up`.
2. `show route` con ruta por defecto por outside.
3. `packet-tracer` tests 1-3 `allow` y 4-7 `drop`.
4. Ping/TCP 554 de inside a la cámara OK.
5. Cámara no alcanza inside ni Internet.
6. Inside navega a Internet y `show nat` incrementa.
7. `write memory` guardado y `show running-config` coincide con
   [`asa5505-portocaribe.cfg`](asa5505-portocaribe.cfg).

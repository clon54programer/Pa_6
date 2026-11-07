# Firewall/router de la simulación — Cisco ASA 5505

Configuración aplicada el **2026-11-07** al ASA 5505 conectado por consola serial en
**COM3** (9600 8N1), para que actúe como router/firewall de la simulación PortoCaribe.

> **Estado:** configuración aplicada y guardada (`write memory`). Los enlaces de datos
> están **desconectados** (los 8 puertos Ethernet figuran `down`), así que las pruebas de
> ping/RTSP/NAT quedan pendientes de cablear. La configuración y el respaldo están
> verificados por consola.

---

## 1. Equipo y acceso

| Dato | Valor |
|---|---|
| Modelo | Cisco ASA 5505 |
| Firmware | 9.1(6), ASDM 7.5(2) |
| Serie | JMX2049G01P |
| Licencia | **Base**: 3 VLANs, 0 puertos trunk, 10 hosts |
| Consola | COM3, 9600 8N1, sin flow control |
| Modo actual | `ASA-PORTOCARIBE#` (privilegio 15) |
| Respaldo en flash | `disk0:/pre-portocaribe-20261107.cfg` |
| Respaldo local | [`backup/asa5505-running-config-2026-11-07.txt`](backup/asa5505-running-config-2026-11-07.txt) |

### Credenciales

| Acceso | Usuario | Contraseña |
|---|---|---|
| Enable (`enable`) | — | `Porto2026*` |
| SSH / consola (tras reconectar) | `admin` | `Porto2026*` |

> `aaa authentication ssh console LOCAL` también protege la consola: si se abre una
> sesión nueva (o el equipo se reinicia) pedirá `Username:` / `Password:` antes del
> prompt. La sesión de trabajo actual sigue abierta y no se ve afectada.

---

## 2. Topología implementada

```
                 ISP simulado (DHCP)
                        │
                  Et0/0 │ Vlan2  outside  security-level 0
                        │
                 ┌──────┴──────┐
                 │  ASA 5505   │
                 └──┬───────┬──┘
        Et0/1-0/4   │       │   Et0/5-0/7
        Vlan1 inside│       │Vlan3 dmz
        sec 100     │       │sec 50
     10.30.50.1/24  │       │10.30.30.1/24
                    │       │
        Portal/BD   │       │   Cámaras
        10.30.50.5  │       │   10.30.30.12
        Monitor     │       │   10.30.30.13
```

| Zona | VLAN | Puertos | Interfaz | Red | Gateway | Security-level |
|---|---|---|---|---|---|---|
| **inside** | 1 | Et0/1 – Et0/4 | Vlan1 | 10.30.50.0/24 | **10.30.50.1** | 100 |
| **outside** | 2 | Et0/0 | Vlan2 | DHCP (ISP) | DHCP `setroute` | 0 |
| **dmz** | 3 | Et0/5 – Et0/7 | Vlan3 | 10.30.30.0/24 | **10.30.30.1** | 50 |

Los puertos son *access*: cada uno pertenece a una sola VLAN (el ASA 5505 con licencia
Base no admite trunk 802.1Q). Para conectar varios equipos por zona hace falta un switch
externo en cada puerto/segmento.

### Hosts de la simulación

| Host | IP | Máscara | Gateway | Zona |
|---|---|---|---|---|
| Portal / PostgreSQL | 10.30.50.5 | /24 | 10.30.50.1 | inside |
| Monitor | 10.30.50.x | /24 | 10.30.50.1 | inside |
| Cam_Muelle_1 | 10.30.30.12 | /24 | 10.30.30.1 | dmz |
| Cam_Perimetro_1 | 10.30.30.13 | /24 | 10.30.30.1 | dmz |
| Asterisk (VoIP) | 10.30.60.10 | — | — | **no enrutado** (ver §6) |

> El monitor debe estar en la VLAN 50 (10.30.50.0/24) o tener una ruta hacia 10.30.0.0/16
> por 10.30.50.1. La VM1 actual (192.168.137.54) no está en esa red: para la simulación
> hay que reubicarla o agregar la ruta en el host.

---

## 3. Política aplicada

| Origen → destino | Resultado | Cómo |
|---|---|---|
| inside → outside | **Permitido** (PAT) | NAT dinámico `NET-SERVIDORES` a la IP de outside; security-level 100→0 |
| inside → dmz | **Permitido** | security-level 100→50; `inspect icmp` para el ping del monitor |
| dmz → inside | **Denegado** | security-level 50→100 (sin ACL que lo permita) |
| dmz → outside | **Denegado** | `no forward interface Vlan2` (restricción de licencia Base) |
| outside → inside | **Denegado** | security-level 0→100 |
| outside → dmz | **Denegado** | security-level 0→50 |

- **NAT:** solo `10.30.50.0/24` sale a Internet con PAT a la IP de outside.
- **Cámaras:** aisladas de Internet y de inside como origen; el monitor las alcanza porque
  la conexión la inicia inside (inspección stateful) y el `no forward` apunta a outside,
  no a inside.
- **ICMP:** se inspecciona para que los echo-reply de las cámaras vuelvan al monitor.
- **SSH:** permitido desde 10.30.50.0/24 por la interfaz inside; usuario `admin`.
- **Logging:** habilitado a buffer (16 KB, nivel informational) con timestamp.
- **DHCP server:** **no** se habilitó en el ASA. El plan del monitor asigna DHCP a VM2
  (`isc-dhcp-server`) y los hosts de la simulación usan IP estática. Si se quisiera que
  el ASA reparta direcciones, se puede agregar `dhcpd address ... inside` + `dhcpd enable
  inside` (licencia Base: 10 hosts), pero chocaría con el DHCP de VM2.

> La regla `no forward interface Vlan2` es el requisito de la licencia Base para poder
> nombrar la tercera VLAN. Al apuntarla a **outside** (en vez de inside) se conserva la
> gestión/monitoreo desde inside y se bloquea la salida de las cámaras a Internet.

---

## 4. Cómo se aplicó

1. Se identificó el equipo por COM3 a 9600 8N1 (`ciscoasa>`), se entró a privilegio 15
   (`enable`, sin contraseña inicial) y se desactivó el paginado (`terminal pager 0`).
2. Se respaldó la configuración original:
   - en flash: `copy running-config disk0:/pre-portocaribe-20261107.cfg`
   - en el repositorio: [`backup/asa5505-running-config-2026-11-07.txt`](backup/asa5505-running-config-2026-11-07.txt)
3. Se limpiaron los restos de la práctica anterior (`no route inside 192.168.0.0/16`,
   `no object network obj_any`, `no http server enable`, `no enable password`).
4. Se aplicó [`asa5505-portocaribe.cfg`](asa5505-portocaribe.cfg) línea por línea por la
   consola y se guardó con `write memory`.

La configuración final del equipo se puede revisar con `show running-config`; el archivo
`.cfg` es el mismo conjunto de comandos, listo para reaplicar en un ASA equivalente.

---

## 5. Verificación

Ejecutado por consola:

| Comprobación | Resultado |
|---|---|
| `show running-config` | hostname, interfaces, NAT, inspección, SSH y logging presentes |
| `show switch vlan` | VLAN 1 = Et0/1-0/4; VLAN 2 = Et0/0; VLAN 3 = Et0/5-0/7 |
| `show interface ip brief` | Vlan1 10.30.50.1; Vlan3 10.30.30.1; Vlan2 método DHCP; **todos los puertos `down`** |
| `show nat` | `(inside) to (outside) source dynamic NET-SERVIDORES interface` |
| `show crypto key mypubkey rsa` | llave RSA 2048 generada (`<Default-RSA-Key>`) |
| `write memory` | `[OK]`, 2793 bytes |

> Mientras outside no tenga enlace ni lease, `show interface Vlan2` puede seguir mostrando
> la IP vieja `192.168.8.1`; la `running-config` ya tiene `ip address dhcp setroute` y el
> cliente DHCP la reemplazará cuando el puerto Et0/0 levante.

**Pendiente de cablear** (por eso no se pudo ejecutar `packet-tracer`, que exige interfaz
`up`). El plan completo, con la matriz de pruebas y los valores esperados, está en
[`PRUEBAS.md`](PRUEBAS.md).

```bash
# Con los cables conectados:
show interface ip brief          # Vlan1/Vlan2/Vlan3 deben estar up/up
show route                       # debe aparecer la ruta por defecto vía DHCP
show nat                         # contadores de traducción
show logging                     # eventos

# Simulación de la política (no requiere hosts reales):
packet-tracer input inside icmp 10.30.50.10 8 0 10.30.30.12 detailed   # permitido
packet-tracer input dmz icmp 10.30.30.12 8 0 10.30.50.10 detailed      # denegado
```

Pruebas con hosts reales:

1. Cam_Muelle_1 (10.30.30.12/24, gw 10.30.30.1) responde `ping` y TCP 554 desde el
   monitor/portal (10.30.50.x).
2. La cámara **no** puede iniciar ping ni HTTP hacia 10.30.50.5 ni hacia Internet.
3. El portal (10.30.50.5, gw 10.30.50.1) navega a Internet con PAT (cuando outside tenga
   lease DHCP).
4. `packet-tracer` confirma allow/deny aunque todavía no haya servidores.

---

## 6. Limitaciones de la licencia Base (importante)

| Límite | Consecuencia |
|---|---|
| **3 VLANs** | Solo outside + inside + dmz. No caben VLAN 30, 40, 50 y 60 a la vez. |
| **0 puertos trunk** | Cada puerto es access a una VLAN; no se puede trunkear 802.1Q. |
| **Sin IP secundaria** | No se pueden tener 10.30.50.0/24 y 10.30.60.0/24 en la misma Vlan1 (el ASA rechaza `secondary`). |
| **DMZ restringida** | La tercera VLAN exige `no forward interface <vlan>`; se apuntó a outside. |
| **10 hosts inside** | Suficiente para el laboratorio, insuficiente para producción. |

### VLAN 60 (VoIP, 10.30.60.0/24) y VLAN 40

No quedan enrutadas por el ASA. Opciones, en orden de menor esfuerzo:

1. **Mover Asterisk a la VLAN 50** (p. ej. 10.30.50.10) y actualizar `inventario.csv` y
   `monitor.toml`. Es lo más simple y no requiere hardware nuevo.
2. **Poner un router/L3 switch** para la VLAN 60 y agregar en el ASA:
   `route inside 10.30.60.0 255.255.255.0 <IP_del_router>` (el router, a su vez, con
   gateway 10.30.50.1). Lo mismo aplicaría para la VLAN 40.
3. **Cambiar de equipo** por un firewall con 4+ interfaces (p. ej. pfSense/OPNsense en
   una VM o un ASA con más puertos), que es lo que el plan original de 4 VLANs requiere.

---

## 7. Rollback

El respaldo está en flash y en el repositorio. Para volver atrás:

```bash
configure terminal
clear configure all
```

y luego pegar el contenido de
[`backup/asa5505-running-config-2026-11-07.txt`](backup/asa5505-running-config-2026-11-07.txt)
(desde `hostname ciscoasa` hasta `call-home ...`, sin las líneas que empiezan por `:`),
terminando con `end` y `write memory`.

Alternativa desde flash:

```bash
copy disk0:/pre-portocaribe-20261107.cfg running-config
write memory
```

> Tras el rollback, el equipo vuelve a `enable` sin contraseña (configuración original) y
> a las redes 192.168.7.0/24 (inside), 192.168.8.0/24 (outside) y 192.168.30.0/24 (Vlan3).

---

## 8. Archivos

| Archivo | Contenido |
|---|---|
| [`asa5505-portocaribe.cfg`](asa5505-portocaribe.cfg) | Configuración aplicada, lista para reaplicar |
| [`backup/asa5505-running-config-2026-11-07.txt`](backup/asa5505-running-config-2026-11-07.txt) | Running-config original completo (respaldo/rollback) |
| [`PRUEBAS.md`](PRUEBAS.md) | Plan de pruebas: enlaces, `packet-tracer` y hosts reales |
| `README.md` | Este documento |

### Conexión de consola

```
PuTTY → Serial → COM3 → 9600, 8, None, 1, flow control None
```

Si aparece `Username:`, usar `admin` / `Porto2026*`. Para entrar a privilegio 15:
`enable` / `Porto2026*`.

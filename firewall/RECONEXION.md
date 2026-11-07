# Reconexión del ASA 5505

Procedimiento para cuando el firewall se apaga, se mueve o se desconecta de la consola
y/o de la red. La configuración vive en el `startup-config`, así que **no se pierde** al
desconectarlo; lo que hay que verificar al volver son los enlaces, el lease DHCP y la
hora.

---

## 1. Antes de desconectar (checklist)

Si todavía tienes la consola:

```bash
write memory
show startup-config | include hostname|nameif|no forward|logging buffered
```

Debe salir `[OK]` y las líneas de `ASA-PORTOCARIBE`, `nameif inside/outside/dmz`,
`no forward interface Vlan2` y `logging buffered informational`.

Respaldo disponible:

- flash: `disk0:/pre-portocaribe-20261107.cfg`
- repositorio: [`backup/asa5505-running-config-2026-11-07.txt`](backup/asa5505-running-config-2026-11-07.txt)

No ejecutes `write erase`, `clear configure all` ni el reset de fábrica.

---

## 2. Orden de reconexión

1. **Energía** (si estaba apagado): conectar y esperar el arranque completo (unos 2-3
   minutos; los puertos y la consola tardan en aparecer).
2. **Consola**: cable a **COM3**, 9600 8N1, sin flow control. Abrir PuTTY y pulsar Enter.
3. **Red**, en este orden:
   - `Et0/0` → segmento del ISP (outside, VLAN 2).
   - `Et0/1`–`Et0/4` → switch/host de servidores (inside, VLAN 1).
   - `Et0/5`–`Et0/7` → switch/host de cámaras (dmz, VLAN 3).
4. Esperar unos segundos a que suban los enlaces; outside pedirá DHCP.

> No conectes `Et0/1` y `Et0/5` al mismo switch no administrado: unirías la VLAN 1
> (inside) y la VLAN 3 (dmz) en L2 y romperías el aislamiento.

---

## 3. Acceso

| Caso | Qué hacer |
|---|---|
| La consola muestra `ASA-PORTOCARIBE#` | Ya estás en privilegio 15; no hace falta `enable`. |
| Pide `Username:` | `admin` / `Porto2026*` (por `aaa authentication ssh console LOCAL`). |
| Muestra `ASA-PORTOCARIBE>` | `enable` / `Porto2026*`. |
| No muestra nada | Pulsar Enter; revisar COM3/9600/cable; probar otro puerto USB-serial. |

---

## 4. Verificación mínima

```bash
show interface ip brief
show switch vlan
show route
show startup-config | include hostname|nameif|no forward
show nat
```

Esperado:

```
Vlan1   10.30.50.1   up/up
Vlan2   <IP DHCP>    up/up
Vlan3   10.30.30.1   up/up

VLAN 1  inside   Et0/1-0/4
VLAN 2  outside  Et0/0
VLAN 3  dmz      Et0/5-0/7

S*  0.0.0.0 0.0.0.0 [1/0] via <gateway DHCP>, outside
```

Si `Vlan2` sigue mostrando la vieja `192.168.8.1`, espera el lease DHCP o revisa que el
segmento del ISP tenga servidor DHCP; la `running-config` ya tiene `ip address dhcp
setroute`.

---

## 5. Verificación de la política

Con las interfaces `up`, repetir la matriz de [`PRUEBAS.md`](PRUEBAS.md):

```bash
packet-tracer input inside  icmp 10.30.50.10 8 0 10.30.30.12 detailed   # allow
packet-tracer input dmz     icmp 10.30.30.12 8 0 10.30.50.10 detailed   # drop
packet-tracer input dmz     icmp 10.30.30.12 8 0 8.8.8.8 detailed       # drop
packet-tracer input outside icmp 203.0.113.10 8 0 10.30.50.5 detailed   # drop
```

Si `packet-tracer` responde `interface-down`, todavía no hay enlace en la interfaz de
entrada o salida; no es un problema de la configuración.

---

## 6. Qué puede cambiar tras un apagado

| Elemento | Efecto |
|---|---|
| Configuración | **No cambia** (está en `startup-config`). |
| Lease DHCP de outside | Puede ser una IP nueva; la ruta por defecto se reinstala. |
| Hora | Sin NTP puede desajustarse; ajustar con `clock set hh:mm:ss dd Mon yyyy`. |
| Contadores NAT/conn | Vuelven a cero. |
| Sesiones SSH/consola | Se pierden; hay que autenticarse de nuevo. |
| Enlaces | Permanecen `down` hasta que se conecten los cables. |

---

## 7. Problemas comunes

| Síntoma | Causa probable | Acción |
|---|---|---|
| Consola sin salida | Puerto/baudios incorrectos o cable | COM3, 9600 8N1, flow none; probar Enter |
| Pide login y no entra | `aaa` local activo | `admin` / `Porto2026*` |
| `Vlan1`/`Vlan3` `down` | Sin cable o puerto en VLAN equivocada | `show switch vlan`; revisar cable/switch |
| `Vlan2` sin IP | Sin DHCP en el segmento | `show interface Vlan2`; habilitar DHCP o IP fija |
| No hay ruta por defecto | DHCP sin gateway | `show route`; revisar servidor DHCP |
| Configuración distinta | Se aplicó otro cambio o rollback | `show startup-config`; restaurar backup (§1) |
| `packet-tracer` `interface-down` | Falta enlace | Conectar cables; `show interface ip brief` |

---

## 8. Checklist rápido

```bash
enable
show interface ip brief
show switch vlan
show route
show nat
show startup-config | include hostname|nameif|no forward
```

Y si todo está bien:

```bash
write memory
```

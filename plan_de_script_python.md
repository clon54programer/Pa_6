
Para el escenario de **PortoCaribe Logística S.A.**, el documento especifica claramente cuáles son los servicios clave, los indicadores de línea base, las amenazas de seguridad y los alcances de la herramienta de monitoreo.

Para que los datos recolectados por el script en Python sean útiles y fáciles de exportar a Power BI (vía CSV, JSON o directamente conectando a la base de datos PostgreSQL), el script debe recolectar y estructurar las métricas agrupadas por **tres grandes pilares**:

---

### 1. Métricas de Disponibilidad y Rendimiento de Servicios

Basadas en el alcance de monitoreo y los servicios convergentes del documento:

* **Disponibilidad de Cámaras (VLAN 30):**


* **Datos a recolectar:** IP de la cámara, estado (Online/Offline mediante `ping`), latencia (ms), estado del puerto RTSP `554` (Abierto/Cerrado) y fecha/hora de la verificación.


* **Utilidad en Power BI:** Calcular el % de disponibilidad por cámara/zona (muelles o perímetro) y alertar sobre cámaras caídas.




* **Rendimiento del Portal Web de Clientes (VM1):**


* **Datos a recolectar:** Código HTTP de respuesta (200, 500, 504), tiempo de respuesta HTTP en segundos y estado del servicio Apache.


* **Utilidad en Power BI:** Verificar la hipótesis de degradación cuando superaba los 10 segundos de respuesta.




* **Estado de la Base de Datos PostgreSQL y Servicios Principales:**


* **Datos a recolectar:** Estado de la conexión a PostgreSQL, disponibilidad del servicio SIP de Asterisk (puerto 5060) y disponibilidad de DNS/DHCP.





---

### 2. Métricas de Calidad de Red (QoS) y Telefonía VoIP

Derivadas de las pruebas con `iperf` y `Wireshark` en los escenarios de carga:

* **Calidad del Enlace y Tráfico de Video/Voz:**


* **Datos a recolectar:** Porcentaje de pérdida de paquetes (`packet_loss_pct`), *jitter* (ms), ancho de banda consumido (Mbps) y etiquetas de QoS detectadas (DSCP EF para voz, AF41 para video).




* **Calidad de Llamadas de Muelle / Garita:**


* **Datos a recolectar:** Duración de llamadas, código de respuesta SIP de Asterisk y número de llamadas simultáneas activas.





---

### 3. Logs de Seguridad y Auditoría de Red

Provenientes de las simulación de amenazas y reglas de firewall (`iptables`/`fail2ban`):

* **Intentos de Acceso Bloqueados a la VLAN de Cámaras (VLAN 30):**


* **Datos a recolectar:** IP de origen, IP/Puerto de destino descartado por `iptables` y VLAN de origen.


* **Utilidad en Power BI:** Demostrar en gráficos el aislamiento efectivo de la VLAN de cámaras.




* **Eventos de Seguridad (fail2ban y SSH):**


* **Datos a recolectar:** Intentos fallidos de autenticación SSH, IPs baneadas por `fail2ban` y detección de eventos de inundación (SYN/ICMP).





---

### Estructura Recomendada del Conjunto de Datos (Dataset para Power BI)

Para simplificar el consumo en Power BI, el script de Python puede generar o almacenar una tabla con la siguiente estructura (por ejemplo en formato CSV o tabla de PostgreSQL):

| Campo | Tipo de Dato | Ejemplo / Descripción |
| --- | --- | --- |
| `timestamp` | DATETIME | `2026-11-06 08:30:00` |
| `modulo` | TEXT | `Camaras`, `PortalWeb`, `VoIP_Asterisk`, `Firewall_iptables`

 |
| `recurso_target` | TEXT | `10.30.30.12` (Cam_Muelle_1), `10.30.50.5` (Portal)

 |
| `estado` | TEXT / BIT | `ONLINE`, `OFFLINE`, `OK`, `DROPPED`

 |
| `tiempo_respuesta_ms` | FLOAT | `245.5` (Latencia o respuesta HTTP)

 |
| `perdida_paquetes_pct` | FLOAT | `0.05` (Pérdida en pruebas iperf)

 |
| `jitter_ms` | FLOAT | `1.2` (Jitter VoIP/Video)

 |
| `evento_seguridad` | TEXT | `SSH_FAIL`, `VLAN30_BLOCKED`, `FAIL2BAN_BAN`

 |

¿Te gustaría que redacte la plantilla base del script en Python que realiza estos chequeos (ping, puerto 554 RTSP, tiempo HTTP) y guarde los resultados en CSV/PostgreSQL?

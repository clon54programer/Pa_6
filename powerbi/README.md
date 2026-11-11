# Entregable de Power BI — dataset del monitor

El monitor produce un CSV diario en `/var/lib/portocaribe-monitor/datos/csv/metricas_AAAA-MM-DD.csv`
(`utf-8-sig`, 27 columnas, sin filas para celdas no aplicables). Este documento es la
capa que faltaba: cómo cargarlo, el modelo y las medidas DAX.

> El plan asignaba las medidas y gráficos a otra persona. Aquí quedan las medidas y la
> guía para que el tablero se monte en minutos; el `.pbix` se arma en Power BI Desktop
> sobre el CSV real (no se versiona un binario).

## 1. Carga

1. `Obtener datos → Texto/CSV` y elegir `metricas_AAAA-MM-DD.csv`.
2. Origen de archivo: **65001 UTF-8**.
3. En Power Query, promover encabezados y fijar tipos:

| Columna | Tipo |
|---|---|
| `timestamp`, `timestamp_utc` | Fecha/hora |
| `tiempo_respuesta_ms`, `perdida_paquetes_pct`, `jitter_ms`, `ancho_banda_mbps`, `duracion_llamada_s` | Número decimal |
| `vlan`, `http_status`, `puerto`, `sip_code`, `llamadas_activas`, `dscp`, `paquetes_delta`, `bytes_delta`, `schema_version` | Número entero |
| resto | Texto |

4. Renombrar la consulta como **Metricas**.

Para el histórico completo, repetir por día o usar una carpeta:

```
Origen = Folder.Files("C:\PortoCaribe\csv"),
Filtro = Table.SelectRows(Origen, each Text.StartsWith([Name], "metricas_")),
Datos  = Table.Combine(List.Transform(Filtro[Content], each Csv.Document(_, [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv])))
```

## 2. Modelo

| Tabla | Origen | Relación |
|---|---|---|
| **Metricas** | CSV | — |
| **Calendario** | `CALENDARAUTO()` o tabla de fechas | `Calendario[fecha]` 1→* `Metricas[fecha]` (`timestamp` truncado) |
| **Inventario** | `inventario.csv` | `Inventario[recurso]` 1→* `Metricas[recurso_target]` (inactiva) |

- `Inventario` es la **dimensión única** de nombre/VLAN/zona/criticidad: el monitor ya
  resuelve esos metadatos con ese archivo, así que el tablero no debe duplicarlos.
- La relación con `Inventario` se deja **inactiva** y se activa en las medidas que la
  necesiten (`USERELATIONSHIP`), porque `recurso_target` puede ser una IP, un nombre de
  servicio o "firewall".

## 3. Medidas

Todas están en [`medidas.dax`](medidas.dax). Las imprescindibles:

| Medida | Para qué |
|---|---|
| `Disponibilidad %` | % de filas `OK`/`ONLINE` sobre el total |
| `Latencia media ms`, `Latencia P95 ms` | rendimiento por módulo y por recurso |
| `Bloqueos VLAN30` / `VLAN40` | paquetes descartados por las reglas del firewall |
| `Baneos fail2ban` | eventos de seguridad reales |
| `Llamadas`, `Duracion media llamada s`, `Canales activos max` | VoIP |
| `Perdida media %`, `Jitter medio ms`, `Paquetes DSCP EF` | QoS |
| `Ultima muestra`, `Horas sin datos` | frescura del dataset |

> **Nota sobre `Leases activos`**: el detalle del DHCP viene como texto
> (`"servicio active; N leases activos"`). En Power Query, duplicar la columna y extraer
> el número con `Text.BetweenDelimiters([detalle], "; ", " leases")`; la medida debe usar
> esa columna numérica. La versión de `medidas.dax` es solo un marcador.

## 4. Páginas sugeridas (criterio 10 de §12)

1. **Resumen**: tarjetas de disponibilidad, muestras del día, latencia media y última
   muestra; gráfico de líneas de disponibilidad por hora.
2. **Disponibilidad por VLAN/zona**: barras con `Disponibilidad por VLAN %` y la
   dimensión `Inventario[vlan]`, `Inventario[zona]`.
3. **Rendimiento por módulo**: columnas de `Latencia media ms` y `Latencia P95 ms`, con
   `modulo` en el eje y una línea de referencia en el umbral de degradado (10 s).
4. **Seguridad**: barras de `Bloqueos VLAN30/40`, tabla de IPs de origen y línea de
   tiempo de `Baneos fail2ban`.
5. **VoIP y QoS**: llamadas por hora, duración media, pérdida/jitter y DSCP EF.
6. **Salud del dataset**: `Horas sin datos`, filas por día y estados distintos.

## 5. Actualización

- Programar la actualización del CSV contra la carpeta compartida o publicarlo en
  Power BI Service con una puerta de enlace.
- El CSV del día se reconstruye a las 23:59; hasta entonces el archivo puede estar
  incompleto. Para el tablero en vivo, usar los JSONL o lanzar `export` a demanda.
- Verificar el SHA-256 del CSV de un día tras dos `export`: debe coincidir.

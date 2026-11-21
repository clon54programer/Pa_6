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

## 6. Insertar el informe en el portal (`[tablero]`)

La URL del editor —
`https://app.powerbi.com/groups/me/reports/<informe>/<página>?experience=power-bi` — **no
se puede pegar en un `<iframe>`**: abre el informe dentro de Power BI Service, exige tu
sesión y el servicio no permite enmarcarlo desde otro sitio (esa URL responde con
`X-Frame-Options: deny`). Además `groups/me` es tu área de trabajo personal. Para el
portal hay que usar el **código de inserción** que Power BI genera en *Archivo → Insertar
informe*:

| | Publicar en la web | Insertar informe (embed seguro) | Embedded analytics (token) |
|---|---|---|---|
| Quién lo ve | cualquiera con el enlace | cuentas con permiso sobre el informe | usuarios del portal, autenticados por la aplicación |
| Cuenta de Power BI del visitante | no | sí | no |
| Licencia | Power BI + ajuste del tenant | Pro/PPU, o capacidad Premium/F64 | capacidad Fabric o Power BI Embedded (A/F) |
| HTTPS en el portal | no | **sí** | sí |
| Datos | públicos (caché de 1 h) | respeta permisos y RLS | respeta RLS con identidad propia |
| Cuándo usarlo | demostración con datos ficticios | portal interno con cuentas corporativas | producto real |

### Opción A — Publicar en la web (la más rápida para la demostración)

1. Abre el informe en Power BI Service → **Archivo → Insertar informe → Publicar en la
   web (público)**.
2. Elige tamaño 16:9 y la página inicial; copia el enlace (`https://app.powerbi.com/view?r=…`).
3. Pégalo en `[tablero]` de `portal.toml` con `habilitado = true`.

> **Advertencia:** cualquiera en Internet puede ver el informe y los datos del modelo.
> Úsalo solo con datos ficticios o públicos. Requiere que el administrador del tenant
> permita *Publicar en la web*; no admite RLS, DirectQuery ni modelos compartidos.

### Opción B — Insertar informe (embed seguro)

1. **Archivo → Insertar informe → Sitio web o portal**; copia el enlace
   `https://app.powerbi.com/reportEmbed?reportId=…&autoAuth=true` (puedes añadir
   `&pageName=` para abrir una página concreta).
2. Comparte el informe con quienes lo verán (**Compartir → Personas específicas**) o
   dales el rol *Viewer* si está en un área de trabajo.
3. Pégalo en `[tablero]`.

Requisitos: la página que lo contiene debe servirse por **HTTPS** (en local con
`http://127.0.0.1:8080` no se verá); cada visitante necesita cuenta con acceso y licencia
Pro/PPU salvo que el informe esté en capacidad Premium/F64; hay que permitir ventanas
emergentes para el inicio de sesión; no funciona con invitados B2B.

Con el informe de este proyecto (ID `d836d9b6-58c8-4ef0-967c-f5a3a6464ce2`), el enlace de
insertar sería:

```
https://app.powerbi.com/reportEmbed?reportId=d836d9b6-58c8-4ef0-967c-f5a3a6464ce2&autoAuth=true&pageName=efd8baf7154cb1b0b4ac
```

Como está en **Mi área de trabajo**, solo lo verá quien tenga acceso a ese informe. Si lo
vas a mostrar a otras personas, muévelo a un área de trabajo (por ejemplo «PortoCaribe
Operación») y compártelo desde allí.

### Opción C — Embedded analytics (token de inserción)

Para producción: registrar una aplicación en Microsoft Entra ID, usar una entidad de
servicio y una capacidad, pedir el token por REST (`GenerateToken`) y montar el informe
con el SDK `powerbi-client`. El portal no usa esta vía: requeriría JavaScript adicional
(el repositorio evita CDN) y la lógica del token en el backend.

### Activar el tablero en el portal

1. Edita `[tablero]` en [`portal.toml`](../portal.toml) (producción) o
   [`portal.dev.toml`](../portal.dev.toml) (local):

   ```toml
   [tablero]
   habilitado = true
   url = "https://app.powerbi.com/reportEmbed?reportId=…&autoAuth=true"
   ```

2. Valida la configuración:

   ```bash
   python3 -m portal --config portal.toml --check
   ```

3. Reinicia el portal (`systemctl restart portal`). Aparece la sección **Tablero de
   infraestructura** con el informe y un enlace «Abrir en Power BI» de respaldo.

El servidor valida el enlace: solo acepta `https://app.powerbi.com/reportEmbed…` o
`https://app.powerbi.com/view…` (nunca la URL del editor) y la CSP del portal ya permite
`frame-src https://app.powerbi.com https://login.microsoftonline.com`. El iframe lo carga
el **navegador del visitante**, no la VM: el servidor no necesita salida a Internet, pero
el equipo que ve la página sí.


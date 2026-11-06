# Plan de implementación — Landing del Portal de Clientes (demo)

Prototipo funcional para probar el Portal de Clientes de **PortoCaribe Logística S.A.**
(bodega de Mamonal, Cartagena), basado en
[`landing_pages_plan.md`](landing_pages_plan.md). No es el portal real: es una
demostración navegable, con datos simulados y métricas etiquetadas como tales, que
luego puede conectarse al backend definitivo.

> **Decisiones de partida**
>
> - Se despliega en la **VM2** (`srv-core`), junto a Apache/PostgreSQL y el resto de
>   servicios; la VM1 queda para Asterisk y el servicio de cámaras.
> - **Python stdlib + HTML/CSS/JS sin frameworks**; sin CDN ni recursos externos.
> - Datos de demostración en **SQLite** (no se toca la PostgreSQL real).
> - Login, rate limiting, sesiones y cabeceras de seguridad implementados en el servidor.
> - El widget de rendimiento puede leer el CSV del monitor o medir el propio servidor.

---

## 1. Objetivo y alcance

**Objetivo.** Construir una landing de acceso al portal que permita:

1. Iniciar sesión con credenciales de demostración y ver las medidas de seguridad
   (TLS, bloqueo por intentos fallidos).
2. Buscar un contenedor por número, BL u orden de despacho.
3. Ver estado, detalles de la carga y línea de tiempo.
4. Consultar avisos operativos y el canal de soporte.
5. Mostrar un indicador de rendimiento que contraste con el problema de respuestas
   superiores a 10 segundos.

**Dentro del alcance**

- Servidor HTTPS con `http.server` + `ssl` y API JSON.
- Autenticación con `scrypt`, sesiones y CSRF.
- Rate limiting visible (5 intentos / 10 min, bloqueo temporal).
- Búsqueda y timeline sobre datos de demostración.
- Interfaz responsive y accesible, sin dependencias.
- Integración opcional de solo lectura con el CSV del monitor.
- Pruebas de unidad e integración con `unittest`.

**Fuera del alcance**

- Portal de producción, conexión a la PostgreSQL real, pagos o documentos.
- Gestión de usuarios, recuperación de contraseña, correo real.
- Panel administrativo.
- Certificados públicos: se usa uno autofirmado para la demo.

**Supuestos**

1. VM2 con Python 3.12, Apache/PostgreSQL ya existentes; el demo no los modifica.
2. Navegador moderno (Chrome/Firefox/Edge) con JavaScript habilitado.
3. La VM2 tiene IP fija en la VLAN de servicios (`10.30.50.5` en el plan del monitor).
4. El monitor puede apuntar su sonda `PortalWeb` a esta landing.
5. El laboratorio no tiene salida a internet: todo se sirve local.

---

## 2. Principios de diseño

1. **Stdlib primero.** Nada de Flask, Django, Jinja ni npm; el servidor y la lógica
   caben en pocos módulos.
2. **Demo honesta.** Banner visible de “entorno de demostración”; los datos y las
   métricas simuladas se etiquetan; nunca se presentan como producción.
3. **Seguridad demostrable.** Lo que la interfaz anuncia (TLS, bloqueo de intentos)
   se implementa de verdad en el servidor, no solo en el navegador.
4. **Separación clara.** HTML/CSS/JS estáticos + API JSON; sin plantillas mezcladas.
5. **Degradación elegante.** Sin JS se muestra un mensaje claro; si falta el CSV del
   monitor, el widget mide el servidor y lo indica.
6. **Rendimiento como requisito.** Respuesta local < 1 s y API p95 < 100 ms; el
   contraste con los 10 s anteriores es parte de la demostración.
7. **Accesible por defecto.** Contraste AA, foco visible, etiquetas, `aria-live` y
   navegación por teclado.

---

## 3. Arquitectura

```
Navegador (HTML/CSS/JS)
        │  HTTPS 8443 (o 443 vía Apache)
        ▼
 portal/app.py  (ThreadingHTTPServer + router)
   ├── /               → web/ (HTML, CSS, JS, SVG)
   ├── /api/login      → auth + rate limit
   ├── /api/sesion     → usuario actual + CSRF
   ├── /api/logout     → cierre de sesión
   ├── /api/track      → búsqueda en SQLite
   ├── /api/avisos     → avisos operativos
   └── /api/estado     → latencia y estado (monitor o self)
        │
        ├── SQLite  /var/lib/portal/portal.db
        └── CSV     /srv/monitor/metricas/metricas_*.csv  (opcional)
```

**Capas**

| Capa | Responsabilidad | Archivos |
|---|---|---|
| Servidor | Socket, TLS, router, errores, estáticos | `app.py`, `servidor.py` |
| Seguridad | Contraseñas, sesiones, CSRF, rate limit, cabeceras | `auth.py`, `seguridad.py` |
| Datos | Esquema, semilla, consultas | `datos.py` |
| API | Serialización y códigos HTTP | `api.py` |
| Monitor | Lectura del CSV y métricas propias | `monitor.py` |
| Interfaz | Estructura, estilos y comportamiento | `web/` |

Servidor `ThreadingHTTPServer` con `protocol_version = "HTTP/1.1"`, `Content-Length`
correcto en cada respuesta, timeout de socket y límite de cuerpo (16 KB).

---

## 4. Stack de biblioteca estándar

| Necesidad | Módulo | Uso |
|---|---|---|
| Servidor HTTP | `http.server`, `socketserver` | `ThreadingHTTPServer`, `BaseHTTPRequestHandler` |
| TLS | `ssl` | `SSLContext(PROTOCOL_TLS_SERVER)`, mínimo TLS 1.2 |
| Router | — | tabla de rutas y métodos en `app.py` |
| JSON | `json` | API, configuración de respuestas |
| SQLite | `sqlite3` | Datos de demo, intentos de login, WAL |
| Contraseñas | `hashlib`, `secrets` | `scrypt` + sal aleatoria |
| Comparación segura | `hmac` | `compare_digest` en contraseñas y tokens |
| Sesiones y CSRF | `secrets`, `http.cookies` | `token_urlsafe`, cookie `HttpOnly` |
| Validación | `re`, `ipaddress` | Número de contenedor, IP del cliente |
| CSV del monitor | `csv`, `pathlib` | Última fila de `PortalWeb` |
| MIME y estáticos | `mimetypes`, `pathlib` | Tipo correcto y protección de rutas |
| Configuración | `tomllib`, `argparse` | `portal.toml`, subcomandos |
| Tiempo | `datetime`, `zoneinfo`, `time` | Ventanas de rate limit y latencias |
| Logs | `logging.handlers` | Rotación, sin contraseñas |
| Pruebas | `unittest`, `http.client`, `unittest.mock` | Integración con servidor efímero |
| Apagado | `signal` | Cierre ordenado del servidor |

**Dependencias de terceros: ninguna.** El certificado se genera con `openssl` del
sistema (no es una dependencia de Python) y solo para el laboratorio.

---

## 5. Seguridad

### 5.1 Autenticación

- Contraseñas con `hashlib.scrypt(password, salt=sal, n=2**14, r=8, p=1)`, sal de 16
  bytes y formato almacenado `scrypt$n$r$p$sal$hash` (base64).
- Usuario inexistente: se verifica contra un hash ficticio para no filtrar por tiempo.
- Mensaje único “Usuario o contraseña incorrectos” (sin enumeración de usuarios).
- Usuario demo `cliente.demo` con contraseña `Porto2026*`, documentada y marcada como
  solo demo; se puede cambiar con `PORTAL_DEMO_PASSWORD` al sembrar.

### 5.2 Sesiones

- `sid = secrets.token_urlsafe(32)`, guardado en memoria con `threading.Lock` y TTL de
  30 minutos (renovable por actividad). Reiniciar el servidor cierra sesiones (aceptable
  para la demo; se documenta).
- Cookie `sid`: `HttpOnly; Secure; SameSite=Strict; Path=/`; en pruebas HTTP se puede
  desactivar `Secure` con una opción explícita.
- `POST /api/logout` exige token CSRF y borra la sesión.

### 5.3 CSRF

- Token por sesión (`secrets.token_urlsafe(32)`), entregado por `GET /api/sesion`.
- Todo `POST` autenticado exige `X-CSRF-Token`; si falta o no coincide → `403`.
- El login no lleva CSRF (no hay sesión aún) pero sí rate limit.

### 5.4 Rate limiting visible

- Ventana deslizante de **10 minutos**, máximo **5 fallos** por combinación
  `(IP, usuario)`; al superar el umbral, bloqueo de **120 s**.
- Además, límite por IP de 20 fallos/10 min para frenar _password spraying_.
- Respuesta `429` con `Retry-After` y cuerpo `{error, retry_after_s}`; la interfaz
  muestra intentos restantes y una cuenta regresiva.
- Persistido en SQLite (`intentos`), con limpieza de filas de más de 24 h.
- La IP se toma del socket; `X-Forwarded-For` solo se acepta si `confiar_proxy = true`
  (detrás de Apache).

### 5.5 Cabeceras y validación

| Cabecera | Valor |
|---|---|
| `Content-Security-Policy` | `default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'` |
| `Strict-Transport-Security` | `max-age=15552000` (solo HTTPS) |
| `X-Content-Type-Options` | `nosniff` |
| `Referrer-Policy` | `no-referrer` |
| `X-Frame-Options` | `DENY` |
| `Permissions-Policy` | `geolocation=(), microphone=(), camera=()` |
| `Cache-Control` | `no-store` en API; `public, max-age=300` en estáticos |

- Cuerpo máximo 16 KB; JSON inválido → `400`; métodos no permitidos → `405`.
- Rutas estáticas resueltas con `Path.resolve()` y verificación de que quedan dentro de
  `web/` (sin `..`).
- SQL siempre parametrizado; salida al DOM con `textContent`, nunca `innerHTML` con
  datos del usuario.
- Errores internos: mensaje genérico al cliente, detalle solo en el log.

---

## 6. Modelo de datos (SQLite)

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE usuarios (
  id INTEGER PRIMARY KEY,
  usuario TEXT NOT NULL UNIQUE,
  nombre TEXT NOT NULL,
  hash TEXT NOT NULL,
  rol TEXT NOT NULL DEFAULT 'cliente',
  activo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE intentos (
  id INTEGER PRIMARY KEY,
  ip TEXT NOT NULL,
  usuario TEXT NOT NULL,
  ts TEXT NOT NULL,
  exito INTEGER NOT NULL
);
CREATE INDEX idx_intentos_ip_ts ON intentos(ip, ts);
CREATE INDEX idx_intentos_usuario_ts ON intentos(usuario, ts);

CREATE TABLE contenedores (
  numero TEXT PRIMARY KEY,          -- ISO 6346: 4 letras + 7 dígitos
  bl TEXT NOT NULL,
  orden TEXT NOT NULL,
  estado TEXT NOT NULL,             -- EN_MUELLE | ALMACENADO | EN_DESPACHO | DESPACHADO | EN_TRANSITO
  importador TEXT NOT NULL,
  buque TEXT NOT NULL,
  arribo TEXT NOT NULL,
  muelle TEXT NOT NULL,
  bodega TEXT NOT NULL,
  actualizado TEXT NOT NULL
);
CREATE INDEX idx_contenedores_bl ON contenedores(bl);
CREATE INDEX idx_contenedores_orden ON contenedores(orden);

CREATE TABLE hitos (
  id INTEGER PRIMARY KEY,
  numero TEXT NOT NULL REFERENCES contenedores(numero),
  orden INTEGER NOT NULL,
  ts TEXT NOT NULL,
  titulo TEXT NOT NULL,
  detalle TEXT NOT NULL,
  ubicacion TEXT NOT NULL,
  completado INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_hitos_numero ON hitos(numero, orden);

CREATE TABLE avisos (
  id INTEGER PRIMARY KEY,
  titulo TEXT NOT NULL,
  detalle TEXT NOT NULL,
  severidad TEXT NOT NULL,          -- info | advertencia | critico
  desde TEXT NOT NULL,
  hasta TEXT NOT NULL
);
```

**Semilla**

- 8 contenedores con números ISO 6346 válidos (el dígito verificador se calcula en el
  código, no se escribe a mano), BL y orden únicos.
- 6 hitos por contenedor: arribo del buque, descarga, ingreso a bodega, inspección,
  proceso de despacho y salida por garita; los últimos quedan pendientes según el estado.
- 3 avisos: congestión en muelle, estimado de entrega y ventana de despacho.
- Fechas relativas a `hoy` por defecto (para que la demo se vea vigente), con opción
  `--fecha-base` para pruebas deterministas.
- `INSERT OR IGNORE` para que sembrar dos veces no duplique.

La landing **no** se conecta a PostgreSQL: usa SQLite para no tocar la base real. La
capa `datos.py` expone funciones (`buscar_contenedor`, `listar_avisos`,
`registrar_intento`) que después pueden reimplementarse contra PostgreSQL sin cambiar
la API.

---

## 7. API

| Método | Ruta | Auth | Cuerpo / parámetros | Respuesta |
|---|---|---|---|---|
| `GET` | `/api/sesion` | cookie | — | `{autenticado, usuario, nombre, csrf}` |
| `POST` | `/api/login` | no | `{usuario, password}` | `200` + cookie, o `401`/`429` |
| `POST` | `/api/logout` | cookie + CSRF | — | `204` |
| `GET` | `/api/track?q=` | cookie | número, BL u orden | `{contenedor, hitos}` o `404` |
| `GET` | `/api/avisos` | cookie | — | `{avisos: [...]}` |
| `GET` | `/api/estado` | cookie | — | `{estado, latencia_ms, http_status, fuente, timestamp, umbral_ms}` |

- Respuestas JSON con `Content-Type: application/json; charset=utf-8` y
  `Cache-Control: no-store`.
- Error uniforme: `{"error": {"codigo": "NO_ENCONTRADO", "mensaje": "..."}}`.
- Códigos: `200`, `204`, `400`, `401`, `403`, `404`, `405`, `429`, `500`.
- `GET /api/track` normaliza mayúsculas/espacios y valida el formato antes de consultar.
- Si el contenedor tiene el dígito verificador inválido, se responde `400` con un
  mensaje que explica el formato (no se busca en la base).
- `GET /api/estado` devuelve `fuente` con uno de `monitor`, `monitor-obsoleto`,
  `servidor` o `simulado`, para que la interfaz pueda etiquetar el dato.

### 7.1 Origen del indicador de rendimiento

1. **Monitor (preferido):** leer el CSV más reciente de
   `metricas_*.csv`, filtrar `modulo == "PortalWeb"` y `fuente == "http"`, y tomar la
   última fila por `timestamp`; devolver `latencia_ms`, `http_status` y `timestamp`.
2. **Servidor:** si no hay CSV, medir una consulta de prueba a SQLite (`SELECT 1`) o
   la última duración registrada de `/api/track`, con `perf_counter`, y reportar esa
   latencia.
3. **Simulado:** si no hay CSV ni medición disponible, usar un valor determinista
   (semilla fija) entre 250 y 800 ms, con `fuente = "simulado"`.

La interfaz muestra siempre la fuente y la hora; nunca se rotula como “real” un dato
simulado. Si el CSV existe pero está viejo (> 15 min), se devuelve
`fuente = "monitor-obsoleto"` con la marca de tiempo vieja y la interfaz lo advierte;
no se hace pasar por actual.

---

## 8. Interfaz

### 8.1 Estructura

```
┌────────────────────────────────────────────────────────────┐
│ [logo] PortoCaribe Logística      🔒 HTTPS   ● 0.42 s      │
│                                        (widget de estado)   │
├───────────────────────────────┬────────────────────────────┤
│ Hero + login                  │ Avisos del puerto          │
│ usuario / contraseña          │ • Congestión en muelle 2   │
│ [Ingresar]                    │ • ETA buque MSC…           │
│ “5 intentos por 10 minutos”   │                            │
├───────────────────────────────┴────────────────────────────┤
│ Buscar: [ CSQU3054383 / BL / orden ]        [Consultar]    │
├────────────────────────────────────────────────────────────┤
│ Resultado: estado · detalles · timeline                    │
├────────────────────────────────────────────────────────────┤
│ Soporte: Liliana Támara · atención al cliente              │
└────────────────────────────────────────────────────────────┘
```

### 8.2 Mapeo con el documento de la landing

| Requisito | Implementación |
|---|---|
| Branding corporativo | Logo SVG inline, paleta azul marino/teal, tipografía del sistema |
| Formulario de login | Tarjeta con etiquetas, `autocomplete`, mostrar/ocultar contraseña |
| TLS visible | Badge “🔒 HTTPS” solo si `request.scheme == https`; tooltip con TLS 1.2+ |
| Límite de intentos visible | Aviso “5 intentos / 10 min”, contador restante y cuenta regresiva al bloquear |
| Búsqueda de contenedores | Input con ejemplos, validación en vivo, botón y `Enter` |
| Indicador de rendimiento | Punto verde/ámbar/rojo, latencia, fuente y última actualización |
| Estado actual | _Pill_ con color por estado y texto en español |
| Detalles de la carga | Grid: importador, buque, arribo, muelle, bodega, BL, orden |
| Timeline | Lista ordenada con hitos completados/pendientes y fecha |
| Avisos del puerto | Panel lateral con severidad y vigencia |
| Canal de soporte | Nombre, correo y horario de atención (datos de demo) |

### 8.3 Estados de la interfaz

- **Inicial:** login visible, búsqueda deshabilitada con ayuda “Inicia sesión para
  consultar”.
- **Cargando:** skeleton en resultados y botón con `aria-busy`.
- **Éxito:** estado, detalles y timeline; foco en el título del resultado.
- **No encontrado:** mensaje claro con ejemplos válidos.
- **Bloqueado:** banner con cuenta regresiva y botón deshabilitado.
- **Error de red:** reintento y mensaje sin detalles técnicos.
- **Sin JS:** `<noscript>` con instrucciones y datos de contacto.

### 8.4 Diseño visual y accesibilidad

- Paleta: `#0B2545` (marino), `#13A89E` (teal), `#F2A33A` (acento), `#F5F7FA` (fondo),
  `#1F2933` (texto).
- Tipografía: `system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`; sin fuentes
  externas.
- Layout mobile-first con CSS Grid; puntos de quiebre 640 px y 960 px.
- Contraste AA, foco visible, `skip-link`, etiquetas asociadas, `aria-live="polite"`
  en resultados y errores, `prefers-reduced-motion`.
- El logo y los iconos son SVG inline; ninguna imagen remota.
- Banner superior “ENTORNO DE DEMOSTRACIÓN — datos simulados” en todas las vistas.

### 8.5 Frontend sin frameworks

- `web/js/api.js`: `fetch` con `credentials: "same-origin"`, manejo de `429` y
  `Retry-After`, timeout con `AbortController`.
- `web/js/app.js`: estado de sesión, búsqueda, renderizado con `textContent` y
  `document.createElement`, cuenta regresiva.
- `web/js/ui.js`: helpers de formato de fechas (`Intl.DateTimeFormat("es-CO")`),
  estados y mensajes.
- Sin `innerHTML` con datos; sin `eval`; sin dependencias.

---

## 9. Estructura de archivos

```
pa/
├── portal/
│   ├── __init__.py
│   ├── __main__.py
│   ├── app.py              # servidor y router
│   ├── auth.py             # scrypt, sesiones, CSRF, rate limit
│   ├── seguridad.py        # cabeceras, cookies, validación
│   ├── datos.py            # SQLite: esquema, semilla, consultas
│   ├── api.py              # endpoints JSON
│   ├── monitor.py          # lectura del CSV de métricas
│   ├── config.py           # TOML + argparse
│   └── web/
│       ├── index.html
│       ├── css/estilos.css
│       ├── js/api.js
│       ├── js/ui.js
│       ├── js/app.js
│       └── assets/logo.svg
├── datos/
│   └── portal.db           # generado, ignorado por git
├── certs/                  # generado, ignorado por git
├── programacion/
│   └── portal.service
├── tests/
│   ├── test_validacion.py
│   ├── test_auth.py
│   ├── test_api.py
│   ├── test_estaticos.py
│   └── test_monitor.py
├── portal.toml
└── README.md
```

---

## 10. Configuración y despliegue

```toml
[servidor]
host = "0.0.0.0"
puerto = 8443
certificado = "certs/portal.crt"
clave = "certs/portal.key"
confiar_proxy = false
cuerpo_maximo_bytes = 16384

[portal]
base_datos = "/var/lib/portal/portal.db"   # en desarrollo: "datos/portal.db"
zona_horaria = "America/Bogota"
ttl_sesion_s = 1800
cookie_segura = true
csrf_obligatorio = true

[seguridad]
intentos_maximos = 5
ventana_s = 600
bloqueo_s = 120
intentos_maximos_ip = 20

[monitor]
csv_dir = "/srv/monitor/metricas"          # opcional: exportar data/csv del monitor
recurso_portal = "10.30.50.5"
frescura_max_s = 900
umbral_degradado_ms = 10000
```

- Certificado de laboratorio:
  ```bash
  openssl req -x509 -newkey rsa:2048 -sha256 -days 365 -nodes \
    -keyout certs/portal.key -out certs/portal.crt \
    -subj "/CN=portal.portocaribe.local" \
    -addext "subjectAltName=DNS:portal.portocaribe.local,DNS:localhost,IP:10.30.50.5"
  ```
- Arranque: `python3 -m portal --config portal.toml` (o `--check` para validar
  configuración, certificado y base).
- `systemd` con usuario `portal`, `ProtectSystem=strict`, `ReadWritePaths=/var/lib/portal`;
  puerto 8443 (> 1024) para no requerir _root_.
- Alternativa con Apache (más cercana al portal real): TLS en Apache y
  `ProxyPass / http://127.0.0.1:8080/`; en ese caso `confiar_proxy = true` y el
  servidor Python escucha solo en `127.0.0.1`.
- Firewall: abrir 8443/tcp (o 443/tcp si se usa Apache).

---

## 11. Pruebas y criterios de aceptación

| Nivel | Qué se prueba | Cómo |
|---|---|---|
| Unitario | Dígito verificador ISO 6346, normalización de búsqueda | `unittest` |
| Unitario | `scrypt`, comparación de contraseñas, sesiones, CSRF | `unittest` |
| Unitario | Rate limiter con reloj simulado (5 fallos, bloqueo, expiración) | `unittest` + `mock` |
| Unitario | Lectura del CSV del monitor y fallback | `tests/fixtures/metricas.csv` |
| Integración | Login correcto/incorrecto, cookie y flags | `http.client` contra servidor efímero |
| Integración | `429` tras 5 fallos y `Retry-After` | mismo servidor |
| Integración | Búsqueda encontrada/no encontrada, BL y orden | mismo servidor |
| Integración | CSRF ausente → `403`; método incorrecto → `405` | mismo servidor |
| Integración | Cabeceras CSP, `nosniff`, `no-referrer` y `no-store` | mismo servidor |
| Integración | Traversal (`/../etc/passwd`) → `404` | mismo servidor |
| Manual | Responsive 360/768/1280, teclado, contraste, lector de pantalla | Lista de verificación |
| Manual | TLS, HSTS y aviso de certificado autofirmado | Navegador |

**Definición de terminado (v1)**

1. `python3 -m portal --check` valida configuración, certificado y base sin errores.
2. Login demo funciona; 5 fallos producen `429` con cuenta regresiva; la contraseña
   correcta durante el bloqueo también se rechaza.
3. Un contenedor válido devuelve estado, detalles y timeline; uno inválido, un `404`
   amable; BL y orden también funcionan.
4. El widget muestra latencia < 1 s con la fuente (`monitor`/`monitor-obsoleto`/
   `servidor`/`simulado`) y la hora.
5. `curl -k -I https://localhost:8443/` muestra CSP, HSTS, `nosniff` y `no-referrer`.
6. La cookie de sesión es `HttpOnly; Secure; SameSite=Strict` y el CSRF se exige.
7. La interfaz responde a 360, 768 y 1280 px; navegable con teclado; sin recursos
   externos.
8. `python3 -m unittest discover -s tests` pasa sin red.
9. `grep -RhE "^(from|import) " portal/` solo muestra stdlib.
10. README con credenciales demo, generación de certificado, despliegue y límites.

---

## 12. Plan por fases

| Fase | Entregable | Horas | Criterio de cierre |
|---|---|---|---|
| **L0. Contenido y datos** | Copy en español, paleta, 8 contenedores, avisos, criterios | 2 | Datos y textos aprobados |
| **L1. Servidor y shell** | `ThreadingHTTPServer`, TLS, estáticos, router, cabeceras, `--check` | 3 | `https://localhost:8443` sirve la página |
| **L2. Autenticación** | scrypt, sesiones, CSRF, rate limit y UI de bloqueo | 4 | Login y `429` funcionando |
| **L3. Datos y tracking** | SQLite, semilla, búsqueda, timeline, API | 4 | Consultas por número/BL/orden |
| **L4. Interfaz** | Login, resultados, timeline, avisos, soporte, responsive | 5 | Flujo completo en navegador |
| **L5. Rendimiento** | Widget, lectura del CSV, modos y etiquetas | 2 | Latencia visible y atribuida |
| **L6. Calidad** | Pruebas, accesibilidad, errores, revisión de seguridad | 3 | Suite verde y checklist |
| **L7. Despliegue** | `systemd`, certificado, README, guion de demo | 2 | Servicio activo en VM2 |

**Total estimado: ~25 h.** Ruta mínima demostrable (L0–L4 + semilla de datos):
~18 h; el resto endurece y despliega.

Orden sugerido: L0 → L1 → L2 → L3 → L4 → L5 → L6 → L7.

---

## 13. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Certificado autofirmado | Aviso del navegador en la demo | Documentarlo; opción de CA local o TLS en Apache |
| Credenciales demo en el repo | Mala imagen si se publica | Banner demo, cambio por entorno, nunca usar en producción |
| Rate limit detrás de proxy | IP falsificada por `X-Forwarded-For` | `confiar_proxy` solo con Apache y cabecera limpiada |
| SQLite con escrituras concurrentes | `database is locked` | WAL, `timeout`, escritura corta |
| CSP bloquea estilos/scripts inline | Página sin estilos | CSS/JS externos y `script-src 'self'` |
| Datos simulados confundidos con reales | Conclusiones falsas | `fuente` visible, banner DEMO, fechas de siembra |
| Monitor sin CSV accesible | Widget sin dato real | Fallback medido/simulado etiquetado |
| JS deshabilitado | Sin búsqueda | `<noscript>` con contacto |
| Afirmar “< 1 s” sin medir | Demostración engañosa | Medición real por respuesta y registro |
| Apache y Python compitiendo por el puerto | Servicio caído | 8443 para Python o proxy a 8080 |

---

## 14. Decisiones y pendientes

**Confirmadas**

- Se despliega en la VM2, con el resto de servicios.
- Demo con datos simulados; no toca PostgreSQL.
- stdlib + HTML/CSS/JS, sin frameworks.
- Login, rate limit y TLS visibles desde la interfaz.

**Pendientes**

- ¿Logo y colores oficiales de PortoCaribe o se usan placeholders?
- ¿Datos reales de contacto de Liliana Támara o placeholders de demo?
- ¿TLS lo termina Apache (443) o el propio Python (8443)?
- ¿El widget debe leer el CSV del monitor o basta con medir el servidor?

## 15. Siguiente paso

Cerrar L0 (textos, logo y datos de ejemplo) e implementar L1–L2: servidor HTTPS,
estáticos, login y rate limiting. Con eso ya se puede mostrar la página y el bloqueo
de intentos, que es lo que el documento pide demostrar.

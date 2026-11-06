# Portal de Clientes PortoCaribe (demostración)

Prototipo funcional del portal de clientes de **PortoCaribe Logística S.A.** para la
bodega de Mamonal (Cartagena). Usa solo la biblioteca estándar de Python: servidor HTTP,
SQLite, `scrypt`, sesiones, CSRF y rate limiting.

> **Entorno de demostración.** Los datos son ficticios. No se conecta a la PostgreSQL
> real ni sustituye al portal de producción.

## Requisitos

- Python 3.11 o superior (probado con 3.12).
- Sin dependencias de terceros (`dependencies = []`).
- Apache 2.4 solo para el despliegue con TLS en 443.

## Arranque rápido (desarrollo)

```bash
python3 -m portal --config portal.dev.toml
```

Abre `http://127.0.0.1:8080`.

- Usuario demo: `cliente.demo`
- Contraseña demo: `Porto2026*`
- La base se crea sola en `datos/portal.db` y se siembra con 8 contenedores, sus hitos
  y 3 avisos.

Para validar configuración y base sin arrancar el servidor:

```bash
python3 -m portal --config portal.dev.toml --check
```

Para reiniciar los datos de demostración, borra `datos/portal.db` y vuelve a arrancar.

## Pruebas

```bash
python3 -m unittest discover -s tests -v
```

Las pruebas usan SQLite temporal y un servidor en un puerto efímero; no requieren red
ni Apache.

## Estructura

```
portal/
├── app.py            # servidor, router, estáticos, cookies y cabeceras
├── api.py            # endpoints JSON
├── auth.py           # scrypt, sesiones, CSRF y rate limit
├── cripto.py         # hash/verificación de contraseñas
├── datos.py          # esquema SQLite, semilla y consultas
├── rendimiento.py    # medición propia del servidor
├── config.py         # TOML + validación
├── cli.py            # python -m portal
└── web/              # HTML, CSS, JS y logo (sin frameworks)
```

## Despliegue con Apache y TLS

1. Copia el proyecto a `/opt/portal` y crea el usuario del servicio:

   ```bash
   sudo useradd --system --home /opt/portal --shell /usr/sbin/nologin portal
   sudo mkdir -p /var/lib/portal
   sudo chown portal:portal /var/lib/portal
   ```

2. Certificado de laboratorio (o usa el del portal real):

   ```bash
   sudo mkdir -p /etc/apache2/ssl
   sudo openssl req -x509 -newkey rsa:2048 -sha256 -days 365 -nodes \
     -keyout /etc/apache2/ssl/portal.key \
     -out /etc/apache2/ssl/portal.crt \
     -subj "/CN=portal.portocaribe.local" \
     -addext "subjectAltName=DNS:portal.portocaribe.local,DNS:localhost,IP:10.30.50.5"
   ```

3. Instala el VirtualHost de [`apache/portal-portocaribe.conf`](apache/portal-portocaribe.conf):

   ```bash
   sudo cp apache/portal-portocaribe.conf /etc/apache2/sites-available/
   sudo a2enmod ssl proxy proxy_http headers
   sudo a2ensite portal-portocaribe
   sudo apache2ctl configtest
   sudo systemctl reload apache2
   ```

4. Configuración de producción [`portal.toml`](portal.toml) (TLS en Apache, backend en
   `127.0.0.1:8080`).

5. Servicio [`programacion/portal.service`](programacion/portal.service):

   ```bash
   sudo cp programacion/portal.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now portal
   ```

6. Firewall: abre **443/tcp**. El puerto 8080 no se expone.

## Seguridad implementada

- Contraseñas con `scrypt` (n=2¹⁴, r=8, p=1) y sal aleatoria.
- Sesiones con token aleatorio, TTL de 30 minutos, cookie `HttpOnly; Secure;
  SameSite=Strict` (en producción).
- CSRF por sesión para `POST /api/logout`.
- Rate limit de 5 fallos por usuario/IP en 10 minutos y bloqueo de 120 s; además,
  20 fallos por IP en la misma ventana.
- Cabeceras CSP, HSTS (Apache), `nosniff`, `X-Frame-Options`, `Referrer-Policy` y
  `Permissions-Policy`.
- Cuerpo máximo de 16 KB, rutas estáticas confinadas a `portal/web/`, SQL parametrizado.
- Logs sin contraseñas.

## API

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/sesion` | Estado de la sesión y token CSRF |
| `POST` | `/api/login` | `{usuario, password}` |
| `POST` | `/api/logout` | Requiere `X-CSRF-Token` |
| `GET` | `/api/track?q=` | Contenedor, BL u orden |
| `GET` | `/api/avisos` | Avisos vigentes |
| `GET` | `/api/estado` | Latencia propia y umbral |

El widget de rendimiento mide el servidor con `perf_counter` y el navegador con
`performance.now`; no depende del monitor. El CSV del monitor queda para el informe.

## Límites conocidos

- SQLite es suficiente para la demostración; el portal real usa PostgreSQL.
- Las sesiones viven en memoria: reiniciar el servicio cierra las sesiones.
- El certificado autofirmado muestra la advertencia del navegador; es esperado en el
  laboratorio.
- La carga de prueba no reproduce el escenario de múltiples buques; para eso está el
  monitor y su histórico.

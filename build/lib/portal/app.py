"""Servidor HTTP del portal: router, estáticos, cookies y cabeceras."""

from __future__ import annotations

import ipaddress
import json
import logging
import mimetypes
import ssl
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from .api import API, ErrorAPI
from .auth import Autenticacion
from .config import Config
from .datos import BaseDatos
from .rendimiento import Medidor

LOG = logging.getLogger("portal.app")

CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


class Aplicacion:
    def __init__(self, config: Config):
        self.cfg = config
        self.db = BaseDatos(config.portal.base_datos)
        self.db.inicializar()
        self.db.sembrar()
        self.auth = Autenticacion(self.db, config)
        self.medidor = Medidor(config.portal.base_datos, config.rendimiento.umbral_degradado_ms)
        self.api = API(self.db, self.auth, self.medidor, config)
        self.web_root = (Path(__file__).resolve().parent / "web").resolve()


class Manejador(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PortoCaribePortal/1.0"
    timeout = 10
    app: Aplicacion

    # ------------------------------------------------------------- verbos HTTP
    def do_GET(self) -> None:  # noqa: N802
        self._despachar("GET")

    def do_HEAD(self) -> None:  # noqa: N802
        self._despachar("HEAD")

    def do_POST(self) -> None:  # noqa: N802
        self._despachar("POST")

    def _despachar(self, metodo: str) -> None:
        partes = urlsplit(self.path)
        ruta = unquote(partes.path)
        try:
            if ruta == "/api" or ruta.startswith("/api/"):
                self._api(metodo, ruta, partes.query)
            else:
                self._estatico(metodo, ruta)
        except ErrorAPI as exc:
            cuerpo = {"error": {"codigo": exc.codigo, "mensaje": exc.mensaje}}
            cabeceras = None
            if exc.retry_after is not None:
                cuerpo["retry_after_s"] = exc.retry_after
                cabeceras = {"Retry-After": str(exc.retry_after)}
            self._json(exc.status, cuerpo, cabeceras=cabeceras)
        except (BrokenPipeError, ConnectionResetError):
            LOG.info("Conexión cerrada por el cliente")
        except Exception:
            LOG.exception("Error no controlado en %s %s", metodo, ruta)
            self._json(500, {"error": {"codigo": "INTERNO", "mensaje": "Error interno del portal."}})

    # --------------------------------------------------------------------- API
    def _api(self, metodo: str, ruta: str, consulta: str) -> None:
        sid = self._sid()

        if metodo == "GET" and ruta == "/api/sesion":
            self._json(200, self.app.api.sesion(sid))
            return

        if metodo == "GET" and ruta == "/api/track":
            valor = parse_qs(consulta).get("q", [""])[0]
            self._json(200, self.app.api.track(valor, sid))
            return

        if metodo == "GET" and ruta == "/api/avisos":
            self._json(200, self.app.api.avisos(sid))
            return

        if metodo == "GET" and ruta == "/api/estado":
            self._json(200, self.app.api.estado(sid))
            return

        if metodo == "POST" and ruta == "/api/login":
            datos = self._leer_json()
            resultado = self.app.api.login(datos, self._ip_cliente())
            sid_nuevo = resultado.pop("sid")
            self._json(200, resultado, cookies=[self._cookie_sesion(sid_nuevo)])
            return

        if metodo == "POST" and ruta == "/api/logout":
            self.app.api.logout(sid, self.headers.get("X-CSRF-Token"))
            self._json(204, None, cookies=[self._cookie_expirada()])
            return

        if ruta in {
            "/api/sesion",
            "/api/track",
            "/api/avisos",
            "/api/estado",
            "/api/login",
            "/api/logout",
        }:
            raise ErrorAPI(405, "METODO_NO_PERMITIDO", "Método no permitido para esta ruta.")

        raise ErrorAPI(404, "NO_ENCONTRADO", "Ruta de API no encontrada.")

    # ---------------------------------------------------------------- estáticos
    def _estatico(self, metodo: str, ruta: str) -> None:
        if metodo not in ("GET", "HEAD"):
            raise ErrorAPI(405, "METODO_NO_PERMITIDO", "Método no permitido.")

        relativa = "index.html" if ruta in ("/", "/index.html") else ruta.lstrip("/")
        if not relativa or relativa.endswith("/"):
            self._texto(404, "No encontrado")
            return

        destino = (self.app.web_root / relativa).resolve()
        try:
            destino.relative_to(self.app.web_root)
        except ValueError:
            self._texto(404, "No encontrado")
            return

        if not destino.is_file():
            self._texto(404, "No encontrado")
            return

        contenido = destino.read_bytes()
        tipo = mimetypes.guess_type(str(destino))[0] or "application/octet-stream"
        cache = "no-store" if destino.suffix == ".html" else "public, max-age=300"

        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(contenido)))
        self.send_header("Cache-Control", cache)
        self._cabeceras_seguridad()
        self.end_headers()
        if metodo != "HEAD":
            self.wfile.write(contenido)

    # ------------------------------------------------------------------ salida
    def _json(
        self,
        status: int,
        contenido,
        cookies: list[str] | None = None,
        cabeceras: dict[str, str] | None = None,
    ) -> None:
        if contenido is None:
            cuerpo = b""
            tipo = "text/plain; charset=utf-8"
        else:
            cuerpo = json.dumps(contenido, ensure_ascii=False).encode("utf-8")
            tipo = "application/json; charset=utf-8"

        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self._cabeceras_seguridad()
        for nombre, valor in (cabeceras or {}).items():
            self.send_header(nombre, valor)
        for cookie in cookies or []:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        if cuerpo and self.command != "HEAD":
            self.wfile.write(cuerpo)

    def _texto(self, status: int, mensaje: str) -> None:
        cuerpo = (mensaje + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self._cabeceras_seguridad()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(cuerpo)

    def _cabeceras_seguridad(self) -> None:
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        if self._es_https():
            self.send_header("Strict-Transport-Security", "max-age=15552000")

    # ------------------------------------------------------------------ apoyo
    def _sid(self) -> str | None:
        crudo = self.headers.get("Cookie")
        if not crudo:
            return None
        try:
            galletas = SimpleCookie()
            galletas.load(crudo)
            morsel = galletas.get("sid")
            return morsel.value if morsel is not None else None
        except Exception:
            return None

    def _cookie_sesion(self, sid: str) -> str:
        partes = [
            f"sid={sid}",
            "Path=/",
            "HttpOnly",
            "SameSite=Strict",
            f"Max-Age={self.app.cfg.portal.ttl_sesion_s}",
        ]
        if self.app.cfg.portal.cookie_segura:
            partes.append("Secure")
        return "; ".join(partes)

    def _cookie_expirada(self) -> str:
        partes = ["sid=", "Path=/", "HttpOnly", "SameSite=Strict", "Max-Age=0"]
        if self.app.cfg.portal.cookie_segura:
            partes.append("Secure")
        return "; ".join(partes)

    def _leer_json(self) -> dict:
        largo = self.headers.get("Content-Length")
        if largo is None:
            raise ErrorAPI(411, "LONGITUD_REQUERIDA", "Falta Content-Length.")
        try:
            tamano = int(largo)
        except ValueError as exc:
            raise ErrorAPI(400, "CUERPO_INVALIDO", "Content-Length inválido.") from exc
        if tamano <= 0:
            raise ErrorAPI(400, "CUERPO_INVALIDO", "El cuerpo está vacío.")
        if tamano > self.app.cfg.servidor.cuerpo_maximo_bytes:
            raise ErrorAPI(413, "CUERPO_GRANDE", "El cuerpo de la petición es demasiado grande.")
        crudo = self.rfile.read(tamano)
        try:
            datos = json.loads(crudo.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ErrorAPI(400, "CUERPO_INVALIDO", "El cuerpo no es JSON válido.") from exc
        if not isinstance(datos, dict):
            raise ErrorAPI(400, "CUERPO_INVALIDO", "El cuerpo debe ser un objeto JSON.")
        return datos

    def _ip_remota(self) -> str:
        return self.client_address[0]

    def _ip_cliente(self) -> str:
        remota = self._ip_remota()
        if not self.app.cfg.servidor.confiar_proxy:
            return remota
        if remota not in ("127.0.0.1", "::1"):
            return remota
        reenviada = self.headers.get("X-Forwarded-For", "")
        if not reenviada:
            return remota
        primera = reenviada.split(",")[0].strip()
        try:
            ipaddress.ip_address(primera)
            return primera
        except ValueError:
            return remota

    def _es_https(self) -> bool:
        if isinstance(self.connection, ssl.SSLSocket):
            return True
        if not self.app.cfg.servidor.confiar_proxy:
            return False
        if self._ip_remota() not in ("127.0.0.1", "::1"):
            return False
        return self.headers.get("X-Forwarded-Proto", "").lower() == "https"

    def log_message(self, formato: str, *args) -> None:
        LOG.info("%s - %s", self._ip_remota(), formato % args)


class Servidor:
    def __init__(self, config: Config):
        self.cfg = config
        self.app = Aplicacion(config)
        manejador = type("ManejadorPortal", (Manejador,), {"app": self.app})
        self.httpd = ThreadingHTTPServer((config.servidor.host, config.servidor.puerto), manejador)
        self.httpd.daemon_threads = True
        self.puerto = self.httpd.server_address[1]

    def servir(self) -> None:
        LOG.info("Portal escuchando en http://%s:%s", self.cfg.servidor.host, self.puerto)
        self.httpd.serve_forever(poll_interval=0.2)

    def detener(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

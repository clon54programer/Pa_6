"""Utilidades compartidas por las pruebas del portal."""

from __future__ import annotations

import http.client
import json
import tempfile
import threading
from http.cookies import SimpleCookie
from pathlib import Path

from portal.app import Servidor
from portal.config import (
    Config,
    ConfigPortal,
    ConfigRendimiento,
    ConfigSeguridad,
    ConfigServidor,
)


def config_prueba(directorio: str | Path) -> Config:
    base = Path(directorio)
    return Config(
        servidor=ConfigServidor(
            host="127.0.0.1",
            puerto=0,
            confiar_proxy=False,
            cuerpo_maximo_bytes=16384,
        ),
        portal=ConfigPortal(
            base_datos=str(base / "portal.db"),
            zona_horaria="America/Bogota",
            ttl_sesion_s=1800,
            cookie_segura=False,
            csrf_obligatorio=True,
        ),
        seguridad=ConfigSeguridad(
            intentos_maximos=5,
            ventana_s=600,
            bloqueo_s=120,
            intentos_maximos_ip=20,
        ),
        rendimiento=ConfigRendimiento(umbral_degradado_ms=10000),
        ruta=base / "portal.toml",
    )


class ServidorPrueba:
    def __init__(self) -> None:
        self._temporal = tempfile.TemporaryDirectory()
        self.config = config_prueba(self._temporal.name)
        self.servidor = Servidor(self.config)
        self.hilo = threading.Thread(target=self.servidor.servir, daemon=True)
        self.hilo.start()

    @property
    def puerto(self) -> int:
        return self.servidor.puerto

    def peticion(self, metodo, ruta, cuerpo=None, cabeceras=None, cookie=None):
        conexion = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=5)
        encabezados = dict(cabeceras or {})
        datos = None
        if cuerpo is not None:
            datos = json.dumps(cuerpo).encode("utf-8")
            encabezados.setdefault("Content-Type", "application/json")
        if cookie:
            encabezados["Cookie"] = f"sid={cookie}"
        try:
            conexion.request(metodo, ruta, body=datos, headers=encabezados)
            respuesta = conexion.getresponse()
            contenido = respuesta.read()
            cabeceras = {nombre.lower(): valor for nombre, valor in respuesta.getheaders()}
            return respuesta.status, cabeceras, contenido
        finally:
            conexion.close()

    def json(self, metodo, ruta, cuerpo=None, cabeceras=None, cookie=None):
        status, headers, contenido = self.peticion(metodo, ruta, cuerpo, cabeceras, cookie)
        datos = json.loads(contenido.decode("utf-8")) if contenido else None
        return status, headers, datos

    def login(self, usuario="cliente.demo", password="Porto2026*"):
        status, headers, datos = self.json(
            "POST", "/api/login", {"usuario": usuario, "password": password}
        )
        cookie = None
        set_cookie = headers.get("set-cookie", "")
        if set_cookie:
            galletas = SimpleCookie()
            galletas.load(set_cookie)
            morsel = galletas.get("sid")
            if morsel is not None:
                cookie = morsel.value
        return status, headers, datos, cookie

    def cerrar(self) -> None:
        self.servidor.detener()
        self._temporal.cleanup()

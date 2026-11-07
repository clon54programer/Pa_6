"""Endpoints JSON del portal, independientes del servidor HTTP."""

from __future__ import annotations

import re

from .auth import Autenticacion, Sesion
from .config import Config
from .datos import ESTADOS, BaseDatos, es_numero_iso, normalizar_consulta
from .rendimiento import Medidor


class ErrorAPI(Exception):
    def __init__(self, status: int, codigo: str, mensaje: str, retry_after: int | None = None):
        super().__init__(mensaje)
        self.status = status
        self.codigo = codigo
        self.mensaje = mensaje
        self.retry_after = retry_after


class API:
    def __init__(self, db: BaseDatos, auth: Autenticacion, medidor: Medidor, config: Config):
        self.db = db
        self.auth = auth
        self.medidor = medidor
        self.cfg = config

    # ---------------------------------------------------------------- sesión
    def sesion(self, sid: str | None) -> dict:
        sesion = self.auth.obtener_sesion(sid)
        if sesion is None:
            return {"autenticado": False, "usuario": None, "nombre": None, "csrf": None}
        return {
            "autenticado": True,
            "usuario": sesion.usuario,
            "nombre": sesion.nombre,
            "csrf": sesion.csrf,
        }

    def login(self, datos: dict, ip: str) -> dict:
        if not isinstance(datos, dict):
            raise ErrorAPI(400, "DATOS_INVALIDOS", "El cuerpo debe ser un objeto JSON.")
        usuario = datos.get("usuario")
        password = datos.get("password")
        if not isinstance(usuario, str) or not isinstance(password, str):
            raise ErrorAPI(400, "DATOS_INVALIDOS", "Usuario y contraseña son obligatorios.")
        usuario = usuario.strip()
        if not usuario or not password:
            raise ErrorAPI(400, "DATOS_INVALIDOS", "Usuario y contraseña son obligatorios.")
        if len(usuario) > 64 or len(password) > 128:
            raise ErrorAPI(400, "DATOS_INVALIDOS", "Usuario o contraseña demasiado largos.")

        resultado = self.auth.intentar_login(usuario, password, ip)
        if not resultado["ok"]:
            if resultado["codigo"] == "BLOQUEADO":
                segundos = int(resultado["retry_after_s"])
                raise ErrorAPI(
                    429,
                    "BLOQUEADO",
                    f"Demasiados intentos fallidos. Espera {segundos} segundos.",
                    retry_after=segundos,
                )
            restantes = int(resultado.get("intentos_restantes", 0))
            raise ErrorAPI(
                401,
                "CREDENCIALES",
                f"Usuario o contraseña incorrectos. Intentos restantes: {restantes}.",
            )

        sesion: Sesion = resultado["sesion"]
        return {
            "usuario": sesion.usuario,
            "nombre": sesion.nombre,
            "csrf": sesion.csrf,
            "sid": sesion.sid,
        }

    def logout(self, sid: str | None, csrf: str | None) -> None:
        sesion = self._requerida(sid)
        if self.cfg.portal.csrf_obligatorio and not self.auth.validar_csrf(sesion, csrf):
            raise ErrorAPI(403, "CSRF", "Token CSRF inválido o ausente.")
        self.auth.cerrar_sesion(sid)

    # --------------------------------------------------------------- consulta
    def track(self, consulta: str, sid: str | None) -> dict:
        self._requerida(sid)
        texto = normalizar_consulta(consulta or "")
        if not texto or len(texto) > 40:
            raise ErrorAPI(400, "CONSULTA_INVALIDA", "Escribe un número, BL u orden válidos.")

        compacto = texto.replace(" ", "").replace("-", "")
        if re.fullmatch(r"[A-Z]{4}\d{7}", compacto):
            if not es_numero_iso(compacto):
                raise ErrorAPI(
                    400,
                    "CONTENEDOR_INVALIDO",
                    "El número no supera la validación ISO 6346 (dígito verificador).",
                )
            busqueda = compacto
        else:
            busqueda = texto

        datos = self.db.buscar_contenedor(busqueda)
        if datos is None:
            raise ErrorAPI(
                404,
                "NO_ENCONTRADO",
                "No encontramos ese contenedor, BL u orden. Revisa el dato e inténtalo de nuevo.",
            )
        datos["contenedor"]["estado_texto"] = ESTADOS.get(
            datos["contenedor"]["estado"], datos["contenedor"]["estado"]
        )
        return datos

    def avisos(self, sid: str | None) -> dict:
        self._requerida(sid)
        return {"avisos": self.db.listar_avisos()}

    def estado(self, sid: str | None) -> dict:
        self._requerida(sid)
        return self.medidor.medir()

    # ---------------------------------------------------------------- apoyo
    def _requerida(self, sid: str | None) -> Sesion:
        sesion = self.auth.obtener_sesion(sid)
        if sesion is None:
            raise ErrorAPI(401, "NO_AUTENTICADO", "Inicia sesión para continuar.")
        return sesion

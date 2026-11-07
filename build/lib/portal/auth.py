"""Autenticación, sesiones, CSRF y límite de intentos."""

from __future__ import annotations

import hmac
import math
import threading
import time
from dataclasses import dataclass

from . import cripto
from .config import Config
from .datos import BaseDatos


@dataclass
class Sesion:
    sid: str
    usuario: str
    nombre: str
    csrf: str
    creada: float
    ultima: float


class Autenticacion:
    def __init__(self, base_datos: BaseDatos, config: Config, ahora=None):
        self.db = base_datos
        self.cfg = config
        self.ahora = ahora or time.time
        self._sesiones: dict[str, Sesion] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ login
    def intentar_login(self, usuario: str, password: str, ip: str) -> dict:
        usuario = usuario.strip().lower()
        bloqueo = self.bloqueo_restante(ip, usuario)
        if bloqueo > 0:
            return {"ok": False, "codigo": "BLOQUEADO", "retry_after_s": bloqueo}

        fila = self.db.obtener_usuario(usuario)
        if fila is None:
            cripto.consumir_tiempo(password)
            valido = False
        else:
            valido = bool(fila["activo"]) and cripto.verify_password(password, fila["hash"])

        if not valido:
            self.db.registrar_intento(ip, usuario, False, self.ahora())
            return {
                "ok": False,
                "codigo": "CREDENCIALES",
                "intentos_restantes": self.intentos_restantes(ip, usuario),
            }

        self.db.limpiar_fallos(ip, usuario)
        self.db.registrar_intento(ip, usuario, True, self.ahora())
        sesion = self._crear_sesion(fila["usuario"], fila["nombre"])
        return {"ok": True, "sesion": sesion}

    # --------------------------------------------------------------- bloqueo
    def bloqueo_restante(self, ip: str, usuario: str) -> int:
        ahora = self.ahora()
        desde = ahora - self.cfg.seguridad.ventana_s

        fallos, ultimo = self.db.fallos_recientes(ip, usuario, desde)
        if fallos >= self.cfg.seguridad.intentos_maximos and ultimo is not None:
            restante = ultimo + self.cfg.seguridad.bloqueo_s - ahora
            if restante > 0:
                return max(1, math.ceil(restante))

        fallos_ip, ultimo_ip = self.db.fallos_por_ip(ip, desde)
        if fallos_ip >= self.cfg.seguridad.intentos_maximos_ip and ultimo_ip is not None:
            restante = ultimo_ip + self.cfg.seguridad.bloqueo_s - ahora
            if restante > 0:
                return max(1, math.ceil(restante))
        return 0

    def intentos_restantes(self, ip: str, usuario: str) -> int:
        desde = self.ahora() - self.cfg.seguridad.ventana_s
        fallos, _ = self.db.fallos_recientes(ip, usuario, desde)
        return max(0, self.cfg.seguridad.intentos_maximos - fallos)

    # --------------------------------------------------------------- sesiones
    def _crear_sesion(self, usuario: str, nombre: str) -> Sesion:
        ahora = self.ahora()
        self._limpiar_expiradas(ahora)
        sesion = Sesion(
            sid=cripto.token(32),
            usuario=usuario,
            nombre=nombre,
            csrf=cripto.token(32),
            creada=ahora,
            ultima=ahora,
        )
        with self._lock:
            self._sesiones[sesion.sid] = sesion
        return sesion

    def obtener_sesion(self, sid: str | None) -> Sesion | None:
        if not sid:
            return None
        ahora = self.ahora()
        with self._lock:
            sesion = self._sesiones.get(sid)
            if sesion is None:
                return None
            if ahora - sesion.ultima > self.cfg.portal.ttl_sesion_s:
                del self._sesiones[sid]
                return None
            sesion.ultima = ahora
            return sesion

    def cerrar_sesion(self, sid: str | None) -> None:
        if not sid:
            return
        with self._lock:
            self._sesiones.pop(sid, None)

    def validar_csrf(self, sesion: Sesion, token: str | None) -> bool:
        if not token:
            return False
        return hmac.compare_digest(sesion.csrf, token)

    def _limpiar_expiradas(self, ahora: float) -> None:
        with self._lock:
            vencidas = [
                sid
                for sid, sesion in self._sesiones.items()
                if ahora - sesion.ultima > self.cfg.portal.ttl_sesion_s
            ]
            for sid in vencidas:
                self._sesiones.pop(sid, None)

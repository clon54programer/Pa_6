"""Carga y validación de la configuración TOML del portal."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class ConfigServidor:
    host: str
    puerto: int
    confiar_proxy: bool
    cuerpo_maximo_bytes: int


@dataclass(frozen=True)
class ConfigPortal:
    base_datos: str
    zona_horaria: str
    ttl_sesion_s: int
    cookie_segura: bool
    csrf_obligatorio: bool


@dataclass(frozen=True)
class ConfigSeguridad:
    intentos_maximos: int
    ventana_s: int
    bloqueo_s: int
    intentos_maximos_ip: int


@dataclass(frozen=True)
class ConfigRendimiento:
    umbral_degradado_ms: float


@dataclass(frozen=True)
class Config:
    servidor: ConfigServidor
    portal: ConfigPortal
    seguridad: ConfigSeguridad
    rendimiento: ConfigRendimiento
    ruta: Path


def _texto(valor: object, nombre: str) -> str:
    if not isinstance(valor, str) or not valor.strip():
        raise ValueError(f"{nombre} debe ser texto no vacío")
    return valor.strip()


def _booleano(valor: object, nombre: str) -> bool:
    if not isinstance(valor, bool):
        raise ValueError(f"{nombre} debe ser true o false")
    return valor


def _entero(valor: object, nombre: str, minimo: int, maximo: int) -> int:
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ValueError(f"{nombre} debe ser un entero")
    if not minimo <= valor <= maximo:
        raise ValueError(f"{nombre} debe estar entre {minimo} y {maximo}")
    return valor


def _decimal(valor: object, nombre: str, minimo: float) -> float:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ValueError(f"{nombre} debe ser numérico")
    numero = float(valor)
    if numero < minimo:
        raise ValueError(f"{nombre} debe ser mayor o igual a {minimo}")
    return numero


def cargar_config(ruta: str | Path) -> Config:
    """Lee el TOML, aplica valores por defecto y valida lo esencial."""

    archivo = Path(ruta).expanduser().resolve()
    with archivo.open("rb") as manejador:
        datos = tomllib.load(manejador)

    servidor = datos.get("servidor", {})
    portal = datos.get("portal", {})
    seguridad = datos.get("seguridad", {})
    rendimiento = datos.get("rendimiento", {})

    if not isinstance(servidor, dict) or not isinstance(portal, dict):
        raise ValueError("Las secciones [servidor] y [portal] deben ser tablas TOML")

    host = _texto(servidor.get("host", "127.0.0.1"), "servidor.host")
    puerto = _entero(servidor.get("puerto", 8080), "servidor.puerto", 1, 65535)
    confiar_proxy = _booleano(servidor.get("confiar_proxy", False), "servidor.confiar_proxy")
    cuerpo_maximo = _entero(
        servidor.get("cuerpo_maximo_bytes", 16384),
        "servidor.cuerpo_maximo_bytes",
        1024,
        1048576,
    )

    base_datos = Path(_texto(portal.get("base_datos", "datos/portal.db"), "portal.base_datos"))
    if not base_datos.is_absolute():
        base_datos = (archivo.parent / base_datos).resolve()

    zona = _texto(portal.get("zona_horaria", "America/Bogota"), "portal.zona_horaria")
    try:
        ZoneInfo(zona)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"portal.zona_horaria no existe: {zona}") from exc

    ttl = _entero(portal.get("ttl_sesion_s", 1800), "portal.ttl_sesion_s", 60, 86400)
    cookie_segura = _booleano(portal.get("cookie_segura", True), "portal.cookie_segura")
    csrf = _booleano(portal.get("csrf_obligatorio", True), "portal.csrf_obligatorio")

    if not isinstance(seguridad, dict):
        raise ValueError("La sección [seguridad] debe ser una tabla TOML")

    intentos = _entero(seguridad.get("intentos_maximos", 5), "seguridad.intentos_maximos", 1, 100)
    ventana = _entero(seguridad.get("ventana_s", 600), "seguridad.ventana_s", 30, 86400)
    bloqueo = _entero(seguridad.get("bloqueo_s", 120), "seguridad.bloqueo_s", 10, 86400)
    intentos_ip = _entero(
        seguridad.get("intentos_maximos_ip", 20), "seguridad.intentos_maximos_ip", 1, 1000
    )

    if not isinstance(rendimiento, dict):
        raise ValueError("La sección [rendimiento] debe ser una tabla TOML")

    umbral = _decimal(rendimiento.get("umbral_degradado_ms", 10000), "rendimiento.umbral_degradado_ms", 1)

    return Config(
        servidor=ConfigServidor(
            host=host,
            puerto=puerto,
            confiar_proxy=confiar_proxy,
            cuerpo_maximo_bytes=cuerpo_maximo,
        ),
        portal=ConfigPortal(
            base_datos=str(base_datos),
            zona_horaria=zona,
            ttl_sesion_s=ttl,
            cookie_segura=cookie_segura,
            csrf_obligatorio=csrf,
        ),
        seguridad=ConfigSeguridad(
            intentos_maximos=intentos,
            ventana_s=ventana,
            bloqueo_s=bloqueo,
            intentos_maximos_ip=intentos_ip,
        ),
        rendimiento=ConfigRendimiento(umbral_degradado_ms=umbral),
        ruta=archivo,
    )

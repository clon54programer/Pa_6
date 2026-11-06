"""Funciones criptográficas basadas solo en la biblioteca estándar."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

_N = 2**14
_R = 8
_P = 1
_DKLEN = 32


def _b64(datos: bytes) -> str:
    return base64.b64encode(datos).decode("ascii")


def _desde_b64(texto: str) -> bytes:
    return base64.b64decode(texto.encode("ascii"), validate=True)


def hash_password(password: str) -> str:
    """Devuelve un hash scrypt con sal aleatoria y parámetros incluidos."""

    sal = secrets.token_bytes(16)
    derivada = hashlib.scrypt(
        password.encode("utf-8"), salt=sal, n=_N, r=_R, p=_P, dklen=_DKLEN
    )
    return f"scrypt${_N}${_R}${_P}${_b64(sal)}${_b64(derivada)}"


def verify_password(password: str, almacenado: str) -> bool:
    """Compara una contraseña con el formato scrypt$... del portal."""

    try:
        partes = almacenado.split("$")
        if len(partes) != 6 or partes[0] != "scrypt":
            return False
        n, r, p = int(partes[1]), int(partes[2]), int(partes[3])
        sal = _desde_b64(partes[4])
        esperada = _desde_b64(partes[5])
        derivada = hashlib.scrypt(
            password.encode("utf-8"), salt=sal, n=n, r=r, p=p, dklen=len(esperada)
        )
        return hmac.compare_digest(derivada, esperada)
    except (ValueError, TypeError):
        return False


def consumir_tiempo(password: str) -> None:
    """Calcula un scrypt descartado para igualar el tiempo de un usuario inexistente."""

    hashlib.scrypt(
        password.encode("utf-8"), salt=b"\x00" * 16, n=_N, r=_R, p=_P, dklen=_DKLEN
    )


def token(bytes_aleatorios: int = 32) -> str:
    return secrets.token_urlsafe(bytes_aleatorios)

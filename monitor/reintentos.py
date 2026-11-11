"""Reintentos con backoff exponencial y jitter (plan §11).

Solo se reintentan fallos transitorios: timeouts, errores de socket/OS y
``SondaError``. Un error de configuración (por ejemplo, falta de binario) se
propaga en el primer intento.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Callable, TypeVar

LOG = logging.getLogger("monitor.reintentos")

T = TypeVar("T")


def intentar(
    funcion: Callable[[], T],
    *,
    intentos: int = 2,
    espera_inicial: float = 0.5,
    factor: float = 2.0,
    jitter: float = 0.25,
    errores: tuple[type[BaseException], ...] = (TimeoutError, OSError),
    dormir: Callable[[float], None] = time.sleep,
    aleatorio: Callable[[float, float], float] = random.uniform,
) -> T:
    """Ejecuta ``funcion`` hasta ``intentos`` veces con backoff y jitter.

    Con ``intentos=2`` la espera entre el primer y el segundo intento es
    0,5 s (+ jitter); con tres intentos se añade 1 s. La espera nunca supera
    ``max_espera_s``.
    """
    intentos = max(1, int(intentos))
    ultimo: BaseException | None = None
    for numero in range(1, intentos + 1):
        try:
            return funcion()
        except errores as exc:
            ultimo = exc
            if numero >= intentos:
                break
            espera = espera_inicial * (factor ** (numero - 1))
            espera += aleatorio(0.0, jitter * espera)
            LOG.info(
                "intento %d/%d falló (%s); reintento en %.2f s",
                numero,
                intentos,
                str(exc)[:120],
                espera,
            )
            dormir(espera)
    assert ultimo is not None
    raise ultimo

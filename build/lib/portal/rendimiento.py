"""Medición de rendimiento propia del portal (sin depender del monitor)."""

from __future__ import annotations

import random
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path


class Medidor:
    def __init__(self, ruta_base_datos: str | Path, umbral_ms: float = 10000.0):
        self.ruta = Path(ruta_base_datos)
        self.umbral_ms = float(umbral_ms)
        self._simulado = random.Random(20261106).uniform(250.0, 800.0)
        self._ultimo: dict | None = None

    def medir(self) -> dict:
        inicio = time.perf_counter()
        fuente = "servidor"
        try:
            con = sqlite3.connect(self.ruta, timeout=2)
            try:
                con.execute("SELECT 1").fetchone()
            finally:
                con.close()
            latencia = (time.perf_counter() - inicio) * 1000.0
        except (sqlite3.Error, OSError):
            latencia = self._simulado
            fuente = "simulado"

        estado = "OK" if latencia <= self.umbral_ms else "DEGRADED"
        resultado = {
            "estado": estado,
            "latencia_ms": round(latencia, 2),
            "fuente": fuente,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "umbral_ms": self.umbral_ms,
        }
        self._ultimo = resultado
        return resultado

    def ultimo(self) -> dict | None:
        return self._ultimo

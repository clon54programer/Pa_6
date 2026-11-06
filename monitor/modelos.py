"""Modelo canónico de una fila de métricas."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

CAMPOS_CSV = [
    "timestamp",
    "timestamp_utc",
    "run_id",
    "modulo",
    "recurso_target",
    "nombre_recurso",
    "vlan",
    "zona",
    "estado",
    "tiempo_respuesta_ms",
    "perdida_paquetes_pct",
    "jitter_ms",
    "ancho_banda_mbps",
    "http_status",
    "puerto",
    "ip_origen",
    "ip_destino",
    "evento_seguridad",
    "sip_code",
    "llamadas_activas",
    "duracion_llamada_s",
    "dscp",
    "paquetes_delta",
    "bytes_delta",
    "detalle",
    "fuente",
    "schema_version",
]

FORMATO_LOCAL = "%Y-%m-%d %H:%M:%S"


@dataclass
class Resultado:
    timestamp: str
    timestamp_utc: str
    run_id: str
    modulo: str
    recurso_target: str
    estado: str
    fuente: str
    schema_version: int = 1
    nombre_recurso: Optional[str] = None
    vlan: Optional[int] = None
    zona: Optional[str] = None
    tiempo_respuesta_ms: Optional[float] = None
    perdida_paquetes_pct: Optional[float] = None
    jitter_ms: Optional[float] = None
    ancho_banda_mbps: Optional[float] = None
    http_status: Optional[int] = None
    puerto: Optional[int] = None
    ip_origen: Optional[str] = None
    ip_destino: Optional[str] = None
    evento_seguridad: Optional[str] = None
    sip_code: Optional[int] = None
    llamadas_activas: Optional[int] = None
    duracion_llamada_s: Optional[float] = None
    dscp: Optional[int] = None
    paquetes_delta: Optional[int] = None
    bytes_delta: Optional[int] = None
    detalle: Optional[str] = None
    huella: str = ""

    def a_dict(self) -> dict:
        return asdict(self)

    def a_csv(self) -> dict:
        datos = asdict(self)
        return {campo: datos.get(campo) for campo in CAMPOS_CSV}

    @classmethod
    def crear(
        cls,
        run_id: str,
        modulo: str,
        target: str,
        estado: str,
        fuente: str,
        zona_horaria: str = "America/Bogota",
        timestamp_evento: datetime | None = None,
        linea_evento: str | None = None,
        **extra,
    ) -> "Resultado":
        zona = ZoneInfo(zona_horaria)
        momento = timestamp_evento or datetime.now(timezone.utc)
        if momento.tzinfo is None:
            momento = momento.replace(tzinfo=zona)
        utc = momento.astimezone(timezone.utc)
        local = momento.astimezone(zona)
        resultado = cls(
            timestamp=local.strftime(FORMATO_LOCAL),
            timestamp_utc=utc.strftime(FORMATO_LOCAL),
            run_id=run_id,
            modulo=modulo,
            recurso_target=target,
            estado=estado,
            fuente=fuente,
            **{clave: valor for clave, valor in extra.items() if clave in cls.__dataclass_fields__},
        )
        if linea_evento is not None:
            material = f"{fuente}|{resultado.timestamp_utc}|{linea_evento}"
        else:
            material = f"{run_id}|{modulo}|{target}|{resultado.timestamp_utc}|{fuente}"
        resultado.huella = hashlib.sha256(material.encode("utf-8")).hexdigest()
        return resultado


def deduplicar(resultados: list[Resultado]) -> list[Resultado]:
    vistos: set[str] = set()
    salida: list[Resultado] = []
    for resultado in resultados:
        if resultado.huella in vistos:
            continue
        vistos.add(resultado.huella)
        salida.append(resultado)
    return salida

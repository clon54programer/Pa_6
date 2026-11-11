"""`inventario.csv` como dimensión única de metadatos (plan §9 y §12).

El TOML describe *qué* se mide y el inventario describe *quién es* cada
recurso (nombre, VLAN, zona, puerto, criticidad). El monitor usa el inventario
para completar las filas y avisa si el TOML lo contradice, de modo que no haya
dos fuentes de verdad para los mismos metadatos.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

LOG = logging.getLogger("monitor.inventario")

CAMPOS = (
    "recurso",
    "nombre",
    "tipo",
    "vlan",
    "zona",
    "puerto",
    "criticidad",
    "habilitado",
)


def _entero(valor: str | None) -> int | None:
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return None


def _booleano(valor: str | None) -> bool:
    return str(valor or "").strip().lower() in ("1", "true", "si", "sí", "yes")


def cargar(ruta: str | Path) -> dict[str, list[dict]]:
    """Devuelve ``{ip: [fichas]}``; una IP puede tener varios servicios."""
    archivo = Path(ruta)
    if not archivo.is_file():
        LOG.warning("No existe el inventario %s; se usan solo los metadatos del TOML", archivo)
        return {}
    indice: dict[str, list[dict]] = {}
    with archivo.open("r", encoding="utf-8-sig", newline="") as manejador:
        for fila in csv.DictReader(manejador):
            ip = (fila.get("recurso") or "").strip()
            if not ip:
                continue
            ficha = {
                "ip": ip,
                "nombre": (fila.get("nombre") or "").strip() or None,
                "tipo": (fila.get("tipo") or "").strip() or None,
                "vlan": _entero(fila.get("vlan")),
                "zona": (fila.get("zona") or "").strip() or None,
                "puerto": _entero(fila.get("puerto")),
                "criticidad": (fila.get("criticidad") or "").strip() or None,
                "habilitado": _booleano(fila.get("habilitado")),
            }
            indice.setdefault(ip, []).append(ficha)
    return indice


def buscar(inventario: dict[str, list[dict]], ip: str, tipo: str | None = None) -> dict | None:
    """Busca la ficha de ``ip``; si se indica ``tipo``, prioriza ese servicio."""
    fichas = inventario.get(str(ip or "").strip())
    if not fichas:
        return None
    if tipo:
        for ficha in fichas:
            if (ficha.get("tipo") or "").lower() == tipo.lower():
                return ficha
    return fichas[0]


def _normalizar(valor) -> str:
    return "" if valor is None else str(valor).strip().lower()


def comparar(seccion: str, ip: str, ficha: dict | None, *, nombre=None, vlan=None, zona=None) -> None:
    """Avisa cuando el TOML contradice al inventario (sin bloquear la corrida)."""
    if not ficha:
        return
    pares = (
        ("nombre", nombre, ficha.get("nombre")),
        ("vlan", vlan, ficha.get("vlan")),
        ("zona", zona, ficha.get("zona")),
    )
    for campo, en_toml, en_inventario in pares:
        if en_toml in (None, "") or en_inventario in (None, ""):
            continue
        if _normalizar(en_toml) != _normalizar(en_inventario):
            LOG.warning(
                "%s/%s: %s=%r en el TOML no coincide con %r en inventario.csv",
                seccion,
                ip,
                campo,
                en_toml,
                en_inventario,
            )

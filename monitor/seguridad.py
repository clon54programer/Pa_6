"""Parsers de logs y contadores para el módulo de seguridad."""

from __future__ import annotations

import re
from datetime import datetime

_MESES = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def _fecha(texto: str) -> datetime | None:
    iso = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})", texto)
    if iso:
        try:
            return datetime.strptime(iso.group(1) + " " + iso.group(2), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    clasica = re.match(r"([A-Z][a-z]{2})\s+(\d{1,2})\s+(\d{2}:\d{2}:\d{2})", texto)
    if clasica:
        mes = _MESES.get(clasica.group(1))
        if mes:
            try:
                return datetime(datetime.now().year, mes, int(clasica.group(2)),
                                *map(int, clasica.group(3).split(":")))
            except ValueError:
                return None
    return None


def parse_iptables(texto: str) -> dict[str, dict]:
    reglas: dict[str, dict] = {}
    patron = re.compile(r"^\[(\d+):(\d+)\]\s+-A\s+(\S+)\s+(.*)$")
    for linea in texto.splitlines():
        coincidencia = patron.match(linea.strip())
        if not coincidencia:
            continue
        pkts, bytes_, cadena, resto = coincidencia.groups()
        clave = f"{cadena} {resto}"
        reglas[clave] = {
            "pkts": int(pkts),
            "bytes": int(bytes_),
            "cadena": cadena,
            "regla": resto,
            "src": _opcion(resto, "-s"),
            "dst": _opcion(resto, "-d"),
            "proto": _opcion(resto, "-p"),
            "dport": _opcion(resto, "--dport"),
        }
    return reglas


def _opcion(texto: str, nombre: str) -> str | None:
    coincidencia = re.search(rf"{re.escape(nombre)}[= ]\s*(\S+)", texto)
    return coincidencia.group(1) if coincidencia else None


def delta_iptables(actual: dict[str, dict], anterior: dict[str, dict]) -> list[dict]:
    salida = []
    for clave, datos in actual.items():
        previo = anterior.get(clave, {"pkts": 0, "bytes": 0})
        delta_pkts = max(0, datos["pkts"] - int(previo.get("pkts", 0)))
        delta_bytes = max(0, datos["bytes"] - int(previo.get("bytes", 0)))
        if delta_pkts or delta_bytes:
            salida.append({**datos, "delta_pkts": delta_pkts, "delta_bytes": delta_bytes})
    return salida


def parse_fail2ban(texto: str) -> dict:
    datos = {"actuales": 0, "total": 0, "baneadas": []}
    for linea in texto.splitlines():
        if "Currently banned:" in linea:
            datos["actuales"] = _entero(linea)
        elif "Total banned:" in linea:
            datos["total"] = _entero(linea)
        elif "Banned IP list:" in linea:
            datos["baneadas"] = linea.split(":", 1)[1].split()
    return datos


def _entero(linea: str) -> int:
    coincidencia = re.search(r"(\d+)", linea)
    return int(coincidencia.group(1)) if coincidencia else 0


def parse_fail2ban_log(texto: str) -> list[dict]:
    eventos = []
    for linea in texto.splitlines():
        if " Ban " not in linea:
            continue
        coincidencia = re.search(r"\bBan\s+(\S+)", linea)
        if coincidencia:
            eventos.append({"ip": coincidencia.group(1), "linea": linea.strip(), "ts": _fecha(linea)})
    return eventos


def parse_auth(texto: str) -> list[dict]:
    eventos = []
    for linea in texto.splitlines():
        if "Failed password for" not in linea:
            continue
        coincidencia = re.search(r"Failed password for .*? from (\S+)", linea)
        if coincidencia:
            eventos.append({"ip": coincidencia.group(1), "linea": linea.strip(), "ts": _fecha(linea)})
    return eventos


def parse_kern(texto: str, prefijos: list[str]) -> list[dict]:
    eventos = []
    for linea in texto.splitlines():
        prefijo = next((p for p in prefijos if p in linea), None)
        if prefijo:
            eventos.append(
                {
                    "evento": "VLAN30_BLOCKED" if "VLAN30" in prefijo else "VLAN40_BLOCKED",
                    "linea": linea.strip(),
                    "ts": _fecha(linea),
                    "src": _opcion(linea, "SRC"),
                    "dst": _opcion(linea, "DST"),
                    "dport": _opcion(linea, "DPT"),
                }
            )
        elif "possible SYN flooding" in linea:
            eventos.append({"evento": "SYN_FLOOD", "linea": linea.strip(), "ts": _fecha(linea)})
    return eventos


def parse_netstat(texto: str) -> dict[str, int]:
    valores: dict[str, int] = {}
    lineas = texto.splitlines()
    for indice, linea in enumerate(lineas):
        if linea.startswith("TcpExt:") and indice + 1 < len(lineas):
            campos = linea.split()[1:]
            datos = lineas[indice + 1].split()[1:]
            for clave, valor in zip(campos, datos):
                if clave in ("ListenOverflows", "ListenDrops"):
                    try:
                        valores[clave] = int(valor)
                    except ValueError:
                        pass
    return valores


def parse_snmp(texto: str) -> dict[str, int]:
    valores: dict[str, int] = {}
    lineas = texto.splitlines()
    for indice, linea in enumerate(lineas):
        if linea.startswith("Icmp:") and indice + 1 < len(lineas):
            campos = linea.split()[1:]
            datos = lineas[indice + 1].split()[1:]
            for clave, valor in zip(campos, datos):
                if clave in ("InMsgs", "InErrors", "InDestUnreachs"):
                    try:
                        valores[clave] = int(valor)
                    except ValueError:
                        pass
    return valores


def parse_leases(texto: str) -> int:
    """IPs con arrendamiento activo (deduplicadas por bloque de lease)."""
    activos: set[str] = set()
    actual: str | None = None
    for linea in texto.splitlines():
        coincidencia = re.match(r"\s*lease\s+(\S+)\s*\{", linea)
        if coincidencia:
            actual = coincidencia.group(1)
            continue
        if actual and "binding state active;" in linea:
            activos.add(actual)
        elif linea.strip() == "}":
            actual = None
    return len(activos)

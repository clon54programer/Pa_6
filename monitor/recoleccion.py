"""Recolección de snapshots desde VM1/VM2 por SSH de solo lectura."""

from __future__ import annotations

import logging
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .config import Config

LOG = logging.getLogger("monitor.recoleccion")

# Recetas cerradas: el wrapper remoto solo acepta estos nombres.
RECETAS = {
    "vm1": [("cdr", "cdr.csv")],
    "vm2": [
        ("apache", "apache.txt"),
        ("iptables", "iptables.save"),
        ("fail2ban", "fail2ban.txt"),
        ("fail2banlog", "fail2ban.log"),
        ("auth", "auth.log"),
        ("kern", "kern.log"),
        ("netstat", "netstat.txt"),
        ("snmp", "snmp.txt"),
        ("dhcp_leases", "dhcpd.leases"),
        ("dhcp_estado", "dhcp_estado.txt"),
    ],
}

MAX_PARALELO = 8


def _destino(config: Config, host: str) -> Path:
    return config.datos / "entradas" / host


def _comando(config: Config, host: str, receta: str) -> list[str]:
    recoleccion = config.recoleccion
    destino = recoleccion["hosts"][host].get("host", host)
    return [
        "ssh",
        "-i", str(recoleccion["clave"]),
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=yes",
        "-o", f"UserKnownHostsFile={recoleccion['known_hosts']}",
        "-o", "PasswordAuthentication=no",
        "-o", "IdentitiesOnly=yes",
        "-o", "ConnectTimeout=5",
        f"{recoleccion['usuario']}@{destino}",
        receta,
    ]


def _traer(config: Config, host: str, receta: str, archivo: str) -> str | None:
    """Ejecuta una receta; devuelve el error o ``None`` si se guardó."""
    try:
        proceso = subprocess.run(
            _comando(config, host, receta),
            capture_output=True,
            timeout=float(config.recoleccion.get("timeout_s", 15)),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"{host}/{receta}: {exc}"
    if proceso.returncode != 0:
        return f"{host}/{receta}: {proceso.stderr.decode('utf-8', 'replace').strip()[:120]}"
    destino = _destino(config, host)
    destino.mkdir(parents=True, exist_ok=True)
    temporal = destino / (archivo + ".tmp")
    temporal.write_bytes(proceso.stdout)
    os.replace(temporal, destino / archivo)
    return None


def recolectar(config: Config, host: str | None = None) -> list[str]:
    recoleccion = config.recoleccion
    if not recoleccion.get("habilitado"):
        return []
    clave = Path(recoleccion["clave"])
    if not clave.is_file():
        LOG.warning("No existe la clave SSH %s; se omite la recolección", clave)
        return []

    hosts = recoleccion.get("hosts", {})
    if host:
        hosts = {host: hosts.get(host, {})} if host in hosts else {}

    trabajos = [
        (nombre, receta, archivo)
        for nombre in hosts
        for receta, archivo in RECETAS.get(nombre, [])
    ]
    if not trabajos:
        return []

    errores: list[str] = []
    with ThreadPoolExecutor(max_workers=min(MAX_PARALELO, len(trabajos))) as pool:
        futuros = {
            pool.submit(_traer, config, nombre, receta, archivo): (nombre, receta)
            for nombre, receta, archivo in trabajos
        }
        for futuro in as_completed(futuros):
            error = futuro.result()
            if error:
                errores.append(error)
    return errores

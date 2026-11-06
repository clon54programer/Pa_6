"""Recolección de snapshots desde VM1/VM2 por SSH de solo lectura."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from .config import Config

LOG = logging.getLogger("monitor.recoleccion")

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


def _destino(config: Config, host: str) -> Path:
    return config.datos / "entradas" / host


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
    errores: list[str] = []
    for nombre, datos in hosts.items():
        destino = _destino(config, nombre)
        destino.mkdir(parents=True, exist_ok=True)
        for receta, archivo in RECETAS.get(nombre, []):
            comando = [
                "ssh",
                "-i", str(clave),
                "-o", "BatchMode=yes",
                "-o", "StrictHostKeyChecking=yes",
                "-o", f"UserKnownHostsFile={recoleccion['known_hosts']}",
                "-o", "ConnectTimeout=5",
                f"{recoleccion['usuario']}@{datos.get('host', nombre)}",
                receta,
            ]
            try:
                proceso = subprocess.run(
                    comando,
                    capture_output=True,
                    timeout=float(recoleccion.get("timeout_s", 15)),
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                errores.append(f"{nombre}/{receta}: {exc}")
                continue
            if proceso.returncode != 0:
                errores.append(f"{nombre}/{receta}: {proceso.stderr.decode('utf-8', 'replace').strip()[:120]}")
                continue
            temporal = destino / (archivo + ".tmp")
            temporal.write_bytes(proceso.stdout)
            os.replace(temporal, destino / archivo)
    return errores

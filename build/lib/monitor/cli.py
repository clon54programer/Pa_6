"""CLI del monitor: run, export, recolectar, prune y validate."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from . import __version__
from .config import cargar_config
from .escritura import exportar_csv, podar
from .recoleccion import recolectar
from .runner import ejecutar

LOG = logging.getLogger("monitor")


def _comun() -> argparse.ArgumentParser:
    base = argparse.ArgumentParser(add_help=False)
    base.add_argument("--config", default="monitor.toml", help="Ruta del TOML")
    base.add_argument("--verbose", action="store_true", help="Log detallado")
    return base


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="monitor", description="Monitor PortoCaribe")
    parser.add_argument("--version", action="version", version=f"monitor {__version__}")
    sub = parser.add_subparsers(dest="comando", required=True)
    comun = _comun()

    p_run = sub.add_parser("run", parents=[comun], help="Ejecuta una muestra")
    p_run.add_argument("--simulate", action="store_true", help="Genera datos simulados")
    p_run.add_argument("--dry-run", action="store_true", help="Solo muestra el plan")
    p_run.add_argument("--solo", default="", help="Módulos separados por coma")

    p_export = sub.add_parser("export", parents=[comun], help="Reconstruye el CSV del día")
    p_export.add_argument("--fecha", default="", help="YYYY-MM-DD (por defecto hoy)")

    p_rec = sub.add_parser("recolectar", parents=[comun], help="Trae snapshots por SSH")
    p_rec.add_argument("--host", default="", help="vm1, vm2 o vacío para todos")

    p_prune = sub.add_parser("prune", parents=[comun], help="Borra datos antiguos")
    p_prune.add_argument("--dias", type=int, default=0)

    sub.add_parser("validate", parents=[comun], help="Valida configuración")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        config = cargar_config(args.config)
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"Configuración inválida: {exc}", file=sys.stderr)
        return 2

    if args.comando == "validate":
        print(f"OK {config.ruta}")
        print(f"Datos: {config.datos}")
        print("Módulos: " + ", ".join(
            nombre for nombre in ("camaras", "portal", "base_datos", "voip", "qos", "seguridad", "dhcp")
            if config.modulo_habilitado(nombre)
        ))
        return 0

    if args.comando == "run":
        solo = {x.strip() for x in args.solo.split(",") if x.strip()}
        return ejecutar(config, simular=args.simulate, solo=solo or None, dry_run=args.dry_run)

    if args.comando == "export":
        fecha = args.fecha or datetime.now().strftime("%Y-%m-%d")
        try:
            ruta, filas = exportar_csv(fecha, config)
        except OSError as exc:
            print(f"No se pudo exportar: {exc}", file=sys.stderr)
            return 2
        print(f"CSV: {ruta} ({filas} filas)")
        return 0

    if args.comando == "recolectar":
        errores = recolectar(config, args.host or None)
        for error in errores:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"Snapshots en {config.datos / 'entradas'}")
        return 1 if errores else 0

    if args.comando == "prune":
        eliminados = podar(config, args.dias or None)
        print(f"Eliminados: {len(eliminados)}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())

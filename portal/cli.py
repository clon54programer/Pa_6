"""Punto de entrada de línea de comandos del portal."""

from __future__ import annotations

import argparse
import logging
import sys

from . import __version__
from .app import Servidor
from .config import cargar_config
from .datos import BaseDatos


def _configurar_logs(nivel: str) -> None:
    logging.basicConfig(
        level=getattr(logging, nivel.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main(argv: list[str] | None = None) -> int:
    analizador = argparse.ArgumentParser(
        prog="portal", description="Portal de Clientes PortoCaribe (demostración)"
    )
    analizador.add_argument("--config", default="portal.toml", help="Ruta del archivo TOML")
    analizador.add_argument("--check", action="store_true", help="Valida configuración y base de datos")
    analizador.add_argument("--seed", action="store_true", help="Crea/actualiza los datos de demostración")
    analizador.add_argument("--version", action="version", version=f"portal {__version__}")
    argumentos = analizador.parse_args(argv)

    _configurar_logs("INFO")

    try:
        config = cargar_config(argumentos.config)
    except FileNotFoundError:
        print(f"No existe el archivo de configuración: {argumentos.config}", file=sys.stderr)
        return 2
    except (ValueError, OSError) as exc:
        print(f"Configuración inválida: {exc}", file=sys.stderr)
        return 2

    if argumentos.check or argumentos.seed:
        try:
            base = BaseDatos(config.portal.base_datos)
            base.inicializar()
            base.sembrar()
        except OSError as exc:
            print(f"No se pudo preparar la base de datos: {exc}", file=sys.stderr)
            return 2
        print(f"Configuración válida. Base de datos: {config.portal.base_datos}")
        print("Usuario demo: cliente.demo / Porto2026*")
        return 0

    try:
        servidor = Servidor(config)
    except OSError as exc:
        print(f"No se pudo iniciar el servidor: {exc}", file=sys.stderr)
        return 1

    print(f"Portal en http://{config.servidor.host}:{servidor.puerto}")
    print("Usuario demo: cliente.demo / Porto2026*")
    try:
        servidor.servir()
    except KeyboardInterrupt:
        print("\nDeteniendo el portal…")
    finally:
        servidor.detener()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

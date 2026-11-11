"""Persistencia JSONL, exportación CSV y retención."""

from __future__ import annotations

import csv
import gzip
import json
import os
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import Config
from .modelos import CAMPOS_CSV, Resultado, deduplicar


def _raw_dir(config: Config, fecha: str) -> Path:
    return config.datos / "raw" / fecha


def _archivos_jsonl(directorio: Path) -> list[Path]:
    """JSONL sueltos y comprimidos, en orden estable."""
    return sorted(list(directorio.glob("*.jsonl")) + list(directorio.glob("*.jsonl.gz")))


def _abrir(archivo: Path):
    if archivo.suffix == ".gz":
        return gzip.open(archivo, "rt", encoding="utf-8")
    return archivo.open("r", encoding="utf-8")


def escribir_jsonl(resultados: list[Resultado], config: Config, inicio: datetime) -> Path:
    fecha = inicio.strftime("%Y-%m-%d")
    directorio = _raw_dir(config, fecha)
    directorio.mkdir(parents=True, exist_ok=True)
    nombre = f"{inicio.strftime('%H%M%S')}_{resultados[0].run_id if resultados else 'sin-datos'}.jsonl"
    destino = directorio / nombre
    temporal = destino.with_suffix(".jsonl.tmp")
    with temporal.open("w", encoding="utf-8") as manejador:
        for resultado in resultados:
            manejador.write(json.dumps(resultado.a_dict(), ensure_ascii=False) + "\n")
        manejador.flush()
        os.fsync(manejador.fileno())
    os.replace(temporal, destino)
    return destino


def exportar_csv(fecha: str, config: Config) -> tuple[Path, int]:
    directorio = _raw_dir(config, fecha)
    archivos = _archivos_jsonl(directorio)
    resultados: list[Resultado] = []
    for archivo in archivos:
        with _abrir(archivo) as manejador:
            for linea in manejador:
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    datos = json.loads(linea)
                except json.JSONDecodeError:
                    continue
                campos = {campo: datos.get(campo) for campo in CAMPOS_CSV}
                if not datos.get("huella"):
                    continue
                resultados.append(Resultado(**campos, huella=datos["huella"]))
    resultados = deduplicar(resultados)
    resultados.sort(key=lambda r: (r.timestamp_utc, r.modulo, r.recurso_target))

    salida = config.datos / "csv" / f"metricas_{fecha}.csv"
    salida.parent.mkdir(parents=True, exist_ok=True)
    temporal = salida.with_suffix(".csv.tmp")
    with temporal.open("w", encoding=config.salida.get("codificacion", "utf-8-sig"), newline="") as manejador:
        escritor = csv.DictWriter(manejador, fieldnames=CAMPOS_CSV, extrasaction="ignore")
        escritor.writeheader()
        for resultado in resultados:
            escritor.writerow(resultado.a_csv())
    os.replace(temporal, salida)
    return salida, len(resultados)


def _comprimir_jsonl(directorio: Path) -> list[Path]:
    """Comprime los JSONL del día y elimina el original (idempotente)."""
    comprimidos: list[Path] = []
    for archivo in directorio.glob("*.jsonl"):
        destino = archivo.with_suffix(archivo.suffix + ".gz")
        if destino.exists():
            archivo.unlink(missing_ok=True)
            continue
        temporal = destino.with_suffix(".gz.tmp")
        with archivo.open("rb") as origen, gzip.open(temporal, "wb", compresslevel=6) as salida:
            shutil.copyfileobj(origen, salida)
        os.replace(temporal, destino)
        archivo.unlink(missing_ok=True)
        comprimidos.append(destino)
    return comprimidos


def podar(config: Config, dias: int | None = None, comprimir_dias: int | None = None) -> list[Path]:
    """Borra lo que excede la retención y comprime los JSONL antiguos."""
    limite = date.today() - timedelta(days=int(dias or config.general["retencion_dias"]))
    comprimir = int(
        comprimir_dias
        if comprimir_dias is not None
        else config.general.get("comprimir_dias", 7)
    )
    limite_compresion = date.today() - timedelta(days=comprimir)
    eliminados: list[Path] = []
    raw = config.datos / "raw"
    if raw.is_dir():
        for directorio in raw.iterdir():
            try:
                fecha = datetime.strptime(directorio.name, "%Y-%m-%d").date()
            except ValueError:
                continue
            if fecha < limite:
                shutil.rmtree(directorio, ignore_errors=True)
                eliminados.append(directorio)
            elif fecha < limite_compresion:
                for archivo in _comprimir_jsonl(directorio):
                    eliminados.append(archivo)
    csv_dir = config.datos / "csv"
    if csv_dir.is_dir():
        for archivo in csv_dir.glob("metricas_*.csv"):
            try:
                fecha = datetime.strptime(archivo.stem.replace("metricas_", ""), "%Y-%m-%d").date()
            except ValueError:
                continue
            if fecha < limite:
                archivo.unlink(missing_ok=True)
                eliminados.append(archivo)
    return eliminados

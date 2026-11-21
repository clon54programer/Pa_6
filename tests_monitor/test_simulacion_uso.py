"""Pruebas del generador de simulación de uso (``simulacion_monitor.py``).

Cubren el modo ``dataset``: esquema CSV v1, JSONL por muestra, reporte,
determinismo con la misma semilla, incidentes y las salvaguardas de rutas.
El modo ``demo`` se prueba aparte con una corrida real del CLI.
"""

from __future__ import annotations

import contextlib
import csv
import io
import shutil
import sys
import unittest
import uuid
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import simulacion_monitor  # noqa: E402

CONFIG = RAIZ / "monitor.toml"
# El sandbox de escritura solo permite crear subdirectorios dentro del repo.
BASE_TEMPORAL = RAIZ / ".tmp"
BASE_TEMPORAL.mkdir(parents=True, exist_ok=True)


@contextlib.contextmanager
def _temporal():
    """Directorio temporal en el workspace (``tempfile`` usa 0o700 y el sandbox lo niega)."""
    ruta = BASE_TEMPORAL / f"caso_{uuid.uuid4().hex[:10]}"
    ruta.mkdir()
    try:
        yield str(ruta)
    finally:
        shutil.rmtree(ruta, ignore_errors=True)


def _ejecutar(*argumentos: str) -> tuple[int, str]:
    salida = io.StringIO()
    with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(salida):
        codigo = simulacion_monitor.main(list(argumentos))
    return codigo, salida.getvalue()


def _csv(directorio: Path) -> list[dict]:
    archivos = list((directorio / "csv").glob("metricas_*.csv"))
    if not archivos:
        raise AssertionError(f"sin CSV en {directorio}")
    with archivos[0].open(encoding="utf-8-sig", newline="") as manejador:
        return list(csv.DictReader(manejador))


class DatasetTest(unittest.TestCase):
    def test_genera_csv_jsonl_y_reporte(self) -> None:
        with _temporal() as tmp:
            codigo, salida = _ejecutar(
                "dataset", "--config", str(CONFIG), "--salida", tmp,
                "--desde", "2026-11-20 00:00", "--horas", "1", "--paso", "600",
                "--semilla", "7", "--sin-incidentes",
            )
            self.assertEqual(codigo, 0, salida)

            filas = _csv(Path(tmp))
            self.assertGreater(len(filas), 0)
            self.assertEqual(len(filas[0]), len(simulacion_monitor.CAMPOS_CSV))
            self.assertTrue(all(fila["fuente"] == "simulado" for fila in filas))
            self.assertTrue(all(fila["schema_version"] == "1" for fila in filas))

            self.assertEqual(len(list((Path(tmp) / "raw").rglob("*.jsonl"))), 6)
            reportes = list(Path(tmp).glob("reporte_uso_*.md"))
            self.assertEqual(len(reportes), 1)
            texto = reportes[0].read_text(encoding="utf-8")
            self.assertIn("fuente=simulado", texto)
            self.assertIn("Linea de tiempo", texto)

    def test_misma_semilla_produce_el_mismo_csv(self) -> None:
        with _temporal() as uno, _temporal() as otro:
            for destino in (uno, otro):
                codigo, salida = _ejecutar(
                    "dataset", "--config", str(CONFIG), "--salida", destino,
                    "--desde", "2026-11-20 06:00", "--horas", "2", "--paso", "900",
                    "--semilla", "42",
                )
                self.assertEqual(codigo, 0, salida)
            self.assertEqual(
                (Path(uno) / "csv" / "metricas_2026-11-20.csv").read_bytes(),
                (Path(otro) / "csv" / "metricas_2026-11-20.csv").read_bytes(),
            )

    def test_incidentes_dejan_problemas_y_aparecen_en_el_reporte(self) -> None:
        with _temporal() as tmp:
            codigo, salida = _ejecutar(
                "dataset", "--config", str(CONFIG), "--salida", tmp,
                "--desde", "2026-11-20 00:00", "--horas", "12", "--paso", "300",
                "--semilla", "20261121",
            )
            self.assertEqual(codigo, 0, salida)
            filas = _csv(Path(tmp))
            self.assertTrue(
                any(fila["estado"] in {"ERROR", "DEGRADED", "OFFLINE"} for fila in filas)
            )
            reporte = next(Path(tmp).glob("reporte_uso_*.md")).read_text(encoding="utf-8")
            self.assertIn("Incidentes simulados", reporte)
            self.assertIn("portal_lento", reporte)

    def test_solo_con_modulo_deshabilitado_falla(self) -> None:
        with _temporal() as tmp:
            codigo, salida = _ejecutar(
                "dataset", "--config", str(CONFIG), "--salida", tmp,
                "--horas", "1", "--paso", "600", "--solo", "qos",
            )
            self.assertEqual(codigo, 2)
            self.assertIn("No hay modulos habilitados", salida)

    def test_no_sobrescribe_los_datos_reales(self) -> None:
        config = simulacion_monitor.cargar_config(CONFIG)
        codigo, salida = _ejecutar(
            "dataset", "--config", str(CONFIG), "--salida", str(config.datos),
            "--horas", "1", "--paso", "600",
        )
        self.assertEqual(codigo, 2)
        self.assertIn("directorio de datos real", salida)

    def test_demo_tampoco_usa_los_datos_reales(self) -> None:
        config = simulacion_monitor.cargar_config(CONFIG)
        codigo, salida = _ejecutar(
            "demo", "--config", str(CONFIG), "--salida", str(config.datos),
        )
        self.assertEqual(codigo, 2)
        self.assertIn("directorio de datos real", salida)


class MenoresTest(unittest.TestCase):
    def test_parsear_desde(self) -> None:
        from zoneinfo import ZoneInfo

        zona = ZoneInfo("America/Bogota")
        self.assertEqual(simulacion_monitor._parsear_desde("2026-11-20", zona).hour, 0)
        self.assertEqual(
            simulacion_monitor._parsear_desde("2026-11-20 07:30", zona).minute, 30
        )
        with self.assertRaises(ValueError):
            simulacion_monitor._parsear_desde("20/11/2026", zona)

    def test_p95(self) -> None:
        self.assertEqual(simulacion_monitor._p95([]), 0.0)
        self.assertEqual(simulacion_monitor._p95([10.0]), 10.0)
        self.assertAlmostEqual(simulacion_monitor._p95(list(range(1, 101))), 95.0)

    def test_config_aislada_solo_cambia_el_directorio(self) -> None:
        config = simulacion_monitor.cargar_config(CONFIG)
        destino = simulacion_monitor._config_aislada(config, Path("/tmp/demo"))
        try:
            texto = destino.read_text(encoding="utf-8")
            self.assertEqual(destino.name, "monitor.demo.toml")
            self.assertIn('directorio_datos = "/tmp/demo"', texto)
            self.assertIn("[general]", texto)
            self.assertIn("[portal]", texto)
        finally:
            destino.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from monitor.config import cargar_config
from monitor.escritura import exportar_csv
from monitor.runner import ejecutar


class RunnerSimuladoTest(unittest.TestCase):
    def setUp(self):
        self._temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporal.cleanup)
        self.config = cargar_config("monitor.toml")
        self.config.general["directorio_datos"] = self._temporal.name
        self.config.recoleccion["habilitado"] = False
        self.config.qos["habilitado"] = False

    def _jsonl(self):
        return list((Path(self._temporal.name) / "raw").rglob("*.jsonl"))

    def test_corrida_completa(self):
        codigo = ejecutar(self.config, simular=True)
        self.assertEqual(codigo, 0)
        archivos = self._jsonl()
        self.assertEqual(len(archivos), 1)
        filas = [json.loads(linea) for linea in archivos[0].read_text(encoding="utf-8").splitlines() if linea]
        self.assertEqual(len(filas), 14)
        self.assertEqual({fila["modulo"] for fila in filas},
                         {"Camaras", "PortalWeb", "BaseDatos", "VoIP", "Seguridad", "DHCP"})
        self.assertTrue(all(fila["run_id"].startswith("sim-") for fila in filas))

        fecha = datetime.now().strftime("%Y-%m-%d")
        _, total = exportar_csv(fecha, self.config)
        self.assertEqual(total, 14)

    def test_solo_camaras(self):
        codigo = ejecutar(self.config, simular=True, solo={"camaras"})
        self.assertEqual(codigo, 0)
        archivos = self._jsonl()
        filas = [json.loads(linea) for linea in archivos[0].read_text(encoding="utf-8").splitlines() if linea]
        self.assertEqual(len(filas), 2)
        self.assertTrue(all(fila["modulo"] == "Camaras" for fila in filas))

    def test_dry_run(self):
        codigo = ejecutar(self.config, simular=True, dry_run=True)
        self.assertEqual(codigo, 0)
        self.assertEqual(self._jsonl(), [])


if __name__ == "__main__":
    unittest.main()

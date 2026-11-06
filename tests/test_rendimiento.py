import tempfile
import unittest
from pathlib import Path

from portal.datos import BaseDatos
from portal.rendimiento import Medidor


class RendimientoTest(unittest.TestCase):
    def setUp(self):
        self._temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporal.cleanup)
        self.ruta = Path(self._temporal.name) / "portal.db"
        base = BaseDatos(self.ruta)
        base.inicializar()

    def test_medicion_servidor(self):
        medidor = Medidor(self.ruta)
        datos = medidor.medir()
        self.assertEqual(datos["fuente"], "servidor")
        self.assertIn(datos["estado"], ("OK", "DEGRADED"))
        self.assertGreaterEqual(datos["latencia_ms"], 0)
        self.assertEqual(medidor.ultimo(), datos)

    def test_fallback_simulado(self):
        medidor = Medidor(Path(self._temporal.name) / "sin" / "carpeta" / "portal.db")
        datos = medidor.medir()
        self.assertEqual(datos["fuente"], "simulado")
        self.assertGreaterEqual(datos["latencia_ms"], 250)
        self.assertLessEqual(datos["latencia_ms"], 800)


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import datetime

from monitor.modelos import CAMPOS_CSV, Resultado


class ModelosTest(unittest.TestCase):
    def test_columnas_csv(self):
        self.assertEqual(len(CAMPOS_CSV), 27)
        self.assertEqual(CAMPOS_CSV[0], "timestamp")
        self.assertEqual(CAMPOS_CSV[-1], "schema_version")
        self.assertNotIn("huella", CAMPOS_CSV)

    def test_crear_metrica(self):
        resultado = Resultado.crear("run1", "Camaras", "10.0.0.1", "ONLINE", "ping", "America/Bogota",
                                    tiempo_respuesta_ms=1.5)
        self.assertEqual(resultado.estado, "ONLINE")
        self.assertEqual(len(resultado.huella), 64)
        self.assertRegex(resultado.timestamp, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
        self.assertIsNotNone(resultado.timestamp_utc)

    def test_huella_metrica_cambia_por_corrida(self):
        a = Resultado.crear("run1", "Camaras", "10.0.0.1", "ONLINE", "ping")
        b = Resultado.crear("run2", "Camaras", "10.0.0.1", "ONLINE", "ping")
        self.assertNotEqual(a.huella, b.huella)

    def test_huella_evento_estable(self):
        momento = datetime(2026, 11, 6, 12, 0, 0)
        a = Resultado.crear("run1", "Seguridad", "10.0.0.2", "DROPPED", "archivo",
                            timestamp_evento=momento, linea_evento="linea-1")
        b = Resultado.crear("run2", "Seguridad", "10.0.0.2", "DROPPED", "archivo",
                            timestamp_evento=momento, linea_evento="linea-1")
        self.assertEqual(a.huella, b.huella)


if __name__ == "__main__":
    unittest.main()

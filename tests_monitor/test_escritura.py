import csv
import hashlib
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from monitor.config import cargar_config
from monitor.escritura import escribir_jsonl, exportar_csv
from monitor.modelos import CAMPOS_CSV, Resultado


class EscrituraTest(unittest.TestCase):
    def setUp(self):
        self._temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporal.cleanup)
        self.config = cargar_config("monitor.toml")
        self.config.general["directorio_datos"] = self._temporal.name

    def test_jsonl_csv_e_idempotencia(self):
        inicio = datetime.now()
        fila = Resultado.crear("run1", "Camaras", "10.0.0.1", "ONLINE", "ping",
                               tiempo_respuesta_ms=2.5, perdida_paquetes_pct=0.0)
        archivo = escribir_jsonl([fila, fila], self.config, inicio)
        self.assertTrue(archivo.is_file())
        self.assertEqual(len(archivo.read_text(encoding="utf-8").splitlines()), 2)

        fecha = inicio.strftime("%Y-%m-%d")
        salida, filas = exportar_csv(fecha, self.config)
        self.assertEqual(filas, 1)
        self.assertTrue(salida.is_file())
        contenido = salida.read_bytes()
        self.assertTrue(contenido.startswith(b"\xef\xbb\xbf"))

        with salida.open(encoding="utf-8-sig", newline="") as manejador:
            lector = csv.DictReader(manejador)
            self.assertEqual(lector.fieldnames, CAMPOS_CSV)
            datos = list(lector)
        self.assertEqual(datos[0]["modulo"], "Camaras")
        self.assertEqual(datos[0]["estado"], "ONLINE")

        primero = hashlib.sha256(salida.read_bytes()).hexdigest()
        exportar_csv(fecha, self.config)
        segundo = hashlib.sha256(salida.read_bytes()).hexdigest()
        self.assertEqual(primero, segundo)


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from datetime import date

from portal.datos import BaseDatos, digito_verificador, es_numero_iso, normalizar_consulta


class DatosTest(unittest.TestCase):
    def setUp(self):
        self._temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporal.cleanup)
        self.db = BaseDatos(f"{self._temporal.name}/portal.db")
        self.db.inicializar()
        self.db.sembrar(fecha_base=date(2026, 11, 6))

    def test_digito_verificador_iso(self):
        self.assertEqual(digito_verificador("CSQU305438"), 3)
        self.assertTrue(es_numero_iso("CSQU3054383"))
        self.assertFalse(es_numero_iso("CSQU3054384"))
        self.assertFalse(es_numero_iso("NO-ES-UN-NUMERO"))

    def test_normalizar_consulta(self):
        self.assertEqual(normalizar_consulta("  csqu 3054383 "), "CSQU 3054383")

    def test_buscar_por_numero(self):
        datos = self.db.buscar_contenedor("CSQU3054383")
        self.assertIsNotNone(datos)
        self.assertEqual(datos["contenedor"]["bl"], "BL-2026-001")
        self.assertGreaterEqual(len(datos["hitos"]), 6)

    def test_buscar_por_bl_y_orden(self):
        por_bl = self.db.buscar_contenedor("BL-2026-001")
        por_orden = self.db.buscar_contenedor("OD-2026-001")
        self.assertIsNotNone(por_bl)
        self.assertIsNotNone(por_orden)
        self.assertEqual(por_bl["contenedor"]["numero"], por_orden["contenedor"]["numero"])

    def test_busqueda_inexistente(self):
        self.assertIsNone(self.db.buscar_contenedor("CSQU0000000"))

    def test_avisos_vigentes(self):
        avisos = self.db.listar_avisos(date(2026, 11, 6))
        self.assertEqual(len(avisos), 3)
        self.assertEqual(avisos[0]["severidad"], "critico")

    def test_usuario_sembrado(self):
        usuario = self.db.obtener_usuario("cliente.demo")
        self.assertIsNotNone(usuario)
        self.assertEqual(usuario["nombre"], "Cliente de demostración")


if __name__ == "__main__":
    unittest.main()

import threading
import time
import unittest
from datetime import date, timedelta
from pathlib import Path

from monitor import runner, seguridad, sondas
from monitor.config import cargar_config
from monitor.escritura import exportar_csv, podar
from monitor.modelos import Resultado
from monitor.reintentos import intentar


class LeasesTest(unittest.TestCase):
    """Las renovaciones repiten el bloque del mismo IP; debe contarse una vez."""

    TEXTO = (
        "lease 10.30.60.100 {\n  binding state active;\n}\n"
        "lease 10.30.60.100 {\n  binding state active;\n}\n"
        "lease 10.30.60.101 {\n  binding state active;\n}\n"
        "lease 10.30.60.102 {\n  binding state free;\n}\n"
    )

    def test_dedupe_por_ip(self):
        self.assertEqual(sondas.leases_activos(self.TEXTO), 2)
        self.assertEqual(seguridad.parse_leases(self.TEXTO), 2)

    def test_sin_leases(self):
        self.assertEqual(sondas.leases_activos("sin datos"), 0)


class ReintentosTest(unittest.TestCase):
    def test_dos_intentos_con_backoff(self):
        llamadas = []
        esperas = []

        def falla():
            llamadas.append(1)
            raise OSError("timeout transitorio")

        with self.assertRaises(OSError):
            intentar(falla, intentos=2, dormir=esperas.append, aleatorio=lambda a, b: 0.0)
        self.assertEqual(len(llamadas), 2)
        self.assertEqual(len(esperas), 1)
        self.assertAlmostEqual(esperas[0], 0.5)

    def test_segundo_intento_ok(self):
        llamadas = []

        def a_veces():
            llamadas.append(1)
            if len(llamadas) == 1:
                raise TimeoutError("primero falla")
            return "ok"

        self.assertEqual(intentar(a_veces, intentos=2, dormir=lambda s: None, aleatorio=lambda a, b: 0.0), "ok")
        self.assertEqual(len(llamadas), 2)

    def test_tres_intentos_espera_creciente(self):
        esperas = []

        def falla():
            raise OSError("x")

        with self.assertRaises(OSError):
            intentar(falla, intentos=3, dormir=esperas.append, aleatorio=lambda a, b: 0.0)
        self.assertEqual(esperas, [0.5, 1.0])

    def test_error_no_transitorio_no_se_reintenta(self):
        llamadas = []

        def falla():
            llamadas.append(1)
            raise ValueError("configuración")

        with self.assertRaises(ValueError):
            intentar(falla, intentos=3, errores=(OSError,), dormir=lambda s: None)
        self.assertEqual(len(llamadas), 1)


class EscrituraGzipTest(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporal.cleanup)
        self.config = cargar_config("monitor.toml")
        self.config.general["directorio_datos"] = self._temporal.name

    def _escribir_dia(self, fecha: str, filas: int = 2):
        directorio = Path(self._temporal.name) / "raw" / fecha
        directorio.mkdir(parents=True)
        resultados = [
            Resultado.crear("run-1", "PortalWeb", f"host-{i}", "OK", "prueba") for i in range(filas)
        ]
        with (directorio / "120000_run-1.jsonl").open("w", encoding="utf-8") as manejador:
            for resultado in resultados:
                manejador.write(__import__("json").dumps(resultado.a_dict()) + "\n")
        return directorio

    def test_podar_comprime_jsonl_antiguo(self):
        fecha = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
        directorio = self._escribir_dia(fecha)
        eliminados = podar(self.config, comprimir_dias=7)
        self.assertTrue(list(directorio.glob("*.jsonl.gz")))
        self.assertFalse(list(directorio.glob("*.jsonl")))
        self.assertTrue(eliminados)

    def test_export_lee_gzip(self):
        fecha = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
        self._escribir_dia(fecha)
        podar(self.config, comprimir_dias=7)
        _ruta, filas = exportar_csv(fecha, self.config)
        self.assertEqual(filas, 2)

    def test_podar_borra_fuera_de_retencion(self):
        fecha = (date.today() - timedelta(days=200)).strftime("%Y-%m-%d")
        directorio = self._escribir_dia(fecha)
        podar(self.config, dias=180)
        self.assertFalse(directorio.exists())


class DeadlineTest(unittest.TestCase):
    def tearDown(self):
        runner._PARADA.clear()

    def test_envolver_agotado(self):
        tarea = runner._envolver("X", "y", lambda: [], time.monotonic() - 1)
        with self.assertRaises(runner.CorridaInterrumpida):
            tarea()

    def test_envolver_parada(self):
        runner._PARADA.set()
        tarea = runner._envolver("X", "y", lambda: [], time.monotonic() + 60)
        with self.assertRaises(runner.CorridaInterrumpida):
            tarea()
        self.assertTrue(runner._PARADA.is_set())

    def test_manejadores_en_hilo_secundario_no_fallan(self):
        hilo = threading.Thread(target=runner._instalar_manejadores)
        hilo.start()
        hilo.join()
        self.assertFalse(hilo.is_alive())


if __name__ == "__main__":
    unittest.main()

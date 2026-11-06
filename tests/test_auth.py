import tempfile
import unittest
from datetime import date

from portal.auth import Autenticacion
from portal.datos import BaseDatos
from tests.helpers import config_prueba


class Reloj:
    def __init__(self, inicial: float = 1_000_000.0):
        self.valor = inicial

    def __call__(self) -> float:
        return self.valor

    def avanzar(self, segundos: float) -> None:
        self.valor += segundos


class AutenticacionTest(unittest.TestCase):
    def setUp(self):
        self._temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporal.cleanup)
        self.config = config_prueba(self._temporal.name)
        self.db = BaseDatos(self.config.portal.base_datos)
        self.db.inicializar()
        self.db.sembrar(fecha_base=date(2026, 11, 6))
        self.reloj = Reloj()
        self.auth = Autenticacion(self.db, self.config, ahora=self.reloj)

    def test_login_correcto(self):
        resultado = self.auth.intentar_login("cliente.demo", "Porto2026*", "10.0.0.1")
        self.assertTrue(resultado["ok"])
        sesion = resultado["sesion"]
        self.assertEqual(sesion.usuario, "cliente.demo")
        self.assertIsNotNone(self.auth.obtener_sesion(sesion.sid))

    def test_cinco_fallos_bloquean(self):
        for _ in range(5):
            resultado = self.auth.intentar_login("cliente.demo", "incorrecta", "10.0.0.2")
            self.assertFalse(resultado["ok"])
            self.assertEqual(resultado["codigo"], "CREDENCIALES")

        self.assertGreater(self.auth.bloqueo_restante("10.0.0.2", "cliente.demo"), 0)
        bloqueado = self.auth.intentar_login("cliente.demo", "Porto2026*", "10.0.0.2")
        self.assertFalse(bloqueado["ok"])
        self.assertEqual(bloqueado["codigo"], "BLOQUEADO")
        self.assertGreater(bloqueado["retry_after_s"], 0)

    def test_desbloqueo_al_expirar(self):
        for _ in range(5):
            self.auth.intentar_login("cliente.demo", "incorrecta", "10.0.0.3")
        self.reloj.avanzar(self.config.seguridad.bloqueo_s + 1)
        resultado = self.auth.intentar_login("cliente.demo", "Porto2026*", "10.0.0.3")
        self.assertTrue(resultado["ok"])
        self.assertEqual(self.auth.bloqueo_restante("10.0.0.3", "cliente.demo"), 0)

    def test_intentos_restantes(self):
        self.auth.intentar_login("cliente.demo", "incorrecta", "10.0.0.4")
        self.auth.intentar_login("cliente.demo", "incorrecta", "10.0.0.4")
        self.assertEqual(self.auth.intentos_restantes("10.0.0.4", "cliente.demo"), 3)

    def test_sesion_expira(self):
        resultado = self.auth.intentar_login("cliente.demo", "Porto2026*", "10.0.0.5")
        sid = resultado["sesion"].sid
        self.reloj.avanzar(self.config.portal.ttl_sesion_s + 1)
        self.assertIsNone(self.auth.obtener_sesion(sid))

    def test_csrf(self):
        resultado = self.auth.intentar_login("cliente.demo", "Porto2026*", "10.0.0.6")
        sesion = resultado["sesion"]
        self.assertTrue(self.auth.validar_csrf(sesion, sesion.csrf))
        self.assertFalse(self.auth.validar_csrf(sesion, "token-falso"))
        self.assertFalse(self.auth.validar_csrf(sesion, None))


if __name__ == "__main__":
    unittest.main()

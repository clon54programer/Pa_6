import tempfile
import unittest
from pathlib import Path

from monitor.config import cargar_config, validar


class ConfigTest(unittest.TestCase):
    def test_carga_monitor(self):
        config = cargar_config("monitor.toml")
        self.assertEqual(len(config.camaras["lista"]), 2)
        self.assertIn("vm1", config.recoleccion["hosts"])
        self.assertIn("vm2", config.recoleccion["hosts"])
        self.assertTrue(Path(config.datos).is_absolute())
        self.assertTrue(config.modulo_habilitado("camaras"))
        self.assertTrue(config.modulo_habilitado("portal"))

    def test_camara_invalida(self):
        texto = Path("monitor.toml").read_text(encoding="utf-8")
        texto = texto.replace('ip = "10.30.30.12"', 'ip = "no-es-ip"')
        with tempfile.TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "monitor.toml"
            ruta.write_text(texto, encoding="utf-8")
            with self.assertRaises(ValueError):
                cargar_config(ruta)

    def test_sin_modulos(self):
        config = cargar_config("monitor.toml")
        for nombre in ("camaras", "portal", "base_datos", "voip", "qos", "seguridad", "dhcp"):
            config.__dict__[nombre]["habilitado"] = False
        with self.assertRaises(ValueError):
            validar(config)


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from portal.app import CSP
from portal.config import ConfigTablero, _url_tablero, cargar_config
from tests.helpers import ServidorPrueba

URL_EMBED = (
    "https://app.powerbi.com/reportEmbed"
    "?reportId=d836d9b6-58c8-4ef0-967c-f5a3a6464ce2&autoAuth=true"
)
URL_PUBLICA = "https://app.powerbi.com/view?r=eyJrIjoiYWJjZGVm"


def _hay_zoneinfo() -> bool:
    try:
        ZoneInfo("America/Bogota")
    except ZoneInfoNotFoundError:
        return False
    return True


class UrlTableroTest(unittest.TestCase):
    """Reglas de validación del enlace, sin depender de tzdata."""

    def test_acepta_insertar_informe(self):
        self.assertEqual(_url_tablero(URL_EMBED, "tablero.url"), URL_EMBED)

    def test_acepta_publicar_en_la_web(self):
        self.assertEqual(_url_tablero(URL_PUBLICA, "tablero.url"), URL_PUBLICA)

    def test_rechaza_url_del_editor(self):
        with self.assertRaises(ValueError):
            _url_tablero(
                "https://app.powerbi.com/groups/me/reports/"
                "d836d9b6-58c8-4ef0-967c-f5a3a6464ce2/efd8baf7154cb1b0b4ac"
                "?experience=power-bi",
                "tablero.url",
            )

    def test_rechaza_host_http_y_faltantes(self):
        for url in (
            "https://ejemplo.example/reportEmbed?reportId=1",
            "http://app.powerbi.com/reportEmbed?reportId=1",
            "https://app.powerbi.com/reportEmbed",
            "https://app.powerbi.com/view?r=",
            "https://usuario:clave@app.powerbi.com/reportEmbed?reportId=1",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    _url_tablero(url, "tablero.url")


@unittest.skipUnless(_hay_zoneinfo(), "falta tzdata (pip install tzdata)")
class ConfigTableroTest(unittest.TestCase):
    def _cargar(self, toml: str):
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / "portal.toml"
            ruta.write_text(toml, encoding="utf-8")
            return cargar_config(ruta)

    def test_sin_seccion_queda_deshabilitado(self):
        config = self._cargar("[portal]\n")
        self.assertFalse(config.tablero.habilitado)
        self.assertEqual(config.tablero.url, "")

    def test_lee_el_enlace_habilitado(self):
        config = self._cargar(f'[tablero]\nhabilitado = true\nurl = "{URL_EMBED}"\n')
        self.assertTrue(config.tablero.habilitado)
        self.assertEqual(config.tablero.url, URL_EMBED)

    def test_habilitado_exige_url(self):
        with self.assertRaises(ValueError):
            self._cargar('[tablero]\nhabilitado = true\nurl = ""\n')

    def test_deshabilitado_ignora_url_vacia(self):
        config = self._cargar('[tablero]\nhabilitado = false\nurl = ""\n')
        self.assertFalse(config.tablero.habilitado)


class TableroAPITest(unittest.TestCase):
    def test_deshabilitado(self):
        servidor = ServidorPrueba()
        self.addCleanup(servidor.cerrar)
        status, _, datos = servidor.json("GET", "/api/tablero")
        self.assertEqual(status, 200)
        self.assertEqual(datos, {"habilitado": False, "url": None})

    def test_habilitado(self):
        servidor = ServidorPrueba(ConfigTablero(habilitado=True, url=URL_EMBED))
        self.addCleanup(servidor.cerrar)
        status, _, datos = servidor.json("GET", "/api/tablero")
        self.assertEqual(status, 200)
        self.assertEqual(datos, {"habilitado": True, "url": URL_EMBED})

    def test_metodo_no_permitido(self):
        servidor = ServidorPrueba()
        self.addCleanup(servidor.cerrar)
        status, _, datos = servidor.json("POST", "/api/tablero")
        self.assertEqual(status, 405)
        self.assertEqual(datos["error"]["codigo"], "METODO_NO_PERMITIDO")

    def test_csp_permite_el_marco_de_power_bi(self):
        self.assertIn("frame-src https://app.powerbi.com", CSP)
        self.assertIn("frame-ancestors 'none'", CSP)


if __name__ == "__main__":
    unittest.main()

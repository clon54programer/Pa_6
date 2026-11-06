import unittest

from tests.helpers import ServidorPrueba


class APITest(unittest.TestCase):
    def setUp(self):
        self.cliente = ServidorPrueba()
        self.addCleanup(self.cliente.cerrar)

    def _login(self):
        status, headers, datos, cookie = self.cliente.login()
        self.assertEqual(status, 200)
        self.assertIsNotNone(cookie)
        return headers, datos, cookie

    def test_sin_sesion(self):
        status, _, datos = self.cliente.json("GET", "/api/track?q=CSQU3054383")
        self.assertEqual(status, 401)
        self.assertEqual(datos["error"]["codigo"], "NO_AUTENTICADO")

    def test_login_y_cookie(self):
        headers, datos, _ = self._login()
        self.assertIn("csrf", datos)
        cookie = headers.get("set-cookie", "")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)

    def test_sesion_autenticada(self):
        _, datos, cookie = self._login()
        status, _, sesion = self.cliente.json("GET", "/api/sesion", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertTrue(sesion["autenticado"])
        self.assertEqual(sesion["usuario"], "cliente.demo")
        self.assertEqual(sesion["csrf"], datos["csrf"])

    def test_consultar_por_numero_bl_y_orden(self):
        _, _, cookie = self._login()
        for consulta, campo in (
            ("CSQU3054383", "numero"),
            ("BL-2026-001", "bl"),
            ("OD-2026-001", "orden"),
        ):
            status, _, datos = self.cliente.json(
                "GET", "/api/track?q=" + consulta, cookie=cookie
            )
            self.assertEqual(status, 200, consulta)
            self.assertEqual(datos["contenedor"]["numero"], "CSQU3054383")
            if campo != "numero":
                self.assertEqual(datos["contenedor"][campo], consulta)

    def test_contenedor_con_digito_invalido(self):
        _, _, cookie = self._login()
        status, _, datos = self.cliente.json("GET", "/api/track?q=CSQU3054384", cookie=cookie)
        self.assertEqual(status, 400)
        self.assertEqual(datos["error"]["codigo"], "CONTENEDOR_INVALIDO")

    def test_consulta_inexistente(self):
        _, _, cookie = self._login()
        status, _, datos = self.cliente.json("GET", "/api/track?q=CSQU0000001", cookie=cookie)
        self.assertEqual(status, 404)

    def test_avisos(self):
        _, _, cookie = self._login()
        status, _, datos = self.cliente.json("GET", "/api/avisos", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertEqual(len(datos["avisos"]), 3)

    def test_csrf_en_logout(self):
        _, datos, cookie = self._login()
        status, _, _ = self.cliente.json("POST", "/api/logout", cookie=cookie)
        self.assertEqual(status, 403)

        status, _, _ = self.cliente.json(
            "POST", "/api/logout", cabeceras={"X-CSRF-Token": datos["csrf"]}, cookie=cookie
        )
        self.assertEqual(status, 204)

        status, _, sesion = self.cliente.json("GET", "/api/sesion", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertFalse(sesion["autenticado"])

    def test_bloqueo_por_intentos(self):
        for _ in range(5):
            status, _, _ = self.cliente.json(
                "POST",
                "/api/login",
                {"usuario": "cliente.demo", "password": "incorrecta"},
            )
            self.assertEqual(status, 401)

        status, headers, datos = self.cliente.json(
            "POST",
            "/api/login",
            {"usuario": "cliente.demo", "password": "Porto2026*"},
        )
        self.assertEqual(status, 429)
        self.assertIn("retry-after", headers)
        self.assertGreaterEqual(datos["retry_after_s"], 1)

    def test_metodo_no_permitido(self):
        status, _, _ = self.cliente.json("POST", "/api/estado")
        self.assertEqual(status, 405)


if __name__ == "__main__":
    unittest.main()

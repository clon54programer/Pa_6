import unittest

from tests.helpers import ServidorPrueba


class EstaticosTest(unittest.TestCase):
    def setUp(self):
        self.cliente = ServidorPrueba()
        self.addCleanup(self.cliente.cerrar)

    def test_index(self):
        status, headers, cuerpo = self.cliente.peticion("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("content-type", ""))
        self.assertIn("PortoCaribe", cuerpo.decode("utf-8"))

    def test_cabeceras_de_seguridad(self):
        _, headers, _ = self.cliente.peticion("GET", "/")
        self.assertIn("default-src 'self'", headers.get("content-security-policy", ""))
        self.assertEqual(headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(headers.get("x-frame-options"), "DENY")
        self.assertEqual(headers.get("referrer-policy"), "no-referrer")

    def test_traversal(self):
        status, _, _ = self.cliente.peticion("GET", "/%2e%2e/%2e%2e/etc/passwd")
        self.assertEqual(status, 404)

    def test_archivo_inexistente(self):
        status, _, _ = self.cliente.peticion("GET", "/no-existe.html")
        self.assertEqual(status, 404)

    def test_api_inexistente(self):
        status, _, _ = self.cliente.peticion("GET", "/api/desconocido")
        self.assertEqual(status, 404)

    def test_head_sin_cuerpo(self):
        status, _, cuerpo = self.cliente.peticion("HEAD", "/")
        self.assertEqual(status, 200)
        self.assertEqual(cuerpo, b"")


if __name__ == "__main__":
    unittest.main()

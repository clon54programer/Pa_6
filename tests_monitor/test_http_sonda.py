import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from monitor.sondas import SondaError, http


class _Manejador(BaseHTTPRequestHandler):
    codigo = 200

    def do_GET(self):  # noqa: N802 - API de http.server
        cuerpo = b"ok"
        self.send_response(self.codigo)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, *_argumentos):
        pass


class SondaHTTPTest(unittest.TestCase):
    """Cubre la ruta http.client que el bug de producción dejó sin probar."""

    def _servidor(self, codigo=200):
        manejador = type("Manejador", (_Manejador,), {"codigo": codigo})
        servidor = ThreadingHTTPServer(("127.0.0.1", 0), manejador)
        hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
        hilo.start()
        self.addCleanup(servidor.shutdown)
        self.addCleanup(servidor.server_close)
        return f"http://127.0.0.1:{servidor.server_address[1]}/"

    def test_200(self):
        datos = http(self._servidor(200), timeout=5)
        self.assertEqual(datos["status"], 200)
        self.assertIn("HTTP 200", datos["detalle"])
        self.assertGreaterEqual(datos["total_ms"], datos["ttfb_ms"])

    def test_500_no_lanza(self):
        datos = http(self._servidor(500), timeout=5)
        self.assertEqual(datos["status"], 500)

    def test_puerto_cerrado(self):
        with self.assertRaises(SondaError):
            http("http://127.0.0.1:1/", timeout=1)

    def test_url_sin_host(self):
        with self.assertRaises(SondaError):
            http("http:///ruta", timeout=1)


if __name__ == "__main__":
    unittest.main()

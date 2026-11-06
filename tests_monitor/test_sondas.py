import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from monitor import seguridad, sondas


class SondasTest(unittest.TestCase):
    def test_ping_parsea_resumen(self):
        salida = (
            "4 packets transmitted, 4 received, 0% packet loss, time 3004ms\n"
            "rtt min/avg/max/mdev = 1.000/2.500/4.000/0.100 ms\n"
        )
        with mock.patch("monitor.sondas.shutil.which", return_value="ping"), mock.patch(
            "monitor.sondas.subprocess.run",
            return_value=SimpleNamespace(stdout=salida, stderr="", returncode=0),
        ):
            datos = sondas.ping("10.0.0.1", 4, 5)
        self.assertEqual(datos["recibidos"], 4)
        self.assertEqual(datos["perdida_pct"], 0.0)
        self.assertEqual(datos["rtt_ms"], 2.5)

    def test_iptables_y_delta(self):
        texto = (
            "[10:600] -A INPUT -s 10.30.30.50/32 -d 10.30.30.12/32 -p tcp --dport 554 -j DROP\n"
            "[5:300] -A INPUT -p tcp --dport 22 -j ACCEPT\n"
        )
        actual = seguridad.parse_iptables(texto)
        self.assertEqual(len(actual), 2)
        primera = next(iter(actual.values()))
        self.assertEqual(primera["src"], "10.30.30.50/32")
        self.assertEqual(seguridad.delta_iptables(actual, {})[0]["delta_pkts"], 10)
        anterior = {clave: {"pkts": datos["pkts"], "bytes": datos["bytes"]} for clave, datos in actual.items()}
        self.assertEqual(seguridad.delta_iptables(actual, anterior), [])

    def test_fail2ban(self):
        texto = "Currently banned: 2\nTotal banned: 8\nBanned IP list: 10.0.0.1 10.0.0.2\n"
        datos = seguridad.parse_fail2ban(texto)
        self.assertEqual(datos["actuales"], 2)
        self.assertEqual(datos["baneadas"], ["10.0.0.1", "10.0.0.2"])

    def test_auth(self):
        texto = (
            "2026-11-06T12:00:00-0500 vm2 sshd[1]: Failed password for root from 10.0.0.9 port 22 ssh2\n"
            "2026-11-06T12:01:00-0500 vm2 sshd[1]: Accepted password for root from 10.0.0.1 port 22 ssh2\n"
        )
        eventos = seguridad.parse_auth(texto)
        self.assertEqual(len(eventos), 1)
        self.assertEqual(eventos[0]["ip"], "10.0.0.9")
        self.assertIsNotNone(eventos[0]["ts"])

    def test_kern(self):
        texto = (
            "2026-11-06T12:00:00-0500 vm2 kernel: VLAN30-DROP: IN=eth1 SRC=10.30.30.50 "
            "DST=10.30.30.12 LEN=60 PROTO=TCP DPT=554\n"
        )
        eventos = seguridad.parse_kern(texto, ["VLAN30-DROP:"])
        self.assertEqual(eventos[0]["evento"], "VLAN30_BLOCKED")
        self.assertEqual(eventos[0]["src"], "10.30.30.50")
        self.assertEqual(eventos[0]["dport"], "554")

    def test_netstat(self):
        texto = (
            "TcpExt: SyncookiesSent ListenOverflows ListenDrops\n"
            "TcpExt: 0 3 4\n"
        )
        valores = seguridad.parse_netstat(texto)
        self.assertEqual(valores["ListenOverflows"], 3)
        self.assertEqual(valores["ListenDrops"], 4)

    def test_cdr(self):
        with tempfile.TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "cdr.csv"
            ruta.write_text(
                "uniqueid,start,duration,billsec,disposition,src,dst\n"
                f"abc,{datetime.now().strftime('%Y-%m-%d')} 10:00:00,60,42,ANSWERED,1001,2001\n",
                encoding="utf-8",
            )
            filas = sondas.cdr(str(ruta), "run1", "America/Bogota")
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0].sip_code, 200)
        self.assertEqual(filas[0].duracion_llamada_s, 42.0)
        self.assertEqual(filas[0].fuente, "asterisk-cdr")


if __name__ == "__main__":
    unittest.main()

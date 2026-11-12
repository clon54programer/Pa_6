#!/usr/bin/env python3
"""Prueba de login del portal desde el PC, sin dependencias externas.

    python portal-login.py [IP] [--usuario cliente.demo] [--password Porto2026*]

Verifica HTTPS, el login demo, la cookie de sesion y /api/estado.
"""

from __future__ import annotations

import argparse
import http.client
import json
import ssl


def main() -> int:
    parser = argparse.ArgumentParser(description="Login del portal PortoCaribe")
    parser.add_argument("ip", nargs="?", default="192.168.100.59")
    parser.add_argument("--usuario", default="cliente.demo")
    parser.add_argument("--password", default="Porto2026*")
    args = parser.parse_args()

    contexto = ssl._create_unverified_context()
    conexion = http.client.HTTPSConnection(args.ip, 443, timeout=10, context=contexto)

    conexion.request("GET", "/")
    respuesta = conexion.getresponse()
    print(f"GET /        -> {respuesta.status} {respuesta.getheader('Content-Type')}")
    respuesta.read()

    cuerpo = json.dumps({"usuario": args.usuario, "password": args.password})
    conexion.request("POST", "/api/login", cuerpo, {"Content-Type": "application/json"})
    respuesta = conexion.getresponse()
    print(f"POST login   -> {respuesta.status}")
    cookie = (respuesta.getheader("Set-Cookie") or "").split(";")[0]
    respuesta.read()
    if not cookie:
        print("Sin cookie de sesion: revise usuario/contrasena")
        return 1
    print(f"cookie       -> {cookie.split('=')[0]}=<valor> (Secure)")

    conexion.request("GET", "/api/estado", headers={"Cookie": cookie})
    respuesta = conexion.getresponse()
    datos = respuesta.read().decode("utf-8", "replace")
    print(f"GET /api/estado -> {respuesta.status} {datos[:120]}")
    conexion.close()
    return 0 if respuesta.status == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())

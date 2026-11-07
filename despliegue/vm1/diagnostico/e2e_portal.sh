#!/bin/bash
# Prueba funcional del portal a través de Apache (HTTPS), como un cliente real.
set -u
python3 - <<'PY'
import http.cookiejar, json, ssl, time, urllib.request

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
BASE = "https://127.0.0.1"
BASE_LAN = "https://192.168.137.54"

def cliente(base):
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=CTX),
        urllib.request.HTTPCookieProcessor(jar),
    ), jar

def get(op, url, timeout=10):
    t = time.perf_counter()
    r = op.open(url, timeout=timeout)
    cuerpo = r.read()
    return r.status, r.headers.get("Content-Type", ""), cuerpo, round((time.perf_counter() - t) * 1000, 1)

print("1) pagina principal")
op, jar = cliente(BASE)
st, ct, cuerpo, ms = get(op, BASE + "/")
print(f"   GET / -> {st} {ct} {len(cuerpo)}B {ms}ms")
print("   titulo:", "PortoCaribe" in cuerpo.decode("utf-8", "replace"))

print("2) estaticos")
for ruta, esperado in (("/css/estilos.css", "text/css"), ("/js/app.js", "javascript"),
                       ("/assets/logo.svg", "svg")):
    try:
        st, ct, cuerpo, ms = get(op, BASE + ruta)
        print(f"   {ruta} -> {st} {ct} {len(cuerpo)}B ({'ok' if esperado in ct else 'tipo inesperado'})")
    except Exception as exc:
        print(f"   {ruta} -> ERROR {exc}")

print("3) api publica")
for ruta in ("/api/sesion", "/api/avisos", "/api/estado"):
    try:
        st, ct, cuerpo, ms = get(op, BASE + ruta)
        print(f"   {ruta} -> {st} {ct} {cuerpo[:90]}")
    except urllib.error.HTTPError as exc:
        print(f"   {ruta} -> {exc.code} {exc.read()[:90]}")

print("4) login demo")
datos = json.dumps({"usuario": "cliente.demo", "password": "Porto2026*"}).encode()
req = urllib.request.Request(BASE + "/api/login", data=datos,
                             headers={"Content-Type": "application/json"})
r = op.open(req, timeout=10)
cuerpo = r.read()
print(f"   POST /api/login -> {r.status} {cuerpo[:120]}")
print("   cookies:", [(c.name, c.secure) for c in jar])
sesion = json.loads(cuerpo)
csrf = sesion.get("csrf")

print("5) api autenticada")
st, ct, cuerpo, ms = get(op, BASE + "/api/estado")
print(f"   GET /api/estado -> {st} {ct} {ms}ms {cuerpo[:150]}")
st, ct, cuerpo, ms = get(op, BASE + "/api/track?q=PC-2026-0001")
print(f"   GET /api/track -> {st} {cuerpo[:150]}")

print("6) logout con CSRF")
req = urllib.request.Request(BASE + "/api/logout", data=b"", method="POST",
                             headers={"X-CSRF-Token": csrf or ""})
try:
    r = op.open(req, timeout=10)
    print(f"   POST /api/logout -> {r.status}")
except urllib.error.HTTPError as exc:
    print(f"   POST /api/logout -> {exc.code} {exc.read()[:100]}")

print("7) mismo portal por la IP de LAN")
op2, _ = cliente(BASE_LAN)
st, ct, cuerpo, ms = get(op2, BASE_LAN + "/")
print(f"   GET {BASE_LAN}/ -> {st} {len(cuerpo)}B {ms}ms")
PY

#!/usr/bin/env python3
"""Simulación de uso del monitor PortoCaribe.

Dos modos, pensados para demostrar el monitor sin tocar la red:

``demo``
    Ejecuta el CLI tal como lo usaría un operador: ``validate``, ``run
    --dry-run``, varias corridas ``run --simulate`` (incluida una con
    ``--solo`` y otra con ``--json-logs``), dos ``export`` y la comprobación de
    que el CSV es idempotente (mismo SHA-256). Es una simulación de *uso*: no
    genera datos, recorre los comandos reales y sus salidas. Usa una copia del
    TOML que apunta a ``simulacion/demo``, así que no toca el dataset real.

``dataset``
    Genera un turno o un día completo de muestras sintéticas (JSONL del
    esquema v1, 27 columnas) con latencias variables e incidentes
    deterministas, y deja el CSV listo para Power BI. Reutiliza
    ``monitor.modelos`` y ``monitor.escritura``, así que el formato es
    exactamente el que produce una corrida real. Todas las filas llevan
    ``fuente = "simulado"``.

Solo biblioteca estándar, igual que ``monitor/``. En Windows hace falta
``tzdata`` (``python -m pip install tzdata``) para ``zoneinfo``.

Ejemplos::

    python simulacion_monitor.py demo --config monitor.toml
    python simulacion_monitor.py dataset --horas 24 --paso 300 --semilla 20261121
    python simulacion_monitor.py dataset --desde "2026-11-20 06:00" --horas 12 --sin-incidentes
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import time
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from monitor.config import Config, cargar_config  # noqa: E402
from monitor.escritura import escribir_jsonl, exportar_csv  # noqa: E402
from monitor.modelos import CAMPOS_CSV, Resultado  # noqa: E402

BANNER = "ENTORNO DE DEMOSTRACION - datos simulados (fuente=simulado)"
EXITO = {"ONLINE", "OK", "DROPPED"}
MODULOS = {
    "Camaras": "camaras",
    "PortalWeb": "portal",
    "BaseDatos": "base_datos",
    "VoIP": "voip",
    "QoS": "qos",
    "Seguridad": "seguridad",
    "DHCP": "dhcp",
}
DESCRIPCIONES = {
    "portal_lento": "Portal lento (latencia por encima del umbral de 10 s)",
    "portal_caido": "Portal caido (timeout al conectar)",
    "bd_caida": "PostgreSQL inaccesible para el monitor",
    "camara_offline": "Camara del muelle sin respuesta (OFFLINE)",
    "ssh_bruteforce": "Fuerza bruta SSH y ban de fail2ban",
    "vlan_ataque": "Trafico bloqueado VLAN 30/40 (contadores de iptables)",
    "dhcp_caida": "isc-dhcp-server detenido",
    "voip_caido": "Asterisk sin SIP ni AMI",
    "qos_degradado": "QoS degradado (perdida y jitter altos)",
    "sin_llamadas": "Franja sin llamadas (CDR SKIPPED)",
}

_RE_RUN = re.compile(r"run_id=(\S+) filas=(\d+) ok=(\d+) con_problema=(\d+) ntp=(\S+)")
_RE_CSV = re.compile(r"CSV: (.+) \((\d+) filas\)")
_RE_JSONL = re.compile(r"JSONL: (.+)")


# --------------------------------------------------------------------------- #
# Utilidades comunes
# --------------------------------------------------------------------------- #


def _entorno() -> dict[str, str]:
    entorno = dict(os.environ)
    entorno["PYTHONIOENCODING"] = "utf-8"
    return entorno


def _sha256(ruta: Path) -> str:
    digest = hashlib.sha256()
    with ruta.open("rb") as manejador:
        for bloque in iter(lambda: manejador.read(1 << 20), b""):
            digest.update(bloque)
    return digest.hexdigest()


def _csv_filas_columnas(ruta: Path) -> tuple[int, int]:
    with ruta.open("r", encoding="utf-8-sig", newline="") as manejador:
        lector = csv.reader(manejador)
        cabecera = next(lector, [])
        return sum(1 for _ in lector), len(cabecera)


def _imprimir_banner(config: Config, modo: str, datos: Path | None = None) -> None:
    print(BANNER)
    print(f"Modo: {modo} | config: {config.ruta}")
    print(f"Salida de datos: {datos or config.datos}")


def _config_aislada(config: Config, salida: Path) -> Path:
    """Copia el TOML al lado del original cambiando solo ``directorio_datos``.

    Al quedar en el mismo directorio, las rutas relativas (inventario, snapshots)
    siguen resolviéndose igual; la demo no toca el dataset real.
    """
    texto = config.ruta.read_text(encoding="utf-8")
    valor = salida.as_posix()
    patron = re.compile(r'(?m)^(\s*directorio_datos\s*=\s*)["\'][^"\']*["\']')
    if patron.search(texto):
        texto = patron.sub(lambda coincidencia: f'{coincidencia.group(1)}"{valor}"', texto, count=1)
    else:
        texto = texto.replace("[general]", f'[general]\ndirectorio_datos = "{valor}"', 1)
    destino = config.ruta.with_suffix(".demo.toml")
    try:
        destino.write_text(texto, encoding="utf-8")
        return destino
    except OSError:
        # Config en un directorio sin permiso de escritura (p. ej. /etc/monitor
        # como usuario no root): se usa el repositorio, que sí es escribible.
        respaldo = RAIZ / ".monitor.demo.toml"
        respaldo.write_text(texto, encoding="utf-8")
        return respaldo


# --------------------------------------------------------------------------- #
# Modo demo: recorrido del CLI como lo usaría un operador
# --------------------------------------------------------------------------- #


def demo(config: Config, args: argparse.Namespace) -> int:
    salida = Path(args.salida).expanduser()
    if not salida.is_absolute():
        salida = (RAIZ / salida).resolve()
    salida = salida.resolve()
    if salida == RAIZ:
        print("La salida de la demo no puede ser la raiz del repositorio", file=sys.stderr)
        return 2
    if salida == config.datos.resolve() and not args.forzar:
        print(
            "La salida es el directorio de datos real del monitor; usa otra ruta "
            "o --forzar si de verdad quieres borrar y mezclar la demo con el dataset real",
            file=sys.stderr,
        )
        return 2
    if not args.conservar:
        for sub in ("raw", "csv"):
            shutil.rmtree(salida / sub, ignore_errors=True)
    salida.mkdir(parents=True, exist_ok=True)

    try:
        ruta = _config_aislada(config, salida)
    except OSError as exc:
        print(f"Aviso: no se pudo aislar la salida ({exc}); se usara {config.ruta}")
        ruta = config.ruta
    try:
        return _demo(config, args, ruta, salida)
    finally:
        if ruta != config.ruta:
            ruta.unlink(missing_ok=True)


def _demo(config: Config, args: argparse.Namespace, cfg_ruta: Path, salida_demo: Path) -> int:
    _imprimir_banner(config, "demo del CLI", salida_demo)
    if cfg_ruta != config.ruta:
        print(f"Config aislada: {cfg_ruta}")
    print(f"Interprete: {sys.executable}\n")

    cfg = str(cfg_ruta)
    pasos: list[dict] = []
    corridas: list[dict] = []

    def correr(nombre: str, argumentos: list[str]) -> dict:
        comando = [sys.executable, "-m", "monitor", *argumentos]
        print(f"== {nombre} ==")
        print("   $ " + " ".join(comando))
        inicio = time.perf_counter()
        try:
            proceso = subprocess.run(
                comando,
                cwd=str(RAIZ),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
                env=_entorno(),
            )
            codigo = proceso.returncode
            salida = (proceso.stdout or "").strip()
            errores = (proceso.stderr or "").strip()
        except subprocess.TimeoutExpired:
            codigo, salida, errores = 124, "", "tiempo de espera agotado (600 s)"
        except OSError as exc:
            codigo, salida, errores = 125, "", str(exc)

        segundos = time.perf_counter() - inicio
        for linea in salida.splitlines():
            print("   " + linea)
        for linea in errores.splitlines():
            print("   ! " + linea)
        estado = "OK" if codigo == 0 else "FALLO"
        print(f"   -> rc={codigo} en {segundos:.2f} s [{estado}]\n")

        paso = {
            "nombre": nombre,
            "comando": " ".join(comando),
            "codigo": codigo,
            "segundos": segundos,
            "salida": salida,
            "errores": errores,
        }
        pasos.append(paso)
        return paso

    correr("validate", ["validate", "--config", cfg])
    correr("run --dry-run", ["run", "--config", cfg, "--dry-run"])

    for numero in range(max(1, args.corridas)):
        paso = correr(
            f"run --simulate ({numero + 1}/{max(1, args.corridas)})",
            ["run", "--config", cfg, "--simulate"],
        )
        coincidencia = _RE_RUN.search(paso["salida"])
        if coincidencia:
            corridas.append(
                {
                    "run_id": coincidencia.group(1),
                    "filas": int(coincidencia.group(2)),
                    "ok": int(coincidencia.group(3)),
                    "problema": int(coincidencia.group(4)),
                    "ntp": coincidencia.group(5),
                }
            )
            coincidencia_jsonl = _RE_JSONL.search(paso["salida"])
            if coincidencia_jsonl:
                corridas[-1]["jsonl"] = Path(coincidencia_jsonl.group(1).strip())

    solo = [nombre for nombre in ("portal", "base_datos") if config.modulo_habilitado(nombre)]
    if solo:
        correr(
            "run --simulate --solo " + ",".join(solo),
            ["run", "--config", cfg, "--simulate", "--solo", ",".join(solo)],
        )
    else:
        print("== run --simulate --solo ==")
        print("   (omitido: portal y base_datos estan deshabilitados)\n")

    correr("run --simulate --json-logs", ["run", "--config", cfg, "--simulate", "--json-logs"])

    primero = correr("export", ["export", "--config", cfg])
    coincidencia = _RE_CSV.search(primero["salida"])
    csv_ruta = Path(coincidencia.group(1).strip()) if coincidencia else None
    filas_csv = int(coincidencia.group(2)) if coincidencia else 0
    sha_1 = _sha256(csv_ruta) if csv_ruta and csv_ruta.is_file() else ""

    segundo = correr("export (repetido)", ["export", "--config", cfg])
    coincidencia = _RE_CSV.search(segundo["salida"])
    sha_2 = _sha256(csv_ruta) if csv_ruta and csv_ruta.is_file() else ""

    verificaciones: list[tuple[str, bool, str]] = []

    ejecutados = [paso for paso in pasos]
    verificaciones.append(
        (
            "Todos los comandos terminan con rc=0",
            all(paso["codigo"] == 0 for paso in ejecutados),
            ", ".join(f"{p['nombre']}={p['codigo']}" for p in ejecutados if p["codigo"] != 0)
            or "sin fallos",
        )
    )
    verificaciones.append(
        (
            f"{len(corridas)} corridas con filas y sin problemas",
            bool(corridas) and all(c["filas"] > 0 and c["problema"] == 0 for c in corridas),
            "; ".join(f"filas={c['filas']} problemas={c['problema']}" for c in corridas) or "sin corridas",
        )
    )
    verificaciones.append(
        (
            "Cada corrida dejo su JSONL en disco",
            all(c.get("jsonl") and Path(c["jsonl"]).is_file() for c in corridas) and bool(corridas),
            ", ".join(str(c.get("jsonl", "?")) for c in corridas) or "sin JSONL",
        )
    )

    columnas = 0
    filas_leidas = 0
    if csv_ruta and csv_ruta.is_file():
        filas_leidas, columnas = _csv_filas_columnas(csv_ruta)
    verificaciones.append(
        (
            f"CSV con las {len(CAMPOS_CSV)} columnas del esquema v1",
            columnas == len(CAMPOS_CSV),
            f"{columnas} columnas, {filas_leidas} filas",
        )
    )
    verificaciones.append(
        (
            "export es idempotente (mismo SHA-256)",
            bool(sha_1) and sha_1 == sha_2,
            f"{sha_1[:16]}... vs {sha_2[:16]}..." if sha_1 else "no se pudo calcular",
        )
    )

    print("=" * 78)
    print("RESUMEN DE LA SIMULACION DE USO")
    print("=" * 78)
    ancho = max([len(paso["nombre"]) for paso in pasos] + [10]) + 2
    print(f"{'paso':<{ancho}}{'rc':>4}{'tiempo':>10}  resultado")
    print("-" * 78)
    for paso in pasos:
        estado = "OK" if paso["codigo"] == 0 else "FALLO"
        print(f"{paso['nombre']:<{ancho}}{paso['codigo']:>4}{paso['segundos']:>9.2f}s  {estado}")

    print("\nVerificaciones")
    print("-" * 78)
    for descripcion, bien, detalle in verificaciones:
        print(f"[{'OK' if bien else 'FALLO'}] {descripcion}")
        if detalle:
            print(f"        {detalle}")

    if csv_ruta and csv_ruta.is_file():
        print(f"\nCSV del dia: {csv_ruta}")
        print(f"  {filas_leidas} filas, {columnas} columnas, sha256={sha_1[:16]}...")
    print(f"JSONL de las corridas: {salida_demo / 'raw'}")

    todo_ok = all(bien for _, bien, _ in verificaciones)
    print("\n" + ("DEMO OK: el monitor se uso de punta a punta." if todo_ok else "DEMO CON FALLOS."))
    return 0 if todo_ok else 1


# --------------------------------------------------------------------------- #
# Modo dataset: muestras sinteticas con incidentes
# --------------------------------------------------------------------------- #


def _parsear_desde(texto: str, zona: ZoneInfo) -> datetime:
    limpio = texto.strip().replace("T", " ")
    for formato in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(limpio, formato).replace(tzinfo=zona)
        except ValueError:
            continue
    raise ValueError(f"fecha invalida: {texto!r} (usa 'YYYY-MM-DD' o 'YYYY-MM-DD HH:MM')")


def _plan_incidentes(n: int, inicio: datetime, paso: int, semilla: int) -> list[dict]:
    """Incidentes deterministas repartidos por la ventana simulada."""
    azar = random.Random(semilla)
    tipos = [
        ("portal_lento", 0.05, 0.07),
        ("portal_caido", 0.008, 0.015),
        ("bd_caida", 0.008, 0.012),
        ("camara_offline", 0.02, 0.04),
        ("ssh_bruteforce", 0.03, 0.05),
        ("vlan_ataque", 0.02, 0.04),
        ("dhcp_caida", 0.006, 0.010),
        ("voip_caido", 0.008, 0.012),
        ("qos_degradado", 0.02, 0.04),
        ("sin_llamadas", 0.08, 0.10),
    ]
    if n < 30:  # ventanas cortas: menos incidentes para que se lean
        elegidos = {"portal_lento", "bd_caida", "ssh_bruteforce", "camara_offline"}
        tipos = [tipo for tipo in tipos if tipo[0] in elegidos]

    plan: list[dict] = []
    for tipo, fraccion_min, fraccion_max in tipos:
        duracion = max(1, round(n * azar.uniform(fraccion_min, fraccion_max)))
        desde = azar.randrange(0, max(1, n - duracion))
        hasta = min(n - 1, desde + duracion - 1)
        plan.append(
            {
                "tipo": tipo,
                "desde": desde,
                "hasta": hasta,
                "inicio": inicio + timedelta(seconds=desde * paso),
                "fin": inicio + timedelta(seconds=hasta * paso),
            }
        )
    return plan


def _activos(plan: list[dict], indice: int) -> set[str]:
    return {evento["tipo"] for evento in plan if evento["desde"] <= indice <= evento["hasta"]}


def _muestra(
    config: Config,
    momento: datetime,
    run_id: str,
    activos: set[str],
    indice: int,
    semilla: int,
) -> list[Resultado]:
    """Una corrida simulada: mismas filas y campos que las sondas reales."""
    azar = random.Random(semilla * 100_000 + indice)
    zona = config.general["zona_horaria"]
    resultados: list[Resultado] = []

    def fila(modulo: str, target: str, estado: str, **extra) -> Resultado:
        return Resultado.crear(
            run_id, modulo, target, estado, "simulado", zona, timestamp_evento=momento, **extra
        )

    if config.modulo_habilitado("camaras"):
        for posicion, camara in enumerate(config.camaras.get("lista", [])):
            ip = camara["ip"]
            ficha = config.ficha(ip, "camara")
            nombre = ficha.get("nombre") or camara.get("nombre")
            vlan = ficha.get("vlan") if ficha.get("vlan") is not None else camara.get("vlan")
            zona_recurso = ficha.get("zona") or camara.get("zona")
            base = dict(nombre_recurso=nombre, vlan=vlan, zona=zona_recurso)
            if "camara_offline" in activos and posicion == 0:
                resultados.append(
                    fila("Camaras", ip, "OFFLINE", perdida_paquetes_pct=100.0,
                         detalle="0/4 paquetes; RTSP 554 cerrado", **base)
                )
            elif azar.random() < 0.02:
                resultados.append(
                    fila("Camaras", ip, "DEGRADED", perdida_paquetes_pct=25.0,
                         tiempo_respuesta_ms=round(2.0 + azar.uniform(0, 3), 2),
                         detalle="4/4 paquetes; RTSP 554 cerrado", **base)
                )
            else:
                resultados.append(
                    fila("Camaras", ip, "ONLINE", puerto=554,
                         tiempo_respuesta_ms=round(1.8 + azar.uniform(0, 2.6), 2),
                         perdida_paquetes_pct=0.0,
                         detalle="4/4 paquetes; RTSP 554 abierto", **base)
                )

    if config.modulo_habilitado("portal"):
        host = urlsplit(config.portal["url"]).hostname or "portal"
        ficha = config.ficha(host, "web")
        base = dict(nombre_recurso=ficha.get("nombre") or "portal", vlan=ficha.get("vlan"),
                    zona=ficha.get("zona"))
        if "portal_caido" in activos:
            resultados.append(
                fila("PortalWeb", host, "ERROR", detalle="timeout tras 15 s al conectar", **base)
            )
            resultados.append(
                fila("PortalWeb", "Apache", "ERROR", detalle="systemctl: failed")
            )
        elif "portal_lento" in activos:
            milisegundos = round(azar.uniform(10_500, 14_000), 2)
            resultados.append(
                fila("PortalWeb", host, "DEGRADED", http_status=200,
                     tiempo_respuesta_ms=milisegundos,
                     detalle=f"HTTP 200 en {milisegundos / 1000:.1f} s; TTFB 3200 ms", **base)
            )
            resultados.append(
                fila("PortalWeb", "Apache", "OK", detalle="systemctl: active")
            )
        else:
            milisegundos = round(180 + azar.uniform(0, 260), 2)
            ttfb = 80 + azar.uniform(0, 90)
            resultados.append(
                fila("PortalWeb", host, "OK", http_status=200,
                     tiempo_respuesta_ms=milisegundos,
                     detalle=f"HTTP 200; TTFB {ttfb:.0f} ms", **base)
            )
            resultados.append(
                fila("PortalWeb", "Apache", "OK", detalle="systemctl: active")
            )

    if config.modulo_habilitado("base_datos"):
        host = config.base_datos["host"]
        ficha = config.ficha(host, "db")
        base = dict(nombre_recurso=ficha.get("nombre") or host, vlan=ficha.get("vlan"),
                    zona=ficha.get("zona"), puerto=int(config.base_datos.get("puerto", 5432)))
        if "bd_caida" in activos:
            resultados.append(
                fila("BaseDatos", host, "ERROR",
                     detalle=f"no se pudo conectar a {host}:{base['puerto']}", **base)
            )
        else:
            resultados.append(
                fila("BaseDatos", host, "OK",
                     tiempo_respuesta_ms=round(2.5 + azar.uniform(0, 6), 2),
                     detalle="SELECT 1 OK", **base)
            )

    if config.modulo_habilitado("voip"):
        host = config.voip["host"]
        ficha = config.ficha(host, "sip")
        base = dict(nombre_recurso=ficha.get("nombre") or host, vlan=ficha.get("vlan"),
                    zona=ficha.get("zona"))
        if "voip_caido" in activos:
            resultados.append(
                fila("VoIP", host, "ERROR", detalle="SIP sin respuesta (408)", **base)
            )
            resultados.append(
                fila("VoIP", "Asterisk AMI", "ERROR", detalle="AMI sin respuesta (timeout 5 s)")
            )
        else:
            resultados.append(
                fila("VoIP", host, "OK", sip_code=200,
                     puerto=int(config.voip.get("sip_puerto", 5060)),
                     detalle="SIP 200", **base)
            )
            activas = 0 if "sin_llamadas" in activos else azar.choice([0, 1, 1, 2, 2, 3])
            resultados.append(
                fila("VoIP", "Asterisk AMI", "OK", llamadas_activas=activas,
                     detalle=f"{activas} canales activos")
            )
            if "sin_llamadas" in activos:
                resultados.append(
                    fila("VoIP", "Asterisk", "SKIPPED", detalle="sin llamadas hoy")
                )
            else:
                for numero in range(azar.randint(1, 3)):
                    resultados.append(
                        fila("VoIP", "Asterisk", "OK", sip_code=200,
                             duracion_llamada_s=round(azar.uniform(25, 95), 1),
                             linea_evento=f"{run_id}-cdr-{numero}",
                             detalle="1001 -> 2001 (ANSWERED)")
                    )

    if config.modulo_habilitado("qos"):
        servidor = config.qos["servidor_iperf"]
        if "qos_degradado" in activos:
            resultados.append(
                fila("QoS", servidor, "OK", perdida_paquetes_pct=round(azar.uniform(0.8, 3.0), 2),
                     jitter_ms=round(azar.uniform(9, 16), 2),
                     ancho_banda_mbps=round(azar.uniform(8, 12), 2),
                     detalle="iperf3 UDP 20M")
            )
            resultados.append(
                fila("QoS", "captura", "OK", dscp=46,
                     detalle=f"{azar.randint(280, 340)} paquetes de 500 con DSCP 46")
            )
        else:
            resultados.append(
                fila("QoS", servidor, "OK", perdida_paquetes_pct=round(azar.uniform(0, 0.3), 2),
                     jitter_ms=round(azar.uniform(0.6, 2.0), 2),
                     ancho_banda_mbps=round(azar.uniform(18.5, 19.9), 2),
                     detalle="iperf3 UDP 20M")
            )
            resultados.append(
                fila("QoS", "captura", "OK", dscp=46,
                     detalle=f"{azar.randint(470, 500)} paquetes de 500 con DSCP 46")
            )

    if config.modulo_habilitado("seguridad"):
        if "ssh_bruteforce" in activos:
            for numero in range(azar.randint(8, 16)):
                ip = f"203.0.113.{azar.randint(10, 60)}"
                resultados.append(
                    fila("Seguridad", ip, "DROPPED", evento_seguridad="SSH_FAIL", ip_origen=ip,
                         linea_evento=f"{run_id}-ssh-{numero}",
                         detalle="Fallo de autenticacion SSH")
                )
            resultados.append(
                fila("Seguridad", "10.30.30.50", "DROPPED", evento_seguridad="VLAN30_BLOCKED",
                     ip_origen="10.30.30.50", ip_destino="10.30.30.12",
                     paquetes_delta=azar.randint(30, 120),
                     bytes_delta=azar.randint(1_800, 7_200),
                     linea_evento=f"{run_id}-vlan-{azar.randint(0, 9)}",
                     detalle="INPUT -p tcp --dport 554 -j DROP")
            )
            resultados.append(
                fila("Seguridad", "203.0.113.23", "DROPPED", evento_seguridad="FAIL2BAN_BAN",
                     ip_origen="203.0.113.23", detalle="baneada; 1 activas")
            )
        elif "vlan_ataque" in activos:
            for destino, red in (("10.30.30.12", "VLAN30"), ("10.30.40.77", "VLAN40")):
                resultados.append(
                    fila("Seguridad", destino, "DROPPED",
                         evento_seguridad=f"{red}_BLOCKED", ip_origen=f"10.30.{red[-2:]}.50",
                         ip_destino=destino, paquetes_delta=azar.randint(40, 200),
                         bytes_delta=azar.randint(2_400, 12_000),
                         linea_evento=f"{run_id}-{red}",
                         detalle="INPUT -p tcp -j DROP")
                )
        elif azar.random() < 0.10:
            ip = f"198.51.100.{azar.randint(1, 60)}"
            resultados.append(
                fila("Seguridad", ip, "DROPPED", evento_seguridad="SSH_FAIL", ip_origen=ip,
                     linea_evento=f"{run_id}-ssh-unico", detalle="Fallo de autenticacion SSH")
            )
        else:
            resultados.append(
                fila("Seguridad", "firewall", "OK", detalle="sin cambios en contadores de iptables")
            )

    if config.modulo_habilitado("dhcp"):
        if "dhcp_caida" in activos:
            resultados.append(
                fila("DHCP", "isc-dhcp-server", "ERROR", detalle="servicio failed; 0 leases activos")
            )
        else:
            resultados.append(
                fila("DHCP", "isc-dhcp-server", "OK",
                     detalle=f"servicio active; {azar.randint(9, 14)} leases activos")
            )

    return resultados


def _limpiar(cfg: Config) -> list[Path]:
    eliminados = []
    for sub in ("raw", "csv"):
        ruta = cfg.datos / sub
        if ruta.is_dir():
            shutil.rmtree(ruta)
            eliminados.append(ruta)
    return eliminados


def _p95(valores: list[float]) -> float:
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    return ordenados[min(len(ordenados) - 1, int(round(0.95 * (len(ordenados) - 1))))]


def _linea_tiempo(marcas: list[str], inicio: datetime, paso: int, ancho: int = 48) -> str:
    lineas = []
    for comienzo in range(0, len(marcas), ancho):
        trozo = "".join(marcas[comienzo:comienzo + ancho])
        momento = inicio + timedelta(seconds=comienzo * paso)
        lineas.append(f"{momento:%Y-%m-%d %H:%M}  {trozo}")
    return "\n".join(lineas)


def _reporte(
    config: Config,
    salida: Path,
    inicio: datetime,
    fin: datetime,
    paso: int,
    semilla: int,
    filas: list[Resultado],
    plan: list[dict],
    marcas: list[str],
    csv_rutas: list[tuple[Path, int]],
    jsonl_total: int,
) -> Path:
    zona = ZoneInfo(config.general["zona_horaria"])
    ahora = datetime.now(zona)
    conteo_modulo = Counter(fila.modulo for fila in filas)
    portal_host = urlsplit(config.portal["url"]).hostname or "portal"
    latencias = [
        fila.tiempo_respuesta_ms
        for fila in filas
        if fila.modulo == "PortalWeb" and fila.recurso_target == portal_host
        and fila.tiempo_respuesta_ms is not None
    ]
    filas_por_hora: Counter[int] = Counter()
    problemas_por_hora: Counter[int] = Counter()
    for fila in filas:
        hora = datetime.strptime(fila.timestamp, "%Y-%m-%d %H:%M:%S").hour
        filas_por_hora[hora] += 1
        if fila.estado not in EXITO:
            problemas_por_hora[hora] += 1

    lineas = [
        f"# Simulacion de uso del monitor - {inicio:%Y-%m-%d}",
        "",
        f"> **{BANNER}**",
        ">",
        "> Estas cifras no son mediciones de la red: las genera este script con",
        "> `fuente = \"simulado\"` para demostrar el flujo del monitor y alimentar el",
        "> tablero. No deben presentarse como produccion.",
        "",
        f"- Generado: {ahora:%Y-%m-%d %H:%M:%S} ({config.general['zona_horaria']})",
        f"- Ventana: {inicio:%Y-%m-%d %H:%M} -> {fin:%Y-%m-%d %H:%M} ({paso} s entre muestras)",
        f"- Muestras: {len(marcas)} | filas: {len(filas)} | JSONL: {jsonl_total}",
        f"- Semilla: {semilla} | config: `{config.ruta.name}`",
        "",
        "## Disponibilidad por modulo",
        "",
        "| Modulo | Filas | OK/ONLINE/DROPPED | Problemas | Disponibilidad |",
        "|---|---:|---:|---:|---:|",
    ]
    for modulo in ("Camaras", "PortalWeb", "BaseDatos", "VoIP", "QoS", "Seguridad", "DHCP"):
        if not conteo_modulo.get(modulo):
            continue
        total = conteo_modulo[modulo]
        buenas = sum(
            1 for fila in filas if fila.modulo == modulo and fila.estado in EXITO
        )
        malas = total - buenas
        lineas.append(
            f"| {modulo} | {total} | {buenas} | {malas} | {100 * buenas / total:.1f} % |"
        )

    lineas += [
        "",
        "## Portal Web",
        "",
    ]
    if latencias:
        lineas += [
            f"- Latencia mediana: {statistics.median(latencias):.0f} ms",
            f"- Latencia P95: {_p95(latencias):.0f} ms",
            f"- Latencia maxima: {max(latencias):.0f} ms",
        ]
    else:
        lineas.append("- Sin muestras de latencia (modulo portal deshabilitado o filtrado).")

    lineas += [
        "",
        "## Incidentes simulados",
        "",
        "| Tipo | Descripcion | Desde | Hasta | Muestras |",
        "|---|---|---|---|---:|",
    ]
    if plan:
        for evento in plan:
            lineas.append(
                f"| `{evento['tipo']}` | {DESCRIPCIONES.get(evento['tipo'], '')} | "
                f"{evento['inicio']:%H:%M} | {evento['fin']:%H:%M} | "
                f"{evento['hasta'] - evento['desde'] + 1} |"
            )
    else:
        lineas.append("| - | Sin incidentes (`--sin-incidentes`) | - | - | - |")

    lineas += [
        "",
        "## Linea de tiempo",
        "",
        "```text",
        "Cada caracter es una muestra: . sin novedad, ! degradado/offline, X error, o sin datos",
        _linea_tiempo(marcas, inicio, paso),
        "```",
        "",
        "## Problemas por hora",
        "",
        "| Hora | Filas | Problemas |",
        "|---|---:|---:|",
    ]
    for hora in sorted(filas_por_hora):
        lineas.append(f"| {hora:02d}:00 | {filas_por_hora[hora]} | {problemas_por_hora[hora]} |")

    lineas += [
        "",
        "## Salida para Power BI",
        "",
    ]
    for ruta, cantidad in csv_rutas:
        lineas.append(f"- `{ruta}` ({cantidad} filas, {len(CAMPOS_CSV)} columnas)")
    lineas += [
        "",
        "Filtra `fuente = \"simulado\"` en el tablero para distinguir estas filas de las",
        "mediciones reales. Las medidas DAX de `powerbi/medidas.dax` funcionan igual",
        "porque el esquema es el v1 del monitor.",
        "",
        "## Como se genero",
        "",
        "```bash",
        f"python simulacion_monitor.py dataset --desde \"{inicio:%Y-%m-%d %H:%M}\" "
        f"--horas {(fin - inicio).total_seconds() / 3600:.0f} --paso {paso} --semilla {semilla}",
        "```",
        "",
    ]
    destino = salida / f"reporte_uso_{inicio:%Y-%m-%d}.md"
    destino.write_text("\n".join(lineas), encoding="utf-8")
    return destino


def dataset(config: Config, args: argparse.Namespace) -> int:
    zona = ZoneInfo(config.general["zona_horaria"])
    if args.paso < 1:
        print("--paso debe ser >= 1 segundo", file=sys.stderr)
        return 2
    if args.horas <= 0:
        print("--horas debe ser mayor que cero", file=sys.stderr)
        return 2

    salida = Path(args.salida).expanduser()
    if not salida.is_absolute():
        salida = (RAIZ / salida).resolve()
    salida = salida.resolve()
    if salida == RAIZ:
        print("La salida no puede ser la raiz del repositorio", file=sys.stderr)
        return 2
    if salida == config.datos.resolve() and not args.forzar:
        print(
            "La salida es el directorio de datos real del monitor; usa otra ruta "
            "o --forzar si de verdad quieres sobrescribirlo",
            file=sys.stderr,
        )
        return 2

    try:
        if args.desde:
            inicio = _parsear_desde(args.desde, zona)
        else:
            ayer = datetime.now(zona) - timedelta(days=1)
            inicio = ayer.replace(hour=0, minute=0, second=0, microsecond=0)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    total_muestras = max(1, int(args.horas * 3600 / args.paso))
    muestras = [inicio + timedelta(seconds=indice * args.paso) for indice in range(total_muestras)]
    fin = muestras[-1]

    cfg = replace(config, general={**config.general, "directorio_datos": str(salida)})
    salida.mkdir(parents=True, exist_ok=True)
    if args.limpiar:
        for ruta in _limpiar(cfg):
            print(f"Limpiado: {ruta}")

    _imprimir_banner(config, "dataset", salida)
    print(f"Ventana: {inicio:%Y-%m-%d %H:%M} -> {fin:%Y-%m-%d %H:%M} "
          f"({total_muestras} muestras cada {args.paso} s)")
    print(f"Semilla: {args.semilla}\n")

    plan = [] if args.sin_incidentes else _plan_incidentes(
        total_muestras, inicio, args.paso, args.semilla
    )

    permitidos = {
        clave
        for clave in MODULOS.values()
        if config.modulo_habilitado(clave)
    }
    if args.solo:
        pedidos = {x.strip() for x in args.solo.split(",") if x.strip()}
        desconocidos = pedidos - set(MODULOS.values())
        if desconocidos:
            print(f"Modulos desconocidos: {', '.join(sorted(desconocidos))}", file=sys.stderr)
            return 2
        permitidos &= pedidos
    if not permitidos:
        print("No hay modulos habilitados para simular", file=sys.stderr)
        return 2
    modulos_fila = {nombre for nombre, clave in MODULOS.items() if clave in permitidos}

    filas: list[Resultado] = []
    marcas: list[str] = []
    jsonl_total = 0
    inicio_generacion = time.perf_counter()
    for indice, momento in enumerate(muestras):
        run_id = f"sim-uso-{momento:%Y%m%dT%H%M%S}"
        resultados = [
            fila
            for fila in _muestra(cfg, momento, run_id, _activos(plan, indice), indice, args.semilla)
            if fila.modulo in modulos_fila
        ]
        if not resultados:
            marcas.append("-")
            continue
        escribir_jsonl(resultados, cfg, momento)
        jsonl_total += 1
        filas.extend(resultados)
        estados = {fila.estado for fila in resultados}
        if "ERROR" in estados:
            marcas.append("X")
        elif estados & {"DEGRADED", "OFFLINE"}:
            marcas.append("!")
        elif "SKIPPED" in estados:
            marcas.append("o")
        else:
            marcas.append(".")
        if (indice + 1) % max(1, total_muestras // 10) == 0 or indice == total_muestras - 1:
            if sys.stdout.isatty():
                print(f"  {indice + 1}/{total_muestras} muestras, {len(filas)} filas", end="\r")
            else:
                print(f"  {indice + 1}/{total_muestras} muestras, {len(filas)} filas")

    if sys.stdout.isatty():
        print(" " * 60, end="\r")
    print(f"Generadas {len(filas)} filas en {jsonl_total} JSONL "
          f"({time.perf_counter() - inicio_generacion:.1f} s)")

    csv_rutas: list[tuple[Path, int]] = []
    for fecha in sorted({momento.strftime("%Y-%m-%d") for momento in muestras}):
        ruta, cantidad = exportar_csv(fecha, cfg)
        csv_rutas.append((ruta, cantidad))

    problema = [fila for fila in filas if fila.estado not in EXITO]
    conteo_modulo = Counter(fila.modulo for fila in filas)
    portal_host = urlsplit(config.portal["url"]).hostname or "portal"
    latencias = [
        fila.tiempo_respuesta_ms
        for fila in filas
        if fila.modulo == "PortalWeb" and fila.recurso_target == portal_host
        and fila.tiempo_respuesta_ms is not None
    ]

    print("\nRESUMEN DE LA SIMULACION")
    print("-" * 78)
    print(f"Filas: {len(filas)} | problemas: {len(problema)} "
          f"({100 * len(problema) / max(1, len(filas)):.1f} %)")
    for modulo, cantidad in conteo_modulo.most_common():
        print(f"  {modulo:<10} {cantidad:>5} filas")
    if latencias:
        print(f"Portal: mediana {statistics.median(latencias):.0f} ms | "
              f"P95 {_p95(latencias):.0f} ms | max {max(latencias):.0f} ms")
    for ruta, cantidad in csv_rutas:
        print(f"CSV: {ruta} ({cantidad} filas, {len(CAMPOS_CSV)} columnas)")
    if plan:
        print("Incidentes: " + ", ".join(
            f"{evento['tipo']} {evento['inicio']:%H:%M}-{evento['fin']:%H:%M}" for evento in plan
        ))

    reporte = _reporte(
        config, salida, inicio, fin, args.paso, args.semilla,
        filas, plan, marcas, csv_rutas, jsonl_total,
    )
    print(f"Reporte: {reporte}")
    print("\nLas filas llevan fuente=simulado; no son mediciones de la red.")
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simulacion_monitor.py",
        description="Simulacion de uso del monitor PortoCaribe (demo y dataset).",
    )
    sub = parser.add_subparsers(dest="comando", required=True)
    comun = argparse.ArgumentParser(add_help=False)
    comun.add_argument("--config", default="monitor.toml", help="TOML del monitor")

    p_demo = sub.add_parser("demo", parents=[comun],
                            help="Recorre el CLI como un operador (validate, run --simulate, export)")
    p_demo.add_argument("--corridas", type=int, default=3,
                        help="Corridas completas --simulate (por defecto 3)")
    p_demo.add_argument("--salida", default="simulacion/demo",
                        help="Datos de la demo, aislados del dataset real (simulacion/demo)")
    p_demo.add_argument("--conservar", action="store_true",
                        help="No borrar los datos de la demo anterior")
    p_demo.add_argument("--forzar", action="store_true",
                        help="Permite usar como salida el directorio de datos real")

    p_data = sub.add_parser("dataset", parents=[comun],
                            help="Genera muestras simuladas con incidentes y su CSV")
    p_data.add_argument("--desde", default="",
                        help="Inicio 'YYYY-MM-DD [HH:MM]' (por defecto ayer 00:00)")
    p_data.add_argument("--horas", type=float, default=24.0, help="Horas a simular (24)")
    p_data.add_argument("--paso", type=int, default=300, help="Segundos entre muestras (300)")
    p_data.add_argument("--semilla", type=int, default=20261121, help="Semilla del generador")
    p_data.add_argument("--salida", default="simulacion/dataset",
                        help="Directorio de salida (simulacion/dataset)")
    p_data.add_argument("--solo", default="", help="Modulos separados por coma")
    p_data.add_argument("--sin-incidentes", action="store_true", help="Dia sin incidentes")
    p_data.add_argument("--conservar", dest="limpiar", action="store_false",
                        help="No borrar la simulacion anterior (por defecto se limpia)")
    p_data.add_argument("--forzar", action="store_true",
                        help="Permite usar como salida el directorio de datos real")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = cargar_config(args.config)
    except FileNotFoundError:
        print(f"No existe la configuracion: {args.config}", file=sys.stderr)
        return 2
    except ValueError as exc:
        if "zona_horaria" in str(exc):
            print(
                "zoneinfo no encuentra la zona horaria. En Windows instala tzdata:\n"
                "  python -m pip install tzdata",
                file=sys.stderr,
            )
        else:
            print(f"Configuracion invalida: {exc}", file=sys.stderr)
        return 2

    if args.comando == "demo":
        return demo(config, args)
    return dataset(config, args)


if __name__ == "__main__":
    raise SystemExit(main())

"""Sondas de red y lectura de snapshots recolectados."""

from __future__ import annotations

import csv
import http.client as http_cliente
import json
import os
import re
import shutil
import socket
import ssl
import struct
import subprocess
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from .modelos import Resultado


class SondaError(Exception):
    pass


def ping(host: str, paquetes: int = 4, timeout: float = 5) -> dict:
    if not shutil.which("ping"):
        raise SondaError("ping no está instalado")
    entorno = dict(os.environ, LC_ALL="C")
    try:
        proceso = subprocess.run(
            ["ping", "-n", "-q", "-c", str(paquetes), "-W", str(int(max(1, timeout))), host],
            capture_output=True,
            text=True,
            timeout=timeout + 5,
            env=entorno,
        )
    except subprocess.TimeoutExpired as exc:
        raise SondaError("ping agotó el tiempo") from exc
    salida = proceso.stdout + proceso.stderr
    perdida = 100.0
    coincidencia = re.search(r"([\d.]+)% packet loss", salida)
    if coincidencia:
        perdida = float(coincidencia.group(1))
    rtt = None
    rtt_match = re.search(r"(?:rtt|round-trip)[^=]*=\s*([\d.]+)/([\d.]+)/", salida)
    if rtt_match:
        rtt = float(rtt_match.group(2))
    recibidos = int(round(paquetes * (1 - perdida / 100.0)))
    return {"recibidos": recibidos, "perdida_pct": perdida, "rtt_ms": rtt}


def tcp(host: str, puerto: int, timeout: float = 5) -> float:
    inicio = time.perf_counter()
    try:
        with socket.create_connection((host, int(puerto)), timeout=timeout):
            pass
    except OSError as exc:
        raise SondaError(f"TCP {host}:{puerto} falló: {exc}") from exc
    return (time.perf_counter() - inicio) * 1000.0


def http(url: str, timeout: float = 15, verificar_tls: bool = False) -> dict:
    partes = urlsplit(url)
    esquema = partes.scheme or "https"
    host = partes.hostname
    if not host:
        raise SondaError("URL sin host")
    puerto = partes.port or (443 if esquema == "https" else 80)
    ruta = partes.path or "/"
    if partes.query:
        ruta += "?" + partes.query
    contexto = ssl.create_default_context()
    if not verificar_tls:
        contexto.check_hostname = False
        contexto.verify_mode = ssl.CERT_NONE
    clase = http_cliente.HTTPSConnection if esquema == "https" else http_cliente.HTTPConnection
    conexion = clase(host, puerto, timeout=timeout, context=contexto) if esquema == "https" else clase(host, puerto, timeout=timeout)
    inicio = time.perf_counter()
    try:
        conexion.connect()
        tls = None
        if isinstance(conexion.sock, ssl.SSLSocket):
            tls = conexion.sock.version()
        conexion.request("GET", ruta, headers={"User-Agent": "PortoCaribeMonitor/1.0"})
        respuesta = conexion.getresponse()
        ttfb = (time.perf_counter() - inicio) * 1000.0
        respuesta.read(2048)
        total = (time.perf_counter() - inicio) * 1000.0
        return {
            "status": respuesta.status,
            "ttfb_ms": ttfb,
            "total_ms": total,
            "tls": tls,
            "detalle": f"HTTP {respuesta.status} · TLS {tls or 'no'}",
        }
    except (OSError, ssl.SSLError, http_cliente.HTTPException) as exc:
        raise SondaError(f"HTTP falló: {exc}") from exc
    finally:
        conexion.close()


def psql(host: str, puerto: int, base: str, usuario: str, pgpassfile: str | None, timeout: float) -> dict | None:
    binario = shutil.which("psql")
    if not binario:
        return None
    entorno = dict(os.environ, PGCONNECT_TIMEOUT=str(int(timeout)))
    if pgpassfile:
        entorno["PGPASSFILE"] = pgpassfile
    inicio = time.perf_counter()
    try:
        proceso = subprocess.run(
            [binario, "-w", "-tAc", "SELECT 1", "-h", host, "-p", str(puerto), "-U", usuario, "-d", base],
            capture_output=True,
            text=True,
            timeout=timeout + 5,
            env=entorno,
        )
    except subprocess.TimeoutExpired as exc:
        raise SondaError("psql agotó el tiempo") from exc
    ms = (time.perf_counter() - inicio) * 1000.0
    if proceso.returncode != 0:
        raise SondaError((proceso.stderr or "psql falló").strip()[:180])
    return {"ms": ms, "detalle": "SELECT 1 OK"}


def sip_options(host: str, puerto: int, timeout: float = 3) -> int:
    rama = f"z9hG4bK-{int(time.time() * 1000)}"
    mensaje = (
        f"OPTIONS sip:{host} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {socket.gethostname()};branch={rama}\r\n"
        "Max-Forwards: 70\r\n"
        f"From: <sip:monitor@{socket.gethostname()}>;tag={rama}\r\n"
        f"To: <sip:{host}>\r\n"
        f"Call-ID: {rama}@{socket.gethostname()}\r\n"
        "CSeq: 1 OPTIONS\r\n"
        "Contact: <sip:monitor@localhost>\r\n"
        "Content-Length: 0\r\n\r\n"
    ).encode("utf-8")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        for _ in range(2):
            sock.sendto(mensaje, (host, int(puerto)))
            try:
                datos, _ = sock.recvfrom(4096)
            except socket.timeout:
                continue
            primera = datos.decode("utf-8", "replace").splitlines()[0]
            coincidencia = re.match(r"SIP/2\.0\s+(\d{3})", primera)
            if coincidencia:
                return int(coincidencia.group(1))
    return 408


def _leer_hasta(sock: socket.socket, marca: bytes, limite: int = 65536) -> bytes:
    datos = b""
    while marca not in datos and len(datos) < limite:
        bloque = sock.recv(4096)
        if not bloque:
            break
        datos += bloque
    return datos


def ami(host: str, puerto: int, usuario: str, secreto: str, timeout: float = 5) -> int:
    with socket.create_connection((host, int(puerto)), timeout=timeout) as sock:
        sock.settimeout(timeout)
        _leer_hasta(sock, b"\r\n")
        login = (
            f"Action: Login\r\nUsername: {usuario}\r\nSecret: {secreto}\r\n"
            "Events: off\r\n\r\n"
        ).encode("utf-8")
        sock.sendall(login)
        respuesta = _leer_hasta(sock, b"\r\n\r\n")
        if b"Response: Success" not in respuesta:
            raise SondaError("AMI rechazó el login")
        sock.sendall(b"Action: CoreShowChannels\r\n\r\n")
        datos = _leer_hasta(sock, b"Event: CoreShowChannelsComplete", limite=262144)
        sock.sendall(b"Action: Logoff\r\n\r\n")
    return datos.count(b"Event: CoreShowChannel\r\n")


_SIP_DISPOSICION = {
    "ANSWERED": 200,
    "BUSY": 486,
    "FAILED": 503,
    "NO ANSWER": 408,
}


_CAMPOS_CDR = ("uniqueid", "start", "duration", "billsec", "disposition", "src", "dst")


def _fila_cdr(fila: list[str], cabecera: list[str] | None) -> dict:
    """Normaliza una fila del CDR; el Master.csv de Asterisk no lleva cabecera."""
    if cabecera:
        datos = {clave: (fila[i] if i < len(fila) else "") for i, clave in enumerate(cabecera)}
    else:

        def posicion(indice: int) -> str:
            return fila[indice] if indice < len(fila) else ""

        datos = {
            "src": posicion(1),
            "dst": posicion(2),
            "start": posicion(9),
            "duration": posicion(12),
            "billsec": posicion(13),
            "disposition": posicion(14),
            "uniqueid": posicion(16),
        }
    return {clave: str(datos.get(clave) or "").strip() for clave in _CAMPOS_CDR}


def cdr(path: str, run_id: str, zona: str) -> list[Resultado]:
    archivo = Path(path)
    if not archivo.is_file():
        return [Resultado.crear(run_id, "VoIP", "Asterisk", "SKIPPED", "asterisk-cdr", zona, detalle="sin CDR recolectado")]
    hoy = datetime.now().strftime("%Y-%m-%d")
    vistos: set[str] = set()
    resultados: list[Resultado] = []
    try:
        with archivo.open("r", encoding="utf-8", errors="replace", newline="") as manejador:
            cabecera: list[str] | None = None
            for fila in csv.reader(manejador):
                if not fila:
                    continue
                if cabecera is None:
                    if "uniqueid" in (celda.strip().lower() for celda in fila):
                        cabecera = [celda.strip().lower() for celda in fila]
                        continue
                    cabecera = []  # sin cabecera: se procesa como datos
                datos = _fila_cdr(fila, cabecera or None)
                uniqueid = datos["uniqueid"]
                if not uniqueid or uniqueid in vistos:
                    continue
                inicio = datos["start"]
                if not inicio.startswith(hoy):
                    continue
                vistos.add(uniqueid)
                try:
                    momento = datetime.strptime(inicio, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    momento = datetime.now()
                try:
                    duracion = float(datos["billsec"] or datos["duration"] or 0)
                except ValueError:
                    duracion = 0.0
                disposicion = datos["disposition"].upper()
                resultados.append(
                    Resultado.crear(
                        run_id,
                        "VoIP",
                        "Asterisk",
                        "OK",
                        "asterisk-cdr",
                        zona,
                        timestamp_evento=momento,
                        linea_evento=uniqueid,
                        sip_code=_SIP_DISPOSICION.get(disposicion, 200),
                        duracion_llamada_s=duracion,
                        ip_origen=datos["src"],
                        detalle=f"{datos['src'] or '?'} -> {datos['dst'] or '?'} ({disposicion or 'SIN ESTADO'})",
                    )
                )
    except OSError:
        return [Resultado.crear(run_id, "VoIP", "Asterisk", "ERROR", "asterisk-cdr", zona, detalle="no se pudo leer el CDR")]
    if not resultados:
        return [Resultado.crear(run_id, "VoIP", "Asterisk", "SKIPPED", "asterisk-cdr", zona, detalle="sin llamadas hoy")]
    return resultados


def ntp_sincronizado(timeout: float = 3) -> bool | None:
    """Estado del reloj según systemd-timesyncd/chrony (plan §11).

    Devuelve ``None`` si no se puede determinar (sin ``timedatectl``), ``True``
    si está sincronizado y ``False`` si el reloj está libre.
    """
    binario = shutil.which("timedatectl")
    if not binario:
        return None
    for argumentos in (["show", "-p", "NTPSynchronized", "--value"],
                       ["show", "-p", "NTPSynchronized"]):
        try:
            proceso = subprocess.run(
                [binario, *argumentos], capture_output=True, text=True, timeout=timeout
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        salida = (proceso.stdout or "").strip().lower()
        if salida in ("yes", "no"):
            return salida == "yes"
        if "ntpsynchronized=" in salida:
            return salida.rsplit("=", 1)[1].strip() == "yes"
    return None


def leer_snapshot(ruta: str, frescura_s: float) -> tuple[str | None, str | None]:
    archivo = Path(ruta)
    if not archivo.is_file():
        return None, "SKIPPED"
    edad = time.time() - archivo.stat().st_mtime
    if edad > frescura_s:
        return None, "STALE"
    try:
        return archivo.read_text(encoding="utf-8", errors="replace"), None
    except OSError:
        return None, "ERROR"


def apache(ruta: str, frescura_s: float, run_id: str, zona: str) -> Resultado:
    texto, problema = leer_snapshot(ruta, frescura_s)
    if texto is None:
        return Resultado.crear(run_id, "PortalWeb", "Apache", problema or "SKIPPED", "archivo", zona, detalle="snapshot de Apache no disponible")
    activo = texto.strip().splitlines()[0].strip().lower() if texto.strip() else ""
    estado = "OK" if activo == "active" else "ERROR"
    return Resultado.crear(run_id, "PortalWeb", "Apache", estado, "archivo", zona, detalle=f"systemctl: {activo or 'sin salida'}")


def leases_activos(texto: str) -> int:
    """Cuenta IPs con arrendamiento activo, sin duplicar bloques repetidos.

    ``dhcpd.leases`` acumula un bloque por renovación, así que contar la cadena
    ``binding state active;`` infla el número; se deduplica por IP.
    """
    activos: set[str] = set()
    actual: str | None = None
    for linea in texto.splitlines():
        coincidencia = re.match(r"\s*lease\s+(\S+)\s*\{", linea)
        if coincidencia:
            actual = coincidencia.group(1)
            continue
        if actual and "binding state active;" in linea:
            activos.add(actual)
        elif linea.strip() == "}":
            actual = None
    return len(activos)


def dhcp(config: dict, frescura_s: float, run_id: str, zona: str) -> list[Resultado]:
    estado_texto, problema = leer_snapshot(config["estado"], frescura_s)
    if estado_texto is None:
        return [Resultado.crear(run_id, "DHCP", "isc-dhcp-server", problema or "SKIPPED", "archivo", zona, detalle="estado de DHCP no disponible")]
    lineas = [linea.strip() for linea in estado_texto.splitlines() if linea.strip()]
    activo = lineas[0].lower() if lineas else ""
    leases, error_leases = leer_snapshot(config["leases"], frescura_s)
    activos = leases_activos(leases) if leases else 0
    estado = "OK" if activo == "active" else "ERROR"
    return [
        Resultado.crear(
            run_id,
            "DHCP",
            "isc-dhcp-server",
            estado,
            "archivo",
            zona,
            detalle=f"servicio {activo or 'desconocido'}; {activos} leases activos" + (f"; {error_leases}" if error_leases else ""),
        )
    ]


def iperf(servidor: str, duracion: int, ancho_banda: str, timeout: float, zona: str, run_id: str) -> Resultado:
    binario = shutil.which("iperf3")
    if not binario:
        return Resultado.crear(run_id, "QoS", servidor, "SKIPPED", "iperf3", zona, detalle="iperf3 no instalado")
    try:
        proceso = subprocess.run(
            [binario, "-c", servidor, "-u", "-b", ancho_banda, "-t", str(duracion), "-S", "0xB8", "-J"],
            capture_output=True,
            text=True,
            timeout=timeout + duracion + 10,
        )
    except subprocess.TimeoutExpired:
        return Resultado.crear(run_id, "QoS", servidor, "ERROR", "iperf3", zona, detalle="iperf3 agotó el tiempo")
    try:
        datos = json.loads(proceso.stdout)
        receptor = datos["end"]["sum_received"]
        emisor = datos["end"]["sum_sent"]
        perdida = float(receptor.get("loss_percent", 0))
        jitter = float(receptor.get("jitter_ms", 0))
        mbps = float(emisor.get("bits_per_second", 0)) / 1_000_000
    except (ValueError, KeyError, TypeError):
        return Resultado.crear(run_id, "QoS", servidor, "ERROR", "iperf3", zona, detalle="salida de iperf3 inválida")
    return Resultado.crear(
        run_id,
        "QoS",
        servidor,
        "OK",
        "iperf3",
        zona,
        perdida_paquetes_pct=round(perdida, 2),
        jitter_ms=round(jitter, 2),
        ancho_banda_mbps=round(mbps, 2),
        detalle=f"iperf3 UDP {ancho_banda}",
    )


def dscp_pcap(ruta: str, run_id: str, zona: str) -> list[Resultado]:
    archivo = Path(ruta)
    if not archivo.is_file():
        return []
    datos = archivo.read_bytes()
    if len(datos) < 24:
        return []
    magia = struct.unpack("<I", datos[:4])[0]
    if magia not in (0xA1B2C3D4, 0xA1B23C4D):
        return []
    fin = "<" if magia in (0xA1B2C3D4, 0xA1B23C4D) else ">"
    enlace = struct.unpack(f"{fin}I", datos[20:24])[0]
    posicion = 24
    conteo: dict[int, int] = {}
    while posicion + 16 <= len(datos):
        _, _, incl, _ = struct.unpack(f"{fin}IIII", datos[posicion : posicion + 16])
        posicion += 16
        paquete = datos[posicion : posicion + incl]
        posicion += incl
        if enlace == 1 and len(paquete) >= 14:
            tipo = struct.unpack(">H", paquete[12:14])[0]
            desplazamiento = 14
            if tipo == 0x8100:
                desplazamiento += 4
            if len(paquete) < desplazamiento + 20:
                continue
            version = paquete[desplazamiento] >> 4
            if version != 4:
                continue
            tos = paquete[desplazamiento + 1]
            dscp = tos >> 2
            conteo[dscp] = conteo.get(dscp, 0) + 1
    if not conteo:
        return []
    total = sum(conteo.values())
    return [
        Resultado.crear(
            run_id,
            "QoS",
            "captura",
            "OK",
            "pcap",
            zona,
            dscp=dscp,
            detalle=f"{cantidad} paquetes de {total} con DSCP {dscp}",
        )
        for dscp, cantidad in sorted(conteo.items())
    ]

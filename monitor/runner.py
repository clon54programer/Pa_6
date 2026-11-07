"""Orquestador de la corrida: sondas, simulación, resumen y salida."""

from __future__ import annotations

import errno
import json
import logging
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import recoleccion, seguridad, sondas
from .config import Config
from .escritura import escribir_jsonl
from .modelos import Resultado

try:  # POSIX (Linux, destino del monitor)
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None
    import msvcrt

LOG = logging.getLogger("monitor.runner")
EXITO = {"ONLINE", "OK", "DROPPED"}


def _zona(config: Config) -> str:
    return config.general["zona_horaria"]


def _error(run_id: str, modulo: str, target: str, exc: Exception, zona: str) -> Resultado:
    return Resultado.crear(run_id, modulo, target, "ERROR", "interno", zona, detalle=str(exc)[:180])


def _camara(config: Config, camara: dict, run_id: str) -> list[Resultado]:
    ip = camara["ip"]
    nombre = camara.get("nombre")
    zona = _zona(config)
    try:
        ping = sondas.ping(ip, int(config.camaras.get("ping_paquetes", 4)), config.timeout)
    except sondas.SondaError as exc:
        return [Resultado.crear(run_id, "Camaras", ip, "OFFLINE", "ping", zona, nombre_recurso=nombre,
                                vlan=camara.get("vlan"), detalle=str(exc)[:180])]
    puerto = int(config.camaras.get("rtsp_puerto", 554))
    rtsp_ok = False
    rtsp_ms = None
    try:
        rtsp_ms = sondas.tcp(ip, puerto, min(config.timeout, 3))
        rtsp_ok = True
    except sondas.SondaError:
        pass
    if ping["recibidos"] == 0:
        estado = "OFFLINE"
    elif not rtsp_ok:
        estado = "DEGRADED"
    else:
        estado = "ONLINE"
    return [
        Resultado.crear(
            run_id, "Camaras", ip, estado, "ping", zona,
            nombre_recurso=nombre, vlan=camara.get("vlan"), zona=camara.get("zona"),
            tiempo_respuesta_ms=ping.get("rtt_ms"), perdida_paquetes_pct=ping.get("perdida_pct"),
            puerto=puerto if rtsp_ok else None,
            detalle=f"{ping['recibidos']}/{config.camaras.get('ping_paquetes', 4)} paquetes; "
                    f"RTSP {puerto} {'abierto' if rtsp_ok else 'cerrado'}"
                    + (f" ({rtsp_ms:.0f} ms)" if rtsp_ms is not None else ""),
        )
    ]


def _portal(config: Config, run_id: str) -> list[Resultado]:
    zona = _zona(config)
    resultados: list[Resultado] = []
    try:
        datos = sondas.http(
            config.portal["url"],
            float(config.portal.get("timeout_s", 15)),
            bool(config.portal.get("verificar_tls", False)),
        )
        umbral = float(config.portal.get("umbral_degradado_s", 10)) * 1000
        estado = "OK"
        if datos["status"] >= 500 or datos["total_ms"] > umbral:
            estado = "DEGRADED"
        resultados.append(
            Resultado.crear(
                run_id, "PortalWeb", config.portal["url"].split("/")[2] if "//" in config.portal["url"] else "portal",
                estado, "http", zona, http_status=datos["status"], tiempo_respuesta_ms=round(datos["total_ms"], 2),
                detalle=f"{datos['detalle']}; TTFB {datos['ttfb_ms']:.0f} ms",
            )
        )
    except (sondas.SondaError, OSError) as exc:
        resultados.append(Resultado.crear(run_id, "PortalWeb", "portal", "ERROR", "http", zona, detalle=str(exc)[:180]))
    resultados.append(sondas.apache(config.portal["estado_apache"], config.frescura, run_id, zona))
    return resultados


def _base_datos(config: Config, run_id: str) -> list[Resultado]:
    zona = _zona(config)
    host = config.base_datos["host"]
    puerto = int(config.base_datos.get("puerto", 5432))
    inicio = time.perf_counter()
    try:
        sondas.tcp(host, puerto, config.timeout)
    except sondas.SondaError as exc:
        return [Resultado.crear(run_id, "BaseDatos", host, "ERROR", "tcp", zona, puerto=puerto, detalle=str(exc)[:180])]
    fuente = "tcp"
    detalle = "puerto 5432 abierto"
    ms = (time.perf_counter() - inicio) * 1000
    try:
        chequeo = sondas.psql(
            host, puerto, config.base_datos.get("base", "postgres"),
            config.base_datos.get("usuario", "postgres"), config.base_datos.get("pgpassfile"),
            config.timeout,
        )
        if chequeo:
            fuente = "psql"
            ms = chequeo["ms"]
            detalle = chequeo["detalle"]
    except sondas.SondaError as exc:
        return [Resultado.crear(run_id, "BaseDatos", host, "ERROR", "psql", zona, puerto=puerto, detalle=str(exc)[:180])]
    return [Resultado.crear(run_id, "BaseDatos", host, "OK", fuente, zona, puerto=puerto,
                            tiempo_respuesta_ms=round(ms, 2), detalle=detalle)]


def _voip(config: Config, run_id: str) -> list[Resultado]:
    zona = _zona(config)
    host = config.voip["host"]
    resultados: list[Resultado] = []
    try:
        codigo = sondas.sip_options(host, int(config.voip.get("sip_puerto", 5060)), min(config.timeout, 3))
        estado = "OK" if codigo in (200, 401, 403) else "ERROR"
        resultados.append(Resultado.crear(run_id, "VoIP", host, estado, "sip", zona, sip_code=codigo,
                                          puerto=int(config.voip.get("sip_puerto", 5060)), detalle=f"SIP {codigo}"))
    except (sondas.SondaError, OSError) as exc:
        resultados.append(Resultado.crear(run_id, "VoIP", host, "ERROR", "sip", zona, detalle=str(exc)[:180]))

    if config.voip.get("ami"):
        secreto = os.environ.get(config.voip.get("ami_secreto_env", "ASTERISK_AMI_SECRET"))
        if not secreto:
            resultados.append(Resultado.crear(run_id, "VoIP", "Asterisk AMI", "SKIPPED", "ami", zona,
                                              detalle="falta el secreto AMI"))
        else:
            try:
                activas = sondas.ami(host, int(config.voip.get("ami_puerto", 5038)),
                                     config.voip.get("ami_usuario", "monitor"), secreto, config.timeout)
                resultados.append(Resultado.crear(run_id, "VoIP", "Asterisk AMI", "OK", "ami", zona,
                                                  llamadas_activas=activas, detalle=f"{activas} canales activos"))
            except (sondas.SondaError, OSError) as exc:
                resultados.append(Resultado.crear(run_id, "VoIP", "Asterisk AMI", "ERROR", "ami", zona,
                                                  detalle=str(exc)[:180]))
    resultados.extend(sondas.cdr(config.voip["cdr"], run_id, zona))
    return resultados


def _leer(ruta: str, config: Config) -> tuple[str | None, str | None]:
    return sondas.leer_snapshot(ruta, config.frescura)


def _estado_json(config: Config, nombre: str) -> dict:
    ruta = config.datos / "estado" / nombre
    if not ruta.is_file():
        return {}
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _guardar_json(config: Config, nombre: str, datos: dict) -> None:
    ruta = config.datos / "estado" / nombre
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(".tmp")
    temporal.write_text(json.dumps(datos, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(temporal, ruta)


def _seguridad(config: Config, run_id: str) -> list[Resultado]:
    zona = _zona(config)
    seguridad_cfg = config.seguridad
    resultados: list[Resultado] = []
    eventos = 0

    texto, problema = _leer(seguridad_cfg["iptables_save"], config)
    if texto:
        actual = seguridad.parse_iptables(texto)
        anterior = _estado_json(config, "contadores.json")
        deltas = seguridad.delta_iptables(actual, anterior)
        _guardar_json(config, "contadores.json", {clave: {"pkts": d["pkts"], "bytes": d["bytes"]} for clave, d in actual.items()})
        for delta in deltas[:200]:
            eventos += 1
            resultados.append(
                Resultado.crear(
                    run_id, "Seguridad", delta.get("dst") or "firewall", "DROPPED", "archivo", zona,
                    evento_seguridad="VLAN30_BLOCKED" if "VLAN30" in delta["regla"] else "VLAN40_BLOCKED",
                    ip_origen=delta.get("src"), ip_destino=delta.get("dst"), paquetes_delta=delta["delta_pkts"],
                    bytes_delta=delta["delta_bytes"], detalle=f"{delta['cadena']} {delta['regla']}"[:200],
                )
            )
        if not deltas:
            resultados.append(Resultado.crear(run_id, "Seguridad", "firewall", "OK", "archivo", zona,
                                              detalle="sin cambios en contadores de iptables"))
    else:
        resultados.append(Resultado.crear(run_id, "Seguridad", "firewall", problema or "SKIPPED", "archivo", zona,
                                          detalle="snapshot de iptables no disponible"))

    for ruta, tipo in ((seguridad_cfg["fail2ban_estado"], "estado"), (seguridad_cfg["fail2ban_log"], "log"),
                       (seguridad_cfg["auth_log"], "auth"), (seguridad_cfg["kern_log"], "kern")):
        texto, problema = _leer(ruta, config)
        if texto is None:
            continue
        if tipo == "estado":
            datos = seguridad.parse_fail2ban(texto)
            for ip in datos["baneadas"]:
                eventos += 1
                resultados.append(Resultado.crear(run_id, "Seguridad", ip, "DROPPED", "archivo", zona,
                                                  evento_seguridad="FAIL2BAN_BAN", ip_origen=ip,
                                                  detalle=f"baneada; {datos['actuales']} activas"))
        elif tipo == "log":
            for evento in seguridad.parse_fail2ban_log(texto)[:100]:
                eventos += 1
                resultados.append(Resultado.crear(run_id, "Seguridad", evento["ip"], "DROPPED", "archivo", zona,
                                                  evento_seguridad="FAIL2BAN_BAN", ip_origen=evento["ip"],
                                                  timestamp_evento=evento["ts"], linea_evento=evento["linea"],
                                                  detalle="Ban en fail2ban"))
        elif tipo == "auth":
            for evento in seguridad.parse_auth(texto)[:100]:
                eventos += 1
                resultados.append(Resultado.crear(run_id, "Seguridad", evento["ip"], "DROPPED", "archivo", zona,
                                                  evento_seguridad="SSH_FAIL", ip_origen=evento["ip"],
                                                  timestamp_evento=evento["ts"], linea_evento=evento["linea"],
                                                  detalle="Fallo de autenticación SSH"))
        elif tipo == "kern":
            for evento in seguridad.parse_kern(texto, seguridad_cfg.get("prefijos_iptables", []))[:100]:
                eventos += 1
                resultados.append(Resultado.crear(run_id, "Seguridad", evento.get("dst") or "firewall", "DROPPED",
                                                  "archivo", zona, evento_seguridad=evento["evento"],
                                                  ip_origen=evento.get("src"), ip_destino=evento.get("dst"),
                                                  timestamp_evento=evento["ts"], linea_evento=evento["linea"],
                                                  detalle=evento["linea"][:200]))
        if problema:
            LOG.info("Seguridad %s: %s", ruta, problema)

    anterior_red = _estado_json(config, "red.json")
    actual_red: dict[str, int] = {}
    for ruta in (seguridad_cfg["netstat"], seguridad_cfg["snmp"]):
        texto, _ = _leer(ruta, config)
        if texto:
            actual_red.update(seguridad.parse_netstat(texto) if "netstat" in ruta else seguridad.parse_snmp(texto))
    _guardar_json(config, "red.json", actual_red)
    for clave, valor in actual_red.items():
        anterior = int(anterior_red.get(clave, valor))
        if valor - anterior > 0:
            eventos += 1
            resultados.append(Resultado.crear(run_id, "Seguridad", "kernel", "DROPPED", "archivo", zona,
                                              evento_seguridad="SYN_FLOOD", paquetes_delta=valor - anterior,
                                              detalle=f"{clave} +{valor - anterior}"))

    if not resultados:
        resultados.append(Resultado.crear(run_id, "Seguridad", "VM2", "SKIPPED", "archivo", zona,
                                          detalle="sin snapshots de seguridad"))
    return resultados


def _dhcp(config: Config, run_id: str) -> list[Resultado]:
    return sondas.dhcp(config.dhcp, config.frescura, run_id, _zona(config))


def _qos(config: Config, run_id: str) -> list[Resultado]:
    zona = _zona(config)
    resultados = [sondas.iperf(config.qos["servidor_iperf"], int(config.qos.get("duracion_s", 10)),
                               config.qos.get("ancho_banda", "20M"), max(config.timeout, 20), zona, run_id)]
    captura = config.datos / "capturas" / "qos.pcap"
    resultados.extend(sondas.dscp_pcap(str(captura), run_id, zona))
    return resultados


def _simular(config: Config, run_id: str) -> list[Resultado]:
    zona = _zona(config)
    resultados: list[Resultado] = []
    for camara in config.camaras.get("lista", []):
        resultados.append(Resultado.crear(run_id, "Camaras", camara["ip"], "ONLINE", "simulado", zona,
                                          nombre_recurso=camara.get("nombre"), vlan=camara.get("vlan"),
                                          zona=camara.get("zona"), tiempo_respuesta_ms=2.4,
                                          perdida_paquetes_pct=0.0, puerto=config.camaras.get("rtsp_puerto", 554),
                                          detalle="4/4 paquetes; RTSP 554 abierto"))
    resultados.append(Resultado.crear(run_id, "PortalWeb", "portal", "OK", "simulado", zona,
                                      http_status=200, tiempo_respuesta_ms=384.0,
                                      detalle="HTTP 200; TTFB 120 ms"))
    resultados.append(Resultado.crear(run_id, "PortalWeb", "Apache", "OK", "simulado", zona,
                                      detalle="systemctl: active"))
    resultados.append(Resultado.crear(run_id, "BaseDatos", "10.30.50.5", "OK", "simulado", zona,
                                      puerto=5432, tiempo_respuesta_ms=6.2, detalle="SELECT 1 OK"))
    resultados.append(Resultado.crear(run_id, "VoIP", "10.30.60.10", "OK", "simulado", zona,
                                      sip_code=200, puerto=5060, detalle="SIP 200"))
    resultados.append(Resultado.crear(run_id, "VoIP", "Asterisk AMI", "OK", "simulado", zona,
                                      llamadas_activas=2, detalle="2 canales activos"))
    for indice in range(3):
        resultados.append(Resultado.crear(run_id, "VoIP", "Asterisk", "OK", "simulado", zona,
                                          sip_code=200, duracion_llamada_s=42.0 + indice,
                                          linea_evento=f"{run_id}-cdr-{indice}",
                                          detalle=f"1001 -> 2001 (ANSWERED) #{indice + 1}"))
    resultados.append(Resultado.crear(run_id, "Seguridad", "10.30.30.50", "DROPPED", "simulado", zona,
                                      evento_seguridad="SSH_FAIL", ip_origen="10.30.30.50",
                                      detalle="Fallo de autenticación SSH"))
    resultados.append(Resultado.crear(run_id, "Seguridad", "10.30.30.12", "DROPPED", "simulado", zona,
                                      evento_seguridad="VLAN30_BLOCKED", ip_origen="10.30.30.50",
                                      ip_destino="10.30.30.12", paquetes_delta=12, bytes_delta=720,
                                      detalle="INPUT -p tcp --dport 554 -j DROP"))
    resultados.append(Resultado.crear(run_id, "Seguridad", "10.30.40.77", "DROPPED", "simulado", zona,
                                      evento_seguridad="FAIL2BAN_BAN", ip_origen="10.30.40.77",
                                      detalle="baneada; 1 activas"))
    resultados.append(Resultado.crear(run_id, "DHCP", "isc-dhcp-server", "OK", "simulado", zona,
                                      detalle="servicio active; 12 leases activos"))
    if config.qos.get("habilitado"):
        resultados.append(Resultado.crear(run_id, "QoS", config.qos["servidor_iperf"], "OK", "simulado", zona,
                                          perdida_paquetes_pct=0.12, jitter_ms=1.4, ancho_banda_mbps=19.6,
                                          detalle="iperf3 UDP 20M"))
        resultados.append(Resultado.crear(run_id, "QoS", "captura", "OK", "simulado", zona, dscp=46,
                                          detalle="320 paquetes de 500 con DSCP 46"))
    return resultados


def _bloqueo(ruta: Path):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(ruta, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        if fcntl is not None:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:  # Windows: bloquea el primer byte del archivo
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        return descriptor
    except OSError as exc:
        os.close(descriptor)
        if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
            return None
        raise


def _desbloqueo(descriptor: int) -> None:
    try:
        if fcntl is not None:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        else:  # Windows
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
    finally:
        os.close(descriptor)


def ejecutar(config: Config, simular: bool = False, solo: set[str] | None = None, dry_run: bool = False) -> int:
    zona = _zona(config)
    inicio_local = datetime.now(ZoneInfo(zona))
    run_id = ("sim-" if simular else "") + uuid.uuid4().hex
    modulos = {nombre for nombre in ("camaras", "portal", "base_datos", "voip", "qos", "seguridad", "dhcp")
               if config.modulo_habilitado(nombre) and (not solo or nombre in solo)}
    if dry_run:
        print(f"run_id={run_id} módulos={','.join(sorted(modulos)) or 'ninguno'} simular={simular}")
        print(f"datos={config.datos}")
        return 0
    if not modulos:
        print("No hay módulos habilitados para esta corrida.")
        return 2

    descriptor = _bloqueo(config.datos / ".lock")
    if descriptor is None:
        print("Otra corrida está en curso; se omite esta muestra.")
        return 0
    try:
        if simular:
            resultados = _simular(config, run_id)
            resultados = [
                r for r in resultados
                if {"Camaras": "camaras", "PortalWeb": "portal", "BaseDatos": "base_datos",
                    "VoIP": "voip", "QoS": "qos", "Seguridad": "seguridad",
                    "DHCP": "dhcp"}.get(r.modulo) in modulos
            ]
        else:
            if config.recoleccion.get("habilitado") and config.recoleccion.get("recolectar_antes", True):
                for error in recoleccion.recolectar(config):
                    LOG.warning("Recolección: %s", error)
            tareas = []
            if "camaras" in modulos:
                for camara in config.camaras.get("lista", []):
                    tareas.append(("Camaras", camara["ip"], lambda c=camara: _camara(config, c, run_id)))
            if "portal" in modulos:
                tareas.append(("PortalWeb", "portal", lambda: _portal(config, run_id)))
            if "base_datos" in modulos:
                tareas.append(("BaseDatos", config.base_datos["host"], lambda: _base_datos(config, run_id)))
            if "voip" in modulos:
                tareas.append(("VoIP", config.voip["host"], lambda: _voip(config, run_id)))
            if "seguridad" in modulos:
                tareas.append(("Seguridad", "VM2", lambda: _seguridad(config, run_id)))
            if "dhcp" in modulos:
                tareas.append(("DHCP", "isc-dhcp-server", lambda: _dhcp(config, run_id)))
            if "qos" in modulos:
                tareas.append(("QoS", config.qos["servidor_iperf"], lambda: _qos(config, run_id)))

            resultados = []
            with ThreadPoolExecutor(max_workers=int(config.general["max_workers"])) as pool:
                futuros = {pool.submit(funcion): (modulo, target) for modulo, target, funcion in tareas}
                for futuro in as_completed(futuros):
                    modulo, target = futuros[futuro]
                    try:
                        resultados.extend(futuro.result())
                    except Exception as exc:  # noqa: BLE001
                        LOG.exception("Sonda %s/%s falló", modulo, target)
                        resultados.append(_error(run_id, modulo, target, exc, zona))
        resultados.sort(key=lambda r: (r.modulo, r.recurso_target, r.timestamp_utc))
        archivo = escribir_jsonl(resultados, config, inicio_local)
        exitoso = sum(1 for r in resultados if r.estado in EXITO)
        fallidos = len(resultados) - exitoso
        print(f"run_id={run_id} filas={len(resultados)} ok={exitoso} con_problema={fallidos}")
        print(f"JSONL: {archivo}")
        return 0 if fallidos == 0 else 1
    finally:
        _desbloqueo(descriptor)

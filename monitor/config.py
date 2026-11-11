"""Configuración TOML y validación del monitor."""

from __future__ import annotations

import copy
import ipaddress
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import inventario as inventario_mod

DEFAULTS = {
    "general": {
        "zona_horaria": "America/Bogota",
        "timeout_s": 5,
        "timeout_total_s": 120,
        "reintentos": 2,
        "max_workers": 12,
        "directorio_datos": "data",
        "inventario": "inventario.csv",
        "retencion_dias": 180,
        "comprimir_dias": 7,
        "intervalo_s": 300,
        "frescura_max_s": 900,
        "version_esquema": 1,
    },
    "salida": {"csv": True, "jsonl": True, "codificacion": "utf-8-sig"},
    "recoleccion": {
        "habilitado": False,
        "usuario": "monitor",
        "clave": "/etc/monitor/id_ed25519",
        "known_hosts": "/etc/monitor/known_hosts",
        "timeout_s": 15,
        "recolectar_antes": True,
        "hosts": {},
    },
    "camaras": {"habilitado": True, "ping_paquetes": 4, "rtsp_puerto": 554, "lista": []},
    "portal": {
        "habilitado": True,
        "url": "https://10.30.50.5/",
        "timeout_s": 15,
        "umbral_degradado_s": 10.0,
        "verificar_tls": False,
        "estado_apache": "data/entradas/vm2/apache.txt",
    },
    "base_datos": {
        "habilitado": True,
        "host": "10.30.50.5",
        "puerto": 5432,
        "base": "portocaribe",
        "usuario": "monitor",
        "pgpassfile": "/etc/monitor/pgpass",
    },
    "voip": {
        "habilitado": True,
        "host": "10.30.60.10",
        "sip_puerto": 5060,
        "ami": True,
        "ami_puerto": 5038,
        "ami_usuario": "monitor",
        "ami_secreto_env": "ASTERISK_AMI_SECRET",
        "cdr": "data/entradas/vm1/cdr.csv",
    },
    "qos": {
        "habilitado": False,
        "servidor_iperf": "10.30.50.20",
        "duracion_s": 10,
        "ancho_banda": "20M",
        "interfaz": "eth1",
    },
    "seguridad": {
        "habilitado": True,
        "modo": "archivo",
        "entradas": "data/entradas/vm2",
        "iptables_save": "data/entradas/vm2/iptables.save",
        "fail2ban_estado": "data/entradas/vm2/fail2ban.txt",
        "fail2ban_log": "data/entradas/vm2/fail2ban.log",
        "auth_log": "data/entradas/vm2/auth.log",
        "kern_log": "data/entradas/vm2/kern.log",
        "netstat": "data/entradas/vm2/netstat.txt",
        "snmp": "data/entradas/vm2/snmp.txt",
        "prefijos_iptables": ["VLAN30-DROP:", "VLAN40-DROP:"],
        "jail": "sshd",
    },
    "dhcp": {
        "habilitado": True,
        "modo": "archivo",
        "entradas": "data/entradas/vm2",
        "leases": "data/entradas/vm2/dhcpd.leases",
        "estado": "data/entradas/vm2/dhcp_estado.txt",
    },
}

_RUTAS = (
    ("portal", "estado_apache"),
    ("voip", "cdr"),
    ("seguridad", "entradas"),
    ("seguridad", "iptables_save"),
    ("seguridad", "fail2ban_estado"),
    ("seguridad", "fail2ban_log"),
    ("seguridad", "auth_log"),
    ("seguridad", "kern_log"),
    ("seguridad", "netstat"),
    ("seguridad", "snmp"),
    ("dhcp", "entradas"),
    ("dhcp", "leases"),
    ("dhcp", "estado"),
)


@dataclass
class Config:
    ruta: Path
    general: dict = field(default_factory=dict)
    salida: dict = field(default_factory=dict)
    recoleccion: dict = field(default_factory=dict)
    camaras: dict = field(default_factory=dict)
    portal: dict = field(default_factory=dict)
    base_datos: dict = field(default_factory=dict)
    voip: dict = field(default_factory=dict)
    qos: dict = field(default_factory=dict)
    seguridad: dict = field(default_factory=dict)
    dhcp: dict = field(default_factory=dict)
    inventario: dict = field(default_factory=dict)

    @property
    def datos(self) -> Path:
        return Path(self.general["directorio_datos"])

    @property
    def zona(self) -> ZoneInfo:
        return ZoneInfo(self.general["zona_horaria"])

    @property
    def timeout(self) -> float:
        return float(self.general["timeout_s"])

    @property
    def timeout_total(self) -> float:
        return float(self.general["timeout_total_s"])

    @property
    def intentos(self) -> int:
        return max(1, int(self.general.get("reintentos", 2)))

    @property
    def frescura(self) -> float:
        return float(self.general["frescura_max_s"])

    def modulo_habilitado(self, nombre: str) -> bool:
        return bool(self.__dict__[nombre].get("habilitado", False))

    def ficha(self, ip: str, tipo: str | None = None) -> dict:
        """Metadatos del inventario para una IP (vacío si no está listada)."""
        return inventario_mod.buscar(self.inventario, ip, tipo) or {}


def _fusionar(base: dict, encima: dict) -> dict:
    resultado = copy.deepcopy(base)
    for clave, valor in encima.items():
        if isinstance(valor, dict) and isinstance(resultado.get(clave), dict):
            resultado[clave] = _fusionar(resultado[clave], valor)
        else:
            resultado[clave] = valor
    return resultado


def _resolver(ruta: Path, valor: str) -> str:
    camino = Path(valor).expanduser()
    if not camino.is_absolute():
        camino = (ruta.parent / camino).resolve()
    return str(camino)


def cargar_config(ruta: str | Path) -> Config:
    archivo = Path(ruta).expanduser().resolve()
    with archivo.open("rb") as manejador:
        crudo = tomllib.load(manejador)

    datos = _fusionar(DEFAULTS, crudo)
    datos["general"]["directorio_datos"] = _resolver(
        archivo, datos["general"]["directorio_datos"]
    )
    datos["general"]["inventario"] = _resolver(archivo, datos["general"]["inventario"])

    for seccion, clave in _RUTAS:
        datos[seccion][clave] = _resolver(archivo, datos[seccion][clave])

    if "hosts" not in datos["recoleccion"]:
        datos["recoleccion"]["hosts"] = {}
    for nombre in ("vm1", "vm2"):
        if nombre in crudo.get("recoleccion", {}):
            host = crudo["recoleccion"][nombre]
            datos["recoleccion"]["hosts"][nombre] = host
    datos["recoleccion"]["hosts"] = {
        nombre: valor
        for nombre, valor in datos["recoleccion"]["hosts"].items()
        if nombre not in ("habilitado", "usuario", "clave", "known_hosts", "timeout_s", "recolectar_antes")
    }

    config = Config(ruta=archivo, **{clave: datos[clave] for clave in DEFAULTS})
    config.inventario = inventario_mod.cargar(datos["general"]["inventario"])
    for camara in config.camaras.get("lista", []):
        inventario_mod.comparar(
            "camaras",
            camara.get("ip", ""),
            inventario_mod.buscar(config.inventario, camara.get("ip", ""), "camara"),
            nombre=camara.get("nombre"),
            vlan=camara.get("vlan"),
            zona=camara.get("zona"),
        )
    validar(config)
    return config


def validar(config: Config) -> None:
    general = config.general
    if general["timeout_s"] <= 0 or general["timeout_total_s"] <= 0:
        raise ValueError("Los timeouts deben ser positivos")
    if general["max_workers"] < 1:
        raise ValueError("max_workers debe ser mayor que cero")
    try:
        config.zona
    except ZoneInfoNotFoundError as exc:
        raise ValueError("zona_horaria inválida") from exc

    for numero, camara in enumerate(config.camaras.get("lista", []), 1):
        try:
            ipaddress.ip_address(camara["ip"])
        except (KeyError, ValueError) as exc:
            raise ValueError(f"Cámara #{numero}: IP inválida") from exc
        if not camara.get("nombre"):
            raise ValueError(f"Cámara #{numero}: falta el nombre")

    for seccion, puerto in (
        ("portal", 443),
        ("base_datos", config.base_datos.get("puerto", 5432)),
        ("voip", config.voip.get("sip_puerto", 5060)),
    ):
        if seccion == "base_datos" and not 1 <= int(puerto) <= 65535:
            raise ValueError("Puerto de PostgreSQL inválido")

    if not any(config.modulo_habilitado(nombre) for nombre in ("camaras", "portal", "base_datos", "voip", "qos", "seguridad", "dhcp")):
        raise ValueError("No hay ningún módulo habilitado")

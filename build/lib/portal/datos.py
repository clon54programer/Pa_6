"""Esquema SQLite, datos de demostración y consultas del portal."""

from __future__ import annotations

import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, time as hora, timedelta
from pathlib import Path

from . import cripto

ESTADOS = {
    "EN_TRANSITO": "En tránsito",
    "EN_MUELLE": "En muelle",
    "ALMACENADO": "Almacenado en bodega",
    "EN_DESPACHO": "En proceso de despacho",
    "DESPACHADO": "Despachado",
}

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY,
    usuario TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    hash TEXT NOT NULL,
    rol TEXT NOT NULL DEFAULT 'cliente',
    activo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS intentos (
    id INTEGER PRIMARY KEY,
    ip TEXT NOT NULL,
    usuario TEXT NOT NULL,
    ts REAL NOT NULL,
    exito INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_intentos_ip_ts ON intentos(ip, ts);
CREATE INDEX IF NOT EXISTS idx_intentos_usuario_ts ON intentos(usuario, ts);

CREATE TABLE IF NOT EXISTS contenedores (
    numero TEXT PRIMARY KEY,
    bl TEXT NOT NULL,
    orden TEXT NOT NULL,
    estado TEXT NOT NULL,
    importador TEXT NOT NULL,
    buque TEXT NOT NULL,
    arribo TEXT NOT NULL,
    muelle TEXT NOT NULL,
    bodega TEXT NOT NULL,
    actualizado TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_contenedores_bl ON contenedores(bl);
CREATE INDEX IF NOT EXISTS idx_contenedores_orden ON contenedores(orden);

CREATE TABLE IF NOT EXISTS hitos (
    id INTEGER PRIMARY KEY,
    numero TEXT NOT NULL REFERENCES contenedores(numero),
    orden INTEGER NOT NULL,
    ts TEXT NOT NULL,
    titulo TEXT NOT NULL,
    detalle TEXT NOT NULL,
    ubicacion TEXT NOT NULL,
    completado INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_hitos_numero ON hitos(numero, orden);

CREATE TABLE IF NOT EXISTS avisos (
    id INTEGER PRIMARY KEY,
    titulo TEXT NOT NULL,
    detalle TEXT NOT NULL,
    severidad TEXT NOT NULL,
    desde TEXT NOT NULL,
    hasta TEXT NOT NULL
);
"""

_LETRAS = {}
_valor = 10
for _letra in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    while _valor % 11 == 0:
        _valor += 1
    _LETRAS[_letra] = _valor
    _valor += 1

_BASES = [
    ("CSQU", "305438", "BL-2026-001", "OD-2026-001", "EN_MUELLE", "Importadora del Caribe S.A.S.", "MSC Aurora", "Muelle 2", 2),
    ("MSCU", "123456", "BL-2026-002", "OD-2026-002", "ALMACENADO", "Comercializadora Andina Ltda.", "CMA CGM Toscana", "Muelle 1", 4),
    ("TGHU", "456789", "BL-2026-003", "OD-2026-003", "EN_DESPACHO", "Distribuciones del Norte S.A.S.", "Maersk Copenhague", "Muelle 3", 6),
    ("HLXU", "234567", "BL-2026-004", "OD-2026-004", "DESPACHADO", "Agroexportadora del Sinú", "Hapag Lloyd Berlín", "Muelle 2", 8),
    ("CMAU", "345678", "BL-2026-005", "OD-2026-005", "ALMACENADO", "Ferretería Central de Bolívar", "MSC Sofía", "Muelle 1", 3),
    ("ONEU", "567890", "BL-2026-006", "OD-2026-006", "EN_MUELLE", "Textiles de Bolívar S.A.S.", "ONE Amazon", "Muelle 4", 1),
    ("SEGU", "678901", "BL-2026-007", "OD-2026-007", "EN_TRANSITO", "Química Caribe Ltda.", "Ever Given", "Muelle 3", -1),
    ("FCIU", "789012", "BL-2026-008", "OD-2026-008", "EN_DESPACHO", "Exportadora Mamonal S.A.S.", "COSCO Pacífico", "Muelle 2", 5),
]

_COMPLETADOS = {
    "EN_TRANSITO": 0,
    "EN_MUELLE": 2,
    "ALMACENADO": 3,
    "EN_DESPACHO": 5,
    "DESPACHADO": 6,
}


def digito_verificador(numero: str) -> int:
    """Calcula el dígito verificador ISO 6346 de 10 caracteres."""

    if len(numero) != 10:
        raise ValueError("El número base debe tener 10 caracteres")
    suma = 0
    for posicion, caracter in enumerate(numero.upper()):
        if caracter.isalpha():
            valor = _LETRAS.get(caracter)
        elif caracter.isdigit():
            valor = int(caracter)
        else:
            valor = None
        if valor is None:
            raise ValueError(f"Carácter no válido en el número: {caracter!r}")
        suma += valor * (2**posicion)
    resto = suma % 11
    return 0 if resto == 10 else resto


def es_numero_iso(numero: str) -> bool:
    """Valida formato y dígito verificador ISO 6346."""

    if not re.fullmatch(r"[A-Z]{4}\d{7}", numero):
        return False
    try:
        return digito_verificador(numero[:10]) == int(numero[10])
    except ValueError:
        return False


def normalizar_consulta(texto: str) -> str:
    return " ".join(texto.strip().upper().split())


class BaseDatos:
    def __init__(self, ruta: str | Path):
        self.ruta = Path(ruta)

    @contextmanager
    def conexion(self):
        con = sqlite3.connect(self.ruta, timeout=5)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def inicializar(self) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        with self.conexion() as con:
            con.execute("PRAGMA journal_mode = WAL")
            con.executescript(_ESQUEMA)

    def sembrar(self, fecha_base: date | None = None, password_demo: str | None = None) -> None:
        hoy = fecha_base or date.today()
        password = password_demo or os.environ.get("PORTAL_DEMO_PASSWORD", "Porto2026*")
        with self.conexion() as con:
            existente = con.execute(
                "SELECT 1 FROM usuarios WHERE usuario = ?", ("cliente.demo",)
            ).fetchone()
            if existente is None:
                con.execute(
                    "INSERT INTO usuarios (usuario, nombre, hash, rol) VALUES (?, ?, ?, ?)",
                    ("cliente.demo", "Cliente de demostración", cripto.hash_password(password), "cliente"),
                )
            if con.execute("SELECT COUNT(*) FROM contenedores").fetchone()[0] == 0:
                self._sembrar_contenedores(con, hoy)
            if con.execute("SELECT COUNT(*) FROM avisos").fetchone()[0] == 0:
                self._sembrar_avisos(con, hoy)

    def _sembrar_contenedores(self, con: sqlite3.Connection, hoy: date) -> None:
        for indice, base in enumerate(_BASES):
            prefijo, seis, bl, orden, estado, importador, buque, muelle, dias = base
            numero = prefijo + seis + str(digito_verificador(prefijo + seis))
            arribo = hoy - timedelta(days=dias)
            actualizado = datetime.combine(hoy, hora(8, 0)) + timedelta(hours=indice)
            con.execute(
                """
                INSERT INTO contenedores
                    (numero, bl, orden, estado, importador, buque, arribo, muelle, bodega, actualizado)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    numero,
                    bl,
                    orden,
                    estado,
                    importador,
                    buque,
                    arribo.isoformat(),
                    muelle,
                    "Bodega de 12.000 m²",
                    actualizado.isoformat(timespec="minutes"),
                ),
            )
            hitos = [
                ("Arribo del buque", f"El buque {buque} arribó a la bahía de Cartagena.", "Bahía de Cartagena", 0),
                ("Descarga en muelle", f"Descarga completada en {muelle}.", muelle, 4),
                ("Ingreso a bodega", "Contenedor almacenado en la bodega de 12.000 m².", "Bodega principal", 8),
                ("Inspección aduanera", "Inspección documental y física finalizada.", "Zona aduanera", 24),
                ("Proceso de despacho", "Documentos de salida en revisión.", "Oficina de despacho", 48),
                ("Salida por garita", "Contenedor entregado al transportador.", "Garita principal", 72),
            ]
            completados = _COMPLETADOS.get(estado, 0)
            inicio = datetime.combine(arribo, hora(6, 0))
            for posicion, (titulo, detalle, ubicacion, horas) in enumerate(hitos):
                con.execute(
                    """
                    INSERT INTO hitos (numero, orden, ts, titulo, detalle, ubicacion, completado)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        numero,
                        posicion + 1,
                        (inicio + timedelta(hours=horas)).isoformat(timespec="minutes"),
                        titulo,
                        detalle,
                        ubicacion,
                        1 if posicion < completados else 0,
                    ),
                )

    def _sembrar_avisos(self, con: sqlite3.Connection, hoy: date) -> None:
        avisos = [
            (
                "Congestión en Muelle 2",
                "Dos buques están operando simultáneamente. Los tiempos de descarga pueden aumentar hasta 45 minutos.",
                "advertencia",
                hoy - timedelta(days=1),
                hoy + timedelta(days=5),
            ),
            (
                "Ventana de despacho extendida",
                "La garita principal atenderá hasta las 22:00 durante esta semana para agilizar entregas.",
                "info",
                hoy,
                hoy + timedelta(days=7),
            ),
            (
                "Mantenimiento de la red de muelles",
                "El sábado se realizará mantenimiento programado. Las consultas seguirán disponibles.",
                "critico",
                hoy - timedelta(days=1),
                hoy + timedelta(days=3),
            ),
        ]
        for titulo, detalle, severidad, desde, hasta in avisos:
            con.execute(
                "INSERT INTO avisos (titulo, detalle, severidad, desde, hasta) VALUES (?, ?, ?, ?, ?)",
                (titulo, detalle, severidad, desde.isoformat(), hasta.isoformat()),
            )

    def obtener_usuario(self, usuario: str) -> sqlite3.Row | None:
        with self.conexion() as con:
            return con.execute(
                "SELECT usuario, nombre, hash, activo FROM usuarios WHERE usuario = ?",
                (usuario,),
            ).fetchone()

    def buscar_contenedor(self, consulta: str) -> dict | None:
        candidatos = [consulta]
        compacto = consulta.replace(" ", "").replace("-", "")
        if compacto != consulta:
            candidatos.append(compacto)
        with self.conexion() as con:
            fila = None
            for candidato in candidatos:
                fila = con.execute(
                    """
                    SELECT numero, bl, orden, estado, importador, buque, arribo, muelle, bodega, actualizado
                    FROM contenedores
                    WHERE numero = ? OR bl = ? OR orden = ?
                    """,
                    (candidato, candidato, candidato),
                ).fetchone()
                if fila is not None:
                    break
            if fila is None:
                return None
            hitos = con.execute(
                """
                SELECT orden, ts, titulo, detalle, ubicacion, completado
                FROM hitos WHERE numero = ? ORDER BY orden
                """,
                (fila["numero"],),
            ).fetchall()
        return {"contenedor": dict(fila), "hitos": [dict(h) for h in hitos]}

    def listar_avisos(self, hoy: date | None = None) -> list[dict]:
        referencia = (hoy or date.today()).isoformat()
        with self.conexion() as con:
            filas = con.execute(
                """
                SELECT titulo, detalle, severidad, desde, hasta
                FROM avisos
                WHERE desde <= ? AND hasta >= ?
                ORDER BY CASE severidad WHEN 'critico' THEN 0 WHEN 'advertencia' THEN 1 ELSE 2 END, desde
                """,
                (referencia, referencia),
            ).fetchall()
        return [dict(fila) for fila in filas]

    def registrar_intento(self, ip: str, usuario: str, exito: bool, ahora: float) -> None:
        with self.conexion() as con:
            con.execute(
                "INSERT INTO intentos (ip, usuario, ts, exito) VALUES (?, ?, ?, ?)",
                (ip, usuario, float(ahora), 1 if exito else 0),
            )

    def fallos_recientes(self, ip: str, usuario: str, desde: float) -> tuple[int, float | None]:
        with self.conexion() as con:
            fila = con.execute(
                """
                SELECT COUNT(*) AS total, MAX(ts) AS ultimo
                FROM intentos
                WHERE ip = ? AND usuario = ? AND exito = 0 AND ts >= ?
                """,
                (ip, usuario, float(desde)),
            ).fetchone()
        return int(fila["total"]), fila["ultimo"]

    def fallos_por_ip(self, ip: str, desde: float) -> tuple[int, float | None]:
        with self.conexion() as con:
            fila = con.execute(
                """
                SELECT COUNT(*) AS total, MAX(ts) AS ultimo
                FROM intentos
                WHERE ip = ? AND exito = 0 AND ts >= ?
                """,
                (ip, float(desde)),
            ).fetchone()
        return int(fila["total"]), fila["ultimo"]

    def limpiar_fallos(self, ip: str, usuario: str) -> None:
        with self.conexion() as con:
            con.execute(
                "DELETE FROM intentos WHERE ip = ? AND usuario = ? AND exito = 0",
                (ip, usuario),
            )

    def limpiar_intentos(self, antes: float) -> None:
        with self.conexion() as con:
            con.execute("DELETE FROM intentos WHERE ts < ?", (float(antes),))

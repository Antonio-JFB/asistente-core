"""Topes de uso para que el gasto en la API no se salga de control.

Dos topes, ambos por día y por proceso (se reinician al cambiar de día o al reiniciar el servicio):
  ASISTENTE_LIMITE_USUARIO_DIA  consultas por persona (default 50; 0 = sin límite)
  ASISTENTE_TOPE_DIARIO_USD     gasto total estimado del asistente (default 5; 0 = sin tope)
Los dashboards con un solo proceso (uvicorn --workers 1) quedan cubiertos; con varios procesos
cada uno lleva su propia cuenta. El tope real de gasto se pone además en la consola de Anthropic.
"""
from __future__ import annotations

import datetime
import os
import threading


def _numero(nombre: str, defecto: float) -> float:
    try:
        return float(os.getenv(nombre, "").strip() or defecto)
    except ValueError:
        return defecto


class Limites:
    def __init__(self):
        self._lock = threading.Lock()
        self._dia = None
        self._consultas: dict[str, int] = {}
        self._gasto = 0.0

    def _rotar(self):
        hoy = datetime.date.today()
        if hoy != self._dia:
            self._dia, self._consultas, self._gasto = hoy, {}, 0.0

    def revisar(self, usuario: str) -> str | None:
        """Cuenta una consulta. Regresa el mensaje a mostrar si ya se alcanzó un tope, o None si procede."""
        tope_usd = _numero("ASISTENTE_TOPE_DIARIO_USD", 5)
        limite = int(_numero("ASISTENTE_LIMITE_USUARIO_DIA", 50))
        with self._lock:
            self._rotar()
            if tope_usd and self._gasto >= tope_usd:
                return ("El asistente alcanzó su límite de uso de hoy. Vuelve a intentarlo mañana "
                        "o avisa a quien administra el dashboard.")
            if limite and self._consultas.get(usuario, 0) >= limite:
                return f"Llegaste al límite de {limite} consultas por día. Vuelve a intentarlo mañana."
            self._consultas[usuario] = self._consultas.get(usuario, 0) + 1
            return None

    def registrar_gasto(self, costo: float | None):
        if not costo:
            return
        with self._lock:
            self._rotar()
            self._gasto += costo

    @property
    def gasto_hoy(self) -> float:
        with self._lock:
            self._rotar()
            return self._gasto


limites = Limites()

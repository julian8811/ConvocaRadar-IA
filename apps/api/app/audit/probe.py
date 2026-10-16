"""Probe SIMULADO opt-in (Fase 2 simulada): cero red real.

Nunca se importa ni se ejecuta de forma implicita: solo via CLI
`--mode probe`. Tres conectores simulados con resultados fijos
deterministicos sobre fixtures en memoria. Pilotos reales: NO sin
consentimiento explicito (no implementados aqui).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SimulatedProbe:
    source_key: str
    reachable: bool
    status_code: int | None
    latency_ms: int
    note: str


SIMULATED_CONNECTORS: dict[str, SimulatedProbe] = {
    "ascun-convocatorias": SimulatedProbe(
        "ascun-convocatorias", True, 200, 320,
        "fixture: pagina lista con 67 fichas simuladas"),
    "novo-nordisk-grants": SimulatedProbe(
        "novo-nordisk-grants", True, 200, 410,
        "fixture: portal de grants simulado, paginacion 2 paginas"),
    "generic-rss-sample": SimulatedProbe(
        "generic-rss-sample", False, None, 0,
        "fixture: timeout simulado (transitorio, no es 404)"),
}


def run_simulated_probe(source_keys: list[str] | None = None) -> list[SimulatedProbe]:
    """Ejecuta probes simulados. Sin sockets, sin DNS, sin HTTP."""
    keys = source_keys or sorted(SIMULATED_CONNECTORS)
    unknown = [k for k in keys if k not in SIMULATED_CONNECTORS]
    if unknown:
        raise ValueError(f"conectores no simulados (piloto real requiere consentimiento): "
                         f"{', '.join(unknown)}")
    return [SIMULATED_CONNECTORS[k] for k in keys]

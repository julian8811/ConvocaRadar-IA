"""Nav-label guard: chrome labels must never become opportunities.

Auditoría 2026-10-15: los portales BR (anp/capes/inct) metían labels de
navegación ("Acesso à Informação", "Ações e Programas") como títulos.
"""

from __future__ import annotations


def test_nav_labels_are_noise():
    from app.services.validation import is_noise_title

    assert is_noise_title("Acesso à Informação") is True
    assert is_noise_title("Ações e Programas") is True
    assert is_noise_title("Acoes e Programas") is True


def test_real_calls_still_pass():
    from app.services.validation import is_noise_title

    assert is_noise_title("Beca de investigación en salud pública") is False
    assert is_noise_title("Convocatoria Programa Turismo +Pro") is False

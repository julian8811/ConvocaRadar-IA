"""Smoke test de ConvocaRadar con Playwright.

Prueba login, dashboard, navegación a oportunidades y health check
de la aplicación deployada en producción.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

BASE_URL = "https://convocaradar-web.vercel.app"
API_URL = "https://convotracker-api.onrender.com"

EMAIL = "admin@convocaradar.io"
PASSWORD = "ConvocaRadarLocal123!"

PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = ""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} — {detail}")


def heading(text: str):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}")


# ── API checks first (no browser) ──────────────────────────────────────
heading("API — Health & Auth")

import urllib.request

# API health
try:
    r = urllib.request.urlopen(f"{API_URL}/api/v1/health", timeout=15)
    data = json.loads(r.read())
    check("API health endpoint", data.get("status") == "ok", str(data))
except Exception as e:
    check("API health endpoint", False, str(e))

# Login
try:
    req = urllib.request.Request(
        f"{API_URL}/api/v1/auth/login",
        data=json.dumps({"email": EMAIL, "password": PASSWORD}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    r = urllib.request.urlopen(req, timeout=15)
    data = json.loads(r.read())
    token = data.get("access_token", "")
    check("API login — obtiene token", bool(token), f"token_prefix={token[:20]}...")
except Exception as e:
    check("API login — obtiene token", False, str(e))
    token = ""

# Token validation (call /me)
if token:
    try:
        req = urllib.request.Request(
            f"{API_URL}/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        r = urllib.request.urlopen(req, timeout=15)
        me = json.loads(r.read())
        check("API /me — token válido", me.get("email") == EMAIL, str(me))
    except Exception as e:
        check("API /me — token válido", False, str(e))

# Worker health
try:
    r = urllib.request.urlopen("https://convotracker.onrender.com/health", timeout=15)
    data = json.loads(r.read())
    check("Worker health endpoint", data.get("status") == "ok", str(data))
except Exception as e:
    check("Worker health endpoint", False, str(e))


# ── Playwright browser tests ───────────────────────────────────────────
heading("Browser — Login & Dashboard")

import re
from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(
        viewport={"width": 1440, "height": 900},
        locale="es-CO",
    )
    page = ctx.new_page()

    # 1. Load login page
    try:
        page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=30000)
        check("Login page carga", True)
    except Exception as e:
        check("Login page carga", False, str(e))
        browser.close()
        sys.exit(1)

    # 2. Check heading
    try:
        heading_el = page.get_by_role("heading", name="ConvocaRadar IA")
        check("Título ConvocaRadar IA visible", heading_el.is_visible(timeout=5000))
    except Exception as e:
        check("Título ConvocaRadar IA visible", False, str(e))

    # 3. Fill login form
    try:
        email_input = page.get_by_label(re.compile(r"correo|email", re.I))
        email_input.fill(EMAIL)
        pass_input = page.get_by_label(re.compile(r"contraseña|password", re.I))
        pass_input.fill(PASSWORD)
        check("Formulario login completado", True)
    except Exception as e:
        check("Formulario login completado", False, str(e))

    # 4. Submit login
    try:
        btn = page.get_by_role("button", name=re.compile(r"^Ingresar$", re.I))
        btn.click()
        page.wait_for_url(re.compile(r"/dashboard$"), timeout=30000)
        check("Login exitoso — redirige a /dashboard", True)
    except Exception as e:
        check("Login exitoso — redirige a /dashboard", False, str(e))
        # Take screenshot for debugging
        page.screenshot(path="/tmp/login-fail.png")
        print(f"  📸 Screenshot guardado en /tmp/login-fail.png")
        browser.close()
        sys.exit(1)

    # 5. Dashboard KPIs — wait for data to load
    try:
        # Wait for the health zone KPIs to render (they come from API)
        page.wait_for_timeout(3000)  # let Plotly lazy-load settle
        check("Dashboard carga después de login", True)
    except Exception as e:
        check("Dashboard carga después de login", False, str(e))

    # 6. Check key elements on dashboard
    checks = [
        ("Triage zone '¿Qué hago hoy?'", page.get_by_text(re.compile(r"qu[ée]\s+hago\s+hoy", re.I))),
        ("Health KPIs 'Convocatorias abiertas'", page.get_by_text("Convocatorias abiertas")),
        ("Health KPIs 'Alta compatibilidad'", page.get_by_text("Alta compatibilidad")),
        ("Health KPIs 'Total convocatorias'", page.get_by_text("Total convocatorias")),
    ]
    for label, locator in checks:
        try:
            check(label, locator.first.is_visible(timeout=8000))
        except Exception as e:
            check(label, False, str(e))

    # 7. Navigate to Convocatorias
    try:
        link = page.get_by_role("link", name="Convocatorias", exact=True)
        link.click()
        page.wait_for_url(re.compile(r"/opportunities$"), timeout=30000)
        check("Navegación a Convocatorias", True)
    except Exception as e:
        check("Navegación a Convocatorias", False, str(e))

    # 8. Check opportunities page
    try:
        heading_opp = page.get_by_role("heading", name="Oportunidades activas")
        check("Página de oportunidades carga", heading_opp.is_visible(timeout=10000))
    except Exception as e:
        check("Página de oportunidades carga", False, str(e))

    # 9. Check no "Not Found" errors
    try:
        not_found_count = page.get_by_text("Not Found").count()
        check("Sin errores 404/NotFound en página", not_found_count == 0, f"found={not_found_count}")
    except Exception as e:
        check("Sin errores 404/NotFound en página", False, str(e))

    ctx.close()
    browser.close()

# ── Summary ────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
total = PASS + FAIL
if FAIL == 0:
    print(f"  ✅ TODAS LAS PRUEBAS PASARON ({PASS}/{total})")
else:
    print(f"  ⚠️  {PASS}/{total} pasaron, {FAIL} fallaron")
print(f"{'='*60}")
sys.exit(0 if FAIL == 0 else 1)

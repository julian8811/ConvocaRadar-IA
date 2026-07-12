# Exploration: Connector Yellow Fixes — Findeter & Uniandes

## Source 1: Findeter (findeter-convocatorias)

### Current State
Seed URL: `https://www.findeter.gov.co/convocatorias`

The site is fully behind **Radware Bot Manager** (`validate.perfdrive.com`).  
Both `fetch_httpx_text()` and `render_page_html()` (Playwright) get redirected to a captcha wall.

- **HTTPX result**: Redirected to Radware validation page (~16KB of captcha HTML).
- **Playwright result**: Same — Radware detects headless Chromium. ~19KB, title "Radware Bot Manager Captcha".
- **Detail pages** (`/convocatorias/paf-*-2026`) are also blocked.
- **Every subpage** under `findeter.gov.co` is blocked — homepage, `/user/login`, `/node/1`, `/sites/default/files/`.

**Exception**: The **sitemap.xml** is NOT blocked.

### What works — Sitemap XML

`https://www.findeter.gov.co/sitemap.xml` returns 692KB with 3,314 URLs, including **2,846 convocatorias**:

| Year | Count |
|------|-------|
| 2026 | 107   |
| 2025 | 272   |
| 2024 | 402   |
| ≤2023 | ~2,065 |

Each sitemap entry has:
```xml
<url>
  <loc>https://www.findeter.gov.co/convocatorias/paf-icbfgs-i-001-2026</loc>
  <lastmod>2026-01-05T15:14:35-05:00</lastmod>
  <changefreq>daily</changefreq>
  <priority>0.5</priority>
</url>
```

**No titles, descriptions, or close dates** in the sitemap — only URLs, lastmod, and the URL slug which encodes: `{program}-{entity}-{type}-{seq}-{year}`

### Approaches

1. **Sitemap-only connector** — Use sitemap to discover URLs, extract what info we can from the URL pattern itself.
   - Pros: We get the list of active convocatorias (107 from 2026)
   - Cons: No title, description, close date, or funding amount. URL slugs only have contract codes, not human-readable names. Very low quality candidates.
   - Effort: Medium (need custom parse logic, entity code mapping)

2. **Sitemap + SECOP alternative** — Findeter contracts appear in Colombia's SECOP procurement platform. Re-source from there.
   - Pros: SECOP has structured data (titles, entities, values)
   - Cons: SECOP covers all public procurement, not just Findeter. Different domain, different connector. Unclear if SECOP has Findeter-specific API.
   - Effort: High (new connector entirely)

3. **Stay YELLOW (disabled via enabled=false)** — Connector returns 0 candidates, probe shows YELLOW.
   - Pros: No work required
   - Cons: We lose visibility into a Colombian development finance source (Findeter manages ~$2B in infrastructure/social projects)
   - Effort: None

### Recommendation for Findeter
**Approach 1 (sitemap-based)**, but only if we can extract meaningful titles. The URL patterns follow `paf-{entity_code}-{type}-{seq}-{year}`. We can map entity codes to names (icbfgs → ICBF, menies → MEN, atf → ATF, etc.) to generate titles like "ICBF Convocatoria PAF 001-2026". This is imperfect but better than nothing.

**Fallback**: If entity-code mapping is too brittle, stay YELLOW but document that the sitemap approach was evaluated and why it was skipped.

---

## Source 2: Uniandes (uniandes-investigacion)

### Current State
Seed URL: `https://investigaciones.uniandes.edu.co/convocatorias/`

The old URL redirects:
1. `investigaciones.uniandes.edu.co/convocatorias/` → **301** → `investigacioncreacion.uniandes.edu.co` → **meta-refresh** → `www.uniandes.edu.co/investigacioncreacion/`
2. The `/convocatorias/` path segment is **dropped** during the redirect chain.

The actual site is a **Drupal 10** installation under the base path `/investigacioncreacion/`.

### What works — HTTPX direct access

- HTTPX **succeeds** with full 350KB HTML response. No bot detection.
- The homepage has **2 convocatoria links** (Dejar Huella 2026, Core Conectar 2025) embedded in a news list that mixes news/comunicados/reconocimientos with actual convocatorias.
- No RSS/Atom feeds found (all 404).
- No Drupal jsonapi module (`/jsonapi/...` returns 404).
- `?_format=json` returns 406 (REST module probably disabled).
- Playwright doesn't help — content is server-rendered Drupal; same 2 convocatorias appear.

### What works — Drupal Views AJAX endpoint

The `news_category` view has an AJAX endpoint:

```
POST https://www.uniandes.edu.co/investigacioncreacion/es/views/ajax
Content-Type: application/x-www-form-urlencoded

view_name=news_category
view_display_id=page_1
view_args=197951
view_path=/taxonomy/term/197951
view_base_path=taxonomy/term/%
view_dom_id=6207af13649f555311227c9c0b34c7a7b09b27979e2a752ad1ec8f32f16e4a10
pager_element=0
page=0
```

- Returns **91KB JSON** (Drupal AJAX command format).
- Contains HTML fragments with news/convocatoria cards.
- Convocatoria links are present but mixed with non-convocatoria news.
- Supports `page=N` parameter for pagination.
- Unique convocatorias in the news list: only **2** (the same ones on the homepage).

### Approaches

1. **Fix seed URL to `https://www.uniandes.edu.co/investigacioncreacion/`** + keep GenericHtmlConnector.
   - Pros: Minimal change — just update `base_url` and `allowed_domains` in seed.py.
   - Cons: Only yields 2 convocatorias, mixed with noise. GenericHtmlConnector's `parse()` filters by keyword and handles noise well, but coverage is low.
   - Effort: Low (5 lines change)

2. **GenericHtmlConnector with convocatorias-focused URL** — if there's a convocatorias-specific path or views display.
   - Currently: `/investigacioncreacion/es/noticias` shows news + only 2 convocatorias.
   - No dedicated `/convocatorias/` path on the new site.
   - Effort: Not viable — no dedicated convocatorias listing found.

3. **Custom connector using Views AJAX** — POST to the views/ajax endpoint, paginate through all pages, filter for convocatoria URLs.
   - Pros: Could yield more items if the archive has older convocatorias.
   - Cons: Only 2 convocatorias found even via AJAX pagination (page 1 and page 2 return the same 2). Heavy dependency on Drupal internal API.
   - Effort: Medium

4. **WordPress/Grants-style connector** — If Uniandes publishes more convocatorias as individual nodes, the current GenericHtmlConnector's `_collect_ld_json` and `_collect_embedded_json` may pick them up.
   - Currently LD+JSON only has Person schema on detail pages (not useful).
   - Effort: None — GenericHtmlConnector already does this.

### Recommendation for Uniandes
**Approach 1** — fix the `base_url` and `allowed_domains` in `seed.py`. The GenericHtmlConnector already handles:
- Keyword filtering for "convocatoria" in links/text
- Noise text rejection
- Detail page enrichment (OG tags, meta descriptions, h1)

The 2 convocatorias will be reliably found. If more appear on the homepage over time, they'll be picked up.

---

## Risks
- **Findeter**: Radware may extend blocking to the sitemap.xml at any point. No fallback if sitemap gets blocked — the connector will go RED.
- **Findeter**: Entity codes in URLs are opaque (e.g., `icbfgs`, `menies`, `atf`). Mapping them to readable names requires maintenance.
- **Uniandes**: If Uniandes changes its Drupal Views configuration (view ID, view name, AJAX path), the approach breaks. The current GenericHtmlConnector is resilient because it just scrapes the homepage HTML.
- **Both**: These are low-volume sources (Findeter has many but we can only extract URLs, Uniandes has only 2 currently). Neither will significantly impact the opportunity pipeline.

## Ready for Proposal
**Yes** — both analyses are complete with verified test results. The orchestrator should explain the tradeoffs (especially Findeter's limited sitemap-only option vs YELLOW status) and let the user decide.

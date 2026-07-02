#!/usr/bin/env python3
"""
Source URL Health Check — ConvocaRadar

Reads all source definitions from seed.py and checks each one responds
with HTTP 200. Reports broken URLs for manual review.

Usage:
    python scripts/check_sources_health.py [--json] [--quiet]

Exit codes:
    0 — all sources OK or only minor warnings
    1 — one or more sources returned 4xx/5xx
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (compatible; ConvocaRadar-HealthCheck/1.0)"
IMPORTANT_STATUSES = {200, 301, 302}  # Accept redirects as "working"


def load_source_definitions(seed_path: str) -> list[dict]:
    """Parse source_definitions from seed.py (no DB needed)."""
    content = Path(seed_path).read_text(encoding="utf-8")
    start = content.index("source_definitions = [")
    depth = 0
    end = start
    for i, c in enumerate(content[start:], start):
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    block = content[start:end]

    entries = []
    i = block.index("[") + 1
    depth = 0
    buf = ""
    in_entry = False
    while i < len(block):
        c = block[i]
        if c == "{":
            if depth == 0:
                in_entry = True
                buf = ""
            depth += 1
        if in_entry:
            buf += c
        if c == "}":
            depth -= 1
            if depth == 0 and in_entry:
                entries.append(buf)
                in_entry = False
                buf = ""
        i += 1

    sources = []
    for e in entries:
        key_m = re.search(r'"key":\s*"([^"]+)"', e)
        name_m = re.search(r'"name":\s*"([^"]+)"', e)
        url_m = re.search(r'"base_url":\s*"([^"]+)"', e)
        type_m = re.search(r'"source_type":\s*"([^"]+)"', e)
        if key_m and url_m:
            sources.append({
                "key": key_m.group(1),
                "name": (name_m.group(1) if name_m else key_m.group(1)),
                "base_url": url_m.group(1),
                "source_type": type_m.group(1) if type_m else "html",
            })
    return sources


def check_url(url: str, timeout: int = TIMEOUT) -> dict:
    """Test URL connectivity. Returns status report dict."""
    result = {"url": url, "status": None, "error": None, "latency_ms": None}
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en,es;q=0.9",
            },
        )
        start = time.time()
        resp = urllib.request.urlopen(req, timeout=timeout)
        result["status"] = resp.status
        result["latency_ms"] = int((time.time() - start) * 1000)
        body = resp.read(512)
        result["has_content"] = len(body) > 100
        resp.close()
    except urllib.error.HTTPError as e:
        result["status"] = e.code
        result["error"] = str(e.reason)
    except urllib.error.URLError as e:
        result["error"] = f"URLError: {e.reason}"
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
    return result


def classify(status: int | None, error: str | None) -> str:
    if status in IMPORTANT_STATUSES:
        return "OK"
    if status in (403,):
        return "BLOCKED"
    if error and "timeout" in error.lower():
        return "TIMEOUT"
    if status and 400 <= status < 500:
        return "BROKEN"
    if status and status >= 500:
        return "SERVER_ERROR"
    return "ERROR"


def main():
    parser = argparse.ArgumentParser(description="Check all ConvocaRadar source URLs")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--quiet", action="store_true", help="Only show broken sources")
    args = parser.parse_args()

    seed_file = Path(__file__).parent.parent / "apps" / "api" / "app" / "db" / "seed.py"
    if not seed_file.exists():
        print(f"❌ seed.py not found at {seed_file}", file=sys.stderr)
        sys.exit(2)

    sources = load_source_definitions(str(seed_file))
    total = len(sources)

    if not args.quiet and not args.json:
        print(f"🔍 Checking {total} sources...\n")

    results = []
    broken_count = 0
    for i, src in enumerate(sources):
        if not args.quiet and not args.json:
            print(f"  [{i+1}/{total}] {src['key']:40s}...", end=" ", flush=True)

        report = check_url(src["base_url"])
        report["key"] = src["key"]
        report["name"] = src["name"]
        report["type"] = src["source_type"]

        cls = classify(report["status"], report["error"])
        report["classification"] = cls

        if cls == "OK":
            if not args.quiet and not args.json:
                print(f"✅ {report['status']} {report['latency_ms']}ms")
        else:
            broken_count += 1
            if not args.quiet and not args.json:
                icon = {"BLOCKED": "🔒", "BROKEN": "❌", "SERVER_ERROR": "⚠️", "TIMEOUT": "⏱️", "ERROR": "❓"}.get(cls, "❌")
                detail = report["error"] or str(report["status"])
                print(f"{icon} {cls} {report['status'] or ''} - {detail}")

        results.append(report)
        time.sleep(0.25)  # Be gentle to servers

    # Summary
    ok_count = total - broken_count
    if not args.quiet and not args.json:
        print(f"\n{'='*60}")
        print(f"Total: {total} | ✅ OK: {ok_count} | ❌ Broken: {broken_count}")
        print(f"{'='*60}")

        if broken_count > 0:
            print(f"\nBroken sources ({broken_count}):")
            for r in results:
                if r["classification"] != "OK":
                    detail = r["error"] or f"HTTP {r['status']}"
                    print(f"  ❌ {r['key']:40s} {detail[:60]}")
                    print(f"     URL: {r['url']}")

    if args.json:
        print(json.dumps({
            "total": total,
            "ok": ok_count,
            "broken": broken_count,
            "sources": results,
        }, indent=2))

    return 1 if broken_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())

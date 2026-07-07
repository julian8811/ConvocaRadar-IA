#!/usr/bin/env python3
"""
Health check monitor for ConvocaRadar IA.

Called by Render cron job every 5 minutes.
Exits with 0 on success, non-zero on failure (Render notifies via email).
"""

import os
import sys
import urllib.request
import urllib.error

HEALTH_URL = os.getenv("HEALTH_CHECK_URL", "https://convocaradar-ia.onrender.com/api/v1/health/live")
TIMEOUT = int(os.getenv("HEALTH_CHECK_TIMEOUT", "15"))


def main():
    try:
        req = urllib.request.Request(HEALTH_URL)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            status = resp.status
            body = resp.read().decode()
            if status == 200:
                print(f"✅ Health check OK — HTTP {status}: {body}")
                return 0
            else:
                print(f"❌ Health check FAILED — HTTP {status}: {body}")
                return 1
    except urllib.error.HTTPError as e:
        print(f"❌ Health check FAILED — HTTP {e.code}: {e.read().decode()}")
        return 1
    except urllib.error.URLError as e:
        print(f"❌ Health check FAILED — {e.reason}")
        return 1
    except Exception as e:
        print(f"❌ Health check FAILED — {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

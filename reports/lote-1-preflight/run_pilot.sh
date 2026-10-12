#!/usr/bin/env bash
# Piloto L3 del lote 1 (issue #59): REQUIERE autorizacion expresa posterior.
# NO ejecutar en este encargo (gate NO-GO para red). 5 GET maximo, secuencial.
set -u
cd "$(dirname "$0")/../../apps/api" || exit 1
for s in novo-nordisk-grants grants-gov-forecast minciencias ukri-opportunities innpulsa; do
  python3 -m app.audit.cli --mode live-probe --allow-network --source-key "$s" \
    --output "../../reports/lote-1-preflight/piloto-$s"
done

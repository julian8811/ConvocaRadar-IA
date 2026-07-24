# Estado de fuentes — 21/07/2026

## Resumen operativo

- Total: 127
- Ejecutables: 108
- En cuarentena: 4
- Inactivas: 15
- Con éxito histórico: 94
- Con error reciente: 13

## En cuarentena

- FONDECYT Chile — HTTP 403.
- IAF — HTTP 403.
- Innovamos FID — página no disponible.
- Innovamos Global Innovation Fund — página no disponible.

## Activas con error reciente

- FAPEMIG — presupuesto Playwright agotado.
- FAPESP — timeout, aunque cuenta con éxito reciente.
- Fondo Emprender SENA — timeout, con éxito reciente.
- Horizon Europe SEDIA — timeout, con éxito reciente.
- ICETEX — timeout, con éxito reciente.
- Novo Nordisk — timeout, con éxito reciente.
- UNDP — timeout, con éxito reciente.
- SIDA — presupuesto Playwright agotado.
- SENA Oferta Educativa — dominio fuera de allowlist.

## Interpretación

La mayoría de errores actuales son transitorios (timeout/concurrencia) y no significan que la fuente esté retirada. Los 4 elementos en cuarentena sí tienen bloqueo o indisponibilidad persistente.

## Próximas acciones

1. Ejecutar FAPEMIG y SIDA con cola Playwright exclusiva por dominio.
2. Aumentar el timeout solo para SENA, ICETEX, Novo Nordisk y UNDP.
3. Corregir la allowlist de SENA.
4. Mantener cuarentena para 403/indisponibles.
5. Medir éxito durante tres ejecuciones antes de cambiar el estado operativo.

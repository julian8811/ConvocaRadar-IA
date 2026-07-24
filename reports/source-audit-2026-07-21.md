# Auditoría exhaustiva de fuentes — 21/07/2026

## Resumen

- Fuentes inactivas auditadas: 29.
- La mayoría no tiene ejecución reciente ni error persistido porque fueron desactivadas manualmente.
- Prueba de contrato HTTP: 72 respuestas válidas, 20 bloqueadas/404/403, 2 errores de conexión, 2 advertencias de contrato y 1 respuesta vacía.

## Clasificación

### Reactivables con selector o conector

AECID, AGROSAVIA, CELAC, DIAN, FAPERJ, iNNpulsa, INVIMA, MinAgricultura, Parlatino, Javeriana, SENA/SENNOVA, SGC y World Bank. Sus URLs responden o tienen estructura recuperable; requieren selector específico y prueba de contrato antes de reactivar.

### Requieren URL/API alternativa

BNDES, CAF, Colombia Científica, DANE, EMBRAPII, FINEP, ICFES, IDEAM, MinSalud, SEBRAE, SENESCYT, UIS y UPTC. Debe localizarse el endpoint vigente o feed oficial antes de crear selectores.

### Retiradas o bloqueadas

FONACYT Facebook, ANP Brasil, cámaras regionales con 404, CEPAL con URL antigua y fuentes cuyo dominio ya no responde. No deben reactivarse con scraping genérico.

## Recomendación operativa

1. Crear snapshot HTML/API y prueba de contrato por cada fuente reactivable.
2. Implementar selectores versionados para título, enlace, cierre y resumen.
3. Reactivar solo después de obtener al menos un registro válido.
4. Mantener cuarentena automática ante 403, 404, respuesta vacía o tres fallos consecutivos.
5. Registrar la causa de desactivación y la fecha de próxima revisión.

# YahooDSP for OST via cos-tags — Design (as built)

**Fecha:** 2026-07-16
**Contenedor:** cos-tags — account `1265057312` / container `230044048`, Default Workspace `113`.
**Scope:** onlineshoppingtools.com only (per-site config gating).

## Objetivo

Agregar el pixel de Yahoo DSP (pixelId `10220900`, projectId `10000`) al contenedor
compartido cos-tags, disparando **solo en OST**, usando el sistema config-driven del
contenedor (no tags específicos por site). Placeholders `he`/`hph` se dejan tal cual.

## Correción de rumbo

Primer intento (incorrecto): se crearon los tags directo en el contenedor OST
(54998520, tags 310/311). Se borraron. Yahoo va en cos-tags, gateado por site como
todos los vendor pixels.

## Patrón usado (Pinterest/Quora — gate por `VENDOR_X_ID != null`)

1. **Variable jsm `VENDOR_YAHOO_DSP_PIXEL_ID`** (var 500) — lee `c.vendors.yahoo.pixelId`
   de `CFG_RESOLVER`. Creada con el skill `gtm-create-jsm-variable` (el MCP no crea jsm).
2. **`CFG_SITES` (var 8)** — se agregó `yahoo: { pixelId: "10220900" }` a la entrada
   `onlineshoppingtools.com` → vendors. En los demás sites resuelve a `null`.
3. **Trigger 501 `Feature - Yahoo DSP Enabled`** (pageview): `{{VENDOR_YAHOO_DSP_PIXEL_ID}}` ≠ null.
4. **Trigger 502 `cos-rd.com Outbound Clicks - Yahoo DSP Enabled`** (linkClick):
   `Click URL contains cos-rd.com` + `{{atnds}}` regex de action-ids + pixelId ≠ null.
5. **Tag 503 `Yahoo DSP DOT Base`** (html, oncePerEvent, consent notSet): `ytc.js`,
   projectId `10000` fijo, pixelId `'{{VENDOR_YAHOO_DSP_PIXEL_ID}}'`. Dispara en 501.
6. **Tag 504 `Yahoo DSP A1 Conversion`** (html, oncePerEvent, consent notSet):
   push `et=custom, ea=1`, mismos IDs. Dispara en 502.

## Notas

- `projectId 10000` hardcodeado (proyecto fijo de Yahoo DSP); solo pixelId es config-driven.
- El A1 dispara solo en `cos-rd.com` outbound clicks — igual que los A1 hermanos
  (Twitter/Pinterest/Quora) en cos-tags; NO los 13 dominios del contenedor OST standalone.
- Consent `notSet`, como todos los ad pixels de cos-tags.

## Estado

Todo en staging en workspace 113. **No publicado.** Pendiente: QA en GTM Preview
(DOT carga + A1 dispara en clickouts de OST; confirmar que NO dispara en otros sites).

## Deuda / follow-up

- El MCP no puede crear variables jsm → se usó el skill `gtm-create-jsm-variable` como
  stopgap. Fix durable: agregar tool `create_variable` a `fastmcp_gtm_write_tools.py`
  (el `GTMClient.create_variable` ya soporta cualquier tipo).

# Yahoo DSP A1 → captura de TODOS los Action 1 vía tag sequencing — Diseño

**Fecha:** 2026-07-17
**Contenedor:** cos-tags — account `1265057312` / container `230044048`, Default Workspace `113`.
**Branch:** `feature/variable-and-trigger-tools`
**Depende de:** `docs/runbooks/2026-07-16-yahoodsp-ost-tags-design.md` (creación inicial de los tags Yahoo).

## Objetivo

Hacer que el pixel **Yahoo DSP A1 Conversion** (tag 504) dispare en **todos** los eventos
Action 1 del contenedor —incluidos los hold-ups, OM, quiz y giftcard OST—, no solo el
clickout de `cos-rd.com` que cubre hoy. Debe seguir siendo **solo OST** y no introducir
doble-conteo.

## Contexto: la familia Action 1 (hallazgos del spike)

Existen **5 tags** de la familia MT Action 1, todos pixeles `img` que pegan a la misma URL
`{{TRACKING_BASE}}/action/1?atnid={{atnid}}` (298 usa `//clk.onlineshoppingtools.com/action/1`),
todos `oncePerLoad`, todos en la carpeta `426`:

| Tag | Nombre | Firing | Blocking | Mecanismo |
|-----|--------|--------|----------|-----------|
| 100 | MT Action 1 | 99, 452, 491 | — | offsite / CTA mpg / clickout domains |
| 142 | MavenScripts Hold-up - MT Action 1 | 409 | 440 | CTA hold-up on-page (URL `#`) |
| 298 | MT Action 1 CTA Click (OST /giftcard) | 296, 297 | — | CTA giftcard OST |
| 304 | OM Hold-up - MT Action 1 | 303 | 141, 440 | CTA OptinMonster hold-up |
| 430 | Quiz Funnel MT Action 1 | 431 | — | quiz funnel |

"Hubo un Action 1" ≡ uno de esos 5 pixeles pegó a `/action/1`. El trigger 502 actual de
Yahoo (y los pixeles hermanos Twitter/Pinterest/Quora) solo cubren el subset de clickout
`cos-rd.com`; los hold-ups (409, 303) son clicks on-page, mecanismo distinto → no cubiertos.

### Por qué sequencing y no triggers compartidos

- Enganchar los 8 triggers al tag Yahoo no replica los *blocking* por-tag (440/141 son a
  nivel-tag): Yahoo dispararía en páginas O&O donde el hold-up de Maven está bloqueado →
  doble-conteo. Y es frágil a tags Action 1 nuevos.
- **Tag sequencing** (Yahoo como *teardown* de cada uno de los 5) hereda la lógica exacta de
  firing+blocking de cada padre → sin doble-conteo, robusto. Los 5 slots teardown están
  **libres** (verificado), sin conflictos.

### Restricciones de GTM verificadas en el spike

1. La API v2 soporta `setupTag[]`/`teardownTag[]` en el recurso Tag. El `teardownTag` se
   escribe **en el tag padre**. El MCP hoy **no** tiene tool para editar un tag existente
   (`grep` de `setupTag|teardownTag|sequenc` → 0 matches; `GTMClient` solo tiene `create_tag`).
2. Las **exceptions/blocking del tag secuenciado NO se evalúan de forma confiable** → el gate
   OST **no** puede depender de un blocking trigger. Debe vivir **dentro del HTML** de Yahoo.

## Diseño

### Parte 1 — Tool nuevo `update_tag` (MCP)

Partial update de un tag existente, espejo de `update_gtm_variable`: fetch → mutar solo lo
pasado → `tags().update(path, body, fingerprint=...)` (concurrencia optimista). Reutiliza el
patrón `get`/`update` que ya usan `pause_tag`, `add_firing_trigger_to_tags_batch`, etc.

**Firma (todos los mutadores opcionales; se aplica solo lo pasado):**

```
update_tag(account_id, container_id, tag_id, *,
           name=None, parameter=None,
           firing_trigger_ids=None, blocking_trigger_ids=None,
           setup_tag_name=None, teardown_tag_name=None, stop_on_failure=False,
           tag_firing_option=None, consent_status=None, consent_types=None,
           notes=None, paused=None, parent_folder_id=None, workspace_id="1")
```

- `teardown_tag_name` → escribe `teardownTag: [{"tagName": <name>, "stopTeardownOnFailure": stop_on_failure}]`.
- `setup_tag_name` → escribe `setupTag: [{"tagName": <name>, "stopOnSetupFailure": stop_on_failure}]`.
- Preserva el `tagId` y todo campo no tocado. Devuelve `{status, tag_id, tag_name, ...}`.
- Se agrega a `GTMClient` un `update_tag(...)` genérico o se hace el get/update inline en la
  tool (siguiendo el patrón existente). Se registra en el conteo de tools del módulo.

**Tests (TDD, primero):** `tests/test_update_tag.py`
- set `teardown_tag_name` escribe el shape correcto y preserva `tagId`/params.
- partial update: pasar solo `name` no borra triggers/params.
- `firing_trigger_ids=[]` limpia los firing triggers (caso Yahoo).
- fingerprint se envía en el `update`.
- validación: tag inexistente → error limpio.

### Parte 2 — Aplicar en cos-tags (workspace 113, staging)

1. **Auto-gate OST dentro del HTML de Yahoo A1 (tag 504):**

   ```html
   <script type="application/javascript">
   (function(){
     var p='{{VENDOR_YAHOO_DSP_PIXEL_ID}}';
     if(!p||p==='null'||p==='undefined')return;   // solo OST (feature on)
     window.dotq=window.dotq||[];
     window.dotq.push({'projectId':'10000','properties':{'pixelId':p,'qstrings':{'et':'custom','ea':'1'}}});
   })();
   </script>
   ```

2. **Quitar el firing trigger propio de Yahoo A1:** `firingTriggerId = []` (se elimina 502).
   Yahoo pasa a dispararse **solo** vía teardown de los 5 padres. El trigger 502 queda
   huérfano (el MCP no puede borrar triggers hoy → se deja y se anota como limpieza; borrar
   en UI o cuando exista `delete_gtm_trigger`).

3. **Escribir `teardownTag → "Yahoo DSP A1 Conversion"` en los 5 tags padre** (100, 142, 298,
   304, 430) con `update_tag` (`stop_on_failure=False`).

4. **Actualizar notas** del tag 504 para reflejar el patrón teardown + auto-gate.

**Resultado:** cada vez que dispara cualquier pixel `/action/1` de Maven (con su propia lógica
de firing+blocking intacta), Yahoo dispara justo después, y el HTML se auto-descarta si el
pixelId no está (no-OST). Sin doble-conteo, auto-mantenible salvo tags Action 1 nuevos (que se
enganchan con un `update_tag` de una línea).

## Decisiones (resueltas)

- **Firing option de Yahoo A1:** cambia de `oncePerEvent` → **`oncePerLoad`** (confirmado),
  para disparar en lockstep con los pixeles padre `oncePerLoad`.
- **`stopTeardownOnFailure`:** `false` — Yahoo no debe afectar el pixel de Maven si algo falla.
- **Trigger 502 huérfano:** se deja en staging y anotado (el MCP no puede borrar triggers hoy);
  limpieza manual en UI o cuando exista `delete_gtm_trigger`.

## Testing / QA

- Unit: `tests/test_update_tag.py` (arriba).
- Manual en GTM Preview (workspace 113, sin publicar):
  - En OST: disparar un Action 1 de cada mecanismo (clickout cos-rd, hold-up, OM, giftcard,
    quiz) → confirmar que el pixel Yahoo `dotq`/`/p/…ea=1` sale **una vez** por cada uno.
  - En un site NO-OST: disparar Action 1 → confirmar que Yahoo **no** sale (auto-gate).
  - Confirmar que los pixeles `/action/1` de Maven siguen saliendo igual (sequencing no los
    rompe).

## Estado (as-built 2026-07-17)

**Implementado y staged en workspace 113. NO publicado.** Pendiente: QA en GTM Preview +
publish (lo hace el usuario tras revisar).

- **Build:** `update_tag` agregado a `fastmcp_gtm_write_tools.py` (partial update + `setupTag`/
  `teardownTag`), con `tests/test_update_tag.py` (8/8 verde). Docstring del módulo → 14 tools.
  Cambios en git **sin commitear** (a pedido del usuario).
- **Aplicado** (vía script `scratchpad/apply_yahoo_sequencing.py`, que dogfoodea `update_tag`
  reusando el token OAuth cacheado):
  - Tag 504 Yahoo A1: HTML auto-gateado por `VENDOR_YAHOO_DSP_PIXEL_ID`, `firingTriggerId=[]`
    (sin trigger propio), `tagFiringOption=oncePerLoad`, notas actualizadas.
  - `teardownTag → "Yahoo DSP A1 Conversion"` escrito en 100, 142, 298, 304, 430. Firing y
    blocking triggers de cada padre preservados (verificado en 100 y 304).
- **Trigger 502** queda huérfano (sin borrar — el MCP aún no tiene `delete_gtm_trigger`).
  Nota: la API omite `stopTeardownOnFailure:false` del valor guardado (es el default).

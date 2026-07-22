# MavenTrack Parallel Tracking Pixel — cos-tags

**Date:** 2026-07-22
**Container:** cos-tags (`GTM-T94N4TKG`, account `1265057312`, container `230044048`)
**Status:** Built (staged, **not published**) — see "As-built" below.

## As-built (2026-07-22)

The gtm MCP server cannot create a new workspace, nor URL-type (`u`) variables — only Data Layer variables. To stay behavior-identical without those primitives, the implementation was adapted:

- **No `qs_ds` / `qs_lp` / `qs_mtpt` / `qs_params` variables created.** All query-string reading happens **inside the tag** JS (`window.location.search`).
- **Gate** is done at the **trigger** via the built-in `{{Page URL}}` (`contains` `mtpt=true`) instead of a `{{qs_mtpt}}` variable.
- Built in the **Default Workspace `114`** (no dedicated workspace possible via API). Unpublished = draft.
- Reused existing variables `{{cid}}` (id 11) and `{{TRACKING_BASE}}` (id 358).

Created objects (workspace 114):
- Trigger **505** — "MTPT Parallel Tracking - mtpt=true" (Page View, filter `{{Page URL}}` contains `mtpt=true`).
- Tag **506** — "MavenTrack - Parallel Tracking" (Custom HTML, `oncePerLoad`, consent `notSet`, firing trigger 505).

Behavior matches the design below; only the variable/workspace mechanics differ.

## Goal

Add a tag to the cos-tags container that fires a **MavenTrack parallel-tracking pixel on page load**, but **only for visitors whose URL query string contains `mtpt=true`**. The pixel forwards the landing-page identifiers `ds` and `lp` (read from the inbound query string, with defaults) plus the rest of the inbound query string to the MavenTrack endpoint.

This replicates the **"MavenTrack - Parallel Tracking"** tag (tag `23`) from the ForeverSongs container (`GTM-TPBV4645`, account `6332661990`, container `239933263`), adapted to cos-tags conventions.

## Reference tag (ForeverSongs, tag 23) — verbatim behavior

- Type: Custom HTML, `tagFiringOption: oncePerLoad`, `priority: 1000`, consent needed (`ad_storage`, `ad_user_data`).
- Firing: All Pages (`2147479553`) + custom event `consent_update` (`172`). Blocking: EU/dev block (`395`).
- Reads `ds` (query key `ds`), `lpid` (query key `lpid`), `cid` (query `cid` persisted to `localStorage`), and the full query string.
- Builds `https://go.fs-px.com/{ds}/{lpid}?pt=1&cid=...&<inbound query string>` and fires a hidden `new Image(1,1)`.
- Defaults when `ds`/`lpid` invalid: `ds=147`, `lpid=17377`.

## cos-tags design

### Where
- New dedicated workspace: **"MavenTrack Parallel Tracking Pixel"**.
- Staged only. **Do not publish** without explicit go-ahead (per container convention).

### Variables to create
cos-tags does not currently have these; create them:

| Variable  | Type          | Definition                                   |
|-----------|---------------|----------------------------------------------|
| `qs_ds`   | URL           | component `QUERY`, queryKey `ds`             |
| `qs_lp`   | URL           | component `QUERY`, queryKey `lp`             |
| `qs_mtpt` | URL           | component `QUERY`, queryKey `mtpt`           |
| `qs_params` | Custom JS   | returns `location.search` without the leading `?` |

`qs_params` source:
```js
function() {
  try {
    var search = window.location.search;
    return search ? search.substring(1) : '';
  } catch (e) {
    return '';
  }
}
```

### Variables reused
- `cid` — reuse the existing cos-tags variable (id `11`, URL / query `cid`). Do **not** create a new one. (Note: this differs from the ForeverSongs `cid`, which is a Custom JS variable with `localStorage` persistence. cos-tags uses a plain URL variable, which is acceptable for this pixel.)
- `TRACKING_BASE` — existing cos-tags variable (id `358`, Custom JS resolving `CFG_RESOLVER.trackingBase` per-site). Used as the pixel host.

### Trigger to create
- **Page View** trigger, e.g. "MTPT Parallel Tracking — mtpt=true".
- Filter: `{{qs_mtpt}}` **equals** `true`.

### Tag to create
- Name: **"MavenTrack - Parallel Tracking"**
- Type: Custom HTML
- `tagFiringOption: oncePerLoad`
- `priority: 1000`
- Consent: `notSet` (matches cos-tags convention). *Open item — see below.*
- Firing trigger: the new `mtpt=true` Page View trigger.
- No blocking trigger (cos-tags has no EU/dev block equivalent).

Tag body (as-built — reads query params in-tag instead of via `{{qs_*}}` variables):
```html
<script>
(function() {
  var openBrace = String.fromCharCode(123, 123);

  var isValid = function(val) {
    return val && val !== "undefined" && val !== "null" && val.indexOf(openBrace) === -1;
  };

  var qp = function(name) {
    try {
      var m = new RegExp('[?&]' + name + '=([^&#]*)').exec(window.location.search);
      return m ? decodeURIComponent(m[1].replace(/\+/g, ' ')) : '';
    } catch (e) { return ''; }
  };

  try {
    var ds = qp('ds');
    var lp = qp('lp');
    var cid = "{{cid}}";

    if (!isValid(ds) || !isValid(lp)) {
      ds = "81";
      lp = "18383";
    }

    var baseUrl = "{{TRACKING_BASE}}";
    if (!isValid(baseUrl)) return;   // guard: TRACKING_BASE can resolve empty per-site

    var allParams = window.location.search ? window.location.search.substring(1) : '';
    var pixelUrl = baseUrl + '/' + ds + '/' + lp + '?pt=1';
    if (isValid(cid)) pixelUrl += '&cid=' + encodeURIComponent(cid);
    if (allParams && allParams.indexOf(openBrace) === -1) pixelUrl += '&' + allParams;

    var img = new Image(1, 1);
    img.src = pixelUrl;
  } catch (e) {}
})();
</script>
```

### Resulting pixel URL
```
{{TRACKING_BASE}}/81/18383?pt=1&cid=<cid>&<inbound query string>
```
(`ds`/`lp` replaced by inbound query values when present and valid.)

## Differences vs the ForeverSongs reference
1. **Host:** `{{TRACKING_BASE}}` (per-site resolved) instead of hardcoded `https://go.fs-px.com`.
2. **Defaults:** `ds=81`, `lp=18383` instead of `147`/`17377`.
3. **Landing-page query key:** reads `lp` (per request) instead of `lpid`.
4. **Gate:** fires only when `mtpt=true` (ForeverSongs fires on all pages).
5. **baseUrl guard:** early return when `TRACKING_BASE` is empty (new, because the host is now dynamic).
6. **Consent:** `notSet` instead of `needed` (`ad_storage`/`ad_user_data`).
7. **No blocking trigger** (no EU/dev block in cos-tags).

## Validation / testing
- Preview mode in cos-tags with a URL containing `?mtpt=true&ds=<x>&lp=<y>`: tag fires once, pixel `img.src` = `{{TRACKING_BASE}}/<x>/<y>?pt=1&...`.
- URL with `?mtpt=true` but no `ds`/`lp`: pixel uses defaults `/81/18383`.
- URL **without** `mtpt=true`: tag does **not** fire.
- URL where `TRACKING_BASE` resolves empty: tag fires trigger but returns early, no pixel request.
- Confirm the extra inbound params are appended after `pt=1` and no unresolved `{{...}}` templates leak into the URL.

## Open items
- **Consent:** design assumes `notSet` (cos convention). If cos-tags should honor consent like ForeverSongs, switch to `consentStatus: needed` with `ad_storage` + `ad_user_data`. Pending user confirmation.

## Out of scope (YAGNI)
- No `FEATURE_*` config-resolver flag or per-site CFG gating — the gate is purely the `mtpt=true` query param.
- No `consent_update` re-fire trigger (only needed alongside consent gating).
- No `localStorage`-backed `cid` variable.

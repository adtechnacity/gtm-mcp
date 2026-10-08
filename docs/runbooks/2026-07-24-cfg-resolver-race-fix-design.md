# CFG_RESOLVER memoization race — Google spinny conversion drop — root cause & fix

**Date:** 2026-07-24
**Container:** cos-tags — account `1265057312` / container `230044048`, Default Workspace `118`.
**Status:** Fix **staged, NOT published** (var 9 updated in workspace 118). Review + publish owned by Kemberly/Angel.
**Severity:** Production — significant drop in Google spinny (OST) flow conversion rate starting ~2026-07-23.

## Symptom (as reported / reproduced)

- Google spinny flow: media URL → spinny page → MT link → jump page → `/go` → COS.com.
- On the **jump/redirect page**, hovering the CTA showed the hardcoded default `cos-rd.com/go` (the IP/MPG fallback) instead of the GTM-rewritten MT link, ~30–40% of loads.
- Repro finding (Kemberly): **the spinny page itself renders fine** (GTM works there); the failure is on the page it redirects to — `MavenScripts getBrowserName` / dynamic browser names don't run and the links on that page are never rewritten.
- Immediate band-aid already shipped (outside this container): OST spinny MT link changed from `go.onlineshoppingtools.com` → `cos-rd.com`, so the cos-rd.com cookie redirect still lands users even when the CTA stays default. This masks the symptom; it does not fix GTM.

## Root cause

Container **Version 108 ("CFG_RESOLVER memoization + Anura Fix", Angel)** refactored config
resolution:

- Config is now built once per page by the **"COS Config Bootstrap"** Custom HTML tag (495),
  which fires on the **Initialization** trigger and writes `window.__cosCfg`.
- `CFG_RESOLVER` (var 9) was reduced to a bare reader:

  ```js
  function() { return window.__cosCfg || {}; }
  ```

The `|| {}` is the defect. GTM does **not** guarantee that a Custom HTML tag's code has
finished executing before Page-View variables/triggers are evaluated — this holds even for
Initialization Custom HTML tags (their code is injected/executed asynchronously). When any
consumer reads `CFG_RESOLVER` before the bootstrap tag has run, it receives an **empty object,
silently**. On empty config:

```
Trigger 96  requires  FEATURE_MAVEN_SCRIPTS == "true"
FEATURE_MAVEN_SCRIPTS (95):  var c = {{CFG_RESOLVER}};
                             return (c && c.features && c.features.mavenScripts) || false;   // -> false
=> trigger 96 never fires
=> MavenScripts suite never fires: 149 (CDN loader), 97 (replaceCTAHoldupLinks / CTA rewrite),
   139 (replaceBrowserNames), 140 (getBrowserName)
=> CTA/hold-up links keep the hardcoded default; browser-name replacement absent.
```

`MS_CDN_URL` (435), `FEATURE_MS_SPINNY_EXPERIENCE` (146), `TRACKING_BASE` (358), and every
`MS_*_SOURCELINKS_*` variable read config the same way, so they all collapse together on an
empty config.

The **pre-v108 inline resolver computed the config synchronously on every read**, so this race
was impossible. The memoization is what introduced it.

### Why intermittent, and why the jump page and not the spinny

Timing race between the async Initialization Custom HTML tag and Page-View variable/trigger
evaluation. On the content-heavy `/join-cos` spinny page the bootstrap reliably wins; on the
lightweight redirect/jump page Page View evaluates early enough to lose the race often enough to
produce the observed ~30–40%. Same URL, same host, same config on every load → a failure that
varies per load is definitionally a timing/race issue, not a static config/trigger bug.

### Not the cause (ruled out)

- **Yahoo DSP A1 sequencing (07-17):** teardown tag 504 on Action-1 parents (100/142/298/304/430)
  — all fire on `linkClick`, i.e. click time, not page load. Irrelevant to the page-load rewrite.
- **MavenTrack tag 506 (07-22):** fires only when the URL contains `mtpt=true`; spinny links don't.
- **Yahoo DSP DOT Base tag 503 (07-16):** fires on OST page view, but the spinny page renders fine,
  so page-load contention there is not the issue.
- **"Anura Fix":** bundled into v108, but the Anura tag (46) does not gate the MavenScripts suite.
  Not part of this failure. Left unchanged.

## Fix (staged)

Make `CFG_RESOLVER` (var 9) **self-healing**: keep the fast memoized read, but when
`window.__cosCfg` is missing, **build and cache the config on demand** instead of returning `{}`.
The build block is a verbatim port of the bootstrap tag (495) — the two must be kept in sync.
The bootstrap tag remains as the common-case pre-warm; this only closes the race.

```js
function() {
  if (window.__cosCfg) { return window.__cosCfg; }   // fast path (bootstrap ran)
  try {
    // ... verbatim port of 'COS Config Bootstrap' (tag 495) build logic ...
    window.__cosCfg = config;                          // cache
    return config;
  } catch (e) { return {}; }
}
```

Full source is in the variable itself (workspace 118, var 9) and in its notes.

**ES5 constraint (GTM Custom JS compiler):** the helper functions (`cloneObject`, `mergeObjects`)
MUST be declared at the top level of the function, NOT inside the `try` block. GTM's Custom
JavaScript compiler runs in ES5 mode and rejects block-scoped function declarations ("This
language feature is only supported for ECMASCRIPT_2015 mode or better"). The bootstrap tag (495)
sidesteps this because its helpers sit at the top level of its IIFE. Anything ported between the
two must keep helpers out of blocks.

**Trade-off:** the self-heal path re-references `CFG_DEFAULTS` (6) and `CFG_SITES` (8), giving
back some of the per-evaluation perf the v108 memoization saved. This is microseconds versus lost
conversions; correctness wins. If profiling ever flags it, revisit (e.g. a Custom Template that
runs config-build guaranteed-first, or caching the defaults/sites resolution).

## Verification plan (owner: Kemberly/Angel before publish)

1. GTM Preview on the two test links (both `/join-cos`), and follow through the redirect to the
   jump page. Confirm on the **jump page**: trigger 96 fires, tags 149/97/139/140 fire,
   `window.__cosCfg` is populated, and the CTA href is the rewritten MT link (not `cos-rd.com/go`).
2. Reload the jump page many times — the ~30–40% default-CTA failures should be gone.
3. Publish cos-tags from workspace 118.
4. Watch the Google spinny (OST) conversion rate recover over the following hours.

## Test links

```
https://blog.onlineshoppingtools.com/join-cos?atnds=60&popup=hdi9&utm_source=google_gdnost_cosspin&postback={gclid}&adgroup={adgroupid}&campaign={campaignid}&device={device}&creative={creative}&publisher={placement}&source={target}&welcome=2
https://blog.onlineshoppingtools.com/join-cos?atnds=164&popup=hdi9&utm_source=google_gdg_ostspin&postback={gclid}&atnid={gclid}&adgroup={adgroupid}&campaign={campaignid}&device={device}&creative={creative}&publisher={placement}&source={target}&welcome=2
```

## Follow-up / debt

- The "pure reader + bootstrap Custom HTML tag" pattern is fragile by construction (any config
  consumer that can be evaluated before the bootstrap runs will read empty). The self-heal makes
  it safe; consider standardizing on the self-healing resolver as the single source of truth and
  demoting the bootstrap tag to an optional warm-up (or removing it) in a later cleanup.
- Any future edit to the bootstrap tag (495) build logic MUST be mirrored into CFG_RESOLVER (9),
  and vice-versa.

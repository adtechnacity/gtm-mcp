# SmarterAdvisors UK config in wealth-tags — Design / As-built

**Date:** 2026-08-12
**Ticket:** "Configure Smarter Advisor UK in GTM" (Kemberly Miliano, 2026-08-12)
**Container:** wealth-tags — account `1265057312` / container `235464083`, Default Workspace `41`.
**Scope:** add `smarteradvisors.uk` to the config system and give it its own dynamic
CTA source links variable.

Reference URLs from the ticket:

- Prod: `media-playground-five.vercel.app/wealth/smarteradvisors.uk/`
- Dev: `media-playground-git-dev-media-playground.vercel.app/wealth/smarteradvisors.uk`

## Objective

Make `smarteradvisors.uk` a first-class site in the wealth-tags config system, so the
existing config-driven tags light up for it with no new tags or triggers, and give the
media team a UK-only place to define CTA source links.

## Container context (findings)

- wealth-tags resolves config through `CFG_DEFAULTS` (var 4) → `CFG_SITES` (var 5),
  deep-merged by `CFG_RESOLVER` (var 79). `FEATURE_*` / `VENDOR_*` jsm variables each read
  one path out of the resolver and return the value or `null`/`false`; triggers gate on
  those. Adding a site is therefore a pure config change.
- **`CFG_RESOLVER` keys on the registrable base domain.** It lowercases `{{Page Hostname}}`,
  strips `www.`, then reduces to the last two labels. Every `CFG_SITES` key in both
  wealth-tags and cos-tags is a registrable domain; there are no preview-host entries
  anywhere.
- Before this change `CFG_SITES` held two sites, `smarteradvisors.co` and
  `smarteradvisors.de`, and **neither overrode `sourcesLinks`** — both inherited
  `MS_DYNAMIC_SOURCELINKS_DEFAULT` (var 86) via `CFG_DEFAULTS`. UK is the first site in this
  container with a per-site source links map.
- `MS_DYNAMIC_SOURCELINKS` (var 85) already dispatches on
  `c.sourcesLinks.msDynamicCTAURL` with a fallback to the default, so a new per-site
  variable needs no dispatcher change.
- cos-tags is the precedent for per-site source links: `MS_DYNAMIC_SOURCELINKS_<CODE>`
  (OST, SPN, CCF, GFC, TS, CBH, KTG, GMD, HYP, LPT), each referenced from that site's
  `sourcesLinks` block. wealth-tags already uses the `SA<country>` convention informally —
  tags 101/104 are named "Consent Default (SADE)" / "Consent Bridge (SADE)" for
  SmarterAdvisors DE — so `SAUK` is the consistent code.
- The MCP cannot create `jsm` variables; the `gtm-create-jsm-variable` skill was used.

## Design

### 1. Variable `MS_DYNAMIC_SOURCELINKS_SAUK` (jsm)

Extends the shared default rather than copying it:

```js
function() {
  var base = {{MS_DYNAMIC_SOURCELINKS_DEFAULT}} || {};

  // Shallow-clone before merging: GTM caches a variable's value for the duration
  // of an event, so mutating `base` in place would corrupt the shared map for
  // every other consumer in that same event.
  var out = {};
  for (var k in base) {
    if (base.hasOwnProperty(k)) { out[k] = base[k]; }
  }

  var uk = {};   // UK-specific overrides

  for (var j in uk) {
    if (uk.hasOwnProperty(j)) { out[j] = uk[j]; }
  }
  return out;
}
```

A byte-copy of the default was rejected: it would freeze UK at today's routes and diverge
silently the next time the shared map is edited. Extension keeps inheritance intact and
gives one obvious place for UK-only codes. `uk` is empty today, so UK resolves exactly as it
would have via the default — the variable is a no-op extension point until UK campaigns
exist, not a behavior change.

### 2. `CFG_SITES` (var 5) — new `smarteradvisors.uk` entry

```js
"smarteradvisors.uk": {
  trackingBase: "//go.smarteradvisors.uk",
  vendors: {
    google: { analytics: { id: "G-K3RMKZN3GG" }, },
    clarity: { id: null }
  },
  sourcesLinks: {
    msDynamicCTAURL: {{MS_DYNAMIC_SOURCELINKS_SAUK}}
  },
},
```

The `.co` and `.de` entries are byte-identical to their pre-change text.

## Decisions and rationale

- **Key on `smarteradvisors.uk`, not the Vercel host.** The resolver reduces
  `media-playground-five.vercel.app` to `vercel.app`, so the ticket's URLs cannot carry
  site config. Keying on the real domain matches every other site in both containers.
  Consequence: **config does not resolve on the Vercel playground hosts** — Preview QA must
  run against a hostname whose base domain is `smarteradvisors.uk`.
- **`clarity: { id: null }` rather than a guessed ID.** A Clarity project ID cannot be
  invented; explicit `null` documents the slot and self-disables tag 94 (trigger 93 requires
  `CLARITY_PROJECT_ID` ≠ `null`). cos-tags has the same explicit-null pattern on several
  sites. Supply the real project ID to turn Clarity on — no other change needed.
- **GA4 reuses `G-K3RMKZN3GG`.** Both existing sites share that property. Note that
  `CFG_DEFAULTS` has no `google.analytics` key, so omitting it would have left
  `VENDOR_GOOGLE_ANALYTICS_ID` null and fired the GA tag with an empty ID — it must be set
  explicitly per site.
- **Consent gating left off (inherits `features.consent: false` from defaults).** This is
  the one decision that needs a human sign-off, and the technically safe default is *off*:
  - `Consent Bridge (SADE)` (tag 104) reads consent **only** from iubenda
    (`window._iub.cs.consent.purposes`). With no iubenda banner on the UK site, nothing is
    ever granted.
  - `Consent Default` (tag 101) would then leave `ad_storage`, `ad_user_data`,
    `ad_personalization` and `analytics_storage` denied, and blocking triggers 102/103 would
    fire on essentially every tag.
  - Net effect of setting `consent: true` today: **UK tracks nothing at all**, while still
    producing no valid consent record.

  **This is a compliance decision, not a technical one.** UK GDPR / PECR require consent for
  non-essential cookies. To turn it on: ship iubenda on the UK site, confirm purpose 5 is
  grantable (a code comment in tag 104 notes it currently is not on `.de`), then add
  `features: { consent: true }` to the UK entry.
- **No new tags or triggers.** Every relevant trigger is already config-driven, so UK
  inherits the container's behavior automatically.

## What UK resolves to, and what fires

Inherited from `CFG_DEFAULTS` and therefore **active on UK immediately**: Anura
(`FEATURE_ANURA` true), MavenScripts (true), Bing audience `283027635`, Taboola `1434039`,
Meta exclusion `8907994789304892`. OptinMonster is false.

| Fires on UK | Off on UK |
|---|---|
| Bing Audience Pixel (32), Bing A1 Event Pixel (90) | Microsoft Clarity (94) — `clarity.id` null |
| Taboola Audience Pixel (57) | Yahoo DSP Base (130) / A1 (131) — `.co`-only |
| Meta exclusion pixel (74), Meta Base Tag (91) | OptinMonster path (trigger 60) |
| Anura IVT (11) | Consent tags 101/104 — self-no-op when gating is false |
| MavenScripts 54 / 64 / 71 / 88 | |
| Google Analytics (45), Sentry (58), MT Extended Info (66), CTA URL Param Append (33) | |
| MT Action 1 (75) on outbound click | |

Blocking triggers 102 and 103 never block on UK, since both require
`FEATURE_CONSENT_GATING = true`.

## Open items / risks

1. **`go.smarteradvisors.uk` has no DNS — publish blocker.** Verified 2026-08-12:
   `smarteradvisors.uk`, `www.smarteradvisors.uk` and `go.smarteradvisors.uk` all return
   NXDOMAIN, while `go.smarteradvisors.co` and `go.smarteradvisors.de` resolve to Cloudflare.
   `MT Action 1` (tag 75) requests `{{TRACKING_BASE}}/action/1`, so **every UK conversion
   will fail until `go.smarteradvisors.uk` exists**. Do not publish before then.
2. **Clarity project ID outstanding** — UK has no session recording until one is supplied.
3. **Consent posture needs sign-off** — see the decision above.
4. **UK source links are empty** — UK currently routes to the shared default map, which
   contains US and German campaign codes (`in_seven`, `retire_j`, `fb_ruhestandsplan`, …).
   Populate `uk` in var 132 once UK campaigns are defined.
5. **UK inherits shared ad accounts.** Bing audience, Taboola and Meta exclusion are the same
   IDs the other markets use, so UK traffic mixes into those audiences. If UK needs its own,
   set them explicitly in the UK entry.
6. **Google Ads tags fire with empty IDs** — a pre-existing container-wide issue, not caused
   by this change, but it now applies to UK too. Every `VENDOR_GOOGLE_ADS_*` resolves to
   `null` for all three sites, yet tags 37 and 42 are not vendor-gated. Either supply the IDs
   or pause tags 37 / 40 / 42 / 70.

## Testing / QA

No Python code changed, so unit tests do not apply — the deliverable is container state.
Verification performed against the live workspace (13/13 checks passed):

- `.co` and `.de` `CFG_SITES` entries byte-identical to their pre-change text.
- UK key present, `trackingBase` correct, references `{{MS_DYNAMIC_SOURCELINKS_SAUK}}`,
  exactly three site keys, no `features` block on UK, braces balanced.
- Var 132 is `jsm`, extends the default, and clones before merging.
- Tag 75 `MT Action 1` still carries the `Yahoo DSP A1 Conversion` teardown and firing
  triggers `["35", "121"]` (fingerprint `1785872365797`, unchanged).

Both variable bodies were parsed with `{{...}}` references stubbed, and the SAUK merge was
unit-tested in node: inherits shared routes, returns a new object, does not mutate the shared
map, and repeated calls are independent.

Remaining manual QA in GTM Preview, on a real `smarteradvisors.uk` hostname, before publish:

1. `CFG_RESOLVER` reports `_host: "smarteradvisors.uk"` and the merged UK config.
2. `MS_DYNAMIC_SOURCELINKS` returns the shared routes via SAUK.
3. `TRACKING_BASE` is `//go.smarteradvisors.uk` and `MT Action 1` gets a 200 (requires item 1
   under Open items).
4. Clarity, Yahoo and OptinMonster tags do **not** fire; Bing, Taboola, Meta exclusion, Anura
   and MavenScripts do.
5. `.co` and `.de` behavior unchanged.

## Status (as-built 2026-08-12)

**Implemented and staged in workspace 41. NOT published.**

| Object | ID | Verified |
|--------|----|----------|
| Var `MS_DYNAMIC_SOURCELINKS_SAUK` (jsm) | **132** | extends var 86, clones before merge, notes set, no parent folder (matches vars 85/86) |
| Var `CFG_SITES` | 5 (edited) | UK entry added; `.co`/`.de` byte-identical; `parentFolderId: 3` preserved; fingerprint `1785866364631` → `1786538341745` |

No new tags or triggers were created. No Python code changed.

Note: the first two `update_gtm_variable` calls timed out at the socket level; the variable
was confirmed unchanged (fingerprint identical) before retrying, so no double write occurred.
The successful write went through a retrying script against the same `GTMClient`.

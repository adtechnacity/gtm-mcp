# Yahoo DSP pixel for SmarterAdvisors (wealth-tags) — Design

**Date:** 2026-08-04
**Ticket:** "Add YahooDSP tags to Investments GTM" (Robert Millie, 2026-08-04)
**Container:** wealth-tags — account `1265057312` / container `235464083`, Default Workspace `35`.
**Scope:** `smarteradvisors.co` only (per-site config gating).
**Pattern source:** `2026-07-16-yahoodsp-ost-tags-design.md` + `2026-07-17-yahoodsp-action1-sequencing-design.md` (cos-tags build).

## Objective

Add the Yahoo DSP DOT pixel (`projectId 10000`, `pixelId 10221725`) to the wealth-tags
container for the Yahoo Native Network campaign: a base pixel on page view and a conversion
pixel on CTA click. Built exactly the way the cos-tags Yahoo pixel was built — config-driven
site gating, no site-specific tags, conversion fires via tag sequencing off `MT Action 1`.

Placeholders `he` / `hph` are kept verbatim from the vendor snippet (per ticket: they do not
interfere with the pixel working).

## Container context (findings)

- wealth-tags uses the same `CFG_DEFAULTS` / `CFG_SITES` / `CFG_RESOLVER` config system as
  cos-tags, with `VENDOR_*` jsm variables reading `c.vendors.<vendor>.<field>` from
  `CFG_RESOLVER` (var 79). Reference implementation: `VENDOR_BING_AUDIENCE_ID` (var 26).
- `CFG_SITES` (var 5) holds two sites: `smarteradvisors.co` and `smarteradvisors.de`. The
  `.de` entry has `features.consent: true`; `.co` does not.
- The Action 1 family here is a **single tag**: `75 MT Action 1` (`img`, firing trigger `35`
  All Outbound Clicks, blocking `103` no-Measurement-consent, `oncePerLoad`). There are no
  hold-up / OM / quiz / giftcard variants like cos-tags has. Its `teardownTag` slot is free
  (verified — no `setupTag`/`teardownTag` on tag 75).
- Structural sibling for the vendor pair: Bing — base `32 Bing Audience Pixel` +
  `90 Bing A1 Event Pixel`.
- The container has **only one workspace** (Default Workspace 35) and the MCP cannot create
  workspaces, so this work stages directly in 35.

## Design

### 1. Variable `VENDOR_YAHOO_DSP_PIXEL_ID` (jsm)

```js
function(){
  var c = {{CFG_RESOLVER}};
  return (c && c.vendors && c.vendors.yahoo && c.vendors.yahoo.pixelId) || null;
}
```

Same body as cos-tags var 500 / same shape as `VENDOR_BING_AUDIENCE_ID`. Created with the
`gtm-create-jsm-variable` skill — the MCP cannot create `jsm` variables.

### 2. `CFG_SITES` (var 5) — enable Yahoo on `.co`

Add to the `smarteradvisors.co` → `vendors` object:

```js
yahoo: { pixelId: "10221725" }
```

`smarteradvisors.de` and every other host resolve `VENDOR_YAHOO_DSP_PIXEL_ID` to `null`,
which self-disables both tags.

### 3. Trigger `Feature - Yahoo DSP Enabled` (pageview)

`{{VENDOR_YAHOO_DSP_PIXEL_ID}}` **does not equal** `null`.

### 4. Tag `Yahoo DSP DOT Base` (html)

cos-tags tag 503 HTML verbatim, with `pixelId` templated:

```html
<script type="application/javascript">(function(w,d,t,r,u){w[u]=w[u]||[];w[u].push({'projectId':'10000','properties':{'pixelId':'{{VENDOR_YAHOO_DSP_PIXEL_ID}}','he': '<email_address>','hph': '<phone_number>'}});…})(window,document,"script","https://s.yimg.com/wi/ytc.js","dotq");</script>
```

- Firing trigger: #3. No blocking trigger.
- `tagFiringOption: oncePerEvent`, `consentStatus: notSet`.

### 5. Tag `Yahoo DSP A1 Conversion` (html)

cos-tags tag 504 HTML verbatim — the site gate lives **inside** the HTML because
exceptions/blocking triggers are not reliably evaluated on sequenced tags:

```html
<script type="application/javascript">
(function(){
  var p='{{VENDOR_YAHOO_DSP_PIXEL_ID}}';
  if(!p||p==='null'||p==='undefined')return;   // only smarteradvisors.co (feature on)
  window.dotq=window.dotq||[];
  window.dotq.push({'projectId':'10000','properties':{'pixelId':p,'qstrings':{'et':'custom','ea':'1'}}});
})();
</script>
```

- `firingTriggerId: []` — **no trigger of its own**. Fires only as a teardown tag.
- `tagFiringOption: oncePerLoad` (lockstep with the `oncePerLoad` parent), `consentStatus: notSet`.

### 6. Sequencing — `teardownTag` on `75 MT Action 1`

`update_tag(tag_id=75, teardown_tag_name="Yahoo DSP A1 Conversion", stop_on_failure=False)`.

Yahoo A1 therefore inherits tag 75's exact firing (trigger 35, the four-domain exclusion) and
blocking (103) logic: "Yahoo A1 fired" ≡ "a real Action 1 fired", with no double-counting and
no duplicated trigger logic to drift. `stopTeardownOnFailure: false` so a Yahoo failure can
never break Maven's `/action/1` pixel.

## Decisions and rationale

- **Consent `notSet`, no blocking trigger** — matches the cos-tags Yahoo build. wealth-tags
  gates its other ad pixels on `ad_storage`/`ad_user_data`/`ad_personalization` + blocking
  trigger `102`, but that exists for `smarteradvisors.de`, the only consent-gated site. Yahoo
  is `.co`-only and the config gate makes it unreachable on `.de`, so consent gating would be
  a no-op. **If Yahoo is ever enabled on `.de`, both tags must be switched to
  `consentStatus: needed` (ad_storage / ad_user_data / ad_personalization) + blocking trigger
  `102` before that config change ships.**
- **Sequencing instead of an outbound-click trigger** — the cos-tags way. With one Action 1
  parent it is also strictly simpler than a cloned click trigger, and it cannot drift from the
  definition of an Action 1.
- **No `consent_update_p5` trigger** — that second firing trigger exists on wealth-tags ad
  pixels so they can re-fire after consent is granted on `.de`. With `notSet` consent there is
  nothing to re-fire.
- **`projectId 10000` hardcoded** — fixed Yahoo DSP project; only `pixelId` is config-driven.
- **`pixelId 10221725`** is a different pixel from the cos-tags one (`10220900`) — a separate
  SmarterAdvisors pixel, as expected.

## Testing / QA

No Python code changes, so unit tests do not apply — the deliverable is container state.
Manual QA in GTM Preview on workspace 35, before publishing:

1. On `smarteradvisors.co`: `Yahoo DSP DOT Base` fires once on page view; `ytc.js` loads and a
   `dotq` beacon goes out with `pixelId=10221725`.
2. On `smarteradvisors.co`: click an outbound CTA → `MT Action 1` fires **and**
   `Yahoo DSP A1 Conversion` fires immediately after, once, with `et=custom&ea=1`.
3. On `smarteradvisors.de`: neither Yahoo tag produces a beacon (base tag does not fire;
   A1 tag may be sequenced but self-discards via the in-HTML guard).
4. `MT Action 1` still fires exactly as before — sequencing must not change its behavior.

## Status

Staged in workspace 35. **Not published** — publish is Kemberly's call after Preview QA.

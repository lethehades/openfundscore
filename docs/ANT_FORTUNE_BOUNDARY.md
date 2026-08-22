# Ant Fortune public-data boundary

- **Boundary resource:** `platform-boundary / ant_fortune / 0.1.0`
- **As of / reviewed:** `2026-08-22T00:22:00Z`
- **Conclusion:** `blocked_pending_authorization`
- **Legal permission claimed:** no
- **Automated adapter available:** no

This is a technical, fail-closed inventory for Issue #9, not legal advice and not
a statement that public access creates permission to collect or reuse content.
No real platform rows, credentials, cookies, personal information, or private
holdings are included.

## What the official entries establish

Only these verified official URLs are used:

- Ant Fortune official public entry: <https://www.antfortune.com/>
- Alipay open-platform public entry: <https://open.alipay.com/>

They support only brand/entry facts. They do **not** establish a documented public
per-fund interface, a field observation, an automatic adapter, or permission to
ingest, cache, derive, display, or redistribute fund data. No confirmed public
Ant Fortune per-fund API is recorded.

The Ant Fortune robots target is
<https://www.antfortune.com/robots.txt>. Its usable policy status is recorded as
`unverified_unavailable`; no `Allow` or `Disallow` rule is inferred. No open-
platform robots URL is asserted. Robots is a collection signal, **not**
authorization, even when it is available.

No official field-level terms URL, rate limit, cache TTL, retention period,
derived-work right, display right, redistribution right, or attribution rule has
been verified. Unknowns are represented by explicit blocked states or sentinels,
never by `null` and never by an implicit grant.

## Candidate field inventory

All per-fund candidates have grain `per_fund_share_class`, access status
`no_authorized_access_mode`, authorization `unknown_blocked`, no ingestion, and
no Open Score eligibility.

| Field ID | Definition | Type | Unit |
|---|---|---|---|
| `fund_identifier` | Platform-specific fund identifier candidate; not canonical identity without independent mapping | `ascii_string` | `identifier` |
| `share_class_identifier` | Platform-specific share-class identifier | `ascii_string` | `identifier` |
| `share_class_name` | Displayed share-class name | `unicode_string` | `text` |
| `subscription_fee` | Displayed subscription/purchase fee candidate | `decimal_string` | `percent` |
| `redemption_fee_tiers` | Redemption fee schedule by holding-period tier | `tier_array` | `percent_by_holding_period` |
| `sales_service_fee` | Recurring sales-service fee candidate | `decimal_string` | `percent_per_year` |
| `ongoing_fee` | Possible displayed ongoing-charge category; not claimed observed | `decimal_string` | `percent_per_year` |
| `management_fee` | Possible displayed management-fee category; not claimed observed | `decimal_string` | `percent_per_year` |
| `custody_fee` | Possible displayed custody-fee category; not claimed observed | `decimal_string` | `percent_per_year` |
| `purchase_amount_limit` | Minimum, maximum, or remaining purchase amount candidate | `money_limit_object` | `currency_amount` |
| `subscription_availability` | Whether subscription/purchase is displayed available | `availability_enum` | `status` |
| `redemption_availability` | Whether redemption is displayed available | `availability_enum` | `status` |
| `sale_availability` | Whether a share class is displayed for sale | `availability_enum` | `status` |
| `platform_rating` | Proprietary platform rating, if later authorized and observed | `external_rating_object` | `provider_defined` |

`platform_brand_entry` is the only marketing-level inventory row. It is entry-
fact evidence only, not evidence for a fund count or any per-fund field.

## Per-field compliance matrix

The packaged resource records every item below on every field rather than relying
on a global assumption:

- definition, value type, unit, and grain;
- public-observation and access-mode status;
- authorization status;
- official source URL and evidence status;
- evidence retrieval and review state/timestamp;
- terms status and URL;
- robots status and URL, plus `robots_is_authorization: false`;
- rate-limit status and value;
- cache status and TTL;
- retention status and value;
- derived, display, redistribution, and attribution status;
- provenance, review status, pending evidence, and re-evaluation triggers;
- namespace, Open Score eligibility, and automated-ingestion permission.

For every per-fund row the current values are fail closed:

| Control | Value |
|---|---|
| observation | `not_observed` |
| official field source/evidence | `not_identified` |
| retrieval | `not_retrieved` |
| terms | `unverified_unknown_blocked`; URL `not_identified` |
| robots | `unverified_unavailable`; URL `not_identified`; never authorization |
| rate limit | `unverified_unknown_blocked`; value `not_established` |
| cache | `unknown_blocked`; TTL `not_established` |
| retention | `unknown_blocked`; value `not_established` |
| derived/display/redistribution | `unknown_blocked` for each purpose |
| attribution | `unverified_unknown_blocked` |
| ingestion / automated adapter | false |
| Open Score | false |

## Access modes and prohibited paths

- `unauthenticated_official_page`: boundary review only; not collection rights.
- `documented_public_api`: no interface identified; blocked.
- `user_authorized_export`: local import only under the user's entitlement;
  public use remains false.
- `login_session`, `private_account`, `login`, `cookie`, `session`, and
  `automated`: prohibited.

The project does not collect account passwords, session cookies, SMS codes,
CAPTCHA solutions, private holdings, or data obtained by reverse engineering.
It does not create an automatic Ant Fortune adapter.

## External-rating isolation

`platform_rating` is fixed to the `external_ratings` namespace. Validation rejects
namespace changes, `open_score_eligible: true`, any allowed derived/display/
redistribution state, and any automatic-ingestion state. The decision API returns
`open_score_allowed: false`, `affects_open_score: false`, and
`automated_adapter_allowed: false`; requesting an Open Score purpose produces the
reason `external_rating_core_score_prohibited`.

## Validation and inspection

```bash
openfundscore resources resolve \
  --type platform-boundary --name ant_fortune --version 0.1.0
openfundscore resources show \
  --type platform-boundary --name ant_fortune --version 0.1.0
openfundscore platform-boundary validate --boundary-version 0.1.0
openfundscore platform-boundary check platform_rating \
  --access-mode automated --use open_score --boundary-version 0.1.0
```

The validator canonicalizes an untrusted input once, rejects duplicate/unknown
fields, unsupported enums, non-finite numbers, booleans used as integers,
cycles, excessive depth/width/length, hostile mappings/sequences, confusable
identifiers, invalid versions/digests/timestamps, and non-allowlisted or non-HTTPS
source URLs. Errors are stable and do not echo hostile content. Decisions are
frozen immutable values and every allowed-purpose flag is false.

## Re-evaluation conditions

Re-review is required if any of the following occurs:

1. an official, documented public per-fund API and field-level terms are
   published;
2. written authorization defines exact fields, access mode, rate limit, cache
   TTL, retention, derived work, display, redistribution, and attribution;
3. official terms or robots information changes (robots still does not grant
   authorization); or
4. a user supplies an authorized export, which can only trigger a separate
   local-entitlement review and cannot silently enable publication.

Until then: no ingestion, no cache, no derived work, no display, no
redistribution, no automated adapter, and no Open Score use.

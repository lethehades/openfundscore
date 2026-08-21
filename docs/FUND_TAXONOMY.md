# Fund Taxonomy v0.1

Classification is multi-axis. `strategy_profile` selects scoring weights while
`vehicle_type`, `share_class`, geography, currency and exposure remain separate.
This prevents labels such as ETF, QDII or LOF from hiding the actual risk source.

## Strategy profiles

| Profile | Included strategies |
|---|---|
| `money_market` | money-market and cash-management public funds |
| `bond` | short-duration, medium/long-duration, pure bond, credit, policy-bank, convertible-bond and secondary-bond funds; peer buckets remain separate |
| `fixed_income_plus` | conservative mixed, partial-debt mixed and fixed-income-plus strategies |
| `active_equity_mixed` | active equity, equity-heavy mixed, flexible allocation and balanced active strategies |
| `index_etf` | domestic broad, factor, dividend, industry, thematic and enhanced index funds/ETFs; active enhancement is a sub-bucket |
| `qdii_active` | active overseas equity, bond, mixed, REIT and regional/global strategies |
| `qdii_index` | overseas index, ETF feeder and passive regional/sector strategies |
| `fof_pension` | FOF, target-date, target-risk and pension target funds |
| `gold_commodity` | gold, commodity, commodity-index and other exchange-traded commodity exposure |
| `public_reit` | publicly offered infrastructure REITs; operator and asset quality replace ordinary fund-manager assumptions |

Special, transforming or legally incomparable funds receive `unrated` until a
sufficient peer bucket and explicit profile exist. “Covered” means ingestion,
classification and reporting are supported; it does not force a misleading
score.

## Complex alternative strategies (research preview)

Market-neutral, long-short, absolute-return, derivatives-heavy (managed
futures/CTA) and other complex public-fund strategies are mapped by the
versioned packaged resource `strategy-mapping / complex_alternatives / 0.1.0`
and the `openfundscore.strategy_mapping` module, never by name heuristics.
Scoring calls must select `mapping_version` explicitly; each returned decision
includes the manifest-verified resource SHA-256 so an evaluation can cite the
exact mapping bytes. Arbitrary validated mapping documents are inspection
artifacts only and cannot authorize a scoring decision. The v0 validator requires
exactly the five documented families and their five designated, distinct buckets;
a new mapping version therefore requires an explicit code/contract update rather
than silently inheriting v0 semantics.

Custom mapping inspection uses strict UTF-8 JSON: files are capped at 1 MiB,
duplicate object keys and non-finite numbers are rejected, parser recursion is
normalized to a redacted error, identifiers are capped at 128 characters, text at
4,096 characters, arrays at 256 items, and mapping objects at 64 entries. Admission
requirements are also upper-bounded. File paths, unknown field names, parser text
and packaged-resource errors are never echoed by the CLI.

| Strategy family | Peer bucket | Score profile (0.1.0) |
|---|---|---|
| `market_neutral` | `market_neutral` | `unrated` — insufficient comparable sample |
| `long_short_equity` | `long_short_equity` | `unrated` — insufficient comparable sample |
| `absolute_return` | `absolute_return_multi_strategy` | `unrated` — insufficient comparable sample |
| `derivatives_heavy` | `managed_futures_derivatives` | `unrated` — insufficient comparable sample |
| `other_complex_alternative` | `other_complex_alternative` (catch-all) | `unrated` — undefined complex strategy |

Rules:

- Named complex families never share one diluted bucket; each keeps its own
  peer bucket so unlike risk sources are never ranked together.
- Every bucket declares machine-checkable admission requirements
  (`min_peer_count`, `min_track_months`, `required_disclosures`). A bucket may
  only be promoted from `unrated` to a real category profile in a new mapping
  version once comparable samples and calibrated evidence meet those gates.
- `unrated` is an explicit decision with a documented reason code; it is not a
  category profile and never produces a score.
- Unknown strategy families fail closed with an error. There is no default or
  best-effort mapping, and no real score or trade is produced anywhere.


## Orthogonal fields

- `vehicle_type`: open-ended, ETF, ETF feeder, LOF, closed-ended, FOF, REIT.
- `management_style`: active, passive, enhanced-index, rules-based.
- `asset_class`: cash, bond, equity, mixed, fund-of-funds, commodity, real asset.
- `geography`: mainland China, Hong Kong, US, Europe, Japan, emerging, global,
  or versioned multi-region allocation.
- `currency`: valuation, trading, hedged and underlying exposure currencies.
- `share_class`: A/C/E/I/R and jurisdiction-specific share classes.
- `benchmark`: primary contract benchmark plus analytical benchmark when needed.
- `cross_border_wrapper`: QDII, Mainland-Hong Kong Mutual Recognition of Funds
  (MRF), cross-border feeder or none. MRF is a distribution/legal status, not a
  performance peer by itself.
- `management_structure`: single manager, co-managed, team, manager-of-managers
  (MOM) or operator. MOM is not treated as duplicated manager evidence.

QDII-FOF uses the FOF/pension profile when its dominant mechanism is manager
selection and allocation, plus QDII currency/geography/settlement modifiers.
Other MRF and MOM products keep the strategy profile implied by underlying risk
and add the corresponding wrapper/structure modifier.

## Entity rule

`fund_strategy` owns mandate, holdings, manager tenures and strategy history.
`share_class` owns fee schedule, distribution policy, dealing currency,
subscription status and investor-specific net outcome. Share classes cannot
create duplicate evidence for the same strategy.

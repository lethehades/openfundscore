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

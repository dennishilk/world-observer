# media-language-germany

`media-language-germany` is a Germany-only, German-language media headline observer.
It collects titles from public RSS feeds and reports transparent keyword-frequency metrics.

## Scope

- Germany-focused observer only.
- German-language news sources only.
- RSS headline/title text only; no full-article scraping.
- No USA, EU, or international comparison.
- No causal, intent, manipulation, propaganda, or real-world-risk claims.
- Observational language-frequency analysis only.

## Public vs private comparison

Each daily run computes the same keyword scoring three ways:

1. Overall across all configured sources.
2. Public broadcasting sources.
3. Private media sources.

The source-group comparison changes only the set of feeds included in each group. The keyword categories, weights, normalization, and `fear_index` formula are identical for both groups, making the comparison transparent and auditable.

### Public broadcasting

- Tagesschau
- ZDFheute
- Deutschlandfunk

### Private media

- Spiegel
- ZEIT
- FOCUS
- n-tv

Only stable/public RSS or equivalent feeds that require no API keys are used. Tabloid media such as Bild are intentionally excluded.

## Sources and limitations

Feeds are publicly accessible RSS or RSS-like endpoints. Availability, feed structure, editorial mix, and update cadence can change without notice. Network failures never crash the observer. If all configured sources fail, the observer still emits valid JSON with `status: "ok"` and `data_status: "unavailable"` plus diagnostics. If only some sources fail, `data_status` is `partial`.

## Categories

Headlines are matched against simple German keyword categories:

- `climate`
- `war_security`
- `health`
- `economy`
- `crime`
- `disaster`
- `political_pressure`
- `general_alarm`

## Score explanation

The observer reports existing overall fields for headlines, matched headlines, total term hits, category counts, top terms, and `fear_index`. It also reports `fear_index_overall` and a `source_groups` object with per-group headline counts, matched headline counts, fear index, category counts, and top terms.

`fear_index` is a normalized weighted keyword frequency per headline:

```text
weighted_hits = sum(category_count[category] * category_weight[category])
raw_frequency = weighted_hits / max(1, headline_count)
fear_index = round(min(100, raw_frequency * 20), 2)
```

The score is intentionally simple and transparent. It is a language-frequency indicator only, not a sentiment model and not evidence of causality, intent, manipulation, propaganda, or public impact.

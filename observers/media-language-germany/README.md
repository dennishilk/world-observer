# media-language-germany

`media-language-germany` is a Germany-only, German-language media headline observer.
It collects titles from a small list of public RSS feeds and reports transparent keyword-frequency metrics.

## Scope

- Germany-focused observer only.
- German-language news sources only.
- RSS headline/title text only; no full-article scraping.
- No USA, EU, or international comparison in V1.
- No causal, intent, manipulation, or real-world-risk claims.

## Sources and limitations

V1 uses a small set of public RSS feeds that do not require API keys. Availability, feed structure, editorial mix, and update cadence can change without notice. If all sources fail, the observer still emits valid JSON with `status: "ok"` and `data_status: "unavailable"` plus diagnostics. If only some sources fail, `data_status` is `partial`.

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

The observer reports counts for headlines, matched headlines, total term hits, category counts, top terms, and `fear_index`.

`fear_index` is a normalized weighted keyword frequency per headline:

```text
weighted_hits = sum(category_count[category] * category_weight[category])
raw_frequency = weighted_hits / max(1, headline_count)
fear_index = round(min(100, raw_frequency * 20), 2)
```

The score is intentionally simple and transparent. It is a language-frequency indicator only, not a sentiment model and not evidence of causality, intent, manipulation, or public impact.

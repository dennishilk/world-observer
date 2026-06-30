# Germany media-language history imports

The dashboard exporter can include optional, manually provided historical snapshots for the Germany Media Language Observer from:

```text
imports/media-language-germany/*.json
```

These files are only used to enrich `dashboard/history/media-language-germany.json` trend analysis. They do not replace the current daily observer output and they do not trigger scraping or source collection.

## Expected JSON shape

Each file must contain one JSON object. The minimal accepted shape is:

```json
{
  "date": "2026-06-01",
  "fear_index_overall": 4.17
}
```

Recommended full shape:

```json
{
  "observer": "media-language-germany",
  "date": "2026-06-01",
  "fear_index_overall": 4.17,
  "headline_count": 266,
  "source_groups": {
    "public_broadcast": {
      "fear_index": 3.8,
      "headline_count": 120
    },
    "private_media": {
      "fear_index": 5.1,
      "headline_count": 146
    }
  },
  "top_terms": [
    {"term": "hitze", "count": 10},
    {"term": "krieg", "count": 9},
    {"term": "polizei", "count": 8}
  ]
}
```

## Accepted date fields

The exporter accepts the first valid date from these fields:

- `date`
- `date_utc`
- `observation_date`

The value must start with an ISO date in `YYYY-MM-DD` format. Longer ISO timestamps are allowed; only the date portion is used for daily history.

## Validation and precedence

- The JSON root must be an object.
- `observer`, when present, must be `media-language-germany`.
- `fear_index_overall` or `fear_index` must be numeric.
- `source_groups`, when present, must be an object.
- `top_terms`, when present, must be an array of objects with `term` and numeric `count` values for term-change analysis.
- Malformed files are ignored and reported in `import_diagnostics` in the exported history JSON.
- If an imported file has the same date as existing daily history, the existing daily history wins and the import is ignored for that date.

## Neutral-use policy

Imported history is used only for observational trend fields such as deltas, averages, public/private spread, and top-term changes. Summary wording must remain neutral and must not make causal claims or claims about manipulation.

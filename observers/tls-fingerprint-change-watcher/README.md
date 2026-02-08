# tls-fingerprint-change-watcher

## Purpose
This observer detects changes in TLS certificate fingerprints for selected public
endpoints. It performs a standard TLS handshake to retrieve the server certificate
metadata, then compares the current SHA-256 fingerprint against the last known
fingerprint stored locally.

## What is a TLS fingerprint?
A TLS certificate fingerprint is a cryptographic hash of the certificate bytes.
In this observer, we use the SHA-256 hash of the leaf certificate presented during
handshake. If the fingerprint changes, it indicates that the certificate (and
likely the underlying infrastructure or issuance path) has changed.

## Why fingerprint changes matter
Fingerprint changes can signal:
- Certificate renewals or replacements.
- Changes in hosting providers or load balancers.
- Potential misconfigurations or unexpected infrastructure shifts.

## State handling
Only the last known fingerprint per target is stored in `fingerprints.json`. This
keeps state minimal and avoids building historical timelines inside the module.
If you need historical analysis, store outputs externally.

## Limitations
- Only a TLS handshake on port 443 is performed.
- No traffic contents are inspected or stored.
- Only the leaf certificate fingerprint and validity window are recorded.
- Handshake failures and timeouts are expected; the observer records them as errors.
- Results depend on the certificate presented at the time of the handshake.

## Ethics and safety
This observer performs minimal, low-impact TLS handshakes against public
endpoints. It does not attempt to bypass access controls or inspect private data.
Use responsibly and only against endpoints you are authorized to monitor.

## Files
- `observer.py`: Runs the handshake and emits JSON output.
- `targets.json`: List of targets (`name`, `host`).
- `fingerprints.json`: Stores the last known fingerprint per host.

## Output schema
```json
{
  "observer": "tls-fingerprint-change-watcher",
  "timestamp": "ISO8601",
  "targets": [
    {
      "name": "...",
      "host": "...",
      "fingerprint_sha256": "...",
      "valid_from": "...",
      "valid_to": "...",
      "changed": false,
      "error": null
    }
  ],
  "notes": "..."
}
```

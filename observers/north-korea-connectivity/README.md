# north-korea-connectivity

## Purpose
This observer provides **minimal, passive reachability signals** for a small,
public list of North Korea–associated targets. It is intentionally limited to
avoid scanning, probing beyond basic reachability, or collecting sensitive data.

## What is measured
Each run emits a JSON snapshot with:
1. **ICMP ping** — Boolean success and round-trip time (if permitted).
2. **TCP 443 handshake** — Boolean success and connection time (no data exchange).
3. **DNS behavior** — A/AAAA query status and any answers.

Targets are defined in `targets.json` within this module.

## What is NOT measured
- No port scanning beyond TCP/443.
- No brute force or exploitation.
- No traceroutes, routing maps, or network topology inference.
- No tracking of individuals or user identifiers.
- No bypassing of filtering, censorship, or access controls.

## Limitations and ethics
Connectivity into and out of North Korea is heavily filtered and often silent.
Silence is **expected** and treated as a valid result; it is **not** a prompt to
increase probing. Measurements are intentionally narrow and infrequent, and the
observer stores no historical state.

## Dependencies
The observer uses the Python standard library. For DNS A/AAAA queries with
proper status classification, it relies on **dnspython** (`dns.resolver`). If
dnspython is not installed, DNS results are returned with `error:
"dnspython_not_installed"`.

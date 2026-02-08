# undersea-cable-dependency

## What undersea cable dependency means
Undersea cable dependency describes how much a country relies on submarine
fiber-optic cables for international connectivity. Countries with a small
number of cables or limited geographic diversity in those cables may be more
structurally dependent on a narrow set of physical paths, even when networks
appear healthy.

## What this observer does
- Reads a **static** undersea cable dataset from `cables.json`.
- Counts the total number of cables per country.
- Counts distinct regions represented by those cables.
- Performs minimal reachability checks (ICMP ping and TCP 443) to a small,
  fixed list of targets from `targets.json`.
- Outputs a JSON summary with a neutral, descriptive note.

## What this observer does NOT do
- It does **not** monitor live cable status.
- It does **not** infer outages, sabotage, or disruptions.
- It does **not** scrape websites or call external APIs.
- It does **not** run traceroute or routing analysis.

## Limitations of static data
Static cable listings can be incomplete, outdated, or overly simplified. They
reflect published infrastructure but do not confirm operational status, repair
conditions, or current traffic flows. The reachability checks are intentionally
minimal and only indicate whether a small set of public endpoints can be
reached at the time of execution.

## Ethical boundaries
This observer is designed to be conservative and non-invasive. It avoids
speculative claims, limits network probing to basic reachability checks, and
stores no sensitive routing details. The output should be used for structural
context only, not for attributing incidents or making real-time assessments.

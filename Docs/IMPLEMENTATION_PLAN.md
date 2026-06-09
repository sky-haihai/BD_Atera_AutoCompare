# BD / Atera Endpoint Alignment Tool

## Summary

Build the tool as three separate modules instead of one large script:

1. Atera CSV module: pull Atera agents and export a normalized CSV.
2. BD CSV module: read or later pull Bitdefender Endpoint Protection Status data and export a normalized CSV.
3. CSV compare module: compare the two normalized CSVs and produce an exception-only review report.

V1 uses Atera API plus a manually downloaded BD report. BD API support is deferred, but the BD module should keep the same normalized CSV output contract so an API implementation can be added later without changing the compare module.

Docs checked:

- Atera API: https://support.atera.com/hc/en-us/articles/219083397-API
- Bitdefender Reports API: https://www.bitdefender.com/business/support/en/77211-135313-reports.html
- Bitdefender createReport: https://www.bitdefender.com/business/support/en/77211-135314-createreport.html

## Module 1: Atera CSV Export

Purpose: pull Atera agent data and write a normalized Atera CSV.

Design constraint:

- Keep the Atera data acquisition behind a small provider interface so the caller only depends on "return normalized Atera rows".
- The API implementation is one provider; a future manual Atera CSV import can be another provider without changing the compare module.
- Each method should do one job only, such as fetch raw API data, map one raw record, validate normalized rows, or write CSV.

Inputs:

- Required environment variable: `ATERA_API_KEY`
- Optional environment variable: `ATERA_BASE_URL`, default `https://app.atera.com/api/v3`

Data source:

- `GET /api/v3/agents`

Expected Atera API fields:

- `MachineName`
- `CustomerName`
- `IPAddress`
- `Online`
- `LastSeen`
- `AgentID`
- `MachineID`
- `DeviceGUID`

Normalized Atera CSV output:

- File example: `data/atera_agents.csv`
- Required columns:
  - `Device Name`
  - `Company Name`
  - `IP Address`
  - `Status`
  - `Last Seen`
  - `Atera Agent ID`
  - `Atera Machine ID`
  - `Atera Device GUID`

Rules:

- Convert Atera field names into the normalized CSV column names above.
- Preserve the original device name exactly except trimming leading/trailing spaces.
- Convert `Online` into a status value usable by the compare module.
- Do not apply device aliases in this module; aliasing belongs in the compare module.

## Module 2: BD CSV Prepare

Purpose: accept BD Endpoint Protection Status data and write a normalized BD CSV.

Design constraint:

- Keep BD data acquisition behind a small provider interface so the caller only depends on "return normalized BD rows".
- Manual report parsing is the V1 provider; a future BD Reports API provider must output the same normalized row shape.
- Each method should do one job only, such as read manual CSV, validate source headers, map one source row, or write normalized CSV.

V1 input:

- Manually downloaded Bitdefender Endpoint Protection Status CSV.

Future input:

- BD Reports API can be added later, but it must output the same normalized BD CSV shape.

Required source headers for V1 manual CSV:

- `Device Name`
- `Company Name`
- `IP Address`
- `Status`
- `Last Seen`

Normalized BD CSV output:

- File example: `data/bd_endpoint_status.csv`
- Required columns:
  - `Device Name`
  - `Company Name`
  - `IP Address`
  - `Status`
  - `Last Seen`
  - `BD Row Number`

Rules:

- Validate required headers before processing.
- Preserve the source device and company names except trimming leading/trailing spaces.
- Add `BD Row Number` so review rows can point back to the manual BD report.
- Do not apply aliases in this module; aliasing belongs in the compare module.

## Module 3: CSV Compare

Purpose: compare normalized Atera CSV and normalized BD CSV, then output exception-only results.

Design constraint:

- The compare module should not know how Atera or BD data was obtained.
- It should only consume normalized row objects or normalized CSV files.
- Split comparison work into small, single-purpose functions: normalize keys, apply aliases, detect duplicates, find exact matches, find low-confidence pairs, and build report rows.

Inputs:

- `data/atera_agents.csv`
- `data/bd_endpoint_status.csv`
- Optional device alias CSV:
  - `Company Name`
  - `Raw Device Name`
  - `Canonical Device Name`

Output:

- File example: `reports/exceptions.csv`

Output columns:

- `Atera Device Name`
- `BD Device Name`
- `Canonical Device Name`
- `Company Name`
- `Missing Software`
- `Issue Type`
- `Match Evidence`
- `Name Similarity`
- `Atera IPv4`
- `BD IPv4`
- `Atera Status`
- `BD Status`
- `Atera Last Seen`
- `BD Last Seen`
- `Atera Count`
- `BD Count`
- `Atera Agent IDs`
- `Atera Machine IDs`
- `Atera Device GUIDs`
- `BD Row Numbers`
- `Alias Applied`
- `Notes`

Primary matching:

- Match only within the same normalized company.
- Normalize company and device names by trimming spaces and comparing case-insensitively.
- Apply optional company-scoped device aliases before matching.
- Do not automatically strip notes such as `(Datatrasfer to Alison)`; handle those through aliases.

Duplicate handling:

- After aliasing, if the same company plus canonical device appears multiple times on either side, output `Duplicate Manual Review`.
- Do not auto-classify missing software for duplicated records.

Low-confidence pairing:

- Run only after primary matching and duplicate handling.
- Compare remaining unmatched Atera and BD records within the same company.
- Name similarity threshold: `80%`, using Python stdlib `difflib.SequenceMatcher`.
- Compare IPv4 only; ignore IPv6.
- If any IPv4 overlaps and names are at least 80% similar, output `Potential Match Manual Review`.
- If IPv4 is missing or does not match, require both sides to be offline using loose detection.
- For offline fallback, `Last Seen` must be the same local date and within 60 minutes.
- Parse timezone if present; if absent, assume `America/Edmonton`.
- Do not also output separate Missing Atera/Missing BD rows for a low-confidence pair.
- If one record has multiple possible counterparts, output `Ambiguous Potential Match Manual Review` rows with evidence for manual review.

Exception rules:

- Atera only: `Missing Software = Bitdefender Endpoint Protection`, `Issue Type = Missing BD`.
- BD only: `Missing Software = Atera Agent`, `Issue Type = Missing Atera`.
- Exact single match: omit.
- Duplicate: `Duplicate Manual Review`.
- Suspicious pair: `Potential Match Manual Review`.
- Bad or missing required data: `Data Quality Review`.

## Planned CLI Shape

The implementation should expose separate commands or entry points for each module:

- `atera-export --output data/atera_agents.csv`
- `bd-prepare --bd-report path\to\bd_report.csv --output data/bd_endpoint_status.csv`
- `compare --atera-csv data/atera_agents.csv --bd-csv data/bd_endpoint_status.csv --output reports/exceptions.csv --device-aliases path\to\device_aliases.csv`

This keeps collection and comparison separate. The compare module should not call Atera or BD APIs directly; it should only consume normalized CSV files.

## Code Design Principles

- Use the smallest practical design: no large all-in-one script and no broad abstraction unless it protects a real future change.
- Prefer single-responsibility methods; each method should transform, validate, fetch, compare, or write, but not mix those concerns.
- Use interface-style boundaries around data acquisition:
  - Atera provider returns normalized Atera rows.
  - BD provider returns normalized BD rows.
  - Compare service consumes normalized rows only.
- Keep normalized CSV schemas as the contract between modules.
- Keep provider implementations replaceable:
  - Atera API provider can later be replaced or supplemented by Atera CSV import.
  - BD manual CSV provider can later be replaced or supplemented by BD API report download.
- Keep matching and reporting logic independent from API clients, HTTP details, file download behavior, and authentication.
- Prefer clear plain data structures over deep class hierarchies.
- Add tests at the module boundary level so data-source changes do not require rewriting compare tests.

## Test Plan

- Atera module writes the normalized Atera CSV columns.
- BD module validates required headers and writes normalized BD CSV columns.
- Compare module omits exact matches.
- Case and space normalization works.
- Alias maps annotated names to canonical names and is company-scoped.
- Duplicate detection happens after aliasing.
- Atera-only and BD-only output correctly.
- IPv4 plus 80% similar name creates a potential match.
- IPv6 is ignored.
- Offline plus same-day Last Seen within 60 minutes creates a potential match.
- Last Seen beyond 60 minutes does not create a potential match.
- Ambiguous candidates are marked for manual review.

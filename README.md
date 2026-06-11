# BD / Atera AutoCompare

BD / Atera AutoCompare is a Python 3.10+ tool for comparing Atera agent inventory against Bitdefender GravityZone endpoint inventory. It pulls both APIs, writes normalized CSV snapshots, and produces exception-focused CSV reports for manual review.

The intended end-user entry point is the Tkinter desktop app packaged as `BD_Atera_AutoCompare.exe`. CLI commands are kept for development, testing, and automation.

## Current Workflow

The full pipeline does three things:

1. Pulls Atera agents from `GET /agents` and writes `atera_agents.csv`.
2. Pulls Bitdefender Network API inventory with `getNetworkInventoryItems`, enriches endpoint rows with company and Deleted-folder context, and writes `bd_endpoint_status.csv`.
3. Compares the normalized CSVs and writes:
   - `mismatch.csv` for review-worthy exceptions.
   - `duplicates.csv` for duplicate canonical company/device keys.

For the packaged app, default paths are resolved from the folder that contains `BD_Atera_AutoCompare.exe`. For local Python runs, CLI defaults are relative to the current working directory.

## Packaged App Usage

Place these files in the same folder:

- `BD_Atera_AutoCompare.exe`
- `.env`

Create `.env` from `.env.example`:

```dotenv
ATERA_API_KEY=your-atera-api-key
# ATERA_BASE_URL=https://app.atera.com/api/v3
# ATERA_USER_AGENT=BD-Atera-AutoCompare/0.1

BD_API_KEY=your-bitdefender-api-key
# BD_API_URL=https://cloud.gravityzone.bitdefender.com/api/v1.0/jsonrpc/network
# BD_PARENT_ID=optional-company-or-group-id
# BD_COMPANY_NAME=optional-company-name-for-output
```

Run the executable, confirm the `.env` file and output folder, optionally adjust the Atera and Bitdefender page sizes, then click **Run**.

By default, the app writes these files under `data/` next to the executable:

- `data/atera_agents.csv`
- `data/bd_endpoint_status.csv`
- `data/mismatch.csv`
- `data/duplicates.csv`

The UI also contains an **Include unprotected BD endpoints** checkbox. In the current code, the BD export already writes endpoint inventory with BEST status fields, and the compare stage decides whether an endpoint counts as protected. The flag remains wired through for compatibility with earlier behavior.

## Configuration

Required values:

- `ATERA_API_KEY`
- `BD_API_KEY`

Optional Atera values:

- `ATERA_BASE_URL` defaults to `https://app.atera.com/api/v3`.
- `ATERA_USER_AGENT` defaults to `BD-Atera-AutoCompare/0.1`.

Optional Bitdefender values:

- `BD_API_URL` defaults to `https://cloud.gravityzone.bitdefender.com/api/v1.0/jsonrpc/network`.
- `BD_PARENT_ID` limits the Bitdefender inventory request to a company or group scope.
- `BD_COMPANY_NAME` is used as a fallback company name when the API row cannot be resolved from inventory data.
- `BD_USER_AGENT` can override the Bitdefender request user agent.

The Bitdefender provider also accepts the legacy environment names `BITDEFENDER_API_KEY`, `BITDEFENDER_API_URL`, `BITDEFENDER_PARENT_ID`, `BITDEFENDER_COMPANY_NAME`, and `BITDEFENDER_USER_AGENT`.

`.env` values take precedence over process environment values. Missing `.env` files are ignored, but missing API keys cause the run to fail.

## Normalized Outputs

`atera_agents.csv` contains the stable Atera comparison fields:

- device name, company name, IP addresses, reported-from IP, MAC addresses, serial number, status, last seen, Atera agent ID, machine ID, and device GUID.

`bd_endpoint_status.csv` contains a wider Bitdefender endpoint snapshot:

- device name, company name, IP address, status, last seen, endpoint/company/parent IDs, network item type, Deleted-folder flag, label, FQDN, group ID, MAC addresses, SSID, management flags, policy fields, moving state, product-outdated flag, last successful scan, and module state summary.

CSV files are written with UTF-8 BOM encoding and stable column order. Parent folders are created automatically.

## Compare Behavior

The compare stage uses canonical `Company Name + Device Name` keys after trimming whitespace and case-folding. Exact one-to-one matches are omitted from `mismatch.csv` when the Bitdefender row is managed with BEST.

Rows are written to `mismatch.csv` for cases including:

- `Missing BD`: an Atera device has no matching protected Bitdefender endpoint.
- `Missing BD`: a matching Bitdefender endpoint exists but `Managed With BEST` is false, `0`, `no`, or status indicates `No BEST` / `Unmanaged`.
- `Missing Atera`: a protected Bitdefender endpoint has no Atera match.
- `Duplicate Manual Review`: more than one Atera or Bitdefender row shares the same canonical company/device key.
- `Potential Match Manual Review`: same-company rows have supporting evidence such as IPv4 overlap or close offline last-seen timing and sufficient name similarity.
- `Ambiguous Potential Match Manual Review`: one record has multiple potential matches.
- `Data Quality Review`: required fields are missing, alias rows are incomplete, or a supplied BD CSV row is not an endpoint type.

Important current rules:

- Bitdefender rows marked `Is In Deleted Folder=true` are ignored during comparison.
- A Bitdefender-only row that is not managed with BEST is ignored instead of producing `Missing Atera`.
- MAC address overlap is treated as strong device evidence, even across company names. If at least one overlapping Bitdefender row is managed with BEST, that Atera device is considered covered.
- IPv6 values are ignored for potential IPv4 matching.
- Offline last-seen matching assumes America/Edmonton local time when timestamps do not include a timezone and only matches within a 60-minute window.
- Unparseable `Last Seen` values are kept as notes on the record; they only appear in reports if that record is otherwise reported.
- `compare` still accepts older Bitdefender CSVs with only `Device Name`, `Company Name`, `IP Address`, and `Status`, although the generated BD CSV has many more columns.

## Alias Files

Alias files are optional. Missing alias files are ignored.

For the desktop app, place them in the selected output folder. With default packaged paths, that means:

- `data/company_aliases.csv`
- `data/device_aliases.csv`

`company_aliases.csv` must use these headers:

```csv
Atera Company Name,BD Company Name
Example Atera Name,Example Bitdefender Name
```

Company aliases map Atera company names to the Bitdefender company names used for comparison.

`device_aliases.csv` must use these headers:

```csv
Company Name,Raw Device Name,Canonical Device Name
Example Bitdefender Name,DESKTOP-123,Accounting-01
```

Device aliases are scoped by canonical company name. If a company alias exists, use the Bitdefender-side company name in `device_aliases.csv`.

Incomplete alias rows do not abort comparison; they produce `Data Quality Review` rows in `mismatch.csv`.

## CLI Commands

Install the package in editable mode first:

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Run the desktop app from source:

```powershell
python run_autocompare.py
```

Run the package entry point:

```powershell
python -m bd_atera_autocompare
```

Run the full CLI pipeline:

```powershell
bd-atera-autocompare --env-file .env
```

Run individual stages:

```powershell
atera-export --env-file .env --output data/atera_agents.csv
bd-prepare --env-file .env --output data/bd_endpoint_status.csv
compare --atera-csv data/atera_agents.csv --bd-csv data/bd_endpoint_status.csv --output data/mismatch.csv --duplicates-output data/duplicates.csv
```

Useful CLI options include:

- `--http-timeout`
- `--atera-page-size`
- `--bd-page-size`
- `--bd-parent-id`
- `--bd-company-name`
- `--bd-no-recursive`
- `--bd-no-product-outdated`
- `--bd-no-scan-logs`
- `--company-aliases`
- `--device-aliases`

Use `--help` on any command for the full option list.

## Build the Windows Executable

Install the build dependency:

```powershell
python -m pip install -e .[build]
```

Build with PyInstaller:

```powershell
python -m PyInstaller BD_Atera_AutoCompare.spec
```

The executable is written to:

```text
dist\BD_Atera_AutoCompare.exe
```

The Python installation used for packaging must include Tcl/Tk so Tkinter can be bundled. The official Windows Python installer includes it by default unless the `tcl/tk and IDLE` option was disabled.

## Tests

```powershell
python -m unittest discover tests
```

The tests use mocked providers and local CSV fixtures. They do not require live Atera or Bitdefender access.

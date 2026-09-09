[Русский](README.md) · **English**

# netwrench-data

Reference data that NetWrench fetches as a file, without an application
update. There is no code here — only facts the application shows a technician.

## router-defaults.json — factory login for routers

Management address and factory credentials by vendor and model. They are
needed where NetWrench has no authentication module for a device yet: the
application has identified the router but cannot configure it — and so it
shows where to log in by hand, and with what.

The data is public: all of it is printed in vendor manuals and on the boxes.
NetWrench never guesses and never brute-forces — a pair is filled into the
fields, and a human performs the login.

### Format

```json
{
  "schema": 2,
  "version": 2,
  "updated": "2026-09-09",
  "entries": [ … ]
}
```

`version` is an integer that grows with every change. The application accepts
a file only when its `version` is higher than the current one, so raise it in
the same commit that edits the entries.

An entry:

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Stable entry identifier, unique within the file |
| `vendor` | yes | Vendor name **exactly as the detector reports it** — see below |
| `models` | no | Canonical models. Without this field the entry covers the vendor's whole range |
| `addresses` | yes | Management addresses: IP and/or hostname, primary one first |
| `access` | yes | Management services and their ports — see below |
| `auth` | yes | How logging in works — see below |
| `factoryReset` | no | `holdSeconds` and/or `note`: how to reset to factory defaults |
| `verified` | no | `true` when the value was confirmed on real hardware during development |
| `note` | no | Short note, an object `{ru, en}` |
| `source` | no | Where it came from |

### access

A list of services, each `{type, port, enabled}`. `enabled` describes the
**factory** state: `false` means the service exists but is switched off, and
knocking on it is pointless until it is enabled through the web interface.
This spares the technician from diagnosing a failure that is not one.

Allowed `type` values: `http`, `https`, `ssh`, `telnet`, `api`, `api-tls`,
`winbox`. A web interface (`http` or `https`) must be present.

`ssh` and `telnet` with their ports feed NetWrench's terminal directly.

### auth

| Field | Meaning |
| --- | --- |
| `usernameField` | Whether the login form has a username field at all. Tenda, Mercusys, Xiaomi and newer Archer units are entered with a password only |
| `username` | Factory username. `null` when there is no field, or the user invents it |
| `usernameCreated` | The username is created by the user at first login |
| `password` | Factory password. `""` — empty, the field is left blank. `null` — no ready password exists |
| `passwordCreated` | The password is created by the user at first login |
| `passwordOnLabel` | The password is printed on the device label. This coexists with a factory pair: on a retail unit `admin/admin` works, while an ISP-branded build of the same vendor uses the label |
| `wizardBlocks` | Management is unavailable until the first-run wizard has been completed (§ 9.2 of the project rules) |

`validate.py` enforces consistency: a value the user invents cannot be in the
database, and a password cannot be both created at first login and printed on
the label.

There is deliberately no separate "state" field — it follows from `auth`, and
storing it alongside would create a second source of truth that sooner or
later disagrees with the first.

### Lookup rule

1. Exact match on `vendor` **and** `models`.
2. Otherwise the entry for the same `vendor` without `models`.
3. Otherwise nothing; the application shows only what it measured itself.

Entries with `models` are placed above the vendor's general entry so that
reading order matches lookup order.

### Vendor names

`vendor` must match the string NetWrench's detector reports, or the entry will
never be found. The strings come from the application repository:

* `discovery/…/RouterDetector.kt`, function `detectVendor` — the general brand dictionary;
* `discovery/…/<vendor>/…FingerprintConfig.kt`, constant `VENDOR_FAMILY` — families with a detector of their own.

### Check before publishing

```sh
python3 validate.py
```

A non-zero exit code means the file must not be published.

## Licence and provenance

The file is compiled by hand from vendor manuals and from devices verified
during development. It is not a copy of anyone else's database: no ready-made
dataset was taken (including from the EU, where the sui generis database right
applies), and none may be — NetWrench is distributed as a paid product.

Entries marked `"verified": true` were confirmed on real hardware.

# Authenticated and gated sites

mdb's native engine remains the default. It renders JavaScript, imports the
user's Safari cookies on macOS, classifies the captured page, and sends a
bundle through the same deterministic Markdown compiler used everywhere
else.

Some sites bind authentication to more than cookies or expose useful content
only through their application APIs. For a small, explicit set of URL shapes,
mdb can delegate the read to an optional tool and normalize the result back
into an mdb bundle.

## Decision manifest

| Observation | Strategy | Expected result |
|---|---|---|
| Native capture is readable | Keep native bundle | No external process or credential surface |
| Native result is `wall` or `app`, URL is covered | Offer authenticated backend | User chooses whether to expand trust |
| `--allow-external-fallback` or `--backend auto` | Prefer installed OpenCLI, then twitter-cli | One read-only retry with provenance |
| Named `--backend` | Skip native capture | Explicit backend attempt or a classified error |
| MCP default reaches a covered gate | Return confirmation guidance | No hanging prompt and no silent credential use |

Every successful external bundle records `mode: external-authenticated`,
`backend`, and `fallback_reason` in the emitted front matter.

## Supported routes

| URL shape | OpenCLI | twitter-cli |
|---|---|---|
| `x.com/<user>/status/<id>` | `twitter thread` | `twitter tweet --json` |
| `x.com/home` | `twitter timeline` | `twitter feed --json` |
| `x.com/search?q=...` | `twitter search` | `twitter search --json` |
| `x.com/<user>` | `twitter profile` | — |
| `reddit.com/.../comments/...` | `reddit read` | — |

The registry intentionally lists only command contracts mdb can normalize and
test. OpenCLI supports many more sites, but adding a route requires a stable,
read-only command and an offline contract fixture; installed does not mean
every OpenCLI adapter is automatically authorized.

## Install separately

Inspect current status first:

```bash
mdb setup backends
```

OpenCLI's recommended desktop installation is the OpenCLI app plus its Chrome
Browser Bridge extension:

- <https://opencli.info/download>
- <https://github.com/jackwener/OpenCLI>

After installation, open Chrome, verify that the intended profile is logged
in, and run `opencli doctor`.

twitter-cli is installed as an isolated uv tool:

```bash
uv tool install twitter-cli
twitter status --json
```

Upstream documentation:
<https://github.com/public-clis/twitter-cli>

mdb does not install, upgrade, or configure either project. That keeps the
core package self-contained and makes the added trust boundary visible.

## Use

Native-first, interactive reader:

```bash
mdb https://x.com/example/status/123
```

If the result is classified as gated and a compatible backend is installed,
press `E`; mdb names the preferred backend and asks for confirmation.

Explicit and automated modes:

```bash
mdb URL --backend opencli
mdb URL --backend twitter-cli
mdb URL --backend auto
mdb URL --allow-external-fallback
```

`auto` and `--allow-external-fallback` still perform the cheap native
classification first. They do not send every page through an external tool.

For MCP, `fetch_page` accepts `backend` and `allow_external_fallback`. The
default is `backend="native"`; a covered gated result describes the available
choices and asks the caller to repeat the request explicitly.

## Security model

- OpenCLI reuses the logged-in Chrome profile through an extension and local
  daemon. Credentials stay in Chrome, but the bridge is capable of page
  interaction. mdb routes only read commands.
- twitter-cli forwards browser cookies to unofficial X GraphQL endpoints.
  Interface churn, rate limits, and account enforcement remain possible.
- Never paste cookie headers into an mdb command, configuration file, issue,
  or agent conversation.
- `--private` governs mdb's native capture and cannot be combined with an
  authenticated backend or fallback.
- External command failures include backend name, exit code, and a bounded
  diagnostic. mdb does not silently replace the result with another
  credential-bearing backend.

Run `mdb --dump bundle` to inspect provenance and `mdb --dump manifest` to see
the resulting classification.

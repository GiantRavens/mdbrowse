# Homebrew Core readiness

This is the preflight and evidence log for converting the `mdbrowse` tap
formula from an online `pip install` into a reproducible Homebrew formula.

## Resource manifest

Observed 2026-07-23 before resource generation:

| Input | Classification | Strategy | Predicted outcome |
|---|---|---|---|
| `mdbrowse` v2.0.1 GitHub tag | Immutable main source | Keep tagged tarball and SHA-256 | Stable formula source |
| `httpx`, `mcp`, `playwright`, `rich` | Direct Python runtime roots | Resolve recursively with `brew update-python-resources` | Checksummed source resources |
| `pydantic-core`, `rpds-py` | Rust-backed transitive packages | Declare `rust` as a build dependency | Source builds without wheels |
| `cryptography` | Native transitive package already maintained by Core | Use Homebrew's `cryptography` formula with `:no_linkage` | Avoid duplicate native dependency ownership |
| `greenlet`, `pydantic-core`, `rpds-py` | Native source resources | Build through Homebrew's Python helper and Rust toolchain | Compiler/link failures become visible at formula build |
| Python 3.14 | Current Core Python line | Use `python@3.14` explicitly | Matches current Core policy |
| Formula test | Version-only smoke test | Exercise offline fixture compilation | Verifies installed behavior, not merely executable presence |
| Chrome/Chromium | Optional runtime engine | Keep outside the formula dependency graph | CLI/compiler self-test remains browser-free |

Expected resource roots: 4 direct and roughly 30 recursive Python packages.
Generation succeeds only if every source URL and SHA-256 resolves. The
expensive source build starts only after the generated resource set has no
`RESOURCE-ERROR` markers.

The resource graph pins application runtime inputs. Homebrew's
`virtualenv_install_with_resources` still uses standard PEP 517 build
isolation, whose build backends may resolve their own temporary build inputs.
That distinction is visible in verbose source-build telemetry and is
consistent with current Core formulas containing Rust-backed Python
resources. Playwright is the one runtime exception because PyPI publishes no
source distribution: the formula pins its GitHub source tag, sets the version
expected by its build, and replaces its bundled Node executable with
Homebrew's managed `node`, following the existing `pytr` Core formula.

## Acceptance

- [x] No install-time runtime dependency resolution.
- [x] Every formula-owned Python dependency is an immutable, checksummed
      resource.
- [x] Formula uses `virtualenv_install_with_resources`.
- [x] Source build and functional `brew test` pass.
- [x] `brew style`, `brew audit --strict --online`, and the locally applicable
      parts of `brew audit --new --formula` pass.
- [x] External Core submission gates are recorded separately from technical
      formula readiness.

## Verification result

Verified on 2026-07-23:

- 31 checksummed Python runtime resources, with `certifi` and `cryptography`
  supplied by their existing Homebrew formulas.
- Clean source reinstall completed with all native extensions built for
  CPython 3.14.
- Imports passed for `cryptography`, `greenlet`, `mcp`, `playwright`,
  `pydantic_core`, and `rpds`.
- `brew test`, `brew linkage --test`, `brew style`,
  `brew audit --strict --online`, and `brew audit --new --formula` passed.
- Installed CLI and MCP entry points both started successfully.

The verification host runs prerelease macOS 27, which Homebrew classifies as
Tier 2. Its dyld rejects Rust dylibs affected by LLVM's known misaligned
`LINKEDIT` bug when `-C strip=debuginfo` is used. The formula therefore
appends `-C strip=none` only on macOS 27 or newer. Before that workaround,
both `pydantic_core` and `rpds` failed the import gate; after a clean rebuild,
both passed. Remove the workaround once the fixed LLVM reaches the supported
Homebrew Rust toolchain.

References: [Homebrew language-specific formulae][language-formulae],
[package acceptance policy][acceptance-policy], and
[Rust issue #157750][rust-linkedit].

[language-formulae]: https://docs.brew.sh/Language-Specific-Formulae
[acceptance-policy]: https://docs.brew.sh/Package-Acceptance-Policy
[rust-linkedit]: https://github.com/rust-lang/rust/issues/157750

## External submission gate

Homebrew's package acceptance policy requires public interest beyond the
author. A repository-owner self-submission normally needs 90 forks, 90
watchers, or 225 stars; maintainer discretion and documented exceptions still
apply. This does not block a high-quality third-party tap formula, but it can
block an immediate `homebrew/core` submission.

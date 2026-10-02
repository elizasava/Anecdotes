# Anecdotes Risk CLI

Interactive command-line tool for creating and updating risks **directly in Anecdotes**.

Anecdotes is the source of truth. This tool writes no local files, creates no YAML,
touches no mapping file, and opens no pull requests. It is independent of the
GitHub/YAML risk sync workflow in `scripts/` — you can copy `risk_cli.py` anywhere
and it will run on its own.

## Setup

Requires Python 3.9+ and `requests`:

```bash
pip install -r cli/requirements.txt
```

Then set your **own** Anecdotes API token:

```bash
export ANECDOTES='<your api token>'
```

### About the token

- It is read from your local environment only. Never commit it, and never add it
  to a `.env` file that is tracked by git.
- Use your own personal token rather than a shared team token. Anecdotes records
  the token as the actor, so a shared token makes it impossible to tell who
  created or changed a risk.
- Avoid putting it in `~/.zshrc` — that is plaintext on disk and leaks into shell
  history and backups. Prefer macOS Keychain, `direnv` with a gitignored
  `.envrc`, or your team's secret manager.

The `ANECDOTES` **GitHub** secret is unrelated: it exists so the Actions sync
workflow can run unattended. This CLI needs no repository secret.

### Optional overrides

All default to values baked into `risk_cli.py`:

| Variable | Purpose |
| --- | --- |
| `ANECDOTES_REGISTER_ID` | Target risk register |
| `ANECDOTES_API_BASE_URL` | API gateway |
| `ANECDOTES_AUTH_URL` | API-key to JWT exchange endpoint |
| `ANECDOTES_USER_AGENT` | User-Agent sent to Anecdotes |

## Usage

Always start with `--dry-run`.

```bash
python3 cli/risk_cli.py create --dry-run
python3 cli/risk_cli.py update --dry-run

python3 cli/risk_cli.py create
python3 cli/risk_cli.py update
```

`create` walks you through the six managed fields, shows a preview, and asks for
confirmation. Anecdotes generates the Risk ID; the CLI never invents one.

`update` lists risks from Anecdotes, requires you to explicitly select one,
shows its current values, lets you edit any field, prints an OLD -> NEW diff, and
patches only the fields that actually changed.

Dropdown options (UKI Brand, Domain) are always fetched live from Anecdotes, so
the menus cannot drift out of date. Matching is case- and whitespace-insensitive,
and you never need to know the `CYB`/`TR` option codes.

## Safety

- **`--dry-run` is enforced at the HTTP layer.** The client refuses any
  POST/PATCH/PUT/DELETE before the request is built, so a bug in the CLI cannot
  produce a write. Reads still hit the real API, so the payload shown is the real
  payload.
- **Confirmation defaults to No.** Only `y` or `yes` proceeds.
- **There is no delete.** Deliberately not implemented.
- **Fails closed.** If the target risk cannot be identified unambiguously, the
  CLI stops rather than guessing. It never falls back to creating a risk when an
  update target is not found.
- Credentials are never printed.

### Concurrent edits

There is no locking or conflict detection. If two people edit the same risk at
the same time, the second PATCH silently overwrites the first. Coordinate with
colleagues before bulk-editing, or re-run `update` to confirm the current state
immediately before applying changes.

## Tests

```bash
python3 -m pytest cli -q
```

50 tests, no network calls, no credentials needed. They run automatically in CI
via the `Validate risks` workflow.

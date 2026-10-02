# Anecdotes Risk CLI

Interactive command-line tool for creating and updating risks **directly in Anecdotes**.

Anecdotes is the source of truth. This tool writes no local files, creates no YAML,
touches no mapping file, and opens no pull requests. It is independent of the
GitHub/YAML risk sync workflow in `scripts/` — you can copy `risk_cli.py` anywhere
and it will run on its own.

## Setup

### Step 1 — Install the dependency (once per machine)

Requires Python 3.9+ and `requests`:

```bash
pip install -r cli/requirements.txt
```

You only ever do this once. It is not needed per session — the only per-terminal
step is entering the token (step 3).

### Step 2 — Open a terminal in the repo

```bash
cd /path/to/Anecdotes
```

A fresh terminal tab avoids inheriting stale environment variables.

### Step 3 — Enter your token without exposing it

```bash
read -rs "ANECDOTES?Anecdotes token: " && export ANECDOTES
```

Press Enter, paste the token, press Enter again. **Nothing appears as you type —
that is expected.**

Use this rather than `export ANECDOTES='...'`. Typing the token directly on the
command line writes it in clear text into `~/.zsh_history`, where it persists
indefinitely and ends up in backups. `read -rs` keeps it out of history and off
the screen; the `-s` suppresses echo and the `-r` stops backslashes being
interpreted.

### Step 4 — Confirm it was set

```bash
echo "${#ANECDOTES}"
```

This prints the character count, never the token. A plausible non-zero number
means you are ready. `0` means it did not take — repeat step 3.

If the number is roughly double what you expect, you pasted twice. That produces
`HTTP 401: Api key invalid`, which is the most common first-run failure.

### Token scope and lifetime

The token lives **only in that terminal tab**, in memory, until you close it.
Other tabs and other applications cannot see it. Processes you launch from that
tab inherit it, which is how the CLI receives it — so avoid running untrusted
scripts from the same tab.

Open a new tab and you repeat step 3. To clear it early:

```bash
unset ANECDOTES
```

### About the token

- Use your **own personal** token, not a shared team one. Anecdotes records the
  token as the actor, so a shared token makes it impossible to tell who created
  or changed a risk. With no pull-request trail, the token is your only audit
  record.
- It must be an **API key** issued for programmatic access, not a session token
  copied from browser developer tools. Those will not exchange.
- API keys expire. `HTTP 401: Api key invalid` on a clean single paste means it
  is time to generate a new one in Anecdotes.
- Never commit it, and never put it in a tracked `.env` file.
- Avoid `~/.zshrc` — plaintext on disk. If re-entering it each session becomes
  tedious, prefer `direnv` with a gitignored `.envrc`, macOS Keychain, or your
  team's secret manager.

The `ANECDOTES` **GitHub secret** is a separate thing. It exists so the Actions
sync workflow can run unattended in CI. This CLI needs no repository secret.

### Optional overrides

All default to values baked into `risk_cli.py`:

| Variable | Purpose |
| --- | --- |
| `ANECDOTES_REGISTER_ID` | Target risk register |
| `ANECDOTES_API_BASE_URL` | API gateway |
| `ANECDOTES_AUTH_URL` | API-key to JWT exchange endpoint |
| `ANECDOTES_USER_AGENT` | User-Agent sent to Anecdotes |

## First run

Work through these in order. Each step builds confidence before anything can be
written to Anecdotes.

### Step 5 — Dry-run an update first

```bash
python3 cli/risk_cli.py update --dry-run
```

Start with `update`, not `create`. It is read-only, and it exercises the most
moving parts in one go: authentication, risk listing, custom-field lookup, and
decoding stored option IDs back into readable values. If something is
misconfigured, this is where you find out, with zero risk.

You should see `DRY RUN - NO CHANGES WILL BE MADE` first.

Then:

1. **Search** — type part of a risk name, or press Enter to list everything.
2. **Select risk (number)** — type a number. Nothing is auto-selected, even when
   only one risk matches.
3. **Field prompts** — there are 15 values including Risk name. Press Enter on
  existing values to keep them unchanged. To see a diff, change exactly one.
4. The CLI prints the OLD -> NEW diff, the exact PATCH payload it *would* send,
   and `DRY RUN - NO CHANGES WERE MADE`.

No confirmation is requested in dry-run, because there is nothing to confirm.

To leave at any point press **Ctrl+C**. It exits cleanly with
`Cancelled. Nothing was changed in Anecdotes.`

Checks worth making: the current values match what the Anecdotes UI shows, and
pressing Enter through every field reports
`No changes detected. Nothing to update.`

### Step 6 — Dry-run a create

```bash
python3 cli/risk_cli.py create --dry-run
```

Confirm the resolved custom-field IDs and option IDs look like real Anecdotes
identifiers, and that the printed payload is complete.

### Step 7 — First live create

```bash
python3 cli/risk_cli.py create
```

Use an obvious throwaway name such as `ZZZ TEST - delete me`. This CLI has **no
delete** by design, so remove the test risk through the Anecdotes UI afterwards.

You will be asked `Create this risk in Anecdotes? [y/N]`. Only `y` or `yes`
proceeds; anything else, including pressing Enter, aborts without writing.

### Step 8 — First live update

```bash
python3 cli/risk_cli.py update
```

Edit the test risk you just created, check the diff, and confirm.

### Troubleshooting

| Symptom | Cause |
| --- | --- |
| `JWT exchange failed: HTTP 401: Api key invalid` | Wrong, doubled, or expired token. Repeat steps 3–4. |
| `Could not list risks from Anecdotes` | The risk-listing endpoint differs from the one assumed in `list_risks`. |
| `NotOpenSSLWarning ... LibreSSL` | Harmless macOS system-Python warning. Ignore it. |
| `ANECDOTES is not set` | New terminal tab. Repeat step 3. |

## Usage

Once set up, day to day:

```bash
python3 cli/risk_cli.py create --dry-run
python3 cli/risk_cli.py update --dry-run

python3 cli/risk_cli.py create
python3 cli/risk_cli.py update
```

`create` walks you through Risk name and 14 custom fields, shows a preview, and
asks for confirmation. Anecdotes generates the Risk ID; the CLI never invents
one.

`update` lists risks from Anecdotes, requires you to explicitly select one,
shows its current values, lets you edit any field, prints an OLD -> NEW diff, and
patches only the fields that actually changed. It reads the selected risk's name
from `/risk/v1/risk/{id}` and its saved custom-field values from
`/risk/v1/risk/fields`; the detail endpoint alone may return only a subset of
the fields shown in the Anecdotes UI. If either read is incomplete, update stops.

Dropdown options are fetched live from Anecdotes. In addition to UKI Brand and
Domain, the wizard includes:

- **CIA:** Availability, Confidentiality, and Integrity; all three start
  selected, and you can choose a subset.
- **Impacted asset contains PII?:** choose from the live No/Unknown/Yes options.
- **Tribe:** set to Gaming on create; updates only offer Gaming.
- **Ratings:** Operational impact, Reputational impact (UKI), Regulatory and
  legal impact (UKI), Financial impact (UKI), Target impact, and Target
  likelihood. Each is a single live dropdown selection with choices displayed
  in numeric order from 1 to 5; example placeholder text is omitted. Inherent
  likelihood is automated by Anecdotes and is intentionally omitted.

The operational-impact field is `Operational impact (Tech, Process, People)`.
Matching is case- and whitespace-insensitive, and you never need to know the
`CYB`/`TR` option codes. If a field cannot be matched uniquely in live metadata,
the CLI stops before any write.

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

71 tests, no network calls, no credentials needed. They run automatically in CI
via the `Validate risks` workflow.

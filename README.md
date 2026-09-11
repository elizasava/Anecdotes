# GitHub to Anecdotes Risk Workflow

This repository runs a file-based risk workflow where each risk is stored as YAML, validated in PRs, and synced to Anecdotes after merge.

## What Is In This Repo

- Workflows:
  - .github/workflows/validate-risks.yml
  - .github/workflows/sync-risks.yml
- Risk source files:
  - risks/active/*.yaml
- Machine-managed risk ID map:
  - system/anecdotes-risk-map.yaml
- Scripts:
  - scripts/create_risk.py
  - scripts/validate_risks.py
  - scripts/sync_risks.py
  - scripts/protect_mapping.py
  - scripts/github_pending.py
  - scripts/anecdotes_client.py

## How It Works

### 1. Authoring

- A new risk YAML is created in risks/active.
- scripts/create_risk.py can generate the next key format (RISK-###) and scaffold valid fields.

### 2. Pull Request Validation

On PRs to main, validate-risks.yml runs:

- schema/content validation for all risk files
- duplicate risk_key detection
- deletion blocking for risks/active files
- machine-map protection for system/anecdotes-risk-map.yaml
- unit tests

No Anecdotes write operations happen in this PR stage.

### 3. Post-Merge Sync

On push to main with risk YAML changes, sync-risks.yml runs:

- determines changed risk files
- resolves custom fields from Anecdotes metadata
- for each changed risk:
  - update if risk_key already exists in system/anecdotes-risk-map.yaml
  - create if risk_key is not yet mapped
- writes/updates machine mapping data in system/anecdotes-risk-map.yaml
- opens or updates an automated mapping PR using create-pull-request

Concurrency is serialized so only one sync job runs at a time.

### 4. Dry Run Mode

sync-risks.yml also supports manual workflow_dispatch dry runs:

- no create/update writes are sent to Anecdotes
- optional connection check is performed
- logs what would be CREATE vs UPDATE
- does not open a mapping PR

## Mapping PR Behavior

- Mapping updates are proposed from automation/anecdotes-map.
- Only system/anecdotes-risk-map.yaml is included in that automated PR.
- Mapping edits are accepted only for the configured automation bot/branch pattern.

## Idempotency and Safety Controls

- risk_key is the stable identity for synchronization.
- Duplicate CREATE protection checks pending mapping state before create.
- Risk deletions from GitHub are blocked by validation policy.
- Mapping file is machine-managed and guarded in PR validation.

## Typical Lifecycle

1. Add or edit a risk YAML in risks/active.
2. Open PR and pass validate-risks workflow.
3. Merge to main.
4. Sync workflow writes to Anecdotes (or dry-run if manually triggered).
5. Automated mapping PR updates system/anecdotes-risk-map.yaml.

# Career Quest data foundation

This package contains the first implementation step: the local data store and a
validated importer for the Career Quest starter kit.

It deliberately uses only Python's standard library and SQLite while the API is
not yet implemented. The schema is portable to PostgreSQL; the next step can
replace the connection layer without changing the import contract.

## Import the starter kit

```bash
python3 -m backend.app.importer full \
  --dataset-dir /absolute/path/to/career_quest_dataset \
  --database ./var/career_quest.db
```

The command creates the database and applies migrations automatically. It
validates the full package before writing anything. Repeating an identical
import is safe; changes to an existing record are rejected instead of being
silently overwritten.

## Import jury profiles

After the catalog has been loaded, import a package containing an
`employees.json` file and an `activity_history.csv` file:

```bash
python3 -m backend.app.importer profiles \
  --employees /absolute/path/to/employees.json \
  --history /absolute/path/to/activity_history.csv \
  --database ./var/career_quest.db
```

New profiles and history records are inserted atomically. References to an
unknown employee, event or skill stop the import and leave the database
unchanged.

## Run validation tests

```bash
python3 -m unittest discover -s backend/tests -v
```

## Calculate a career trajectory

After importing the starter kit, calculate the factual basis for a
recommendation. The output contains the effective skills, a trace of skill
updates after the last review, target requirements, critical skills, gaps and
coverage percentage.

```bash
python3 -m backend.app.career \
  --database ./var/career_quest.db \
  --employee-id E0001
```

For a profile with `career_goal`, its target role and grade are used. When the
goal is absent, the next grade in the current role is used. A Lead without a
goal receives `goal_required` instead of a fictional promotion target.

## Get development recommendations

The recommendation command filters out mandatory, unavailable, already
completed/current and prerequisite-blocked events before ranking only actions
that reduce the employee's target gaps. `EV_036`, the regular club specified in
the starter kit, is the documented exception and may repeat after completion.
It takes critical requirements,
expected skill growth, duration and comparable participation history into
account.

```bash
python3 -m backend.app.recommendations \
  --database ./var/career_quest.db \
  --employee-id E0001
```

Without model credentials it returns an explicitly labelled `rules_fallback`.
For an OpenAI-compatible endpoint, set all three variables before the command:

```bash
export LLM_API_URL="https://provider.example/v1/chat/completions"
export LLM_API_KEY="..."
export LLM_MODEL="..."
```

The model can select only verified event IDs; it cannot change skills, bypass
audience or prerequisites, or invent an event. Invalid or slow model replies
fall back to the rules-based result.

## Create and verify demo accounts

Import the starter kit first, then create the predefined demo accounts:

```bash
python3 -m backend.app.demo_seed --database ./var/career_quest.db
```

| Login | Password | Access role | Employee profile | Demo focus |
|---|---|---|---|---|
| `junior@careerquest.demo` | `DemoEmployee2026!` | employee | E0001, Junior | First path to Middle |
| `middle@careerquest.demo` | `DemoEmployee2026!` | employee | E0002, Middle | Critical gap and participation history |
| `senior@careerquest.demo` | `DemoEmployee2026!` | employee | E0007, Senior | Path to Lead |
| `lead@careerquest.demo` | `DemoEmployee2026!` | employee | E0014, Lead | Cross-role Lead goal |
| `hr@careerquest.demo` | `DemoHR2026!` | hr | — | HR dashboard and imports |

The command is idempotent: it only creates missing accounts. If a documented
username already belongs to a different account or password, it fails instead
of changing that account. Passwords are stored as salted PBKDF2-SHA256 hashes.

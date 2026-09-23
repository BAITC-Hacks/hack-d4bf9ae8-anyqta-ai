# Career Quest data foundation

This package contains the application data store, calculations, web cabinet and
validated importer for the Career Quest starter kit.

The current local demo uses SQLite and only Python's standard library.

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

## Run the employee web cabinet

After importing the starter kit and creating demo accounts, start the local
web server:

```bash
python3 -m backend.app.web --database ./var/career_quest.db
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) and sign in using an
employee demo account. The session is an HttpOnly, signed cookie. Set a stable
secret of at least 32 characters before deploying beyond a local demo:

```bash
export SESSION_SECRET="replace-with-a-long-random-secret"
```

Without `SESSION_SECRET`, the server generates an in-memory secret for the
current local run; active sessions expire when the server restarts. HR can sign
in now; its analytics and import interface are added in stage 7.

## Employee profile, history and career goal

The employee cabinet shows the current role and grade, department, tenure,
work format and last assessment date. The complete skill table includes all
60 catalog skills, assessed/current levels, target requirements and critical
gaps. Search by skill name/category or show only target skills and gaps.

The full activity history is searchable and filterable by all six statuses.
It includes participation dates, deadlines, completion percentage, scores,
feedback and the calculated skill changes for each completion. Earlier
completions are marked as included in the last assessment. Dataset participation
dates are not presented as exact completion dates; app completions show their
separately recorded completion date. HR can inspect the same skills and history.

Employees can choose a target role/grade from the catalog under **«Изменить
цель»**, including a cross-role goal. Saving refreshes requirements, coverage
and recommendations. Clearing the goal restores the default next grade;
a Lead without a goal keeps the full profile/history and can select a new goal.
Goal changes persist across restarts and import retries. HR views are read-only
for goals, and the employee API always updates the signed-in employee only.

## Activity lifecycle in the demo

In the employee cabinet, use **«Начать активность»** on a recommendation. It
creates one `in_progress` history record and moves the activity to **«В
процессе»**. In the local demo, `DEMO_MODE=true` by default and exposes
**«Завершить в демо»**. Completion is transactional: it changes that same
record to `completed`, saves `completed_at`, recalculates skills and refreshes
recommendations. A repeated completion request cannot add a second skill gain.

Set `DEMO_MODE=false` to hide the completion simulation. A real LMS integration
is intentionally outside the MVP.

Each employee demo account also has **«Сбросить демо»**. It is available only
to that account while `DEMO_MODE=true`, removes activity records created
through the application for that employee and restores their original career
goal. The original starter-kit history,
other demo accounts and HR-imported profiles are preserved.

## HR overview and jury-data upload

Sign in as `hr@careerquest.demo` after starting the web server. The HR screen
contains:

- a private aggregate of skill gaps, filterable by department, role and grade;
- explainable support signals based on voluntary activity participation during
  the displayed six-month period;
- a count and filter for employees without a next step, with reasons such as a
  missing goal, unmet prerequisites, completed/current activities, no upcoming
  session or no suitable catalog activity;
- participation by activity: all six statuses, participation records, unique
  employees and the percentage of completed records, with mandatory activities
  labelled separately;
- an employee detail view with trajectory and currently available steps;
- an upload form for `employees.json` and `activity_history.csv` in the
  starter-kit schema.

The upload is validated as one atomic package. If it contains unknown IDs,
invalid dates, duplicate records or another schema error, nothing is written to
the database. A successful upload immediately appears in the HR filters and
can be opened in the detail view without creating an employee login.

HR employee details, including newly imported jury profiles, use the same
`LLM_API_URL`, `LLM_API_KEY` and `LLM_MODEL` configuration as the employee cabinet.
Recommendation cards show the AI/rules mode, activity format and schedule, and
the skill and participation evidence behind each step. If the model is absent,
unavailable or returns an invalid selection, verified rules-based recommendations
remain available. The aggregate HR overview does not call the model.

Department, role, grade and next-step filters apply to the entire overview,
including skill gaps, support signals and activity participation. Next-step
availability uses the recommendation engine's eligibility checks; a covered
target is distinguished from a missing goal or an unavailable activity. When
an activity has several blockers, the overview reports its first blocking rule.

Participation uses the inclusive interval from six calendar months before the
displayed snapshot date through that date. Repeat participation counts as
separate records; unique employees are counted once per activity. Completion
percentage is completed records divided by all records in that interval and
cohort, including unfinished records. Activities with no records remain visible
with zero counts and no percentage. These are participation measures, not
employee performance scores.

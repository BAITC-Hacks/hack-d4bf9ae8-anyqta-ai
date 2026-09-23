# Career Quest repository guidance

## Product boundaries

- The product serves two roles: `employee` can access only the profile bound to
  their account; `hr` can access HR analytics and profile imports. Enforce this
  in server code, not only by hiding UI controls.
- Skill levels and career coverage are deterministic calculations. The LLM may
  select only from server-validated event IDs and must never set levels, bypass
  prerequisites or invent activities.
- Treat participation signals as prompts for support, never as a public ranking,
  performance score or attrition prediction.
- `DEMO_MODE=true` enables completion simulation and personal reset only for
  seeded demo employees. A reset removes only records created through the app.

## Data and persistence

- `data/career_quest_dataset/` is the canonical synthetic starter kit bundled
  for jury startup. Preserve its schema and do not replace it with real data.
- Add schema changes as ordered files in `backend/migrations/`; migrations must
  remain safe for an existing local SQLite database.
- Keep imports atomic. Invalid jury JSON/CSV must not partially change the DB.
- Preserve completed source history. App-created records must remain traceable
  so demo reset can remove only those records.

## Running and validating

- Use `python3 -m unittest discover -s backend/tests -v` after backend changes.
- Run `python3 scripts/acceptance.py` after changes to the demo journey,
  authentication, bootstrap or HR operations.
- Use `docker compose up --build -d` for jury startup when Docker is available.
- Keep secrets only in `.env`; never commit, print or copy API keys.

For task-specific decisions, use [the repository Career Quest skill](skills/career-quest/SKILL.md).

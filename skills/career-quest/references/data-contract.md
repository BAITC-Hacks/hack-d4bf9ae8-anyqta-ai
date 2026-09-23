# Career Quest data and workflow contract

## Canonical data

The bundled starter kit is `data/career_quest_dataset/`:

- `employees.json`: profiles, baseline skills, current role/grade, optional goal
  and `last_review_date`.
- `skills.json`: skill catalog and role/grade requirements, including critical
  skills.
- `events.json`: audience, format, prerequisites, voluntary/mandatory flag and
  skill development rules.
- `activity_history.csv`: participation status and historic outcomes.

Missing skills mean level 0. The demo reference date is `2026-10-01`.
Completed events after `last_review_date` affect the effective skill level;
activities on or before it are already represented by the assessment.

## Recommendation invariant

An eligible recommendation is voluntary, matches the employee's current target
audience, satisfies prerequisites, is available at the reference date, is not
currently in progress, and reduces at least one target gap. A completed event
cannot repeat except `EV_036`, the regular club.

Ranking can consider critical gap reduction, total gap reduction, duration and
comparable participation history. Explain using factual evidence supplied by
the server. Repeated non-completion should inform format selection; it must not
be presented as a judgement about motivation.

## Demo and roles

The five seed accounts are created by `backend.app.demo_seed`. The employee
accounts use E0001, E0002, E0007 and E0014; HR has no employee binding.

App-created participation is tracked in `app_activity_records`. During reset,
delete only these rows and their associated enrollments. Never delete starter
history or HR-uploaded profile data.

## Entry points

- `backend.app.bootstrap`: migrations, initial import and demo users.
- `backend.app.career`: deterministic trajectory calculation.
- `backend.app.recommendations`: candidate filtering, rules fallback and LLM
  selector validation.
- `backend.app.activities`: enrollment, demo completion and personal reset.
- `backend.app.hr`: HR aggregate, employee details and jury imports.
- `backend.app.web`: local HTTP API and static cabinet.

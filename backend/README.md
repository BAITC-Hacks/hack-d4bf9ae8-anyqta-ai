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

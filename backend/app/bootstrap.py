"""Initialize a persistent Career Quest database for local or Docker startup."""

from __future__ import annotations

import argparse
from pathlib import Path

from .db import connect, migrate
from .demo_seed import seed_demo_users
from .importer import import_package, load_full_package


def bootstrap(database_path: str | Path, dataset_dir: str | Path) -> bool:
    """Apply migrations, load the starter kit once and ensure five demo users.

    Returns True when the catalog was imported during this invocation. Existing
    databases are preserved, including progress and HR-imported jury profiles.
    """
    connection = connect(database_path)
    try:
        migrate(connection)
        catalog_exists = connection.execute("SELECT 1 FROM skills LIMIT 1").fetchone() is not None
        if not catalog_exists:
            package = load_full_package(dataset_dir)
            import_package(connection, package, "full", str(dataset_dir))
        seed_demo_users(connection)
        return not catalog_exists
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap Career Quest data")
    parser.add_argument("--database", required=True)
    parser.add_argument("--dataset-dir", required=True)
    args = parser.parse_args()
    imported = bootstrap(args.database, args.dataset_dir)
    print("Starter kit imported and demo users ready." if imported else "Existing data and demo users are ready.")


if __name__ == "__main__":
    main()

"""Export the live ZERO X-RAY SQLite database to easy-to-open CSV files."""
from __future__ import annotations
import csv
import sqlite3
from pathlib import Path

from core.data_paths import get_database_path, get_database_view_root


def main():
    packaged = Path(__file__).resolve().parent.parent / "data" / "runtime.db"
    db_path = get_database_path(packaged)
    out_dir = get_database_view_root()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()]
        summary = []
        for table in tables:
            rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
            columns = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
            csv_path = out_dir / f"{table}.csv"
            with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(columns)
                for row in rows:
                    writer.writerow([row[col] for col in columns])
            summary.append(f"{table}: {len(rows)} rows")

    (out_dir / "DATABASE_SUMMARY.txt").write_text(
        "ZERO X-RAY DATABASE VIEW\n"
        f"Live database: {db_path}\n"
        f"Export folder: {out_dir}\n\n" + "\n".join(summary) + "\n",
        encoding="utf-8",
    )
    print(f"Live database: {db_path}")
    print(f"CSV export created: {out_dir}")


if __name__ == "__main__":
    main()

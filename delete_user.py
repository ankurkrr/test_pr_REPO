import sys
from typing import List, Tuple


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/delete_user.py <USER_ID>")
        return 1

    user_id: str = sys.argv[1]

    try:
        from src.services.database_service_new import get_database_service
    except Exception as import_error:
        print(f"ERROR: Failed to import database service: {import_error}")
        return 1

    db = get_database_service()

    # Resolve current database/schema
    try:
        dbname_rows = db.execute_query("SELECT DATABASE()")
        dbname = dbname_rows[0][0] if dbname_rows and dbname_rows[0] else None
        if not dbname:
            print("ERROR: Could not determine current database name")
            return 1
    except Exception as e:
        print(f"ERROR: Failed to get database name: {e}")
        return 1

    # Find tables containing a user_id column
    try:
        rows = db.execute_query(
            f"SELECT TABLE_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='{dbname}' AND COLUMN_NAME='user_id'"
        )
        tables: List[str] = [r[0] for r in rows] if rows else []
    except Exception as e:
        print(f"ERROR: Failed to list tables with user_id column: {e}")
        return 1

    print(f"Tables with user_id column: {tables}")

    total_deleted = 0
    per_table: List[Tuple[str, int]] = []

    # Disable foreign key checks (best effort)
    try:
        db.execute_query("SET FOREIGN_KEY_CHECKS=0")
    except Exception as e:
        print(f"WARNING: Could not disable FOREIGN_KEY_CHECKS: {e}")

    for table_name in tables:
        try:
            # NOTE: Using direct string interpolation due to adapter param rules
            count_rows = db.execute_query(
                f"SELECT COUNT(*) FROM `{table_name}` WHERE user_id='{user_id}'"
            )
            count = int(count_rows[0][0]) if count_rows else 0

            db.execute_query(
                f"DELETE FROM `{table_name}` WHERE user_id='{user_id}'"
            )

            per_table.append((table_name, count))
            total_deleted += count
        except Exception as e:
            print(f"ERROR deleting from {table_name}: {e}")

    # Re-enable foreign key checks (best effort)
    try:
        db.execute_query("SET FOREIGN_KEY_CHECKS=1")
    except Exception as e:
        print(f"WARNING: Could not re-enable FOREIGN_KEY_CHECKS: {e}")

    print("Deletion summary:")
    for table_name, count in per_table:
        print(f"  {table_name}: {count} rows deleted")
    print(f"Total rows deleted for user_id {user_id}: {total_deleted}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())



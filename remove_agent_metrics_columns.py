"""
Migration Script: Remove Metric Columns from Agent Table

This script removes the following columns from the agent table:
- events_scanned
- transcripts_ingested
- summaries_generated
- tasks_extracted
- emails_sent
- platform_tasks_fetched
- integration_analysis_completed

Run this script to update the database schema after code changes.
"""

import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> int:
    """Remove metric columns from agent table"""
    
    try:
        from src.services.database_service_new import get_database_service
    except Exception as import_error:
        print(f"ERROR: Failed to import database service: {import_error}")
        return 1

    db = get_database_service()

    # Columns to remove
    columns_to_remove = [
        'events_scanned',
        'transcripts_ingested',
        'summaries_generated',
        'tasks_extracted',
        'emails_sent',
        'platform_tasks_fetched',
        'integration_analysis_completed'
    ]

    print("=" * 80)
    print("Agent Table Migration: Removing Metric Columns")
    print("=" * 80)
    print(f"\nColumns to remove: {', '.join(columns_to_remove)}")
    
    # Confirm before proceeding
    response = input("\nDo you want to proceed? This will permanently delete these columns. (yes/no): ")
    if response.lower() != 'yes':
        print("Migration cancelled.")
        return 0

    try:
        # Check current table structure
        print("\nChecking current table structure...")
        describe_query = "DESCRIBE agent"
        current_columns = db.execute_query(describe_query)
        
        existing_columns = [row[0] for row in current_columns] if current_columns else []
        print(f"Current columns in agent table: {', '.join(existing_columns)}")
        
        # Check which columns exist
        columns_to_drop = [col for col in columns_to_remove if col in existing_columns]
        columns_not_found = [col for col in columns_to_remove if col not in existing_columns]
        
        if columns_not_found:
            print(f"\n⚠️  Warning: These columns don't exist (may have been removed already):")
            for col in columns_not_found:
                print(f"   - {col}")
        
        if not columns_to_drop:
            print("\n✅ All metric columns have already been removed. No migration needed.")
            return 0
        
        print(f"\nColumns to drop: {', '.join(columns_to_drop)}")
        
        # Drop each column
        print("\nDropping columns...")
        for column in columns_to_drop:
            try:
                drop_query = f"ALTER TABLE agent DROP COLUMN `{column}`"
                print(f"   Dropping column: {column}...")
                db.execute_query(drop_query)
                print(f"   ✅ Successfully dropped column: {column}")
            except Exception as e:
                print(f"   ❌ Failed to drop column {column}: {e}")
                logger.error(f"Failed to drop column {column}: {e}")
                # Continue with other columns
        
        # Verify final structure
        print("\nVerifying final table structure...")
        final_columns = db.execute_query(describe_query)
        final_column_names = [row[0] for row in final_columns] if final_columns else []
        
        print(f"\n✅ Migration completed!")
        print(f"Final columns in agent table: {', '.join(final_column_names)}")
        
        # Check if any metric columns remain
        remaining_metrics = [col for col in columns_to_remove if col in final_column_names]
        if remaining_metrics:
            print(f"\n⚠️  Warning: These metric columns still exist: {', '.join(remaining_metrics)}")
            return 1
        else:
            print("\n✅ All metric columns successfully removed!")
            return 0
        
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        logger.error(f"Migration failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


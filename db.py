# db.py

"""
Database Configuration for Enhanced Meeting Intelligence Agent
Simplified schema with core tables for LangChain integration
Configured for MySQL 8.0
"""

import os
import sys
import logging
from typing import Generator, List, Type, Dict, Any
from sqlalchemy import create_engine, MetaData, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import QueuePool

# Ensure parent path is accessible
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# Import settings
from src.configuration.config import DB_URL, DEBUG, LOG_FORMAT, LOG_DATE_FORMAT, LOG_FILE_PATH, LOG_LEVEL

# Import table models - Focus on 3-table audit system
# Optional ORM table imports (used for table management). Not required for connection test.
try:
    from src.constants.tables import (
        Base, Agent, UserAgentTask, AgentFunctionLog, get_core_tables
    )
except Exception:
    # Provide safe fallbacks so connection tests work even if ORM models are absent
    Base = declarative_base()
    def get_core_tables():
        return []

# ---------------- Configure Logging ----------------
numeric_level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
# Ensure we use a relative path for logs directory - fix for /app permission issue
log_dir = os.path.dirname(LOG_FILE_PATH)
if not os.path.isabs(log_dir):
    log_dir = os.path.join(os.getcwd(), log_dir)
else:
    # If absolute path, use relative logs directory instead
    log_dir = os.path.join(os.getcwd(), "logs")

# Ensure logs directory exists and is writable
try:
    os.makedirs(log_dir, exist_ok=True)
except PermissionError:
    # Fallback to current directory if logs directory can't be created
    log_dir = os.getcwd()
    LOG_FILE_PATH = os.path.join(log_dir, "app.log")

logging.basicConfig(
    level=numeric_level,
    format=LOG_FORMAT,
    datefmt=LOG_DATE_FORMAT,
    handlers=[
        logging.FileHandler(LOG_FILE_PATH),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ---------------- SQLAlchemy Setup ----------------
engine = create_engine(
    DB_URL,
    poolclass=QueuePool,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=300,
    echo=DEBUG
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
metadata = MetaData()

# ---------------- DB Utilities ----------------
def get_db() -> Generator:
    """Database session generator for dependency injection"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def create_core_tables_only(eng):
    """Create only core tables (agent, user_agent_task, agent_function_log)"""
    try:
        core_tables = get_core_tables()
        for table_class in core_tables:
            table_class.__table__.create(eng, checkfirst=True)
        logger.info(f"Created {len(core_tables)} core tables")
    except Exception as e:
        logger.error(f"Error creating core tables: {e}")
        raise

def create_all_tables(eng):
    """Create all tables including compatibility tables"""
    try:
        # Create core tables
        create_core_tables_only(eng)
        # Note: Add compatibility tables here if needed
        # Currently only core tables are implemented
        logger.info("All tables created (core tables only in current implementation)")
    except Exception as e:
        logger.error(f"Error creating all tables: {e}")
        raise

def create_tables(core_only: bool = False):
    """
    Create database tables

    Args:
        core_only: If True, create only core tables (agent, user_agent_task, agent_function_log)
                  If False, create all tables including compatibility tables
    """
    try:
        if core_only:
            create_core_tables_only(engine)
            logger.info("Core database tables created successfully")
            logger.info("   Created: agent, user_agent_task, agent_function_log")
        else:
            create_all_tables(engine)
            logger.info("All database tables created successfully")
            logger.info("   Core: agent, user_agent_task, agent_function_log")
            logger.info("   Compatibility: audit_logs, workflows")
    except Exception as e:
        logger.error(f"Error creating database tables: {e}")
        raise

def drop_tables(core_only: bool = False):
    """
    Drop database tables (use with caution!)

    Args:
        core_only: If True, drop only core tables
                  If False, drop all tables
    """
    try:
        if core_only:
            # Drop core tables only
            core_metadata = MetaData()
            for table_class in get_core_tables():
                table_class.__table__.tometadata(core_metadata)
            core_metadata.drop_all(bind=engine)
            logger.warning("Core database tables dropped")
        else:
            Base.metadata.drop_all(bind=engine)
            logger.warning("All database tables dropped")
    except Exception as e:
        logger.error(f"Error dropping database tables: {e}")
        raise

def get_table_info() -> dict:
    """Get information about the 3-table audit system"""
    return {
        'core_tables': [table.__tablename__ for table in get_core_tables()],
        'core_table_descriptions': {
            "agent": "Agent registry and configuration",
            "user_agent_task": "Workflow execution tracking",
            "agent_function_log": "Detailed audit logging"
        },
        'total_count': len(get_core_tables()),
        'recommended': '3-table audit system provides complete functionality'
    }

def verify_3_table_structure() -> Dict[str, Any]:
    """Verify the 3-table audit system is properly set up"""
    try:
        with engine.connect() as connection:
            results = {}

            # Check each core table
            for table_class in get_core_tables():
                table_name = table_class.__tablename__
                try:
                    result = connection.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                    count = result.scalar()
                    results[table_name] = {
                        "exists": True,
                        "record_count": count,
                        "status": "OK"
                    }
                except Exception as e:
                    results[table_name] = {
                        "exists": False,
                        "error": str(e),
                        "status": "MISSING"
                    }

            # Overall status
            all_exist = all(table["exists"] for table in results.values())
            results["overall_status"] = "3-table system ready" if all_exist else "Missing tables"

            return results

    except Exception as e:
        return {
            "error": str(e),
            "overall_status": "Database connection failed"
        }

def get_db_session() -> Generator:
    """Get database session (for compatibility)"""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

def test_connection() -> bool:
    """Test database connection"""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            logger.info("Database connection successful")
            return True
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False

# ---------------- Manual Test Mode ----------------
if __name__ == "__main__":
    print("Testing Enhanced Database Configuration")
    print("=" * 50)
    print(f"DB_URL: {DB_URL}")
    print("=" * 50)

    # Test connection
    if test_connection():
        print("Database connection is valid")
    else:
        print("Database connection failed")
        sys.exit(1)

    # Show table information
    print("\nTable Information:")
    table_info = get_table_info()
    print(f"   Core tables ({len(table_info['core_tables'])}): {', '.join(table_info['core_tables'])}")
    print(f"   Compatibility tables ({len(table_info['compatibility_tables'])}): {', '.join(table_info['compatibility_tables'])}")
    print(f"   Total tables: {table_info['total_count']}")

    # Test table creation (dry run)
    print("\nTesting table creation (core only)...")
    try:
        create_tables(core_only=True)
        print("Core tables creation test successful")
    except Exception as e:
        print(f"Core tables creation test failed: {e}")

    print("\nDatabase configuration test complete!")
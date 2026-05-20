from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from utils.config import config as mto_config
from utils.secrets_manager import secrets

SQLALCHEMY_DATABASE_URL = f"mysql+pymysql://{mto_config.DB_USER}:{secrets.db_password}@{mto_config.DB_HOST}:{mto_config.DB_PORT}/{mto_config.DB_NAME}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_size=20,
    max_overflow=5,
    pool_recycle=1800,
    pool_pre_ping=True
)

from sqlalchemy import event
from utils.logger import mto_logger

@event.listens_for(engine, "connect")
def connect(dbapi_connection, connection_record):
    mto_logger.info("New DB Connection established", pool_size=engine.pool.size(), checked_out=engine.pool.checkedout())

@event.listens_for(engine, "checkout")
def checkout(dbapi_connection, connection_record, connection_proxy):
    checked_out = engine.pool.checkedout()
    if checked_out > 15:
        mto_logger.warning("High DB Pool Usage detected", checked_out=checked_out, pool_size=engine.pool.size())


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def wait_for_db(max_attempts: int = 10, base_delay: float = 2.0) -> bool:
    """
    Waits for the database to become available using exponential backoff.

    Called once before the uvicorn server starts. This handles the common
    race condition on Windows where XAMPP/MariaDB takes 5–15 seconds to
    initialize after boot, causing the backend to crash if it starts first.

    Returns True when the DB is ready, raises SystemExit after max_attempts.

    Backoff schedule (base_delay=2.0, max_attempts=10):
      Attempt 1: wait 2s   (total waited:  2s)
      Attempt 2: wait 4s   (total waited:  6s)
      Attempt 3: wait 8s   (total waited: 14s)
      Attempt 4: wait 16s  (total waited: 30s)
      Attempt 5+: wait 30s (capped)
    """
    import time

    MAX_DELAY = 30.0

    for attempt in range(1, max_attempts + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            mto_logger.info(
                f"Database connection established on attempt {attempt}."
            )
            return True
        except Exception as e:
            delay = min(base_delay * (2 ** (attempt - 1)), MAX_DELAY)
            if attempt < max_attempts:
                mto_logger.warning(
                    f"Database not ready (attempt {attempt}/{max_attempts}): {e}. "
                    f"Retrying in {delay:.0f}s..."
                )
                print(
                    f"[MTO] Waiting for database... attempt {attempt}/{max_attempts} "
                    f"(retry in {delay:.0f}s)"
                )
                time.sleep(delay)
            else:
                mto_logger.error(
                    f"Database unavailable after {max_attempts} attempts. "
                    "Check that MariaDB/MySQL is running and credentials in .env are correct."
                )
                print(
                    f"\n[MTO] FATAL: Could not connect to the database after "
                    f"{max_attempts} attempts.\n"
                    "Please check:\n"
                    "  1. XAMPP MySQL is running\n"
                    "  2. MTO_DB_USER, MTO_DB_PASSWORD, MTO_DB_NAME in .env are correct\n"
                    f"  3. Database host is reachable at "
                    f"{mto_config.DB_HOST}:{mto_config.DB_PORT}\n"
                )
                raise SystemExit(1)

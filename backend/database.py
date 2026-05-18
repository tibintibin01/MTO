from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from utils.config import config as mto_config
from utils.secrets_manager import secrets

# Database Configuration from utils
user = mto_config.DB_HOST
password = secrets.db_password
host = mto_config.DB_HOST
port = mto_config.DB_PORT
database = mto_config.DB_NAME

# Re-constructing URI (consistent with db_manager.py)
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

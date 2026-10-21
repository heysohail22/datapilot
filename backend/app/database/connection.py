from sqlalchemy import create_engine, text
from app.config import Settings


def create_database_engine(settings: Settings):
    return create_engine(
        settings.DATABASE_URL.get_secret_value(),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_timeout=5,
        pool_recycle=1800,
        connect_args={"connect_timeout": 5},
        hide_parameters=True,
    )


def probe(engine) -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False

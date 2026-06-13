from app.db.database import Base, engine
from app.models import refresh_token, user


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    print("Database tables initialized successfully.")


if __name__ == "__main__":
    init_db()

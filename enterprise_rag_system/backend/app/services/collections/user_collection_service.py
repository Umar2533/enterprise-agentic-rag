import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.user_collection import UserCollection


def sanitize_collection_slug(collection_name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", collection_name.strip().lower()).strip("_")
    return slug or "collection"


def physical_collection_name(user_id: int, display_name: str) -> str:
    return f"user_{user_id}_{sanitize_collection_slug(display_name)}"


def create_user_collection(
    db: Session,
    user_id: int,
    collection_name: str,
    display_name: str | None = None,
    session_id: str | None = None,
    filename: str | None = None,
    embedding_provider: str | None = None,
    source: str = "upload",
) -> UserCollection:
    existing = get_user_collection_by_name(db, user_id, collection_name)
    if existing is not None:
        existing.session_id = session_id or existing.session_id
        existing.filename = filename or existing.filename
        existing.embedding_provider = embedding_provider or existing.embedding_provider
        existing.source = source or existing.source
        existing.display_name = display_name or existing.display_name or collection_name
        existing.is_active = True
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing

    user_collection = UserCollection(
        user_id=user_id,
        collection_name=collection_name,
        display_name=display_name or collection_name,
        session_id=session_id,
        filename=filename,
        embedding_provider=embedding_provider,
        source=source,
        is_active=True,
    )
    db.add(user_collection)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = get_user_collection_by_name(db, user_id, collection_name)
        if existing is None:
            raise
        return existing

    db.refresh(user_collection)
    return user_collection


def get_user_collections(db: Session, user_id: int) -> list[UserCollection]:
    stmt = (
        select(UserCollection)
        .where(
            UserCollection.user_id == user_id,
            UserCollection.is_active.is_(True),
        )
        .order_by(UserCollection.created_at.desc(), UserCollection.id.desc())
    )
    return list(db.execute(stmt).scalars().all())


def get_all_active_user_collections(db: Session) -> list[UserCollection]:
    stmt = (
        select(UserCollection)
        .where(UserCollection.is_active.is_(True))
        .order_by(UserCollection.created_at.desc(), UserCollection.id.desc())
    )
    return list(db.execute(stmt).scalars().all())


def get_user_collection_by_name(
    db: Session,
    user_id: int,
    collection_name: str,
) -> UserCollection | None:
    stmt = select(UserCollection).where(
        UserCollection.user_id == user_id,
        UserCollection.collection_name == collection_name,
    )
    return db.execute(stmt).scalar_one_or_none()


def get_user_collection_by_display_name(
    db: Session,
    user_id: int,
    display_name: str,
) -> UserCollection | None:
    normalized = display_name.strip().lower()
    stmt = select(UserCollection).where(
        UserCollection.user_id == user_id,
        UserCollection.is_active.is_(True),
    )
    for user_collection in db.execute(stmt).scalars().all():
        effective_name = user_collection.display_name or user_collection.collection_name
        if effective_name.strip().lower() == normalized:
            return user_collection
    return None


def user_owns_session(db: Session, user_id: int, session_id: str) -> bool:
    stmt = select(UserCollection.id).where(
        UserCollection.user_id == user_id,
        UserCollection.session_id == session_id,
        UserCollection.is_active.is_(True),
    )
    return db.execute(stmt).first() is not None


def get_user_collection_by_session(
    db: Session,
    session_id: str,
    user_id: int | None = None,
) -> UserCollection | None:
    stmt = select(UserCollection).where(
        UserCollection.session_id == session_id,
        UserCollection.is_active.is_(True),
    )
    if user_id is not None:
        stmt = stmt.where(UserCollection.user_id == user_id)
    return db.execute(stmt).scalars().first()


def update_user_collection_session(
    db: Session,
    user_collection_id: int,
    session_id: str,
) -> UserCollection | None:
    user_collection = db.get(UserCollection, user_collection_id)
    if user_collection is None:
        return None

    user_collection.session_id = session_id
    user_collection.is_active = True
    db.add(user_collection)
    db.commit()
    db.refresh(user_collection)
    return user_collection


def deactivate_user_collection(
    db: Session,
    user_collection_id: int,
) -> UserCollection | None:
    user_collection = db.get(UserCollection, user_collection_id)
    if user_collection is None:
        return None

    user_collection.is_active = False
    db.add(user_collection)
    db.commit()
    db.refresh(user_collection)
    return user_collection

"""Async SQLite persistence via SQLAlchemy 2.0.

Data survives restarts because everything lives in a single SQLite file
(``DATA_DIR/bot.db``), mounted as a volume in Docker.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (Boolean, DateTime, ForeignKey, Integer, String, select, update)
from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker, create_async_engine)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from . import config


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # Telegram user id
    language: Mapped[str] = mapped_column(String(8), default=config.DEFAULT_LANGUAGE)
    last_lang: Mapped[str] = mapped_column(String(8), default=config.DEFAULT_LANGUAGE)
    timezone: Mapped[str] = mapped_column(String(64), default=config.DEFAULT_TIMEZONE)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    text: Mapped[str] = mapped_column(String(512))
    remind_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    # none | daily | weekly | monthly
    recurrence: Mapped[str] = mapped_column(String(16), default="none")
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | done
    last_notified: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


engine = create_async_engine(f"sqlite+aiosqlite:///{config.DB_PATH}", future=True)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_user(session: AsyncSession, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        user = User(id=user_id)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user


def effective_language(user: User) -> str:
    """Language used for replies/UI: explicit choice, else last detected one."""
    if user.language != "auto":
        return user.language
    return user.last_lang or config.DEFAULT_LANGUAGE


async def list_active_reminders(session: AsyncSession, user_id: int) -> list[Reminder]:
    rows = await session.execute(
        select(Reminder)
        .where(Reminder.user_id == user_id, Reminder.status == "active")
        .order_by(Reminder.remind_at.asc())
    )
    return list(rows.scalars().all())


async def list_due_reminders(session: AsyncSession, now: datetime) -> list[Reminder]:
    """Active reminders whose time has come (used by the scheduler)."""
    rows = await session.execute(
        select(Reminder).where(
            Reminder.status == "active", Reminder.remind_at <= now
        )
    )
    return list(rows.scalars().all())


async def mark_done(session: AsyncSession, reminder_id: int, when: datetime) -> None:
    await session.execute(
        update(Reminder)
        .where(Reminder.id == reminder_id)
        .values(status="done", last_notified=when)
    )
    await session.commit()


async def count_stats(session: AsyncSession, user_id: int) -> dict[str, int]:
    from sqlalchemy import func

    total = await session.scalar(
        select(func.count()).select_from(Reminder).where(Reminder.user_id == user_id)
    )
    active = await session.scalar(
        select(func.count())
        .select_from(Reminder)
        .where(Reminder.user_id == user_id, Reminder.status == "active")
    )
    done = await session.scalar(
        select(func.count())
        .select_from(Reminder)
        .where(Reminder.user_id == user_id, Reminder.status == "done")
    )
    return {"total": total or 0, "active": active or 0, "done": done or 0}
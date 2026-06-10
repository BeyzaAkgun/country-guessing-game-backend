# app/models/daily.py
# New file — DailyResult model.
# Import this in app/models/__init__.py so Alembic picks it up.

import uuid
from datetime import datetime, date
from sqlalchemy import Integer, Date, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base


class DailyResult(Base):
    """One row per user per day — enforced by unique constraint."""
    __tablename__ = "daily_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_time_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    user: Mapped["User"] = relationship("User", lazy="select")  # type: ignore[name-defined]

    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_daily_results_user_date"),
    )
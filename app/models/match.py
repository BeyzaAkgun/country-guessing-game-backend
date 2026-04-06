#models/match.py
import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Integer, Float, Boolean, Enum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base


def utcnow():
    return datetime.now(timezone.utc)


class MatchMode(str, enum.Enum):
    RANKED_1V1 = "ranked_1v1"
    PARTY      = "party"
    CLASSROOM  = "classroom"


class MatchStatus(str, enum.Enum):
    WAITING     = "waiting"
    IN_PROGRESS = "in_progress"
    FINISHED    = "finished"
    CANCELLED   = "cancelled"


class QuestionMode(str, enum.Enum):
    CLASSIC = "classic"
    FLAG    = "flag"
    CAPITAL = "capital"
    HINT    = "hint"


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mode: Mapped[MatchMode] = mapped_column(Enum(MatchMode), default=MatchMode.RANKED_1V1, nullable=False)
    question_mode: Mapped[QuestionMode] = mapped_column(Enum(QuestionMode), default=QuestionMode.CLASSIC, nullable=False)
    status: Mapped[MatchStatus] = mapped_column(Enum(MatchStatus), default=MatchStatus.WAITING, nullable=False, index=True)
    room_code: Mapped[str | None] = mapped_column(String(6), nullable=True, index=True)
    winner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_rounds: Mapped[int] = mapped_column(Integer, default=10, nullable=False)

    players: Mapped[list["MatchPlayer"]] = relationship(back_populates="match", cascade="all, delete-orphan")
    questions: Mapped[list["MatchQuestion"]] = relationship(back_populates="match", cascade="all, delete-orphan")


class MatchPlayer(Base):
    __tablename__ = "match_players"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    match_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True)

    # One of these must be set — enforced in service layer
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    guest_session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("guest_sessions.id", ondelete="CASCADE"), nullable=True, index=True)

    score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    correct_answers: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    wrong_answers: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    best_streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_response_time_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    xp_earned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rank_points_delta: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    team_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    disconnected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    match: Mapped["Match"] = relationship(back_populates="players")
    user: Mapped["User"] = relationship("User", back_populates="match_players")

    @property
    def accuracy(self) -> float:
        total = self.correct_answers + self.wrong_answers
        if total == 0:
            return 0.0
        return round(self.correct_answers / total * 100, 1)


class MatchQuestion(Base):
    __tablename__ = "match_questions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    match_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    country_name: Mapped[str] = mapped_column(String(100), nullable=False)
    question_mode: Mapped[QuestionMode] = mapped_column(Enum(QuestionMode), nullable=False)
    asked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    match: Mapped["Match"] = relationship(back_populates="questions")


class GuestSession(Base):
    __tablename__ = "guest_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nickname: Mapped[str] = mapped_column(String(32), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
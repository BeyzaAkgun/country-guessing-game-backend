#step2

from pydantic import BaseModel, ConfigDict
from uuid import UUID
from datetime import datetime
from app.models.match import MatchMode, MatchStatus, QuestionMode


class MatchPlayerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID | None
    guest_session_id: UUID | None
    score: int
    correct_answers: int
    wrong_answers: int
    best_streak: int
    avg_response_time_ms: float
    xp_earned: int
    rank_points_delta: int
    accuracy: float


class MatchQuestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    round_number: int
    country_name: str
    question_mode: QuestionMode
    asked_at: datetime | None
    answered_at: datetime | None


class MatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mode: MatchMode
    question_mode: QuestionMode
    status: MatchStatus
    winner_id: UUID | None
    total_rounds: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    players: list[MatchPlayerResponse] = []


class MatchResultResponse(BaseModel):
    """Detailed post-match result screen."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mode: MatchMode
    question_mode: QuestionMode
    status: MatchStatus
    winner_id: UUID | None
    total_rounds: int
    started_at: datetime | None
    finished_at: datetime | None
    players: list[MatchPlayerResponse] = []
    questions: list[MatchQuestionResponse] = []
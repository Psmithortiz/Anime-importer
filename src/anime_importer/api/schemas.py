from typing import Literal

from pydantic import BaseModel, Field

from anime_importer.domain.models import (
    AiringStatus,
    ListStatus,
    MediaType,
    suggest_list_status,
)
from anime_importer.services.import_session import CandidateChoice, NormalizationChoice

SessionStatus = Literal["normalizing", "question", "finished", "failed"]


class CreateSessionRequest(BaseModel):
    text: str = Field(min_length=1)


class ChooseRequest(BaseModel):
    option: int = Field(ge=1)


class SelectionIn(BaseModel):
    option: int = Field(ge=1)
    status: ListStatus


class ChooseManyRequest(BaseModel):
    selections: list[SelectionIn] = Field(min_length=1)


class OptionOut(BaseModel):
    number: int
    label: str
    mal_id: int | None = None
    image_url: str | None = None
    media_type: MediaType | None = None
    year: int | None = None
    episodes: int | None = None
    airing_status: AiringStatus | None = None
    suggested_status: ListStatus | None = None


class QuestionOut(BaseModel):
    kind: Literal["normalization", "candidate"]
    original_title: str
    query: str | None = None
    options: list[OptionOut]


class ProgressOut(BaseModel):
    done: int
    total: int


class RejectedOut(BaseModel):
    title: str
    reason: str


class SummaryOut(BaseModel):
    imported: int
    by_status: dict[ListStatus, int]
    rejected: list[RejectedOut]


class SessionView(BaseModel):
    id: str
    status: SessionStatus
    progress: ProgressOut
    error: str | None = None
    question: QuestionOut | None = None
    summary: SummaryOut | None = None


def question_out(step: NormalizationChoice | CandidateChoice) -> QuestionOut:
    if isinstance(step, NormalizationChoice):
        return QuestionOut(
            kind="normalization",
            original_title=step.original_title,
            options=[
                OptionOut(number=number, label=label)
                for number, label in enumerate(step.options, start=1)
            ],
        )
    return QuestionOut(
        kind="candidate",
        original_title=step.original_title,
        query=step.query,
        options=[
            OptionOut(
                number=number,
                label=candidate.title,
                mal_id=candidate.mal_id,
                image_url=candidate.image_url,
                media_type=candidate.media_type,
                year=candidate.year,
                episodes=candidate.episodes,
                airing_status=candidate.airing_status,
                suggested_status=suggest_list_status(candidate.airing_status),
            )
            for number, candidate in enumerate(step.options, start=1)
        ],
    )

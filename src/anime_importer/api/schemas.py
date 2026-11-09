from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from anime_importer.config import KeySource
from anime_importer.domain.models import (
    AiringStatus,
    ListStatus,
    MediaType,
    RelationType,
    suggest_list_status,
)
from anime_importer.domain.session import CandidateChoice, NormalizationChoice

SessionStatus = Literal["preparing", "question", "finished", "failed"]


class AppInfo(BaseModel):
    # Marker so the desktop launcher can tell one of our instances from any other server.
    app: Literal["anime-importer"] = "anime-importer"
    demo: bool
    configured: bool = True
    sample_text: str | None = None


class CreateSessionRequest(BaseModel):
    text: str = Field(min_length=1)


class ChooseRequest(BaseModel):
    option: int = Field(ge=1)


class SelectionIn(BaseModel):
    mal_id: int = Field(ge=1)
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
    is_original: bool = False


class FranchiseOptionOut(BaseModel):
    mal_id: int
    label: str
    image_url: str | None = None
    media_type: MediaType | None = None
    year: int | None = None
    episodes: int | None = None
    airing_status: AiringStatus
    suggested_status: ListStatus
    relation: RelationType


class QuestionOut(BaseModel):
    kind: Literal["normalization", "candidate"]
    original_title: str
    query: str | None = None
    options: list[OptionOut]
    franchise: list[FranchiseOptionOut] = []
    franchise_truncated: bool = False
    preselected: list[int] = []
    used_fallback: bool = False


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
    normalization: ProgressOut | None = None
    resolution: ProgressOut | None = None
    error: str | None = None
    question: QuestionOut | None = None
    summary: SummaryOut | None = None
    can_undo: bool = False


class SessionSummaryOut(BaseModel):
    id: str
    created_at: datetime
    updated_at: datetime
    title_count: int
    preview: list[str]
    decision_count: int


def question_out(step: NormalizationChoice | CandidateChoice) -> QuestionOut:
    if isinstance(step, NormalizationChoice):
        return QuestionOut(
            kind="normalization",
            original_title=step.original_title,
            options=[
                OptionOut(number=number, label=label, is_original=number == step.original_option)
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
        franchise=[
            FranchiseOptionOut(
                mal_id=entry.candidate.mal_id,
                label=entry.candidate.title,
                image_url=entry.candidate.image_url,
                media_type=entry.candidate.media_type,
                year=entry.candidate.year,
                episodes=entry.candidate.episodes,
                airing_status=entry.candidate.airing_status,
                suggested_status=suggest_list_status(entry.candidate.airing_status),
                relation=entry.relation,
            )
            for entry in step.franchise.entries
        ],
        franchise_truncated=step.franchise.truncated,
        preselected=sorted(step.preselected),
        used_fallback=step.used_fallback,
    )


class KeyStatusOut(BaseModel):
    name: str
    source: KeySource
    masked: str | None = None


class ConfigView(BaseModel):
    demo: bool
    configured: bool
    restart_required: bool
    keys: list[KeyStatusOut]


KeyValue = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200, pattern=r"^\S+$")
]


class ConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gemini_api_key: KeyValue | None = None
    mal_client_id: KeyValue | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> Self:
        if self.gemini_api_key is None and self.mal_client_id is None:
            raise ValueError("Provide at least one key")
        return self

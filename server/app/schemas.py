from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from server.app.models import TransactionStatus


class TransactionCreate(BaseModel):
    title: str = Field(min_length=1)
    status: TransactionStatus = TransactionStatus.NEW
    next_action: str | None = None
    owner: str = "unassigned"
    suggested_follow_up_at: datetime | None = None
    notes: str | None = None


class TransactionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    status: TransactionStatus | None = None
    next_action: str | None = None
    owner: str | None = None
    suggested_follow_up_at: datetime | None = None
    notes: str | None = None


class Transaction(BaseModel):
    id: str
    title: str
    status: TransactionStatus
    next_action: str | None
    owner: str | None
    suggested_follow_up_at: datetime | None
    created_at: datetime
    updated_at: datetime
    notes: str | None

    model_config = ConfigDict(from_attributes=True)


class TransactionSummary(BaseModel):
    total: int
    by_status: dict[TransactionStatus, int]

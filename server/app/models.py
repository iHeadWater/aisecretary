from enum import StrEnum


class TransactionStatus(StrEnum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    WAITING_FEEDBACK = "waiting_feedback"
    DONE = "done"


from enum import StrEnum


class TransactionStatus(StrEnum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    WAITING_FEEDBACK = "waiting_feedback"
    DONE = "done"


class RelationType(StrEnum):
    """事务之间的关联类型。

    - PART_OF：A 是 B 的子任务（有向）
    - BLOCKS：A 阻塞 B，A 未完成时 B 推进不了（有向）
    - RELATED：弱相关（无向，只存一条边）
    """

    PART_OF = "part_of"
    BLOCKS = "blocks"
    RELATED = "related"


# 反向关系：查询时用于把「别人指向我」的边解释成我的语义
INVERSE_RELATION = {
    RelationType.PART_OF: "has_part",
    RelationType.BLOCKS: "blocked_by",
    RelationType.RELATED: "related",
}

SYMMETRIC_RELATIONS = {RelationType.RELATED}
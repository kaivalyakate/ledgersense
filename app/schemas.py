from pydantic import BaseModel
from typing import List, Optional


class AskIn(BaseModel):
    question: str
    entity_ids: Optional[List[str]] = None  # None = query spans all entities


class AskResult(BaseModel):
    question: str
    answer: str
    sql: str
    row_count: int
    follow_up_suggestions: List[str]
    model_provider: str
    model_name: str
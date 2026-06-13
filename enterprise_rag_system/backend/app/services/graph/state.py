from typing import List, Optional, TypedDict


class AgentState(TypedDict):
    question: str
    documents: List[str]
    answer: str
    iteration_count: int
    search_type: str
    evaluation: Optional[str]


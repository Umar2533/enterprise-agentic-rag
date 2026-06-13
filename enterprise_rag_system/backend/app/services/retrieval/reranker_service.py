from typing import List

from app.core.constants import FINAL_CONTEXT_DOCS, RERANK_CANDIDATES
from app.services.retrieval.hybrid_search import ScoredDocument


def rerank_documents(scored_documents: List[ScoredDocument]) -> List[ScoredDocument]:
    candidates = scored_documents[:RERANK_CANDIDATES]
    candidates.sort(
        key=lambda item: (
            item.final_score,
            item.metadata_score,
            item.keyword_score,
            item.dense_score,
        ),
        reverse=True,
    )
    return candidates[:FINAL_CONTEXT_DOCS]

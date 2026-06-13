import re
from collections import defaultdict
from dataclasses import dataclass
from typing import List, Optional, Sequence

from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document

from app.core.constants import BM25_WEIGHT, DENSE_WEIGHT


@dataclass
class ScoredDocument:
    document: Optional[Document] = None
    dense_score: float = 0.0
    bm25_score: float = 0.0
    metadata_score: float = 0.0
    keyword_score: float = 0.0
    final_score: float = 0.0
    retrieval_type: str = "dense"

    def as_source(self) -> dict:
        assert self.document is not None
        metadata = self.document.metadata or {}
        confidence = confidence_for_score(self.final_score)
        return {
            "page_content": self.document.page_content,
            "content": self.document.page_content,
            "score": round(self.final_score, 4),
            "retrieval_score": round(self.final_score, 4),
            "dense_score": round(self.dense_score, 4),
            "bm25_score": round(self.bm25_score, 4),
            "metadata_score": round(self.metadata_score, 4),
            "keyword_score": round(self.keyword_score, 4),
            "retrieval_type": self.retrieval_type,
            "confidence_level": confidence,
            "metadata": metadata,
            "file_name": metadata.get("file_name") or "Unknown document",
            "chunk_id": metadata.get("chunk_id") or "Unknown",
            "page_number": metadata.get("page_number"),
            "section_title": metadata.get("section_title"),
            "collection_name": metadata.get("collection_name") or "Unknown collection",
        }


class HybridRetriever:
    def __init__(self, vectorstore, documents: Sequence[Document], k: int = 5):
        self.vectorstore = vectorstore
        self.documents = list(documents)
        self.k = k
        self.keyword_retriever = BM25Retriever.from_documents(self.documents) if self.documents else None
        self.mode = "dense + BM25 hybrid" if self.keyword_retriever else "dense only"
        if self.keyword_retriever:
            self.keyword_retriever.k = max(k * 2, 10)

    def retrieve(
        self,
        query: str,
        collection_name: str = "",
        file_name: str = "",
        limit: int = 10,
    ) -> List[ScoredDocument]:
        dense_docs = self._dense_search(query, max(limit, self.k * 2))
        bm25_docs = self.keyword_retriever.invoke(query) if self.keyword_retriever else []

        scores = defaultdict(lambda: ScoredDocument(document=None))

        for rank, (doc, score) in enumerate(dense_docs):
            key = self._key(doc)
            normalized = self._normalize_dense_score(score, rank, len(dense_docs))
            scores[key].document = doc
            scores[key].dense_score = max(scores[key].dense_score, normalized)

        total_bm25 = max(len(bm25_docs), 1)
        for rank, doc in enumerate(bm25_docs):
            key = self._key(doc)
            scores[key].document = doc
            scores[key].bm25_score = max(scores[key].bm25_score, 1 - (rank / total_bm25))

        query_terms = _terms(query)
        ranked = []
        for item in scores.values():
            if item.document is None:
                continue
            item.keyword_score = _keyword_overlap(query_terms, _terms(item.document.page_content))
            item.metadata_score = _metadata_boost(
                query_terms,
                item.document.metadata,
                collection_name=collection_name,
                file_name=file_name,
            )
            item.final_score = min(
                1.0,
                (DENSE_WEIGHT * item.dense_score)
                + (BM25_WEIGHT * item.bm25_score)
                + item.keyword_score
                + item.metadata_score,
            )
            item.retrieval_type = _retrieval_type(item)
            ranked.append(item)

        ranked.sort(key=lambda item: item.final_score, reverse=True)
        return ranked[:limit]

    def invoke(self, query: str):
        return [item.document for item in self.retrieve(query, limit=self.k)]

    def _dense_search(self, query: str, limit: int):
        try:
            return self.vectorstore.similarity_search_with_relevance_scores(query, k=limit)
        except Exception:
            docs = self.vectorstore.similarity_search(query, k=limit)
            total = max(len(docs), 1)
            return [(doc, 1 - (rank / total)) for rank, doc in enumerate(docs)]

    @staticmethod
    def _normalize_dense_score(score: float, rank: int, total: int) -> float:
        try:
            score = float(score)
        except Exception:
            score = 0.0
        if 0 <= score <= 1:
            return score
        return max(0.0, 1 - (rank / max(total, 1)))

    @staticmethod
    def _key(doc: Document) -> str:
        metadata = doc.metadata or {}
        return metadata.get("chunk_id") or doc.page_content[:200]


def _terms(text: str) -> set[str]:
    return set(re.findall(r"[A-Za-z0-9_]{3,}", (text or "").lower()))


def _keyword_overlap(query_terms: set[str], doc_terms: set[str]) -> float:
    if not query_terms or not doc_terms:
        return 0.0
    return min(0.12, 0.12 * (len(query_terms & doc_terms) / len(query_terms)))


def _metadata_boost(
    query_terms: set[str],
    metadata: dict,
    collection_name: str = "",
    file_name: str = "",
) -> float:
    metadata = metadata or {}
    boost = 0.0
    source_file_name = str(metadata.get("file_name", "")).lower()
    section_title = str(metadata.get("section_title", "")).lower()
    if collection_name and metadata.get("collection_name") == collection_name:
        boost += 0.04
    if file_name and source_file_name == str(file_name).lower():
        boost += 0.04
    if any(term in source_file_name for term in query_terms):
        boost += 0.05
    if any(term in section_title for term in query_terms):
        boost += 0.08
    try:
        chunk_index = int(metadata.get("chunk_index", 999999))
        if chunk_index <= 2:
            boost += 0.03
    except Exception:
        pass
    return min(boost, 0.16)


def _retrieval_type(item: ScoredDocument) -> str:
    if item.dense_score > 0 and item.bm25_score > 0:
        return "hybrid"
    if item.bm25_score > 0:
        return "bm25"
    return "dense"


def confidence_for_score(score: float) -> str:
    if score >= 0.70:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"

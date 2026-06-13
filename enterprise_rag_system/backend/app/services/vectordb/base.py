from abc import ABC, abstractmethod
from typing import List

from langchain_core.documents import Document

from app.core.runtime_credentials import RuntimeCredentials


class VectorDB(ABC):
    @abstractmethod
    def build_vectorstore(
        self,
        documents: List[Document],
        collection_name: str,
        embedding_provider: str,
        credentials: RuntimeCredentials | None = None,
    ):
        raise NotImplementedError

    def build_retriever(
        self,
        documents: List[Document],
        collection_name: str,
        k: int,
        embedding_provider: str = "huggingface",
        credentials: RuntimeCredentials | None = None,
    ):
        raise NotImplementedError

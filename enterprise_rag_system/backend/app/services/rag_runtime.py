import logging
import re
from dataclasses import dataclass, field
from typing import Dict, Generator, List

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate

from app.core.constants import DEFAULT_COLLECTION, DEFAULT_MAX_ITERATIONS
from app.core.prompts import COLLECTION_RELEVANCE_PROMPT, EVALUATE_PROMPT, GENERATE_PROMPT
from app.core.runtime_credentials import RuntimeCredentials
from app.services.ingestion.pipeline import load_and_chunk_document
from app.services.llm.embeddings_service import normalize_embedding_provider
from app.services.llm.generation_service import get_chat_model
from app.services.memory.memory_store import append_memory
from app.services.retrieval.bm25_store import (
    bm25_index_exists,
    load_bm25_index,
    save_bm25_index,
)
from app.services.retrieval.context_builder import build_context
from app.services.retrieval.hybrid_search import HybridRetriever, ScoredDocument
from app.services.retrieval.reranker_service import rerank_documents
from app.services.retrieval.web_fallback import run_web_search_sources
from app.services.vectordb.collection_registry import (
    collection_exists,
    list_registered_collections,
    register_collection,
)
from app.services.vectordb.factory import get_vector_db


@dataclass
class RagSession:
    session_id: str
    collection_name: str
    filename: str
    embedding_provider: str
    documents: List[Document]
    retrieval_mode: str
    build_documents: List[Document] = field(default_factory=list)
    k: int = 5
    source: str = "runtime"
    retrieval_warning: str = ""
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    enable_grading: bool = True
    enable_evaluation: bool = True


_SESSIONS: Dict[str, RagSession] = {}
logger = logging.getLogger(__name__)


def register_session(session: RagSession) -> None:
    _SESSIONS[session.session_id] = session


def list_sessions() -> List[dict]:
    return [
        {
            "session_id": session.session_id,
            "collection_name": session.collection_name,
            "filename": session.filename,
            "embedding_provider": session.embedding_provider,
            "source": session.source,
            "retrieval_mode": session.retrieval_mode,
            "retrieval_warning": session.retrieval_warning,
        }
        for session in _SESSIONS.values()
    ]


def delete_session(session_id: str) -> bool:
    return _SESSIONS.pop(session_id, None) is not None


def delete_sessions_for_collection(collection_name: str) -> int:
    to_delete = [
        session_id
        for session_id, session in _SESSIONS.items()
        if session.collection_name == collection_name
    ]
    for session_id in to_delete:
        _SESSIONS.pop(session_id, None)
    return len(to_delete)


def get_session(session_id: str) -> RagSession:
    if session_id not in _SESSIONS:
        fallback = _fallback_session()
        if fallback:
            return fallback
        raise KeyError("Session not found. Upload and build a knowledge base first.")
    return _SESSIONS[session_id]


def get_runtime_session(session_id: str) -> RagSession | None:
    return _SESSIONS.get(session_id)


def resolve_chat_session(
    session_id: str,
    collection_name: str = "",
    credentials: RuntimeCredentials | None = None,
) -> RagSession:
    requested_collection = (collection_name or "").strip()
    runtime_session = get_runtime_session(session_id)
    if requested_collection and (
        runtime_session is None or runtime_session.collection_name != requested_collection
    ):
        logger.warning(
            "Resolving chat session from request payload session_id=%s requested_collection=%s runtime_collection=%s",
            session_id,
            requested_collection,
            runtime_session.collection_name if runtime_session else "missing",
        )
        session = select_existing_collection(
            session_id=session_id,
            collection_name=requested_collection,
            embedding_provider=runtime_session.embedding_provider if runtime_session else "huggingface",
            credentials=credentials,
        )
        logger.info(
            "Resolved chat session session_id=%s collection=%s from request payload",
            session.session_id,
            session.collection_name,
        )
        return session
    session = get_session(session_id)
    logger.info(
        "Resolved chat session session_id=%s collection=%s",
        session.session_id,
        session.collection_name,
    )
    return session


def create_rag_session(
    session_id: str,
    file_path: str,
    filename: str,
    collection_name: str,
    chunk_size: int,
    chunk_overlap: int,
    k: int,
    max_iterations: int,
    enable_grading: bool = True,
    enable_evaluation: bool = True,
    credentials: RuntimeCredentials | None = None,
    embedding_provider: str = "huggingface",
    use_existing_collection: bool = False,
) -> RagSession:
    credentials = credentials or RuntimeCredentials()
    credentials.require_chat_credentials()

    embedding_provider = normalize_embedding_provider(embedding_provider)
    logger.info(
        "Creating RAG session session_id=%s collection=%s embedding_provider=%s",
        session_id,
        collection_name,
        embedding_provider,
    )
    if embedding_provider == "openai":
        credentials.require_openai_api_key()

    chunks = load_and_chunk_document(
        file_path=file_path,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        collection_name=collection_name,
        embedding_provider=embedding_provider,
    )
    vector_provider = get_vector_db()
    vectorstore = vector_provider.build_vectorstore(
        documents=chunks,
        collection_name=collection_name,
        embedding_provider=embedding_provider,
        credentials=credentials,
    )
    indexed_chunks = _merge_documents(load_bm25_index(collection_name), chunks) if use_existing_collection else chunks
    save_bm25_index(collection_name, indexed_chunks)
    retriever = HybridRetriever(vectorstore, indexed_chunks, k=max(k, 5))
    register_collection(collection_name, indexed_chunks, embedding_provider, source="runtime")
    session = RagSession(
        session_id=session_id,
        collection_name=collection_name,
        filename=filename,
        embedding_provider=embedding_provider,
        documents=indexed_chunks,
        retrieval_mode=retriever.mode,
        build_documents=chunks,
        k=max(k, 5),
        source="runtime",
        max_iterations=max_iterations,
        enable_grading=enable_grading,
        enable_evaluation=enable_evaluation,
    )
    register_session(session)
    return session


def select_existing_collection(
    session_id: str,
    collection_name: str,
    embedding_provider: str = "huggingface",
    credentials: RuntimeCredentials | None = None,
) -> RagSession:
    credentials = credentials or RuntimeCredentials()
    collection_name = (collection_name or "").strip() or _resolve_collection_name("")
    embedding_provider = normalize_embedding_provider(embedding_provider)
    logger.info(
        "Selecting collection session_id=%s collection=%s embedding_provider=%s",
        session_id,
        collection_name,
        embedding_provider,
    )
    vector_provider = get_vector_db()
    if not hasattr(vector_provider, "existing_vectorstore"):
        raise ValueError("Current vector DB provider cannot attach existing collections.")
    vectorstore = vector_provider.existing_vectorstore(collection_name, embedding_provider, credentials)
    documents = load_bm25_index(collection_name)
    retrieval_warning = ""
    if not documents:
        retrieval_warning = (
            "BM25 index not found for this collection. Dense retrieval is active. "
            "Rebuild BM25 index to enable full hybrid search."
        )
    retriever = HybridRetriever(vectorstore, documents, k=5)
    session = RagSession(
        session_id=session_id,
        collection_name=collection_name,
        filename="existing_qdrant_collection",
        embedding_provider=embedding_provider,
        documents=documents,
        retrieval_mode=retriever.mode,
        k=5,
        source="qdrant",
        retrieval_warning=retrieval_warning,
    )
    register_session(session)
    return session


def _build_session_retriever(
    session: RagSession,
    credentials: RuntimeCredentials | None = None,
) -> HybridRetriever:
    vector_provider = get_vector_db()
    if not hasattr(vector_provider, "existing_vectorstore"):
        raise ValueError("Current vector DB provider cannot attach existing collections.")
    vectorstore = vector_provider.existing_vectorstore(
        session.collection_name,
        session.embedding_provider,
        credentials or RuntimeCredentials(),
    )
    return HybridRetriever(vectorstore, session.documents, k=session.k)


def retrieve_session_sources(
    session_id: str,
    question: str,
    credentials: RuntimeCredentials | None = None,
) -> List[ScoredDocument]:
    session = get_session(session_id)
    retriever = _build_session_retriever(session, credentials)
    candidates = retriever.retrieve(
        question,
        collection_name=session.collection_name,
        file_name=session.filename,
        limit=10,
    )
    return rerank_documents(candidates)


def _trace(message: str, kind: str = "info", node: str = "") -> dict:
    step = {"message": message, "kind": kind}
    if node:
        step["node"] = node
    return step


def _web_documents(web_sources: List[dict]) -> List[Document]:
    documents = []
    for source in web_sources:
        metadata = source.get("metadata") or {}
        documents.append(Document(page_content=str(source.get("content") or ""), metadata=metadata))
    return documents


def _run_web_fallback(
    question: str,
    trace: List[dict],
    credentials: RuntimeCredentials | None = None,
) -> tuple[List[dict], List[Document]]:
    credentials = credentials or RuntimeCredentials()
    if not _web_search_configured(credentials):
        trace.append(_trace("Web search skipped because Tavily is not configured.", "warning", "web_search"))
        return [], []
    trace.append(_trace("No useful collection chunks found. Running Tavily web search.", "warning", "web_search"))
    try:
        web_sources = run_web_search_sources(question, max_results=3, credentials=credentials)
    except Exception as exc:
        trace.append(_trace(f"Web search failed: {credentials.redact(exc)}", "error", "web_search"))
        return [], []
    trace.append(_trace(f"Web search returned {len(web_sources)} result(s).", "success", "web_search"))
    return web_sources, _web_documents(web_sources)


def _web_search_configured(credentials: RuntimeCredentials | None = None) -> bool:
    credentials = credentials or RuntimeCredentials()
    return bool(credentials.effective_tavily_api_key)


def _is_collection_related(
    question: str,
    context_documents,
    collection_documents=None,
    credentials: RuntimeCredentials | None = None,
) -> bool:
    scope_documents = _scope_documents(context_documents or [], collection_documents or [])
    context = build_context(scope_documents)
    if not context.strip():
        return False
    if _has_scope_evidence(question, context):
        return True
    try:
        llm = get_chat_model(streaming=False, credentials=credentials)
        result = (ChatPromptTemplate.from_template(COLLECTION_RELEVANCE_PROMPT) | llm).invoke(
            {
                "question": question,
                "context": context,
            }
        ).content
        normalized = result.strip().lower()
        return normalized.startswith("related") and not normalized.startswith("unrelated")
    except Exception:
        return True


def _scope_documents(context_documents, collection_documents) -> List:
    scoped = []
    seen = set()
    for item in [*(context_documents or []), *(collection_documents or [])]:
        doc = item.document if hasattr(item, "document") else item
        metadata = getattr(doc, "metadata", {}) or {}
        key = metadata.get("chunk_id") or getattr(doc, "page_content", str(doc))[:120]
        if key in seen:
            continue
        seen.add(key)
        scoped.append(item)
        if len(scoped) >= 12:
            break
    return scoped


def _collection_scope_documents(session: RagSession, sources: List[ScoredDocument]) -> List:
    if sources:
        source_docs = [source.document for source in sources if source.document is not None]
        return [*sources, *source_docs[:4]]
    return list(session.documents[:12])


def _has_scope_evidence(question: str, context: str) -> bool:
    normalized_question = _normalize_scope_text(question)
    normalized_context = _normalize_scope_text(context)
    if not normalized_question or not normalized_context:
        return False
    if _is_document_summary_intent(question):
        return True

    for phrase in _scope_phrases(normalized_question):
        if phrase in normalized_context:
            return True

    for alias, evidence_terms in _SCOPE_ALIASES.items():
        if alias in normalized_question and any(term in normalized_context for term in evidence_terms):
            return True

    if _is_educational_domain_question(normalized_question):
        for domain_terms in _EDUCATIONAL_DOMAIN_TERMS.values():
            if any(term in normalized_question for term in domain_terms) and any(term in normalized_context for term in domain_terms):
                return True

    question_terms = {
        term
        for term in normalized_question.split()
        if len(term) >= 4 and term not in _SCOPE_STOPWORDS
    }
    if not question_terms:
        return False

    context_terms = set(normalized_context.split())
    overlap = question_terms & context_terms
    return len(overlap) >= 2 or bool(overlap & _DOMAIN_SCOPE_TERMS)


def _is_educational_domain_question(normalized_question: str) -> bool:
    return any(intent in normalized_question for intent in _EDUCATIONAL_INTENT_TERMS)


def _is_document_summary_intent(question: str) -> bool:
    normalized_question = _normalize_scope_text(question)
    if not normalized_question:
        return False

    document_references = (
        "active document",
        "this document",
        "uploaded document",
        "selected document",
        "active file",
        "this file",
        "uploaded file",
        "selected file",
    )
    document_reference_summary_phrases = (
        "what is this document about",
        "tell me about this document",
        "what is this file about",
        "tell me about this file",
    )
    summary_intents = (
        "summarize",
        "summary",
        "overview",
        "main points",
        "key points",
        "key takeaways",
    )
    document_about_terms = (
        "about",
        "describe",
        "explain",
        "tell",
    )

    if any(phrase in normalized_question for phrase in document_reference_summary_phrases):
        return True
    if any(intent in normalized_question for intent in summary_intents):
        return True
    return any(reference in normalized_question for reference in document_references) and any(
        term in normalized_question.split() for term in document_about_terms
    )


def _question_may_need_web_search(question: str) -> bool:
    normalized_question = _normalize_scope_text(question)
    return any(term in normalized_question.split() for term in _WEB_SEARCH_HINT_TERMS)


def _normalize_scope_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()


def _scope_phrases(normalized_question: str) -> List[str]:
    words = [word for word in normalized_question.split() if word not in _SCOPE_STOPWORDS]
    phrases = []
    for size in (3, 2):
        phrases.extend(" ".join(words[index : index + size]) for index in range(0, max(len(words) - size + 1, 0)))
    return [phrase for phrase in phrases if len(phrase) >= 8]


_SCOPE_STOPWORDS = {
    "about",
    "answer",
    "bata",
    "batao",
    "btao",
    "cost",
    "document",
    "does",
    "give",
    "hai",
    "hain",
    "hoga",
    "hogi",
    "how",
    "info",
    "kia",
    "kya",
    "kitna",
    "kitni",
    "mein",
    "tell",
    "this",
    "what",
    "will",
}


_DOMAIN_SCOPE_TERMS = {
    "appointment",
    "attendance",
    "backup",
    "biometric",
    "clinic",
    "cloud",
    "cricket",
    "drive",
    "google",
    "gym",
    "patient",
    "playground",
    "proposal",
    "ground",
    "revenue",
    "storage",
    "application",
    "applications",
    "chatbot",
    "chatbots",
    "generation",
    "language",
    "llm",
    "llms",
    "machine",
    "model",
    "models",
    "natural",
    "nlp",
    "processing",
    "sentiment",
    "text",
    "transformer",
    "transformers",
    "translation",
}


_SCOPE_ALIASES = {
    "nlp": (
        "natural language processing",
        "language models",
        "large language models",
        "llm",
        "transformers",
        "text generation",
        "chatbots",
        "machine translation",
        "sentiment analysis",
        "text processing",
    ),
    "natural language processing": (
        "nlp",
        "language models",
        "large language models",
        "transformers",
        "text generation",
        "chatbots",
        "machine translation",
        "sentiment analysis",
    ),
    "language models": (
        "nlp",
        "natural language processing",
        "large language models",
        "llm",
        "transformers",
        "text generation",
    ),
    "llm": (
        "language models",
        "large language models",
        "natural language processing",
        "nlp",
        "transformers",
        "text generation",
    ),
    "llms": (
        "language models",
        "large language models",
        "natural language processing",
        "nlp",
        "transformers",
        "text generation",
    ),
    "purpposal": (
        "project proposal",
        "proposal outlines",
        "project deliverables",
    ),
    "purposal": (
        "project proposal",
        "proposal outlines",
        "project deliverables",
    ),
    "hims": (
        "clinic",
        "management system",
        "appointments",
        "clinic management",
        "physician clinic",
        "patient records",
        "appointment scheduling",
        "doctor availability",
        "revenue calculation",
    ),
    "hospital information management": (
        "clinic management",
        "physician clinic",
        "patient records",
        "appointment scheduling",
    ),
    "hospital management": (
        "clinic management",
        "physician clinic",
        "patient records",
        "appointment scheduling",
    ),
    "play ground": (
        "cricket playground",
        "playground booking",
        "ground booking",
        "cricket ground",
    ),
}


_EDUCATIONAL_INTENT_TERMS = {
    "application",
    "applications",
    "benefit",
    "benefits",
    "challenge",
    "challenges",
    "example",
    "examples",
    "explain",
    "future",
    "limitation",
    "limitations",
    "main points",
    "overview",
    "summary",
    "trend",
    "trends",
    "what is",
}


_EDUCATIONAL_DOMAIN_TERMS = {
    "nlp": {
        "natural language processing",
        "language models",
        "large language models",
        "machine translation",
        "sentiment analysis",
        "text generation",
        "nlp",
        "llm",
        "llms",
        "transformer",
        "transformers",
        "chatbot",
        "chatbots",
        "language",
        "text",
    },
}


_WEB_SEARCH_HINT_TERMS = {
    "cost",
    "current",
    "estimate",
    "external",
    "fee",
    "kitna",
    "kitni",
    "latest",
    "market",
    "price",
    "pricing",
    "quote",
    "rate",
    "today",
    "won",
}


def _evaluate_answer(
    question: str,
    answer: str,
    context_documents=None,
    credentials: RuntimeCredentials | None = None,
) -> str:
    if not answer.strip():
        return "not_good"
    lowered = answer.lower()
    weak_phrases = (
        "could not find document context",
        "there is no information",
        "no information regarding",
        "no information about",
        "not enough information",
        "no available context",
        "cannot provide specific",
        "can't provide specific",
        "unable to provide specific",
        "i don't have enough",
    )
    if any(phrase in lowered for phrase in weak_phrases):
        return "not_good"
    if not context_documents and any(marker in lowered for marker in ("general knowledge", "general answer", "general ai knowledge")):
        return "good"
    try:
        llm = get_chat_model(streaming=False, credentials=credentials)
        result = (ChatPromptTemplate.from_template(EVALUATE_PROMPT) | llm).invoke(
            {
                "question": question,
                "context": build_context(context_documents or []),
                "answer": answer,
            }
        ).content
        lowered_result = result.strip().lower()
        return "good" if "good" in lowered_result and "not_good" not in lowered_result else "not_good"
    except Exception:
        return "good"


def _generate_answer(
    question: str,
    context_documents,
    confidence_level: str,
    answer_length: str,
    streaming: bool = False,
    credentials: RuntimeCredentials | None = None,
):
    llm = get_chat_model(streaming=streaming, credentials=credentials)
    prompt = ChatPromptTemplate.from_template(GENERATE_PROMPT)
    messages = prompt.format_messages(
        context=build_context(context_documents),
        question=question,
        confidence_level=confidence_level,
        answer_length=answer_length,
    )
    if streaming:
        return llm.stream(messages)
    return llm.invoke(messages).content


def _agentic_chat_plan(
    session: RagSession,
    question: str,
    allow_web_search: bool = False,
    credentials: RuntimeCredentials | None = None,
) -> dict:
    credentials = credentials or RuntimeCredentials()
    web_search_configured = _web_search_configured(credentials)
    trace = [_trace("LangGraph-style agent started.", "info", "start")]
    trace.append(_trace("Retrieving from selected collection with hybrid retrieval.", "info", "retrieve"))
    sources = retrieve_session_sources(session.session_id, question, credentials)
    confidence_level = _confidence_level(sources)
    serialized_sources = [source.as_source() for source in sources]
    trace.append(_trace(f"Retrieved {len(sources)} collection chunk(s).", "success" if sources else "warning", "retrieve"))
    trace.append(_trace(f"Confidence: {confidence_level}.", "info", "grade_documents"))

    web_sources: List[dict] = []
    web_documents: List[Document] = []
    search_type = "hybrid"
    context_documents = sources
    collection_scope_documents = _collection_scope_documents(session, sources)
    if session.enable_grading:
        collection_related = _is_collection_related(question, sources, collection_scope_documents, credentials)
        trace.append(
            _trace(
                f"Collection relevance: {'related' if collection_related else 'unrelated'}.",
                "success" if collection_related else "warning",
                "scope_gate",
            )
        )
    else:
        collection_related = True
        trace.append(_trace("Collection relevance grading skipped by settings.", "info", "scope_gate"))

    if not sources and collection_related:
        if allow_web_search and web_search_configured:
            web_sources, web_documents = _run_web_fallback(question, trace, credentials)
            if web_documents:
                search_type = "web_search"
                context_documents = web_documents
                confidence_level = "web"
        elif allow_web_search:
            trace.append(_trace("Web search requested but Tavily is not configured.", "warning", "web_search"))
        else:
            trace.append(_trace("Web search is available for this related question, pending user approval.", "warning", "web_search"))
    elif not sources:
        if allow_web_search and web_search_configured:
            web_sources, web_documents = _run_web_fallback(question, trace, credentials)
            if web_documents:
                search_type = "web_search"
                context_documents = web_documents
                confidence_level = "web"
        elif allow_web_search:
            trace.append(_trace("Web search requested but Tavily is not configured.", "warning", "web_search"))
        else:
            trace.append(_trace("No related collection chunks found. General answer is allowed with clear labeling.", "warning", "scope_gate"))
    elif collection_related and allow_web_search and web_search_configured and _question_may_need_web_search(question):
        web_sources, web_documents = _run_web_fallback(question, trace, credentials)
        if web_documents:
            search_type = "web_search"
            context_documents = [*sources, *web_documents]
            confidence_level = "web"
    elif collection_related and allow_web_search and not web_search_configured and _question_may_need_web_search(question):
        trace.append(_trace("Web search requested but Tavily is not configured.", "warning", "web_search"))
    elif not collection_related:
        if allow_web_search and web_search_configured:
            web_sources, web_documents = _run_web_fallback(question, trace, credentials)
            if web_documents:
                search_type = "web_search"
                context_documents = web_documents
                confidence_level = "web"
            else:
                context_documents = []
                confidence_level = "none"
        elif allow_web_search:
            context_documents = []
            confidence_level = "none"
            trace.append(_trace("Web search requested but Tavily is not configured.", "warning", "web_search"))
        else:
            context_documents = []
            confidence_level = "none"
            trace.append(
                _trace(
                    "Answer generation blocked because retrieved chunks are outside the selected collection scope.",
                    "warning",
                    "scope_gate",
                )
            )

    web_search_eligible = collection_related or bool(web_sources)
    web_search_can_be_offered = web_search_configured and not web_sources and (
        not sources or _question_may_need_web_search(question) or not collection_related
    )

    return {
        "trace": trace,
        "sources": serialized_sources,
        "web_sources": web_sources,
        "context_documents": context_documents,
        "search_type": search_type,
        "confidence_level": confidence_level,
        "retrieved_docs_count": len(sources),
        "web_results_count": len(web_sources),
        "web_search_used": bool(web_sources),
        "collection_relevance": "related" if collection_related else "unrelated",
        "web_search_eligible": web_search_eligible,
        "allow_web_search": allow_web_search,
        "web_search_available": web_search_can_be_offered,
        "web_search_requires_approval": web_search_can_be_offered and not allow_web_search,
    }


def ask_session(
    session_id: str,
    question: str,
    answer_length: str = "Medium: 180-250 words",
    allow_web_search: bool = False,
    credentials: RuntimeCredentials | None = None,
    collection_name: str = "",
) -> dict:
    credentials = credentials or RuntimeCredentials()
    credentials.require_chat_credentials()
    session = resolve_chat_session(session_id, collection_name, credentials)
    plan = _agentic_chat_plan(session, question, allow_web_search, credentials)
    iteration_count = 1
    if not plan["context_documents"]:
        if plan.get("web_search_eligible", True):
            plan["trace"].append(_trace("No answer context available; generating a clearly labeled general answer.", "warning", "generate"))
            answer = _generate_answer(question, [], "none", answer_length, credentials=credentials)
        else:
            plan["trace"].append(_trace("No answer context available; returning a scope-safe response.", "warning", "generate"))
            answer = "This question appears outside the selected document collection, so I did not run web search."
    else:
        plan["trace"].append(_trace("Generating answer from current context.", "info", "generate"))
        answer = _generate_answer(question, plan["context_documents"], plan["confidence_level"], answer_length, credentials=credentials)
    if not session.enable_evaluation:
        evaluation = "skipped"
    elif not plan.get("web_search_eligible", True) and not plan["context_documents"]:
        evaluation = "not_good"
    else:
        evaluation = _evaluate_answer(question, answer, plan["context_documents"], credentials)
    plan["trace"].append(_trace(f"Evaluation: {evaluation}.", "success" if evaluation in {"good", "skipped"} else "warning", "evaluate"))

    if (
        evaluation == "not_good"
        and not plan["web_search_used"]
        and plan.get("web_search_eligible", True)
        and plan.get("allow_web_search", False)
        and iteration_count < session.max_iterations
    ):
        web_sources, web_documents = _run_web_fallback(question, plan["trace"], credentials)
        if web_documents:
            iteration_count += 1
            plan["web_sources"] = web_sources
            plan["context_documents"] = web_documents
            plan["search_type"] = "web_search"
            plan["confidence_level"] = "web"
            plan["web_search_used"] = True
            plan["trace"].append(_trace("Regenerating answer with web-search context.", "info", "generate"))
            answer = _generate_answer(question, web_documents, "web", answer_length, credentials=credentials)
            evaluation = _evaluate_answer(question, answer, web_documents, credentials)
            plan["trace"].append(
                _trace(f"Evaluation after web search: {evaluation}.", "success" if evaluation == "good" else "warning", "evaluate")
            )
    elif evaluation == "not_good" and not plan.get("web_search_eligible", True):
        plan["trace"].append(
            _trace("Web search skipped because the question is outside the selected collection scope.", "warning", "scope_gate")
        )
    elif (
        plan.get("web_search_eligible", True)
        and plan.get("web_search_available", False)
        and not plan.get("allow_web_search", False)
        and _question_may_need_web_search(question)
    ):
        plan["web_search_available"] = True
        plan["web_search_requires_approval"] = True
        plan["trace"].append(_trace("Web search is available but requires user approval.", "warning", "web_search"))
    else:
        plan["web_search_requires_approval"] = False

    all_sources = [] if not plan.get("web_search_eligible", True) else plan["sources"] + plan["web_sources"]
    result = {
        "answer": answer,
        "search_type": plan["search_type"],
        "evaluation": evaluation,
        "iteration_count": iteration_count,
        "retrieved_docs_count": plan["retrieved_docs_count"],
        "web_results_count": len(plan["web_sources"]),
        "confidence_level": plan["confidence_level"],
        "retrieval_mode": session.retrieval_mode,
        "retrieval_warning": session.retrieval_warning,
        "llm_provider": credentials.llm_provider,
        "llm_model": credentials.llm_model,
        "runtime_openai_active": credentials.runtime_openai_active,
        "llm_fallback_status": "not_used" if credentials.llm_provider == "openai" else "",
        "error_reason": "",
        "sources": all_sources,
        "web_search_used": plan["web_search_used"],
        "web_search_available": plan.get("web_search_available", False),
        "web_search_requires_approval": plan.get("web_search_requires_approval", False),
        "collection_relevance": plan.get("collection_relevance"),
        "web_search_eligible": plan.get("web_search_eligible"),
        "trace": plan["trace"],
    }
    if session.retrieval_warning:
        result["trace"].append({"message": session.retrieval_warning, "kind": "warning"})
    _safe_append_memory(session.session_id, session.collection_name, question, answer, all_sources)
    return result


def stream_session_answer(
    session_id: str,
    question: str,
    answer_length: str = "Medium: 180-250 words",
    allow_web_search: bool = False,
    credentials: RuntimeCredentials | None = None,
    collection_name: str = "",
) -> Generator[str, None, None]:
    import json

    credentials = credentials or RuntimeCredentials()
    try:
        credentials.require_chat_credentials()
        session = resolve_chat_session(session_id, collection_name, credentials)
        plan = _agentic_chat_plan(session, question, allow_web_search, credentials)
        for step in plan["trace"]:
            yield _sse("trace", step)
        all_sources = plan["sources"] + plan["web_sources"]
        if not plan.get("web_search_eligible", True):
            all_sources = []
        yield _sse(
            "sources",
            {
                "sources": all_sources,
                "retrieved_docs_count": plan["retrieved_docs_count"],
                "web_results_count": len(plan["web_sources"]),
                "confidence_level": plan["confidence_level"],
                "retrieval_mode": session.retrieval_mode,
                "retrieval_warning": session.retrieval_warning,
                "search_type": plan["search_type"],
                "web_search_used": plan["web_search_used"],
                "web_search_available": plan.get("web_search_available", False),
                "web_search_requires_approval": plan.get("web_search_requires_approval", False),
                "collection_relevance": plan.get("collection_relevance"),
                "web_search_eligible": plan.get("web_search_eligible"),
                "trace_steps": plan["trace"],
            },
        )
        if not plan["context_documents"]:
            if plan.get("web_search_eligible", True):
                no_context_trace = _trace("No answer context available; generating a clearly labeled general answer.", "warning", "generate")
            else:
                no_context_trace = _trace("No answer context available; returning a scope-safe response.", "warning", "generate")
            plan["trace"].append(no_context_trace)
            yield _sse("trace", no_context_trace)
            if plan.get("web_search_eligible", True):
                answer_parts: List[str] = []
                for chunk in _generate_answer(
                    question,
                    [],
                    "none",
                    answer_length,
                    streaming=True,
                    credentials=credentials,
                ):
                    token = getattr(chunk, "content", "") or ""
                    if token:
                        answer_parts.append(token)
                        yield _sse("token", {"token": token})
                message = "".join(answer_parts)
                evaluation = "skipped" if not session.enable_evaluation else _evaluate_answer(question, message, [], credentials)
            else:
                message = "This question appears outside the selected document collection, so I did not run web search."
                yield _sse("token", {"token": message})
                evaluation = "skipped" if not session.enable_evaluation else "not_good"
            trace = plan["trace"] + [_trace(f"Evaluation: {evaluation}.", "success" if evaluation in {"good", "skipped"} else "warning", "evaluate")]
            yield _sse(
                "done",
                {
                    "answer": message,
                    "sources": all_sources,
                    "search_type": plan["search_type"],
                    "evaluation": evaluation,
                    "iteration_count": 1,
                    "retrieved_docs_count": plan["retrieved_docs_count"],
                    "web_results_count": len(plan["web_sources"]),
                    "confidence_level": "none",
                    "retrieval_mode": session.retrieval_mode,
                    "retrieval_warning": session.retrieval_warning,
                    "llm_provider": credentials.llm_provider,
                    "llm_model": credentials.llm_model,
                    "runtime_openai_active": credentials.runtime_openai_active,
                    "llm_fallback_status": "not_used" if credentials.llm_provider == "openai" else "",
                    "error_reason": "",
                    "web_search_used": plan["web_search_used"],
                    "web_search_available": plan.get("web_search_available", False),
                    "web_search_requires_approval": plan.get("web_search_requires_approval", False),
                    "collection_relevance": plan.get("collection_relevance"),
                    "web_search_eligible": plan.get("web_search_eligible"),
                    "trace_steps": trace,
                },
            )
            _safe_append_memory(session.session_id, session.collection_name, question, message, all_sources)
            return

        generation_trace = _trace("Generating answer from current context.", "info", "generate")
        plan["trace"].append(generation_trace)
        yield _sse("trace", generation_trace)
        answer_parts: List[str] = []
        for chunk in _generate_answer(
            question,
            plan["context_documents"],
            plan["confidence_level"],
            answer_length,
            streaming=True,
            credentials=credentials,
        ):
            token = getattr(chunk, "content", "") or ""
            if token:
                answer_parts.append(token)
                yield _sse("token", {"token": token})
        final_answer = "".join(answer_parts)
        evaluation = "skipped" if not session.enable_evaluation else _evaluate_answer(question, final_answer, plan["context_documents"], credentials)
        eval_trace = _trace(f"Evaluation: {evaluation}.", "success" if evaluation in {"good", "skipped"} else "warning", "evaluate")
        plan["trace"].append(eval_trace)
        yield _sse("trace", eval_trace)

        iteration_count = 1
        if (
            evaluation == "not_good"
            and not plan["web_search_used"]
            and plan.get("web_search_eligible", True)
            and plan.get("allow_web_search", False)
            and iteration_count < session.max_iterations
        ):
            web_sources, web_documents = _run_web_fallback(question, plan["trace"], credentials)
            for step in plan["trace"][-2:]:
                yield _sse("trace", step)
            if web_documents:
                iteration_count += 1
                plan["web_sources"] = web_sources
                plan["search_type"] = "web_search"
                plan["confidence_level"] = "web"
                plan["web_search_used"] = True
                plan["context_documents"] = web_documents
                all_sources = plan["sources"] + web_sources
                yield _sse(
                    "sources",
                    {
                        "sources": all_sources,
                        "retrieved_docs_count": plan["retrieved_docs_count"],
                        "web_results_count": len(web_sources),
                        "confidence_level": "web",
                        "retrieval_mode": session.retrieval_mode,
                        "retrieval_warning": session.retrieval_warning,
                        "search_type": "web_search",
                        "web_search_used": True,
                        "web_search_available": False,
                        "web_search_requires_approval": False,
                        "collection_relevance": plan.get("collection_relevance"),
                        "web_search_eligible": plan.get("web_search_eligible"),
                        "trace_steps": plan["trace"],
                    },
                )
                regen_trace = _trace("Regenerating answer with web-search context.", "info", "generate")
                plan["trace"].append(regen_trace)
                yield _sse("trace", regen_trace)
                answer_parts = []
                for chunk in _generate_answer(
                    question,
                    web_documents,
                    "web",
                    answer_length,
                    streaming=True,
                    credentials=credentials,
                ):
                    token = getattr(chunk, "content", "") or ""
                    if token:
                        answer_parts.append(token)
                        yield _sse("token", {"token": token})
                final_answer = "".join(answer_parts)
                evaluation = "skipped" if not session.enable_evaluation else _evaluate_answer(question, final_answer, web_documents, credentials)
                eval_trace = _trace(
                    f"Evaluation after web search: {evaluation}.",
                    "success" if evaluation in {"good", "skipped"} else "warning",
                    "evaluate",
                )
                plan["trace"].append(eval_trace)
                yield _sse("trace", eval_trace)
        elif evaluation == "not_good" and not plan.get("web_search_eligible", True):
            skip_trace = _trace("Web search skipped because the question is outside the selected collection scope.", "warning", "scope_gate")
            plan["trace"].append(skip_trace)
            yield _sse("trace", skip_trace)
        elif (
            plan.get("web_search_eligible", True)
            and plan.get("web_search_available", False)
            and not plan.get("allow_web_search", False)
            and _question_may_need_web_search(question)
        ):
            plan["web_search_available"] = True
            plan["web_search_requires_approval"] = True
            approval_trace = _trace("Web search is available but requires user approval.", "warning", "web_search")
            plan["trace"].append(approval_trace)
            yield _sse("trace", approval_trace)
        else:
            plan["web_search_requires_approval"] = False

        yield _sse(
            "done",
            {
                "answer": final_answer,
                "sources": all_sources,
                "search_type": plan["search_type"],
                "evaluation": evaluation,
                "iteration_count": iteration_count,
                "retrieved_docs_count": plan["retrieved_docs_count"],
                "web_results_count": len(plan["web_sources"]),
                "confidence_level": plan["confidence_level"],
                "retrieval_mode": session.retrieval_mode,
                "retrieval_warning": session.retrieval_warning,
                "llm_provider": credentials.llm_provider,
                "llm_model": credentials.llm_model,
                "runtime_openai_active": credentials.runtime_openai_active,
                "llm_fallback_status": "not_used" if credentials.llm_provider == "openai" else "",
                "error_reason": "",
                "web_search_used": plan["web_search_used"],
                "web_search_available": plan.get("web_search_available", False),
                "web_search_requires_approval": plan.get("web_search_requires_approval", False),
                "collection_relevance": plan.get("collection_relevance"),
                "web_search_eligible": plan.get("web_search_eligible"),
                "trace_steps": plan["trace"],
            },
        )
        _safe_append_memory(session.session_id, session.collection_name, question, final_answer, all_sources)
    except Exception as exc:
        fallback_trace = _trace(
            "Streaming response failed; retrying with the standard response mode.",
            "warning",
            "generate",
        )
        yield _sse("trace", fallback_trace)
        try:
            fallback_credentials = credentials.as_local_stub() if credentials.should_fallback_to_local(exc) else credentials
            result = ask_session(
                session_id,
                question,
                answer_length,
                allow_web_search,
                fallback_credentials,
                collection_name,
            )
            if fallback_credentials.llm_provider == "local_stub" and credentials.llm_provider == "openai":
                result["llm_fallback_warning"] = "OpenAI unavailable; using local_stub for this answer."
                result["llm_fallback_status"] = "failed"
                result["error_reason"] = credentials.redact(exc).replace("\r", " ").replace("\n", " ").strip()[:180]
                logger.warning(
                    "Chat LLM fallback runtime_key_present=%s env_key_present=%s selected_llm_provider=%s selected_model=%s fallback_used=true",
                    bool(credentials.openai_api_key),
                    credentials.env_openai_api_key_present,
                    fallback_credentials.llm_provider,
                    fallback_credentials.llm_model,
                )
            trace_steps = [fallback_trace, *(result.get("trace") or [])]
            sources = result.get("sources", [])
            yield _sse(
                "sources",
                {
                    "sources": sources,
                    "retrieved_docs_count": result.get("retrieved_docs_count", 0),
                    "web_results_count": result.get("web_results_count", 0),
                    "confidence_level": result.get("confidence_level", "unknown"),
                    "retrieval_mode": result.get("retrieval_mode", "unknown"),
                    "retrieval_warning": result.get("retrieval_warning", ""),
                    "search_type": result.get("search_type", "hybrid"),
                    "web_search_used": result.get("web_search_used", False),
                    "web_search_available": result.get("web_search_available", False),
                    "web_search_requires_approval": result.get("web_search_requires_approval", False),
                    "collection_relevance": result.get("collection_relevance"),
                    "web_search_eligible": result.get("web_search_eligible"),
                    "trace_steps": trace_steps,
                },
            )
            yield _sse(
                "done",
                {
                    **result,
                    "sources": sources,
                    "trace_steps": trace_steps,
                    "streaming": False,
                    "response_mode": "standard_fallback",
                },
            )
        except Exception as fallback_exc:
            message = credentials.redact(fallback_exc)
            yield _sse("error", {"message": f"Streaming chat failed: {message}"})


def _sse(event: str, payload: dict) -> str:
    import json

    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _resolve_collection_name(collection_name: str) -> str:
    requested = (collection_name or "").strip()
    if requested and collection_exists(requested):
        return requested
    if collection_exists(DEFAULT_COLLECTION):
        return DEFAULT_COLLECTION
    registered = list_registered_collections(refresh=True)
    if registered:
        return registered[0]["collection_name"]
    return requested or DEFAULT_COLLECTION


def _fallback_session() -> RagSession | None:
    collection_name = _resolve_collection_name(DEFAULT_COLLECTION)
    if not collection_exists(collection_name):
        return None
    try:
        return select_existing_collection(
            session_id=f"default:{collection_name}",
            collection_name=collection_name,
            embedding_provider="huggingface",
        )
    except Exception:
        return None


def _safe_append_memory(
    session_id: str,
    collection_name: str,
    question: str,
    answer: str,
    sources: List[dict],
) -> None:
    try:
        append_memory(session_id, collection_name, question, answer, sources)
    except Exception:
        return


def _merge_documents(existing: List, incoming: List) -> List:
    merged = {}
    ordered = []
    for document in [*existing, *incoming]:
        metadata = document.metadata or {}
        key = metadata.get("chunk_id") or f"{metadata.get('file_name', '')}:{len(ordered)}:{document.page_content[:80]}"
        if key not in merged:
            ordered.append(key)
        merged[key] = document
    return [merged[key] for key in ordered]


def rebuild_bm25_index(collection_name: str) -> dict:
    collection_name = _resolve_collection_name(collection_name)
    vector_provider = get_vector_db()
    if not hasattr(vector_provider, "load_documents"):
        return {
            "success": False,
            "message": "Current vector DB provider cannot rebuild BM25 indexes.",
        }
    documents = vector_provider.load_documents(collection_name)
    if not documents:
        return {
            "success": False,
            "message": "Cannot rebuild BM25 index because chunk text is missing from Qdrant payload.",
        }
    save_bm25_index(collection_name, documents)
    for session in _SESSIONS.values():
        if session.collection_name == collection_name:
            session.documents = documents
            session.retrieval_mode = "dense + BM25 hybrid" if documents else "dense only"
            session.retrieval_warning = ""
    return {
        "success": True,
        "message": "BM25 index rebuilt.",
        "collection_name": collection_name,
        "chunk_count": len(documents),
        "bm25_ready": bm25_index_exists(collection_name),
    }


def _confidence_level(sources: List[ScoredDocument]) -> str:
    if not sources:
        return "none"
    best_score = max((source.final_score for source in sources), default=0.0)
    if best_score >= 0.70:
        return "high"
    if best_score >= 0.45:
        return "medium"
    return "low"

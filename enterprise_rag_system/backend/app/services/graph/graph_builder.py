from typing import Callable, Optional

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, StateGraph

from app.core.prompts import EVALUATE_PROMPT, GENERATE_PROMPT
from app.core.runtime_credentials import RuntimeCredentials
from app.services.graph.conditions import route_after_evaluation, route_after_grading
from app.services.graph.state import AgentState
from app.services.ingestion.pipeline import load_and_chunk_document
from app.services.llm.generation_service import get_chat_model
from app.services.retrieval.context_builder import build_context
from app.services.retrieval.hybrid_search import HybridRetriever
from app.services.retrieval.relevance_grader import grade_documents as grade_docs
from app.services.retrieval.web_fallback import run_web_search
from app.services.vectordb.factory import get_vector_db


def build_agent(
    file_path: str,
    collection_name: str,
    chunk_size: int,
    chunk_overlap: int,
    k: int,
    max_iterations: int,
    openai_api_key: str = "",
    tavily_api_key: str = "",
):
    credentials = RuntimeCredentials.from_values(
        openai_api_key=openai_api_key,
        tavily_api_key=tavily_api_key,
    )
    credentials.require_chat_credentials()

    chunks = load_and_chunk_document(
        file_path=file_path,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        collection_name=collection_name,
        embedding_provider="huggingface",
    )
    vectorstore = get_vector_db().build_vectorstore(chunks, collection_name, "huggingface", credentials)
    hybrid_retriever = HybridRetriever(vectorstore, chunks, k)
    llm = get_chat_model(streaming=True, credentials=credentials)

    def retrieve(state: AgentState) -> dict:
        docs = hybrid_retriever.invoke(state["question"])
        return {
            "documents": [doc.page_content for doc in docs],
            "search_type": "vectorstore",
        }

    def grade_documents(state: AgentState) -> dict:
        return {
            "documents": grade_docs(
                question=state["question"],
                documents=state["documents"],
                llm=llm,
            )
        }

    def generate(state: AgentState) -> dict:
        chain = ChatPromptTemplate.from_template(GENERATE_PROMPT) | llm | StrOutputParser()
        answer = chain.invoke(
            {
                "context": build_context(state["documents"]),
                "question": state["question"],
                "confidence_level": "medium",
                "answer_length": "Medium: 180-250 words",
            }
        )
        return {
            "answer": answer,
            "iteration_count": state.get("iteration_count", 0) + 1,
        }

    def evaluate_answer(state: AgentState) -> dict:
        if state.get("iteration_count", 1) >= max_iterations:
            return {"answer": state["answer"], "evaluation": "good"}

        chain = ChatPromptTemplate.from_template(EVALUATE_PROMPT) | llm | StrOutputParser()
        result = chain.invoke(
            {
                "question": state["question"],
                "context": build_context(state["documents"]),
                "answer": state["answer"],
            }
        )
        lowered = result.strip().lower()
        quality = "good" if "good" in lowered and "not_good" not in lowered else "not_good"
        return {"answer": state["answer"], "evaluation": quality}

    def web_search(state: AgentState) -> dict:
        return {
            "documents": run_web_search(state["question"], credentials=credentials),
            "search_type": "web_search",
        }

    workflow = StateGraph(AgentState)
    workflow.add_node("retrieve", retrieve)
    workflow.add_node("grade_documents", grade_documents)
    workflow.add_node("generate", generate)
    workflow.add_node("evaluate", evaluate_answer)
    workflow.add_node("web_search", web_search)

    workflow.set_entry_point("retrieve")
    workflow.add_edge("retrieve", "grade_documents")
    workflow.add_conditional_edges(
        "grade_documents",
        route_after_grading,
        {"generate": "generate", "web_search": "web_search"},
    )
    workflow.add_edge("web_search", "generate")
    workflow.add_edge("generate", "evaluate")
    workflow.add_conditional_edges(
        "evaluate",
        lambda state: route_after_evaluation(state, max_iterations),
        {"end": END, "web_search": "web_search"},
    )

    return workflow.compile()


def run_agent(
    app,
    question: str,
    trace_callback: Optional[Callable[[str, str], None]] = None,
    stream_callback: Optional[Callable[[str], None]] = None,
) -> dict:
    def trace(message: str, kind: str = "info") -> None:
        if trace_callback:
            trace_callback(message, kind)

    initial_state = {
        "question": question,
        "documents": [],
        "answer": "",
        "iteration_count": 0,
        "search_type": "",
        "evaluation": None,
    }
    merged = {**initial_state}

    trace("Starting agent", "info")
    for event in app.stream(initial_state):
        for node_name, node_output in event.items():
            merged.update(node_output)
            if node_name == "retrieve":
                trace("Searching knowledge base with hybrid retrieval", "info")
            elif node_name == "grade_documents":
                trace(f"Graded {len(node_output.get('documents', []))} chunks", "success")
            elif node_name == "web_search":
                trace("Using Tavily web fallback", "warning")
            elif node_name == "generate":
                trace("Generating answer", "info")
                if stream_callback:
                    for char in node_output.get("answer", ""):
                        stream_callback(char)
            elif node_name == "evaluate":
                evaluation = node_output.get("evaluation", "?")
                trace(f"Quality: {evaluation}", "success" if evaluation == "good" else "warning")

    trace(
        f"Done ({merged.get('search_type', '?')}, {merged.get('iteration_count', 1)} iteration)",
        "success",
    )
    return merged

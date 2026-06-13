from app.core.runtime_credentials import RuntimeCredentials


def run_web_search_sources(
    question: str,
    max_results: int = 3,
    credentials: RuntimeCredentials | None = None,
) -> list[dict]:
    from langchain_community.tools.tavily_search import TavilySearchResults

    credentials = credentials or RuntimeCredentials()
    tool = TavilySearchResults(
        api_key=credentials.require_tavily_api_key(),
        max_results=max_results,
    )
    results = tool.invoke(question)
    sources = []
    for index, item in enumerate(results, start=1):
        if isinstance(item, dict):
            content = item.get("content") or item.get("snippet") or item.get("description") or str(item)
            sources.append(
                {
                    "content": str(content),
                    "page_content": str(content),
                    "title": item.get("title") or f"Web result {index}",
                    "url": item.get("url") or item.get("source") or "",
                    "source": item.get("url") or item.get("title") or f"Web result {index}",
                    "source_type": "web_search",
                    "retrieval_type": "web_search",
                    "score": item.get("score", ""),
                    "metadata": {
                        "file_name": item.get("url") or item.get("title") or f"Web result {index}",
                        "section_title": "Web Search",
                        "collection_name": "web_search",
                        "source_type": "web_search",
                        "url": item.get("url") or "",
                    },
                }
            )
        else:
            content = str(item)
            sources.append(
                {
                    "content": content,
                    "page_content": content,
                    "title": f"Web result {index}",
                    "source": f"Web result {index}",
                    "source_type": "web_search",
                    "retrieval_type": "web_search",
                    "metadata": {
                        "file_name": f"Web result {index}",
                        "section_title": "Web Search",
                        "collection_name": "web_search",
                        "source_type": "web_search",
                    },
                }
            )
    return sources


def run_web_search(
    question: str,
    max_results: int = 3,
    credentials: RuntimeCredentials | None = None,
) -> list[str]:
    return [item["content"] for item in run_web_search_sources(question, max_results, credentials)]

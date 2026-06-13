import streamlit as st


def render_trace(trace_steps):
    st.markdown("#### Agent Trace")
    if not trace_steps:
        st.caption("Trace will appear after your first question.")
        return

    for step in trace_steps:
        kind = step.get("kind", "info")
        message = step.get("message", "")
        st.markdown(f'<div class="trace-item {kind}">{message}</div>', unsafe_allow_html=True)


def render_sources(sources, compact: bool = False):
    if not compact:
        st.markdown("#### Sources")
    if not sources:
        if not compact:
            st.caption("Sources will appear here after a response.")
        return

    with st.expander("Sources", expanded=not compact):
        for index, source in enumerate(sources, start=1):
            metadata = source.get("metadata", {}) or {}
            file_name = source.get("file_name") or metadata.get("file_name") or "Unknown document"
            chunk_id = source.get("chunk_id") or metadata.get("chunk_id") or "Unknown"
            page_number = source.get("page_number") or metadata.get("page_number") or "n/a"
            section_title = source.get("section_title") or metadata.get("section_title") or "Document"
            collection_name = source.get("collection_name") or metadata.get("collection_name") or "Unknown collection"
            score = source.get("retrieval_score", source.get("score", 0))
            retrieval_type = source.get("retrieval_type") or "hybrid"
            confidence = source.get("confidence_level") or "unknown"

            st.markdown(f"**Source {index}: {file_name}**")
            st.caption(
                " | ".join(
                    [
                        f"Chunk: {chunk_id}",
                        f"Page: {page_number}",
                        f"Section: {section_title}",
                        f"Collection: {collection_name}",
                        f"Score: {score}",
                        f"Retrieval: {retrieval_type}",
                        f"Confidence: {confidence}",
                    ]
                )
            )
            st.write(source.get("content") or source.get("page_content") or "")
            if index < len(sources):
                st.divider()

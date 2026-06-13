import streamlit as st


def render_upload_status():
    session_id = st.session_state.get("session_id")
    collection = st.session_state.get("collection_name")
    filename = st.session_state.get("filename")

    if not session_id:
        st.info("Build a knowledge base from the sidebar to start chatting.")
        return

    st.success("Knowledge base ready")
    st.markdown(
        f"""
        <div class="status-grid">
          <div><span>Session</span><strong>{session_id[:10]}...</strong></div>
          <div><span>Collection</span><strong>{collection}</strong></div>
          <div><span>Document</span><strong>{filename}</strong></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


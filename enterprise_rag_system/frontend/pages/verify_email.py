import streamlit as st

from components.auth_panel import render_verification_page
from components.layout import init_session_state, load_styles


def main() -> None:
    st.set_page_config(page_title="Verify Email | Enterprise RAG", page_icon="R", layout="centered")
    load_styles()
    init_session_state()
    render_verification_page("verify_page")


if __name__ == "__main__":
    main()

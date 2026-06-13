from pathlib import Path

import streamlit as st


def render_uploaded_files_panel() -> None:
    st.markdown("View and delete locally uploaded files.")
    _init_delete_state()
    upload_dir = _find_upload_dir()
    if not upload_dir:
        st.info("No uploads directory found yet.")
        return

    files = sorted(
        [path for path in upload_dir.iterdir() if path.is_file() and path.name != ".gitkeep"],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not files:
        st.info("No uploaded files found.")
        _clear_delete_state()
        return

    rows = [
        {
            "file_name": path.name,
            "size_kb": round(path.stat().st_size / 1024, 2),
            "modified": _format_mtime(path),
        }
        for path in files
    ]
    st.dataframe(rows, width="stretch", hide_index=True)

    if st.session_state.get("upload_delete_message"):
        st.success(st.session_state.upload_delete_message)
        st.session_state.upload_delete_message = ""

    file_names = [path.name for path in files]
    current_selection = st.session_state.get("selected_upload_file")
    selected_index = file_names.index(current_selection) if current_selection in file_names else 0
    selected_name = st.selectbox("Uploaded files", file_names, index=selected_index, key="selected_upload_file")
    if not selected_name:
        st.info("Select an uploaded file to view or delete.")
        return

    selected = upload_dir / selected_name
    if not selected.exists():
        st.warning("Selected file no longer exists. Refreshing file list.")
        _clear_delete_state()
        st.rerun()

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Preview File", width="stretch"):
            _preview_file(selected)
    with col2:
        if st.button("Delete selected file", width="stretch"):
            st.session_state.delete_upload_requested = True
            st.session_state.pending_delete_upload = selected_name

    if st.session_state.delete_upload_requested:
        pending_name = st.session_state.get("pending_delete_upload")
        pending_path = upload_dir / pending_name if pending_name else None
        if not pending_name:
            st.warning("No file is pending deletion.")
            _clear_delete_state()
            return
        st.warning(f"Delete local uploaded file '{pending_name}'? This will not delete any Qdrant collection.")
        confirm_col, cancel_col = st.columns(2)
        with confirm_col:
            if st.button("Confirm Delete", key="confirm_delete_upload_btn", width="stretch"):
                try:
                    if not pending_path or not pending_path.exists():
                        st.session_state.upload_delete_message = "Selected file was already removed."
                    else:
                        pending_path.unlink()
                        st.session_state.upload_delete_message = "File deleted successfully."
                    _clear_delete_state(keep_message=True)
                    st.rerun()
                except OSError as exc:
                    st.error(f"Could not delete file: {exc}")
        with cancel_col:
            if st.button("Cancel", key="cancel_delete_upload_btn", width="stretch"):
                _clear_delete_state()
                st.rerun()

    st.caption("Deleting a local uploaded file does not delete any Qdrant collection or vectors.")


def _init_delete_state() -> None:
    defaults = {
        "selected_upload_file": None,
        "delete_upload_requested": False,
        "pending_delete_upload": None,
        "delete_upload_confirmed": False,
        "upload_delete_message": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _clear_delete_state(keep_message: bool = False) -> None:
    st.session_state.delete_upload_requested = False
    st.session_state.pending_delete_upload = None
    st.session_state.delete_upload_confirmed = False
    if not keep_message:
        st.session_state.upload_delete_message = ""


def _find_upload_dir() -> Path | None:
    frontend_dir = Path(__file__).resolve().parents[1]
    project_dir = frontend_dir.parent
    candidates = [
        project_dir / "backend" / "data" / "uploads",
        project_dir / "backend" / "app" / "data" / "uploads",
        project_dir / "app" / "data" / "uploads",
        project_dir / "data" / "uploads",
    ]
    for path in candidates:
        if path.exists() and path.is_dir():
            return path
    return None


def _format_mtime(path: Path) -> str:
    from datetime import datetime

    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")


def _preview_file(path: Path) -> None:
    if path.suffix.lower() not in {".txt", ".csv", ".md"}:
        st.info("Preview is available for txt, csv, and md files.")
        return
    if path.stat().st_size > 512_000:
        st.warning("File is too large for safe preview.")
        return
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        st.error(f"Could not read file: {exc}")
        return
    st.text_area("Preview", text[:10000], height=280)

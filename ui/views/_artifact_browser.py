"""
Reusable MLflow-style two-panel file browser.

Layout: file list on the left, content preview on the right with an
MLflow-style header (full path + size). Used by both the Pipeline Config
Viewer (Run Experiment page) and the Artifact Viewer (Experiment Detail
page) so the layout lives in exactly one place.

Implementation uses Approach A: st.columns + st.button. No extra
dependency. Approach B (streamlit-tree-select) remains an optional upgrade
if a genuinely collapsible hierarchy is ever needed; both current viewers
are flat single-level lists, so Approach A is sufficient.

Layer note: this module lives in ui/ and imports nothing below the UI
layer here. The page-specific builders pass in lazy callables, so this
module never reaches into pipelines/ or storage/ directly. It never
deserializes binary artifacts and never reads files itself; callers supply
loaders that have already validated their own paths.
"""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

_PREVIEW_MAX_LINES = 800
_LOG_TAIL_LINES = 500


def format_size(num_bytes: int) -> str:
    """Human-readable byte size."""
    n = float(num_bytes)
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{int(n)} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


# ── Lazy loader factories (used by the artifact viewer) ────────────────────
# Defined as factories to avoid the classic loop-closure late-binding bug.

def make_json_loader(path: Path):
    def _load() -> str:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return json.dumps(data, indent=2, ensure_ascii=False)
    return _load


def make_text_loader(path: Path):
    def _load() -> str:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    return _load


def make_bytes_reader(path: Path):
    def _read() -> bytes:
        return Path(path).read_bytes()
    return _read


# ── The reusable two-panel browser ─────────────────────────────────────────

def render_file_browser(files: dict, state_key: str) -> None:
    """Render the two-panel file browser.

    files: ordered mapping ``display_name -> spec``. Spec keys:
        icon          (str)   leading icon in the file list
        full_path     (str)   shown in the right-panel header
        language      (str)   st.code language for text preview
        loader        (callable -> str)   lazy text content (text specs)
        binary        (bool)  if True: no preview, show size + download
        size          (int)   byte size (binary specs; for the header)
        read_bytes    (callable -> bytes)  lazy byte reader (binary download)
        download_name (str)   filename for the download button
        tail          (bool)  if True and large, show last lines (logs)
        note          (str)   optional caption note
    state_key: unique session_state key so two browsers never collide.
    """
    if not files:
        st.info("Tidak ada berkas untuk ditampilkan.")
        return

    names = list(files.keys())
    if st.session_state.get(state_key) not in names:
        st.session_state[state_key] = names[0]

    col_left, col_right = st.columns([1, 2])
    with col_left:
        st.markdown("**Files**")
        for name in names:
            spec = files[name]
            selected = st.session_state[state_key] == name
            if st.button(
                name,
                key=f"{state_key}__btn__{name}",
                use_container_width=True,
                type="primary" if selected else "secondary",
            ):
                st.session_state[state_key] = name
                st.rerun()

    with col_right:
        current = st.session_state[state_key]
        _render_preview(files[current], current, state_key)


def _render_preview(spec: dict, name: str, state_key: str) -> None:
    full_path = spec.get("full_path", name)

    if spec.get("binary"):
        size = int(spec.get("size", 0))
        st.caption(f"**Full Path:** `{full_path}`")
        st.caption(f"**Size:** {format_size(size)} · binary artifact (joblib)")
        st.info("Berkas biner tidak dapat di-preview. Gunakan tombol unduh di bawah.")
        _download_binary(spec, name, state_key)
        return

    try:
        content = spec["loader"]()
        if content is None:
            content = ""
    except Exception as e:
        st.caption(f"**Full Path:** `{full_path}`")
        st.error(f"Tidak dapat membaca berkas: {e}")
        return

    lines = content.splitlines()
    n_lines = len(lines)
    size_bytes = len(content.encode("utf-8", errors="replace"))
    st.caption(f"**Full Path:** `{full_path}`")
    st.caption(f"**Size:** {format_size(size_bytes)} · {n_lines} lines")
    if spec.get("note"):
        st.caption(spec["note"])

    if n_lines > _PREVIEW_MAX_LINES:
        if spec.get("tail"):
            shown = "\n".join(lines[-_LOG_TAIL_LINES:])
            st.caption(f"Output besar — menampilkan {_LOG_TAIL_LINES} baris terakhir.")
        else:
            shown = "\n".join(lines[:_PREVIEW_MAX_LINES])
            st.caption(f"Output besar — menampilkan {_PREVIEW_MAX_LINES} baris pertama.")
    else:
        shown = content

    st.code(shown, language=spec.get("language", "text"))

    # Full-content download (handy when the preview above is truncated).
    # Content is already in memory, so this adds no extra file read.
    st.download_button(
        f"Download {name}",
        data=content,
        file_name=spec.get("download_name", name),
        key=f"{state_key}__dltxt__{name}",
    )


def _download_binary(spec: dict, name: str, state_key: str) -> None:
    read_bytes = spec.get("read_bytes")
    if read_bytes is None:
        return
    buf_key = f"{state_key}__bytes__{name}"
    # Two-step: read bytes into session_state only when the user asks, so a
    # large model.pkl (tens of MB) is never read on every rerun.
    if st.button(f"Siapkan unduhan {name}", key=f"{state_key}__prep__{name}"):
        try:
            st.session_state[buf_key] = read_bytes()
        except Exception as e:
            st.error(f"Gagal menyiapkan unduhan: {e}")
    if st.session_state.get(buf_key) is not None:
        st.download_button(
            f"Download {name}",
            data=st.session_state[buf_key],
            file_name=spec.get("download_name", name),
            key=f"{state_key}__dl__{name}",
        )

"""Tests for the "Add Pipeline & Dataset" page helpers (ui/views/contribute.py).

Only pure logic is exercised — the algorithm lookup (read from the REAL
registry, never hardcoded) and the dataset-name guard. Panel rendering is
verified separately; the profile data itself is covered by
tests/test_dataset_diagnostics.py.
"""
import io
import re

import pytest

from config.pipeline_registry import PIPELINE_REGISTRY
from config.research_attribution import (
    RESEARCH_ATTRIBUTION, get_research_display_name, get_research_short_label,
)
from contracts.dataset_schemas import supported_datasets
from ui.views.contribute import (
    DATASET_EXTENSIONS, _algorithms_for, _dataset_label, safe_dataset_name,
)


# ── attributed names: short label for tight spots ─────────────────────────

@pytest.mark.parametrize("dtype", supported_datasets())
def test_short_label_is_attributed_and_not_a_raw_id(dtype):
    label = get_research_short_label(dtype)
    assert label != dtype                      # bukan ID mentah
    assert " — " in label                      # "<kredit> — <nama pendek>"
    credit, short = label.split(" — ", 1)
    assert credit and short
    # Kredit diturunkan dari display_name yang sama — bukan string kedua.
    assert RESEARCH_ATTRIBUTION[dtype]["display_name"].startswith(credit)


def test_short_labels_match_the_expected_wording():
    assert get_research_short_label("HIKARI2021") == "Rayyan (2024) — HIKARI2021"
    assert get_research_short_label("EVE_SURICATA") == "Niswar dkk. (2026) — EVE Suricata"


def test_short_label_is_shorter_than_the_full_display_name():
    for dtype in supported_datasets():
        assert len(get_research_short_label(dtype)) < len(get_research_display_name(dtype))


def test_short_label_falls_back_for_an_unknown_type():
    assert get_research_short_label("NOT_A_TYPE") == "NOT_A_TYPE"


def test_dataset_label_maps_types_and_passes_through_the_other_option():
    from ui.views.contribute import _OTHER_DATASET_OPTION

    assert _dataset_label("HIKARI2021") == get_research_short_label("HIKARI2021")
    assert _dataset_label(_OTHER_DATASET_OPTION) == _OTHER_DATASET_OPTION


# ── dataset_type → algorithms, straight from the registry ─────────────────

@pytest.mark.parametrize("dtype", supported_datasets())
def test_every_dataset_type_maps_to_its_registry_algorithms(dtype):
    expected = [info["algorithm"] for pid, info in PIPELINE_REGISTRY.items()
                if info["dataset_type"] == dtype]
    assert _algorithms_for(dtype) == expected
    assert len(expected) == len(set(expected)), "algoritma duplikat di registry"


def test_hikari_and_eve_algorithm_counts_match_the_registry():
    """Angka yang ditampilkan UI ("dapat dijalankan pada N algoritma") harus
    berasal dari registry, bukan angka tetap di kode."""
    counts = {dt: len(_algorithms_for(dt)) for dt in supported_datasets()}
    from_registry = {}
    for info in PIPELINE_REGISTRY.values():
        from_registry[info["dataset_type"]] = from_registry.get(info["dataset_type"], 0) + 1
    assert counts == from_registry


def test_unknown_dataset_type_has_no_algorithms():
    assert _algorithms_for("NOT_A_TYPE") == []


# ── dataset filename guard ────────────────────────────────────────────────

@pytest.mark.parametrize("good", ["data.csv", "eve_sample.jsonl",
                                  "HIKARI-2021.ndjson", "a.b_c-1.json"])
def test_safe_dataset_names_are_accepted(good):
    assert safe_dataset_name(good) == good


@pytest.mark.parametrize("bad", [
    "../evil.csv", "..\\evil.csv", "/etc/passwd.csv", "C:\\data\\x.csv",
    "sub/dir/data.csv", "script.py", "archive.zip", "", "..", "no ext",
    "data.csv.exe", "spaced name.csv",
])
def test_unsafe_or_wrong_type_dataset_names_are_refused(bad):
    assert safe_dataset_name(bad) is None


def test_accepted_extensions_cover_both_research_pipelines():
    assert ".csv" in DATASET_EXTENSIONS          # HIKARI2021
    assert ".ndjson" in DATASET_EXTENSIONS and ".jsonl" in DATASET_EXTENSIONS  # EVE


# ── page naming stays consistent with the navigation ──────────────────────

def test_page_title_matches_the_navigation_entry():
    import ast
    from pathlib import Path

    import ui.views.contribute as contrib

    app_src = Path(contrib.__file__).resolve().parents[1] / "app.py"
    app_text = app_src.read_text(encoding="utf-8")
    page_src = Path(contrib.__file__).read_text(encoding="utf-8")

    assert '"Add Pipeline & Dataset"' in app_text          # _PAGES + dispatch
    assert app_text.count("Add Pipeline & Dataset") >= 2
    assert 'st.title("Add Pipeline & Dataset")' in page_src
    # Tidak ada sisa nama lama di navigasi maupun halaman.
    assert "Tambah Pipeline & Dataset" not in app_text
    assert ast.parse(page_src) is not None


# ── upload limit, chunked writes, and the temp-file diagnosis ─────────────

class _FakeUpload(io.BytesIO):
    """Stands in for Streamlit's UploadedFile (name/size + file-like reads)."""

    def __init__(self, name: str, data: bytes, *, declared_size: int | None = None):
        super().__init__(data)
        self.name = name
        self.size = len(data) if declared_size is None else declared_size


def test_upload_limit_is_five_gigabytes():
    from ui.views.contribute import MAX_DATASET_UPLOAD_BYTES

    assert MAX_DATASET_UPLOAD_BYTES == 5 * 1024 ** 3


def test_streamlit_config_matches_the_code_limit():
    """server.maxUploadSize (MB) harus >= batas di kode, kalau tidak Streamlit
    menolak lebih dulu di sisi server."""
    from pathlib import Path

    import ui.views.contribute as contrib
    from ui.views.contribute import MAX_DATASET_UPLOAD_BYTES

    cfg = Path(contrib.__file__).resolve().parents[2] / ".streamlit" / "config.toml"
    assert cfg.exists(), "-.streamlit/config.toml belum ada"
    text = cfg.read_text(encoding="utf-8")
    match = re.search(r"maxUploadSize\s*=\s*(\d+)", text)
    assert match, text
    assert int(match.group(1)) * 1024 * 1024 >= MAX_DATASET_UPLOAD_BYTES


def test_oversize_upload_is_measured_without_reading_the_bytes():
    """Ukuran diambil dari atribut `size` — berkas 5 GB tiruan tidak pernah
    benar-benar dibuat maupun dibaca."""
    from ui.views.contribute import MAX_DATASET_UPLOAD_BYTES, upload_size

    huge = _FakeUpload("big.csv", b"a,b\n1,2\n",
                       declared_size=MAX_DATASET_UPLOAD_BYTES + 1)
    assert upload_size(huge) > MAX_DATASET_UPLOAD_BYTES


def test_upload_size_falls_back_to_seek_when_size_is_missing():
    from ui.views.contribute import upload_size

    stub = io.BytesIO(b"12345")
    assert upload_size(stub) == 5
    assert stub.tell() == 0                    # posisi dikembalikan


def test_copy_stream_writes_in_chunks_without_duplicating_bytes(tmp_path):
    from ui.views.contribute import copy_stream

    payload = b"".join(f"row{i}\n".encode() for i in range(5000))
    src = _FakeUpload("data.csv", payload)
    target = tmp_path / "out.csv"

    written, truncated = copy_stream(src, target, chunk=1024)
    assert truncated is False
    assert written == len(payload)
    assert target.read_bytes() == payload


def test_copy_stream_prefix_stops_on_a_line_boundary(tmp_path):
    from ui.views.contribute import copy_stream

    payload = b"".join(f"row{i:04d}\n".encode() for i in range(1000))
    src = _FakeUpload("data.csv", payload)
    target = tmp_path / "prefix.csv"

    written, truncated = copy_stream(src, target, max_bytes=500, chunk=128)
    assert truncated is True
    assert written < len(payload)
    data = target.read_bytes()
    assert data.endswith(b"\n")                # tidak ada baris terpenggal
    assert payload.startswith(data)


def test_diagnosis_uses_a_temp_file_and_never_touches_storage_datasets(tmp_path, monkeypatch):
    """Diagnosa berjalan SEBELUM penyimpanan: storage/datasets/ harus tetap
    kosong, dan berkas sementaranya tidak boleh tertinggal."""
    import pandas as pd

    import ui.views.contribute as contrib
    from contracts.dataset_schemas import HIKARI2021_SCHEMA

    datasets = tmp_path / "datasets"
    tmpdir = tmp_path / "_upload_tmp"
    datasets.mkdir()
    monkeypatch.setattr(contrib, "UPLOAD_TMP_DIR", tmpdir)
    monkeypatch.setattr(contrib, "_dataset_target_path",
                        lambda name: datasets / name)
    import config.settings as _s
    monkeypatch.setattr(_s, "BASE_DIR", tmp_path)
    monkeypatch.setattr(_s, "DATASETS_DIR", str(datasets))
    monkeypatch.setattr(contrib.st, "session_state", {})

    cols = HIKARI2021_SCHEMA["expected_columns"]
    frame = {c: [0.0, 1.0] for c in cols if c != "Label"}
    frame["Label"] = [0, 1]
    payload = pd.DataFrame(frame)[cols].to_csv(index=False).encode("utf-8")

    diag = contrib._diagnose_uploaded(_FakeUpload("up.csv", payload), "up.csv")

    assert diag is not None
    assert diag["compatible_types"] == ["HIKARI2021"]
    assert list(datasets.iterdir()) == []                   # tidak ada yang disimpan
    assert not tmpdir.exists() or list(tmpdir.iterdir()) == []   # tidak ada sisa temp


def test_diagnosis_result_is_reused_for_the_same_upload(tmp_path, monkeypatch):
    """Rerun berikutnya memakai hasil di session_state — tanpa membaca ulang."""
    import ui.views.contribute as contrib

    calls = {"n": 0}

    def _fake_diagnose_all(path):
        calls["n"] += 1
        return {"profile": {}, "results": {}, "compatible_types": [], "error": None}

    import orchestrator.dataset_diagnostics as dd
    monkeypatch.setattr(dd, "diagnose_all", _fake_diagnose_all)
    monkeypatch.setattr(contrib, "UPLOAD_TMP_DIR", tmp_path / "_tmp")
    monkeypatch.setattr(contrib.st, "session_state", {})

    up = _FakeUpload("x.csv", b"a,b\n1,2\n")
    contrib._diagnose_uploaded(up, "x.csv")
    contrib._diagnose_uploaded(up, "x.csv")
    assert calls["n"] == 1


def test_server_tab_reads_the_same_folder_listing_as_run_experiment():
    """Jalur server memakai pembacaan folder milik Run Experiment, bukan
    implementasi kedua."""
    import ast
    from pathlib import Path

    import ui.views.contribute as contrib

    tree = ast.parse(Path(contrib.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "ui.views.run_experiment":
            imported.update(a.name for a in node.names)
    assert "_all_dataset_options" in imported
    assert "_diagnose_selected" in imported          # diagnosa ber-cache


def test_dataset_flow_has_no_research_pipeline_dropdown():
    """Dropdown "untuk pipeline yang mana?" dicabut — platform yang menyimpulkan."""
    src = _page_source()
    flow = src.split("def _render_dataset_flow()")[1].split("\ndef _render_dataset_upload_tab")[0]
    assert "selectbox" not in flow
    assert "contrib_ds_type" not in src


# ── typography rules ──────────────────────────────────────────────────────

def _page_source() -> str:
    from pathlib import Path

    import ui.views.contribute as contrib

    return Path(contrib.__file__).read_text(encoding="utf-8")


def test_every_dataset_type_selectbox_shows_attributed_labels():
    """Dropdown tidak boleh menampilkan ID mentah: setiap selectbox atas
    dataset_type wajib memakai format_func."""
    import ast

    tree = ast.parse(_page_source())
    boxes = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "selectbox"]
    assert boxes, "tidak ada selectbox terdeteksi — pemindaian salah"
    for call in boxes:
        kwargs = {kw.arg for kw in call.keywords}
        assert "format_func" in kwargs, ast.dump(call)[:120]


def test_file_sizes_are_human_formatted_not_raw_bytes():
    """Ukuran berkas tampil "288.4 MB", bukan "302.425.555 byte"."""
    src = _page_source()
    assert "format_size(" in src
    code = "\n".join(ln for ln in src.splitlines()
                     if ln.strip() and not ln.strip().startswith("#"))
    assert ":,} byte" not in code
    assert ":,} byte" not in code.replace(" ", "")


def test_widget_labels_are_short_not_sentences():
    """Label widget pendek; keterangan panjang pindah ke help=/caption."""
    import ast

    tree = ast.parse(_page_source())
    labelled = ("text_input", "selectbox", "text_area", "file_uploader")
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in labelled and node.args):
            label = node.args[0]
            if isinstance(label, ast.Constant) and isinstance(label.value, str):
                assert len(label.value) <= 24, label.value
                assert "?" not in label.value, label.value


def test_big_blocks_are_separated_by_dividers():
    src = _page_source()
    assert src.count("st.divider()") >= 4
    code = "\n".join(ln for ln in src.splitlines()
                     if ln.strip() and not ln.strip().startswith("#"))
    assert 'st.markdown("---")' not in code       # satu mekanisme pemisah saja


def test_factual_notes_are_not_dropped_by_the_typography_pass():
    """Info faktual wajib tetap ada setelah dirapikan."""
    src = _page_source()
    assert "belum aktif" in src                    # valid ≠ aktif
    assert "berkas tidak dimuat" in src            # catatan sampel
    assert "Batas unggah" in src                   # batas ukuran
    assert "_action_sentence" in src               # tindakan "Agar cocok…"
    assert "_cause_sentence" in src                # penyebab utama
    assert "tidak menimpa dataset" in src          # tolak timpa


def test_choice_boxes_have_no_leading_blurb():
    """Kalimat pembuka lama dihapus dan tidak diganti kalimat panjang lain."""
    from pathlib import Path

    import ui.views.contribute as contrib

    src = Path(contrib.__file__).read_text(encoding="utf-8")
    assert "Pilih jenis kontribusi" not in src
    body = src.split("def _render_choice_boxes()")[1].split("def ")[0]
    assert "st.caption(" not in body.split("cols = st.columns(2)")[0]

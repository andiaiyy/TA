"""Tests for the pipeline-upload UI layer (ui/components/pipeline_upload.py).

Only the PURE layer is tested — ``review_upload`` (bytes → payload siap-tampil),
the check grouping, the staging-name guard, and the staging write. No Streamlit
runtime is needed, and no uploaded source is ever imported or executed: the
hostile samples below are inert strings handed to the static validator.

Validator behaviour itself is covered by tests/test_pipeline_validator.py.
"""
from pathlib import Path

import pytest

from ui.components.pipeline_upload import (
    GROUP_SECURITY, GROUP_STRUCTURE, MAX_UPLOAD_BYTES, PLACEHOLDER,
    REGISTRY_FIELDS, SECURITY_CHECK_NAMES, STAGING_DIR, build_registry_snippet,
    classify_check, decode_upload, extract_registry_metadata, review_upload,
    safe_staging_name, save_to_staging,
)

# Identitas berhak-unggah untuk aksi staging (izinnya diuji terpisah di
# tests/test_permissions.py).
CONTRIBUTOR = {"username": "rina", "role": "contributor"}

VALID_SOURCE = '''
from typing import Optional

from sklearn.ensemble import RandomForestClassifier

from pipelines.base import BasePipeline, ProgressCallback
from contracts.pipeline_contracts import PipelineInput, PipelineResult


class MyPipeline(BasePipeline):

    def run(self, pipeline_input: PipelineInput,
            progress: Optional[ProgressCallback] = None) -> PipelineResult:
        clf = RandomForestClassifier(n_estimators=10, random_state=42)
        return clf

    def get_info(self) -> dict:
        return {
            "paper": "Contoh (2026)",
            "algorithm": "Random Forest",
            "preprocessing_steps": ["scaling"],
            "feature_selection": "None",
            "fixed_params": {"n_estimators": 10},
            "train_test_split": {"test_size": 0.3},
        }
'''

HOSTILE_SOURCE = "import subprocess\nsubprocess.run(['whoami'])\n" + VALID_SOURCE


# ── happy path ────────────────────────────────────────────────────────────

def test_valid_upload_produces_a_valid_verdict():
    result = review_upload(VALID_SOURCE.encode("utf-8"), "my_pipeline.py")
    assert result["ok"] is True
    assert result["verdict"] == "valid"
    assert result["cause"] == ""                       # tidak ada kegagalan
    assert result["report"]["valid"] is True
    assert result["filename"] == "my_pipeline.py"


def test_payload_groups_checks_into_structure_and_security():
    result = review_upload(HOSTILE_SOURCE.encode("utf-8"), "bad.py")
    groups = result["groups"]
    assert set(groups) == {GROUP_STRUCTURE, GROUP_SECURITY}
    assert any(c["name"] == "import terlarang" for c in groups[GROUP_SECURITY])
    assert any(c["name"] == "kelas pipeline" for c in groups[GROUP_STRUCTURE])
    # Setiap check masuk tepat satu grup, tidak ada yang hilang.
    total = len(groups[GROUP_STRUCTURE]) + len(groups[GROUP_SECURITY])
    assert total == len(result["report"]["checks"])


def test_every_check_name_the_validator_emits_is_classified():
    """Grup 'Struktur' adalah default, jadi nama baru tidak pernah hilang —
    tetapi nama keamanan harus benar-benar terklasifikasi sebagai Keamanan."""
    samples = [
        VALID_SOURCE,
        HOSTILE_SOURCE,
        "import csv\n" + VALID_SOURCE,        # netral, di luar allowlist → warn
        VALID_SOURCE + "\nx = eval('1')\n",
        VALID_SOURCE + "\nleak = ().__class__.__subclasses__()\n",
        VALID_SOURCE + "\nf = open('x', 'w')\n",
        VALID_SOURCE + "\nv = getattr(obj, 'a')\n",
        "class NotAPipeline:\n    pass\n",
    ]
    seen = set()
    for src in samples:
        result = review_upload(src.encode("utf-8"), "s.py")
        seen.update(c["name"] for c in result["report"]["checks"])
    assert SECURITY_CHECK_NAMES <= seen, "sampel belum memicu semua check keamanan"
    for name in seen:
        assert classify_check(name) in (GROUP_STRUCTURE, GROUP_SECURITY)


# ── invalid uploads: the cause line ───────────────────────────────────────

def test_security_failure_becomes_the_primary_cause():
    result = review_upload(HOSTILE_SOURCE.encode("utf-8"), "bad.py")
    assert result["verdict"] == "invalid"
    assert "subprocess" in result["cause"]
    assert "baris" in result["cause"]                  # lokasi ikut disebut


def test_missing_pipeline_class_becomes_the_primary_cause():
    src = "class NotAPipeline:\n    def run(self):\n        return 1\n"
    result = review_upload(src.encode("utf-8"), "x.py")
    assert result["verdict"] == "invalid"
    assert "BasePipeline" in result["cause"]


def test_syntax_error_is_the_primary_cause_and_does_not_crash():
    result = review_upload(b"def broken(:\n    pass\n", "broken.py")
    assert result["ok"] is True                        # berkas terbaca…
    assert result["verdict"] == "invalid"              # …tetapi tidak valid
    assert "Python yang valid" in result["cause"]


def test_cause_summarises_instead_of_listing_every_failure():
    src = ("import os\nimport socket\nimport pickle\n"
           "class NotAPipeline:\n    pass\n")
    result = review_upload(src.encode("utf-8"), "many.py")
    cause = result["cause"]
    assert len(cause) < 400
    assert "Total" in cause or "sejenis" in cause      # sisanya diringkas


# ── robustness ────────────────────────────────────────────────────────────

def test_empty_file_is_rejected_cleanly():
    result = review_upload(b"", "empty.py")
    assert result["ok"] is False
    assert "kosong" in result["error"].lower()
    assert result["report"] is None


def test_whitespace_only_file_is_rejected_cleanly():
    result = review_upload(b"   \n\n  ", "blank.py")
    assert result["ok"] is False
    assert "kosong" in result["error"].lower()


def test_oversized_file_is_rejected_before_validation():
    payload = b"# padding\n" * (MAX_UPLOAD_BYTES // 5)
    assert len(payload) > MAX_UPLOAD_BYTES
    result = review_upload(payload, "huge.py")
    assert result["ok"] is False
    assert "besar" in result["error"].lower()
    assert result["report"] is None


def test_non_utf8_bytes_are_reported_not_crashed():
    result = review_upload(b"\xff\xfe\x00binary junk", "weird.py")
    assert result["ok"] is False
    assert "UTF-8" in result["error"]


def test_utf8_bom_is_accepted():
    source, error = decode_upload(b"\xef\xbb\xbf" + VALID_SOURCE.encode("utf-8"))
    assert error is None
    assert "BasePipeline" in source


def test_non_python_extension_is_rejected():
    result = review_upload(VALID_SOURCE.encode("utf-8"), "notes.txt")
    assert result["ok"] is False
    assert ".py" in result["error"]


# ── staging: outside the import path, with a filename guard ───────────────

@pytest.mark.parametrize("bad", [
    "../evil.py", "..\\evil.py", "/etc/evil.py", "C:\\Windows\\evil.py",
    "evil.txt", "", "..", "sub/dir/evil.py", "evil.py.exe", "evil py.py",
])
def test_unsafe_staging_names_are_refused(bad):
    assert safe_staging_name(bad) is None


@pytest.mark.parametrize("good", ["pipeline.py", "my_pipeline.py",
                                  "rfc-v2.py", "A1._x.py"])
def test_safe_staging_names_are_accepted(good):
    assert safe_staging_name(good) == good


def test_save_to_staging_writes_the_validated_text(tmp_path, monkeypatch):
    import ui.components.pipeline_upload as up
    monkeypatch.setattr(up, "STAGING_DIR", tmp_path / "uploaded_pipelines")

    target = up.save_to_staging(VALID_SOURCE, "my_pipeline.py", user=CONTRIBUTOR)
    assert target.exists()
    assert target.read_text(encoding="utf-8") == VALID_SOURCE
    assert target.parent.name == "uploaded_pipelines"


def test_save_to_staging_refuses_a_traversing_filename(tmp_path, monkeypatch):
    import ui.components.pipeline_upload as up
    monkeypatch.setattr(up, "STAGING_DIR", tmp_path / "uploaded_pipelines")

    with pytest.raises(ValueError):
        up.save_to_staging(VALID_SOURCE, "../../escaped.py", user=CONTRIBUTOR)
    assert not (tmp_path.parent / "escaped.py").exists()


def test_staging_dir_is_outside_the_import_path():
    """storage/ is data, not a package: nothing the platform imports lives there."""
    assert STAGING_DIR.parent.name == "storage"
    assert not (STAGING_DIR.parent / "__init__.py").exists()
    assert "pipelines" not in STAGING_DIR.parent.parts[-1:]


# ── package rules: every file checked, exactly one entry point ────────────

SUPPORT_SOURCE = '''
import numpy as np


def helper(x):
    return np.asarray(x).mean()
'''

HOSTILE_SUPPORT = "import os\n" + SUPPORT_SOURCE


def _pkg(*files):
    from ui.components.pipeline_upload import review_package
    return review_package([(name, src.encode("utf-8")) for name, src in files])


def test_package_with_one_entry_point_and_clean_support_is_valid():
    """A helper module is not a pipeline, so "no BasePipeline subclass" must not
    count against it — only the security rules apply to support files."""
    result = _pkg(("my_pipeline.py", VALID_SOURCE), ("helpers.py", SUPPORT_SOURCE))
    assert result["valid"] is True, result["cause"]
    assert result["entry_points"] == ["my_pipeline.py"]
    roles = {f["filename"]: f["role"] for f in result["files"]}
    assert roles == {"my_pipeline.py": "entry point", "helpers.py": "pendukung"}

    helper = next(f for f in result["files"] if f["filename"] == "helpers.py")
    assert helper["package_ok"] is True
    assert helper["verdict"] == "invalid"          # apa adanya dari validator…
    assert helper["blocking_failures"] == []       # …tetapi tidak memblokir paket
    # Pemeriksaan khas entry point tidak ditampilkan untuk berkas pendukung.
    names = {c["name"] for c in helper["groups"][GROUP_STRUCTURE]}
    assert "kelas pipeline" not in names
    assert "sintaks Python" in names


def test_package_without_an_entry_point_fails():
    result = _pkg(("helpers.py", SUPPORT_SOURCE))
    assert result["valid"] is False
    assert result["entry_points"] == []
    assert "BasePipeline" in result["cause"]


def test_package_with_two_entry_points_fails_as_ambiguous():
    result = _pkg(("a_pipeline.py", VALID_SOURCE), ("b_pipeline.py", VALID_SOURCE))
    assert result["valid"] is False
    assert len(result["entry_points"]) == 2
    assert "entry point" in result["cause"]
    assert "a_pipeline.py" in result["cause"] and "b_pipeline.py" in result["cause"]


def test_security_failure_in_a_SUPPORT_file_fails_the_whole_package():
    """The point of validating every file: a hidden `import os` in a helper
    must not ride along just because the entry point is clean."""
    result = _pkg(("my_pipeline.py", VALID_SOURCE), ("helpers.py", HOSTILE_SUPPORT))
    assert result["valid"] is False
    assert result["n_problem_files"] == 1
    assert "helpers.py" in result["cause"]
    bad = next(f for f in result["files"] if f["filename"] == "helpers.py")
    assert bad["role"] == "pendukung"
    assert any(c["status"] == "fail" and "os" in c["message"]
               for c in bad["groups"][GROUP_SECURITY])


def test_every_package_file_gets_its_own_report():
    result = _pkg(("my_pipeline.py", VALID_SOURCE), ("helpers.py", SUPPORT_SOURCE))
    assert len(result["files"]) == 2
    assert all(f["report"] is not None for f in result["files"])


def test_package_carries_the_per_file_descriptions():
    from ui.components.pipeline_upload import review_package
    result = review_package(
        [("my_pipeline.py", VALID_SOURCE.encode("utf-8"))],
        {"my_pipeline.py": "  entry point utama  "},
    )
    assert result["files"][0]["description"] == "entry point utama"


def test_unreadable_file_in_a_package_fails_the_package():
    result = _pkg(("my_pipeline.py", VALID_SOURCE), ("broken.py", "def f(:\n"))
    assert result["valid"] is False
    assert result["n_problem_files"] == 1


def test_empty_package_is_not_valid():
    from ui.components.pipeline_upload import review_package
    result = review_package([])
    assert result["valid"] is False
    assert result["files"] == []


# ── form metadata fills the registry snippet ──────────────────────────────

def test_form_metadata_overrides_placeholders_in_the_snippet():
    from ui.components.pipeline_upload import merge_form_metadata

    meta = extract_registry_metadata(VALID_SOURCE, "my_pipeline.py")
    form = {"name": "Random Forest — HIKARI2021", "dataset_type": "HIKARI2021",
            "algorithm": "Random Forest", "paper": "Rayyan (2024)"}
    snippet = build_registry_snippet(merge_form_metadata(meta, form))

    assert '"dataset_type": "HIKARI2021"' in snippet
    assert '"name": "Random Forest — HIKARI2021"' in snippet
    assert '"paper": "Rayyan (2024)"' in snippet
    assert "hikari2021.my_pipeline" in snippet       # id memakai dataset_type
    # Tidak ada placeholder tersisa untuk field yang diisi formulir…
    for field in ("dataset_type", "name", "paper", "algorithm"):
        assert f"{PLACEHOLDER}_{field}" not in snippet
    # …sementara `stages` (tidak ada di formulir dan tidak terbaca dari source
    # ini) memang masih placeholder — itu jujur, bukan tebakan.
    assert f"{PLACEHOLDER}_stage_1" in snippet


def test_blank_form_fields_keep_the_static_values():
    from ui.components.pipeline_upload import merge_form_metadata

    meta = extract_registry_metadata(VALID_SOURCE, "my_pipeline.py")
    merged = merge_form_metadata(meta, {"name": "  ", "algorithm": ""})
    assert merged["algorithm"] == "Random Forest"     # dari AST, tidak ditimpa
    assert not merged.get("name")                     # tetap placeholder nanti


def test_form_metadata_does_not_change_validation_outcome():
    from ui.components.pipeline_upload import merge_form_metadata

    meta = extract_registry_metadata(VALID_SOURCE, "my_pipeline.py")
    before = review_upload(VALID_SOURCE.encode("utf-8"), "my_pipeline.py")["report"]
    merge_form_metadata(meta, {"dataset_type": "HIKARI2021"})
    after = review_upload(VALID_SOURCE.encode("utf-8"), "my_pipeline.py")["report"]
    assert before == after


# ── registry snippet generator (Tahap 3): static metadata only ────────────

def test_metadata_reads_the_class_name_from_the_source():
    meta = extract_registry_metadata(VALID_SOURCE, "my_pipeline.py")
    assert meta["class_name"] == "MyPipeline"
    assert meta["module_stem"] == "my_pipeline"


def test_metadata_reads_literal_values_from_get_info():
    meta = extract_registry_metadata(VALID_SOURCE, "my_pipeline.py")
    assert meta["algorithm"] == "Random Forest"
    assert meta["paper"] == "Contoh (2026)"


def test_metadata_leaves_unreadable_fields_unset_instead_of_guessing():
    """`dataset_type` and `name` are registry-level fields; a pipeline file
    usually has neither, so they must come back unset (→ placeholder)."""
    meta = extract_registry_metadata(VALID_SOURCE, "my_pipeline.py")
    assert meta["dataset_type"] is None


def test_metadata_uses_a_literal_dataset_type_when_the_source_states_one():
    src = VALID_SOURCE.replace(
        '"paper": "Contoh (2026)",',
        '"paper": "Contoh (2026)",\n            "dataset_type": "EVE_SURICATA",')
    meta = extract_registry_metadata(src, "eve_new.py")
    assert meta["dataset_type"] == "EVE_SURICATA"


def test_metadata_offers_a_hint_without_using_it_as_a_value():
    """A known dataset_type appearing as some other literal (e.g. the argument
    of research_paper_credit) is reported as a HINT, never as the value."""
    src = VALID_SOURCE.replace(
        '"paper": "Contoh (2026)",',
        '"paper": research_paper_credit("HIKARI2021"),')
    meta = extract_registry_metadata(src, "x.py")
    assert meta["dataset_type"] is None
    assert any("HIKARI2021" in h for h in meta["hints"])


def test_metadata_extracts_stage_labels_in_source_order():
    src = VALID_SOURCE.replace(
        "        clf = RandomForestClassifier",
        '        self._emit_progress(progress, "Preprocessing")\n'
        '        self._emit_progress(progress, "Training")\n'
        "        clf = RandomForestClassifier")
    meta = extract_registry_metadata(src, "x.py")
    assert meta["stages"] == ["Preprocessing", "Training"]


def test_metadata_survives_a_syntax_error():
    meta = extract_registry_metadata("def broken(:\n", "broken.py")
    assert meta["class_name"] is None
    assert meta["stages"] == []


def test_snippet_contains_the_real_class_name_and_every_registry_field():
    meta = extract_registry_metadata(VALID_SOURCE, "my_pipeline.py")
    snippet = build_registry_snippet(meta)
    assert "MyPipeline" in snippet
    assert "import MyPipeline" in snippet          # baris import ikut disarankan
    for field in REGISTRY_FIELDS:
        assert f'"{field}"' in snippet


def test_snippet_uses_placeholders_for_values_it_cannot_read():
    snippet = build_registry_snippet(
        extract_registry_metadata(VALID_SOURCE, "my_pipeline.py"))
    assert f'"dataset_type": "{PLACEHOLDER}_dataset_type"' in snippet
    assert f'"name": "{PLACEHOLDER}_name"' in snippet
    # …tetapi yang TERBACA dipakai apa adanya, bukan placeholder.
    assert '"algorithm": "Random Forest"' in snippet
    assert '"paper": "Contoh (2026)"' in snippet


def test_snippet_never_invents_a_dataset_type():
    snippet = build_registry_snippet(
        extract_registry_metadata(VALID_SOURCE, "my_pipeline.py"))
    for known in ("HIKARI2021", "EVE_SURICATA"):
        assert f'"dataset_type": "{known}"' not in snippet


def test_snippet_is_syntactically_valid_python_once_placeholders_are_quoted():
    """The entry body must parse as Python so a paste cannot break the registry
    with a syntax error (placeholders are quoted strings, not bare names)."""
    import ast

    meta = extract_registry_metadata(VALID_SOURCE, "my_pipeline.py")
    body = "\n".join(ln for ln in build_registry_snippet(meta).splitlines()
                     if not ln.startswith(("#", "from ")))
    ast.parse("PIPELINE_REGISTRY = {\n" + body + "\n}")


def test_snippet_for_a_real_repo_pipeline_matches_its_registry_stages():
    """Sanity check against reality: the stage labels extracted from
    hikari2021/rfc_pipeline.py are exactly the ones its registry entry lists."""
    from config.pipeline_registry import PIPELINE_REGISTRY

    path = Path(__file__).resolve().parents[1] / "pipelines" / "hikari2021" / "rfc_pipeline.py"
    meta = extract_registry_metadata(path.read_text(encoding="utf-8"), path.name)
    assert meta["class_name"] == "HikariRFCPipeline"
    assert meta["stages"] == PIPELINE_REGISTRY["hikari2021.rfc_pipeline"]["stages"]


def test_snippet_generation_never_writes_anything(tmp_path, monkeypatch):
    """Tahap 3 hanya menghasilkan TEKS — tidak ada berkas yang dibuat."""
    import ui.components.pipeline_upload as up
    monkeypatch.setattr(up, "STAGING_DIR", tmp_path / "staging")

    before = set(tmp_path.rglob("*"))
    build_registry_snippet(extract_registry_metadata(VALID_SOURCE, "x.py"))
    assert set(tmp_path.rglob("*")) == before
    assert not (tmp_path / "staging").exists()


def test_upload_module_has_no_automatic_activation_path():
    """No widget activates anything, and the module has exactly ONE write — the
    opt-in staging copy. Checked structurally on the AST, since the module's
    prose legitimately mentions `pipelines/` and the registry while explaining
    that it never touches them."""
    import ast

    import ui.components.pipeline_upload as up

    tree = ast.parse(Path(up.__file__).with_suffix(".py").read_text(encoding="utf-8"))

    writes = []          # (nama fungsi pembungkus, metode tulis)
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            attr = node.func.attr
            if attr in ("write_text", "write_bytes", "mkdir", "open"):
                writes.append((fn.name, attr))

    # Satu-satunya penulisan: mkdir + write_text, keduanya di save_to_staging.
    assert {fn for fn, _ in writes} == {"save_to_staging"}, writes
    assert sorted(a for _, a in writes) == ["mkdir", "write_text"]


def test_every_activation_call_passes_an_actor_to_be_checked():
    """Sejak Fase 4 aktivasi memang ada (pipeline yang disetujui, akun yang
    didaftarkan) — yang harus dijaga sekarang: SETIAP pemanggilan aktivasi
    menyertakan `actor`, sehingga izinnya diperiksa di dalam fungsi dan bukan
    hanya oleh tampilan."""
    import ast

    import ui.views.contribute as contrib

    tree = ast.parse(Path(contrib.__file__).with_suffix(".py").read_text(encoding="utf-8"))
    guarded_calls = {"set_pipeline_active", "set_user_status", "set_user_role",
                     "set_user_active", "approve_submission", "reject_submission"}

    seen = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name in guarded_calls:
            seen.add(name)
            kwargs = {kw.arg for kw in node.keywords}
            assert "actor" in kwargs, f"{name} dipanggil tanpa actor"

    assert seen, "tidak ada pemanggilan aktivasi terdeteksi — pemindaian salah"


def test_staging_target_is_not_inside_the_pipelines_package():
    """Jalur tulis satu-satunya tidak boleh menyentuh paket yang di-import."""
    import ui.components.pipeline_upload as up

    pipelines_pkg = (Path(up.__file__).resolve().parents[2] / "pipelines").resolve()
    assert pipelines_pkg.is_dir()
    assert not str(up.STAGING_DIR.resolve()).startswith(str(pipelines_pkg))


# ── the upload layer never executes what it validates ─────────────────────

def test_review_upload_does_not_execute_the_uploaded_source(tmp_path):
    """Source whose top level would write a file / raise must do neither."""
    marker = tmp_path / "pwned.txt"
    hostile = (f"open(r'{marker}', 'w').write('x')\n"
               f"raise SystemExit('top-level ran')\n" + VALID_SOURCE)

    result = review_upload(hostile.encode("utf-8"), "hostile.py")

    assert result["verdict"] == "invalid"          # open(...,'w') ditolak
    assert not marker.exists()                     # dan tidak pernah terjadi


def test_upload_module_never_imports_or_execs_the_upload():
    """Static guarantee over the module's own AST (same method as Tahap 1)."""
    import ast

    import ui.components.pipeline_upload as up

    tree = ast.parse(Path(up.__file__).with_suffix(".py").read_text(encoding="utf-8"))
    called, imported = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name):
                called.add(fn.id)
            elif isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                called.add(f"{fn.value.id}.{fn.attr}")
        elif isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert not (called & {"exec", "eval", "compile", "__import__"})
    assert not (imported & {"importlib", "runpy", "subprocess", "pickle", "os"})
    assert "validate_pipeline_source" in called      # satu-satunya pemroses kode


def test_upload_layer_does_not_touch_the_registry():
    """No import of / no call into the registry. Checked on the AST, because the
    module legitimately NAMES `config/pipeline_registry.py` in the user-facing
    guidance text ("activation is manual") — mentioning it is the point."""
    import ast

    import ui.components.pipeline_upload as up

    tree = ast.parse(Path(up.__file__).with_suffix(".py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Name):
            assert node.id != "PIPELINE_REGISTRY"
    assert not any("registry" in m for m in imported)

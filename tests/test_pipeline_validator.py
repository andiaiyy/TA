"""Tests for orchestrator/pipeline_validator.py (TAHAP 1 — logika validasi).

Every fixture is a SMALL source string defined here — never a real file on disk
and never anything that gets imported or executed. The malicious samples below
are inert: the validator only parses them with ``ast.parse``, so writing
``import os`` or ``eval(...)`` in a test string runs nothing.

The last group validates every REAL registered pipeline file in the repo, so
the rules can never drift into rejecting the platform's own pipelines.
"""
from pathlib import Path

import pytest

from orchestrator.pipeline_validator import (
    ALLOWED_MODULES, EXPECTED_INFO_KEYS, FORBIDDEN_MODULES,
    ValidationReport, validate_pipeline_file, validate_pipeline_source,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# ── helpers ───────────────────────────────────────────────────────────────

VALID_PIPELINE = '''
"""A minimal but contract-complete pipeline."""
from typing import Optional

import numpy as np
from sklearn.ensemble import RandomForestClassifier

from pipelines.base import BasePipeline, ProgressCallback
from contracts.pipeline_contracts import PipelineInput, PipelineResult


class MyPipeline(BasePipeline):

    def run(self, pipeline_input: PipelineInput,
            progress: Optional[ProgressCallback] = None) -> PipelineResult:
        self._emit_progress(progress, "Training")
        clf = RandomForestClassifier(n_estimators=10, random_state=42)
        X = pipeline_input.df.drop(columns=[pipeline_input.label_column])
        y = pipeline_input.df[pipeline_input.label_column]
        clf.fit(X, y)
        return PipelineResult(
            accuracy=1.0, precision=1.0, recall=1.0, f1_score=1.0,
            confusion_matrix=[[1, 0], [0, 1]], model=clf,
            feature_names=list(X.columns), label_mapping={0: "Benign", 1: "Attack"},
        )

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


def _statuses(report: ValidationReport, name_part: str) -> list[str]:
    return [c.status for c in report.checks if name_part in c.name]


def _messages(report: ValidationReport) -> str:
    return " | ".join(c.message for c in report.checks)


# ── the happy path ────────────────────────────────────────────────────────

def test_minimal_valid_pipeline_passes():
    report = validate_pipeline_source(VALID_PIPELINE, "my_pipeline.py")
    assert report.valid is True, _messages(report)
    assert report.failures == []
    assert "Valid" in report.summary
    assert _statuses(report, "kelas pipeline") == ["pass"]
    assert _statuses(report, "method `run`") == ["pass"]
    assert _statuses(report, "method `get_info`") == ["pass"]


def test_valid_pipeline_reports_no_missing_metadata_keys():
    report = validate_pipeline_source(VALID_PIPELINE)
    info_check = next(c for c in report.checks if "get_info" in c.name)
    assert info_check.status == "pass"


def test_report_serialises_to_a_plain_dict_for_the_ui_stage():
    payload = validate_pipeline_source(VALID_PIPELINE, "x.py").to_dict()
    assert payload["valid"] is True
    assert payload["filename"] == "x.py"
    assert all({"name", "status", "message", "line"} <= set(c) for c in payload["checks"])


# ── structure failures ────────────────────────────────────────────────────

def test_class_without_basepipeline_fails():
    src = '''
class NotAPipeline:
    def run(self, pipeline_input, progress=None):
        return None

    def get_info(self):
        return {}
'''
    report = validate_pipeline_source(src)
    assert report.valid is False
    check = next(c for c in report.checks if c.name == "kelas pipeline")
    assert check.status == "fail"
    assert "BasePipeline" in check.message


def test_missing_get_info_fails_with_a_specific_message():
    src = '''
from pipelines.base import BasePipeline


class MyPipeline(BasePipeline):
    def run(self, pipeline_input, progress=None):
        return None
'''
    report = validate_pipeline_source(src)
    assert report.valid is False
    check = next(c for c in report.checks if c.name == "method `get_info`")
    assert check.status == "fail"
    assert "get_info" in check.message


def test_missing_run_fails():
    src = '''
from pipelines.base import BasePipeline


class MyPipeline(BasePipeline):
    def get_info(self):
        return {"paper": "x"}
'''
    report = validate_pipeline_source(src)
    assert report.valid is False
    assert next(c for c in report.checks if c.name == "method `run`").status == "fail"


def test_get_info_without_return_fails():
    src = '''
from pipelines.base import BasePipeline


class MyPipeline(BasePipeline):
    def run(self, pipeline_input, progress=None):
        return None

    def get_info(self):
        pass
'''
    report = validate_pipeline_source(src)
    assert report.valid is False
    check = next(c for c in report.checks if "get_info" in c.name and c.name.startswith("get_info"))
    assert check.status == "fail"


def test_get_info_returning_a_non_dict_fails():
    src = '''
from pipelines.base import BasePipeline


class MyPipeline(BasePipeline):
    def run(self, pipeline_input, progress=None):
        return None

    def get_info(self):
        return "bukan dict"
'''
    report = validate_pipeline_source(src)
    assert report.valid is False


def test_get_info_missing_metadata_keys_only_warns():
    src = '''
from pipelines.base import BasePipeline


class MyPipeline(BasePipeline):
    def run(self, pipeline_input, progress=None):
        return None

    def get_info(self):
        return {"paper": "Contoh (2026)"}
'''
    report = validate_pipeline_source(src)
    assert report.valid is True                       # warn tidak menggagalkan
    check = next(c for c in report.checks if c.name.startswith("get_info"))
    assert check.status == "warn"
    assert "algorithm" in check.message


def test_odd_run_signature_only_warns():
    src = '''
from pipelines.base import BasePipeline


class MyPipeline(BasePipeline):
    def run(self, data):
        return None

    def get_info(self):
        return {"paper": "x", "algorithm": "y", "preprocessing_steps": [],
                "feature_selection": "n", "fixed_params": {}, "train_test_split": {}}
'''
    report = validate_pipeline_source(src)
    assert report.valid is True
    check = next(c for c in report.checks if c.name == "signature run()")
    assert check.status == "warn"
    assert "pipeline_input" in check.message


# ── security: forbidden imports ───────────────────────────────────────────

@pytest.mark.parametrize("module", ["os", "sys", "subprocess", "socket", "shutil",
                                    "requests", "urllib", "pickle", "ctypes",
                                    "importlib", "pty", "multiprocessing"])
def test_forbidden_import_fails(module):
    src = f"import {module}\n" + VALID_PIPELINE
    report = validate_pipeline_source(src)
    assert report.valid is False
    check = next(c for c in report.checks if c.name == "import terlarang")
    assert module in check.message
    assert check.line == 1


def test_forbidden_from_import_is_caught_too():
    report = validate_pipeline_source("from subprocess import run\n" + VALID_PIPELINE)
    assert report.valid is False
    assert any("subprocess" in c.message for c in report.failures)


def test_aliased_forbidden_import_is_caught():
    report = validate_pipeline_source("import os as _o\n" + VALID_PIPELINE)
    assert report.valid is False
    assert any("`os`" in c.message for c in report.failures)


def test_every_forbidden_module_has_a_reason():
    assert all(reason.strip() for reason in FORBIDDEN_MODULES.values())
    assert not (set(FORBIDDEN_MODULES) & ALLOWED_MODULES)   # tidak saling tumpang tindih


# ── security: forbidden calls & dunder access ─────────────────────────────

@pytest.mark.parametrize("snippet, needle", [
    ("x = eval('1+1')", "eval"),
    ("exec('a = 1')", "exec"),
    ("compile('a', '<s>', 'exec')", "compile"),
    ("m = __import__('os')", "__import__"),
])
def test_forbidden_calls_fail(snippet, needle):
    src = VALID_PIPELINE + f"\n\n{snippet}\n"
    report = validate_pipeline_source(src)
    assert report.valid is False
    assert any(needle in c.message for c in report.failures)


def test_os_system_style_call_fails():
    report = validate_pipeline_source("import os\nos.system('whoami')\n" + VALID_PIPELINE)
    assert report.valid is False
    assert any("os.system" in c.message for c in report.failures)


@pytest.mark.parametrize("dunder", ["__subclasses__", "__globals__",
                                    "__builtins__", "__bases__"])
def test_sandbox_escape_dunders_fail(dunder):
    src = VALID_PIPELINE + f"\n\nleak = ().__class__{'.' + dunder if dunder != '__builtins__' else ''}\n"
    if dunder == "__builtins__":
        src = VALID_PIPELINE + "\n\nleak = __builtins__\n"
    report = validate_pipeline_source(src)
    assert report.valid is False
    assert any(dunder in c.message for c in report.failures)


def test_open_for_writing_fails_but_reading_does_not():
    writing = validate_pipeline_source(VALID_PIPELINE + "\nf = open('x.txt', 'w')\n")
    assert writing.valid is False
    assert any("open()" in c.message for c in writing.failures)

    reading = validate_pipeline_source(VALID_PIPELINE + "\nf = open('data.csv', 'r')\n")
    assert reading.valid is True


def test_getattr_on_a_module_fails_but_on_an_object_only_warns():
    on_module = validate_pipeline_source(
        "import json\n" + VALID_PIPELINE + "\nfn = getattr(json, 'loads')\n")
    assert on_module.valid is False
    assert any("getattr" in c.message for c in on_module.failures)

    on_object = validate_pipeline_source(VALID_PIPELINE + "\nv = getattr(clf, 'coef_')\n")
    assert on_object.valid is True
    assert any(c.name == "refleksi atribut" for c in on_object.warnings)


def test_findings_carry_a_line_number():
    src = VALID_PIPELINE + "\n\nimport socket\n"
    report = validate_pipeline_source(src)
    finding = next(c for c in report.failures if "socket" in c.message)
    assert finding.line == src.splitlines().index("import socket") + 1


# ── tolerance: normal ML code must not be rejected ────────────────────────

@pytest.mark.parametrize("module", ["numpy", "pandas", "sklearn", "xgboost",
                                    "joblib", "imblearn", "scipy"])
def test_ml_libraries_are_allowed(module):
    report = validate_pipeline_source(f"import {module}\n" + VALID_PIPELINE)
    assert report.valid is True
    assert not any(module in c.message for c in report.warnings)


@pytest.mark.parametrize("module", ["math", "csv", "tempfile", "logging"])
def test_neutral_import_never_fails_hard(module):
    """Neutral stdlib must not be rejected: allow-listed ones pass silently,
    the rest are only flagged for a manual look."""
    report = validate_pipeline_source(f"import {module}\n" + VALID_PIPELINE)
    assert report.valid is True
    assert report.failures == []
    if module not in ALLOWED_MODULES:
        assert any(module in c.message for c in report.warnings)


# ── robustness ────────────────────────────────────────────────────────────

def test_syntax_error_is_reported_without_crashing():
    report = validate_pipeline_source("def broken(:\n    pass\n", "broken.py")
    assert report.valid is False
    assert len(report.checks) == 1
    assert report.checks[0].name == "sintaks Python"
    assert report.checks[0].line == 1


def test_empty_source_does_not_crash():
    report = validate_pipeline_source("")
    assert report.valid is False                      # tidak ada kelas pipeline
    assert any(c.name == "kelas pipeline" for c in report.failures)


def test_unreadable_file_is_reported():
    report = validate_pipeline_file(REPO_ROOT / "tests" / "does_not_exist.py")
    assert report.valid is False
    assert "tidak dapat dibaca" in report.summary


# ── the validator never executes what it validates ────────────────────────

def test_validator_does_not_execute_the_source(tmp_path, monkeypatch):
    """A source whose top level would explode if executed must still validate.

    If the validator imported/exec'd it, this test would raise instead of
    returning a report.
    """
    src = VALID_PIPELINE + "\nraise RuntimeError('top-level code ran!')\n"
    report = validate_pipeline_source(src)
    assert isinstance(report, ValidationReport)
    assert report.valid is True          # `raise` is not a security finding

    marker = tmp_path / "side_effect.txt"
    hostile = f"open(r'{marker}', 'w').write('pwned')\n" + VALID_PIPELINE
    report = validate_pipeline_source(hostile)
    assert report.valid is False         # write-mode open is rejected...
    assert not marker.exists()           # ...and never actually happened


def test_validator_module_never_imports_or_execs():
    """Static guarantee, checked with AST (not substring matching, which would
    trip over the validator's own list of forbidden NAMES): the validator makes
    no call to exec/eval/compile/__import__ and imports no dynamic loader. The
    only way it touches the source under validation is ``ast.parse``."""
    import ast as _ast

    source = (REPO_ROOT / "orchestrator" / "pipeline_validator.py").read_text(encoding="utf-8")
    tree = _ast.parse(source)

    called, imported, parses = set(), set(), 0
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Call):
            fn = node.func
            if isinstance(fn, _ast.Name):
                called.add(fn.id)
            elif isinstance(fn, _ast.Attribute):
                if isinstance(fn.value, _ast.Name):
                    called.add(f"{fn.value.id}.{fn.attr}")
                    if (fn.value.id, fn.attr) == ("ast", "parse"):
                        parses += 1
        elif isinstance(node, _ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, _ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert not (called & {"exec", "eval", "compile", "__import__", "open"})
    assert not any(c.startswith(("importlib.", "runpy.", "subprocess.", "os."))
                   for c in called)
    assert not (imported & {"importlib", "runpy", "subprocess", "os", "sys", "pickle"})
    assert parses == 1, "source di bawah validasi hanya boleh disentuh ast.parse"


# ── the platform's own pipelines must stay valid ──────────────────────────

def _registered_pipeline_files() -> list[Path]:
    from config.pipeline_registry import PIPELINE_REGISTRY
    import inspect
    files = set()
    for entry in PIPELINE_REGISTRY.values():
        files.add(Path(inspect.getfile(entry["class"])))
    return sorted(files)


@pytest.mark.parametrize("path", _registered_pipeline_files(),
                         ids=lambda p: p.name)
def test_real_registered_pipelines_validate(path):
    """Guards against rules that would reject the platform's own pipelines."""
    report = validate_pipeline_file(path)
    assert report.valid is True, f"{path.name}: " + "; ".join(
        f"{c.name}: {c.message}" for c in report.failures)


def test_expected_info_keys_match_the_base_contract():
    """The metadata keys come from BasePipeline.get_info's docstring, not from
    the validator's imagination."""
    doc = (REPO_ROOT / "pipelines" / "base.py").read_text(encoding="utf-8")
    for key in EXPECTED_INFO_KEYS:
        assert key in doc, f"{key} tidak disebut di pipelines/base.py"

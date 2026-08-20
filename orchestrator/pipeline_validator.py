"""
Static validator for uploaded pipeline scripts — TAHAP 1 (logika saja).

Answers ONE question about a ``.py`` file: "is this a well-formed and safe
research pipeline for this platform?" It produces a report; it does not stage,
register, activate, or run anything. UI (tahap 2) and activation (tahap 3) are
separate work and are deliberately absent here.

⚠️ SECURITY — STATIC ONLY. The source under validation is NEVER imported,
``exec``-ed, ``eval``-ed, or compiled to a code object. Importing an untrusted
module executes its top level, which is exactly the arbitrary code execution
this validator exists to prevent. Every check runs on the ``ast`` tree returned
by ``ast.parse``, which parses text into a syntax tree without evaluating it.
The only "execution" is our own traversal of that tree.

The rules are derived from the platform's own contract, not invented:
  - ``pipelines/base.py`` — ``BasePipeline`` declares exactly two abstract
    methods, ``run(self, pipeline_input, progress=None)`` and ``get_info()``.
  - ``pipelines/base.py`` docstring of ``get_info`` — the metadata keys a
    pipeline is expected to return (paper, algorithm, preprocessing_steps,
    feature_selection, fixed_params, train_test_split).
  - ``contracts/pipeline_contracts.py`` — ``PipelineInput`` / ``PipelineResult``.

⚠️ IMPORT RESTRICTION: no imports from ui/, database/, or pipelines/. This
module reads source TEXT; it never touches the registry.
"""
from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
from pathlib import Path

# ── Statuses ──────────────────────────────────────────────────────────────
PASS, WARN, FAIL = "pass", "warn", "fail"

# ── Kontrak yang harus dipenuhi (dari pipelines/base.py) ──────────────────
BASE_CLASS_NAME = "BasePipeline"
REQUIRED_METHODS = ("run", "get_info")

# Nama parameter run() sesuai BasePipeline.run.
RUN_FIRST_PARAM = "pipeline_input"
RUN_PROGRESS_PARAM = "progress"

# Kunci metadata yang disebut docstring BasePipeline.get_info. Ketiadaannya
# hanya WARN — sebagian pipeline membangun dict-nya secara dinamis.
EXPECTED_INFO_KEYS = (
    "paper", "algorithm", "preprocessing_steps",
    "feature_selection", "fixed_params", "train_test_split",
)

# ── SATU daftar terpusat untuk aturan keamanan ────────────────────────────
# Modul yang memberi akses ke proses, berkas, jaringan, atau pemuatan kode
# arbitrer. Sebuah pipeline riset tidak pernah membutuhkannya.
FORBIDDEN_MODULES: dict[str, str] = {
    "os": "akses sistem berkas & proses",
    "sys": "akses interpreter & manipulasi path/modul",
    "subprocess": "menjalankan proses lain",
    "socket": "koneksi jaringan mentah",
    "shutil": "operasi berkas destruktif (copy/move/rmtree)",
    "requests": "koneksi jaringan keluar",
    "urllib": "koneksi jaringan keluar",
    "http": "koneksi jaringan keluar",
    "httpx": "koneksi jaringan keluar",
    "ftplib": "koneksi jaringan keluar",
    "telnetlib": "koneksi jaringan keluar",
    "smtplib": "pengiriman email",
    "pickle": "deserialisasi objek arbitrer (eksekusi kode)",
    "dill": "deserialisasi objek arbitrer (eksekusi kode)",
    "marshal": "deserialisasi objek arbitrer",
    "ctypes": "pemanggilan kode native",
    "cffi": "pemanggilan kode native",
    "multiprocessing": "menjalankan proses lain",
    "importlib": "memuat modul secara dinamis",
    "imp": "memuat modul secara dinamis",
    "runpy": "menjalankan modul lain",
    "pty": "membuka terminal semu",
    "signal": "mengirim sinyal ke proses",
    "resource": "mengubah batas sumber daya proses",
    "builtins": "akses langsung ke builtins",
}

# Modul yang wajar bagi pipeline ML + modul milik platform ini. Di luar daftar
# ini dan bukan modul terlarang → WARN (tidak menggagalkan), supaya validator
# tidak terlalu ketat terhadap pustaka riset yang sah.
ALLOWED_MODULES: frozenset[str] = frozenset({
    # ML / numerik
    "numpy", "pandas", "scipy", "sklearn", "xgboost", "lightgbm", "catboost",
    "imblearn", "joblib", "statsmodels",
    # tipe & utilitas murni
    "typing", "dataclasses", "abc", "enum", "math", "statistics", "decimal",
    "fractions", "collections", "itertools", "functools", "operator",
    "__future__",
    # milik platform (dibutuhkan untuk mewarisi BasePipeline & kontraknya)
    "pipelines", "contracts", "config", "utils",
})

# Fungsi builtin yang mengeksekusi/memuat kode.
FORBIDDEN_CALLS: dict[str, str] = {
    "eval": "mengeksekusi ekspresi arbitrer",
    "exec": "mengeksekusi kode arbitrer",
    "compile": "mengompilasi kode arbitrer",
    "__import__": "memuat modul secara dinamis",
    "globals": "membuka namespace global",
    "locals": "membuka namespace lokal",
    "vars": "membuka namespace objek",
    "breakpoint": "menghentikan eksekusi ke debugger",
    "input": "meminta masukan interaktif (menggantung worker)",
}

# Atribut dunder yang lazim dipakai untuk keluar dari sandbox.
FORBIDDEN_ATTRIBUTES: dict[str, str] = {
    "__subclasses__": "teknik sandbox-escape",
    "__globals__": "akses namespace global fungsi lain",
    "__builtins__": "akses langsung ke builtins",
    "__bases__": "penelusuran hierarki kelas untuk sandbox-escape",
    "__mro__": "penelusuran hierarki kelas untuk sandbox-escape",
    "__code__": "akses objek kode",
    "__loader__": "akses pemuat modul",
    "__reduce__": "hook serialisasi yang dapat mengeksekusi kode",
    "__class__": "penelusuran tipe untuk sandbox-escape",
}

# Mode open() yang menulis/menimpa berkas.
_WRITE_MODES = ("w", "a", "x", "+")


@dataclass
class ValidationCheck:
    """Satu pemeriksaan. ``line`` diisi bila temuan punya lokasi di source."""
    name: str
    status: str            # PASS | WARN | FAIL
    message: str
    line: int | None = None


@dataclass
class ValidationReport:
    """Hasil validasi satu berkas. ``valid`` true HANYA bila nol status fail."""
    valid: bool = False
    filename: str = ""
    summary: str = ""
    checks: list[ValidationCheck] = field(default_factory=list)

    @property
    def failures(self) -> list[ValidationCheck]:
        return [c for c in self.checks if c.status == FAIL]

    @property
    def warnings(self) -> list[ValidationCheck]:
        return [c for c in self.checks if c.status == WARN]

    def to_dict(self) -> dict:
        """Bentuk polos (JSON/cache friendly) untuk dipakai UI di tahap 2."""
        return {
            "valid": self.valid,
            "filename": self.filename,
            "summary": self.summary,
            "checks": [asdict(c) for c in self.checks],
        }


# ── Pembantu AST ──────────────────────────────────────────────────────────

def _dotted_name(node: ast.AST) -> str:
    """Nama ber-titik dari Name/Attribute, mis. `pipelines.base.BasePipeline`."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _root_module(name: str) -> str:
    return (name or "").split(".", 1)[0]


def _class_bases(cls: ast.ClassDef) -> list[str]:
    return [_dotted_name(b) for b in cls.bases]


def _methods(cls: ast.ClassDef) -> dict[str, ast.AST]:
    return {n.name: n for n in cls.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


# ── Pemeriksaan STRUKTUR ──────────────────────────────────────────────────

def _find_pipeline_class(tree: ast.Module) -> tuple[ast.ClassDef | None, bool]:
    """(kelas pipeline, apakah mewarisi BasePipeline secara LANGSUNG).

    Prioritas: kelas yang langsung mewarisi ``BasePipeline`` (juga bila ditulis
    ber-titik seperti ``base.BasePipeline``). Bila tidak ada, terima kelas yang
    mewarisi base lain bernama ``*Pipeline`` — pola nyata di repo ini
    (``EveCbrRFCPipeline(BaseCbrEvePipeline)``), ditandai sebagai tidak langsung.
    """
    indirect: ast.ClassDef | None = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for base in _class_bases(node):
            if base.split(".")[-1] == BASE_CLASS_NAME:
                return node, True
        if indirect is None:
            for base in _class_bases(node):
                if base.split(".")[-1].endswith("Pipeline"):
                    indirect = node
    return indirect, False


def _check_structure(tree: ast.Module) -> list[ValidationCheck]:
    checks: list[ValidationCheck] = []
    cls, direct = _find_pipeline_class(tree)

    if cls is None:
        checks.append(ValidationCheck(
            "kelas pipeline", FAIL,
            f"Tidak ditemukan kelas turunan `{BASE_CLASS_NAME}`. Pipeline harus "
            f"berupa kelas yang mewarisi `{BASE_CLASS_NAME}` "
            f"(lihat `pipelines/base.py`)."))
        return checks

    if direct:
        checks.append(ValidationCheck(
            "kelas pipeline", PASS,
            f"Kelas `{cls.name}` mewarisi `{BASE_CLASS_NAME}`.", cls.lineno))
    else:
        base_names = ", ".join(f"`{b}`" for b in _class_bases(cls))
        checks.append(ValidationCheck(
            "kelas pipeline", WARN,
            f"Kelas `{cls.name}` tidak mewarisi `{BASE_CLASS_NAME}` secara "
            f"langsung, melainkan {base_names}. Pastikan kelas induk itu "
            f"turunan `{BASE_CLASS_NAME}`.", cls.lineno))

    methods = _methods(cls)
    # Bila pewarisan tidak langsung, method wajib boleh diwarisi dari induk →
    # ketiadaannya hanya peringatan, bukan kegagalan.
    missing_status = FAIL if direct else WARN
    for name in REQUIRED_METHODS:
        if name in methods:
            checks.append(ValidationCheck(
                f"method `{name}`", PASS,
                f"`{name}()` diimplementasi pada `{cls.name}`.",
                methods[name].lineno))
        else:
            detail = ("" if direct else
                      " (mungkin diwarisi dari kelas induk — tidak dapat "
                      "diperiksa dari berkas ini saja)")
            checks.append(ValidationCheck(
                f"method `{name}`", missing_status,
                f"Method `{name}()` belum diimplementasi pada `{cls.name}`"
                f"{detail}.", cls.lineno))

    if "run" in methods:
        checks.append(_check_run_signature(methods["run"]))
    if "get_info" in methods:
        checks.append(_check_get_info(methods["get_info"]))
    return checks


def _check_run_signature(fn: ast.AST) -> ValidationCheck:
    """Signature run() dibandingkan dengan BasePipeline.run — selisih gaya hanya
    menghasilkan WARN, karena penamaan parameter bisa berbeda tanpa merusak
    kontrak (pemanggilnya memakai argumen posisional)."""
    args = [a.arg for a in fn.args.args]
    positional = [a for a in args if a != "self"]
    if not positional:
        return ValidationCheck(
            "signature run()", WARN,
            f"`run()` tidak menerima parameter apa pun; kontraknya "
            f"`run(self, {RUN_FIRST_PARAM}, {RUN_PROGRESS_PARAM}=None)`.",
            fn.lineno)

    problems: list[str] = []
    if positional[0] != RUN_FIRST_PARAM:
        problems.append(f"parameter pertama `{positional[0]}` "
                        f"(kontrak: `{RUN_FIRST_PARAM}`)")
    if RUN_PROGRESS_PARAM not in args and not fn.args.kwonlyargs:
        problems.append(f"tidak ada parameter opsional `{RUN_PROGRESS_PARAM}`")
    if problems:
        return ValidationCheck(
            "signature run()", WARN,
            "Signature berbeda dari kontrak: " + "; ".join(problems) + ".",
            fn.lineno)
    return ValidationCheck(
        "signature run()", PASS,
        f"`run(self, {RUN_FIRST_PARAM}, {RUN_PROGRESS_PARAM}=None)` sesuai kontrak.",
        fn.lineno)


def _check_get_info(fn: ast.AST) -> ValidationCheck:
    """get_info() harus mengembalikan dict metadata. Bila dict-nya literal, kunci
    yang disarankan ikut diperiksa (WARN bila kurang); bila dibangun dinamis,
    isinya tidak dapat dibaca secara statis dan itu diterima apa adanya."""
    returns = [n for n in ast.walk(fn)
               if isinstance(n, ast.Return) and n.value is not None]
    if not returns:
        return ValidationCheck(
            "get_info() mengembalikan dict", FAIL,
            "`get_info()` tidak mengembalikan apa pun; kontraknya mengembalikan "
            "`dict` metadata (lihat `pipelines/base.py`).", fn.lineno)

    dict_returns = [r for r in returns if isinstance(r.value, ast.Dict)]
    if not dict_returns:
        non_dict = [r for r in returns
                    if isinstance(r.value, (ast.Constant, ast.List, ast.Tuple,
                                            ast.Set))]
        if non_dict and len(non_dict) == len(returns):
            return ValidationCheck(
                "get_info() mengembalikan dict", FAIL,
                "`get_info()` mengembalikan nilai yang bukan `dict`.",
                non_dict[0].lineno)
        return ValidationCheck(
            "get_info() mengembalikan dict", PASS,
            "`get_info()` mengembalikan nilai yang dibangun dinamis — isinya "
            "tidak dapat diperiksa secara statis.", returns[0].lineno)

    literal = dict_returns[0].value
    keys = {k.value for k in literal.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    missing = [k for k in EXPECTED_INFO_KEYS if k not in keys]
    if missing:
        return ValidationCheck(
            "get_info() mengembalikan dict", WARN,
            "`get_info()` mengembalikan dict, tetapi kunci berikut belum ada: "
            + ", ".join(f"`{k}`" for k in missing)
            + " (disarankan oleh `pipelines/base.py`).", literal.lineno)
    return ValidationCheck(
        "get_info() mengembalikan dict", PASS,
        "`get_info()` mengembalikan dict dengan seluruh kunci metadata yang "
        "disarankan.", literal.lineno)


# ── Pemeriksaan KEAMANAN ──────────────────────────────────────────────────

def _check_imports(tree: ast.Module) -> tuple[list[ValidationCheck], set[str]]:
    """Periksa setiap import. Mengembalikan (checks, nama modul yang di-bind)
    — nama binding dipakai untuk mengenali panggilan seperti `os.system(...)`
    dan `getattr(<modul>, ...)`."""
    checks: list[ValidationCheck] = []
    module_bindings: set[str] = set()
    neutral: list[tuple[str, int]] = []

    def _record(module: str, bound_as: str, line: int) -> None:
        root = _root_module(module)
        module_bindings.add(bound_as)
        if root in FORBIDDEN_MODULES:
            checks.append(ValidationCheck(
                "import terlarang", FAIL,
                f"Penggunaan modul `{root}` tidak diizinkan pada pipeline yang "
                f"diunggah ({FORBIDDEN_MODULES[root]}).", line))
        elif root not in ALLOWED_MODULES:
            neutral.append((root, line))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _record(alias.name, (alias.asname or alias.name).split(".")[0],
                        node.lineno)
        elif isinstance(node, ast.ImportFrom):
            if node.level:                      # from . import x → modul lokal
                continue
            module = node.module or ""
            for alias in node.names:
                _record(module, alias.asname or alias.name, node.lineno)

    for root, line in neutral:
        checks.append(ValidationCheck(
            "import di luar daftar", WARN,
            f"Modul `{root}` bukan pustaka ML yang biasa dipakai platform ini. "
            f"Periksa manual sebelum diaktifkan.", line))
    return checks, module_bindings


def _open_writes(call: ast.Call) -> bool:
    """True bila open() dipanggil dengan mode tulis/timpa."""
    mode = None
    if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
        mode = call.args[1].value
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            mode = kw.value.value
    if not isinstance(mode, str):
        return False
    return any(m in mode for m in _WRITE_MODES)


def _check_calls(tree: ast.Module, module_bindings: set[str]) -> list[ValidationCheck]:
    checks: list[ValidationCheck] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _dotted_name(node.func)
        if not name:
            continue
        root, leaf = _root_module(name), name.split(".")[-1]

        # 1. Builtin yang mengeksekusi/memuat kode.
        if name in FORBIDDEN_CALLS:
            checks.append(ValidationCheck(
                "pemanggilan terlarang", FAIL,
                f"Pemanggilan `{name}()` tidak diizinkan "
                f"({FORBIDDEN_CALLS[name]}).", node.lineno))
            continue

        # 2. Pemanggilan pada modul terlarang (mis. os.system, subprocess.run).
        if root in FORBIDDEN_MODULES and "." in name:
            checks.append(ValidationCheck(
                "pemanggilan terlarang", FAIL,
                f"Pemanggilan `{name}()` tidak diizinkan "
                f"({FORBIDDEN_MODULES[root]}).", node.lineno))
            continue

        # 3. getattr/setattr PADA OBJEK MODUL — jalan pintas menuju API
        #    terlarang. Pada objek biasa ini lazim, jadi hanya WARN.
        if leaf in ("getattr", "setattr", "delattr") and "." not in name:
            target = node.args[0] if node.args else None
            target_name = _dotted_name(target) if target is not None else ""
            if target_name and _root_module(target_name) in module_bindings:
                checks.append(ValidationCheck(
                    "pemanggilan terlarang", FAIL,
                    f"`{leaf}()` pada objek modul `{target_name}` tidak "
                    f"diizinkan (menghindari pemeriksaan import).", node.lineno))
            else:
                checks.append(ValidationCheck(
                    "refleksi atribut", WARN,
                    f"`{leaf}()` dipakai — pastikan targetnya bukan modul.",
                    node.lineno))
            continue

        # 4. open() untuk menulis. Membaca berkas dataset tetap diperbolehkan.
        if leaf == "open" and _open_writes(node):
            checks.append(ValidationCheck(
                "penulisan berkas", FAIL,
                "`open()` dengan mode tulis/timpa tidak diizinkan; pipeline "
                "hanya boleh membaca dataset dan mengembalikan PipelineResult.",
                node.lineno))
    return checks


def _check_attributes(tree: ast.Module) -> list[ValidationCheck]:
    checks: list[ValidationCheck] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRIBUTES:
            checks.append(ValidationCheck(
                "atribut dunder terlarang", FAIL,
                f"Akses `{node.attr}` tidak diizinkan "
                f"({FORBIDDEN_ATTRIBUTES[node.attr]}).", node.lineno))
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_ATTRIBUTES:
            checks.append(ValidationCheck(
                "atribut dunder terlarang", FAIL,
                f"Akses `{node.id}` tidak diizinkan "
                f"({FORBIDDEN_ATTRIBUTES[node.id]}).", node.lineno))
    return checks


# ── API publik ────────────────────────────────────────────────────────────

def validate_pipeline_source(source_code: str, filename: str = "") -> ValidationReport:
    """Validasi source pipeline SECARA STATIS. Tidak pernah menjalankan source.

    Mengembalikan ``ValidationReport``: ``valid`` bernilai True hanya bila tidak
    ada satu pun check berstatus ``fail`` (warn tidak menggagalkan). Tidak pernah
    raise — berkas yang tidak dapat diparse dilaporkan sebagai check gagal.
    """
    report = ValidationReport(filename=filename)

    try:
        # ast.parse HANYA mengurai teks menjadi pohon sintaks. Tidak ada kode
        # dari `source_code` yang dievaluasi di sini maupun di mana pun.
        tree = ast.parse(source_code, filename=filename or "<uploaded>")
    except SyntaxError as e:
        report.checks.append(ValidationCheck(
            "sintaks Python", FAIL,
            f"Berkas bukan Python yang valid: {e.msg}.", e.lineno))
        report.valid = False
        report.summary = "Tidak valid — berkas tidak dapat diparse sebagai Python."
        return report
    except (ValueError, RecursionError, MemoryError) as e:  # source ekstrem
        report.checks.append(ValidationCheck(
            "sintaks Python", FAIL, f"Berkas tidak dapat diproses: {e}."))
        report.valid = False
        report.summary = "Tidak valid — berkas tidak dapat diproses."
        return report

    report.checks.append(ValidationCheck(
        "sintaks Python", PASS, "Berkas adalah Python yang valid."))

    import_checks, module_bindings = _check_imports(tree)
    report.checks.extend(import_checks)
    report.checks.extend(_check_calls(tree, module_bindings))
    report.checks.extend(_check_attributes(tree))
    report.checks.extend(_check_structure(tree))

    n_fail, n_warn = len(report.failures), len(report.warnings)
    report.valid = n_fail == 0
    if report.valid:
        report.summary = (
            "Valid — siap didaftarkan"
            + (f" ({n_warn} catatan untuk diperiksa manual)." if n_warn else "."))
    else:
        report.summary = (
            f"Tidak valid — {n_fail} masalah"
            + (f" dan {n_warn} catatan." if n_warn else "."))
    return report


def validate_pipeline_file(path: str | Path) -> ValidationReport:
    """Baca sebuah berkas .py lalu validasi isinya.

    Berkas hanya DIBACA sebagai teks (tidak diimpor, tidak dijalankan). Berguna
    untuk memeriksa berkas yang sudah ada di disk; penyimpanan/staging berkas
    unggahan bukan urusan tahap ini.
    """
    p = Path(path)
    try:
        source = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        report = ValidationReport(filename=p.name)
        report.checks.append(ValidationCheck(
            "berkas terbaca", FAIL, f"Berkas tidak dapat dibaca: {e}."))
        report.summary = "Tidak valid — berkas tidak dapat dibaca."
        return report
    return validate_pipeline_source(source, filename=p.name)

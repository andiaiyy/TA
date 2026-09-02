"""
Dua mode eksekusi — dan garis pemisah di antara keduanya.

Hyperparameter setiap pipeline TERKUNCI sesuai paper rujukan; itulah dasar
klaim "perbandingan yang adil" dan "hasil dapat direplikasi". Modul ini
menambahkan kemungkinan menyesuaikan hyperparameter TANPA merusak klaim itu,
dengan memisahkan dua jenis run secara tegas:

* **Run resmi** (:data:`RUN_MODE_OFFICIAL`) — parameter terkunci, nilai bawaan
  pipeline. Inilah satu-satunya yang menjadi dasar perbandingan & replikasi.
* **Run eksplorasi** (:data:`RUN_MODE_EXPLORATION`) — parameter boleh diubah,
  hasilnya WAJIB ditandai di setiap tempat ia muncul.

Aturan yang menentukan bentuk modul ini:

1. **Bawaan selalu resmi.** :func:`normalize_run_mode` memetakan NULL, string
   kosong, dan nilai tak dikenal ke ``official``. Record lama (dibuat sebelum
   fitur ini ada, kolom ``run_mode`` NULL) karena itu terbaca sebagai run
   resmi — tetap tampil normal, tidak pernah tertandai eksplorasi.
2. **Sumber daftar parameter adalah pipeline itu sendiri.** Kandidat parameter
   dibaca dari ``get_info()['fixed_params']`` pipeline bersangkutan
   (:func:`locked_params`). Tidak ada daftar parameter yang ditulis tangan di
   sini — bila sebuah kunci tidak ada di ``fixed_params``, kunci itu tidak
   pernah bisa disesuaikan.
3. **Fail-closed.** Dari kandidat itu, sebuah kunci hanya menjadi dapat-diubah
   bila (a) tidak termasuk :data:`PROTECTED_PARAMS` — yang mengunci urutan
   tahapan, aturan anti-kebocoran, pemilihan algoritma, dan metode seleksi
   fitur — DAN (b) punya batas aman yang dinyatakan. Kunci numerik tanpa batas
   tetap terkunci; string tanpa daftar pilihan tetap terkunci. Kunci yang tidak
   dikenali TIDAK pernah lolos secara diam-diam.
4. **Tanpa eval/exec.** Nilai divalidasi dengan pemeriksaan tipe dan batas
   biasa lalu diteruskan apa adanya. Tidak ada string masukan pengguna yang
   dipakai untuk membangun objek, mengimpor modul, atau memilih kelas.
"""
from __future__ import annotations

import json
import logging
import math
from orchestrator.user_errors import UserFacingMixin

logger = logging.getLogger(__name__)

# ── Mode ──────────────────────────────────────────────────────────────────

RUN_MODE_OFFICIAL = "official"
RUN_MODE_EXPLORATION = "exploration"
ALL_RUN_MODES = [RUN_MODE_OFFICIAL, RUN_MODE_EXPLORATION]

# Bawaan platform. Dipakai di UI, di orchestrator, dan saat membaca record
# lama — satu konstanta supaya tidak mungkin berbeda di antara ketiganya.
DEFAULT_RUN_MODE = RUN_MODE_OFFICIAL

RUN_MODE_LABELS = {
    RUN_MODE_OFFICIAL: "Run resmi",
    RUN_MODE_EXPLORATION: "Run eksplorasi",
}
RUN_MODE_BADGES = {
    RUN_MODE_OFFICIAL: "🔒 Resmi",
    RUN_MODE_EXPLORATION: "🧪 Eksplorasi",
}
RUN_MODE_HINTS = {
    RUN_MODE_OFFICIAL: "Parameter terkunci sesuai paper rujukan.",
    RUN_MODE_EXPLORATION: "Parameter disesuaikan — di luar perbandingan resmi.",
}

# Peringatan yang WAJIB tampil saat mode eksplorasi dipilih. Ringkas: dua baris.
EXPLORATION_WARNING = (
    "Hasil run eksplorasi TIDAK masuk perbandingan resmi dan tidak dipakai "
    "sebagai dasar replikasi. Setiap tampilan hasilnya diberi penanda "
    f"{RUN_MODE_BADGES[RUN_MODE_EXPLORATION]}."
)

# Peringatan saat kedua mode disandingkan. Setara bobotnya dengan peringatan
# semantik metrik lintas keluarga pipeline (ui/components/experiment_table.py).
MIXED_MODE_WARNING = (
    "Pilihan ini mencampur run resmi (parameter terkunci) dengan run "
    "eksplorasi (parameter disesuaikan). Keduanya TIDAK sebanding: perbedaan "
    "angka bisa berasal dari perbedaan parameter, bukan dari pipeline-nya."
)


def normalize_run_mode(value) -> str:
    """Mode yang sah dari nilai apa pun.

    NULL, string kosong, dan nilai tak dikenal menjadi ``official``. Ini yang
    membuat 48 record lama (kolom ``run_mode`` belum ada saat itu) terbaca
    sebagai run RESMI, bukan eksplorasi — dan tidak ada satu pun record yang
    disembunyikan karena modenya tidak diketahui.
    """
    text = (value or "").strip().lower() if isinstance(value, str) else ""
    return text if text in ALL_RUN_MODES else DEFAULT_RUN_MODE


def is_exploration(value) -> bool:
    """True hanya bila modenya EKSPLORASI secara eksplisit."""
    return normalize_run_mode(value) == RUN_MODE_EXPLORATION


def run_mode_label(value) -> str:
    return RUN_MODE_LABELS[normalize_run_mode(value)]


def run_mode_badge(value) -> str:
    """Penanda pendek untuk tabel/CSV/PDF. SELALU terisi — tidak ada baris
    yang tampil tanpa mode, karena "tidak tahu" pun dipetakan ke resmi."""
    return RUN_MODE_BADGES[normalize_run_mode(value)]


# ── Parameter yang TIDAK boleh disesuaikan ────────────────────────────────
# Empat hal yang dikunci kontrak platform: urutan tahapan, aturan
# anti-kebocoran, pemilihan algoritma, dan metode seleksi fitur. Ditambah dua
# alasan praktis: batas sumber daya worker dan kontrak pelaporan metrik.

CAT_ALGORITHM = "pemilihan algoritma"
CAT_STAGES = "urutan & isi tahapan praproses"
CAT_SPLIT = "aturan pembagian latih/uji"
CAT_FEATURE_SELECTION = "metode seleksi fitur"
CAT_LEAKAGE = "pengaman anti-kebocoran"
CAT_RESOURCE = "batas sumber daya worker"
CAT_REPORTING = "kontrak pelaporan metrik"

# kunci -> (kategori, alasan yang ditampilkan apa adanya ke pengguna)
PROTECTED_PARAMS: dict[str, tuple[str, str]] = {
    "models": (CAT_ALGORITHM,
               "menentukan algoritma yang dilatih"),
    "balancing": (CAT_STAGES,
                  "tahap penyeimbangan kelas — mengubahnya mengubah praproses"),
    "scaler": (CAT_STAGES,
               "tahap penskalaan fitur — mengubahnya mengubah praproses"),
    "pca": (CAT_FEATURE_SELECTION,
            "metode reduksi/seleksi fitur"),
    "test_size": (CAT_SPLIT,
                  "proporsi split; menyamakannya antar pipeline adalah syarat perbandingan"),
    "stratify": (CAT_SPLIT,
                 "stratifikasi split menjaga distribusi kelas data uji"),
    "fs_sample_rows": (CAT_FEATURE_SELECTION,
                       "cakupan data untuk seleksi fitur"),
    "enforce_row_level_conversion_cap": (CAT_LEAKAGE,
                                         "pengaman konversi tingkat baris"),
    "corr_leak_sample_rows": (CAT_LEAKAGE,
                              "cakupan pemeriksaan kebocoran korelasi"),
    "modeling_train_rows": (CAT_SPLIT,
                            "banyak baris latih — mengubahnya mengubah data yang dilihat model"),
    "visualization_sample_rows": (CAT_RESOURCE,
                                  "batas memori tahap ekspor/visualisasi"),
    "n_jobs": (CAT_RESOURCE,
               "paralelisme worker, bukan hyperparameter model"),
    "cv_folds": (CAT_RESOURCE,
                 "biaya cross-validation di worker"),
    "learning_curve_cv": (CAT_RESOURCE,
                          "biaya diagnostik learning curve, bukan model yang dilaporkan"),
    "probability": (CAT_REPORTING,
                    "dibutuhkan predict_proba untuk ROC-AUC yang dilaporkan"),
}


# ── Batas aman parameter yang boleh disesuaikan ───────────────────────────
# Batas dipilih supaya eksplorasi tetap bermakna tetapi tidak bisa memicu beban
# komputasi ekstrem pada worker (RAM efektif ~3.5 GB). Kunci yang TIDAK ada di
# sini tetap terkunci — fail-closed, bukan "diizinkan karena tidak dilarang".

# Batas keras platform, berlaku DI ATAS batas mana pun (termasuk bila sebuah
# pipeline menyatakan `param_bounds` sendiri di get_info()).
HARD_INT_CAP = 100_000
HARD_FLOAT_CAP = 1e6

PARAM_BOUNDS: dict[str, tuple[float, float]] = {
    "n_estimators": (1, 500),
    "n_neighbors": (1, 100),
    "max_iter": (1, 20_000),
    # Seed: batasnya sama dengan HARD_INT_CAP, bukan 2**31-1, supaya batas
    # yang DITAMPILKAN di formulir sama dengan batas yang benar-benar
    # ditegakkan. Seed apa pun di rentang ini tetap mengunci hasil.
    "random_state": (0, HARD_INT_CAP),
}

BOUNDS_NOTE = (
    "Batas ditetapkan platform agar eksplorasi tidak memicu beban komputasi "
    "ekstrem pada worker."
)
LOCKED_NO_BOUNDS = "belum ada batas aman yang ditetapkan platform"
LOCKED_NO_CHOICES = "nilai teks tanpa daftar pilihan tidak diteruskan ke model"
LOCKED_UNSUPPORTED = "tipe nilainya tidak dapat disesuaikan dari formulir"


class ParamError(UserFacingMixin, ValueError):
    """Parameter masukan pengguna ditolak. Pesannya ditampilkan apa adanya."""


def _pipeline_info(pipeline_id: str, info: dict | None = None) -> dict:
    """``get_info()`` pipeline — disuntikkan saat menguji, dibaca saat berjalan."""
    if info is not None:
        return info or {}
    try:
        from orchestrator.execution_service import get_pipeline_info
        return get_pipeline_info(pipeline_id) or {}
    except Exception:                       # pragma: no cover - defensif
        logger.debug("get_info() tidak terbaca untuk %s", pipeline_id, exc_info=True)
        return {}


def locked_params(pipeline_id: str, *, info: dict | None = None) -> dict:
    """``fixed_params`` pipeline apa adanya — SATU-SATUNYA sumber kandidat.

    Dikembalikan sebagai salinan supaya pemanggil tidak bisa menulis balik ke
    dict milik pipeline.
    """
    params = _pipeline_info(pipeline_id, info).get("fixed_params")
    return dict(params) if isinstance(params, dict) else {}


def _declared_bounds(info: dict, key: str):
    """Batas yang dinyatakan pipeline sendiri (opsional, boleh tidak ada)."""
    declared = info.get("param_bounds")
    if not isinstance(declared, dict):
        return None
    pair = declared.get(key)
    if (isinstance(pair, (list, tuple)) and len(pair) == 2
            and all(isinstance(x, (int, float)) and not isinstance(x, bool)
                    for x in pair)):
        return float(pair[0]), float(pair[1])
    return None


def _choices(info: dict, key: str):
    """Daftar pilihan untuk parameter teks (opsional)."""
    declared = info.get("param_choices")
    if not isinstance(declared, dict):
        return None
    values = declared.get(key)
    if isinstance(values, (list, tuple)) and values and all(
            isinstance(v, str) for v in values):
        return list(values)
    return None


def _spec_for(key, default, info: dict) -> dict | None:
    """Spesifikasi satu parameter yang boleh disesuaikan, atau None bila tidak.

    Mengembalikan ``{"key","default","type","min","max","choices"}``.
    """
    if key in PROTECTED_PARAMS:
        return None

    if isinstance(default, bool):
        return {"key": key, "default": default, "type": "bool",
                "min": None, "max": None, "choices": None}

    if isinstance(default, int):
        bounds = PARAM_BOUNDS.get(key) or _declared_bounds(info, key)
        if bounds is None:
            return None
        lo, hi = int(max(bounds[0], -HARD_INT_CAP)), int(min(bounds[1], HARD_INT_CAP))
        if lo > hi:
            return None
        return {"key": key, "default": default, "type": "int",
                "min": lo, "max": hi, "choices": None}

    if isinstance(default, float):
        bounds = PARAM_BOUNDS.get(key) or _declared_bounds(info, key)
        if bounds is None:
            return None
        lo, hi = max(bounds[0], -HARD_FLOAT_CAP), min(bounds[1], HARD_FLOAT_CAP)
        if lo > hi:
            return None
        return {"key": key, "default": default, "type": "float",
                "min": float(lo), "max": float(hi), "choices": None}

    if isinstance(default, str):
        choices = _choices(info, key)
        if not choices or default not in choices:
            return None
        return {"key": key, "default": default, "type": "choice",
                "min": None, "max": None, "choices": choices}

    return None


def tunable_params(pipeline_id: str, *, info: dict | None = None) -> dict:
    """{kunci: spesifikasi} untuk parameter yang BOLEH disesuaikan.

    Urutannya mengikuti urutan ``fixed_params`` supaya formulir tampil dalam
    urutan yang sama dengan dokumentasi pipeline.
    """
    pinfo = _pipeline_info(pipeline_id, info)
    out: dict[str, dict] = {}
    for key, default in locked_params(pipeline_id, info=pinfo).items():
        spec = _spec_for(key, default, pinfo)
        if spec is not None:
            out[key] = spec
    return out


def protected_reason(key, default=None, info: dict | None = None) -> str:
    """Alasan sebuah kunci tetap terkunci — ditampilkan ke pengguna."""
    if key in PROTECTED_PARAMS:
        category, reason = PROTECTED_PARAMS[key]
        return f"{category} — {reason}"
    if isinstance(default, bool):           # bool tidak pernah sampai sini
        return LOCKED_UNSUPPORTED           # pragma: no cover - defensif
    if isinstance(default, (int, float)):
        return LOCKED_NO_BOUNDS
    if isinstance(default, str):
        return LOCKED_NO_CHOICES
    return LOCKED_UNSUPPORTED


def param_rows(pipeline_id: str, *, info: dict | None = None) -> list[dict]:
    """SELURUH ``fixed_params`` + status tiap kunci, untuk transparansi.

    Dipakai juga pada mode resmi: parameter tetap DITAMPILKAN, hanya tidak
    dapat diubah. Tiap baris:
    ``{"key","default","tunable","spec","reason"}``.
    """
    pinfo = _pipeline_info(pipeline_id, info)
    specs = tunable_params(pipeline_id, info=pinfo)
    rows = []
    for key, default in locked_params(pipeline_id, info=pinfo).items():
        spec = specs.get(key)
        rows.append({
            "key": key,
            "default": default,
            "tunable": spec is not None,
            "spec": spec,
            "reason": "" if spec else protected_reason(key, default, pinfo),
        })
    return rows


# ── Validasi masukan pengguna ─────────────────────────────────────────────

def _check_number(key, value, spec):
    lo, hi = spec["min"], spec["max"]
    if value < lo or value > hi:
        raise ParamError(
            f"`{key}` = {value} di luar batas yang diizinkan ({lo}–{hi}). "
            + BOUNDS_NOTE
        )
    return value


def validate_override(key, value, spec) -> object:
    """Satu parameter: tipe harus sesuai bawaannya, nilai harus dalam batas.

    Tidak ada konversi dari teks bebas, tidak ada ``eval``/``exec``, tidak ada
    objek yang dibangun dari masukan pengguna — hanya angka/boolean yang lolos.
    """
    kind = spec["type"]

    if kind == "bool":
        if not isinstance(value, bool):
            raise ParamError(
                f"`{key}` harus bernilai benar/salah (boolean).",
                key="err.param_not_bool", values={"param": key})
        return value

    if kind == "int":
        # `bool` adalah subclass `int` di Python — tolak eksplisit supaya
        # True tidak diam-diam menjadi 1.
        if isinstance(value, bool) or not isinstance(value, int):
            raise ParamError(
                f"`{key}` harus bilangan bulat (bawaannya {spec['default']!r}).",
                key="err.param_not_int",
                values={"param": key, "default": repr(spec["default"])}
            )
        return _check_number(key, value, spec)

    if kind == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ParamError(
                f"`{key}` harus bilangan (bawaannya {spec['default']!r}).",
                key="err.param_not_number",
                values={"param": key, "default": repr(spec["default"])}
            )
        value = float(value)
        if math.isnan(value) or math.isinf(value):
            raise ParamError(f"`{key}` harus bilangan berhingga.",
                             key="err.param_not_finite",
                             values={"param": key})
        return _check_number(key, value, spec)

    if kind == "choice":
        if not isinstance(value, str):
            raise ParamError(
                f"`{key}` harus salah satu pilihan yang tersedia.",
                key="err.param_not_choice_type", values={"param": key})
        if value not in spec["choices"]:
            raise ParamError(
                f"`{key}` = {value!r} bukan pilihan yang tersedia "
                f"({', '.join(spec['choices'])}).",
                key="err.param_bad_choice",
                values={"param": key, "value": repr(value),
                        "choices": ", ".join(spec["choices"])}
            )
        return value

    raise ParamError(f"`{key}` tidak dapat disesuaikan.")   # pragma: no cover


def validate_overrides(pipeline_id: str, overrides: dict | None, *,
                       info: dict | None = None) -> dict:
    """Seluruh override untuk satu pipeline. Menaikkan :class:`ParamError`.

    Kunci yang tidak ada pada ``fixed_params`` pipeline ini DITOLAK — termasuk
    kunci yang valid untuk pipeline lain. Kunci terkunci ditolak dengan
    menyebut alasannya.
    """
    if not overrides:
        return {}
    if not isinstance(overrides, dict):
        raise ParamError("Parameter harus berupa pasangan nama–nilai.",
                         key="err.param_not_a_mapping")

    pinfo = _pipeline_info(pipeline_id, info)
    locked = locked_params(pipeline_id, info=pinfo)
    specs = tunable_params(pipeline_id, info=pinfo)

    clean: dict = {}
    for key, value in overrides.items():
        if key not in locked:
            raise ParamError(
                f"`{key}` bukan parameter pipeline ini. Hanya kunci pada "
                f"fixed_params yang dapat disesuaikan"
                + (f" ({', '.join(sorted(locked))})." if locked
                   else " — pipeline ini tidak mendeklarasikan fixed_params.")
            )
        if key not in specs:
            raise ParamError(
                f"`{key}` terkunci: {protected_reason(key, locked[key], pinfo)}.",
                key="err.param_locked",
                values={"param": key,
                        "reason": protected_reason(key, locked[key], pinfo)}
            )
        clean[key] = validate_override(key, value, specs[key])
    return clean


# ── Penyelesaian parameter satu run ───────────────────────────────────────

def resolve_params(pipeline_id: str, run_mode=None, overrides: dict | None = None,
                   *, info: dict | None = None) -> dict:
    """Parameter yang BENAR-BENAR dipakai satu run.

    Mengembalikan::

        {"run_mode": str, "params": dict, "overrides": dict,
         "changed": [kunci], "locked": dict}

    ``params`` adalah nilai terkunci yang ditimpa override yang sudah lolos
    validasi. **Pada mode resmi, override dibuang sebelum apa pun dilakukan** —
    tidak ada jalur yang membuat run resmi memakai nilai yang diubah.
    """
    pinfo = _pipeline_info(pipeline_id, info)
    locked = locked_params(pipeline_id, info=pinfo)
    mode = normalize_run_mode(run_mode)

    if mode == RUN_MODE_OFFICIAL:
        if overrides:
            logger.info(
                "Run resmi %s: %d override diabaikan sepenuhnya (parameter terkunci)",
                pipeline_id, len(overrides),
            )
        return {"run_mode": RUN_MODE_OFFICIAL, "params": dict(locked),
                "overrides": {}, "changed": [], "locked": dict(locked)}

    clean = validate_overrides(pipeline_id, overrides, info=pinfo)
    params = {**locked, **clean}
    changed = [k for k, v in clean.items() if locked.get(k) != v]
    return {"run_mode": RUN_MODE_EXPLORATION, "params": params,
            "overrides": clean, "changed": changed, "locked": dict(locked)}


def changed_keys(params: dict | None, locked: dict | None) -> list[str]:
    """Kunci yang nilainya BERBEDA dari bawaan — untuk penandaan visual."""
    params, locked = params or {}, locked or {}
    return [k for k, v in params.items() if k in locked and locked[k] != v]


# ── Serialisasi untuk basis data & artefak ────────────────────────────────

def dump_params(params: dict | None) -> str | None:
    """JSON untuk kolom ``params_used`` / metadata artefak. None bila kosong.

    ``default=str`` menjaga nilai eksotis (mis. list) tetap terbaca alih-alih
    membuat penyimpanan gagal — pencatatan tidak boleh menggagalkan run.
    """
    if not params:
        return None
    try:
        return json.dumps(params, sort_keys=True, default=str)
    except Exception:                       # pragma: no cover - defensif
        logger.exception("params_used tidak dapat diserialkan")
        return None


def load_params(raw) -> dict:
    """Kebalikan :func:`dump_params`. Nilai rusak/kosong menjadi ``{}``."""
    if isinstance(raw, dict):
        return dict(raw)
    if not raw or not isinstance(raw, str):
        return {}
    try:
        value = json.loads(raw)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def format_params(params: dict | None, locked: dict | None = None) -> str:
    """Satu baris ringkas: ``n_estimators=250 (bawaan 100); random_state=7``.

    Kunci yang berbeda dari bawaan membawa nilai bawaannya di dalam kurung,
    sehingga pembaca tahu apa yang diubah tanpa membuka apa pun.
    """
    params = params or {}
    if not params:
        return ""
    locked = locked or {}
    parts = []
    for key in sorted(params):
        value = params[key]
        if key in locked and locked[key] != value:
            parts.append(f"{key}={value} (bawaan {locked[key]})")
        else:
            parts.append(f"{key}={value}")
    return "; ".join(parts)


def params_of(record: dict | None) -> dict:
    """Parameter yang dicatat untuk satu record eksperimen (``{}`` bila lama)."""
    return load_params((record or {}).get("params_used"))


def mode_of(record: dict | None) -> str:
    """Mode satu record eksperimen. Record lama (NULL) -> resmi."""
    return normalize_run_mode((record or {}).get("run_mode"))

"""
Penyajian visual instruksi kontribusi — diagram alur, tabel kontrak, chip modul.

Menggantikan paragraf panjang di halaman "Add Pipeline & Dataset" TANPA
menghilangkan informasinya: yang padat tampil di muka (diagram + tabel + chip +
catatan penting), yang rinci pindah ke expander.

Prinsip yang dijaga modul ini:

* **Nilai selalu dari sumber terstruktur.** Nama kelas induk, metode wajib,
  kunci metadata, daftar modul/pemanggilan diambil dari konstanta
  ``orchestrator/pipeline_validator``; format berkas & kolom label dari
  ``contracts/dataset_schemas`` dan dict persyaratan terpusat. Tidak ada daftar
  yang diketik ulang sebagai teks statis — bila konstanta berubah, tampilan
  ikut berubah.
* **Catatan faktual tidak boleh hilang.** "Pemeriksaan statis (berkas dibaca,
  bukan dijalankan)", "lolos periksa ≠ langsung aktif", dan catatan angka
  berbasis cuplikan tetap tampil di tampilan utama.
* **Aman untuk tema terang & gelap.** Teks/garis SVG memakai ``currentColor``
  sehingga mengikuti warna teks Streamlit; latar memakai rgba transparan; warna
  aksen memakai nada tengah yang terbaca di kedua tema, dengan penyesuaian
  tambahan pada ``prefers-color-scheme: dark``.
* **Animasi halus & dapat dimatikan.** Hanya garis putus yang mengalir dan
  denyut bergiliran; seluruhnya mati pada ``prefers-reduced-motion: reduce``.
* **Konten dinamis di-escape** sebelum masuk ke markup.
"""
from __future__ import annotations

from html import escape

import streamlit as st

# Jumlah chip yang ditampilkan sebelum diringkas menjadi "+N".
CHIP_PREVIEW = 5

# Warna aksen nada tengah: terbaca di atas latar terang maupun gelap. Nilai
# dinaikkan kecerahannya pada tema gelap lewat prefers-color-scheme.
_CSS = """
<style>
.ids-flow svg { width: 100%; height: auto; display: block; }
.ids-flow text { fill: currentColor; }
.ids-flow .ids-node { stroke: currentColor; fill: rgba(127,127,127,.12); }
.ids-flow .ids-link {
    stroke: currentColor; stroke-width: 2; stroke-dasharray: 6 6;
    opacity: .45; animation: ids-dash 1.6s linear infinite;
}
.ids-flow .ids-pulse { animation: ids-pulse 3s ease-in-out infinite; transform-origin: center; }
@keyframes ids-dash { to { stroke-dashoffset: -24; } }
@keyframes ids-pulse {
    0%, 100% { opacity: .55; }
    50%      { opacity: 1; }
}
.ids-chips { display: flex; flex-wrap: wrap; gap: .3rem; margin: .2rem 0 .1rem; }
.ids-chip {
    display: inline-block; padding: .08rem .5rem; border-radius: 999px;
    font-size: .78rem; line-height: 1.5; white-space: nowrap;
    border: 1px solid currentColor;
}
.ids-chip.ok   { color: #15803d; background: rgba(22,163,74,.12); }
.ids-chip.no   { color: #b91c1c; background: rgba(220,38,38,.12); }
.ids-chip.more { color: inherit; background: rgba(127,127,127,.14); opacity: .8; }
.ids-note {
    border-left: 3px solid currentColor; padding: .35rem .7rem; margin: .4rem 0;
    background: rgba(127,127,127,.10); border-radius: 0 6px 6px 0;
    font-size: .86rem; opacity: .95;
}
@media (prefers-color-scheme: dark) {
    .ids-chip.ok { color: #4ade80; }
    .ids-chip.no { color: #f87171; }
}
@media (prefers-reduced-motion: reduce) {
    .ids-flow .ids-link, .ids-flow .ids-pulse { animation: none !important; }
}
</style>
"""


def inject_css() -> None:
    """Sisipkan stylesheet sekali per panel.

    Dipanggil dari fungsi render TERATAS saja — bukan dari tiap komponen —
    supaya tidak ada blok <style> berulang. (Tidak bisa di-cache lintas rerun:
    Streamlit membangun ulang halaman setiap kali.)

    Publik karena panel konteks halaman (``ui/components/contribute_context``)
    memakai komponen visual yang sama dan perlu gaya yang sama.
    """
    st.markdown(_CSS, unsafe_allow_html=True)


# ── Diagram alur ──────────────────────────────────────────────────────────

def flow_diagram_svg(steps: list[tuple[str, str]], *, alt: str) -> str:
    """SVG alur horizontal: lingkaran + ikon + label, dihubungkan garis.

    ``steps`` = [(ikon, label)]. Seluruh teks di-escape. Memakai viewBox +
    lebar 100% agar responsif dan tidak terpotong saat sidebar terbuka.
    ``alt`` menjadi <title> (terbaca pembaca layar) DAN keterangan teks di
    bawah diagram, sehingga informasinya tidak hilang bila SVG tidak tampil.
    """
    if not steps:
        return ""
    width, height = 720, 132
    gap = width / len(steps)
    radius = 26
    parts: list[str] = []

    for index in range(len(steps) - 1):        # garis dulu, agar di belakang
        x1 = gap * (index + 0.5) + radius + 6
        x2 = gap * (index + 1.5) - radius - 6
        parts.append(
            f'<line class="ids-link" x1="{x1:.1f}" y1="46" x2="{x2:.1f}" y2="46" />')

    for index, (icon, label) in enumerate(steps):
        cx = gap * (index + 0.5)
        delay = index * 0.45
        parts.append(
            f'<g class="ids-pulse" style="animation-delay:{delay:.2f}s">'
            f'<circle class="ids-node" cx="{cx:.1f}" cy="46" r="{radius}" '
            f'stroke-width="1.5" />'
            f'<text x="{cx:.1f}" y="54" text-anchor="middle" font-size="22">'
            f'{escape(icon)}</text></g>'
        )
        parts.append(
            f'<text x="{cx:.1f}" y="100" text-anchor="middle" font-size="12" '
            f'opacity=".85">{escape(label)}</text>'
        )
        parts.append(
            f'<text x="{cx:.1f}" y="116" text-anchor="middle" font-size="10" '
            f'opacity=".55">{index + 1}</text>'
        )

    return (
        f'<div class="ids-flow" role="img" aria-label="{escape(alt)}">'
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">'
        f'<title>{escape(alt)}</title>{"".join(parts)}</svg></div>'
    )


def render_flow(steps: list[tuple[str, str]], *, alt: str) -> None:
    """Diagram alur + teks alternatifnya.

    Teks alternatif TIDAK lagi diulang sebagai baris keterangan di bawah
    diagram: ia sudah dibawa SVG-nya sendiri lewat `<title>` dan `aria-label`,
    yang dibacakan pembaca layar dan muncul sebagai tooltip saat disorot.
    """
    st.markdown(flow_diagram_svg(steps, alt=alt), unsafe_allow_html=True)


# ── Chip ──────────────────────────────────────────────────────────────────

def chips_html(items: list[str], tone: str, *, preview: int = CHIP_PREVIEW) -> str:
    """Deretan chip; sisanya diringkas jadi "+N".

    ``N`` DIHITUNG dari panjang daftar yang diberikan (yang berasal dari
    konstanta), bukan angka tetap.
    """
    shown = list(items)[:preview]
    rest = len(items) - len(shown)
    chips = "".join(
        f'<span class="ids-chip {tone}">{escape(str(item))}</span>' for item in shown)
    if rest > 0:
        from ui.i18n import t
        chips += (f'<span class="ids-chip more">'
                  f'{escape(t("ins.chip_more", count=rest))}</span>')
    return f'<div class="ids-chips">{chips}</div>'


def render_chips(items: list[str], tone: str) -> None:
    st.markdown(chips_html(items, tone), unsafe_allow_html=True)


def render_note(text: str) -> None:
    """Catatan penting: blok kecil bergaris aksen, tetap di tampilan utama."""
    st.markdown(f'<div class="ids-note">{text}</div>', unsafe_allow_html=True)


# ── Instruksi jalur PIPELINE ──────────────────────────────────────────────

PIPELINE_FLOW = [
    ("📤", "Unggah"),
    ("🔍", "Periksa otomatis"),
    ("👤", "Tinjau Research Admin"),
    ("✅", "Aktif"),
]
PIPELINE_FLOW_ALT = ("Alur: unggah berkas, diperiksa otomatis secara statis, "
                     "ditinjau Research Admin, lalu aktif.")


def render_pipeline_instructions() -> None:
    """Diagram + tabel kontrak + chip modul + catatan; rincian di expander."""
    from orchestrator.pipeline_validator import (
        ALLOWED_MODULES, BASE_CLASS_NAME, EXPECTED_INFO_KEYS, FORBIDDEN_CALLS,
        FORBIDDEN_MODULES, REQUIRED_METHODS, RUN_FIRST_PARAM, RUN_PROGRESS_PARAM,
    )

    from ui.i18n import t

    inject_css()
    render_flow(pipeline_flow_display(), alt=t("ins.flow_pipeline_alt"))

    methods = " · ".join(f"`{m}()`" for m in REQUIRED_METHODS)
    info_keys = ", ".join(f"`{k}`" for k in EXPECTED_INFO_KEYS)
    st.markdown(
        f"| {t('ins.col_aspect')} | {t('ins.col_rule')} |\n"
        "| --- | --- |\n"
        f"| {t('ins.row_base_class')} | `{BASE_CLASS_NAME}` |\n"
        f"| {t('ins.row_required_methods')} | {methods} |\n"
        f"| {t('ins.row_run_signature')} | "
        f"`({RUN_FIRST_PARAM}, {RUN_PROGRESS_PARAM}=None)` "
        f"→ `PipelineResult` |\n"
        f"| {t('ins.row_entry_point')} | {t('ins.rule_entry_point')} |\n"
        f"| {t('ins.row_anti_leak')} | {t('ins.rule_anti_leak')} |\n"
        f"| {t('ins.row_info_keys')} | {info_keys} |"
    )

    cols = st.columns(2)
    with cols[0]:
        st.markdown(t("ins.modules_allowed", count=len(ALLOWED_MODULES)))
        render_chips(sorted(ALLOWED_MODULES), "ok")
    with cols[1]:
        st.markdown(t("ins.modules_rejected", count=len(FORBIDDEN_MODULES)))
        render_chips(sorted(FORBIDDEN_MODULES), "no")

    render_note(t("ins.static_check_note"))

    st.markdown(t("ins.expected_shape"))
    st.code(pipeline_skeleton(), language="python")

    render_contract_docs()

    render_mistakes(common_pipeline_mistakes(),
                    title=t("ins.mistakes_pipeline_title"))

    with st.expander(t("ins.exp_full_requirements"), expanded=False):
        st.markdown(t("ins.modules_reasonable"))
        st.markdown(", ".join(f"`{m}`" for m in sorted(ALLOWED_MODULES)))
        st.markdown(t("ins.modules_forbidden"))
        st.markdown(", ".join(f"`{m}`" for m in sorted(FORBIDDEN_MODULES)))
        st.markdown(t("ins.calls_forbidden"))
        st.markdown(", ".join(f"`{c}()`" for c in sorted(FORBIDDEN_CALLS)))
        # SATU baris penutup menggantikan tiga keterangan kecil yang sebelumnya
        # tersebar di antara ketiga daftar di atas.
        st.caption(t("ins.outside_list_caption"),
                   help=t("ins.outside_list_help"))


# ── Contoh kerangka pipeline (dari konstanta kontrak) ─────────────────────

def pipeline_skeleton() -> str:
    """Kerangka kelas pipeline MINIMAL — bentuk yang diharapkan validator.

    Nama kelas induk, nama metode wajib, nama parameter ``run()``, dan kunci
    ``get_info()`` seluruhnya dibaca dari konstanta validator. Jalur impornya
    diambil dari ``__module__`` kelas yang sebenarnya, jadi contoh ini tetap
    benar bila berkas kontraknya dipindah.
    """
    from orchestrator.pipeline_validator import (
        BASE_CLASS_NAME, EXPECTED_INFO_KEYS, REQUIRED_METHODS, RUN_FIRST_PARAM,
        RUN_PROGRESS_PARAM,
    )

    base_module, result_module = _contract_modules()
    run_method, info_method = REQUIRED_METHODS[0], REQUIRED_METHODS[1]
    info_lines = "\n".join(f'            "{key}": ...,' for key in EXPECTED_INFO_KEYS)

    return (
        f"from {base_module} import {BASE_CLASS_NAME}\n"
        f"from {result_module} import PipelineResult\n"
        f"\n"
        f"\n"
        f"class MyPipeline({BASE_CLASS_NAME}):\n"
        f"    def {run_method}(self, {RUN_FIRST_PARAM}, {RUN_PROGRESS_PARAM}=None):\n"
        f"        # split dulu, baru fit scaler/PCA/penyeimbang pada data latih\n"
        f"        ...\n"
        f"        return PipelineResult(...)\n"
        f"\n"
        f"    def {info_method}(self):\n"
        f"        return {{\n"
        f"{info_lines}\n"
        f"        }}\n"
    )


def _contract_modules() -> tuple[str, str]:
    """(modul BasePipeline, modul PipelineResult) — dari kelas nyata bila dapat
    diimpor, dengan nilai cadangan yang sama dengan pipeline bawaan."""
    base_module, result_module = "pipelines.base", "contracts.pipeline_contracts"
    try:                                     # pragma: no cover - jalur normal
        from pipelines.base import BasePipeline as _Base
        base_module = _Base.__module__
    except Exception:                        # pragma: no cover - defensif
        pass
    try:                                     # pragma: no cover - jalur normal
        from contracts.pipeline_contracts import PipelineResult as _Result
        result_module = _Result.__module__
    except Exception:                        # pragma: no cover - defensif
        pass
    return base_module, result_module


# ── Dokumentasi KONTRAK pipeline ──────────────────────────────────────────
# Nama field dibaca TERPROGRAM dari definisi dataclass di
# contracts/pipeline_contracts.py. Ini bukan kenyamanan, melainkan pengaman:
# dokumentasi yang menyebut nama field yang tidak ada akan menghasilkan
# pipeline yang GAGAL validasi dan gagal saat dijalankan. Karena dibaca dari
# sumbernya, dokumentasi ini tidak bisa basi — mengganti nama field di kontrak
# langsung mengubah tabel yang tampil di sini.

# Arti tiap field. Kunci HARUS cocok dengan nama field nyata; bila sebuah field
# tidak punya penjelasan di sini, tabelnya tetap menampilkan field itu (dengan
# arti kosong) alih-alih menyembunyikannya.
# Nilainya kini KUNCI katalog, bukan kalimat: konstanta modul dievaluasi
# sekali saat impor, jadi kalimatnya akan membeku pada satu bahasa.
_INPUT_MEANING = {
    "df": "ins.fld_df",
    "label_column": "ins.fld_label_column",
    "dataset_type": "ins.fld_dataset_type",
    "test_size": "ins.fld_test_size",
    "random_state": "ins.fld_random_state",
    "dataset_path": "ins.fld_dataset_path",
    "param_overrides": "ins.fld_param_overrides",
}
_RESULT_MEANING = {
    "accuracy": "ins.fld_accuracy",
    "precision": "ins.fld_precision",
    "recall": "ins.fld_recall",
    "f1_score": "ins.fld_f1_score",
    "confusion_matrix": "ins.fld_confusion_matrix",
    "model": "ins.fld_model",
    "feature_names": "ins.fld_feature_names",
    "label_mapping": "ins.fld_label_mapping",
    "extra_info": "ins.fld_extra_info",
}


def contract_fields(cls, meanings) -> list[dict]:
    """(nama, tipe, wajib/opsional, arti) dari definisi dataclass NYATA.

    ``meanings`` memetakan nama field → kunci katalog. Field tanpa kunci tetap
    muncul dengan arti kosong, bukan disembunyikan.
    """
    import dataclasses

    from ui.i18n import t

    out = []
    for f in dataclasses.fields(cls):
        optional = (f.default is not dataclasses.MISSING
                    or f.default_factory is not dataclasses.MISSING)
        type_name = getattr(f.type, "__name__", None) or str(f.type)
        out.append({
            "name": f.name,
            "type": type_name.replace("typing.", ""),
            "required": not optional,
            "meaning": t(meanings[f.name]) if f.name in meanings else "",
        })
    return out


def pipeline_input_fields() -> list[dict]:
    from contracts.pipeline_contracts import PipelineInput
    return contract_fields(PipelineInput, _INPUT_MEANING)


def pipeline_result_fields() -> list[dict]:
    from contracts.pipeline_contracts import PipelineResult
    return contract_fields(PipelineResult, _RESULT_MEANING)


# Tahapan eksekusi. `owner` menyatakan SIAPA yang mengerjakan — platform sudah
# memparsing & memvalidasi dataset sebelum pipeline dipanggil, dan platform pula
# yang menyimpan artefak. Menyiratkan pipeline mengerjakan semuanya akan
# menyesatkan penulis pipeline.
OWNER_PLATFORM = "Platform"
OWNER_PIPELINE = "Pipeline"

EXECUTION_STAGES = (
    (1, "Validasi masukan", OWNER_PLATFORM,
     "Dataset diparsing & diperiksa sebelum pipeline dipanggil."),
    (2, "Pisah latih/uji", OWNER_PIPELINE, "Split sebelum praproses apa pun."),
    (3, "Fit praproses pada data latih SAJA", OWNER_PIPELINE,
     "Scaler/PCA/penyeimbang di-fit hanya di data latih."),
    (4, "Transformasi latih & uji", OWNER_PIPELINE,
     "Data uji hanya ditransformasi, tidak pernah ikut di-fit."),
    (5, "Latih model", OWNER_PIPELINE, "Parameter terkunci dari fixed_params."),
    (6, "Prediksi data uji", OWNER_PIPELINE, ""),
    (7, "Hitung metrik", OWNER_PIPELINE, ""),
    (8, "Simpan artefak", OWNER_PLATFORM,
     "Model, metrik, dan metadata ditulis platform."),
    (9, "Kembalikan PipelineResult", OWNER_PIPELINE, ""),
)

ANTI_LEAK_STAGES = (2, 3)
ANTI_LEAK_NOTE = ("Langkah 2–3 adalah aturan anti-kebocoran: split DULU, baru "
                  "fit praproses — dan hanya pada data latih.")

# get_info(): dua kelompok yang BERBEDA statusnya.
#   WAJIB      = disebut docstring BasePipeline.get_info dan diperiksa validator.
#   DISARANKAN = memperkuat ketertelusuran, TIDAK diperiksa validator, dan
#                pipeline bawaan pun belum menyediakannya.
SUGGESTED_INFO_KEYS = ("dataset_requirements", "target", "evaluation_metrics",
                       "random_seed")
SUGGESTED_INFO_NOTE = ("Disarankan, bukan wajib: tidak diperiksa validator dan "
                       "pipeline bawaan pun belum menyediakannya.")


def required_info_keys() -> tuple[str, ...]:
    """Kunci get_info() yang diperiksa validator — dibaca dari konstantanya."""
    from orchestrator.pipeline_validator import EXPECTED_INFO_KEYS
    return tuple(EXPECTED_INFO_KEYS)


def missing_info_severity() -> str:
    """Bagaimana validator memperlakukan kunci yang tidak ada.

    Dibaca dari perilaku sebenarnya, bukan diasumsikan — saat ini ketiadaan
    kunci hanya menghasilkan PERINGATAN, tidak menggagalkan validasi.
    """
    return "peringatan"


# Larangan. Ini yang memisahkan MASUKAN yang dikendalikan pengguna dari
# PARAMETER yang ditetapkan eksperimen — dasar perbandingan yang adil dan hasil
# yang dapat diulang.
FORBIDDEN_FRAME = ("Ini yang memisahkan masukan yang dikendalikan pengguna dari "
                   "parameter yang ditetapkan eksperimen — dasar perbandingan "
                   "yang adil dan hasil yang dapat diulang.")
FORBIDDEN_ACTIONS = (
    "Mengubah dataset asli.",
    "Mengubah hyperparameter terkunci sendiri saat berjalan — penyesuaian "
    "hanya lewat run eksplorasi platform, yang mencatat & menandainya.",
    "Fit praproses pada data uji.",
    "Mengganti algoritma secara dinamis.",
    "Mengubah seleksi fitur secara acak / tidak dideklarasikan.",
)


def contract_skeleton() -> str:
    """Kerangka kelas minimal memakai NAMA FIELD NYATA.

    Field wajib PipelineResult dibaca dari dataclass-nya, jadi contoh ini ikut
    berubah bila kontraknya berubah — bukan salinan statis yang bisa basi.
    """
    from orchestrator.pipeline_validator import (
        BASE_CLASS_NAME, REQUIRED_METHODS, RUN_FIRST_PARAM, RUN_PROGRESS_PARAM,
    )

    base_module, result_module = _contract_modules()
    run_method, info_method = REQUIRED_METHODS[0], REQUIRED_METHODS[1]
    required = [f["name"] for f in pipeline_result_fields() if f["required"]]
    result_args = "\n".join(f"            {name}=...," for name in required)
    info_lines = "\n".join(f'            "{k}": ...,' for k in required_info_keys())

    return (
        f"from {base_module} import {BASE_CLASS_NAME}\n"
        f"from {result_module} import PipelineInput, PipelineResult\n"
        f"\n"
        f"\n"
        f"class MyPipeline({BASE_CLASS_NAME}):\n"
        f"    def {run_method}(self, {RUN_FIRST_PARAM}: PipelineInput,\n"
        f"            {RUN_PROGRESS_PARAM}=None) -> PipelineResult:\n"
        f"        df = {RUN_FIRST_PARAM}.df\n"
        f"        y = df[{RUN_FIRST_PARAM}.label_column]\n"
        f"        # 2) split DULU, 3) baru fit praproses pada data latih saja\n"
        f"        ...\n"
        f"        return PipelineResult(\n"
        f"{result_args}\n"
        f"        )\n"
        f"\n"
        f"    def {info_method}(self) -> dict:\n"
        f"        return {{\n"
        f"{info_lines}\n"
        f"        }}\n"
    )


def render_contract_docs() -> None:
    """Bagian kontrak: dua tabel field, tahapan, get_info, larangan, kerangka."""
    from ui.i18n import t

    st.markdown(t("ins.contract_intro"))

    # "get_info()" adalah nama metode — label tabnya tidak diterjemahkan.
    tabs = st.tabs([t("ins.tab_input"), t("ins.tab_return"),
                    t("ins.tab_stages"), "get_info()",
                    t("ins.tab_forbidden")])

    with tabs[0]:
        _render_field_table(pipeline_input_fields(), "pipeline_input")
    with tabs[1]:
        _render_field_table(pipeline_result_fields(), "PipelineResult")
    with tabs[2]:
        _render_stage_table()
    with tabs[3]:
        _render_info_keys()
    with tabs[4]:
        _render_forbidden()

    with st.expander(t("ins.exp_minimal_skeleton"), expanded=False):
        st.code(contract_skeleton(), language="python")


def _render_field_table(fields, title: str) -> None:
    from ui.i18n import t

    required, optional = t("ins.required"), t("ins.optional")
    rows = "\n".join(
        f"| `{f['name']}` | `{f['type']}` | "
        f"{required if f['required'] else optional} | {f['meaning']} |"
        for f in fields)
    st.markdown(f"| Field | {t('ins.col_type')} | | {t('ins.col_meaning')} |\n"
                f"| --- | --- | --- | --- |\n{rows}")


def _render_stage_table() -> None:
    from ui.i18n import t

    rows = []
    # Tahapan dari penyaji dua bahasa; nomor & pemiliknya tetap pengenal.
    for number, name, owner, note in execution_stages_display():
        mark = " ⚠" if number in ANTI_LEAK_STAGES else ""
        rows.append(f"| {number}{mark} | {name} | {owner} | {note} |")
    st.markdown(f"| # | {t('ins.col_stage')} | {t('ins.col_owner')} | "
                f"{t('ins.col_note')} |\n| --- | --- | --- | --- |\n"
                + "\n".join(rows))
    st.markdown(f"⚠ {t('ins.anti_leak_note')}")


def _render_info_keys() -> None:
    from ui.i18n import t

    st.markdown(t("ins.required_heading"))
    st.markdown("\n".join(f"- `{k}`" for k in required_info_keys()))
    # `missing_info_severity()` tetap mengembalikan PENGENAL "peringatan";
    # kalimatnya yang berbahasa, dipetakan di sini.
    severity = (t("ins.severity_warning")
                if missing_info_severity() == "peringatan"
                else missing_info_severity())
    st.markdown(t("ins.suggested_line", note=t("ins.suggested_note"),
                  severity=severity))
    st.markdown("\n".join(f"- `{k}`" for k in SUGGESTED_INFO_KEYS))


def _render_forbidden() -> None:
    from ui.i18n import t

    st.markdown(t("ins.forbidden_frame"))
    st.markdown("\n".join(f"- {item}" for item in forbidden_actions_display()))


# ── Kesalahan yang paling sering (dari daftar pemeriksaan NYATA) ──────────

# Aturan tingkat PAKET (bukan per berkas): ditegakkan di `review_package`,
# jadi namanya tidak ada di _CAUSE_PRIORITY yang isinya nama check per berkas.
ENTRY_POINT_RULE = "titik masuk"

# Urutan = seberapa sering pengguna menabraknya, bukan tingkat keparahan.
# Setiap butir WAJIB merujuk pemeriksaan yang benar-benar ada: nama check per
# berkas harus terdaftar di `_CAUSE_PRIORITY` (ui/components/pipeline_upload),
# selain ENTRY_POINT_RULE. Bila sebuah check dihapus/berganti nama, butirnya
# ikut hilang dari daftar dan test menangkapnya.
_PIPELINE_MISTAKE_ORDER = (
    ENTRY_POINT_RULE,
    "kelas pipeline",
    "method `run`",
    "import terlarang",
    "pemanggilan terlarang",
    "method `get_info`",
    "sintaks Python",
    "atribut dunder terlarang",
    "penulisan berkas",
    "get_info() mengembalikan dict",
)


def _pipeline_mistake_text(name: str) -> str:
    """Kalimat untuk satu nama check — nilai contohnya dari konstanta validator."""
    from orchestrator.pipeline_validator import (
        BASE_CLASS_NAME, FORBIDDEN_CALLS, FORBIDDEN_MODULES, REQUIRED_METHODS,
    )

    example_module = sorted(FORBIDDEN_MODULES)[0] if FORBIDDEN_MODULES else "—"
    example_call = sorted(FORBIDDEN_CALLS)[0] if FORBIDDEN_CALLS else "—"
    run_method, info_method = REQUIRED_METHODS[0], REQUIRED_METHODS[1]

    from ui.i18n import t

    # Nama check (kunci dict) adalah PENGENAL yang dicocokkan dengan
    # `_CAUSE_PRIORITY`; ia tidak berbahasa. Yang berbahasa nilainya.
    return {
        ENTRY_POINT_RULE: t("ins.mis_entry_point",
                            base_class=BASE_CLASS_NAME),
        "kelas pipeline": t("ins.mis_pipeline_class",
                            base_class=BASE_CLASS_NAME),
        "method `run`": t("ins.mis_method_run", method=run_method),
        "method `get_info`": t("ins.mis_method_get_info", method=info_method),
        "import terlarang": t("ins.mis_forbidden_import",
                              module=example_module),
        "pemanggilan terlarang": t("ins.mis_forbidden_call",
                                   call=example_call),
        "sintaks Python": t("ins.mis_syntax"),
        "atribut dunder terlarang": t("ins.mis_dunder"),
        "penulisan berkas": t("ins.mis_file_write"),
        "get_info() mengembalikan dict": t("ins.mis_get_info_dict",
                                           method=info_method),
    }.get(name, name)


def common_pipeline_mistakes(limit: int = 5) -> list[str]:
    """Penyebab penolakan tersering — diturunkan dari pemeriksaan yang ada.

    Disaring terhadap daftar nama check nyata, sehingga daftar ini tidak dapat
    memuat pemeriksaan yang tidak pernah dijalankan.
    """
    from ui.components.pipeline_upload import _CAUSE_PRIORITY

    known = set(_CAUSE_PRIORITY) | {ENTRY_POINT_RULE}
    return [_pipeline_mistake_text(name)
            for name in _PIPELINE_MISTAKE_ORDER if name in known][:limit]


def common_dataset_mistakes(limit: int = 5) -> list[str]:
    """Penyebab dataset dinyatakan belum cocok — satu butir per pemeriksaan
    diagnosa yang benar-benar dijalankan (lima check di dataset_diagnostics)."""
    from orchestrator.dataset_diagnostics import (
        CHECK_CLASSES, CHECK_DTYPE, CHECK_FEATURES, CHECK_FORMAT, CHECK_LABEL,
        _CHECK_TITLES,
    )
    from ui.components.validator_messages import diagnostic_title
    from ui.i18n import t

    hints = {
        CHECK_FORMAT: "ins.dsmis_format",
        CHECK_LABEL: "ins.dsmis_label",
        CHECK_FEATURES: "ins.dsmis_features",
        CHECK_DTYPE: "ins.dsmis_dtype",
        CHECK_CLASSES: "ins.dsmis_classes",
    }
    # Judulnya lewat lapisan tampilan diagnosa, supaya satu pemeriksaan
    # bernama sama di panduan dan di hasil diagnosa.
    return [f"**{diagnostic_title({'key': key, 'title': _CHECK_TITLES[key]})}**"
            f" — {t(hint_key)}"
            for key, hint_key in hints.items() if key in _CHECK_TITLES][:limit]


def render_mistakes(items: list[str], *, title: str) -> None:
    """Daftar padat kesalahan umum — satu baris per butir."""
    if not items:
        return
    st.markdown(f"**{title}**")
    st.markdown("\n".join(f"- {item}" for item in items))


# ── Instruksi jalur DATASET ───────────────────────────────────────────────

# Dataset adalah DATA: tidak ada tahap tinjauan. Bandingkan dengan
# PIPELINE_FLOW di atas, yang tetap melewati Research Admin karena isinya kode.
DATASET_FLOW = [
    ("📤", "Unggah"),
    ("🧪", "Periksa kecocokan"),
    ("📊", "Tersedia"),
]
DATASET_FLOW_ALT = ("Alur: unggah berkas, diperiksa kecocokannya dengan tiap "
                    "research pipeline, lalu langsung tersedia untuk eksperimen.")


def dataset_contract_rows(dataset_type: str) -> list[tuple[str, str]]:
    """(aspek, ketentuan) untuk sebuah dataset_type — seluruhnya dari skema &
    dict persyaratan terpusat, tidak ada yang diketik ulang."""
    from contracts.dataset_schemas import get_schema
    from ui.views.run_experiment import _DATASET_REQUIREMENTS, _dataset_extensions

    schema = get_schema(dataset_type) or {}
    req = _DATASET_REQUIREMENTS.get(dataset_type, {})
    exts = " / ".join(f"`{e}`" for e in _dataset_extensions(dataset_type))
    label_col = schema.get("label_column", "?")

    from ui.i18n import t

    if schema.get("expected_top_level_keys"):
        label_meaning = t("ins.dslabel_from_suricata", column=label_col)
    else:
        label_meaning = t("ins.dslabel_binary", column=label_col)

    return [
        (t("ins.dsrow_format"),
         f"{exts} — {dataset_requirement_text(dataset_type, 'row_unit')}"),
        (t("ins.dsrow_label_column"), label_meaning),
        (t("ins.dsrow_feature_nature"),
         dataset_requirement_text(dataset_type, "summary_line")),
        (t("ins.dsrow_class_count"), t("ins.dsval_two_classes")),
    ]


def render_dataset_instructions() -> None:
    """Diagram + tabel per research pipeline + contoh + checklist + catatan.

    Panel persyaratan LENGKAP milik halaman Run Experiment tetap dipakai apa
    adanya di dalam expander — satu sumber, dua tempat, tanpa duplikasi teks.
    """
    from contracts.dataset_schemas import supported_datasets
    from config.research_attribution import get_research_short_label
    from ui.views.run_experiment import _render_dataset_requirements

    from ui.i18n import t

    inject_css()
    render_flow(dataset_flow_display(), alt=t("ins.flow_dataset_alt"))

    tabs = st.tabs([get_research_short_label(dt) for dt in supported_datasets()])
    for tab, dtype in zip(tabs, supported_datasets()):
        with tab:
            rows = dataset_contract_rows(dtype)
            st.markdown(
                f"| {t('ins.col_aspect')} | {t('ins.col_rule')} |\n"
                "| --- | --- |\n"
                + "\n".join(f"| {aspect} | {rule} |" for aspect, rule in rows)
            )
            sample = dataset_sample_snippet(dtype)
            if sample:
                st.code(sample, language=None)
            st.markdown("\n".join(f"- ✔ {item}"
                                  for item in dataset_checklist(dtype)))

    render_note(t("ins.dataset_sample_note"))

    render_mistakes(common_dataset_mistakes(),
                    title=t("ins.mistakes_dataset_title"))

    with st.expander(t("ins.exp_dataset_requirements"), expanded=False):
        for dtype in supported_datasets():
            st.markdown(f"**{get_research_short_label(dtype)}**")
            _render_dataset_requirements(dtype)
            st.divider()


def dataset_sample_snippet(dataset_type: str) -> str:
    """Potongan struktur RINGKAS memakai nama kolom/field NYATA dari skema."""
    import json

    from contracts.dataset_schemas import get_schema
    from ui.views.run_experiment import _DATASET_REQUIREMENTS, _hikari_column_facts

    schema = get_schema(dataset_type) or {}
    req = _DATASET_REQUIREMENTS.get(dataset_type, {})

    if schema.get("expected_top_level_keys"):
        values = req.get("sample_values") or {}
        keys = [k for k in schema["expected_top_level_keys"] if k in values][:5]
        if not keys:
            return ""
        return json.dumps({k: values[k] for k in keys}, ensure_ascii=False) + " …"

    features, _drops, _names = _hikari_column_facts()
    pairs = [(c, v) for c, v in (req.get("sample_columns") or {}).items()
             if c in features][:3]
    if not pairs:
        return ""
    label_col = schema.get("label_column", "Label")
    header = "…," + ",".join(c for c, _ in pairs) + f",…,{label_col}"
    values_row = "…," + ",".join(v for _, v in pairs) + ",…,0"
    return f"{header}\n{values_row}"


def dataset_checklist(dataset_type: str) -> list[str]:
    """Checklist padat "Dataset Anda cocok jika…" — diturunkan dari skema."""
    from contracts.dataset_schemas import get_schema
    from ui.views.run_experiment import _dataset_extensions

    schema = get_schema(dataset_type) or {}
    exts = " / ".join(f"`{e}`" for e in _dataset_extensions(dataset_type))
    label_col = schema.get("label_column", "?")

    from ui.i18n import t

    if schema.get("expected_top_level_keys"):
        return [
            t("ins.dschk_json_format", exts=exts),
            t("ins.dschk_tls_events"),
            t("ins.dschk_no_label_column", column=label_col),
            t("ins.dschk_alert_events"),
        ]
    return [
        t("ins.dschk_csv_format", exts=exts),
        t("ins.dschk_label_column", column=label_col),
        t("ins.dschk_numeric_features"),
        t("ins.dschk_two_classes"),
    ]


# ── Panduan kontrak dalam DUA BAHASA ─────────────────────────────────────
#
# Konstanta di atas TIDAK diubah: ia diimpor & diuji test lama, dan nama tahap
# dipakai sebagai KUNCI pencarian di sana (`owners["Validasi masukan"]`).
# Terjemahannya hidup di samping, dipetakan lewat nomor tahap / indeks — nilai
# yang stabil dan tidak berbahasa.
#
# Yang TIDAK diterjemahkan di seluruh bagian ini: nama field kontrak
# (`fixed_params`, `PipelineResult`, `get_info`), potongan kode, nama kelas, dan
# nama metode. Yang berbahasa hanya penjelasan di sekitarnya.

#: Nomor tahap → (kunci nama, kunci catatan). Nomor dipakai sebagai pengenal
#: karena ia tidak pernah berubah bahasa.
EXECUTION_STAGE_KEYS = {
    1: ("ins.stage1_name", "ins.stage1_note"),
    2: ("ins.stage2_name", "ins.stage2_note"),
    3: ("ins.stage3_name", "ins.stage3_note"),
    4: ("ins.stage4_name", "ins.stage4_note"),
    5: ("ins.stage5_name", "ins.stage5_note"),
    6: ("ins.stage6_name", ""),
    7: ("ins.stage7_name", ""),
    8: ("ins.stage8_name", "ins.stage8_note"),
    9: ("ins.stage9_name", ""),
}

#: Indeks larangan → kunci. Urutannya sama dengan `FORBIDDEN_ACTIONS`.
FORBIDDEN_ACTION_KEYS = (
    "ins.forbid_dataset", "ins.forbid_params", "ins.forbid_fit_test",
    "ins.forbid_algorithm", "ins.forbid_features",
)


def execution_stages_display():
    """Tahapan eksekusi pada bahasa aktif — struktur & pemiliknya TIDAK berubah.

    Pembagian tugas tetap terbaca: tahap 1 & 8 milik PLATFORM (orchestrator),
    sisanya milik PIPELINE. Itulah yang membedakan "apa yang dikerjakan platform
    sebelum pipeline dipanggil" dari "apa yang menjadi tanggung jawab pipeline",
    dan ia tidak boleh kabur pada bahasa mana pun.
    """
    from ui.i18n import t

    out = []
    for number, name, owner, note in EXECUTION_STAGES:
        name_key, note_key = EXECUTION_STAGE_KEYS.get(number, ("", ""))
        out.append((
            number,
            t(name_key) if name_key else name,
            owner,                       # PENGENAL pemilik — tidak berbahasa
            t(note_key) if note_key else "",
        ))
    return out


def forbidden_actions_display():
    """Daftar larangan pada bahasa aktif — tetap TEGAS, tidak diperhalus."""
    from ui.i18n import t

    return [t(key) for key in FORBIDDEN_ACTION_KEYS]


#: Indeks langkah → kunci label. Ikon & urutannya tetap di konstanta.
PIPELINE_FLOW_KEYS = ("ins.flow_upload", "ins.flow_auto_check",
                      "ins.flow_admin_review", "ins.flow_active")
DATASET_FLOW_KEYS = ("ins.flow_upload", "ins.flow_match_check",
                     "ins.flow_available")

#: (dataset_type, field persyaratan) → kunci. Konstanta `_DATASET_REQUIREMENTS`
#: pada `run_experiment` TIDAK diubah; ia tetap sumber strukturnya.
DATASET_REQUIREMENT_KEYS = {
    ("HIKARI2021", "row_unit"): "ins.req_hikari_row_unit",
    ("HIKARI2021", "feature_nature"): "ins.req_hikari_feature_nature",
    ("HIKARI2021", "summary_line"): "ins.req_hikari_summary",
    ("EVE_SURICATA", "row_unit"): "ins.req_eve_row_unit",
    ("EVE_SURICATA", "feature_nature"): "ins.req_eve_feature_nature",
    ("EVE_SURICATA", "summary_line"): "ins.req_eve_summary",
    ("EVE_SURICATA", "class_hint"): "ins.req_eve_class_hint",
}


def _flow_display(steps, keys):
    """Ikon dari konstanta, label dari katalog — jumlah langkah tetap sama."""
    from ui.i18n import t

    return [(icon, t(key) if key else label)
            for (icon, label), key in zip(steps, keys)]


def pipeline_flow_display():
    """Langkah alur pipeline pada bahasa aktif."""
    return _flow_display(PIPELINE_FLOW, PIPELINE_FLOW_KEYS)


def dataset_flow_display():
    """Langkah alur dataset pada bahasa aktif."""
    return _flow_display(DATASET_FLOW, DATASET_FLOW_KEYS)


def dataset_requirement_text(dataset_type: str, field: str) -> str:
    """Satu keterangan persyaratan dataset pada bahasa aktif.

    Bila pasangan (dataset, field) belum punya kunci — misalnya dataset baru
    yang diunggah — nilai aslinya dikembalikan apa adanya, bukan teks kosong.
    """
    from ui.i18n import t
    from ui.views.run_experiment import _DATASET_REQUIREMENTS

    original = (_DATASET_REQUIREMENTS.get(dataset_type, {}) or {}).get(field)
    key = DATASET_REQUIREMENT_KEYS.get((dataset_type, field))
    if key:
        return t(key)
    return original if original else "—"

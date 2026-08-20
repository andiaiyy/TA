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
    st.markdown(flow_diagram_svg(steps, alt=alt), unsafe_allow_html=True)
    st.caption(alt)          # teks alternatif yang tetap terbaca


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
        chips += f'<span class="ids-chip more">+{rest} lainnya</span>'
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

    inject_css()
    render_flow(PIPELINE_FLOW, alt=PIPELINE_FLOW_ALT)

    methods = " · ".join(f"`{m}()`" for m in REQUIRED_METHODS)
    info_keys = ", ".join(f"`{k}`" for k in EXPECTED_INFO_KEYS)
    st.markdown(
        "| Aspek | Ketentuan |\n"
        "| --- | --- |\n"
        f"| Kelas induk | `{BASE_CLASS_NAME}` |\n"
        f"| Metode wajib | {methods} |\n"
        f"| Tanda tangan `run` | `({RUN_FIRST_PARAM}, {RUN_PROGRESS_PARAM}=None)` "
        f"→ `PipelineResult` |\n"
        f"| Titik masuk | tepat **satu** berkas memuat kelas turunan itu; "
        f"berkas lain pendukung |\n"
        f"| Anti-kebocoran | scaler/PCA/penyeimbang di-*fit* hanya pada data "
        f"latih (setelah split) |\n"
        f"| Kunci `get_info()` | {info_keys} |"
    )

    cols = st.columns(2)
    cols[0].caption(f"Modul diizinkan ({len(ALLOWED_MODULES)})")
    with cols[0]:
        render_chips(sorted(ALLOWED_MODULES), "ok")
    cols[1].caption(f"Modul ditolak ({len(FORBIDDEN_MODULES)})")
    with cols[1]:
        render_chips(sorted(FORBIDDEN_MODULES), "no")

    render_note(
        "🔒 Pemeriksaan bersifat <b>statis</b>: berkas dibaca dan diurai, "
        "<b>tidak dijalankan</b>. Lolos pemeriksaan <b>bukan</b> berarti "
        "langsung aktif — tetap perlu tinjauan Research Admin."
    )

    st.caption("Bentuk yang diharapkan")
    st.code(pipeline_skeleton(), language="python")

    render_mistakes(common_pipeline_mistakes(),
                    title="Paling sering membuat paket ditolak")

    with st.expander("Persyaratan lengkap — modul & pemanggilan", expanded=False):
        st.markdown("**Modul yang wajar dipakai**")
        st.caption(", ".join(f"`{m}`" for m in sorted(ALLOWED_MODULES)))
        st.caption("Modul lain di luar daftar ini tidak menggagalkan validasi, "
                   "hanya ditandai untuk diperiksa manual.")
        st.markdown("**Modul yang dilarang**")
        st.caption(", ".join(f"`{m}`" for m in sorted(FORBIDDEN_MODULES)))
        st.markdown("**Pemanggilan yang dilarang**")
        st.caption(", ".join(f"`{c}()`" for c in sorted(FORBIDDEN_CALLS)))
        st.caption("Termasuk pemanggilan pada modul terlarang (`os.system()`), "
                   "`open()` mode tulis, dan atribut sandbox-escape "
                   "(`__subclasses__`, `__globals__`, `__builtins__`).")
        st.caption("Daftar ini dibaca dari konstanta validator, jadi selalu "
                   "sama dengan aturan yang dijalankan.")


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

    return {
        ENTRY_POINT_RULE: (
            f"Titik masuk tidak tepat satu — tidak ada berkas dengan kelas "
            f"turunan `{BASE_CLASS_NAME}`, atau justru lebih dari satu."),
        "kelas pipeline": (
            f"Kelas pipeline tidak mewarisi `{BASE_CLASS_NAME}`."),
        "method `run`": f"Metode wajib `{run_method}()` belum ada.",
        "method `get_info`": f"Metode wajib `{info_method}()` belum ada.",
        "import terlarang": (
            f"Mengimpor modul terlarang — mis. `{example_module}`."),
        "pemanggilan terlarang": (
            f"Memakai pemanggilan terlarang — mis. `{example_call}()`."),
        "sintaks Python": "Berkas gagal diurai — bukan Python yang valid.",
        "atribut dunder terlarang": (
            "Menyentuh atribut pelolos sandbox (`__globals__`, `__subclasses__`)."),
        "penulisan berkas": "Membuka berkas dalam mode tulis.",
        "get_info() mengembalikan dict": (
            f"`{info_method}()` tidak mengembalikan dict."),
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

    hints = {
        CHECK_FORMAT: "ekstensi/bentuk berkas tidak sesuai, atau isinya gagal diparse",
        CHECK_LABEL: "kolom label yang diminta research pipeline tidak ditemukan",
        CHECK_FEATURES: "kolom fitur yang diharapkan skema banyak yang hilang",
        CHECK_DTYPE: "kolom fitur tidak numerik sehingga tidak dapat dilatih",
        CHECK_CLASSES: "hanya satu kelas yang muncul — tidak ada contoh attack",
    }
    return [f"**{_CHECK_TITLES[key]}** — {hint}"
            for key, hint in hints.items() if key in _CHECK_TITLES][:limit]


def render_mistakes(items: list[str], *, title: str) -> None:
    """Daftar padat kesalahan umum — satu baris per butir."""
    if not items:
        return
    st.markdown(f"**{title}**")
    st.markdown("\n".join(f"- {item}" for item in items))


# ── Instruksi jalur DATASET ───────────────────────────────────────────────

DATASET_FLOW = [
    ("📤", "Unggah"),
    ("🧪", "Periksa kecocokan"),
    ("👤", "Tinjau"),
    ("📊", "Tersedia"),
]
DATASET_FLOW_ALT = ("Alur: unggah berkas, diperiksa kecocokannya dengan tiap "
                    "research pipeline, ditinjau Research Admin, lalu tersedia "
                    "untuk eksperimen.")


def dataset_contract_rows(dataset_type: str) -> list[tuple[str, str]]:
    """(aspek, ketentuan) untuk sebuah dataset_type — seluruhnya dari skema &
    dict persyaratan terpusat, tidak ada yang diketik ulang."""
    from contracts.dataset_schemas import get_schema
    from ui.views.run_experiment import _DATASET_REQUIREMENTS, _dataset_extensions

    schema = get_schema(dataset_type) or {}
    req = _DATASET_REQUIREMENTS.get(dataset_type, {})
    exts = " / ".join(f"`{e}`" for e in _dataset_extensions(dataset_type))
    label_col = schema.get("label_column", "?")

    if schema.get("expected_top_level_keys"):
        label_meaning = (f"`{label_col}` — dibentuk pipeline dari **alert "
                         f"Suricata**, tidak perlu ada di berkas")
    else:
        label_meaning = f"`{label_col}` — `0` = benign, `1` = malicious"

    return [
        ("Format berkas", f"{exts} — {req.get('row_unit', '—')}"),
        ("Kolom label", label_meaning),
        ("Sifat fitur", req.get("summary_line", "—")),
        ("Jumlah kelas", "dua kelas (benign & attack)"),
    ]


def render_dataset_instructions() -> None:
    """Diagram + tabel per research pipeline + contoh + checklist + catatan.

    Panel persyaratan LENGKAP milik halaman Run Experiment tetap dipakai apa
    adanya di dalam expander — satu sumber, dua tempat, tanpa duplikasi teks.
    """
    from contracts.dataset_schemas import supported_datasets
    from config.research_attribution import get_research_short_label
    from ui.views.run_experiment import _render_dataset_requirements

    inject_css()
    render_flow(DATASET_FLOW, alt=DATASET_FLOW_ALT)

    tabs = st.tabs([get_research_short_label(dt) for dt in supported_datasets()])
    for tab, dtype in zip(tabs, supported_datasets()):
        with tab:
            rows = dataset_contract_rows(dtype)
            st.markdown(
                "| Aspek | Ketentuan |\n| --- | --- |\n"
                + "\n".join(f"| {aspect} | {rule} |" for aspect, rule in rows)
            )
            sample = dataset_sample_snippet(dtype)
            if sample:
                st.code(sample, language=None)
            st.markdown("\n".join(f"- ✔ {item}"
                                  for item in dataset_checklist(dtype)))

    render_note(
        "🔍 Pemeriksaan membaca <b>cuplikan</b> berkas (bukan seluruh isinya), "
        "jadi angka profil & distribusi kelas adalah angka cuplikan. Berkas "
        "tidak langsung tersedia — menunggu tinjauan Research Admin."
    )

    render_mistakes(common_dataset_mistakes(),
                    title="Paling sering membuat dataset dinyatakan belum cocok")

    with st.expander("Persyaratan dataset lengkap", expanded=False):
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

    if schema.get("expected_top_level_keys"):
        return [
            f"Format {exts}, satu objek JSON per baris.",
            "Memuat event TLS (`app_proto`/`event_type` = `tls`).",
            f"Tidak perlu kolom `{label_col}` — dibentuk dari alert Suricata.",
            "Ada event `alert`, sehingga kelas attack tidak kosong.",
        ]
    return [
        f"Format {exts}, satu baris per flow.",
        f"Ada kolom label `{label_col}` berisi `0`/`1`.",
        "Kolom fitur numerik (non-numerik diabaikan otomatis).",
        "Berisi dua kelas: benign dan malicious.",
    ]

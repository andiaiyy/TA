"""
Katalog research pipeline — tampilan pembuka halaman "Run Experiment".

Katalog bersifat DESKRIPTIF: ia menjelaskan pipeline apa saja yang tersedia dan
apa isinya, lalu mengantar pengguna ke tampilan eksekusi. Tidak ada satu pun
angka hasil/metrik di sini — hasil eksperimen tinggal di halaman
"Progress & Status".

**Semua keterangan dibaca dari sumber terstruktur**, tidak ada yang diketik
ulang sebagai teks statis:

* nama beratribusi tiap research pipeline → ``config/research_attribution``;
* daftar algoritma & pipeline_id → ``config/pipeline_registry``;
* keterangan tiap algoritma (feature selection, preprocessing, fixed_params,
  anti-leakage, metrics policy, paper) → ``get_info()`` milik pipeline itu;
* persyaratan dataset (format, kolom label, sifat fitur) → skema dataset lewat
  ``ui.components.instructions.dataset_contract_rows``.

Konsekuensinya: menambah pipeline ke registry langsung memunculkannya di
katalog, dan mengubah ``get_info()`` langsung mengubah keterangannya.

Gayanya mengikuti pola yang sudah dipakai sidebar: perataan kiri konsisten,
jarak vertikal seragam, pemisah tipis, satu warna aksen, warna aman di tema
terang maupun gelap (memakai ``currentColor``/opacity, bukan nilai heksa).
"""
from __future__ import annotations

from html import escape

import streamlit as st

from ui.i18n import t

# Panjang maksimum ringkasan satu baris (dipakai penyusun keterangan
# algoritma di modal). Nama research pipeline pada baris katalog TIDAK memakai
# batas karakter: pemotongannya ditentukan lebar nyata oleh CSS.
SUMMARY_CHARS = 90

# Kunci get_info yang layak tampil sebagai RINGKASAN satu baris per algoritma,
# menurut urutan keinformatifannya. Yang pertama tersedia yang dipakai.
_SUMMARY_KEYS = ("feature_selection", "metrics_policy", "algorithm")

# Kunci get_info yang masuk ke expander detail, dengan labelnya.
_DETAIL_FIELDS = (
    ("preprocessing_steps", "Langkah preprocessing"),
    ("anti_leakage", "Anti-kebocoran"),
    ("metrics_policy", "Kebijakan metrik"),
    ("train_test_split", "Pembagian train/test"),
    ("fixed_params", "Parameter tetap"),
    ("app", "Fokus trafik"),
    ("dataset", "Dataset sumber"),
    ("paper", "Penelitian sumber"),
)

# Awalan kunci `st.container(key=…)` untuk satu BARIS katalog. Streamlit
# menambahkan kelas `st-key-<key>` pada elemen berkunci, dan ITULAH kaitan
# CSS-nya — bukan testid yang ditebak. Ada test yang mencocokkan awalan ini
# dengan bundel frontend yang benar-benar terpasang. Nilainya dimiliki `theme`
# supaya satu konstanta melayani gaya dan kode sekaligus.
from ui.components.theme import ROW_KEY_PREFIX


def row_key(dataset_type: str) -> str:
    """Kunci container untuk satu baris research pipeline."""
    return ROW_KEY_PREFIX + str(dataset_type)


_CSS = """
<style>
.ids-cat-title { font-size: 1.05rem; font-weight: 600; margin: .2rem 0 .15rem; }
.ids-cat-short { font-size: .86rem; opacity: .7; line-height: 1.6;
                 margin-bottom: .45rem; }

/* ── Baris katalog: TIGA TINGKAT TEKS yang jelas berbeda ───────────────
   Perbedaannya dibuat oleh tiga sumbu sekaligus — ukuran, bobot, dan
   keredupan — supaya terbaca sekilas, bukan cuma sedikit berbeda:

     1. nama penelitian  1.25rem · bobot 600 · opacity 1
     2. keterangan utama 0.95rem · bobot 400 · opacity 1
     3. penjelasan       0.84rem · bobot 400 · opacity .55

   Jarak DI DALAM baris sengaja rapat (≤ .35rem); jarak ANTAR baris dipegang
   padding besar di theme.py. Perataan kiri semuanya sama: tidak ada indentasi
   tambahan pada tingkat mana pun. */
.ids-cat-head {
    display: flex; align-items: baseline; justify-content: space-between;
    gap: .5rem 1rem; flex-wrap: wrap;    /* layar sempit: meta turun ke bawah */
    /* Lebar MENGIKUTI wadahnya, dengan batas atas supaya baris tidak terlalu
       panjang di layar lebar. Tidak ada lebar tetap di mana pun. */
    width: 100%;
    max-width: var(--ids-cat-textw, 46rem);
    margin: 0 0 .3rem;
}
.ids-cat-name {
    font-size: 1.25rem; font-weight: 600; line-height: 1.3;
    /* Boleh menyusut DI BAWAH lebar isinya. Tanpa `min-width: 0` sebuah item
       flex menolak menyusut, dan metadata di sebelahnya akan terdorong keluar
       pada lebar sempit. */
    flex: 1 1 auto; min-width: 0;
    overflow-wrap: anywhere; margin: 0;
}
/* Metadata kanan atas, sejajar baris nama. `margin-left: auto` menahannya di
   kanan pada lebar berapa pun; begitu ia membungkus ke baris baru, ia kembali
   rata kiri bersama nama. Tidak pernah ikut menyusut sampai terpotong. */
.ids-cat-meta {
    font-size: .84rem; opacity: .6; white-space: nowrap;
    flex: 0 0 auto; margin-left: auto; text-align: right;
}
.ids-cat-lead {
    font-size: .95rem; font-weight: 400; line-height: 1.5;
    width: 100%;
    max-width: var(--ids-cat-textw, 46rem);
    overflow-wrap: anywhere; margin: 0 0 .25rem;
}
/* Penjelasan: SATU baris, dipotong elipsis oleh LEBAR NYATA saat itu — bukan
   pada jumlah karakter tetap. Melebarkan jendela atau menutup sidebar langsung
   menampilkan lebih banyak teks. Teks lengkapnya tetap ada di atribut `title`
   (tooltip) dan di pop-up Detail — tidak ada yang hilang. */
.ids-cat-note {
    font-size: .84rem; font-weight: 400; opacity: .55; line-height: 1.5;
    width: 100%;
    max-width: var(--ids-cat-textw, 46rem);
    min-width: 0;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    margin: 0 0 .35rem;
}
@media (prefers-reduced-motion: reduce) {
    .ids-cat-head, .ids-cat-name, .ids-cat-lead, .ids-cat-note {
        transition: none !important;
    }
}
/* Chip membungkus ke baris berikutnya, tidak pernah terpotong, dan ikut
   batas lebar blok teks yang sama. */
.ids-cat-chips { display: flex; flex-wrap: wrap; gap: .3rem;
                 margin: .1rem 0 .5rem;
                 max-width: var(--ids-cat-textw, 46rem); }
.ids-cat-chip {
    display: inline-block; padding: .08rem .55rem; border-radius: 999px;
    font-size: .76rem; line-height: 1.6; white-space: nowrap;
    background: rgba(127,127,127,.16); opacity: .9;
}
.ids-cat-chip-accent {
    background: transparent; opacity: 1;
    border: 1px solid var(--primary-color, currentColor);
}
.ids-cat-count {
    display: inline-block; font-size: .78rem; opacity: .7;
    border-left: 3px solid var(--primary-color, currentColor);
    padding: .1rem .6rem; margin: .1rem 0 .4rem;
}
.ids-cat-rows { margin: .5rem 0 .3rem; }
.ids-cat-row {
    display: flex; gap: 1rem; align-items: baseline;
    padding: .38rem 0; border-bottom: 1px solid rgba(127,127,127,.22);
}
.ids-cat-row:last-child { border-bottom: none; }
.ids-cat-row-label { flex: 0 0 42%; font-size: .8rem; opacity: .6; }
.ids-cat-row-value {
    flex: 1 1 auto; font-size: .86rem; text-align: right; overflow-wrap: anywhere;
}
.ids-ph-wrap { overflow-x: auto; overflow-y: hidden; padding: .2rem 0 .4rem; }
.ids-ph-wrap svg { display: block; }
.ids-ph-card {
    fill: rgba(127,127,127,.10); stroke: currentColor;
    stroke-width: 1; opacity: .85;
}
.ids-ph-link { stroke: var(--primary-color, currentColor); stroke-width: 1.5; opacity: .55; }
.ids-ph-num { fill: currentColor; opacity: .45; font-size: 10px; }
.ids-ph-label { fill: currentColor; font-size: 11px; }
</style>
"""


def shorten(text, limit: int) -> str:
    """Potong dengan elipsis; aman untuk None dan nilai non-teks."""
    s = str(text or "").strip()
    return s if len(s) <= limit else s[: max(1, limit - 1)].rstrip() + "…"


# ── Lapis MURNI: susun data katalog ───────────────────────────────────────

def plain_text(value) -> str:
    """Buang penanda markdown ringan dari nilai bersumber terstruktur.

    Baris label-nilai dirender sebagai HTML mentah, dan Streamlit tidak
    memproses markdown di dalamnya — tanpa ini, backtick dan tanda bintang dari
    skema dataset akan tampil apa adanya sebagai karakter.
    """
    text = str(value or "")
    text = text.replace("**", "").replace("`", "")
    return " ".join(text.split())


def _as_text(value) -> str:
    """Nilai get_info apa pun menjadi satu baris teks yang terbaca."""
    if isinstance(value, (list, tuple)):
        return " · ".join(str(v) for v in value)
    if isinstance(value, dict):
        return ", ".join(f"{k}={v}" for k, v in value.items())
    return str(value or "")


def algorithm_summary(info: dict) -> str:
    """Keterangan SANGAT RINGKAS satu algoritma, dari get_info.

    Memakai kunci pertama yang tersedia menurut ``_SUMMARY_KEYS`` — tidak
    pernah kalimat karangan. Kosong bila pipeline tidak menyediakan satu pun.
    """
    for key in _SUMMARY_KEYS:
        value = (info or {}).get(key)
        if value:
            return shorten(_as_text(value), SUMMARY_CHARS)
    return ""


def algorithm_details(info: dict) -> list[tuple[str, str]]:
    """(label, isi) untuk expander detail — hanya kunci yang BENAR-BENAR ada."""
    out = []
    for key, label in _DETAIL_FIELDS:
        value = (info or {}).get(key)
        if value:
            out.append((label, value))
    return out


# Label baris yang menampung keterangan "belum tersedia" pada expander detail.
# Bukan salah satu `_DETAIL_FIELDS`: ia bukan bidang get_info, melainkan
# keterangan tentang KETIADAAN bidang-bidang itu.
UPLOADED_NOTICE_KEY = "re.cat_uploaded_no_info"
UPLOADED_NOTICE_LABEL_KEY = "re.cat_uploaded_no_info_label"


def uploaded_notice() -> str:
    """Kalimat untuk pipeline kontribusi yang keterangannya tidak dibaca.

    Ditulis SEKALI di sini dan dipakai ulang oleh ringkasan maupun detail.
    Katalog sengaja tidak memuat kode pipeline kontribusi — memanggil
    ``get_info()`` berarti meng-import modulnya, dan katalog dirender setiap
    kali halaman dibuka. Jadi yang dinyatakan bukan "tidak ada keterangan",
    melainkan alasan mengapa keterangan itu tidak dibaca di sini.
    """
    from ui.i18n import t

    return t(UPLOADED_NOTICE_KEY)


def research_scope(dataset_type: str) -> str:
    """Penjelasan singkat satu kalimat, dari bidang `scope` sumber atribusi."""
    try:
        from orchestrator.research_registry import (
            attribution_for as get_research_attribution,
        )
        attribution = get_research_attribution(dataset_type) or {}
        key = attribution.get("scope_key")
        return t(key) if key else attribution.get("scope", "")
    except Exception:                       # pragma: no cover - defensif
        return ""


def dataset_lines(dataset_type: str) -> list[str]:
    """Keterangan dataset satu-dua baris, dari skema (bukan teks statis)."""
    try:
        from ui.components.instructions import dataset_contract_rows
        rows = dataset_contract_rows(dataset_type)
    except Exception:                       # pragma: no cover - defensif
        return []
    return [f"{aspect}: {rule}" for aspect, rule in rows]


#: Keadaan satu entri katalog.
STATE_OK = "ok"
STATE_BROKEN = "broken"
STATE_NO_DATASET = "no_dataset"


def group_title(dataset_type: str, name_reader) -> str:
    """Judul grup: nama beratribusi bila dikenal, apa adanya bila tidak.

    Pipeline kontribusi boleh membawa jenis datasetnya sendiri. Tanpa
    penanganan ini judulnya menjadi pengenal mentah (`MY_OWN_FORMAT`) yang
    tidak menjelaskan apa pun.
    """
    from ui.i18n import t

    try:
        name = name_reader(dataset_type)
    except Exception:                       # pragma: no cover - defensif
        name = ""
    if name and name != dataset_type:
        return name
    return t("re.cat_contributed_group", dataset=dataset_type)


def entry_state(pipeline_id: str, entry: dict) -> tuple[str, str]:
    """(keadaan, sebab) satu entri katalog.

    Pipeline BAWAAN selalu "ok": definisinya ada di git, tidak ada berkas
    unggahan yang bisa berubah di belakang platform.

    Untuk pipeline kontribusi, dua hal yang bisa membuatnya tidak terpakai
    diperiksa DI SINI supaya keduanya terlihat, bukan ditemukan saat run:

    * berkasnya tidak dapat dimuat (hash tidak cocok / berkas hilang);
    * belum ada dataset platform berjenis itu, jadi ia belum dapat dijalankan.
    """
    from ui.i18n import t

    if not entry.get("uploaded"):
        return STATE_OK, ""

    try:
        from orchestrator.dynamic_registry import get_registered
        from ui.components.registry_view import version_state

        row = get_registered(pipeline_id)
        if row is not None:
            state, reason = version_state(row)
            from ui.components.registry_view import STATE_OK as RV_OK

            if state != RV_OK:
                return STATE_BROKEN, reason
    except Exception:                       # pragma: no cover - defensif
        pass

    if not _has_dataset_for(entry.get("dataset_type")):
        return STATE_NO_DATASET, t("re.cat_no_dataset_reason")
    return STATE_OK, ""


def _has_dataset_for(dataset_type: str | None) -> bool:
    """Adakah dataset platform berjenis ini? Tidak pernah melempar."""
    if not dataset_type:
        return False
    try:
        from contracts.dataset_schemas import get_schema

        if get_schema(dataset_type) is None:
            # Jenis dataset yang skemanya tidak dikenal platform: tidak ada
            # berkas yang dapat dicocokkan dengannya.
            return False
        from ui.views.run_experiment import _list_dataset_files

        return bool(_list_dataset_files(dataset_type))
    except Exception:                       # pragma: no cover - defensif
        return True                          # jangan menuduh saat ragu


def build_catalog(*, registry_reader=None, info_reader=None,
                  name_reader=None) -> list[dict]:
    """Katalog dikelompokkan per research pipeline (satu grup per dataset_type).

    Seluruh pembacaan disuntikkan agar dapat diuji tanpa registry sungguhan::

        registry_reader() -> {pipeline_id: {dataset_type, algorithm, name, ...}}
        info_reader(pipeline_id) -> get_info() milik pipeline itu
        name_reader(dataset_type) -> nama tampilan beratribusi

    Mengembalikan::

        [{"dataset_type", "title", "dataset_lines",
          "algorithms": [{"pipeline_id", "algorithm", "summary", "details"}]}]
    """
    if registry_reader is None:
        # Registry GABUNGAN: bawaan + kontribusi yang AKTIF. Sebelumnya di
        # sini terpasang daftar statis, sehingga pipeline kontribusi yang
        # sudah disetujui & diaktifkan tidak pernah muncul di katalog —
        # padahal pemilihan dan worker sudah membacanya. Ketiganya kini
        # membaca kumpulan yang sama.
        from orchestrator.dynamic_registry import get_all_pipelines
        registry_reader = get_all_pipelines
    if info_reader is None:
        info_reader = _registry_info
    if name_reader is None:
        from orchestrator.research_registry import (
            display_name_for as get_research_display_name,
        )
        name_reader = get_research_display_name

    groups: dict[str, dict] = {}
    for pipeline_id, entry in (registry_reader() or {}).items():
        dataset_type = (entry or {}).get("dataset_type")
        if not dataset_type:
            continue
        group = groups.setdefault(dataset_type, {
            "dataset_type": dataset_type,
            "title": group_title(dataset_type, name_reader),
            # Penjelasan SINGKAT satu kalimat — bukan karangan: `scope` memang
            # ada sebagai bidang tersendiri di sumber atribusi.
            "short": research_scope(dataset_type),
            "dataset_lines": dataset_lines(dataset_type),
            "paper": "",
            "algorithms": [],
        })
        info = {}
        try:
            info = info_reader(pipeline_id) or {}
        except Exception:                   # pipeline rusak != katalog rusak
            info = {}
        state, reason = entry_state(pipeline_id, entry)
        summary = algorithm_summary(info)
        details = algorithm_details(info)
        # Pipeline kontribusi tidak punya `get_info()` di sini — katalog
        # sengaja tidak memuat kodenya. Kekosongan itu DINYATAKAN, bukan
        # dibiarkan tampil sebagai bidang kosong tanpa penjelasan.
        if entry.get("uploaded") and not summary and not details:
            from ui.i18n import t

            summary = uploaded_notice()
            details = [(t(UPLOADED_NOTICE_LABEL_KEY), uploaded_notice())]
        group["algorithms"].append({
            "pipeline_id": pipeline_id,
            # Nama algoritma dari registry; get_info hanya melengkapi keterangan.
            "algorithm": (entry.get("algorithm") or entry.get("name")
                          or pipeline_id),
            "summary": summary,
            "details": details,
            # get_info mentah — dipakai modal untuk menyusun baris label–nilai
            # tanpa harus menebak balik dari label yang sudah diformat.
            "info": info,
            # Asal & versi: pembaca berhak tahu ini pipeline kontribusi, dan
            # versi yang mana.
            "uploaded": bool(entry.get("uploaded")),
            "version": entry.get("version"),
            # Keadaan: "ok" atau sebab ia tidak dapat dimuat. Pipeline yang
            # rusak TETAP ditampilkan — menghilangkannya membuat pengguna
            # mencari sesuatu yang tidak pernah menjelaskan dirinya.
            "state": state,
            "state_reason": reason,
        })
        if not group["paper"]:
            group["paper"] = str(info.get("paper") or entry.get("paper") or "")

    for group in groups.values():
        group["algorithms"].sort(key=lambda a: a["algorithm"].lower())
    return list(groups.values())


def _registry_info(pipeline_id: str) -> dict:
    """get_info() satu pipeline dari registry. Tidak pernah melempar."""
    try:
        from config.pipeline_registry import get_pipeline_instance
        instance = get_pipeline_instance(pipeline_id)
        return (instance.get_info() or {}) if instance else {}
    except Exception:                       # pragma: no cover - defensif
        return {}


def group_problems(group: dict) -> list[str]:
    """Kalimat sebab untuk tiap algoritma yang tidak dapat dipakai.

    Dikumpulkan per grup supaya satu grup dengan beberapa pipeline bermasalah
    tidak mengulang kalimat yang sama.
    """
    from ui.i18n import t

    seen, out = set(), []
    for algo in group.get("algorithms") or []:
        state = algo.get("state") or STATE_OK
        if state == STATE_OK:
            continue
        reason = str(algo.get("state_reason") or "").strip()
        name = algo.get("algorithm") or algo.get("pipeline_id") or ""
        if state == STATE_BROKEN:
            line = f"**{name}** — {t('re.cat_broken_heading')}: {reason}"
        else:
            line = f"**{name}** — {reason}"
        if line not in seen:
            seen.add(line)
            out.append(line)
    return out


def catalog_counts(catalog) -> dict:
    """Jumlah research pipeline & algoritma — DIHITUNG, bukan angka tetap."""
    groups = list(catalog or [])
    return {"research": len(groups),
            "algorithms": sum(len(g.get("algorithms") or []) for g in groups)}


def summary_text(counts: dict) -> str:
    return (f"{counts.get('research', 0)} research pipeline · "
            f"{counts.get('algorithms', 0)} algoritma tersedia")


# ── Isi MODAL: pasangan label–nilai + bagian yang dilipat ─────────────────

# Baris label–nilai tingkat RESEARCH, dengan ikon kecil sebagai penanda label.
# Nilainya biasanya sama untuk semua algoritma dalam satu keluarga; bila ternyata
# berbeda, seluruh varian ikut disebut agar tidak ada yang disembunyikan.
_MODAL_ROW_FIELDS = (
    ("dataset", "Dataset", "🗂"),
    ("app", "Fokus trafik", "🎯"),
    ("feature_selection", "Feature selection", "🧮"),
    ("train_test_split", "Pembagian train/test", "✂"),
)

# Bagian sekunder — tertutup secara bawaan.
_MODAL_SECTION_FIELDS = (
    ("fixed_params", "Hyperparameter terkunci"),
    ("preprocessing_steps", "Langkah preprocessing"),
    ("anti_leakage", "Anti-kebocoran"),
    ("metrics_policy", "Kebijakan metrik"),
)

_SCHEMA_ROW_ICON = "📐"
_ALGO_ROW_ICON = "⚙"
_PAPER_ROW_ICON = "📄"


def _distinct_values(group: dict, key: str) -> list[str]:
    """Nilai berbeda untuk sebuah kunci get_info di seluruh algoritma grup."""
    seen: list[str] = []
    for algo in group.get("algorithms") or []:
        text = _as_text((algo.get("info") or {}).get(key)).strip()
        if text and text not in seen:
            seen.append(text)
    return seen


def modal_rows(group: dict) -> list[tuple[str, str, str]]:
    """(ikon, label, nilai) untuk badan modal — hanya yang benar-benar ada.

    Menggabungkan tiga sumber terstruktur: ``get_info()`` tiap algoritma, skema
    dataset (format & kolom label), dan registry (daftar algoritma) serta
    atribusi penelitian (paper).
    """
    rows: list[tuple[str, str, str]] = []

    for key, label, icon in _MODAL_ROW_FIELDS:
        values = _distinct_values(group, key)
        if values:
            rows.append((icon, label, plain_text(" / ".join(values))))

    # Format berkas & kolom label datang dari SKEMA, bukan dari get_info.
    for line in group.get("dataset_lines") or []:
        label, _, value = line.partition(": ")
        if value:
            rows.append((_SCHEMA_ROW_ICON, plain_text(label), plain_text(value)))

    algorithms = group.get("algorithms") or []
    if algorithms:
        rows.append((_ALGO_ROW_ICON, f"Algoritma ({len(algorithms)})",
                     ", ".join(a["algorithm"] for a in algorithms)))

    if group.get("paper"):
        rows.append((_PAPER_ROW_ICON, "Paper", plain_text(group["paper"])))
    return rows


def modal_sections(group: dict) -> list[tuple[str, list[tuple[str, object]]]]:
    """[(judul bagian, [(algoritma, nilai)])] untuk bagian yang dilipat.

    Per algoritma, karena hyperparameter & langkah preprocessing memang berbeda
    antar algoritma di dalam satu research pipeline.
    """
    sections = []
    for key, title in _MODAL_SECTION_FIELDS:
        entries = [(algo["algorithm"], (algo.get("info") or {}).get(key))
                   for algo in group.get("algorithms") or []
                   if (algo.get("info") or {}).get(key)]
        if entries:
            sections.append((title, entries))
    return sections


# ── Syarat utama sebuah research pipeline (untuk pop-up "tidak ada yang cocok")

def run_requirements(dataset_type: str) -> list[tuple[str, str]]:
    """(label, syarat) paling menentukan, dari SKEMA dataset.

    Dipakai saat tidak ada dataset yang cocok: pengguna perlu tahu apa yang
    kurang, bukan sekadar diberi tahu bahwa kosong.
    """
    wanted = ("Format berkas", "Kolom label")
    rows = []
    for line in dataset_lines(dataset_type):
        label, _, value = line.partition(": ")
        if label in wanted and value:
            rows.append((label, plain_text(value)))
    return rows


# ── Graf fase pipeline ────────────────────────────────────────────────────

# Tahap yang dijalankan ORCHESTRATOR sebelum pipeline dipanggil. Dibedakan
# gayanya supaya tidak terbaca sebagai bagian dari pipeline itu sendiri.
# Rumusan acuan — diimpor & diuji test lama. Kalimat yang TAMPIL datang dari
# katalog lewat `pre_stages()`/`pre_stage_note()`: konstanta modul dievaluasi
# sekali saat impor, jadi menerjemahkannya di sini akan membekukannya pada
# bahasa yang kebetulan aktif.
PRE_STAGES = ("Parsing & validasi dataset",)
PRE_STAGE_NOTE = ("Tahap bergaris putus dijalankan platform sebelum pipeline "
                  "dipanggil, bukan bagian dari pipeline-nya.")

PRE_STAGE_KEYS = ("pc.pre_stage_parse",)
PRE_STAGE_NOTE_KEY = "pc.pre_stage_note"


def pre_stage_labels() -> tuple[str, ...]:
    """Tahap milik platform, pada bahasa aktif.

    Namanya sengaja BEDA dari parameter `pre_stages` di bawah — nama yang sama
    akan tertutupi parameternya, dan tahap platform hilang tanpa satu pun
    galat.
    """
    return tuple(t(key) for key in PRE_STAGE_KEYS)


def pre_stage_note() -> str:
    """Keterangan tahap bergaris putus, pada bahasa aktif."""
    return t(PRE_STAGE_NOTE_KEY)

# Ambang: di atas ini grafnya digulir mendatar, bukan dibungkus ke banyak baris.
GRAPH_CARD_W = 132
GRAPH_CARD_H = 62
GRAPH_GAP = 34


def phase_graph_stages(pipeline_id: str, info: dict, *,
                       registry_reader=None) -> list[dict]:
    """Tahap NYATA sebuah pipeline, urut, dari sumber terstruktur.

    Sumbernya dua, keduanya benar-benar ada:

    * ``stages`` pada registry — daftar tahap prosedural yang dipakai worker
      untuk melaporkan progres, jadi persis tahap yang dijalankan;
    * ``feature_selection`` dari ``get_info()`` — hanya ditambahkan bila
      pipeline itu MEMANG memakainya.

    Jumlah & isinya berbeda antar pipeline (Naive Bayes 3 tahap, SVC 5, EVE 9),
    dan fungsi ini tidak pernah menyeragamkannya menjadi satu template.
    """
    if registry_reader is None:
        from config.pipeline_registry import get_pipeline
        registry_reader = get_pipeline

    entry = registry_reader(pipeline_id) or {}
    stages = [str(s) for s in (entry.get("stages") or []) if str(s).strip()]

    graph = [{"label": s, "kind": "stage", "note": ""} for s in stages]

    fs = (info or {}).get("feature_selection")
    if uses_feature_selection(fs):
        # Diselipkan sebelum tahap pelatihan — di situlah seleksi fitur bekerja.
        index = next((i for i, s in enumerate(graph)
                      if "train" in s["label"].lower()), len(graph))
        graph.insert(index, {"label": "Feature selection", "kind": "stage",
                             "note": shorten(_as_text(fs), 60)})
    return graph


def uses_feature_selection(value) -> bool:
    """Apakah pipeline BENAR-BENAR memakai seleksi fitur.

    Sebagian pipeline HIKARI mengisi bidang ini dengan kalimat yang artinya
    "tidak ada" (mis. "None — all numeric features used"). Menampilkannya
    sebagai tahap akan menyesatkan, jadi kasus itu dikenali di sini.
    """
    text = _as_text(value).strip().lower()
    if not text:
        return False
    return not text.startswith(("none", "tidak", "-"))


def phase_graph_svg(stages, *, pre_stages=None) -> str:
    """Kartu tahap berjajar mendatar, dihubungkan garis. SVG inline murni.

    Lebarnya mengikuti jumlah tahap; wadahnya menggulir mendatar sehingga
    pipeline berfase panjang tidak dibungkus ke banyak baris.

    **Kenapa atribut presentasi, bukan kelas CSS.** Setiap bentuk membawa
    ``fill``/``stroke``/``font-size`` sendiri di dalam atribut. Sebelumnya
    warnanya diserahkan ke kelas ``.ids-ph-*`` di stylesheet katalog; bila blok
    gaya itu tidak ikut ke dalam cakupan DOM yang sama (mis. di dalam modal),
    ``<rect>`` jatuh ke bawaan SVG — **isi hitam pekat** — dan grafnya tidak
    terbaca. Dengan atribut inline, graf ini tampil benar tanpa stylesheet apa
    pun.

    **Aman lintas tema.** Semua warna memakai ``currentColor`` beropasitas
    rendah, jadi ia mengikuti warna teks tema yang aktif — tidak ada nilai heksa
    yang bisa menghilang di tema terang atau gelap.
    """
    stages_before = pre_stage_labels() if pre_stages is None else pre_stages
    nodes = ([{"label": s, "kind": "pre", "note": ""} for s in stages_before]
             + list(stages or []))
    if not nodes:
        return ""

    width = len(nodes) * GRAPH_CARD_W + max(0, len(nodes) - 1) * GRAPH_GAP + 8
    height = GRAPH_CARD_H + 26
    parts: list[str] = []

    for index, node in enumerate(nodes):
        x = 4 + index * (GRAPH_CARD_W + GRAPH_GAP)
        if index:                           # garis penghubung ke kartu sebelumnya
            parts.append(
                f'<line class="ids-ph-link" x1="{x - GRAPH_GAP}" '
                f'y1="{GRAPH_CARD_H / 2:.0f}" x2="{x}" '
                f'y2="{GRAPH_CARD_H / 2:.0f}" stroke="currentColor" '
                f'stroke-width="1.5" stroke-opacity=".55" />')
        # Tahap PRA-PIPELINE dibedakan: garis putus + isi lebih pudar, supaya
        # tidak terbaca sebagai bagian dari pipeline itu sendiri.
        is_pre = node["kind"] == "pre"
        dashed = ' stroke-dasharray="4 3"' if is_pre else ""
        parts.append(
            f'<rect class="ids-ph-card" x="{x}" y="0" width="{GRAPH_CARD_W}" '
            f'height="{GRAPH_CARD_H}" rx="8"{dashed} '
            f'fill="currentColor" fill-opacity="{".04" if is_pre else ".07"}" '
            f'stroke="currentColor" stroke-opacity="{".35" if is_pre else ".55"}" '
            f'stroke-width="1" />')
        parts.append(
            f'<text class="ids-ph-num" x="{x + 10}" y="18" fill="currentColor" '
            f'fill-opacity=".45" font-size="10">{index + 1}</text>')
        for line_no, chunk in enumerate(_wrap(node["label"], 18)[:2]):
            parts.append(
                f'<text class="ids-ph-label" x="{x + 10}" '
                f'y="{34 + line_no * 13}" fill="currentColor" '
                f'font-size="11">{escape(chunk)}</text>')

    alt = " → ".join(n["label"] for n in nodes)
    # `overflow-x:auto` inline juga: gulir mendatar tetap bekerja meski
    # stylesheet katalog tidak ikut ke cakupan DOM ini.
    return (
        f'<div class="ids-ph-wrap" role="img" aria-label="{escape(alt)}" '
        f'style="overflow-x:auto;overflow-y:hidden;padding:.2rem 0 .4rem">'
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'style="display:block" '
        f'xmlns="http://www.w3.org/2000/svg"><title>{escape(alt)}</title>'
        f'{"".join(parts)}</svg></div>'
    )


def _wrap(text: str, width: int) -> list[str]:
    """Pemenggal kata sederhana untuk label kartu."""
    words, lines, current = str(text or "").split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def phase_graph_alt(stages, *, pre_stages=None) -> str:
    """Keterangan teks graf — tetap terbaca bila SVG tidak tampil."""
    stages_before = pre_stage_labels() if pre_stages is None else pre_stages
    names = list(stages_before) + [s["label"] for s in (stages or [])]
    return " → ".join(names)


def render_phase_graph(pipeline_id: str, info: dict) -> None:
    """Graf fase satu pipeline + keterangan teksnya.

    Dirender lewat :func:`streamlit.html`, BUKAN
    ``st.markdown(unsafe_allow_html=True)``. Alasannya menentukan: markdown
    Streamlit melewati react-markdown, yang membangun ulang HTML mentah menjadi
    elemen React di namespace HTML — ``<rect>``/``<line>``/``<text>`` di
    dalamnya tidak menjadi bentuk SVG, sehingga grafnya tidak tergambar.
    ``st.html`` menyisipkan markup lewat DOMPurify, yang memang mengizinkan
    namespace SVG. Bila versi Streamlit terlalu lama untuk punya ``st.html``,
    baru jatuh ke markdown.
    """
    stages = phase_graph_stages(pipeline_id, info)
    if not stages:
        st.caption(t("re.msg_no_stages"))
        return
    markup = phase_graph_svg(stages)
    if hasattr(st, "html"):
        st.html(markup)
    else:                                   # pragma: no cover - Streamlit lama
        st.markdown(markup, unsafe_allow_html=True)
    # SATU baris: urutan tahap (teks alternatif graf) + keterangan tahap
    # pra-pipeline, sebelumnya dua caption bertumpuk.
    st.caption(f"{phase_graph_alt(stages)} — {pre_stage_note()}")


# ── Perenderan blok katalog ───────────────────────────────────────────────

def _line(text: str, css_class: str) -> None:
    st.markdown(f'<div class="{css_class}">{escape(str(text))}</div>',
                unsafe_allow_html=True)


def row_meta_text(group: dict) -> str:
    """Metadata kanan atas — HANYA dari data yang sudah ada.

    Dua keping, keduanya sudah dipakai di tempat lain pada halaman ini: kode
    jenis dataset (``dataset_type``) dan banyaknya algoritma pada research
    pipeline itu. Tidak ada informasi baru yang diperkenalkan di sini.
    """
    count = len(group.get("algorithms") or [])
    parts = [str(group.get("dataset_type") or "").strip()]
    if count:
        parts.append(f"{count} algoritma")
    return " · ".join(p for p in parts if p)


def row_head_html(group: dict) -> str:
    """Tiga tingkat teks satu baris katalog + metadata kanan atas.

    Urutannya: nama penelitian (+metadata rata kanan) -> keterangan utama ->
    penjelasan redup. Ketiganya dari sumber terstruktur:

    * nama         -> ``config/research_attribution`` (nama beratribusi);
    * keterangan   -> bidang ``scope`` sumber atribusi yang sama;
    * penjelasan   -> kredit paper (``get_info()['paper']`` / registry).

    Penjelasan DIPOTONG satu baris oleh CSS (``text-overflow: ellipsis``),
    bukan dipotong di sini — teks lengkapnya tetap utuh di atribut ``title``
    sehingga muncul sebagai tooltip, dan tetap tersedia di pop-up Detail.
    """
    # Nama TIDAK dipotong pada jumlah karakter: berapa yang muat ditentukan
    # lebar baris yang sedang tersedia, bukan angka tetap. Ia membungkus bila
    # perlu, dan langsung menampilkan lebih banyak begitu sidebar ditutup atau
    # jendela diperlebar.
    name = escape(str(group.get("title") or ""))
    meta = escape(row_meta_text(group))
    lead = str(group.get("short") or "").strip()
    note = str(group.get("paper") or "").strip()

    parts = [
        f'<div class="ids-cat-head"><div class="ids-cat-name">{name}</div>'
        f'<div class="ids-cat-meta">{meta}</div></div>'
    ]
    if lead:
        parts.append(f'<div class="ids-cat-lead" title="{escape(lead)}">'
                     f'{escape(lead)}</div>')
    if note:
        parts.append(f'<div class="ids-cat-note" title="{escape(note)}">'
                     f'{escape(note)}</div>')
    return "".join(parts)


def chips_html(names) -> str:
    """Daftar algoritma sebagai chip satu baris. Isinya di-escape.

    Menerima daftar nama (bentuk lama) ATAU daftar entri algoritma; bentuk
    entri membawa asal, versi, dan keadaannya.
    """
    chips = "".join(_chip_html(item) for item in names or [])
    return f'<div class="ids-cat-chips">{chips}</div>'


def _chip_html(item) -> str:
    """Satu chip. Nama saja, atau nama + penanda asal/keadaan."""
    from ui.i18n import t

    if not isinstance(item, dict):
        return f'<span class="ids-cat-chip">{escape(str(item))}</span>'

    label = escape(str(item.get("algorithm") or item.get("pipeline_id") or ""))
    marks, title, extra = [], "", ""

    if item.get("uploaded"):
        # Asal & versi dinyatakan pada chipnya sendiri: pembaca tidak perlu
        # membuka detail untuk tahu ini pipeline kontribusi.
        marks.append(escape(t("re.cat_badge_contributed",
                              version=item.get("version") or "?")))

    state = item.get("state") or STATE_OK
    if state == STATE_BROKEN:
        marks.append(escape(t("re.cat_state_broken")))
        title = str(item.get("state_reason") or "")
        extra = " ids-cat-chip-broken"
    elif state == STATE_NO_DATASET:
        marks.append(escape(t("re.cat_state_no_dataset")))
        title = str(item.get("state_reason") or "")
        extra = " ids-cat-chip-warn"

    suffix = (f'<span class="ids-cat-chip-mark">{" · ".join(marks)}</span>'
              if marks else "")
    tooltip = f' title="{escape(title)}"' if title else ""
    return (f'<span class="ids-cat-chip{extra}"{tooltip}>'
            f'{label}{suffix}</span>')


def rows_html(rows) -> str:
    """Seluruh pasangan label–nilai sebagai SATU blok markup.

    Digabung menjadi satu string karena Streamlit membungkus tiap panggilan
    ``st.markdown`` dalam wadahnya sendiri — memecahnya akan memutus daftar.
    """
    items = "".join(
        f'<div class="ids-cat-row">'
        f'<span class="ids-cat-row-label">{escape(icon)} {escape(label)}</span>'
        f'<span class="ids-cat-row-value">{escape(value)}</span></div>'
        for icon, label, value in rows or [])
    return f'<div class="ids-cat-rows">{items}</div>'


def render_catalog(catalog=None, *, on_detail=None,
                   on_run=None) -> str | None:
    """Blok RINGKAS per research pipeline: nama, penjelasan singkat, algoritma.

    Tidak ada keterangan lain di sini — semuanya pindah ke modal, yang dibuka
    lewat tombol "Detail". Tombol itu HANYA memanggil ``on_detail`` (yang men-set
    flag); fungsi ber-``@st.dialog`` tidak pernah dipanggil dari dalam
    kolom/container.

    Mengembalikan dataset_type yang tombolnya ditekan, atau None. Kedua
    callback (``on_detail``, ``on_run``) hanya menulis flag — dialognya dibuka
    dari alur utama halaman.
    """
    catalog = build_catalog() if catalog is None else catalog
    st.markdown(_CSS, unsafe_allow_html=True)

    # DUA elemen pengantar saja: satu baris hitungan + satu petunjuk singkat.
    # Nama tombolnya sudah jelas, jadi fungsinya tidak dijelaskan lagi.
    counts = catalog_counts(catalog)
    st.markdown(f'<span class="ids-cat-count">{escape(summary_text(counts))}'
                f'</span>', unsafe_allow_html=True)


    requested = None
    for group in catalog:
        # BARIS, bukan kartu: container TANPA batas. Garis pemisah selebar
        # penuh, padding, dan efek sorot datang dari CSS terpusat lewat kelas
        # `st-key-<key>` yang muncul karena container ini berkunci.
        with st.container(border=False, key=row_key(group["dataset_type"])):
            st.markdown(row_head_html(group), unsafe_allow_html=True)

            st.markdown(chips_html(group.get("algorithms") or []),
                        unsafe_allow_html=True)

            # Sebab pipeline tidak dapat dipakai dinyatakan sebagai KALIMAT,
            # bukan hanya tooltip — tooltip tidak terbaca di layar sentuh dan
            # tidak terbaca pembaca layar.
            for problem in group_problems(group):
                st.caption(problem)

            # Dua kolom berukuran SAMA -> kedua tombol selebar & setinggi sama,
            # sejajar pada satu garis dasar; lebar tetapnya dikunci di CSS.
            cols = st.columns([1, 1, 3])
            if cols[0].button(t("re.btn_run_short"), type="primary",
                              key=f"cat_run_{group['dataset_type']}",
                              use_container_width=True,
                              help=t("re.help_find_dataset")):
                requested = group["dataset_type"]
                if on_run is not None:
                    on_run(requested)
            # Aksi SEKUNDER — sengaja lebih tenang daripada aksi utama.
            if cols[1].button(t("re.btn_detail"), key=f"cat_detail_{group['dataset_type']}",
                              type="tertiary", use_container_width=True,
                              help=t("re.help_full_detail")):
                requested = group["dataset_type"]
                if on_detail is not None:
                    on_detail(requested)
    return requested


# ── Perenderan isi modal ──────────────────────────────────────────────────

def render_modal_body(group: dict) -> None:
    """Kepala + pasangan label–nilai + bagian yang dilipat.

    Aksinya (Tutup / Jalankan) dirender pemanggil, karena hanya halaman yang
    tahu cara berpindah ke tampilan eksekusi.
    """
    st.markdown(_CSS, unsafe_allow_html=True)

    st.markdown(
        f'<div class="ids-cat-title">{escape(group["title"])} '
        f'<span class="ids-cat-chip ids-cat-chip-accent">'
        f'{escape(group["dataset_type"])}</span></div>',
        unsafe_allow_html=True)
    if group.get("short"):
        _line(group["short"], "ids-cat-short")

    st.markdown(rows_html(modal_rows(group)), unsafe_allow_html=True)

    st.markdown("**Tahapan pipeline**")
    st.caption(t("cat.stages_differ"))
    algorithms = group.get("algorithms") or []
    if algorithms:
        tabs = st.tabs([a["algorithm"] for a in algorithms])
        for tab, algo in zip(tabs, algorithms):
            with tab:
                render_phase_graph(algo["pipeline_id"], algo.get("info") or {})

    for title, entries in modal_sections(group):
        with st.expander(title, expanded=False):
            for algorithm, value in entries:
                st.markdown(f"**{algorithm}**")
                _render_value(value)

    with st.expander(t("re.dlg_dataset_req"), expanded=False):
        _render_dataset_requirements(group["dataset_type"])


def _render_value(value) -> None:
    """Nilai get_info apa pun, dirender seperlunya."""
    if isinstance(value, (list, tuple)):
        st.markdown("\n".join(f"- {item}" for item in value))
    elif isinstance(value, dict):
        st.markdown("\n".join(f"- `{k}`: {v}" for k, v in value.items()))
    else:
        st.caption(str(value))


def _render_dataset_requirements(dataset_type: str) -> None:
    """Persyaratan dataset — memakai penyaji yang SUDAH ADA di halaman
    Run Experiment, bukan salinan kedua."""
    try:
        from ui.views.run_experiment import _render_dataset_requirements as presenter
    except Exception:                       # pragma: no cover - defensif
        st.caption(t("re.msg_no_requirements"))
        return
    presenter(dataset_type)

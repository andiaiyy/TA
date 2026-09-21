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

from ui.i18n import localized, t

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
from ui.components.tables import dataset_code
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
/* PENELITI: baris tersendiri tepat di bawah nama pipeline. Lebih redup
   daripada namanya dan lebih tegas daripada penjelasan di bawahnya — ia
   menjawab "karya siapa", bukan "pipeline ini apa". */
.ids-cat-by {
    font-size: .88rem; font-weight: 400; opacity: .72;
    line-height: 1.4; margin: .05rem 0 .3rem;
}
.ids-cat-lead {
    font-size: .95rem; font-weight: 400; line-height: 1.5;
    width: 100%;
    max-width: var(--ids-cat-textw, 46rem);
    overflow-wrap: anywhere; margin: 0 0 .25rem;
}
@media (prefers-reduced-motion: reduce) {
    .ids-cat-head, .ids-cat-name, .ids-cat-lead {
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
/* ── "Keterangan metode": dua kolom yang RAPAT ────────────────────────────
   Baris fakta di atas memasangkan label dengan satu nilai pendek, jadi kolom
   labelnya boleh lebar dan nilainya rata kanan. Di sini nilainya BLOK berbaris
   banyak, dan aturan yang sama menghasilkan dua cacat sekaligus: jurang kosong
   selebar hampir separuh kartu, lalu isinya terjepit di sisa lebar.

   Labelnya karena itu hanya selebar yang dibutuhkan ("Langkah preprocessing"
   adalah yang terpanjang), sisanya milik isinya. */
.ids-cat-rows-detail .ids-cat-row {
    gap: .75rem;
    /* Label sejajar dengan PUNCAK bloknya, bukan dengan garis dasar baris
       pertama: satu label untuk blok setinggi sepuluh baris. */
    align-items: flex-start;
    padding: .45rem 0;
}
.ids-cat-rows-detail .ids-cat-row-label {
    flex: 0 0 28%;
    max-width: 28%;
    overflow-wrap: anywhere;
    line-height: 1.5;
}
.ids-cat-rows-detail .ids-cat-row-value {
    text-align: left;
    /* `min-width: 0` MENENTUKAN: bawaan flex item adalah `auto`, yang menolak
       menyusut di bawah lebar isinya — satu baris panjang lalu mendorong
       kolomnya melebar dan seluruh halaman ikut dapat digeser mendatar. */
    min-width: 0;
    overflow-wrap: anywhere;
}
/* Hyperparameter & langkah: nama algoritma dibedakan dari nilainya oleh tebal
   dan jarak, bukan oleh ukuran huruf keempat — ia mewarisi ukuran kolom
   nilai. Tidak ada elipsis di mana pun: yang panjang MEMBUNGKUS, sebab yang
   dipotong di sini adalah nilai parameter, dan nilai setengah tidak berarti. */
.ids-hp-algo { font-weight: 600; margin: .45rem 0 .1rem; }
.ids-hp-algo:first-child { margin-top: 0; }
.ids-hp-param { opacity: .75; line-height: 1.5; overflow-wrap: anywhere; }

/* Layar lebih sempit: jaraknya dirapatkan lagi sebelum kolomnya ditumpuk. */
@media (max-width: 60rem) {
    .ids-cat-rows-detail .ids-cat-row { gap: .5rem; }
    .ids-cat-rows-detail .ids-cat-row-label { flex-basis: 30%; max-width: 30%; }
}
/* Layar sangat sempit: labelnya PINDAH ke atas isinya. Dua kolom pada lebar
   telepon berarti keduanya terjepit, dan yang terjepit bukan lagi tabel. */
@media (max-width: 38rem) {
    .ids-cat-rows-detail .ids-cat-row { display: block; }
    .ids-cat-rows-detail .ids-cat-row-label {
        display: block; max-width: none; margin-bottom: .2rem;
    }
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


def research_facts(dataset_type: str) -> dict:
    """Cakupan + institusi + tahun sebuah research, dari SATU pembacaan.

    Ketiganya tinggal di sumber atribusi yang sama. Membacanya sekali per grup
    membuat penyaring kategori tidak menambah satu pun kueri: katalog memang
    sudah membaca atribusi itu untuk kalimat penjelasannya.

    Kosong bukan kesalahan. Atribusi tersimpan adalah POTRET saat persetujuan,
    dan pengajuan yang disetujui sebelum formulirnya diperluas tidak membawa
    institusi maupun tahun sama sekali.
    """
    try:
        from orchestrator.research_registry import (
            attribution_for as get_research_attribution,
        )
        attribution = get_research_attribution(dataset_type) or {}
    except Exception:                       # pragma: no cover - defensif
        return {"scope": "", "institution": "", "year": ""}

    key = attribution.get("scope_key")
    source = attribution.get("pipeline_source") or {}
    return {
        # Research BAWAAN memakai kunci katalog (diterjemahkan); research
        # KONTRIBUSI menyimpan kalimatnya sendiri, dan kalimat itu boleh
        # dwibahasa — `localized` yang memilih bahasanya.
        "scope": t(key) if key else localized(attribution.get("scope", "")),
        # Kredit penelitiannya. Ia milik BARIS RESEARCH, bukan kode
        # pipeline-nya: baris itulah yang dapat disunting Research Admin, dan
        # untuk research kontribusi ia satu-satunya tempat kreditnya dapat
        # diperbaiki tanpa mengajukan ulang seluruh paket.
        "credit": localized(attribution.get("paper_credit", "")),
        "institution": str(source.get("institution") or "").strip(),
        "year": str(source.get("year") or "").strip(),
    }


def research_scope(dataset_type: str) -> str:
    """Penjelasan singkat satu kalimat, dari bidang `scope` sumber atribusi."""
    return research_facts(dataset_type)["scope"]


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

    dataset_type = entry.get("dataset_type")
    if not has_dataset_for(dataset_type):
        # Dua sebab yang berbeda, dan karena itu dua jalan keluar yang berbeda.
        # Research pipeline KONTRIBUSI hanya boleh memakai dataset yang terikat
        # padanya; mengunggah berkas ke `storage/datasets/` tidak akan pernah
        # menolongnya. Kalimat lama menyuruh tepat itu — sebuah instruksi yang
        # tidak mungkin berhasil.
        from database.models import is_uploaded_research

        return STATE_NO_DATASET, t(
            "re.cat_no_dataset_reason_uploaded"
            if is_uploaded_research(dataset_type or "")
            else "re.cat_no_dataset_reason")
    return STATE_OK, ""


def has_dataset_for(dataset_type: str | None) -> bool:
    """Adakah dataset yang dapat dipakai jenis ini? Tidak pernah melempar.

    Publik karena halaman "Aktif" membacanya juga: tanpa itu tabel di sana
    menyebut sebuah pipeline "aktif" sementara halaman Jalankan Eksperimen
    menyebutnya belum dapat dijalankan — dua halaman, dua kebenaran.
    """
    if not dataset_type:
        return False
    try:
        from ui.views.run_experiment import _list_dataset_files, _schema_of

        # Skema GABUNGAN: bawaan + kontrak yang dideklarasikan kontributor.
        # Sebelumnya di sini terpasang `contracts.get_schema`, yang hanya
        # mengenal jenis bawaan — sehingga SETIAP research pipeline kontribusi
        # dinyatakan "belum ada datasetnya", tanpa pertanyaan itu pernah sampai
        # ke `_list_dataset_files`, satu-satunya yang tahu bahwa paket
        # kontribusi membawa datasetnya sendiri.
        if not _schema_of(dataset_type):
            return False                     # jenis yang benar-benar asing
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
        if dataset_type not in groups:
            facts = research_facts(dataset_type)
        group = groups.setdefault(dataset_type, {
            "dataset_type": dataset_type,
            "title": group_title(dataset_type, name_reader),
            # Penjelasan SINGKAT satu kalimat — bukan karangan: `scope` memang
            # ada sebagai bidang tersendiri di sumber atribusi.
            "short": facts["scope"],
            # Dipakai penyaring kategori. Diambil dari pembacaan atribusi yang
            # SAMA dengan kalimat di atas — bukan kueri tambahan per kategori.
            "institution": facts["institution"],
            "year": facts["year"],
            "dataset_lines": dataset_lines(dataset_type),
            # Kredit dari baris research lebih dulu; `get_info()["paper"]`
            # tetap menjadi cadangan bagi research yang barisnya belum
            # membawa kredit apa pun (lihat isian di bawah). Urutan ini yang
            # membuat baris "Penelitian sumber" menyebut STUDI SUMBER pipeline
            # pada semua kartu, bukan kutipan dataset pada sebagian.
            "paper": facts["credit"],
            "algorithms": [],
        })
        if entry.get("uploaded"):
            # POTRET `get_info()`, diambil saat pipeline ini didaftarkan.
            # Katalog tetap tidak pernah memuat kode kontribusi — sekarang ia
            # tidak perlu, karena keterangannya sudah tersimpan bersama
            # barisnya. Yang dulu kosong bukan karena tidak ada keterangan,
            # melainkan karena tidak ada tempat menyimpannya.
            info = dict(entry.get("info") or {})
        else:
            info = {}
            try:
                info = info_reader(pipeline_id) or {}
            except Exception:               # pipeline rusak != katalog rusak
                info = {}
        state, reason = entry_state(pipeline_id, entry)
        summary = algorithm_summary(info)
        details = algorithm_details(info)
        # Potretnya kosong hanya bila pipeline ini terdaftar SEBELUM potret
        # ada. Kekosongan itu DINYATAKAN beserta cara mengisinya, bukan
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
            line = f"**{name}** · {t('re.cat_broken_heading')}: {reason}"
        else:
            line = f"**{name}** · {reason}"
        if line not in seen:
            seen.add(line)
            out.append(line)
    return out


# ── Cari & saring: fungsi MURNI, tampilan hanya merangkainya ──────────────
# Pola yang sama dengan antrean peninjauan (`submission_review.search_text` →
# `filter_pending` → `result_note`), supaya kedua daftar berperilaku sama dan
# diuji dengan cara yang sama — tanpa Streamlit.

#: Nilai untuk grup yang TIDAK menyebutkan kategori itu. Ia sebuah pilihan
#: tersendiri, bukan ketiadaan: tanpa itu, menyaring institusi membuat setiap
#: pipeline kontribusi lama lenyap tanpa sebab yang terbaca.
UNSPECIFIED = "__unspecified__"

CATEGORY_ORIGIN = "origin"
CATEGORY_DATASET = "dataset_type"
CATEGORY_FORMAT = "file_format"
CATEGORY_ALGORITHM = "algorithm"
CATEGORY_INSTITUTION = "institution"
CATEGORY_YEAR = "year"


def _origin_values(group: dict) -> list[str]:
    uploaded = any(a.get("uploaded") for a in group.get("algorithms") or [])
    return [t("re.cat_origin_uploaded" if uploaded else "re.cat_origin_builtin")]


def _algorithm_values(group: dict) -> list[str]:
    return sorted({str(a.get("algorithm") or "").strip()
                   for a in group.get("algorithms") or []
                   if str(a.get("algorithm") or "").strip()})


def _format_values(group: dict) -> list[str]:
    """Format berkas dari baris kontrak yang SUDAH disusun untuk grup ini."""
    import re

    for line in group.get("dataset_lines") or []:
        label, _, value = line.partition(": ")
        if label.startswith("Format berkas"):
            # Yang diambil DAFTAR EKSTENSINYA, bukan potongan sebelum sebuah
            # tanda baca. Pengurai yang memotong pada tanda tertentu berhenti
            # bekerja diam-diam begitu kalimatnya ditulis ulang, dan itu sudah
            # pernah terjadi: pemisahnya berganti dan filter format berhenti
            # cocok tanpa satu pun galat.
            teks = plain_text(value)
            ekstensi = re.findall(r"\.[A-Za-z0-9]+", teks)
            if ekstensi:
                return [" / ".join(dict.fromkeys(ekstensi))]
            return [teks.strip()]
    return []


#: (kunci, kunci label, pembaca nilai). Urutannya urutan tampil.
CATEGORIES = (
    (CATEGORY_ORIGIN, "re.cat_by_origin", _origin_values),
    (CATEGORY_DATASET, "re.cat_by_dataset",
     lambda g: [str(g.get("dataset_type") or "").strip()]),
    (CATEGORY_FORMAT, "re.cat_by_format", _format_values),
    (CATEGORY_ALGORITHM, "re.cat_by_algorithm", _algorithm_values),
    (CATEGORY_INSTITUTION, "re.cat_by_institution",
     lambda g: [institution_label(g.get("institution"))]),
    (CATEGORY_YEAR, "re.cat_by_year",
     lambda g: [str(g.get("year") or "").strip()]),
)

_READERS = {key: reader for key, _label, reader in CATEGORIES}


def category_values(group: dict, category: str) -> list[str]:
    """Nilai satu grup untuk sebuah kategori; ``UNSPECIFIED`` bila tidak ada."""
    reader = _READERS.get(category)
    if reader is None:
        return [UNSPECIFIED]
    try:
        values = [v for v in (reader(group) or []) if v]
    except Exception:                       # pragma: no cover - defensif
        values = []
    return values or [UNSPECIFIED]


#: Kata yang MENANDAI sebuah lembaga di dalam alamat afiliasi yang panjang.
#: Dipakai memilih ruas mana yang layak menjadi label kotak centang.
_INSTITUTION_WORDS = ("universitas", "university", "institut", "institute",
                      "politeknik", "polytechnic", "sekolah tinggi", "akademi",
                      "college", "school")


def institution_label(raw: str) -> str:
    """Nama lembaga dari sebuah alamat afiliasi yang panjang.

    Aturannya dinyatakan, bukan potong sembarang. Afiliasi ditulis dari yang
    paling khusus ke paling umum dan sering berakhir pada KOTA:

        "Program Studi …, Fakultas Teknik, Universitas Hasanuddin, Gowa"

    Mengambil ruas terakhir menghasilkan "Gowa" — nama kota, bukan lembaga.
    Jadi yang dicari adalah ruas yang MENYEBUT lembaganya; bila tidak ada satu
    pun, barulah ruas terakhir dipakai. Nilai tanpa koma dibiarkan apa adanya.

    Hasilnya menjadi NILAI fasetnya, bukan sekadar labelnya: dua afiliasi yang
    berbeda kata demi kata tetapi menyebut lembaga yang sama harus menjadi SATU
    kotak centang. Dua kotak berlabel "Universitas Hasanuddin" berdampingan
    tidak dapat dibedakan oleh siapa pun yang membacanya.
    """
    parts = [p.strip() for p in str(raw or "").split(",") if p.strip()]
    if not parts:
        return ""
    for part in parts:
        if any(word in part.lower() for word in _INSTITUTION_WORDS):
            # Keterangan dalam kurung ("(afiliasi penulis pertama)") adalah
            # catatan, bukan bagian nama lembaganya.
            return part.split("(")[0].strip() or part
    return parts[-1]


def value_label(value: str) -> str:
    """Label sebuah nilai faset. Nilainya sudah siap baca; hanya penanda
    "tidak disebutkan" yang perlu diterjemahkan."""
    if value == UNSPECIFIED:
        return t("re.cat_value_unspecified")
    return str(value)


def catalog_search_text(group: dict) -> str:
    """Teks yang dicari untuk satu grup, huruf kecil.

    Seluruhnya dari yang SUDAH ada di grup — tidak ada berkas yang dibuka dan
    tidak ada kueri yang dijalankan untuk menyusunnya.
    """
    parts = [str(group.get("title") or ""), str(group.get("dataset_type") or ""),
             str(group.get("short") or ""), str(group.get("paper") or ""),
             str(group.get("institution") or ""), str(group.get("year") or "")]
    parts += _algorithm_values(group)
    return " ".join(p for p in parts if p).lower()


def filter_catalog(catalog, query: str):
    """Grup yang cocok dengan kata pencarian. Kosong = seluruhnya."""
    text = str(query or "").strip().lower()
    if not text:
        return list(catalog or [])
    return [g for g in catalog or [] if text in catalog_search_text(g)]


def catalog_categories(catalog) -> list[dict]:
    """Kategori yang LAYAK dipilih, beserta nilai & jumlahnya.

    Sebuah kategori dibuang bila nilainya kurang dari dua: penyaring dengan
    satu pilihan tidak menyaring apa pun, ia hanya memakan ruang. Inilah yang
    membuat daftarnya mengikuti isi katalog, bukan daftar tetap yang lama-lama
    menjadi bohong.
    """
    groups = list(catalog or [])
    out = []
    for key, label_key, _reader in CATEGORIES:
        counts: dict[str, int] = {}
        for group in groups:
            for value in category_values(group, key):
                counts[value] = counts.get(value, 0) + 1
        if len(counts) < 2:
            continue
        values = sorted(counts.items(),
                        key=lambda pair: (pair[0] == UNSPECIFIED,
                                          value_label(pair[0]).lower()))
        out.append({"key": key, "label": t(label_key), "values": values})
    return out


def apply_filters(catalog, selected: dict):
    """DAN antar kategori, ATAU di dalam satu kategori."""
    groups = list(catalog or [])
    for category, wanted in (selected or {}).items():
        chosen = set(wanted or ())
        if not chosen:
            continue
        groups = [g for g in groups
                  if chosen & set(category_values(g, category))]
    return groups


def active_filter_text(selected: dict) -> str:
    """Kalimat "Aktif: …" — penyaring yang menyembunyikan baris harus TERBACA.

    Penyaringan bertingkat aman hanya bila apa pun yang sedang menyaring tetap
    tercetak meski kategorinya sedang tidak dibuka.
    """
    labels = {key: t(label_key) for key, label_key, _ in CATEGORIES}
    parts = []
    for key, _label_key, _reader in CATEGORIES:
        chosen = sorted((selected or {}).get(key) or ())
        if chosen:
            parts.append(f"{labels[key]} = "
                         + ", ".join(value_label(v) for v in chosen))
    return " · ".join(parts)


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
# Ikonnya dipilih dengan dua syarat, dan yang lama melanggar keduanya: ia
# harus BERBEDA antar baris, dan harus tergambar sebagai emoji berwarna di
# semua peramban. `✂` dan `⚙` tanpa penanda varian jatuh ke bentuk teks
# monokrom, sehingga barisnya terlihat seperti simbol acak; `🧮` (sempoa) dan
# `🎯` tidak menyarankan apa pun tentang seleksi fitur maupun trafik.
# `dataset` dan `app` TIDAK di sini: keduanya bagian dari "Keterangan metode"
# pada formulir unggah, dan bagian itu kini digambar utuh di bawah. Selama
# keduanya ada di dua tempat, satu modal menyebut hal yang sama dua kali.
_MODAL_ROW_FIELDS = (
    ("feature_selection", "Feature selection", "🔎"),
    ("train_test_split", "Pembagian train/test", "✂️"),
)

# Bagian sekunder — tertutup secara bawaan.
# Bagian "Keterangan metode" — bidang, urutan, dan LABEL yang sama persis
# dengan blok "Keterangan metode" pada formulir unggah. Labelnya dibaca dari
# kunci katalog, bukan diketik ulang di sini: dua salinan label untuk satu
# bidang pasti menyimpang suatu saat, dan yang diketik ulang tidak ikut
# berpindah bahasa.
_MODAL_SECTION_FIELDS = (
    ("app", "ap.lbl_info_app"),
    ("metrics_policy", "ap.lbl_info_metrics"),
    ("dataset", "ap.lbl_info_dataset"),
    ("anti_leakage", "ap.lbl_info_anti_leakage"),
    ("preprocessing_steps", "ap.lbl_info_preprocessing"),
    ("fixed_params", "ap.lbl_info_fixed_params"),
)

# Baris SKEMA dahulu berbagi SATU ikon, sehingga "Format berkas", "Kolom
# label", dan "Kolom wajib" tergambar sebagai tiga baris yang tampak sama
# persis — ikon yang berulang berhenti menjadi penanda dan menjadi hiasan.
# Masing-masing kini menyebut isinya sendiri; yang tidak dikenali jatuh ke
# ikon umum alih-alih hilang.
_SCHEMA_ROW_ICONS = {
    "Format berkas": "📄",
    "File format": "📄",
    "Kolom label": "🏷️",
    "Label column": "🏷️",
    "Kolom wajib": "📋",
    "Required columns": "📋",
}
_SCHEMA_ROW_ICON = "📐"
_ALGO_ROW_ICON = "⚙️"
_PAPER_ROW_ICON = "📖"


def _distinct_values(group: dict, key: str) -> list[str]:
    """Nilai berbeda untuk sebuah kunci get_info di seluruh algoritma grup."""
    seen: list[str] = []
    for algo in group.get("algorithms") or []:
        # Keterangan yang diketik kontributor boleh dwibahasa; yang ditulis
        # kode selalu teks biasa dan lewat tanpa berubah.
        text = _as_text(localized((algo.get("info") or {}).get(key))).strip()
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
            bersih = plain_text(label)
            rows.append((_SCHEMA_ROW_ICONS.get(bersih, _SCHEMA_ROW_ICON),
                         bersih, plain_text(value)))

    algorithms = group.get("algorithms") or []
    if algorithms:
        rows.append((_ALGO_ROW_ICON, f"Algoritma ({len(algorithms)})",
                     ", ".join(a["algorithm"] for a in algorithms)))

    if group.get("paper"):
        rows.append((_PAPER_ROW_ICON, "Paper", plain_text(group["paper"])))
    return rows


def algorithm_sections(algo: dict) -> list[tuple[str, object]]:
    """[(label, nilai)] keterangan SATU algoritma; hanya bidang yang terisi.

    Per algoritma, karena hyperparameter & langkah preprocessing memang berbeda
    antar algoritma di dalam satu research pipeline.

    Kosong bila potret ``get_info()`` algoritma ini belum pernah diambil.
    Kekosongan itu DINYATAKAN pemanggil, bukan disembunyikan.
    """
    info = algo.get("info") or {}
    return [(t(label_key), localized(info.get(key)))
            for key, label_key in _MODAL_SECTION_FIELDS if info.get(key)]


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
# katalog lewat `pre_stage_labels()`: konstanta modul dievaluasi
# sekali saat impor, jadi menerjemahkannya di sini akan membekukannya pada
# bahasa yang kebetulan aktif.
PRE_STAGES = ("Parsing & validasi dataset",)

PRE_STAGE_KEYS = ("pc.pre_stage_parse",)


def pre_stage_labels() -> tuple[str, ...]:
    """Tahap milik platform, pada bahasa aktif.

    Namanya sengaja BEDA dari parameter `pre_stages` di bawah — nama yang sama
    akan tertutupi parameternya, dan tahap platform hilang tanpa satu pun
    galat.
    """
    return tuple(t(key) for key in PRE_STAGE_KEYS)


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
    # Urutan tahapnya saja. Keterangan "tahap bergaris putus dijalankan
    # platform…" DICABUT: garis putus pada grafnya sudah membedakan keduanya
    # secara visual, dan kalimat sepanjang itu di bawah tiap graf menerangkan
    # hal yang sama berulang-ulang pada setiap pipeline.
    st.caption(phase_graph_alt(stages))
    render_phase_files(stages, info)


def phase_file_rows(stages, info: dict) -> list[tuple[str, list[str]]]:
    """(nama fase, berkas yang bekerja padanya) untuk pipeline ini.

    Sumbernya peta penempatan yang ditetapkan Research Admin saat meninjau, dan
    ikut tersimpan pada potret keterangan baris registry. Ia MENERANGKAN:
    yang dijalankan tetap kelas titik masuk, dan peta ini tidak pernah
    menentukan berkas mana yang dimuat.

    Fase tanpa berkas TIDAK dibuang: rangkaian fasenya harus tetap terbaca
    utuh, dan fase yang kosong adalah keterangan tentang petanya, bukan tentang
    pipelinenya.

    Fungsi MURNI; daftar kosong berarti pipeline ini memang tidak punya peta.
    """
    berkas = (info or {}).get("file_placement")
    if not isinstance(berkas, list) or not berkas:
        return []
    keluar = []
    for tahap in stages or []:
        label = str((tahap or {}).get("label") or "")
        milik = [str(b.get("filename") or "") for b in berkas
                 if isinstance(b, dict)
                 and label in [str(f) for f in b.get("phases") or []]]
        keluar.append((label, sorted(n for n in milik if n)))
    return keluar


def render_phase_files(stages, info: dict) -> None:
    """Berkas yang bekerja pada tiap fase, di bawah graf fasenya.

    Tidak digambar sama sekali bila pipeline ini tidak punya peta penempatan:
    itu keadaan yang wajar bagi pipeline bawaan dan bagi paket yang peninjaunya
    belum menempatkan apa pun, jadi ia tidak perlu dikeluhkan di layar.
    """
    baris = phase_file_rows(stages, info)
    if not baris or not any(nama for _, nama in baris):
        return
    st.markdown(f"**{t('re.sec_phase_files')}**")
    for label, milik in baris:
        st.markdown(t("re.phase_files_row", phase=label,
                      files=", ".join(f"`{n}`" for n in milik)
                      if milik else t("re.phase_files_none")))


# ── Perenderan blok katalog ───────────────────────────────────────────────

def _line(text: str, css_class: str) -> None:
    st.markdown(f'<div class="{css_class}">{escape(str(text))}</div>',
                unsafe_allow_html=True)


def split_credit(title) -> tuple[str, str]:
    """``"<peneliti> · <nama>"`` menjadi ``(nama, peneliti)``. MURNI.

    Contohnya sengaja tidak memakai nama research yang sungguhan: modul ini
    tidak boleh memuat satu pun nama research, dan sebuah test menjaganya —
    yang dipaku di kode akan terus tampil setelah datanya berubah.

    Atribusi disusun sebagai satu label oleh `research_registry.
    short_label_from`, dan dipecah kembali di sini memakai pemisah yang SAMA —
    bukan ditebak. Judul tanpa pemisah dikembalikan apa adanya sebagai nama,
    tanpa peneliti: research yang atribusinya memang belum diisi tidak boleh
    kehilangan namanya hanya karena bentuknya berbeda.
    """
    from orchestrator.research_registry import LABEL_SEP

    mentah = str(title or "")
    teks = mentah.strip()
    if LABEL_SEP not in teks:
        # Dikembalikan APA ADANYA, tanpa dipangkas: yang tidak beratribusi
        # hanya dilewatkan, dan memangkasnya di sini berarti judulnya diam-diam
        # berubah pada satu jalur saja.
        return mentah, ""
    kredit, _, nama = teks.partition(LABEL_SEP)
    kredit, nama = kredit.strip(), nama.strip()
    return (nama or teks), (kredit if nama else "")


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
    # Judulnya dipecah: NAMA pipeline lebih dulu, penelitinya di baris
    # sendiri. Sebagai satu baris "<peneliti> · <nama>", yang pertama dibaca
    # mata adalah nama orangnya — padahal yang dicari pembaca katalog adalah
    # pipeline mana ini.
    nama_pipeline, peneliti = split_credit(group.get("title"))
    name = escape(nama_pipeline)
    lead = str(group.get("short") or "").strip()

    # TANPA baris metadata kanan atas. Ia memuat kode jenis dataset dan
    # banyaknya algoritma — keduanya sudah terbaca di tempat yang lebih
    # berguna: chip algoritma tepat di bawah kartu ini menyebutkan setiap
    # algoritmanya satu per satu, jadi angkanya hanya menghitung ulang apa
    # yang sudah terlihat, dan kode jenis dataset adalah pengenal mesin.
    parts = [
        f'<div class="ids-cat-head"><div class="ids-cat-name">{name}</div></div>'
    ]
    if peneliti:
        parts.append(f'<div class="ids-cat-by">{escape(peneliti)}</div>')
    if lead:
        parts.append(f'<div class="ids-cat-lead" title="{escape(lead)}">'
                     f'{escape(lead)}</div>')
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

    # Penanda "kontribusi v1" DICABUT. Asal dan versi adalah keterangan
    # pengelolaan, bukan yang dicari pembaca katalog, dan menempelkannya pada
    # tiap chip membuat baris algoritma terbaca dua kali lebih panjang tanpa
    # menambah satu pun keputusan. Keduanya tetap ada di modal Detail.
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


#: Kunci session_state penyaring katalog. Berawalan `_cat_` sehingga
#: `page_flags.VIEW_STATE_PREFIXES` membuangnya saat pengguna pindah halaman.
_QUERY_KEY = "_cat_query"
_CATEGORY_KEY = "_cat_category"
_SELECTED_KEY = "_cat_selected"


def _selected_filters() -> dict:
    return dict(st.session_state.get(_SELECTED_KEY) or {})


def _render_search_and_filters(catalog):
    """Kotak cari + kategori terpilih + nilainya. Mengembalikan grup yang tampil.

    Kategori dipilih DULU, nilainya menyusul — daftar enam kelompok kotak
    centang sekaligus akan menenggelamkan katalognya sendiri. Pilihan dari
    kategori lain TETAP berlaku saat berpindah kategori, dan justru karena itu
    seluruh penyaring aktif dicetak terus-menerus: penyaring yang menyembunyikan
    baris tanpa terbaca adalah cara tercepat membuat sebuah daftar terasa rusak.
    """
    categories = catalog_categories(catalog)
    cols = st.columns([3, 2])
    query = cols[0].text_input(t("re.cat_search"), key=_QUERY_KEY,
                               placeholder=t("re.cat_search_ph"))

    chosen_category = None
    if categories:
        labels = {c["key"]: c["label"] for c in categories}
        chosen_category = cols[1].selectbox(
            t("re.cat_filter_by"), list(labels), index=None,
            placeholder=t("re.cat_filter_none"), key=_CATEGORY_KEY,
            format_func=lambda key: labels[key])

    selected = _selected_filters()
    if chosen_category:
        current = set(selected.get(chosen_category) or ())
        entry = next(c for c in categories if c["key"] == chosen_category)
        boxes = st.columns(min(4, len(entry["values"])) or 1)
        picked = set()
        for i, (value, count) in enumerate(entry["values"]):
            label = f"{value_label(value)} ({count})"
            if boxes[i % len(boxes)].checkbox(
                    label, value=value in current,
                    key=f"_cat_v_{chosen_category}_{value}",
                    help=value if value != UNSPECIFIED else None):
                picked.add(value)
        selected[chosen_category] = sorted(picked)
        st.session_state[_SELECTED_KEY] = {k: v for k, v in selected.items() if v}
        selected = _selected_filters()

    visible = apply_filters(filter_catalog(catalog, query), selected)

    active = active_filter_text(selected)
    if active:
        line, clear = st.columns([5, 1])
        line.markdown(t("re.cat_active_filters", filters=active))
        if clear.button(t("re.cat_clear_filters"), key="_cat_clear",
                        use_container_width=True):
            for key in list(st.session_state):
                if str(key).startswith("_cat_"):
                    del st.session_state[key]
            st.rerun()

    # Jumlah hasil SELALU dinyatakan: penyaring tidak boleh memendekkan daftar
    # tanpa disadari.
    if query or selected:
        st.caption(t("re.cat_shown", shown=len(visible), total=len(catalog)))
    if not visible and (query or selected):
        from ui.components.sections import prose

        prose(t("re.cat_empty_filtered"), key="cat_empty_filtered")
    return visible


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

    visible = _render_search_and_filters(catalog)

    requested = None
    for group in visible:
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
            cols = st.columns([2, 2, 3])
            if cols[0].button(t("re.btn_setup"), type="primary",
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
        f'{escape(dataset_code(group["dataset_type"]))}</span></div>',
        unsafe_allow_html=True)
    if group.get("short"):
        _line(group["short"], "ids-cat-short")

    st.markdown(rows_html(modal_rows(group)), unsafe_allow_html=True)

    # Persyaratan dataset berdiri BERSAMA baris fakta di atas, bukan di bawah
    # tahapan: ia menerangkan researchnya secara keseluruhan — data apa yang
    # diterima — sedangkan segala yang menyusul di bawah adalah milik SATU
    # algoritma. Sebelumnya ia terdampar sebagai bagian terakhir, di bawah
    # dua bagian yang isinya berbeda-beda per algoritma.
    with st.expander(t("re.dlg_dataset_req"), expanded=False):
        _render_dataset_requirements(group["dataset_type"])

    # Bagian "Tahapan pipeline" DICABUT. Graf fasenya menggambar urutan
    # tahap yang sama pada hampir setiap algoritma, dan urutan itu bukan yang
    # dicari orang saat membuka Detail: yang dicari ada di "Keterangan metode"
    # tepat di bawah ini.
    markup = sections_html(group)
    if markup:
        st.markdown(f"**{t('re.dlg_method_notes')}**")
        st.markdown(markup, unsafe_allow_html=True)
    elif not any(algo.get("info") for algo in group.get("algorithms") or []):
        # Potretnya belum pernah diambil. Modal yang terbuka lalu tidak
        # menjelaskan apa pun lebih membingungkan daripada kekosongan yang
        # menyebut dirinya.
        st.markdown(uploaded_notice())


def inline_value(value) -> str:
    """Nilai get_info apa pun sebagai SATU baris teks.

    Daftar dan kamus dirapatkan dengan "; ", bukan dipecah menjadi bullet:
    empat bidang berisi dua-tiga butir masing-masing tumbuh menjadi belasan
    baris bullet, padahal yang dibaca orang hanya isinya.
    """
    if isinstance(value, dict):
        # Nilai yang SENDIRI berupa daftar dirapikan dulu: `repr` Python
        # menuliskannya sebagai ['DT'], dan tanda kutip itu keterangan bahasa
        # pemrograman, bukan keterangan pipeline.
        return "; ".join(f"{k} = {inline_value(v)}" for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return "; ".join(str(item).strip().rstrip(".") for item in value
                         if str(item).strip())
    return str(value).strip()


#: Kunci `get_info()` yang memuat hyperparameter. Dinamai, bukan diketik ulang
#: di dua tempat: penyajinya memperlakukan bidang ini berbeda dari yang lain.
HYPERPARAM_KEY = "fixed_params"

#: Setelan INTERNAL: berapa proses paralel, berapa lipatan validasi, berapa
#: baris yang disampel, dan batas pengaman. Semuanya nyata dan tetap tercatat
#: di `get_info()`; yang dibuang hanya tampilannya di modal, sebab tak satu pun
#: dari angka itu menjelaskan perbedaan ANTAR algoritma — dan justru merekalah
#: yang membuat barisnya menjadi kalimat panjang bertitik koma.
_HP_HIDDEN = frozenset({"n_jobs", "cv_folds", "learning_curve_cv"})
_HP_HIDDEN_SUFFIX = ("_sample_rows", "_train_rows", "_cap")
_HP_HIDDEN_PREFIX = ("enforce_",)


def visible_params(params) -> list[tuple[str, str]]:
    """[(nama, nilai)] hyperparameter yang DITAMPILKAN. MURNI.

    Urutannya urutan `get_info()` apa adanya: itulah urutan yang ditulis
    penulis pipeline-nya, dan mengurutkannya sendiri akan menyembunyikan
    pengelompokan yang ia maksud.
    """
    if not isinstance(params, dict):
        return []
    keluar = []
    for kunci, nilai in params.items():
        nama = str(kunci)
        if (nama in _HP_HIDDEN
                or nama.endswith(_HP_HIDDEN_SUFFIX)
                or nama.startswith(_HP_HIDDEN_PREFIX)):
            continue
        keluar.append((nama, inline_value(nilai)))
    return keluar


def hyperparam_blocks(group: dict) -> list[tuple[str, list]]:
    """[(algoritma, [(nama, nilai)])] untuk algoritma yang punya isinya."""
    keluar = []
    for algo in group.get("algorithms") or []:
        params = visible_params((algo.get("info") or {}).get("fixed_params"))
        if params:
            keluar.append((algo["algorithm"], params))
    return keluar


def value_lines(value, *, hide_internal: bool = False) -> list[str]:
    """Nilai get_info apa pun sebagai BARIS-BARIS, bukan satu kalimat.

    Kamus menjadi "nama = nilai" per baris, daftar menjadi satu butir per
    baris, dan teks yang memang ditulis sebagai daftar bertitik koma dipecah
    kembali pada titik komanya. Yang terakhir paling menentukan: langkah
    preprocessing EVE adalah SATU string sepanjang empat baris kolom, dan
    sebagai satu baris ia hanya dapat dibaca kata demi kata.

    Tidak ada yang dibuang, kecuali bila ``hide_internal`` — dan itu hanya
    dipakai hyperparameter (lihat :func:`visible_params`).
    """
    if isinstance(value, dict):
        pasangan = (visible_params(value) if hide_internal
                    else [(str(k), inline_value(v)) for k, v in value.items()])
        return [f"{k} = {v}" for k, v in pasangan]
    if isinstance(value, (list, tuple)):
        return [str(item).strip().rstrip(".") for item in value
                if str(item).strip()]
    teks = str(value or "").strip()
    if not teks:
        return []
    return [b.strip() for b in teks.split("; ") if b.strip()]


def field_blocks(group: dict, key: str, *,
                 hide_internal: bool = False) -> list[tuple[str, list]]:
    """[(algoritma, [baris])] untuk satu bidang; hanya yang terisi. MURNI."""
    keluar = []
    for algo in group.get("algorithms") or []:
        baris = value_lines(localized((algo.get("info") or {}).get(key)),
                            hide_internal=hide_internal)
        if baris:
            keluar.append((algo["algorithm"], baris))
    return keluar


def _block_row(label: str, blocks, *, bernama: bool) -> str:
    """Satu baris label-nilai yang isinya BLOK, bukan satu kalimat.

    Labelnya disebut SEKALI di kolom kiri, sejajar dengan seluruh blok di
    kanannya. Sebelumnya tiap algoritma mendapat barisnya sendiri, sehingga
    research berisi enam algoritma mengulang label yang sama enam kali dan
    perbedaan yang justru dicari orang tenggelam di antaranya.
    """
    potongan = []
    for nama, baris in blocks:
        if bernama:
            potongan.append(f'<div class="ids-hp-algo">{escape(nama)}</div>')
        potongan.extend(f'<div class="ids-hp-param">{escape(b)}</div>'
                        for b in baris)
    return (f'<div class="ids-cat-row">'
            f'<span class="ids-cat-row-label">{escape(label)}</span>'
            f'<span class="ids-cat-row-value">{"".join(potongan)}</span></div>')


def hyperparams_html(group: dict) -> str:
    """Hyperparameter sebagai SATU baris: label kiri sekali, isi per algoritma."""
    blok = hyperparam_blocks(group)
    if not blok:
        return ""
    return _block_row(t("re.dlg_hyperparams"),
                      [(nama, [f"{k} = {v}" for k, v in params])
                       for nama, params in blok],
                      bernama=len(blok) > 1)


def sections_html(group: dict) -> str:
    """Seluruh "Keterangan metode" sebagai TABEL label-nilai.

    Bentuknya sengaja sama dengan baris fakta di atasnya: kolom label kelabu,
    kolom nilai, garis pemisah tipis. SATU baris per bidang, tanpa satu pun
    label yang berulang. Bidang yang nilainya sama pada setiap algoritma
    ditulis tanpa menyebut nama algoritma sama sekali; yang berbeda menyebut
    nama tiap algoritma sebagai judul kecil di atas nilainya.
    """
    algorithms = group.get("algorithms") or []
    potongan = []
    for key, label_key in _MODAL_SECTION_FIELDS:
        rahasia = key == HYPERPARAM_KEY
        blocks = field_blocks(group, key, hide_internal=rahasia)
        if not blocks:
            continue
        label = t("re.dlg_hyperparams") if rahasia else t(label_key)
        seragam = (len(blocks) == len(algorithms)
                   and len({tuple(baris) for _n, baris in blocks}) == 1)
        potongan.append(_block_row(
            label, blocks[:1] if seragam else blocks, bernama=not seragam))
    if not potongan:
        return ""
    return ('<div class="ids-cat-rows ids-cat-rows-detail">'
            + "".join(potongan) + "</div>")


def group_sections(group: dict) -> list[tuple[str, list]]:
    """[(label, [(nama algoritma | None, teks)])] keterangan SELURUH algoritma.

    Bidang yang nilainya SAMA pada setiap algoritma ditulis sekali, dengan
    ``None`` sebagai nama: pada research yang algoritmanya berbagi satu
    praproses, menulisnya per algoritma berarti mengulang paragraf yang sama
    empat kali dan membuat satu-satunya bidang yang benar-benar berbeda
    tenggelam di antaranya. Yang berbeda tetap ditulis per algoritma, sebab
    perbedaannya justru isi yang perlu dibaca.

    Bidang yang hanya dimiliki sebagian algoritma dihitung BERBEDA, bukan sama:
    "tidak punya" adalah keterangan tersendiri, dan menyamakannya dengan nilai
    tetangganya akan mengarang isi.
    """
    per_algoritma = [(algo["algorithm"], dict(algorithm_sections(algo)))
                     for algo in group.get("algorithms") or []]
    keluar = []
    for _key, label_key in _MODAL_SECTION_FIELDS:
        title = t(label_key)
        nilai = [(nama, inline_value(bagian.get(title, "")))
                 for nama, bagian in per_algoritma]
        terisi = [(nama, teks) for nama, teks in nilai if teks]
        if not terisi:
            continue
        seragam = (len(terisi) == len(nilai)
                   and len({teks for _n, teks in terisi}) == 1)
        keluar.append((title, [(None, terisi[0][1])] if seragam else terisi))
    return keluar


def shared_stages(group: dict):
    """Algoritma yang tahapannya dipakai BERSAMA, atau ``None`` bila berbeda.

    Grafnya digambar sekali bila semua algoritma menjalankan tahap yang sama.
    Begitu ada satu yang berbeda, seluruhnya digambar sendiri-sendiri: graf
    gabungan akan menyembunyikan justru perbedaan yang ingin dilihat orang.
    """
    algorithms = list(group.get("algorithms") or [])
    if not algorithms:
        return None
    tahap = [phase_graph_stages(algo["pipeline_id"], algo.get("info") or {})
             for algo in algorithms]
    pertama = repr(tahap[0])
    return algorithms[0] if all(repr(t) == pertama for t in tahap) else None


def _render_dataset_requirements(dataset_type: str) -> None:
    """Persyaratan dataset — memakai penyaji yang SUDAH ADA di halaman
    Run Experiment, bukan salinan kedua."""
    try:
        from ui.views.run_experiment import _render_dataset_requirements as presenter
    except Exception:                       # pragma: no cover - defensif
        st.caption(t("re.msg_no_requirements"))
        return
    presenter(dataset_type)

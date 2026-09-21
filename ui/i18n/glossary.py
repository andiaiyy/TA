"""
Padanan istilah TETAP.

Satu konsep, satu kata — di seluruh platform, pada kedua bahasa. Tanpa daftar
seperti ini, "pengajuan" pelan-pelan menjadi *submission* di satu halaman dan
*proposal* di halaman lain, dan pembaca mengira keduanya hal berbeda. Pada
platform penelitian itu bukan sekadar tidak rapi: istilah yang bergeser membuat
pembacanya salah menyimpulkan apa yang dilakukan sistem.

Dipakai dua cara:

* sebagai **acuan** saat menulis kunci baru di :mod:`ui.i18n.catalog`;
* sebagai **penjaga**: test menelusuri seluruh kamus dan menolak sinonim yang
  sudah ditetapkan sebagai terlarang (lihat ``FORBIDDEN_SYNONYMS``).

Beberapa istilah sengaja TIDAK diterjemahkan dan itu keputusan, bukan kelalaian
— alasannya ditulis di sebelahnya.
"""
from __future__ import annotations

#: Konsep → (istilah Indonesia, istilah Inggris).
GLOSSARY: dict[str, tuple[str, str]] = {
    # Inti domain.
    "research_pipeline": ("research pipeline", "research pipeline"),
    # ^ Dipakai apa adanya di kedua bahasa: ia nama golongan objek di platform
    #   ini, bukan kata umum. Menerjemahkannya menjadi "alur penelitian" akan
    #   memutus kaitannya dengan `pipeline_id` yang dilihat pengguna.
    "dataset": ("dataset", "dataset"),
    "experiment": ("eksperimen", "experiment"),
    "submission": ("pengajuan", "submission"),
    "review": ("peninjauan", "review"),
    "approval": ("persetujuan", "approval"),
    "approve": ("setujui", "approve"),
    "reject": ("tolak", "reject"),
    "version": ("versi", "version"),
    "upload": ("unggah", "upload"),
    "compatibility": ("kecocokan", "compatibility"),

    # Mode eksekusi.
    "official_run": ("resmi", "official"),
    "exploration_run": ("eksplorasi", "exploration"),
    "run_mode": ("mode eksekusi", "run mode"),

    # Peran.
    "contributor": ("Kontributor", "Contributor"),
    "visitor": ("Pengunjung", "Visitor"),
    "research_admin": ("Research Admin", "Research Admin"),
    # ^ Nama peran, sama seperti nama algoritma — tetap sama di kedua bahasa.

    # Istilah pendukung yang juga mudah bergeser.
    "entry_point": ("titik masuk", "entry point"),
    "support_file": ("berkas pendukung", "support file"),
    "hash": ("hash", "hash"),
    "validation": ("validasi", "validation"),
    "static_check": ("pemeriksaan statis", "static check"),
    "active": ("aktif", "active"),
    "inactive": ("nonaktif", "inactive"),
    "pending_review": ("menunggu tinjauan", "awaiting review"),
    "artifact": ("artefak", "artifact"),
    "metric": ("metrik", "metric"),
    "sample": ("cuplikan", "sample"),
}

#: Sinonim yang DILARANG, beserta istilah yang harus dipakai sebagai gantinya.
#: Ditegakkan test atas seluruh kamus — inilah yang mencegah istilah bergeser
#: diam-diam saat kunci baru ditambahkan.
#: Awalan kunci yang DIKECUALIKAN dari pemeriksaan sinonim terlarang.
#:
#: "uji coba" terdaftar sebagai sinonim terlarang untuk "eksperimen", dan itu
#: tetap benar: hasil penelitian tidak boleh disebut uji coba, dan sebaliknya.
#: Tetapi ada satu konsep yang memang BUKAN eksperimen — menjalankan pipeline
#: yang belum disetujui untuk memutuskan kelayakannya. Menyebutnya
#: "eksperimen" justru yang keliru: ia tidak tercatat sebagai eksperimen,
#: tidak masuk riwayat, dan hasilnya dibuang setelah keputusan diambil.
#:
#: Pengecualiannya sengaja DIPERSEMPIT ke awalan ini saja, sehingga aturan
#: aslinya tetap menjaga seluruh kunci lain.
SYNONYM_EXEMPT_PREFIXES: tuple[str, ...] = ("trial.", "td.")


FORBIDDEN_SYNONYMS: dict[str, str] = {
    # Indonesia
    "submisi": "pengajuan",
    "review-an": "peninjauan",
    "approve-an": "persetujuan",
    "upload-an": "unggahan",
    "percobaan": "eksperimen",
    "uji coba": "eksperimen",
    "kompatibilitas": "kecocokan",
    "alur penelitian": "research pipeline",
    # Inggris
    "proposal": "submission",
    "trial": "experiment",
    "run mode official": "official run mode",
    "checking": "check",
}


def indonesian(concept: str) -> str:
    return GLOSSARY[concept][0]


def english(concept: str) -> str:
    return GLOSSARY[concept][1]


def forbidden_terms_in(text: str) -> list[str]:
    """Sinonim terlarang yang muncul di ``text``. Kosong = bersih."""
    low = (text or "").lower()
    return sorted(bad for bad in FORBIDDEN_SYNONYMS if bad in low)

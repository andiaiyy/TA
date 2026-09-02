"""
Apa yang TIDAK PERNAH diterjemahkan.

Ditulis sebagai aturan yang dapat dieksekusi, bukan sekadar catatan: Tahap 2 & 3
akan menyentuh ribuan string, dan "ingat jangan menerjemahkan nama peneliti"
tidak akan bertahan sebanyak itu. :func:`is_protected` dipakai test untuk
membuktikan bahwa nilai-nilai ini identik di kedua bahasa.

Alasan tiap golongan:

* **Atribusi penelitian** — nama karya orang. Menerjemahkan judul penelitian
  memutus jejaknya ke sumber aslinya dan, pada skripsi, itu salah kutip.

  Yang dilindungi adalah JUDUL KARYA dan nama penulisnya — apa yang akan
  ditulis pada daftar pustaka. Kalimat yang MENJELASKAN penelitian itu bukan
  judulnya: ringkasan cakupan yang ditulis platform sendiri
  (`scope` pada `config/research_attribution.py`) adalah teks antarmuka biasa
  dan JUSTRU harus diterjemahkan. Pembedaannya: bila mengubah kalimat itu
  akan membuat kutipannya salah, ia judul; bila tidak, ia deskripsi.
* **Identitas pipeline, dataset, kolom, berkas** — pengenal yang dipakai untuk
  mencocokkan data. Menerjemahkannya tidak hanya membingungkan, tetapi membuat
  nilainya tidak lagi cocok dengan isi basis data dan artefak.
* **Nama field kontrak, metode, kelas, potongan kode** — dibaca mesin.
* **Nama algoritma & istilah metrik** — sudah berupa istilah Inggris yang lazim
  dipakai apa adanya dalam tulisan Indonesia di bidang ini; menerjemahkannya
  justru membuat pembaca Indonesia lebih sulit mengenalinya.
* **Nilai dari basis data/artefak/berkas pengguna** — bukan teks antarmuka.
  Menerjemahkan data pengguna berarti mengubah data.
"""
from __future__ import annotations

#: Golongan yang tidak diterjemahkan, beserta contohnya. Dipakai test sebagai
#: daftar periksa, dan dibaca manusia sebagai aturan.
NEVER_TRANSLATE: dict[str, tuple[str, ...]] = {
    # JUDUL karya + atribusi penulisnya. Bukan deskripsi tentang karya itu —
    # lihat `TRANSLATE_ANYWAY` di bawah.
    "atribusi_penelitian": (
        "Rayyan (2024) — Klasifikasi Trafik Terenkripsi HIKARI2021",
        "Niswar dkk. (2026) — Feature Engineering Suricata EVE Logs",
    ),
    "identitas_pipeline": (
        "hikari2021.dt_pipeline", "hikari2021.nbgc_pipeline",
        "uploaded.contoh@v2",
    ),
    "nama_dataset": (
        "HIKARI2021", "EVE", "ALLFLOWMETER_HIKARI2021.csv",
    ),
    "kolom_dataset": (
        "Label", "Target", "traffic_category", "originh", "responh",
    ),
    "field_kontrak": (
        "fixed_params", "feature_selection", "preprocessing_steps",
        "metrics_policy", "entry_class", "pipeline_id", "dataset_type",
    ),
    "metode_dan_kelas": (
        "BasePipeline", "run", "get_info", "PipelineInput",
    ),
    "nama_algoritma": (
        "Random Forest", "XGBoost", "Decision Tree", "Naive Bayes",
        "Gaussian Naive Bayes", "SVC", "Logistic Regression",
    ),
    "istilah_metrik": (
        "accuracy", "precision", "recall", "f1_score", "F1", "ROC AUC",
        "confusion matrix",
    ),
}

#: Yang MIRIP terlindungi tetapi sebenarnya harus diterjemahkan. Ditulis
#: sebagai daftar agar pembedaannya tidak bergantung pada ingatan: keduanya
#: hidup berdampingan di berkas atribusi yang sama.
TRANSLATE_ANYWAY: dict[str, str] = {
    "scope": "Ringkasan cakupan penelitian — kalimat yang ditulis platform "
             "untuk menjelaskan sebuah karya, bukan judul karyanya.",
}


#: Semua contoh di atas, diratakan — bentuk yang dipakai :func:`is_protected`.
PROTECTED_VALUES: frozenset[str] = frozenset(
    value for values in NEVER_TRANSLATE.values() for value in values)


def is_protected(text: str) -> bool:
    """True bila ``text`` termasuk yang tidak boleh diterjemahkan.

    Pencocokan tepat, bukan substring: ``"Label"`` sebagai nama kolom dilindungi,
    tetapi kalimat yang kebetulan memuat kata itu tidak ikut terkunci.
    """
    return (text or "").strip() in PROTECTED_VALUES


def protected_group(text: str) -> str:
    """Nama golongan pelindung sebuah nilai, atau "" bila tidak dilindungi."""
    needle = (text or "").strip()
    for group, values in NEVER_TRANSLATE.items():
        if needle in values:
            return group
    return ""

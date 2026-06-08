"""Tutorial page — static guide on how to use the platform.

Content is grounded in the actual dataset flow (manual placement into
storage/datasets/, no file uploader), the actual supported formats from
contracts/dataset_schemas.py, and the actual folder paths from
config/settings.py. No interaction with experiment data; safe to import
and render without any preconditions.
"""
import streamlit as st

from config.settings import BASE_DIR, STORAGE_DIR, DATASETS_DIR, ARTIFACTS_DIR


def _relative(path) -> str:
    """Show paths relative to project root for readability."""
    try:
        return str(path.relative_to(BASE_DIR)).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def render() -> None:
    st.title("Tutorial Penggunaan Platform")

    # ── A. Pengantar singkat ──────────────────────────────────────────────
    st.markdown(
        "Platform ini menjalankan eksperimen klasifikasi *Intrusion Detection System* "
        "berbasis *machine learning* dengan pipeline ML yang dikunci per paper rujukan. "
        "Pengguna memilih dataset dan pipeline lewat antarmuka web; eksekusi, "
        "pencatatan metadata, dan penyimpanan artefak dilakukan otomatis. Tujuan utama "
        "platform adalah reproduksibilitas: eksperimen yang sama akan menghasilkan "
        "metrik yang sama selama dataset dan kode pipeline tidak berubah."
    )

    # ── B. Struktur Folder dan Lokasi Dataset ─────────────────────────────
    st.header("Struktur Folder dan Lokasi Dataset")

    storage_rel = _relative(STORAGE_DIR)
    datasets_rel = _relative(DATASETS_DIR)
    artifacts_rel = _relative(ARTIFACTS_DIR)

    tree = f"""{storage_rel}/
├── datasets/                  <- LETAKKAN BERKAS DATASET DI SINI (read-only saat eksekusi)
│   ├── ALLFLOWMETER_HIKARI2021.csv   (contoh: dataset HIKARI2021)
│   └── eve_100k.json                 (contoh: dataset EVE Suricata, NDJSON)
├── artifacts/                 <- hasil eksperimen tersimpan otomatis di sini
│   └── {{experiment_id}}/
│       ├── model.pkl                 (model terlatih, joblib)
│       ├── metrics.json              (metrik utama + extra_info)
│       └── metadata.json             (dataset_hash, pipeline_id, environment)
└── experiments.db             <- basis data SQLite metadata eksperimen (otomatis)
"""
    st.code(tree, language="text")

    st.markdown(
        f"Folder `{datasets_rel}/` adalah satu-satunya lokasi yang perlu disentuh "
        f"pengguna. Letakkan berkas dataset di sana sebelum membuka halaman "
        f"**Run Experiment**. Folder `{artifacts_rel}/` dan berkas "
        f"`{_relative(STORAGE_DIR / 'experiments.db')}` diisi dan dikelola otomatis "
        f"oleh platform; tidak perlu (dan sebaiknya tidak) dimodifikasi manual."
    )

    st.warning(
        "Platform ini saat ini tidak menyediakan widget unggah berkas di antarmuka. "
        "Berkas dataset harus diletakkan langsung di folder di atas sebelum eksperimen "
        "dijalankan. Setelah berkas berada di folder yang benar, dropdown pada halaman "
        "Run Experiment akan mendeteksinya secara otomatis."
    )

    # ── C. Alur Penggunaan Platform ───────────────────────────────────────
    st.header("Alur Penggunaan")

    st.markdown(
        f"1. **Siapkan dataset.** Letakkan berkas CSV (HIKARI2021) atau "
        f"NDJSON (EVE Suricata) di `{datasets_rel}/`.  \n"
        "2. **Buka halaman Run Experiment** dari menu sidebar.  \n"
        "3. **Pilih jenis dataset** dengan menekan salah satu kartu tipe dataset. "
        "Sebuah dialog akan muncul menampilkan berkas yang cocok dari folder dataset.  \n"
        "4. **Konfirmasi berkas dataset** pada dialog, lalu tekan tombol **Validate "
        "Dataset**. Platform memeriksa skema, menghitung *hash* SHA-256, dan menentukan "
        "pipeline yang kompatibel.  \n"
        "5. **Pilih pipeline** dari daftar yang muncul setelah validasi sukses. "
        "Detail pipeline (paper rujukan, hyperparameter, preprocessing) ditampilkan "
        "agar diketahui sebelum eksekusi.  \n"
        "6. **Jalankan eksperimen** dengan tombol **Run Experiment**. Status dan progres "
        "ditampilkan pada antarmuka. Bila platform berjalan dalam mode asinkron "
        "(Celery + Redis), eksperimen dapat ditinggal dan diperiksa kembali kemudian.  \n"
        "7. **Lihat hasil** di halaman **History** untuk metrik, *confusion matrix*, "
        "*ROC curve*, *feature importance*, dan unduhan laporan PDF."
    )

    # ── D. Format Dataset yang Didukung ───────────────────────────────────
    st.header("Format Dataset yang Didukung")

    st.markdown(
        "Hanya dua ekstensi yang diterima: `.csv` dan `.json` (NDJSON, satu objek JSON "
        "per baris). Validator menolak berkas selain itu dan menolak berkas di luar "
        "direktori dataset sebagai pengaman jalur."
    )

    st.subheader("HIKARI2021 (varian ALLFLOWMETER)")
    st.markdown(
        "Format: CSV.  \n"
        "Kolom label: `Label` (label biner: 0 = benign, 1 = malicious).  \n"
        "Berkas berisi 88 kolom fitur, mencakup *flow statistics*, *payload statistics*, "
        "dan *window/header counts*. Skema lengkap di `contracts/dataset_schemas.py`."
    )

    st.subheader("EVE Suricata")
    st.markdown(
        "Format: NDJSON (`.json`), satu objek JSON per baris.  \n"
        "Kunci tingkat-atas yang wajib ada minimal: `timestamp`, `flow_id`, "
        "`event_type`, `src_ip`, `src_port`, `dest_ip`, `dest_port`, `proto`. Kolom "
        "label tidak perlu ada di berkas; platform menurunkan label biner dari "
        "`alert.severity` pada Phase 1 pipeline EVE."
    )

    # ── E. Catatan Penting ────────────────────────────────────────────────
    st.header("Catatan Penting")

    st.info(
        "Hasil setiap eksperimen tersimpan otomatis di folder artefak. Eksperimen yang "
        "sudah selesai dapat dibuka kembali kapan saja dari halaman History dan "
        "diunduh sebagai laporan PDF, tanpa perlu dijalankan ulang."
    )
    st.info(
        "Kolom dataset harus sesuai skema. Bila skema tidak cocok, validasi akan "
        "gagal dengan pesan yang menyebutkan kolom yang hilang. Periksa berkas dataset "
        "sebelum menjalankan ulang."
    )
    st.warning(
        "Beberapa pipeline (misalnya SVC pada HIKARI2021 lengkap) berjalan sangat "
        "lambat pada dataset besar karena karakteristik algoritma. Platform "
        "menampilkan peringatan runtime sebelum eksekusi dimulai bila pipeline yang "
        "dipilih diketahui lambat."
    )

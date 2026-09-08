# BAGIAN 3/19 — FAKTA TERVERIFIKASI (SATU-SATUNYA SUMBER ANGKA)

Seluruh angka di bawah **diukur langsung dari repositori, basis data, dan
kontainer** pada 7 September 2026, bukan diperkirakan. Bila kamu butuh angka
yang tidak ada di sini, tulis `[PERLU_DIUKUR: ...]`.

---

## 1. Repositori dan riwayat

| Ruas | Nilai |
|---|---|
| Total commit | 43 |
| Commit sesudah seminar hasil | 9 (bertanda "1 after semhas" … "9 after semhas") |
| Commit terakhir | `9d182fe` — "9 after semhas" |
| Status pohon kerja | bersih (0 berkas berubah) |
| Repositori publik | https://github.com/andiaiyy/TA.git |

## 2. Ukuran basis kode

| Direktori | Berkas .py | Baris |
|---|---:|---:|
| pipelines/ | 78 | 48.239 |
| tests/ | 110 | 33.441 |
| ui/ | 39 | 22.555 |
| orchestrator/ | 19 | 7.693 |
| utils/ | 8 | 1.699 |
| database/ | 5 | 1.189 |
| workers/ | 5 | 779 |
| config/ | 5 | 409 |
| contracts/ | 3 | 117 |
| **Total berkas .py di repo** | **303** | — |

Catatan: tests/ memuat 110 berkas .py, di antaranya **103 berkas test_*.py**
(sisanya conftest dan modul bantu seperti render_cost dan grid_probe).

## 3. Pengujian otomatis

| Ruas | Nilai |
|---|---|
| Pengujian dikumpulkan | **3.073** |
| Lulus | **3.071** |
| Dilewati (skipped) | **2** |
| Gagal | **0** |
| Berkas tes | 103 |
| Durasi satu putaran penuh | ± 4–7 menit |
| Perintah | `python -m pytest -q` dengan `DB_PATH` menunjuk salinan basis data |

Nilai pembanding pada draf lama: 227 dikumpulkan, 225 lulus, 2 dilewati.

## 4. Internasionalisasi (i18n)

| Ruas | Nilai |
|---|---|
| Kunci teks | **1.309** |
| Terisi bahasa Indonesia | 1.309 (100%) |
| Terisi bahasa Inggris | 1.309 (100%) |
| Lokasi | ui/i18n/catalog.py |

## 5. Basis data

| Ruas | Nilai |
|---|---|
| Mesin | SQLite, mode WAL |
| Tabel aplikasi | **6** + 1 tabel versi skema |
| Jumlah migrasi | **31** (aditif, tidak ada yang merusak) |
| Versi skema pada basis data penelitian | **29** (migrasi 30 dan 31 belum diterapkan ke basis data hidup) |

Isi basis data penelitian saat pengukuran:

| Tabel | Baris |
|---|---:|
| experiments | 61 |
| users | 4 |
| submissions | 2 |
| registered_pipelines | 2 |
| research_pipelines | 1 |
| pipeline_trials | 0 |

Jumlah kolom per tabel: experiments **23**, registered_pipelines **19**,
submissions **16**, pipeline_trials **16**, users **11**,
research_pipelines **10**.

## 6. Registry pipeline

| Ruas | Nilai |
|---|---|
| Pipeline bawaan (PIPELINE_REGISTRY) | **10** (6 HIKARI2021 + 4 EVE) |
| Jenis dataset bawaan | 2 — HIKARI2021, EVE_SURICATA |
| Ruang nama pipeline kontribusi | `uploaded.<nama>_<kelas>@v<N>` |
| Ruang nama jenis dataset kontribusi | `uploaded:<nama>` |

## 7. Validator statis (orchestrator/pipeline_validator.py)

| Ruas | Nilai |
|---|---|
| Kelas induk wajib | BasePipeline |
| Metode wajib | run, get_info |
| Nama parameter run yang diwajibkan | `pipeline_input`, `progress` |
| Kunci get_info yang diwajibkan | **6**: paper, algorithm, preprocessing_steps, feature_selection, fixed_params, train_test_split |
| Modul yang diizinkan | **27** |
| Modul yang dilarang | **25** |
| Pemanggilan yang dilarang | **9** |
| Kelompok pemeriksaan | 2 — "Struktur" dan "Keamanan" |
| Nama cek keamanan | 6 — import terlarang, import di luar daftar, pemanggilan terlarang, penulisan berkas, atribut dunder terlarang, refleksi atribut |
| Batas ukuran berkas unggahan | 1.000.000 byte (± 0,95 MB) per berkas |
| Ekstensi pipeline yang diterima | .py |
| Ekstensi dataset yang diterima | .csv, .ndjson, .jsonl, .json |

**Daftar 27 modul yang diizinkan:** `__future__`, abc, catboost, collections,
config, contracts, dataclasses, decimal, enum, fractions, functools, imblearn,
itertools, joblib, lightgbm, math, numpy, operator, pandas, pipelines, scipy,
sklearn, statistics, statsmodels, typing, utils, xgboost.

**Daftar 25 modul yang dilarang:** builtins, cffi, ctypes, dill, ftplib, http,
httpx, imp, importlib, marshal, multiprocessing, os, pickle, pty, requests,
resource, runpy, shutil, signal, smtplib, socket, subprocess, sys, telnetlib,
urllib.

**Daftar 9 pemanggilan yang dilarang:** `__import__`, breakpoint, compile, eval,
exec, globals, input, locals, vars.

## 8. Uji coba (trial)

| Ruas | Nilai |
|---|---|
| Batas waktu | 300 detik (5 menit) |
| Batas baris dataset | 50.000 baris |
| Batas kedaluwarsa uji coba | 24 jam |
| Batas ukuran dataset lampiran | 25 MB |
| Direktori artefak uji coba | storage/trials/ |
| Status pengajuan | pending, approved, rejected |
| Jenis pengajuan | pipeline, dataset |

## 9. Peran dan otorisasi

| Ruas | Nilai |
|---|---|
| Peran | visitor (tanpa akun), contributor, research_admin |
| Fungsi pemeriksa izin | can_upload, can_approve, can_manage_users, can_run_experiment, can_view_experiments |
| Fungsi penegak izin (melempar) | require_upload, require_approve, require_manage_users |
| Hashing kata sandi | PBKDF2-HMAC-SHA256, **260.000 iterasi**, salt 16 byte, dari pustaka standar (hashlib) |
| Format simpanan | `pbkdf2_sha256$<iterasi>$<salt_hex>$<hash_hex>` |
| Status akun | active, pending, disabled |

## 10. Mode eksekusi (orchestrator/run_mode.py)

| Ruas | Nilai |
|---|---|
| Nilai run_mode | "official" (bawaan) dan "exploration" |
| Parameter terlindungi | **15 kunci** dalam **7 kategori** |
| Kategori | pemilihan algoritma; urutan & isi tahapan praproses; aturan pembagian latih/uji; metode seleksi fitur; pengaman anti-kebocoran; batas sumber daya worker; kontrak pelaporan metrik |
| Kolom pencatat | run_mode, params_used, params_changed pada tabel experiments |

## 11. Antarmuka

| Ruas | Nilai |
|---|---|
| Halaman navigasi | **3** — Progres & Status, Jalankan Eksperimen, Tambah Pipeline & Dataset |
| Modul tampilan (ui/views/) | 6 berkas + app.py |
| Komponen bersama (ui/components/) | 25 berkas |
| Komponen pihak ketiga | streamlit-aggrid, streamlit-option-menu |

## 12. Dependensi runtime (requirements.txt, 15 baris)

streamlit >= 1.30.0, pandas >= 2.0.0, numpy >= 1.24.0, scikit-learn >= 1.3.0,
joblib >= 1.3.0, matplotlib >= 3.7.0 < 3.11, pytest >= 7.4.0, reportlab >= 4.0.0,
imbalanced-learn >= 0.11.0, celery >= 5.3.0, redis >= 5.0.0, xgboost >= 2.0.0,
tqdm >= 4.65.0, **streamlit-aggrid >= 1.0.0**, **streamlit-option-menu >= 0.4.0**.

Tiga baris terakhir belum tercantum pada Tabel 5 draf.

## 13. Lingkungan eksekusi terukur

**Kontainer ids_worker:** Python 3.11.16, scikit-learn 1.9.0, pandas 3.0.5,
numpy 2.4.6, Celery 5.6.3, redis-py 8.1.0.

**Host (tempat test suite dijalankan):** Python 3.14.4, scikit-learn 1.9.0,
pandas 3.0.5, numpy 2.5.2, Streamlit 1.62.0.

**Docker:** Server 29.5.3; MemTotal 3.788.718.080 byte (± 3,53 GB); batas memori
ids_worker 3.670.016.000 byte (± 3,42 GiB); tiga layanan (ids_redis, ids_worker,
ids_ui) dengan **0 restart** selama rangkaian pengujian; pemakaian memori
terpantau: ids_worker 109,5 MiB, ids_ui 46,2 MiB, ids_redis 8,77 MiB.

## 14. Reproduktibilitas (verifikasi berkelanjutan)

Setiap tahap pengembangan sesudah seminar ditutup dengan pemeriksaan
reproduktibilitas: satu pipeline bawaan dijalankan ulang dan metriknya
dibandingkan dengan artefak lama. Hasil pada setiap pemeriksaan:
**IDENTICAL, delta +0** untuk accuracy, precision, recall, f1_score, dan
confusion matrix; ditambah pemeriksaan determinisme (dijalankan dua kali pada
lingkungan yang sama) yang juga **IDENTICAL**.

Artinya: seluruh penambahan subsistem kontribusi **tidak menggeser satu digit pun**
pada hasil Bab III yang sudah dilaporkan.

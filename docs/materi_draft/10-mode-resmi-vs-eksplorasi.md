# BAGIAN 10/19 — MODE RESMI VS EKSPLORASI (REVISI PRINSIP FIXED PIPELINE)

Ini revisi **paling halus** di seluruh materi, karena menyentuh salah satu dari
lima prinsip perancangan pada Tabel 1 draf. Kerjakan dengan hati-hati.

---

## 1. PERINGATAN: dua hal berbeda yang mudah tertukar

Draf sudah punya subbab **2.2.3.6 Mode Eksekusi Sinkron dan Asinkron**. Itu soal
**di mana** pipeline dijalankan (di dalam proses Streamlit vs di worker Celery),
dikendalikan variabel lingkungan `USE_ASYNC`.

Yang baru adalah **mode run (`run_mode`)**, yaitu soal **apakah parameter boleh
disesuaikan**, dikendalikan pengguna per-eksperimen. Keduanya **saling
tegak lurus**: sebuah run eksplorasi dapat berjalan sinkron maupun asinkron.

**Jangan menggabungkan kedua subbab.** Buat subbab baru, misalnya **2.2.3.8 Mode
Run Resmi dan Run Eksplorasi**, dan beri satu kalimat penegas bahwa ia berbeda
dari 2.2.3.6.

---

## 2. Revisi Tabel 1, baris "Fixed pipeline"

**Baris lama:**

| Prinsip | Inti rancangan | Kontribusi pada tujuan |
|---|---|---|
| Fixed pipeline | Hyperparameter dikunci permanen di berkas pipeline; pengguna hanya memilih dataset dan pipeline | Perbandingan terkendali yang adil dan reproducibility (hanya satu variabel uji) |

**Baris pengganti yang disarankan:**

| Prinsip | Inti rancangan | Kontribusi pada tujuan |
|---|---|---|
| Fixed pipeline (terkunci sebagai bawaan) | Hyperparameter dikunci di berkas pipeline dan menjadi bawaan setiap eksekusi; penyesuaian hanya mungkin pada run eksplorasi yang eksplisit, terbatas, dan berlabel, sementara parameter yang menentukan keterbandingan tidak pernah dapat diubah | Perbandingan terkendali yang adil dan reproducibility, tanpa menutup kebutuhan eksplorasi yang sah — karena hasil eksplorasi tidak pernah tercampur dengan hasil resmi |

---

## 3. Isi subbab baru (bahan lengkap)

### 3.1 Dua mode

| Mode | Nilai `run_mode` | Perilaku |
|---|---|---|
| **Run resmi** | `official` (bawaan; juga dipakai bila nilainya kosong atau tidak dikenal) | Seluruh parameter memakai nilai terkunci pipeline. Penyesuaian yang dikirim **dibuang**, bukan ditolak dengan galat. `params_changed = 0` |
| **Run eksplorasi** | `exploration` | Penyesuaian diterapkan setelah divalidasi terhadap batas aman. `params_used` mencatat nilai yang benar-benar dipakai; `params_changed` mencatat berapa kunci yang berbeda dari nilai terkunci |

**Keputusan rancangan yang layak dijelaskan:** mode resmi adalah **bawaan**, dan
nilai yang tidak dikenal juga diperlakukan sebagai resmi. Artinya, kesalahan
apa pun pada pemanggilan akan jatuh ke arah yang aman — tidak mungkin sebuah run
menjadi eksplorasi tanpa ada yang benar-benar memilihnya.

### 3.2 Parameter yang tidak pernah dapat disesuaikan

Lima belas kunci terlindungi, dikelompokkan menjadi tujuh kategori. Setiap
penolakan menyertakan **alasan yang ditampilkan apa adanya ke pengguna** —
bukan sekadar "tidak diizinkan".

| Kategori | Kunci | Alasan penguncian |
|---|---|---|
| Pemilihan algoritma | `models` | menentukan algoritma yang dilatih |
| Urutan & isi tahapan praproses | `balancing`, `scaler` | mengubahnya mengubah praproses |
| Aturan pembagian latih/uji | `test_size`, `stratify`, `modeling_train_rows` | menyamakan proporsi split antar pipeline adalah syarat perbandingan; stratifikasi menjaga distribusi kelas data uji |
| Metode seleksi fitur | `pca`, `fs_sample_rows` | metode reduksi/seleksi fitur dan cakupan datanya |
| Pengaman anti-kebocoran | `enforce_row_level_conversion_cap`, `corr_leak_sample_rows` | pengaman konversi tingkat baris dan cakupan pemeriksaan kebocoran korelasi |
| Batas sumber daya worker | `n_jobs`, `cv_folds`, `learning_curve_cv`, `visualization_sample_rows` | paralelisme dan biaya komputasi worker, bukan hyperparameter model |
| Kontrak pelaporan metrik | `probability` | dibutuhkan `predict_proba` untuk ROC-AUC yang dilaporkan |

**Inilah yang menjaga klaim standarisasi tetap utuh.** Yang dibuka untuk
eksplorasi hanyalah hyperparameter **algoritmanya**; yang menentukan apakah dua
pipeline masih dapat dibandingkan — urutan praproses, aturan split, seleksi
fitur, dan pengaman anti-kebocoran — tetap terkunci pada kedua mode.

### 3.3 Contoh konkret (boleh dikutip)

| Pipeline | Terkunci | Dapat disesuaikan pada mode eksplorasi |
|---|---|---|
| `hikari2021.rfc_pipeline` | n_estimators 100, random_state 42, n_jobs 2, balancing RandomUnderSampler, scaler StandardScaler, pca False, test_size 0,3, stratify True | `n_estimators` (bilangan bulat, 1–500), `random_state` (0–100.000) |
| `hikari2021.knn_pipeline` | n_neighbors 5, random_state 42, balancing, scaler, pca, test_size, stratify | `n_neighbors` (1–100), `random_state` (0–100.000) |
| `eve_cbr.xgb` | models, fs_sample_rows, modeling_train_rows, visualization_sample_rows, corr_leak_sample_rows, n_jobs, cv_folds, enforce_row_level_conversion_cap | **tidak ada** |

Baris terakhir penting: pipeline EVE **tidak membuka satu pun** parameter untuk
disesuaikan, karena seluruh parameternya jatuh ke kategori terlindungi. Ini
menunjukkan bahwa daftar terlindungi bukan formalitas.

### 3.4 Batas nilai

Batas atas dipilih supaya eksplorasi tetap bermakna tetapi tidak dapat memicu
beban komputasi ekstrem pada worker, mengingat RAM efektif ± 3,5 GB. Nilai di
luar batas ditolak dengan pesan yang menyebut batasnya, bukan dipotong diam-diam.

### 3.5 Pencatatan dan pembedaan hasil

Tiga kolom baru pada tabel `experiments`:

| Kolom | Isi |
|---|---|
| `run_mode` | `official` atau `exploration` |
| `params_used` | nilai parameter yang benar-benar dipakai, sebagai JSON |
| `params_changed` | jumlah kunci yang berbeda dari nilai terkunci |

Hasil eksplorasi diberi **lencana pembeda** pada tabel riwayat dan pada laporan
PDF, sehingga tidak mungkin tertukar dengan hasil resmi ketika dibaca kemudian.
Nilai `run_mode` dicatat **sebelum** status QUEUED, sehingga setiap baris punya
mode sejak lahirnya.

---

## 4. Argumen mengapa ini memperkuat, bukan melemahkan, kontribusi penelitian

Tulis paragraf yang isinya kira-kira begini:

> Membuka penyesuaian parameter tampak berlawanan dengan prinsip pipeline
> terkunci, tetapi justru menegaskannya. Sebelum mode ini ada, seorang peneliti
> yang ingin melihat pengaruh satu hyperparameter tidak punya jalan di dalam
> platform, sehingga ia akan keluar dari platform dan menjalankan notebooknya
> sendiri — dan pada saat itu seluruh jaminan keseragaman, pencatatan, dan
> keterulangan hilang. Dengan menyediakan jalur eksplorasi yang eksplisit,
> terbatas pada hyperparameter algoritma, tercatat, dan berlabel, kebutuhan itu
> tetap berada di dalam kerangka yang sama. Angka yang menjadi dasar perbandingan
> pada penelitian ini seluruhnya berasal dari run resmi, dan pembedaannya dapat
> diperiksa langsung pada kolom run_mode setiap eksperimen.

---

## 5. Bukti empiris yang tersedia (Bagian 15)

| Kasus | Hasil |
|---|---|
| **KTR-R-04** | Run resmi yang dikirimi penyesuaian `n_estimators = 300`: `params_used` tetap sama dengan nilai terkunci, `params_changed = 0`, `run_mode = official` |
| **KTR-R-05** | Run eksplorasi dengan `n_estimators = 300`: `params_used` memuat 300, `params_changed = 1`, `run_mode = exploration` |
| **KTR-R-05 (bukti penerapan)** | Pada AdaBoost, `n_estimators = 1` menghasilkan accuracy **0,9791666666666666** sedangkan `n_estimators = 50` menghasilkan **1,0** — penyesuaian benar-benar sampai ke model, bukan sekadar tercatat |
| **KTR-R-06** | `balancing`, `scaler`, `test_size`, dan `stratify` seluruhnya ditolak dengan galat yang menyebutkan alasan penguncian |

Bukti pada baris ketiga penting: ia diambil pada nilai yang justru **memperburuk**
hasil, karena pada nilai yang sudah jenuh perbedaannya tidak akan terlihat.

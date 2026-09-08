# BAGIAN 2/19 — KONTRADIKSI: KALIMAT DRAF YANG KINI SALAH

Ini bagian **paling mendesak**. Setiap butir di bawah adalah pernyataan yang ada
di draf dan **dapat dibantah penguji dengan membuka aplikasinya atau menjalankan
satu perintah**. Semuanya wajib diperbaiki.

Format: **[K-n] Lokasi** → apa yang tertulis → apa yang benar → cara memperbaiki.

---

## [K-1] Jumlah pengujian otomatis — 2.2.4.6 (hlm. 30), 2.2.5.4 (hlm. 33), Gambar 14

**Tertulis:** "test suite otomatis yang terdiri atas 227 pengujian, dengan 225
lulus dan 2 dilewati".

**Sebenarnya:** **3.073 pengujian dikumpulkan, 3.071 lulus, 2 dilewati**, dalam
103 berkas tes (33.441 baris kode uji). Nilai 227 adalah keadaan sebelum
subsistem kontribusi ada.

**Perbaikan:** ganti seluruh angka; **Gambar 14 (tangkapan layar pytest) harus
diambil ulang** karena gambar lama menampilkan "225 passed, 2 skipped" dan
daftar berkas yang sudah tidak lengkap. Uraian lengkap: Bagian 14.

---

## [K-2] Jumlah halaman antarmuka — 1.2.7, 2.2.3.2 (hlm. 15), 2.2.5.3 (hlm. 32)

**Tertulis:** "Layer UI berbasis Streamlit menyediakan **dua halaman**, yaitu Run
Experiment ... dan Progress & Status".

**Sebenarnya:** **tiga halaman** pada navigasi: Progress & Status,
Run Experiment, dan **Add Pipeline & Dataset** (kunci i18n page.progress,
page.run_experiment, page.contribute), ditambah **layar masuk (login)** sebagai
modul tersendiri (ui/views/login.py). Modul tampilan seluruhnya enam berkas,
bukan dua.

**Perbaikan:** ubah "dua halaman" menjadi "tiga halaman", tambahkan uraian
halaman ketiga (Bagian 11), dan sebutkan layar masuk.

---

## [K-3] Prinsip fixed pipeline — Tabel 1 (hlm. 14) dan paragraf sesudahnya (hlm. 15)

**Tertulis:** "Seluruh hyperparameter dikunci secara permanen di dalam berkas
pipeline, dan pengguna **hanya memilih dataset serta pipeline tanpa antarmuka
untuk mengubah parameter algoritma**. Dengan demikian, eksperimen di sini
bukanlah penyetelan parameter (hyperparameter tuning)".

**Sebenarnya:** sistem kini punya **dua mode eksekusi**:

- **Run resmi** (run_mode = "official", bawaan): perilakunya persis seperti yang
  dijelaskan draf — parameter terkunci, override yang dikirim **dibuang**, dan
  params_changed = 0.
- **Run eksplorasi** (run_mode = "exploration"): pengguna **boleh** mengubah
  sebagian hyperparameter dalam batas aman, hasilnya diberi lencana pembeda, dan
  params_changed mencatat berapa kunci yang berubah.

Lima belas kunci parameter tetap **tidak pernah** dapat diubah pada mode mana pun
(PROTECTED_PARAMS), karena mengubahnya akan merusak keterbandingan.

**Perbaikan:** prinsip fixed pipeline **tidak dihapus** — ia dipertajam menjadi
"terkunci sebagai bawaan; eksplorasi bersifat eksplisit dan berlabel". Teks
lengkapnya ada di Bagian 10. **Jangan** menghapus kalimat tentang perbandingan
terkendali; justru itu yang menjelaskan mengapa mode resmi tetap menjadi bawaan.

---

## [K-4] Lima service pada Orchestrator — Tabel 3 (hlm. 16)

**Tertulis:** Tabel 3 memuat lima berkas: experiment_service.py,
validation_service.py, execution_service.py, result_service.py,
dataset_parser.py.

**Sebenarnya:** direktori orchestrator/ berisi **19 modul** (7.693 baris). Empat
belas di antaranya tidak ada di draf, termasuk auth_service, submission_service,
pipeline_validator, trial_service, trial_dataset_service, dynamic_registry,
pipeline_versions, research_registry, run_mode, dataset_diagnostics,
health_service, user_errors, dan validator.

**Perbaikan:** Tabel 3 diperluas atau dipecah menjadi dua tabel (inti eksekusi vs
subsistem kontribusi). Daftar lengkap beserta tanggung jawab tiap modul ada di
Bagian 13 pasal 2.

---

## [K-5] Kolom tabel experiments — 2.2.3.2 Layer Storage (hlm. 16)

**Tertulis:** "memuat antara lain pengenal eksperimen, jenis dan jalur dataset,
nilai hash dataset, pengenal pipeline, status, penanda waktu, empat metrik utama,
dan jalur artefak."

**Sebenarnya:** tabel experiments kini punya **23 kolom**; enam di antaranya
tidak disebut draf dan justru penting untuk ketertelusuran: owner,
pipeline_version, pipeline_hash, run_mode, params_used, params_changed.

**Perbaikan:** perluas kalimatnya dan jelaskan fungsi keenam kolom itu
(Bagian 12 pasal 2).

---

## [K-6] Jumlah tabel basis data — implisit di seluruh Bab II

**Tertulis:** draf hanya pernah menyebut satu tabel (experiments).

**Sebenarnya:** **enam tabel aplikasi** ditambah satu tabel versi skema:
experiments, users, submissions, pipeline_trials, registered_pipelines,
research_pipelines, dan _schema_version. Skema dibangun lewat **31 migrasi
aditif**.

**Perbaikan:** tambahkan subbab dan tabel skema basis data (Bagian 12).

---

## [K-7] Memori lingkungan pengujian — 3.2.3 (hlm. 41)

**Tertulis:** "lingkungan pengujian berjalan pada VM WSL2 dengan memori sekitar
**23,5 GB** dan batas memori worker **15 GB**".

**Sebenarnya (diukur ulang pada mesin yang sama):** docker info melaporkan
MemTotal **3.788.718.080 byte (± 3,53 GB)**, dan batas memori kontainer
ids_worker adalah **3.670.016.000 byte (± 3,42 GiB)**.

**Catatan penting:** angka 23,5 GB juga **tidak konsisten** dengan subbab 2.1
yang menyebut RAM mesin **8 GB** — sebuah VM WSL2 tidak dapat memiliki memori
lebih besar daripada RAM fisik host. Kemungkinan besar angka lama salah catat.

**Perbaikan:** ganti dengan angka terukur, lalu sesuaikan kalimat sesudahnya.
Dengan plafon 3,42 GiB, menjalankan **dua eksperimen berat secara paralel bukan
"berpotensi mendekati plafon", melainkan tidak muat**. Konsekuensinya:
concurrency worker sebaiknya dilaporkan sebagai **1**, bukan 2 (lihat K-9).

---

## [K-8] Spesifikasi perangkat dan periode — 2.1 (hlm. 12)

**Tertulis:** "prosesor AMD Ryzen 5, RAM 8 GB, penyimpanan 512 GB, dan sistem
operasi Windows 11", periode "April sampai dengan Juli 2026".

**Sebenarnya:** RAM 8 GB konsisten dengan plafon Docker 3,53 GB, jadi baris
spesifikasi kemungkinan benar. Tetapi **periodenya perlu diperpanjang**:
pengembangan subsistem kontribusi dan pengujian lapangannya berlangsung sesudah
Juli — commit terakhir tertanggal **7 September 2026**.

**Perbaikan:** sesuaikan rentang periode penelitian.
**[PERLU_DIPASTIKAN PENULIS: tanggal mulai dan selesai yang benar.]**

---

## [K-9] Concurrency worker — 2.2.3.6 (hlm. 20)

**Tertulis:** "worker dikonfigurasi memakai **concurrency dua** sehingga hingga
dua eksperimen dapat berjalan paralel".

**Sebenarnya:** dengan plafon memori 3,42 GiB, menjalankan dua pipeline berat
serentak tidak aman; keputusan operasional yang dipakai adalah **tetap sekuensial
(concurrency 1)** demi keamanan memori sekaligus keterulangan.

**Perbaikan:** nyatakan nilai yang benar-benar dipakai saat eksekusi yang
dilaporkan, dan jelaskan alasannya (batas memori, bukan batas rancangan).
**[PERLU_DIPASTIKAN PENULIS: nilai --concurrency pada docker-compose.yml saat
eksekusi Bab III dilakukan.]**

---

## [K-10] "Basis kode disimpan lokal dan tidak dipublikasikan" — 2.2.5.1 (hlm. 31)

**Tertulis:** "dengan basis kode disimpan lokal dan tidak dipublikasikan selama
pengembangan."

**Sebenarnya:** Lampiran 1 mencantumkan repositori publik
https://github.com/andiaiyy/TA.git

**Perbaikan:** ubah menjadi "tidak dipublikasikan **selama** pengembangan dan
baru dipublikasikan setelah penelitian selesai", atau hapus klausanya.

---

## [K-11] Versi pustaka — 3.2.2 (hlm. 40)

**Tertulis:** "Python 3.11.15, scikit-learn 1.9.0, pandas 3.0.3, dan numpy
2.4.6".

**Sebenarnya (diukur di kontainer ids_worker saat ini):** Python **3.11.16**,
scikit-learn 1.9.0, pandas **3.0.5**, numpy 2.4.6. Di host (tempat test suite
dijalankan): Python **3.14.4**, scikit-learn 1.9.0, pandas 3.0.5, numpy 2.5.2.

**Perbaikan:** pilih satu menurut kapan Bab III dieksekusi:

- bila angka Bab III berasal dari image lama, **biarkan** dan tambahkan catatan
  bahwa image telah dibangun ulang sesudahnya dengan versi tersebut di atas;
- bila dilaporkan sebagai keadaan sekarang, perbarui angkanya.

Yang **tidak boleh**: mencampur keduanya tanpa penjelasan.

---

## [K-12] Kamus metadata lima key — 2.2.4.1 (hlm. 23)

**Tertulis:** "Kamus metadata memuat **lima key** yang konsisten di seluruh
pipeline, yaitu rujukan paper asli, nama algoritma, daftar langkah preprocessing,
strategi feature selection, dan hyperparameter yang dikunci."

**Sebenarnya:** validator menegakkan **enam kunci** (EXPECTED_INFO_KEYS): paper,
algorithm, preprocessing_steps, feature_selection, fixed_params, dan
**train_test_split**.

**Perbaikan:** ubah "lima key" menjadi "enam key" dan tambahkan train_test_split.
Perlu ditegaskan pula bahwa keenam kunci itu kini **diperiksa otomatis** pada
kode kontributor, bukan sekadar konvensi penulisan (Bagian 5).

---

## [K-13] "Sepuluh pipeline" sebagai angka mutlak — Abstrak, 2.2.3.2, 4.1

**Tertulis:** di banyak tempat, "sepuluh pipeline" ditulis seolah itu isi tetap
platform.

**Sebenarnya:** sepuluh adalah jumlah **pipeline bawaan** (PIPELINE_REGISTRY,
tetap 10). Registry yang dibaca sistem sekarang adalah **gabungan** bawaan
ditambah pipeline kontribusi yang telah disetujui, sehingga jumlah totalnya
bertambah seiring kontribusi.

**Perbaikan:** setiap kali menyebut sepuluh, tambahkan kata **"bawaan"** —
"sepuluh pipeline bawaan". Ini sekaligus membuat klaim "penambahan pipeline baru
bersifat aditif" menjadi hal yang terbukti, bukan sekadar rancangan.

---

## [K-14] Klaim "satu pengguna" — 2.2.3.4 (hlm. 18), 2.2.3.7 (hlm. 22)

**Tertulis:** "menyasar lingkungan penelitian **satu pengguna**"; "target
pengguna tunggal di lingkungan akademik".

**Sebenarnya:** sistem punya tabel users, tiga peran, kata sandi ber-hash
(PBKDF2-HMAC-SHA256, 260.000 iterasi, salt 16 byte), serta alur pendaftaran dan
persetujuan akun. Pada basis data yang dipakai sekarang terdapat **4 akun**.

**Perbaikan:** ubah menjadi "multi-pengguna dalam satu instans on-premise, tanpa
multi-tenancy". SQLite tetap dapat dijustifikasi — alasannya **skala data satu
laboratorium**, bukan "penggunanya satu orang".

---

## [K-15] Penomoran ulang subbab Pembahasan

Bila subbab hasil baru disisipkan sebagai 3.2.5 (Bagian 15), maka subbab
**3.2.5 Pembahasan** yang sekarang bergeser menjadi **3.2.6**. Perbarui juga
Daftar Isi.

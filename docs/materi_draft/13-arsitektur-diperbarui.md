# BAGIAN 13/19 — ARSITEKTUR & ATURAN KETERGANTUNGAN YANG DIPERBARUI

Bahan untuk **2.2.3 (paragraf pembuka)**, **Tabel 3**, **Tabel 4**, **Tabel 5**,
dan **Gambar 7**. Memperbaiki **K-4** pada Bagian 2.

---

## 1. Arsitektur lima lapis: tetap berlaku

Kabar baiknya, **rancangan intinya tidak berubah**. Lima lapis fungsional (UI,
Orchestrator, Workers, Pipelines, Storage) beserta shared kernel (Contracts &
Config) tetap seperti Gambar 7, dan arah ketergantungannya tetap satu arah.

Yang bertambah adalah **isi** lapisan Orchestrator dan UI. **Gambar 7 tidak perlu
digambar ulang seluruhnya** — cukup ditambahkan kotak baru pada dua lapisan itu
(lihat Bagian 17).

Kalimat yang layak ditambahkan pada 2.2.3:

> Bertambahnya subsistem kontribusi menguji rancangan berlapis ini secara nyata:
> seluruh kemampuan baru — unggahan, validasi statis, uji coba, persetujuan,
> registry dinamis, versioning, dan otorisasi — dapat ditampung tanpa mengubah
> arah ketergantungan antarlapisan maupun kontrak data antara orchestrator dan
> pipeline. Lapisan Pipelines, yang memuat seluruh logika machine learning, sama
> sekali tidak tersentuh oleh penambahan ini.

Kalimat terakhir itu **kuat dan benar**: `pipelines/` tidak berubah, dan
reproduktibilitas hasil Bab III yang tetap identik membuktikannya.

---

## 2. Tabel 3 diperluas — 19 modul Orchestrator

Draf memuat lima. Berikut keseluruhannya, dikelompokkan supaya tabelnya terbaca.

### 2.1 Inti eksekusi eksperimen (sudah ada di draf)

| Modul | Tanggung jawab |
|---|---|
| `experiment_service.py` | membuat dan menjalankan eksperimen serta mengelola siklus hidupnya |
| `validation_service.py` | memvalidasi dataset dan skema sebelum eksekusi |
| `execution_service.py` | men-dispatch eksperimen ke worker (sinkron atau asinkron) |
| `result_service.py` | mengambil hasil dan metrik eksperimen untuk ditampilkan |
| `dataset_parser.py` | mem-parsing berkas CSV atau NDJSON menjadi DataFrame |
| `validator.py` | memeriksa skema dataset terhadap kontrak |

### 2.2 Subsistem kontribusi (baru)

| Modul | Tanggung jawab |
|---|---|
| `submission_service.py` | menerima, menyimpan, menyetujui, dan menolak pengajuan; mengelola area staging |
| `pipeline_validator.py` | analisis statis berbasis AST atas kode kontributor |
| `trial_service.py` | menjalankan uji coba terkendali dan menjaga gerbang persetujuan |
| `trial_dataset_service.py` | menyimpan dan memverifikasi dataset lampiran pengajuan |
| `dynamic_registry.py` | registry gabungan, pendaftaran, verifikasi hash, aktif/nonaktif |
| `pipeline_versions.py` | penyuntingan yang selalu menambah versi, riwayat, dan penghapusan terjaga |
| `research_registry.py` | identitas research pipeline kontribusi dan pembacaan gabungan |

### 2.3 Lintas fungsi (baru)

| Modul | Tanggung jawab |
|---|---|
| `auth_service.py` | akun, peran, kata sandi, dan penegakan izin |
| `run_mode.py` | mode resmi/eksplorasi, parameter terlindungi, validasi penyesuaian |
| `dataset_diagnostics.py` | diagnosa kecocokan berkas terhadap seluruh research pipeline |
| `health_service.py` | pemeriksaan kesehatan Redis dan worker |
| `user_errors.py` | galat yang dapat diterjemahkan dan ditampilkan apa adanya ke pengguna |

**Saran penyajian:** pecah Tabel 3 menjadi **Tabel 3a** (inti eksekusi) dan
**Tabel 3b** (subsistem kontribusi dan lintas fungsi), agar tidak menjadi satu
tabel sepanjang satu halaman.

---

## 3. Tabel 4 — aturan ketergantungan: satu pengecualian bertambah

Aturan pokoknya **tidak berubah**. Yang perlu diperbarui adalah daftar
pengecualian terdokumentasi. Draf menyebut tiga:

1. `ui -> database` untuk inisialisasi skema saat startup;
2. `ui -> workers` untuk pembacaan status atau pembatalan task Celery;
3. `workers -> orchestrator` untuk pemakaian ulang logika dispatch dan parsing.

**Pengecualian keempat yang harus ditambahkan:**

4. `ui -> database` untuk **pembacaan agregat** pada halaman pengelolaan, yaitu
   menghitung jumlah eksperimen per pipeline dengan satu kueri gabungan.
   Melewatkannya ke orchestrator akan menambah satu lapisan penerus yang tidak
   melakukan apa pun selain meneruskan, sementara operasinya murni baca dan tidak
   mengubah keadaan.

**Kalimat yang jujur untuk menutup subbab 2.2.3.3:**

> Keempat pengecualian bersifat minor, seluruhnya terdokumentasi, dan tidak
> mengubah struktur lapisan: tidak satu pun di antaranya membuat lapisan bawah
> bergantung pada lapisan atas. Penegakan aturan masih dilakukan lewat peninjauan
> kode dan pengujian yang membaca teks sumber, bukan lewat perkakas analisis
> ketergantungan otomatis seperti import-linter, yang tetap ditempatkan sebagai
> pekerjaan lanjutan.

Perlu ditambahkan pula satu fakta yang memperkuat: **beberapa aturan lapisan kini
diuji otomatis** oleh test suite, yang membaca teks sumber modul dan memastikan
tidak ada impor terlarang serta tidak ada kueri basis data pada fungsi yang
seharusnya murni.

---

## 4. Tabel 5 — stack teknologi: tiga baris baru

Tambahkan:

| Komponen | Teknologi | Justifikasi |
|---|---|---|
| Tabel interaktif | streamlit-aggrid | tabel yang barisnya dapat dipilih, diurutkan, dan digulir; dipakai untuk riwayat eksperimen, antrean pengajuan, dan riwayat versi |
| Navigasi | streamlit-option-menu | menu samping yang konsisten lintas halaman |
| Autentikasi | `hashlib` (pustaka standar) | PBKDF2-HMAC-SHA256 tanpa menambah dependensi baru; sejalan dengan kriteria dependensi minimal |

Perbarui juga baris **Bahasa pemrograman**: runtime kontainer **Python 3.11**
(3.11.16 saat pengukuran terakhir), sementara perkakas pengembangan dan test
suite pada host berjalan pada Python 3.14 — perbedaan yang disengaja, karena
jaminan reproduksibilitas bertumpu pada lingkungan kontainer.

---

## 5. Angka ukuran kode (untuk 2.2.5.3)

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

Dua hal yang menarik untuk dikomentari satu kalimat:

- **`contracts/` tetap yang terkecil (117 baris)** meski sistem tumbuh besar. Ini
  bukti bahwa kontrak data benar-benar berperan sebagai *change firewall*:
  seluruh penambahan terjadi di sekelilingnya, bukan di dalamnya.
- **`tests/` (33.441 baris) hampir seukuran seluruh `ui/`**, dan lebih besar
  daripada orchestrator, database, workers, config, contracts, dan utils
  digabungkan. Rasio ini layak disebut sebagai indikator disiplin verifikasi.

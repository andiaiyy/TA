# BAGIAN 5/19 — GERBANG 1: VALIDASI STATIS KODE KONTRIBUTOR

Bahan untuk: **subbab baru 1.2.8** (landasan teori), **subbab baru 2.2.4.7**
(metode), dan tabel baru (Bagian 17).

---

## 1. Landasan teori untuk 1.2.8 (subbab baru)

**Judul yang disarankan:** *1.2.8 Analisis Statis dan Isolasi Eksekusi Kode
Pihak Ketiga*

Isi yang perlu ada (tulis dengan gayamu, jangan menyalin mentah):

- **Analisis statis** adalah pemeriksaan program tanpa menjalankannya, dengan
  membaca struktur sintaksisnya. Pada Python, struktur itu tersedia sebagai
  *Abstract Syntax Tree* (AST) melalui modul `ast` pada pustaka standar.
- Perbedaan mendasar dengan **analisis dinamis**: analisis dinamis memerlukan
  kode dijalankan, sehingga bila kode itu berbahaya, kerusakan sudah terjadi
  sebelum pemeriksaan selesai. Pada platform yang menerima kode pihak ketiga,
  urutannya harus terbalik — periksa dulu, jalankan kemudian.
- Bahaya khas yang dicegah pada konteks ini: akses sistem berkas dan proses
  (`os`, `subprocess`, `shutil`), akses jaringan (`socket`, `requests`,
  `urllib`), eksekusi kode dinamis (`eval`, `exec`, `compile`, `__import__`),
  deserialisasi objek arbitrer (`pickle`, `dill`, `marshal`), dan teknik keluar
  dari pembatasan lewat atribut *dunder* (`__subclasses__`, `__globals__`,
  `__builtins__`, `__mro__`).
- **Batas kemampuan yang wajib disebut secara jujur:** analisis statis berbasis
  daftar-larangan tidak setara dengan *sandbox* pada tingkat sistem operasi. Ia
  menutup jalur yang terbaca dari teks kode, tetapi tidak dapat menjamin bahwa
  tidak ada jalur lain sama sekali. Untuk lingkungan penelitian on-premise satu
  laboratorium, dengan kontributor yang identitasnya diketahui dan persetujuan
  manusia sebagai gerbang terakhir, tingkat jaminan ini memadai; untuk layanan
  publik, ia tidak memadai.
- Rujukan yang relevan dan sudah ada di daftar pustaka: Arp et al. (2022) untuk
  praktik yang keliru pada machine learning di ranah keamanan. Bila ingin
  menambah satu rujukan tentang analisis statis, lihat Bagian 18 pasal 4.

---

## 2. Apa yang benar-benar diperiksa (untuk 2.2.4.7)

Pemeriksaan dijalankan oleh `orchestrator/pipeline_validator.py` lewat
`validate_pipeline_source(source_code, filename)`, yang mengembalikan sebuah
laporan berisi daftar pemeriksaan; setiap pemeriksaan berstatus **pass**,
**warn**, atau **fail**, dan membawa **nomor baris** tempat pelanggaran
ditemukan.

Hasilnya dikelompokkan menjadi **dua kelompok** pada antarmuka: **Struktur** dan
**Keamanan**.

### 2.1 Kelompok Struktur — enam pemeriksaan, selalu dijalankan

| # | Nama pemeriksaan | Yang dipastikan |
|---|---|---|
| 1 | sintaks Python | berkas dapat diurai `ast.parse` |
| 2 | kelas pipeline | ada kelas yang mewarisi `BasePipeline` |
| 3 | method `run` | metode `run` ada pada kelas itu |
| 4 | method `get_info` | metode `get_info` ada pada kelas itu |
| 5 | signature run() | parameter pertama bernama `pipeline_input`, parameter kedua bernama `progress` |
| 6 | get_info() mengembalikan dict | mengembalikan dict literal yang memuat enam kunci wajib |

Enam kunci wajib pada `get_info()`: **paper, algorithm, preprocessing_steps,
feature_selection, fixed_params, train_test_split**.

Catatan penting untuk penulisan: pemeriksaan nomor 6 berstatus **warn**, bukan
**fail**, bila kunci tidak lengkap — kontributor tetap dapat melanjutkan tetapi
diberi tahu. Yang membuat paket **ditolak** hanyalah status **fail**.

### 2.2 Kelompok Keamanan — enam jenis temuan, muncul hanya bila dilanggar

| # | Nama temuan | Pemicu | Status |
|---|---|---|---|
| 1 | import terlarang | mengimpor salah satu dari 25 modul terlarang | fail |
| 2 | import di luar daftar | mengimpor modul di luar 27 modul yang diizinkan | fail |
| 3 | pemanggilan terlarang | memanggil salah satu dari 9 fungsi terlarang | fail |
| 4 | penulisan berkas | `open()` dengan mode tulis/timpa (`w`, `a`, `x`, `+`) | fail |
| 5 | atribut dunder terlarang | mengakses salah satu dari 9 atribut dunder | fail |
| 6 | refleksi atribut | `getattr`/`setattr`/`delattr` pada objek modul | warn |

**Sembilan atribut dunder yang diblokir beserta alasannya** (layak masuk tabel):
`__subclasses__` (teknik sandbox-escape), `__globals__` (akses namespace global
fungsi lain), `__builtins__` (akses langsung ke builtins), `__bases__` dan
`__mro__` (penelusuran hierarki kelas untuk sandbox-escape), `__code__` (akses
objek kode), `__loader__` (akses pemuat modul), `__reduce__` (hook serialisasi
yang dapat mengeksekusi kode), `__class__` (penelusuran tipe untuk
sandbox-escape).

Daftar lengkap 27 modul diizinkan, 25 modul dilarang, dan 9 pemanggilan dilarang
ada pada **Bagian 3 pasal 7** — salin dari sana, jangan tulis dari ingatan.

**Perhatikan asimetri yang disengaja:** membaca berkas tetap diperbolehkan
(pipeline harus dapat membaca dataset); yang dilarang hanya **menulis**.

### 2.3 Aturan tingkat paket

Sebuah pengajuan boleh memuat beberapa berkas sekaligus (satu paket). Aturan
yang berlaku:

- **Setiap** berkas dalam paket diperiksa, bukan hanya berkas titik masuknya.
  Satu berkas pendukung yang melanggar membuat **seluruh paket ditolak**.
- Satu paket **boleh** memuat lebih dari satu titik masuk (lebih dari satu
  turunan `BasePipeline`), karena satu research pipeline wajar membawa beberapa
  algoritma — persis seperti keluarga HIKARI2021 yang punya enam.
- Paket **tanpa** satu pun titik masuk ditolak.
- Nama berkas disanitasi: komponen direktori (`../`), karakter di luar pola
  huruf/angka/titik/garis bawah/hubung, dan ekstensi di luar `.py`
  **ditolak — bukan dipotong atau dinormalisasi diam-diam**.
- Batas ukuran berkas: 1.000.000 byte (± 0,95 MB) per berkas.

---

## 3. Klaim yang boleh ditulis, dan buktinya

| Klaim | Bukti empiris |
|---|---|
| Kode kontributor tidak pernah dieksekusi saat validasi | Kasus **KTR-V-05** (Bagian 15): berkas uji memanggil `open(..., 'w')` pada tingkat modul; penanda **tidak** terbentuk sesudah validasi |
| Pelanggaran ditunjuk dengan tepat, bukan hanya dinyatakan gagal | Kasus **KTR-V-03**: enam pelanggaran ditanam pada baris 7, 8, 9, 19, 20, 21; keenamnya terdeteksi dengan **nomor baris yang tepat** |
| Struktur dan keamanan dinilai terpisah | Kasus **KTR-V-02**: fikstur negatif lulus seluruh cek Struktur (6/6 pass) dan gagal seluruh cek Keamanan (6 temuan fail) |
| Seluruh berkas paket diperiksa | Kasus **KTR-V-04**: `import os` disisipkan pada berkas **bukan** titik masuk; paket ditolak dan berkas yang bermasalah ditunjuk dengan benar |
| Tidak ada false positive pada kode yang sah | Kasus **KTR-V-06**: paket tiga berkas bersih lulus tanpa satu pun peringatan |

---

## 4. Kalimat yang layak menutup subbab ini

> Dengan demikian, standar struktural yang pada Bab II sebelumnya ditegakkan
> melalui kelas abstrak dan kontrak data — yaitu pada kode yang ditulis sendiri —
> kini ditegakkan pula pada kode yang datang dari luar, sebelum kode itu memperoleh
> kesempatan dijalankan sekali pun. Pemeriksaan ini bersifat statis dan berbasis
> daftar; ia menutup jalur yang terbaca dari teks program, tetapi tidak
> menggantikan isolasi pada tingkat sistem operasi, dan karena itu tetap
> ditempatkan sebagai gerbang pertama dari tiga gerbang berurutan, bukan sebagai
> satu-satunya pengaman.

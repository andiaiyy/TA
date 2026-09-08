# BAGIAN 11/19 — ANTARMUKA: TIGA HALAMAN, DWIBAHASA, SISTEM DESAIN

Bahan untuk **2.2.3.2 Layer UI**, **2.2.5.3 Struktur Direktori**, dan gambar
baru. Memperbaiki **K-2** pada Bagian 2.

---

## 1. Tiga halaman (bukan dua)

| Halaman | Pengenal i18n | Isi |
|---|---|---|
| **Progres & Status** | `page.progress` | Halaman pendaratan. Memantau eksperimen yang sedang berjalan sekaligus riwayat eksekusi lengkap, dengan dialog detail per-eksperimen, unduhan laporan PDF dan CSV, serta pemeriksaan kesehatan infrastruktur Redis dan worker |
| **Jalankan Eksperimen** | `page.run_experiment` | Katalog research pipeline (pencarian + penyaring bertingkat), pemilihan dataset, diagnosa kecocokan, pemilihan mode run, dan eksekusi |
| **Tambah Pipeline & Dataset** | `page.contribute` | Unggah pipeline dan dataset, panduan kontrak, peninjauan pengajuan, pengelolaan research pipeline, penyunting versi, dan pengelolaan pengguna |

Ditambah **layar masuk** (`ui/views/login.py`) yang muncul ketika pengguna
memilih masuk. Aplikasi **terbuka langsung dalam mode pengunjung** — tanpa login
— sehingga peninjau dapat melihat dan menjalankan eksperimen tanpa mendaftar.

Seluruh modul tampilan: `run_experiment.py`, `view_results.py`, `contribute.py`,
`manage_pipelines.py`, `login.py`, `_artifact_browser.py`, ditambah `app.py`
sebagai pengarah navigasi. Total **39 berkas** di `ui/` (22.555 baris), dengan
**25 komponen bersama** di `ui/components/`.

---

## 2. Halaman ketiga secara rinci (bahan untuk subbab baru)

Halaman **Tambah Pipeline & Dataset** memuat empat jalur yang dipilih dari satu
layar pilihan:

1. **Unggah pipeline** — memilih berkas, melihat hasil pemeriksaan statis
   per-berkas dalam dua kelompok (Struktur dan Keamanan) beserta nomor barisnya,
   mengisi metadata penelitian, dan mengirim pengajuan.
2. **Unggah dataset** — memilih berkas, melihat profil dataset yang dihitung dari
   cuplikan (format, jumlah baris, kolom, tipe data, kolom label, distribusi
   kelas), lalu menyimpan.
3. **Peninjauan pengajuan** — antrean pengajuan dengan pencarian, pengurutan, dan
   penggalan halaman; kartu peninjauan yang menampilkan hasil validasi dan hasil
   uji coba; tombol Setujui/Tolak; daftar pengelolaan research pipeline; riwayat
   versi beserta pembandingnya; dan penyunting berkas.
4. **Kelola pengguna** — hanya untuk Research Admin.

**Kalimat yang layak untuk 2.2.3.2:**

> Halaman ketiga menampung seluruh alur kontribusi, dari unggahan hingga
> persetujuan dan pengelolaan versi. Penempatannya sebagai satu halaman dengan
> beberapa jalur, bukan sebagai beberapa halaman navigasi, menjaga agar menu
> utama tetap memuat tiga entri; alur kontribusi hanya relevan bagi dua dari tiga
> peran, sehingga memberinya beberapa entri menu akan membebani pengguna yang
> tidak memerlukannya.

---

## 3. Dwibahasa (i18n)

| Ruas | Nilai |
|---|---|
| Kunci teks | 1.309 |
| Bahasa | Indonesia dan Inggris, **keduanya terisi 100%** |
| Lokasi katalog | `ui/i18n/catalog.py` |
| Cara pemakaian | fungsi `t("kunci")` dipanggil di seluruh tampilan |

Sifat yang layak ditulis:

- **Tidak ada teks Inggris yang tertanam langsung di kode tampilan.** Keadaan
  seperti "Active" yang tidak ikut berganti bahasa dicegah lewat kunci
  (`rs.status_active`) dan diuji otomatis.
- **Berpindah bahasa tidak memindahkan halaman.** Pengenal halaman disimpan
  sebagai nilai tetap yang tidak diterjemahkan; hanya labelnya yang berbahasa.
  Tanpa pemisahan itu, mengganti bahasa akan memutus rute navigasi.
- **Setiap kunci wajib punya kedua bahasa.** Ini diperiksa oleh pengujian
  otomatis, sehingga kunci yang setengah jadi tidak dapat masuk.

**Justifikasi akademik yang dapat dipakai:** dwibahasa relevan karena dataset,
istilah, dan rujukan penelitian IDS seluruhnya berbahasa Inggris, sementara
pengguna sasaran platform berbahasa Indonesia. Antarmuka yang mencampur keduanya
secara sembarangan justru menyulitkan keduanya.

---

## 4. Sistem desain (bahan opsional, untuk 2.2.5.3)

Antarmuka memakai skala visual yang dibatasi secara sengaja:

| Aturan | Nilai |
|---|---|
| Tingkat ukuran teks | **empat**: judul bagian 1,05rem; teks isi 0,95rem; keterangan 0,84rem; angka ringkasan 1,6rem (khusus angka, bukan kalimat) |
| Bobot huruf | **dua**: 400 dan 600 |
| Jarak vertikal | **dua** nilai: antar elemen 1rem, antar bagian 2rem |
| Tema | mengikuti tema terang/gelap Streamlit |

**Alasannya layak ditulis satu kalimat:** membatasi skala membuat hierarki
terbaca dari ukuran dan jarak, bukan dari warna, sehingga halaman tetap terbaca
pada tema gelap maupun terang dan pada pembaca layar.

Sertakan juga catatan bahwa keterbatasan Streamlit memang membuat sebagian
tampilan diatur lewat CSS terpusat, bukan lewat komponen kustom, agar dependensi
tetap minimal.

---

## 5. Diagnosa kecocokan dataset (fitur baru pada halaman eksekusi)

Sebelum menjalankan, sistem mendiagnosa kecocokan berkas yang dipilih terhadap
**seluruh** research pipeline sekaligus, lalu mengunci tombol jalankan bila
berkas itu tidak cocok dengan research pipeline yang sedang dipilih. Diagnosanya
dihitung dari cuplikan berkas dan disimpan sementara, sehingga berpindah pilihan
tidak berarti membaca ulang berkas dari disk.

Ini menutup satu kelas kegagalan yang sebelumnya baru ketahuan setelah
eksperimen berjalan dan gagal di worker.

---

## 6. Gambar yang perlu diperbarui atau ditambahkan

Lihat Bagian 17 untuk spesifikasi lengkap. Ringkasnya:

- **Gambar 12 dan 13** (Run Experiment, Progress & Status): sebaiknya diambil
  ulang karena tampilannya sudah berubah (mode run, katalog research, pencarian).
- **Gambar 14** (pytest): **wajib** diambil ulang — angkanya sudah salah.
- **Gambar baru**: alur kontribusi tiga gerbang; tangkapan layar halaman Tambah
  Pipeline & Dataset; tangkapan layar laporan validasi statis dengan nomor baris.

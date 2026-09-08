# BAGIAN 0/19 — CARA PAKAI MATERI INI (BACA DULU)

Kamu akan menerima **20 bagian** (00–19). Ini bagian pertama: aturan main.

## Apa ini

Materi pemutakhiran draf skripsi **"Perancangan Platform Analisis Data Jaringan
Berbasis Website On-Premise untuk Eksekusi Pipeline Machine Learning
End-to-End"** (Andi Siti Aisyah Amin, D121221043, Teknik Informatika UNHAS).

Draf yang kamu pegang ditulis pada keadaan sistem **sebelum seminar hasil**.
Sesudah itu sistem bertambah **satu subsistem besar yang sama sekali belum ada
di draf**: subsistem kontribusi (unggah pipeline & dataset oleh peneliti lain,
validasi statis, uji coba, persetujuan, registry dinamis, versioning),
ditambah autentikasi peran, dua mode eksekusi, dwibahasa, dan pengujian
lapangan 38 kasus.

Tugasmu: **menulis ulang/menambah bagian draf** sesuai peta pada Bagian 1,
memakai fakta pada Bagian 3–16.

## Aturan keras (melanggar = hasilnya tidak dapat dipakai)

1. **JANGAN MENGARANG ANGKA.** Setiap angka yang kamu tulis harus ada di
   Bagian 3 (fakta terverifikasi) atau di bagian materi lain. Kalau kamu
   merasa butuh angka yang tidak diberikan, tulis persis:
   `[PERLU_DIUKUR: <apa yang perlu diukur>]` dan lanjutkan. Jangan menebak.
2. **JANGAN MENGUBAH HASIL BAB III YANG SUDAH ADA.** Tabel 12–20 (dataset,
   distribusi kelas, hasil fungsional, reproducibility, stabilitas, evaluasi
   kinerja sepuluh pipeline) berasal dari eksekusi nyata dan **tetap berlaku**.
   Yang berubah hanya yang disebut eksplisit di Bagian 2.
3. **PERBAIKI YANG SUDAH TIDAK BENAR.** Bagian 2 memuat daftar kalimat draf
   yang kini salah. Semuanya wajib diperbaiki, bukan dibiarkan.
4. **JANGAN MELEBIH-LEBIHKAN.** Sistem ini punya keterbatasan nyata
   (Bagian 16). Tulis apa adanya; penguji menghargai kejujuran metodologis dan
   draf ini memang sudah bergaya begitu.
5. **IKUTI GAYA DRAF.** Bahasa Indonesia formal-akademik, istilah asing
   dimiringkan pada kemunculan pertama (*pipeline*, *reproducibility*,
   *data leakage*), kalimat penjelas sebelum setiap tabel/gambar, rujukan
   silang eksplisit ("sebagaimana ditunjukkan pada Tabel X").
6. **NOMOR TABEL DAN GAMBAR BERURUTAN.** Draf sekarang berakhir di Tabel 20
   dan Gambar 14. Tabel/gambar baru melanjutkan dari sana. Setiap penambahan
   di tengah menggeser penomoran sesudahnya — Bagian 17 memberi rencana
   penomoran yang sudah dihitung; pakai itu.
7. **SATU SUMBER PENOMORAN SUBBAB.** Bila kamu menambah subbab baru, cantumkan
   nomor lengkapnya (mis. 2.2.7) dan sebutkan di mana ia disisipkan.
8. **JANGAN MENYENTUH** halaman judul, pernyataan keaslian, ucapan terima
   kasih, dan daftar pustaka lama (kecuali penambahan pada Bagian 18).

## Format keluaran yang diharapkan

Untuk setiap bagian draf yang diubah, tulis dalam bentuk:

```
### [GANTI] Subbab 2.2.3.1, paragraf ke-2
<teks lama, dikutip satu kalimat pembuka saja sebagai penanda>
--- diganti dengan ---
<teks baru lengkap>
```

atau

```
### [SISIP BARU] Subbab 2.2.7 — Judul Subbab
<teks lengkap, siap tempel>
```

Jangan menulis ringkasan "apa yang akan saya lakukan" — langsung tulis
teksnya, karena teks itulah yang akan ditempel ke dokumen.

## Urutan yang disarankan

Kerjakan sesuai urutan bagian materi (Bab I → Bab II → Bab III → Bab IV),
bukan sesuai urutan bagian materi yang datang. Bagian 1 memberi peta lengkapnya.

## Daftar 20 bagian

| # | Isi |
|---|---|
| 00 | Cara pakai (ini) |
| 01 | Ringkasan perubahan + peta dampak ke tiap subbab draf |
| 02 | **Kontradiksi**: kalimat draf yang kini salah dan wajib diperbaiki |
| 03 | Fakta terverifikasi (satu-satunya sumber angka) |
| 04 | Subsistem kontribusi: gambaran umum & alur end-to-end |
| 05 | Gerbang 1 — validasi statis kode kontributor |
| 06 | Gerbang 2 — uji coba (trial run) dan gerbang persetujuan |
| 07 | Registry dinamis, versioning, dan isolasi |
| 08 | Identitas research pipeline & katalog gabungan |
| 09 | Autentikasi dan otorisasi peran |
| 10 | Mode eksekusi resmi vs eksplorasi (revisi prinsip *fixed pipeline*) |
| 11 | Antarmuka: tiga halaman, dwibahasa, sistem desain |
| 12 | Basis data: skema dan 31 migrasi |
| 13 | Arsitektur & aturan ketergantungan yang diperbarui |
| 14 | Test suite: 227 → 3.073 pengujian |
| 15 | Bab III baru: hasil pengujian lapangan subsistem kontribusi (38 kasus) |
| 16 | Temuan, anomali, dan keterbatasan baru |
| 17 | Spesifikasi tabel & gambar baru + rencana penomoran |
| 18 | Singkatan, pustaka, abstrak, dan judul |
| 19 | Checklist verifikasi akhir |

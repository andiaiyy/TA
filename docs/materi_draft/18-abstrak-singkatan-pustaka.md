# BAGIAN 18/19 — ABSTRAK, JUDUL, RUMUSAN MASALAH, SINGKATAN, PUSTAKA

---

## 1. Judul: perlu diubah atau tidak?

Judul sekarang: *"Perancangan Platform Analisis Data Jaringan Berbasis Website
On-Premise untuk Eksekusi Pipeline Machine Learning End-to-End"*.

**Rekomendasi: JANGAN diubah.** Alasannya:

- judul sudah tercetak pada lembar pengesahan dan pernyataan keaslian;
- kata "platform" dan "end-to-end" sudah cukup luas untuk mencakup subsistem
  kontribusi;
- mengubah judul menjelang sidang menimbulkan urusan administratif yang tidak
  sepadan.

Yang perlu dilakukan cukup **memperluas cakupan pada abstrak, rumusan masalah,
dan tujuan** sehingga isinya menjawab judul yang sama secara lebih penuh.

**[Bila pembimbing memang meminta perubahan judul, opsi yang paling dekat:
menambahkan frasa "…dengan Dukungan Kontribusi Pipeline Terverifikasi" — tetapi
ini keputusan pembimbing, bukan keputusan penulis sendiri.]**

---

## 2. Abstrak: bahan revisi

Abstrak sekarang berbunyi pada bagian Metode dan Hasil sebagai berikut (ringkas):
lima layer + shared kernel, standarisasi tiga dimensi, sepuluh pipeline, tiga
kategori pengujian; sepuluh pipeline berhasil, variansi nol, tiga kasus leakage,
sistem stabil.

**Yang perlu ditambahkan (sisipkan, jangan menulis ulang seluruhnya):**

Pada **Metode**, sesudah kalimat tentang standarisasi tiga dimensi:

> Platform kemudian diperluas dengan subsistem kontribusi yang memungkinkan
> research pipeline dari luar diunggah, diperiksa secara statis tanpa dieksekusi,
> diuji coba di bawah batas sumber daya, dan didaftarkan setelah disetujui, dengan
> otorisasi tiga peran serta pencatatan versi dan sidik jari berkas.

Pada **Hasil**, sesudah kalimat tentang tiga kasus leakage:

> Pengujian lapangan atas subsistem kontribusi mencakup 38 kasus dalam tujuh
> kategori dengan 37 kasus memenuhi kriteria; kode kontributor terbukti tidak
> pernah dieksekusi pada tahap pemeriksaan, seluruh kategori pelanggaran keamanan
> terdeteksi beserta nomor barisnya, dan sepuluh pengenal pipeline bawaan tetap
> utuh setelah pendaftaran kontribusi.

Pada **Kesimpulan**, ganti "dengan kontribusi utama pada infrastruktur
reproducibility dan standarisasi eksperimen" menjadi:

> dengan kontribusi utama pada infrastruktur reproducibility dan pada standarisasi
> yang ditegakkan, yaitu standar yang berlaku pula bagi pipeline yang berasal dari
> luar platform.

**Perhatikan batas panjang abstrak** yang berlaku di prodi. Bila terlalu panjang,
korbankan rincian metode, bukan hasil.

**Kata kunci:** tambahkan satu atau dua — usulan: *analisis statis kode*;
*platform kontribusi penelitian*. Kata kunci lama tetap.

**ABSTRACT** harus diterjemahkan mengikuti perubahan yang sama, dengan istilah:
contribution subsystem, static code analysis, controlled trial run, dynamic
registry, role-based authorization.

---

## 3. Rumusan masalah dan tujuan

**Rumusan masalah sekarang** (satu kalimat) masih benar, tetapi tidak lagi
menyebut kemampuan yang paling baru. Dua pilihan:

**Pilihan A — perluas kalimat yang ada:**

> Bagaimana merancang dan mengimplementasikan sistem berbasis web on-premise
> untuk mengeksekusi pipeline machine learning pada Intrusion Detection System
> (IDS) secara terisolasi, terkelola, dan reproducible dengan memanfaatkan
> teknologi containerization, **serta bagaimana menegakkan standar pipeline
> tersebut pada kontribusi yang berasal dari luar platform tanpa mengorbankan
> keamanan eksekusi?**

**Pilihan B — jadikan dua rumusan bernomor.** Lebih rapi, tetapi menuntut
penyesuaian pada tujuan, kesimpulan, dan seluruh rujukan silang.

**Rekomendasi: Pilihan A**, karena mempertahankan struktur draf.

**Tujuan (1.4.1)** disesuaikan mengikuti rumusan yang dipilih.

**Manfaat (1.4.2)** — tambahkan dua butir:

> - Memungkinkan peneliti lain menyumbangkan research pipeline miliknya ke dalam
>   kerangka eksperimen yang sama, sehingga perbandingan antar-penelitian dapat
>   dilakukan pada kondisi yang setara.
> - Menyediakan mekanisme pemeriksaan otomatis atas kode pipeline yang diunggah,
>   sehingga kesalahan struktural dan risiko keamanan dapat dikenali sebelum kode
>   tersebut dijalankan.

**Ruang lingkup (1.5)** — tambahkan dua butir:

> - Sistem menerima kontribusi pipeline dalam bahasa Python yang mengikuti kontrak
>   platform; pemeriksaan keamanannya bersifat analisis statis berbasis daftar,
>   bukan isolasi pada tingkat sistem operasi.
> - Pengelolaan pengguna dibatasi pada tiga peran dalam satu instans on-premise,
>   dan tidak mencakup multi-tenancy maupun integrasi dengan penyedia identitas
>   eksternal.

---

## 4. Daftar singkatan: delapan tambahan

| Singkatan | Kepanjangan |
|---|---|
| AST | Abstract Syntax Tree |
| CRUD | Create, Read, Update, Delete |
| i18n | Internationalization |
| JSON | JavaScript Object Notation |
| PBKDF2 | Password-Based Key Derivation Function 2 |
| SHA-256 | Secure Hash Algorithm 256-bit |
| SQL | Structured Query Language |
| UUID | Universally Unique Identifier |

**[PERIKSA: buang yang tidak benar-benar muncul di teks akhir. Daftar singkatan
hanya memuat yang dipakai.]**

Catatan: SHA-256 sudah dipakai berkali-kali di draf tetapi **belum** ada di
daftar singkatan — itu kelalaian yang sekaligus terperbaiki di sini.

---

## 5. Daftar pustaka: usulan penambahan

Draf punya 9 rujukan. Subsistem baru sebaiknya punya minimal satu rujukan
pendukung agar tidak tampak murni rekayasa tanpa dasar.

**Sudah ada dan dapat dipakai ulang (tidak perlu tambah):**

- **Arp et al. (2022)** — untuk praktik keliru pada machine learning di ranah
  keamanan; relevan untuk gerbang metodologis.
- **Kapoor & Narayanan (2023)** — untuk kebocoran dan krisis reproduksibilitas.
- **Moreau et al. (2023)** — untuk kontainerisasi sebagai penjamin lingkungan.

**Usulan tambahan (pilih satu, cari yang benar-benar dapat diakses dan dibaca):**

1. Satu rujukan tentang **analisis statis untuk keamanan Python** atau
   **eksekusi kode tidak tepercaya**, untuk menopang subbab 1.2.8.
2. Satu rujukan tentang **infrastruktur reproduksibilitas berbagi-pakai** atau
   **platform eksperimen kolaboratif** (misalnya pembahasan tentang MLflow,
   OpenML, atau Papers-with-Code sebagai pembanding), untuk menopang argumen
   bahwa kebutuhan kontribusi terverifikasi bukan kebutuhan yang dikarang.

**PENTING: jangan mengarang rujukan.** Bila belum menemukan yang sesuai, tulis
`[PERLU_DIISI: rujukan tentang ...]` dan biarkan penulis mencarinya sendiri.
Rujukan palsu adalah pelanggaran akademik yang jauh lebih berat daripada bab yang
kurang rujukan.

---

## 6. Ucapan terima kasih dan lampiran

- **Ucapan terima kasih:** tidak perlu diubah.
- **Lampiran 1 (kode sumber):** tetap; tautan repositori sudah benar.
- **Lampiran 2 (usulan baru):** jejak perintah dan keluaran pengujian lapangan
  subsistem kontribusi. Ini menaikkan kredibilitas Bab III secara berarti karena
  setiap angka dapat ditelusuri ke keluaran mentahnya.
  **[PERLU_DIPASTIKAN PENULIS: apakah lampiran log akan disertakan; bila ya,
  tambahkan barisnya pada Daftar Lampiran.]**

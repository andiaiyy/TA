# BAGIAN 7/19 — REGISTRY DINAMIS, VERSIONING, DAN ISOLASI

Bahan untuk **2.2.4.7 lanjutan**, **2.2.3.2 Layer Pipelines/Storage**, dan
tabel baru.

---

## 1. Registry gabungan: bawaan statis + kontribusi dinamis

Draf menyebut "satu registry terpusat" yang memetakan `pipeline_id` ke kelas
pipeline. Itu masih benar untuk pipeline bawaan. Yang bertambah: registry yang
**dibaca sistem** sekarang adalah **gabungan** dua sumber.

| Sumber | Tempat | Sifat |
|---|---|---|
| `config.pipeline_registry.PIPELINE_REGISTRY` | kode | statis, 10 entri, tidak berubah saat sistem berjalan |
| tabel `registered_pipelines` | basis data | dinamis, bertambah setiap persetujuan |

Fungsi `get_all_pipelines()` menggabungkan keduanya. Tiga sifat yang dijaga dan
layak ditulis:

1. **Statis selalu menang.** Bila terjadi tabrakan pengenal, entri bawaan yang
   dipertahankan.
2. **Tabrakan tidak mungkin terjadi.** Pipeline kontribusi memakai ruang nama
   `uploaded.<nama>_<kelas>@v<N>` dan jenis datasetnya `uploaded:<nama>`, jadi
   bertabrakan dengan `hikari2021.*` atau `eve_cbr.*` bukan sekadar tidak
   disengaja, melainkan **tidak dapat terjadi**.
3. **Kegagalan membaca tabel tidak merusak yang bawaan.** Tabel yang hilang atau
   rusak menghasilkan daftar bawaan yang utuh, bukan halaman yang jatuh.

Terbukti pada kasus **KTR-I-01**: sesudah sebuah paket tiga algoritma disetujui,
kesepuluh pengenal bawaan tetap identik dengan `PIPELINE_REGISTRY`, dan seluruh
pengenal kontribusi berawalan `uploaded.` tanpa kecuali.

---

## 2. Verifikasi hash pada setiap pemuatan

Setiap baris `registered_pipelines` menyimpan `file_hash` — SHA-256 berkas titik
masuk pada saat pendaftaran. **Setiap kali** kelas pipeline hendak dimuat, hash
berkas di disk dihitung ulang dan dibandingkan. Bila berbeda, **pemuatan
ditolak** dan kode tidak pernah dijalankan.

Terbukti pada kasus **KTR-I-03**: setelah berkas diubah langsung di disk (di luar
penyunting versi), pemuatan ditolak dengan pesan yang menyebut hash tercatat dan
hash yang ditemukan; tidak ada eksperimen yang terbentuk.

Ini menutup celah yang tersisa setelah gerbang persetujuan: menukar berkas
**sesudah** disetujui pun tidak berhasil.

**Catatan teknis yang layak disebut di Bab II** (menunjukkan kedalaman
pemeriksaan): Python menganggap bytecode yang tersimpan (`.pyc`) masih sahih bila
ukuran dan waktu-ubah berkas sumbernya sama — dan keduanya diukur dalam satuan
**detik**. Akibatnya, dua versi berkas yang berbeda isinya tetapi berukuran sama
dan ditulis pada detik yang sama dapat memakai bytecode lama, sehingga
pemeriksaan hash lulus tetapi kode yang berjalan bukan kode yang diverifikasi.
Platform menutup celah ini dengan pemuat khusus yang **selalu mengompilasi dari
byte yang baru saja diverifikasi**, bukan dari cache.

---

## 3. Versioning: menyunting selalu menambah, tidak pernah menimpa

Research Admin dapat menyunting sumber pipeline kontribusi lewat penyunting versi
di dalam aplikasi. Aturannya, berurutan, dan setiap langkah adalah pengaman:

1. **izin** — hanya Research Admin (ditegakkan di fungsi, bukan di tombol);
2. **ruang nama** — pipeline bawaan ditolak; hanya kontribusi yang dapat
   disunting;
3. **catatan perubahan wajib** — inilah isi riwayat versinya;
4. **validasi statis ulang** — gagal berarti berhenti **sebelum** ada berkas yang
   ditulis;
5. **tulis seluruh berkas paket** ke folder versi berikutnya; versi lama tetap
   utuh di tempatnya;
6. baris registry baru dengan `version = max + 1`, hash baru, penyunting, waktu,
   dan catatan perubahan.

Terbukti pada kasus **KTR-I-02** dan **KTR-I-06**: sesudah persetujuan kedua dan
sesudah penyuntingan, terdapat baris v1 **dan** v2 sekaligus, dan berkas v1
masih ada di disk.

**Konsekuensi untuk ketertelusuran:** eksperimen lama menunjuk `pipeline_id`
beserta `pipeline_version` dan `pipeline_hash`-nya sendiri, sehingga kode yang
dipakainya tetap dapat ditemukan meski pipeline itu sudah punya versi yang lebih
baru.

---

## 4. Penonaktifan, bukan penghapusan

Sebuah pipeline kontribusi dapat dinonaktifkan (`active = 0`). Yang terjadi:
barisnya **tetap ada**, berkasnya **tetap ada**, hash-nya **tidak berubah** —
hanya ketersediaannya untuk dijalankan yang dicabut. Terbukti pada kasus
**KTR-I-05**.

Penghapusan versi tersedia tetapi dijaga penghalang tersendiri: versi yang sudah
dipakai eksperimen tidak dapat dihapus, karena menghapusnya akan memutus
ketertelusuran eksperimen tersebut.

**Kalimat yang layak:**

> Penonaktifan dipilih sebagai bentuk pencabutan yang utama, bukan penghapusan,
> karena setiap eksperimen yang pernah dijalankan menunjuk berkas dan hash
> tertentu. Menghapus berkas itu berarti membuat eksperimen yang sudah dilaporkan
> tidak lagi dapat ditelusuri, dan itu justru merusak sifat yang menjadi
> kontribusi utama penelitian ini.

---

## 5. Isolasi: direktori unggahan tidak pernah masuk `sys.path`

Pemuatan kelas pipeline kontribusi dilakukan lewat `spec_from_file_location`
(memuat dari jalur berkas tertentu), **bukan** dengan menambahkan direktori
unggahan ke `sys.path`.

Bedanya menentukan. Bila direktori unggahan masuk ke jalur pencarian modul, maka
sebuah berkas bernama `contracts.py` di dalamnya akan **membajak** modul platform
bernama sama pada impor berikutnya.

Terbukti pada kasus **KTR-I-04**: sebuah berkas `contracts.py` diletakkan di
direktori paket unggahan; direktori itu **tidak** muncul di `sys.path`, pipeline
tetap berhasil dimuat, dan `contracts.pipeline_contracts` tetap menunjuk berkas
platform yang asli.

---

## 6. Potret `get_info()` (info_json) — mengapa perlu

Halaman katalog perlu menampilkan keterangan setiap research pipeline: algoritma,
langkah praproses, strategi seleksi fitur, hyperparameter terkunci. Untuk
pipeline bawaan, keterangan itu diambil dengan memanggil `get_info()`.

Untuk pipeline kontribusi, memanggilnya berarti **memuat dan menjalankan kode
kontributor hanya untuk menggambar sebuah kartu di layar**. Itu tidak dapat
diterima: kode pihak ketiga tidak boleh dieksekusi untuk keperluan tampilan.

Solusinya: pada saat pendaftaran, `get_info()` dipanggil **satu kali** di jalur
yang memang sudah memuat kode itu (persetujuan), hasilnya disimpan sebagai
`info_json`, dan seluruh tampilan sesudahnya membaca potret tersebut. Dampak
terukur: biaya render halaman Progres & Status pada keadaan panas turun dari
**5 pembacaan menjadi 1**.

---

## 7. Ketahanan lintas lingkungan (temuan yang layak ditulis)

`registered_pipelines.entry_file` dan `research_pipelines.dataset_json` menyimpan
**jalur absolut**. Platform ini berpindah antara host Windows dan kontainer Linux
di atas direktori `storage/` yang sama, sehingga jalur yang benar di satu
lingkungan salah di lingkungan lain — akibatnya pipeline yang berkasnya ada
persis di sana dilaporkan "bermasalah", dan dataset yang terikat padanya tidak
muncul untuk dipilih.

Penyelesaiannya adalah penambatan ulang saat pembacaan: jalur dipakai apa adanya
bila berkasnya ada; bila tidak, ekornya (bagian sesudah `uploaded_pipelines/`
atau `uploaded_datasets/`) ditambatkan ke akar `storage/` yang berlaku,
**dan hanya bila hasilnya benar-benar ada**. Pemeriksaan hash sama sekali tidak
dilonggarkan: berkas yang benar-benar berubah tetap ditolak.

Temuan ini layak masuk Bab III sebagai **temuan operasional** (Bagian 16),
karena ia contoh konkret persoalan yang hanya muncul ketika sistem benar-benar
dijalankan di dua lingkungan, bukan ketika diuji di satu lingkungan saja.

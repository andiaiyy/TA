# BAGIAN 8/19 — IDENTITAS RESEARCH PIPELINE & KATALOG GABUNGAN

Bahan untuk **2.2.4.4** (penerapan standarisasi per dataset) dan **2.2.3.5**
(alur pemilihan), serta tabel baru.

---

## 1. Masalah yang diselesaikan

Sebelum subsistem ini ada, "apa yang membuat sebuah research pipeline ada di
platform" ditentukan oleh **tiga sumber statis di dalam kode**:

| Sumber | Menentukan |
|---|---|
| `contracts/dataset_schemas.py` | `dataset_type` beserta skema datasetnya |
| `config/research_attribution.py` | nama beratribusi dan kredit penelitian |
| `config/pipeline_registry.py` | daftar algoritmanya |

Hanya sumber ketiga yang punya pasangan dinamis (`registered_pipelines`).
Akibatnya sebuah unggahan **tidak pernah dapat berdiri sendiri**: ia harus
menumpang salah satu `dataset_type` bawaan. Kartu peninjauan bahkan sempat harus
bertanya "ini ikut research pipeline mana" — pertanyaan yang lahir dari
ketiadaan jalur dinamis, bukan dari pilihan rancangan.

**Penyelesaiannya:** tabel `research_pipelines` melengkapi dua sumber sisanya,
mengikuti pola yang sudah terbukti pada registry algoritma.

---

## 2. Tabel `research_pipelines` (10 kolom)

| Kolom | Isi |
|---|---|
| dataset_type | pengenal, berawalan `uploaded:` |
| name | nama research pipeline |
| submission_id | pengajuan asalnya |
| schema_json | kontrak dataset yang dideklarasikan pengunggah |
| attribution_json | atribusi penelitian (penulis, tahun, institusi, judul, cakupan, sumber dataset) |
| registered_by / registered_at | siapa dan kapan didaftarkan |
| active | ketersediaan |
| dataset_json | dataset yang **menyatu** dengan research pipeline ini |
| updated_at / updated_by | suntingan terakhir (migrasi 30 dan 31) |

**Tiga sifat yang dijaga dan layak ditulis:**

1. **Statis selalu menang.** Skema dan atribusi bawaan tidak dapat ditimpa oleh
   baris yang muncul lewat jalur lain.
2. **Skema dideklarasikan, tidak pernah ditebak.** Isinya berasal dari isian
   kontributor; platform tidak pernah mengarang skema dari nama berkas atau dari
   isi datanya.
3. **Kegagalan membaca tidak merusak yang bawaan.** Tabel yang hilang atau rusak
   menghasilkan daftar bawaan yang utuh.

---

## 3. Pembacaan gabungan

Modul `orchestrator/research_registry.py` menyediakan pembaca gabungan yang
dipakai seluruh tampilan:

| Fungsi | Menjawab |
|---|---|
| `all_dataset_types()` | jenis dataset bawaan + kontribusi yang aktif; bawaan selalu lebih dulu |
| `schema_for(dataset_type)` | skema efektif — bawaan menang, lalu kontribusi |
| `attribution_for(dataset_type)` | atribusi efektif |
| `dataset_for(dataset_type)` | dataset yang terikat pada research ini |
| `dataset_files_for(dataset_type)` | berkas dataset yang boleh dipakai research ini |
| `display_name_for` / `short_label_for` | nama beratribusi untuk ditampilkan |

**Catatan arsitektur yang layak disebut di 2.2.3.3:** modul ini sengaja
ditempatkan pada lapisan orchestrator, bukan di `contracts/` atau `config/`.
Alasannya, `pipelines/` mengimpor `config.research_attribution` di tujuh tempat
dan **tidak boleh** mengimpor `orchestrator/` maupun `database/`. Menaruh
pembaca gabungan di sana akan membalik arah ketergantungan antarlapisan.
Karena itu fungsi statisnya dibiarkan apa adanya untuk `pipelines/`, dan
penggabungan hidup di lapisan yang memang sudah boleh membaca basis data.

Ini contoh bagus untuk memperkuat argumen aturan ketergantungan pada draf: aturan
itu benar-benar membatasi keputusan rancangan, bukan sekadar dokumentasi.

---

## 4. Dataset yang menyatu dengan research pipeline (penting untuk 2.2.4.4)

Research pipeline kontribusi yang berdiri sendiri **membawa datasetnya sendiri**
dan hanya boleh memakai itu. Konsekuensinya, dan inilah yang menjaga
keterbandingan tetap jujur:

- Datasetnya **tidak pernah** masuk ke `storage/datasets/`, sehingga ia tidak
  ikut ditawarkan sebagai dataset platform.
- Dataset kontribusi **tidak dapat** dipakai menjalankan pipeline bawaan yang
  menjadi dasar hasil penelitian Bab III.
- Sebaliknya, pipeline kontribusi yang berdiri sendiri **tidak dapat** memakai
  dataset platform.
- Research pipeline **bawaan** sama sekali tidak berubah: pilihannya tetap isi
  `storage/datasets/` yang disaring menurut ekstensi jenisnya.

**Kalimat yang layak:**

> Pemisahan ini menjaga agar penambahan kontribusi tidak pernah mencemari dasar
> pembanding penelitian. Sebuah dataset yang dibawa kontributor hanya berlaku
> bagi research pipeline yang membawanya, sehingga angka pada Tabel 20 tetap
> berasal dari dataset yang sama persis dengan yang dilaporkan sejak awal.

---

## 5. Katalog research pipeline pada halaman eksekusi

Halaman Jalankan Eksperimen menampilkan katalog research pipeline — bawaan dan
kontribusi berdampingan, dengan bentuk kartu yang sama. Tiap kartu memuat nama
beratribusi, penjelasan singkat, daftar algoritma sebagai chip, dan keadaannya.

**Pencarian dan penyaring bertingkat.** Sejak jumlah research dapat bertambah
seiring kontribusi, katalog dilengkapi:

- **kotak pencarian** yang menjangkau nama beratribusi, jenis dataset, cakupan,
  nama algoritma, institusi, tahun, dan rujukan paper;
- **penyaring bertingkat**: kategori dipilih lebih dulu (Asal, Jenis dataset,
  Format berkas, Algoritma, Institusi, Tahun), lalu nilainya muncul sebagai
  kotak centang beserta jumlah masing-masing.

Dua aturan yang layak ditulis karena keduanya keputusan rancangan, bukan detail
teknis:

1. **Sebuah kategori hanya ditawarkan bila nilainya lebih dari satu.** Penyaring
   dengan satu pilihan tidak menyaring apa pun; ia hanya memakan ruang. Daftar
   kategori karena itu mengikuti isi katalog, bukan daftar tetap yang lama-lama
   menjadi tidak benar.
2. **Yang tidak menyebutkan sebuah keterangan tetap terlihat**, lewat pilihan
   eksplisit "tidak disebutkan". Tanpa itu, menyaring berdasarkan institusi akan
   membuat setiap research pipeline lama menghilang tanpa sebab yang terbaca.

Seluruh penyaring yang sedang aktif dicetak terus-menerus beserta tombol
pembersih, sehingga tidak pernah ada baris yang tersembunyi tanpa alasan yang
terbaca.

---

## 6. Halaman pengelolaan research pipeline

Halaman Tambah Pipeline & Dataset memuat daftar pengelolaan yang menampilkan
**seluruh** research pipeline — bawaan maupun kontribusi, aktif maupun tidak —
dengan pencarian, penyaring status/asal, dan pengurutan (terbaru diperbarui,
nama A–Z, tahun).

Tiga keputusan yang layak dicatat:

1. **Sumbernya bukan tabel pengajuan.** Antrean tinjauan adalah jejak alur kerja,
   bukan katalog; memakainya sebagai sumber daftar akan menyembunyikan seluruh
   research pipeline bawaan.
2. **Metadata setiap research dapat disunting**, termasuk milik research bawaan.
   Suntingan atas research bawaan disimpan sebagai **baris timpaan** di basis
   data — berkas definisi di `contracts/` dan `config/` tidak pernah disentuh —
   dan selalu dapat dipulihkan ke definisi aslinya.
3. **Cap waktu tidak pernah dikarang.** Research bawaan hidup di kode, bukan di
   basis data, sehingga ia memang tidak punya tanggal; keadaan itu dinyatakan apa
   adanya, bukan diisi dengan tanggal terdekat yang kebetulan tersedia.

**[CATATAN UNTUK PENULIS: bagian ini adalah pekerjaan paling akhir dan paling
sedikit teruji di lapangan dibanding gerbang validasi/uji coba. Bila ingin aman,
tulis secukupnya di Bab II sebagai fasilitas pengelolaan, dan jangan menjadikannya
klaim utama di Bab IV.]**

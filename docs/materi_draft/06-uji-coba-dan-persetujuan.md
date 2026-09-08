# BAGIAN 6/19 — GERBANG 2 & 3: UJI COBA (TRIAL) DAN PERSETUJUAN

Bahan untuk **subbab baru 2.2.4.7** (lanjutan Bagian 5) dan tabel baru.

---

## 1. Mengapa uji coba diperlukan sesudah validasi statis

Validasi statis menjawab "apakah kode ini berbentuk benar dan tidak menjangkau
hal yang terlarang". Ia **tidak** menjawab "apakah kode ini benar-benar berjalan
dan menghasilkan sesuatu yang bermakna". Sebuah paket dapat lolos seluruh
pemeriksaan struktur dan keamanan namun tetap gagal pada baris pertama
eksekusinya, atau menghasilkan model yang tidak belajar apa pun.

Karena itu persetujuan tidak boleh diberikan berdasarkan pemeriksaan statis saja.
Uji coba adalah **satu-satunya titik** ketika kode kontributor benar-benar
dijalankan sebelum ia diterima — dan justru karena itu ia dijalankan di bawah
batas yang ketat.

---

## 2. Batas sumber daya yang ditegakkan

| Batas | Nilai | Alasan |
|---|---|---|
| Waktu maksimum | **300 detik** | Uji coba menjawab "apakah pipeline ini berjalan", bukan "berapa skor terbaiknya"; lima menit cukup untuk menemukan kesalahan kontrak, impor, bentuk data, dan kolom |
| Baris dataset maksimum | **50.000 baris** | Dataset penelitian platform berukuran ratusan ribu baris; uji coba tidak perlu seluruhnya |
| Ukuran dataset lampiran | **25 MB** | Membatasi biaya penyimpanan area pengajuan |
| Kedaluwarsa uji coba | **24 jam** | Uji coba yang tertinggal dianggap basi dan tidak dapat dipakai menyetujui |

Pembandingnya: eksperimen resmi dibatasi 3.600 detik (satu jam) pada jalur
asinkron. Jadi batas uji coba **dua belas kali lebih ketat**, dan itu disengaja.

**Pemotongan baris terjadi saat pembacaan**, bukan sesudah dataset dimuat penuh
ke memori — dibuktikan pada kasus KTR-T-05 (Bagian 15).

---

## 3. Isolasi uji coba dari data penelitian

Tiga pemisahan yang layak ditulis sebagai klaim:

1. **Proses terpisah.** Uji coba dijalankan pada proses anak, bukan di dalam
   proses antarmuka, sehingga kegagalan atau kemacetan kode kontributor tidak
   menjatuhkan aplikasi.
2. **Tabel terpisah.** Hasilnya ditulis ke `pipeline_trials`, bukan
   `experiments`. Jumlah baris `experiments` terbukti **tidak berubah** (61 → 61)
   sepanjang seluruh rangkaian uji coba pada pengujian lapangan.
3. **Artefak terpisah dan bersifat sementara.** Direktori artefaknya
   `storage/trials/`, bukan `storage/artifacts/`; baris `pipeline_trials`
   dibersihkan setelah keputusan persetujuan diambil (terbukti: 3 baris → 0).

Konsekuensi metodologisnya penting dan layak dinyatakan: **angka hasil uji coba
tidak pernah bercampur dengan angka hasil penelitian**. Uji coba adalah alat
kendali mutu, bukan sumber data Bab III.

---

## 4. Dua sumber dataset untuk uji coba

| Sumber | Keterangan |
|---|---|
| **Dataset platform** | Research Admin memilih salah satu dataset yang sudah ada di `storage/datasets/` |
| **Dataset lampiran kontributor** | Kontributor melampirkan dataset uji cobanya sendiri bersama pengajuan |

Sumber kedua diperlukan karena sebuah research pipeline kontribusi boleh berdiri
sendiri dengan **jenis dataset yang belum dikenal platform**. Untuk kasus itu,
platform tidak punya dataset yang cocok, dan satu-satunya cara mengujinya adalah
memakai dataset yang dibawa pengajuan itu sendiri.

**Penentuan jenis dataset** dilakukan berurutan oleh `resolve_dataset_type()`:

1. jenis berkas platform yang dipilih (paling berwenang — itulah data yang
   benar-benar dibaca); dilewati untuk dataset lampiran;
2. **deklarasi pipeline** — dibaca statis dari kunci literal `"dataset_type"` di
   dalam dict yang dikembalikan `get_info()`;
3. metadata pengajuan (isian kontributor pada formulir);
4. identitas yang **akan** dimilikinya bila disetujui — hanya untuk pengajuan
   yang berdiri sendiri.

Langkah keempat ada karena tanpa itu jawabannya melingkar: identitas research
pipeline berdiri sendiri baru dibuat saat disetujui, persetujuan menuntut uji
coba yang lulus, dan uji coba menuntut jenis dataset. Nilai yang dipakai
**dihitung dari pengajuan itu sendiri**, bukan dibaca dari tabel yang memang
belum terisi, sehingga tidak ada baris yang didaftarkan lebih awal.

---

## 5. Gerbang 3: persetujuan

Persetujuan hanya terbuka bila **seluruh** syarat berikut terpenuhi. Setiap
syarat punya penanda alasannya sendiri sehingga peninjau tahu mengapa tombolnya
terkunci:

| Penghalang | Artinya |
|---|---|
| `trial.static_failed` | paket belum lolos pemeriksaan statis |
| `trial.gate_untested` | paket belum pernah diuji coba |
| `trial.gate_failed` | uji coba terakhir berstatus gagal |
| `trial.gate_stale` | isi paket berubah sesudah uji coba terakhir |
| `trial.not_pending` | pengajuan sudah diputuskan sebelumnya |
| `trial.only_pipeline` | hanya pengajuan pipeline yang ditinjau |

**Gerbang `gate_stale` adalah yang paling menarik secara metodologis.** Sidik
jari (hash) seluruh berkas paket dicatat pada saat uji coba dijalankan. Bila
sesudahnya ada **satu karakter pun** yang berubah pada paket itu, sidik jarinya
tidak lagi cocok dan persetujuan otomatis tertutup sampai uji coba diulang.
Tanpa gerbang ini, seorang kontributor dapat menguji coba kode yang bersih lalu
menukarnya dengan kode lain sebelum disetujui.

Terbukti pada kasus **KTR-T-06**: sebelum diubah `approval_blocker` kosong;
sesudah satu baris komentar ditambahkan, ia berubah menjadi `trial.gate_stale`
dan `approve_submission` menolak dengan pesan yang dapat dibaca.

---

## 6. Apa yang terjadi pada saat persetujuan (satu transaksi)

1. Berkas paket **dipindahkan** dari area `pending/` ke `approved/`.
2. Satu baris `registered_pipelines` dibuat **untuk setiap algoritma** dalam
   paket, dengan `version = 1`, `entry_class`, `entry_file`, dan
   `file_hash` (SHA-256) masing-masing.
3. Potret `get_info()` disimpan sebagai `info_json` agar tampilan tidak perlu
   memuat kode kontributor hanya untuk menampilkan keterangannya (lihat
   Bagian 7 pasal 5).
4. Bila pengajuan berdiri sendiri, satu baris `research_pipelines` dibuat berisi
   identitas, skema dataset yang dideklarasikan, dan atribusi penelitiannya.
5. Dataset lampiran diikat ke research pipeline itu, sehingga hanya dataset itu
   yang ditawarkan untuk menjalankannya.
6. Status pengajuan berubah menjadi `approved` beserta nama peninjau, waktu, dan
   catatan.

Bila salah satu langkah gagal, tidak ada satu pun yang berubah.

---

## 7. Penolakan

Menolak **wajib disertai alasan** — tanpa catatan, aksinya tidak dijalankan sama
sekali. Berkasnya **tidak dihapus**, hanya berpindah status ke `rejected`,
sehingga keputusan dapat ditinjau ulang di kemudian hari.

---

## 8. Kalimat penutup yang layak

> Ketiga gerbang bekerja berurutan dan tidak dapat saling menggantikan: gerbang
> pertama memastikan kode berbentuk benar dan tidak menjangkau yang terlarang,
> gerbang kedua memastikan kode benar-benar berjalan di bawah batas sumber daya,
> dan gerbang ketiga memastikan yang disetujui adalah kode yang persis sama
> dengan yang diuji. Keputusan akhir tetap berada pada manusia; sistem hanya
> memastikan bahwa keputusan itu diambil di atas bukti yang lengkap dan masih
> berlaku.

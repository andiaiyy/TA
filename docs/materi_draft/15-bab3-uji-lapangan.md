# BAGIAN 15/19 — BAB III BARU: HASIL PENGUJIAN SUBSISTEM KONTRIBUSI

Ini bagian terbesar. Isinya bahan untuk **subbab baru 3.2.5** (sehingga
"Pembahasan" bergeser menjadi 3.2.6) dan perluasan **Tabel 11** pada 2.2.6.

Seluruh angka di bawah berasal dari satu rangkaian pengujian yang dijalankan
pada 6 September 2026, di atas **salinan** basis data penelitian, dengan jejak
perintah dan keluaran tersimpan.

---

## 1. Perluasan Tabel 11 (rancangan pengujian) pada 2.2.6

Draf punya tiga kategori: fungsional, reproducibility, stabilitas. Tambahkan
**empat kategori baru** khusus subsistem kontribusi. Rancangan ini ditetapkan
**sebelum** pengujian dijalankan.

| Kategori | Aspek yang diuji | Metrik/Parameter | Kriteria keberhasilan |
|---|---|---|---|
| **Fungsional kontribusi** | unggah berkas dan paket, penolakan nama tidak sah, antrean tinjauan, cuplikan registry, pembacaan deklarasi jenis dataset | status pengajuan, isi area staging | unggahan tercatat berstatus pending; berkas berada di area staging, bukan di dalam paket Python; nama tidak sah ditolak |
| **Validasi statis** | fikstur negatif, pemisahan kelompok cek, deteksi tiap kategori pelanggaran, cakupan seluruh berkas paket, ketiadaan eksekusi kode | verdict, nomor baris temuan, keberadaan penanda eksekusi | seluruh pelanggaran terdeteksi dengan nomor baris tepat; kode kontributor **tidak** dieksekusi; paket bersih lulus tanpa false positive |
| **Uji coba terkendali** | izin, gerbang paket gagal, uji coba dengan dataset lampiran, batas sumber daya, sidik jari paket, keterpisahan artefak | durasi, metrik, jumlah baris tabel | uji coba selesai dalam batas; artefak terpisah; jumlah baris `experiments` tidak berubah |
| **Isolasi & versioning** | pipeline bawaan tidak terbayangi, versi baru, verifikasi hash, `sys.path`, penonaktifan, penyuntingan | daftar pengenal, baris registry, keberadaan berkas | sepuluh pengenal bawaan tetap utuh; penyuntingan selalu menambah versi; berkas yang diubah ditolak saat dimuat |

Kategori **Reproducibility**, **Otorisasi**, dan **Stabilitas** tetap seperti
draf, hanya diperluas ke pipeline kontribusi.

---

## 2. Ringkasan hasil (tabel pertama pada 3.2.5)

| Kategori | Jumlah kasus | Lulus | Gagal | Terblokir | Tidak diuji |
|---|---:|---:|---:|---:|---:|
| A. Fungsional kontribusi | 6 | 6 | 0 | 0 | 0 |
| B. Validasi statis | 6 | 6 | 0 | 0 | 0 |
| C. Uji coba terkendali | 8 | 7 | **1** | 0 | 0 |
| D. Isolasi & versioning | 6 | 6 | 0 | 0 | 0 |
| E. Reproducibility kontribusi | 6 | 6 | 0 | 0 | 0 |
| F. Otorisasi peran | 2 | 2 | 0 | 0 | 0 |
| G. Stabilitas | 4 | 4 | 0 | 0 | 0 |
| **Total** | **38** | **37** | **1** | **0** | **0** |

Satu kasus yang gagal (C-4) **bukan kegagalan sistem** — penjelasannya di
pasal 6. Empat ruas di dalam kasus yang lulus ditandai "tidak diuji" dan
disebutkan apa adanya (pasal 8).

---

## 3. Berkas uji yang dipakai (untuk 3.1 Data)

Pengujian memerlukan pipeline kontribusi yang belum pernah ada di platform.
Lima berkas fikstur dibuat khusus untuk itu:

| Berkas | Peran | SHA-256 |
|---|---|---|
| kontrib_extratrees_pipeline.py | titik masuk paket | 3ddbb34c0dcfbdd8067b305bcef0357f3cc2501c31e0510fc87a376b6b0af815 |
| kontrib_gradboost_pipeline.py | anggota paket | c23459fee9d4296b5cc7e34ae30e27fb869be89fd32db19346bf7adb125a224e |
| kontrib_adaboost_pipeline.py | anggota paket | 35623528817b75ac303aa271758d30554618d3a440235979252acc72a596a061 |
| kontrib_ditolak_pipeline.py | fikstur negatif | 8ffc900006db265034b74ec923ac2d5db57e1cb026bcf4543ec6564033b7b221 |
| hikari2021_sample_6k.csv | dataset uji coba | 2ab8446f39551ae1ed2c85450c8f34300805bc6d1c526eeed696984f562f7b12 |

**Dataset uji coba:** 6.000 baris × 88 kolom (3.673.695 byte), disampel dari
ALLFLOWMETER_HIKARI2021.csv dengan komposisi **seimbang 3.000 benign : 3.000
attack**. Hasil `validate_dataset(df, "HIKARI2021")`: `is_valid=True`,
`label_column='Label'`, `unique_labels=[0, 1]`, tanpa kolom yang hilang.

**Fikstur negatif** sengaja dibuat dengan **struktur yang sah** (mewarisi
BasePipeline, `run(pipeline_input, progress)`, `get_info()` lengkap) tetapi
menanam **satu pelanggaran keamanan per kategori pada baris terpisah**, agar
pemisahan kelompok cek dan ketepatan nomor baris dapat diuji.

**Catatan metodologis yang wajib ditulis:** dataset seimbang 50:50 ini **bukan**
representasi distribusi HIKARI2021 yang sebenarnya (93,2% benign). Ia dipilih
karena tujuannya menguji **mekanisme platform**, bukan mengukur kinerja model.
Konsekuensinya dibahas pada pasal 6.

---

## 4. Hasil per kategori (bahan tabel-tabel 3.2.5)

### 4.1 Kategori A — Fungsional kontribusi (6/6 lulus)

| Kasus | Hasil kunci |
|---|---|
| Unggah satu berkas | tercatat berstatus `pending`; berkas berada di area staging; **tidak** berada di dalam paket Python mana pun |
| Unggah paket tiga berkas | ketiganya tersimpan dalam satu direktori; **satu** baris pengajuan mewakili paket; metadata mencatat ketiga berkas dengan titik masuk di depan |
| Penolakan nama tidak sah | `../keluar.py` ditolak ("nama berkas tidak aman"); `berkas spasi.py` ditolak ("hanya boleh huruf/angka/._-"); `pipeline.txt` ditolak ("ekstensi tidak didukung"). **Tidak ada berkas yang telanjur tertulis ke disk** |
| Antrean tinjauan | seluruh pengajuan `pending` tampil beserta metadata dan hasil validasinya, tanpa membuka berkas paketnya |
| Cuplikan registry | ruas yang terbaca statis terisi (`dataset_type`, `algorithm`, `paper`); yang tidak terbaca muncul sebagai `PERLU_DIISI_...`, **bukan tebakan** |
| Deklarasi jenis dataset | terbaca `HIKARI2021` dari kunci literal `"dataset_type"` di dalam dict yang dikembalikan `get_info()` |

### 4.2 Kategori B — Validasi statis (6/6 lulus)

Hasil pada fikstur negatif: kelompok **Struktur 6 cek, 0 gagal (LULUS)**;
kelompok **Keamanan 6 temuan, seluruhnya gagal (GAGAL)**. Persis seperti yang
dituju rancangan fikstur.

**Ketepatan nomor baris — tabel yang layak dikutip utuh:**

| Kategori pelanggaran | Terdeteksi | Baris dilaporkan | Baris sebenarnya |
|---|:---:|---:|---:|
| Impor terlarang `os` | ya | 7 | 7 |
| Impor terlarang `subprocess` | ya | 8 | 8 |
| Impor terlarang `socket` | ya | 9 | 9 |
| Pemanggilan terlarang `eval()` | ya | 19 | 19 |
| `open()` mode tulis | ya | 20 | 20 |
| Atribut dunder `__subclasses__` | ya | 21 | 21 |

Enam pelanggaran ditanam, enam terdeteksi, **keenam nomor barisnya tepat**, dan
tidak ada pelanggaran yang lolos.

Tiga hasil lain:

- **Seluruh berkas paket diperiksa:** `import os` disisipkan pada berkas yang
  **bukan** titik masuk; paket ditolak, berkas bermasalahnya ditunjuk dengan
  benar, dan berkas titik masuk yang bersih tetap dinyatakan lulus.
- **Kode tidak dieksekusi:** berkas uji memanggil `open(..., 'w')` pada tingkat
  modul; sesudah validasi, penanda **tidak terbentuk**. Ini pengujian terpenting
  di seluruh rangkaian.
- **Paket bersih lulus:** ketiga berkas dikenali sebagai titik masuk, tanpa satu
  pun peringatan dan tanpa satu pun *false positive*.

### 4.3 Kategori C — Uji coba terkendali (7/8 lulus)

| Kasus | Hasil |
|---|---|
| Izin uji coba | visitor dan kontributor ditolak `PermissionDenied` **saat fungsi layanan dipanggil langsung**, tanpa melewati antarmuka; Research Admin lolos gerbang izin dan berhenti pada gerbang berikutnya |
| Gerbang paket gagal | `trial.static_failed`; `run_trial` menolak dengan kalimat yang dapat dibaca |
| Uji coba dengan dataset lampiran | ketiganya selesai; lihat tabel di bawah |
| Batas sumber daya | `max_rows=1000` mengembalikan 1.000 baris dari berkas 6.000 baris; pemotongan terjadi **saat pembacaan** |
| Sidik jari paket | `approval_blocker` kosong sebelum diubah; berubah menjadi `trial.gate_stale` sesudah satu baris ditambahkan; persetujuan ditolak |
| Keterpisahan artefak | baris `pipeline_trials` **3 → 0** setelah keputusan; jumlah folder `storage/artifacts/` **tidak berubah** (78 → 78) |
| Jumlah eksperimen penelitian | **61 → 61**, tidak berubah |

**Hasil ketiga uji coba:**

| Pipeline | Status | Durasi | Accuracy | F1-Score | Fitur |
|---|---|---:|---|---|---:|
| KontribExtraTreesPipeline | selesai | 3,84 detik | 1,0 | 1,0 | 81 |
| KontribGradBoostPipeline | selesai | 6,21 detik | 0,9991666666666666 | 0,9991666660879626 | 81 |
| KontribAdaBoostPipeline | selesai | 3,93 detik | 1,0 | 1,0 | 81 |

Terlama 6,21 detik dari batas 300 detik.

### 4.4 Kategori D — Isolasi & versioning (6/6 lulus)

| Kasus | Hasil |
|---|---|
| Bawaan tidak terbayangi | kesepuluh pengenal bawaan identik dengan `PIPELINE_REGISTRY` sesudah persetujuan; seluruh pengenal kontribusi berawalan `uploaded.` |
| Versi baru pada persetujuan kedua | terbentuk v1 **dan** v2 untuk ketiga algoritma; berkas v1 masih ada di disk |
| Verifikasi hash saat memuat | pemuatan ditolak dengan pesan yang menyebut hash tercatat dan hash yang ditemukan; tidak ada eksperimen yang terbentuk |
| `sys.path` tidak tercemar | berkas `contracts.py` di direktori unggahan tidak membajak modul platform; pipeline tetap berhasil dimuat |
| Penonaktifan | `active=0`, berkas tetap ada, hash tidak berubah |
| Penyuntingan | v1 → v1 + v2 pada paket satu berkas |

### 4.5 Kategori E — Reproducibility pipeline kontribusi (6/6 lulus)

**Tabel yang layak dikutip utuh:**

| Pipeline kontribusi | Jumlah run | Accuracy | F1-Score | Variansi metrik utama |
|---|:---:|---|---|:---:|
| Extra Trees | 2 | 1,0 | 1,0 | **0** |
| Gradient Boosting | 2 | 0,9991666666666666 | 0,9991666660879626 | **0** |
| AdaBoost | 2 | 1,0 | 1,0 | **0** |

Ketertelusuran yang tercatat pada keenam baris `experiments`:

- `dataset_hash` **identik** pada keenamnya (`2ab8446f3955…`), dan cocok dengan
  SHA-256 berkas dataset pada pasal 3;
- `pipeline_version = 1` pada keenamnya;
- `pipeline_hash` **berbeda per pipeline** (Extra Trees `3ddbb34c0dcf…`,
  AdaBoost `2a4b26043451…`, Gradient Boosting `f9adcd6481fd…`), yang membuktikan
  ketiga run memakai **kode yang berbeda**, bukan pipeline yang tertukar;
- seluruhnya berstatus `FINISHED`.

**Mode run:**

| Kasus | `run_mode` | `params_used` | `params_changed` |
|---|---|---|---:|
| Run resmi + penyesuaian `n_estimators=300` | official | `{"n_estimators": 100, "n_jobs": 1, "random_state": 42}` | 0 |
| Run eksplorasi + penyesuaian `n_estimators=300` | exploration | `{"n_estimators": 300, "n_jobs": 1, "random_state": 42}` | 1 |

**Bukti bahwa penyesuaian benar-benar sampai ke model** (bukan sekadar tercatat):
pada AdaBoost, `n_estimators = 1` menghasilkan accuracy
**0,9791666666666666**, sedangkan `n_estimators = 50` menghasilkan **1,0**.

**Parameter terlindungi:** `balancing`, `scaler`, `test_size`, dan `stratify`
seluruhnya ditolak dengan galat yang menyebutkan alasan penguncian.

### 4.6 Kategori F — Otorisasi peran (2/2 lulus)

| Aksi | Visitor | Kontributor | Research Admin |
|---|:---:|:---:|:---:|
| Unggah | tidak | ya | ya |
| Setujui / uji coba / sunting versi | tidak | tidak | ya |
| Kelola pengguna | tidak | tidak | ya |

Penegakan diverifikasi dengan **memanggil fungsi layanan secara langsung**,
melewati seluruh antarmuka. Peran yang tidak dikenal memperoleh **hak paling
rendah** pada ketiga aksi.

### 4.7 Kategori G — Stabilitas (4/4 lulus)

| Aspek | Hasil |
|---|---|
| Crash / restart kontainer | **0** restart pada ketiga layanan sepanjang rangkaian (± 30 menit) |
| Pemakaian memori | ids_worker 109,5 MiB (3,13%), ids_ui 46,2 MiB (1,28%), ids_redis 8,77 MiB (0,24%) |
| Kegagalan tidak merambat | berkas pipeline sengaja dirusak; eksperimen tercatat `FAILED`, proses pemanggil tetap hidup |
| Sanitasi pesan galat | `error_message` berbunyi "Pipeline not found: uploaded.paket_satu_berkas@v1" — **tidak** memuat lintasan absolut |
| Basis data tetap terbaca | `PRAGMA journal_mode` = `wal`; pembacaan berhasil dari koneksi lain |
| Test suite | 3.071 lulus, 2 dilewati, 0 gagal |

---

## 5. Kalimat pembuka yang disarankan untuk 3.2.5

> Subbab ini menyajikan hasil pengujian subsistem kontribusi, yaitu kemampuan
> platform menerima, memeriksa, menguji, dan mendaftarkan research pipeline yang
> berasal dari luar. Pengujian disusun sebagai 38 kasus dalam tujuh kategori,
> dengan kriteria keberhasilan yang ditetapkan sebelum pengujian dijalankan.
> Seluruh kasus dijalankan di atas salinan basis data penelitian dan direktori
> penyimpanan terpisah, sehingga tidak satu pun baris pada basis data yang
> menjadi dasar Tabel 12 sampai Tabel 20 tersentuh; hal ini diverifikasi dengan
> membandingkan jumlah baris tabel eksperimen sebelum dan sesudah rangkaian
> pengujian, yang tetap bernilai 61.

---

## 6. Satu kasus yang GAGAL — tulis apa adanya (jangan disembunyikan)

**Kasus C-4** menetapkan kriteria: ketiga uji coba selesai **dan ketiga
angkanya berbeda satu sama lain** (bila identik, curigai dataset atau pipeline
tertukar). Hasilnya: ketiga uji coba selesai, tetapi Extra Trees dan AdaBoost
sama-sama menghasilkan accuracy tepat 1,0.

**Kriteria tidak dilonggarkan; kasus ini dicatat GAGAL.**

**Sebabnya bukan platform, dan itu dapat dibuktikan:** ketiga run memakai
`pipeline_hash` yang **berbeda** dan `dataset_hash` yang **sama**, sehingga
kemungkinan "pipeline tertukar" tertutup. Penyebab sebenarnya adalah **dataset
fikstur yang terlalu mudah**: sampel 6.000 baris berimbang dari HIKARI2021 dapat
dipisahkan hampir sempurna oleh 81 fitur berbasis aliran.

**Temuan turunan yang layak ditulis** dan justru menarik secara metodologis:
versi pertama fikstur memakai **seluruh** kolom numerik sebagai fitur, dan kolom
indeks `Unnamed: 0.1` ternyata berkorelasi **0,988** dengan label — sebuah
kebocoran yang lahir dari cara penyampelan, bukan dari platform. Fikstur
diperbaiki dengan membuang kolom non-fitur yang sama dengan yang dibuang pipeline
bawaan (`Unnamed: 0`, `Unnamed: 0.1`, `originh`, `responh`, `traffic_category`,
`uid`), sehingga jumlah fitur turun dari 83 menjadi 81.

**Kalimat penutup yang disarankan:**

> Kegagalan ini justru menegaskan sifat yang sedang diuji. Kriteria "ketiga angka
> harus berbeda" dirancang sebagai pendeteksi kekeliruan, dan ia bekerja: ia
> menyalakan tanda ketika angka yang seharusnya berbeda ternyata sama. Bahwa
> penyebabnya kemudian dapat dilacak ke dataset fikstur — dan bukan ke platform —
> dimungkinkan justru oleh kolom ketertelusuran yang menjadi kontribusi penelitian
> ini. Untuk pengujian berikutnya, sampel sebaiknya mempertahankan ketimpangan
> kelas asli HIKARI2021 agar ketiga algoritma benar-benar terbedakan.

---

## 7. Empat ruas yang TIDAK DIUJI (nyatakan jujur)

Keempatnya berada di dalam kasus yang lulus, tetapi salah satu ruasnya tidak
teramati:

| Ruas | Sebab |
|---|---|
| Penolakan hash pada jalur Celery worker | pengujian dijalankan pada mode sinkron; jalur worker memakai fungsi pemuatan yang sama, tetapi kesamaan itu dibaca dari kode, bukan diamati |
| Tampilan perbandingan versi berdampingan | diuji pada lapisan layanan; tampilannya tidak digerakkan |
| Lencana penanda run eksplorasi pada tabel riwayat dan PDF | sama seperti di atas |
| Selisih AUC antar-run pada pipeline kontribusi | AUC tidak termasuk kolom yang dibandingkan pada rangkaian ini |

---

## 8. Keterbatasan pengujian (untuk 3.2.6 atau subbab keterbatasan)

1. **Dijalankan di host, bukan di dalam kontainer.** Kontainer hidup dan dipakai
   sebagai bahan pengujian stabilitas, tetapi seluruh pemanggilan layanan
   berjalan di host. Akibatnya jalur Celery/worker tidak teruji pada rangkaian
   ini.
2. **Seluruh kasus menyentuh lapisan layanan, bukan antarmuka.** Untuk uji
   otorisasi hal ini justru lebih kuat, tetapi untuk ruas yang bersifat tampilan
   hasilnya kosong.
3. **Akar penyimpanan dialihkan** ke direktori terpisah di dalam proyek;
   perilakunya identik, tetapi lintasan yang dilaporkan bukan lintasan produksi.
4. **Angka metrik uji coba tidak dapat dipakai menilai mutu algoritma** — lihat
   pasal 6.
5. **Satu rangkaian, satu mesin.** Tidak ada pengulangan lintas mesin maupun
   lintas versi pustaka.

---

## 9. Catatan penyusunan (untuk penulis, bukan untuk dimasukkan ke draf)

- Kelima berkas fikstur **tidak ada di repositori** sebelum pengujian; keduanya
  dibuat khusus untuk rangkaian ini. Bila fikstur ingin disertakan sebagai
  lampiran, berkasnya perlu dimasukkan kembali ke repositori.
- Jejak perintah dan keluaran mentah seluruh rangkaian tersimpan sebagai berkas
  log terpisah dan dapat dijadikan **Lampiran 2** bila diinginkan.
- **[PERLU_DIPASTIKAN PENULIS: apakah rangkaian ini akan diulang di dalam
  kontainer sebelum sidang, agar keterbatasan nomor 1 dapat dihapus.]**

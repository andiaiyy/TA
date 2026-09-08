# BAGIAN 16/19 — TEMUAN, ANOMALI, DAN KETERBATASAN BARU

Bahan untuk **3.2.6 Pembahasan** (bekas 3.2.5), **4.1 Kesimpulan** (butir baru),
dan **4.2 Saran**.

---

## 1. Temuan yang layak masuk Pembahasan

### 1.1 Standar yang ditegakkan pada kode pihak ketiga

Draf menutup Bab II dengan kalimat bahwa standarisasi ditegakkan lewat perpaduan
struktur kode, komentar koreksi, tinjauan manual, dan test suite. Seluruhnya
adalah mekanisme yang berlaku bagi **kode yang ditulis sendiri**.

Yang bertambah: standar yang sama kini ditegakkan pada **kode yang datang dari
luar**, secara otomatis, dan **sebelum kode itu dieksekusi sekali pun**. Enam
pemeriksaan struktural dan enam jenis temuan keamanan berlaku pada setiap berkas
setiap paket, dan pelanggarannya ditunjuk sampai ke nomor baris.

**Kalimat yang disarankan:**

> Dengan demikian, klaim standarisasi pada penelitian ini bergeser dari
> deskriptif menjadi ditegakkan. Sebelumnya, keseragaman antar-pipeline
> bergantung pada disiplin satu penulis yang menyusun seluruh pipeline sendiri;
> sekarang, sebuah pipeline yang tidak memenuhi kontrak tidak dapat masuk ke
> platform, terlepas dari siapa yang menulisnya.

### 1.2 Tiga gerbang berurutan sebagai pola rancangan

Layak dibahas sebagai temuan rancangan, bukan sekadar fitur: masing-masing
gerbang menjawab pertanyaan yang **tidak dapat dijawab** gerbang lain.

| Gerbang | Menjawab | Tidak dapat menjawab |
|---|---|---|
| Validasi statis | apakah kode berbentuk benar dan tidak menjangkau yang terlarang | apakah kode benar-benar berjalan |
| Uji coba terkendali | apakah kode berjalan dan menghasilkan sesuatu | apakah kode yang disetujui sama dengan yang diuji |
| Sidik jari paket saat persetujuan | apakah yang disetujui persis yang diuji | apakah kode di disk masih sama saat dijalankan nanti |
| (verifikasi hash saat memuat) | apakah kode di disk masih sama | — |

Keempatnya berurutan dan tidak ada yang dapat dihilangkan tanpa membuka celah
tertentu. Ini pola yang dapat dipakai ulang pada platform sejenis, dan layak
disebut sebagai sumbangan metodologis kecil.

### 1.3 Nilai analitis yang baru muncul

Draf sudah menyebut satu nilai analitis: perbandingan biaya komputasi antar
algoritma pada kondisi identik (SVC 12 jam vs KNN 0,4 menit). Tambahkan satu
lagi:

> Kolom `pipeline_hash` dan `dataset_hash` yang tercatat pada setiap eksperimen
> tidak hanya berfungsi sebagai bukti keterulangan, tetapi juga sebagai alat
> diagnosa. Ketika tiga pipeline kontribusi menghasilkan angka yang mencurigakan
> karena terlalu mirip, ketiga kolom itulah yang memungkinkan penyebabnya
> dipisahkan secara meyakinkan: hash pipeline yang berbeda menutup kemungkinan
> pipeline tertukar, dan hash dataset yang sama menutup kemungkinan data yang
> berbeda, sehingga penyebabnya dapat dilokalisasi pada karakteristik dataset
> fikstur itu sendiri.

### 1.4 Temuan operasional: jalur absolut lintas lingkungan

Ini temuan nyata yang muncul hanya karena sistem dijalankan di **dua lingkungan**
(host Windows dan kontainer Linux) di atas direktori penyimpanan yang sama.

Karena `entry_file` dan jalur dataset disimpan sebagai lintasan absolut, sebuah
pipeline yang berkasnya utuh dilaporkan "bermasalah" di lingkungan yang lain, dan
dataset yang terikat padanya tidak muncul untuk dipilih. Perbaikannya adalah
penambatan ulang saat pembacaan, dengan syarat berkas hasil penambatan
benar-benar ada, dan **tanpa melonggarkan pemeriksaan hash sedikit pun**.

**Kalimat yang disarankan:**

> Temuan ini menegaskan bahwa jaminan reproduksibilitas yang bertumpu pada
> kontainer perlu diuji pada kedua lingkungan yang benar-benar dipakai, bukan
> pada salah satunya saja. Sebuah sistem dapat lulus seluruh pengujian pada satu
> lingkungan dan tetap menampilkan keadaan yang keliru pada lingkungan lain, bila
> yang dicatat adalah lintasan absolut, bukan lintasan relatif terhadap akar
> penyimpanan.

### 1.5 Anomali: paket multi-algoritma belum dapat disunting

Ditemukan pada pengujian lapangan: penyunting versi **menolak** paket yang
memuat lebih dari satu titik masuk, padahal unggahan dan persetujuan
**mendukungnya** (satu paket tiga algoritma terbukti melahirkan tiga baris
registry sekaligus).

Akibatnya, research pipeline kontribusi yang sah dengan beberapa algoritma tidak
dapat diperbaiki lewat penyunting versi; satu-satunya jalan adalah mengunggah
ulang seluruh paket.

**Tulis apa adanya sebagai keterbatasan**, dan masukkan ke Saran. Ini justru
menaikkan kredibilitas, karena ia menunjukkan pengujian lapangannya benar-benar
menemukan sesuatu.

---

## 2. Keterbatasan baru untuk 3.2.6

Draf sudah punya tiga keterbatasan (semantik metrik berbeda; label EVE turunan
Suricata; cakupan EVE terbatas TLS). **Ketiganya tetap.** Tambahkan:

4. **Validasi statis berbasis daftar, bukan isolasi tingkat sistem operasi.**
   Ia menutup jalur yang terbaca dari teks program dan terbukti menolak keenam
   kategori pelanggaran yang diuji, tetapi tidak memberi jaminan yang setara
   dengan sandbox pada tingkat proses atau kontainer per-eksekusi. Untuk
   lingkungan on-premise satu laboratorium dengan kontributor yang identitasnya
   diketahui dan persetujuan manusia sebagai gerbang terakhir, tingkat jaminan
   ini memadai; untuk layanan publik, tidak.
5. **Persetujuan tetap bergantung pada penilaian manusia.** Sistem memastikan
   keputusan diambil di atas bukti yang lengkap dan masih berlaku, tetapi tidak
   menilai mutu metodologis pipeline yang diunggah. Sebuah pipeline yang lolos
   seluruh gerbang tetap dapat mengandung kesalahan metodologis yang hanya dapat
   dikenali pembaca ahli.
6. **Belum ada pemeriksaan anti-kebocoran otomatis pada pipeline kontribusi.**
   Aturan anti-*leakage* ditegakkan pada keenam pipeline HIKARI lewat struktur
   kode dan tinjauan, tetapi platform belum memeriksa apakah pipeline yang
   diunggah menerapkan transformasi hanya pada data latih. Ini keterbatasan yang
   paling berarti dari sudut kontribusi metodologis penelitian, dan layak
   disebut secara eksplisit.
7. **Paket multi-algoritma belum dapat disunting** (lihat pasal 1.5).
8. **Pengujian lapangan dijalankan pada satu rangkaian, satu mesin, dan pada
   mode sinkron**, sehingga jalur worker asinkron pada subsistem kontribusi
   belum teruji langsung.

---

## 3. Yang TIDAK boleh diklaim

Daftar ini penting supaya penulisan tidak melampaui bukti:

| Jangan tulis | Karena |
|---|---|
| "Platform aman menjalankan kode arbitrer dari internet" | validasi statis berbasis daftar; tidak ada sandbox tingkat OS |
| "Sistem mencegah data leakage pada pipeline kontribusi" | belum ada pemeriksaan otomatisnya; yang dicegah adalah leakage pada pipeline bawaan |
| "Sistem mendukung banyak pengguna secara bersamaan" | belum diuji beban maupun konkurensi; SQLite satu berkas, worker terbatas memori |
| "Uji coba menjamin pipeline kontribusi benar" | uji coba menjawab "berjalan atau tidak", bukan "benar secara metodologis" |
| "Seluruh fitur telah diuji" | empat ruas ditandai tidak diuji; jalur worker asinkron belum |

---

## 4. Butir tambahan untuk 4.1 Kesimpulan

Draf punya lima butir. Tambahkan dua, dan sesuaikan butir 1 dan 4 mengikuti
Bagian 2 (K-13, K-1).

**Butir 6 (usulan):**

> Platform diperluas menjadi kerangka kontribusi yang menegakkan standar pada
> kode pihak ketiga. Sebuah research pipeline yang berasal dari luar harus
> melewati tiga gerbang berurutan — pemeriksaan statis tanpa eksekusi, uji coba
> terkendali di bawah batas sumber daya, dan persetujuan yang menuntut sidik jari
> paket masih cocok dengan yang diuji — sebelum terdaftar dan dapat dijalankan.
> Pengujian lapangan atas 38 kasus menunjukkan 37 kasus memenuhi kriteria, dengan
> satu kasus yang tidak terpenuhi karena karakteristik dataset fikstur, bukan
> karena perilaku sistem.

**Butir 7 (usulan):**

> Penambahan subsistem kontribusi terbukti tidak menggeser hasil yang telah
> dilaporkan. Setiap tahap pengembangan ditutup dengan menjalankan ulang satu
> pipeline bawaan dan membandingkan metriknya dengan artefak sebelumnya, dan
> seluruh pemeriksaan menghasilkan selisih nol pada seluruh digit. Dengan
> demikian, sifat reproduksibilitas yang menjadi kontribusi utama penelitian ini
> terjaga justru ketika sistemnya berubah paling banyak.

Butir kedua ini **kuat**, karena ia menjawab keberatan yang paling wajar dari
penguji.

---

## 5. Penyesuaian untuk 4.2 Saran

Saran yang sudah ada (perluasan EVE ke protokol lain, CI, kasus di luar IDS,
migrasi ke cloud) **tetap relevan**. Tambahkan tiga yang lahir dari temuan:

1. **Pemeriksaan anti-kebocoran otomatis pada pipeline kontribusi**, misalnya
   dengan menganalisis urutan pemanggilan `fit` terhadap posisi pemisahan
   latih–uji pada AST. Ini kelanjutan paling langsung dari kontribusi metodologis
   penelitian ini.
2. **Isolasi eksekusi yang lebih kuat**, misalnya menjalankan setiap uji coba di
   dalam kontainer sekali pakai dengan batas sumber daya dan tanpa akses
   jaringan, sehingga jaminannya tidak lagi bertumpu pada daftar larangan
   semata.
3. **Dukungan penyuntingan untuk paket multi-algoritma**, agar research pipeline
   kontribusi yang membawa beberapa algoritma dapat diperbaiki tanpa mengunggah
   ulang seluruh paketnya.

Boleh ditambahkan satu kalimat penutup:

> Ketiga saran tersebut berasal langsung dari keterbatasan yang teridentifikasi
> pada pengujian lapangan, sehingga arah pengembangan lanjutannya tidak bersifat
> spekulatif melainkan tertuju pada celah yang sudah diketahui letaknya.

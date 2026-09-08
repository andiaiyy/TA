# BAGIAN 19/19 — CHECKLIST VERIFIKASI AKHIR

Jalankan checklist ini **setelah** seluruh penulisan selesai, sebelum draf
dikirim ke pembimbing. Setiap butir dapat diperiksa tanpa membuka kode.

---

## A. Konsistensi angka (paling sering salah)

- [ ] Angka test suite **sama** di 2.2.4.6, 2.2.5.4, teks Gambar 14, dan Bab III:
      **3.073 dikumpulkan, 3.071 lulus, 2 dilewati, 0 gagal**.
- [ ] Tangkapan layar pytest (Gambar 14/18) **menampilkan angka yang sama** dengan
      teksnya. Bila belum diambil ulang, beri tanda dan jangan cetak.
- [ ] Kata **"sepuluh pipeline"** selalu disertai kata **"bawaan"**.
- [ ] Jumlah halaman antarmuka disebut **tiga**, konsisten di seluruh dokumen.
- [ ] Memori WSL2 dan batas memori worker konsisten dengan RAM mesin pada 2.1
      (tidak boleh VM lebih besar daripada RAM fisik).
- [ ] Versi pustaka pada 3.2.2 konsisten dengan yang disebut pada 2.2.5.1, dan
      dijelaskan bila host dan kontainer berbeda.
- [ ] Jumlah kunci `get_info()` disebut **enam**, bukan lima.
- [ ] Periode penelitian pada 2.1 mencakup seluruh masa pengembangan.

## B. Kelengkapan koreksi Bagian 2

- [ ] K-1 sampai K-15 sudah dikerjakan seluruhnya, atau yang belum ditandai
      dengan alasan.
- [ ] Tidak ada lagi kalimat "pengguna tunggal" / "satu pengguna" yang
      bertentangan dengan adanya tiga peran.
- [ ] Kalimat "tidak dipublikasikan" tidak lagi bertentangan dengan Lampiran 1.
- [ ] Prinsip *fixed pipeline* pada Tabel 1 sudah direvisi, dan revisinya
      **tidak** menghapus argumen perbandingan terkendali.

## C. Penomoran dan rujukan silang

- [ ] Seluruh tabel bernomor berurutan menurut urutan kemunculan.
- [ ] Seluruh gambar bernomor berurutan menurut urutan kemunculan.
- [ ] **Setiap** tabel dan gambar dirujuk minimal satu kali di dalam teks
      ("sebagaimana ditunjukkan pada Tabel X").
- [ ] Tidak ada rujukan ke nomor tabel/gambar yang sudah berubah.
- [ ] Daftar Tabel, Daftar Gambar, dan Daftar Isi disusun ulang **paling akhir**.
- [ ] Subbab Pembahasan sudah bergeser dari 3.2.5 menjadi 3.2.6 (bila subbab hasil
      baru disisipkan sebagai 3.2.5), dan Daftar Isi mengikutinya.

## D. Kejujuran klaim

- [ ] Kasus C-4 yang **gagal** ditulis apa adanya, tidak disembunyikan, dan
      kriterianya **tidak dilonggarkan**.
- [ ] Empat ruas yang tidak diuji disebutkan.
- [ ] Keterbatasan baru (nomor 4–8 pada Bagian 16) masuk ke Pembahasan.
- [ ] Tidak ada klaim dari tabel "Yang TIDAK boleh diklaim" (Bagian 16 pasal 3).
- [ ] Anomali paket multi-algoritma yang belum dapat disunting disebutkan.
- [ ] Keterbatasan lama (semantik metrik, label EVE, cakupan TLS) **tidak
      dihapus**.

## E. Integritas hasil lama

- [ ] Tabel 12–20 lama (dataset, distribusi kelas, hasil fungsional,
      reproducibility, stabilitas, evaluasi kinerja) **tidak berubah angkanya**.
- [ ] Ada satu kalimat yang menegaskan bahwa penambahan subsistem kontribusi
      terbukti tidak menggeser hasil tersebut (Bagian 14 pasal 4).

## F. Rujukan dan istilah

- [ ] Tidak ada rujukan yang dikarang. Setiap entri baru pada Daftar Pustaka
      benar-benar ada dan sudah dibaca.
- [ ] Setiap penanda `[PERLU_DIUKUR: ...]` dan `[PERLU_DIPASTIKAN PENULIS: ...]`
      sudah diselesaikan atau sengaja dibiarkan untuk ditanyakan ke pembimbing.
- [ ] Istilah asing dimiringkan pada kemunculan pertama.
- [ ] Singkatan baru masuk Daftar Singkatan, dan yang tidak terpakai dibuang.
- [ ] SHA-256 sudah ada di Daftar Singkatan.

## G. Bahasa dan gaya

- [ ] Bahasa Indonesia formal-akademik, konsisten dengan bab yang tidak diubah.
- [ ] Tidak ada kalimat yang menyebut proses pengembangan secara informal
      ("saya menemukan", "ternyata error").
- [ ] Setiap tabel didahului kalimat pengantar, bukan langsung tabel.
- [ ] Tidak ada potongan kode mentah di dalam Bab II selain nama modul, nama
      fungsi, dan nilai konstanta.

## H. Pemeriksaan terakhir sebelum cetak

- [ ] Baca ulang **Abstrak** dan **Kesimpulan** berdampingan — keduanya harus
      menyebut hal yang sama, dengan angka yang sama.
- [ ] Baca ulang **Bab I bagian akhir** dan **Bab IV** — janji yang dibuat di
      awal harus terjawab di akhir.
- [ ] Hitung ulang jumlah halaman Daftar Isi terhadap dokumen final.

---

## Kalau ada waktu tersisa: tiga hal yang paling menaikkan mutu

1. **Gambar alur kontribusi tiga gerbang** (Bagian 17 pasal 4). Satu gambar ini
   menjelaskan seluruh subsistem baru lebih cepat daripada tiga halaman teks.
2. **Lampiran log pengujian lapangan.** Membuat setiap angka Bab III dapat
   ditelusuri, dan itu persis sifat yang menjadi kontribusi penelitian ini.
3. **Satu paragraf pada Pembahasan** yang membandingkan platform ini dengan
   KNIME dan Orange **untuk kemampuan barunya**, bukan hanya untuk eksekusi
   pipeline — yaitu bahwa keduanya tidak menegakkan kontrak metodologis pada alur
   yang dibangun penggunanya. Ini menutup lingkaran dengan Latar Belakang.

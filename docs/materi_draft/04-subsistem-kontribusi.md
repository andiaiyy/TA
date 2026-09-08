# BAGIAN 4/19 — SUBSISTEM KONTRIBUSI: GAMBARAN UMUM & ALUR END-TO-END

Bagian ini memberi bahan untuk: **1.1 Latar Belakang** (2 paragraf tambahan),
**2.2.2 Analisis Kebutuhan** (butir baru), **2.2.3.5 Alur Data** (alur kedua),
dan **2.2.5.2 Tabel 10** (fase pengembangan lanjutan).

---

## 1. Masalah yang dijawab subsistem ini

Draf berhenti pada satu pengamatan: setiap penelitian IDS datang dengan notebook
eksperimennya sendiri, dengan struktur kode, asumsi praproses, dan praktik yang
berbeda-beda, dan tidak jarang menyimpan kesalahan metodologis. Platform
menjawabnya dengan **menyatukan sepuluh pipeline bawaan ke dalam satu kerangka**.

Tetapi jawaban itu hanya berlaku bagi pipeline yang **ditulis sendiri oleh
pengembang platform**. Peneliti lain yang ingin membandingkan pipeline miliknya
pada kondisi yang sama tetap harus menyerahkan kodenya untuk dipasang manual ke
dalam repositori, lalu menunggu pengembang menyuntingnya agar sesuai kontrak.
Selama itu belum ada, klaim "standarisasi" tetap berupa disiplin internal, bukan
kemampuan platform.

Subsistem kontribusi menutup jarak itu: **standar yang sama kini ditegakkan
kepada kode yang datang dari luar**, secara otomatis, sebelum kode itu boleh
dijalankan sekali pun.

**Paragraf untuk 1.1 Latar Belakang (bahan, tulis ulang dengan gayamu):**

> Tantangan berikutnya muncul ketika platform eksperimen hendak dipakai lebih
> dari satu peneliti. Standardisasi pipeline hanya bermakna bila ia juga berlaku
> bagi pipeline yang datang dari luar; bila setiap kontribusi baru harus dipasang
> secara manual ke dalam kode platform, maka jaminan keseragaman kembali
> bergantung pada ketelitian satu orang. Di sisi lain, menerima kode pihak ketiga
> pada sebuah platform eksekusi menimbulkan persoalan keamanan tersendiri, karena
> kode itu akan dijalankan pada mesin yang sama dengan data penelitian yang
> bersifat sensitif.

> Oleh karena itu, penelitian ini memperluas platform dengan subsistem kontribusi
> yang menegakkan standar secara otomatis: kode yang diunggah diperiksa secara
> statis tanpa pernah diimpor maupun dieksekusi, diuji coba di bawah batas sumber
> daya yang ketat, dan baru terdaftar sebagai research pipeline setelah melewati
> persetujuan Research Admin. Dengan demikian, keseragaman pipeline tidak lagi
> bertumpu pada disiplin penulis, melainkan pada gerbang yang tertanam di dalam
> sistem.

---

## 2. Tiga entitas yang harus dibedakan (PENTING untuk ketepatan penulisan)

Draf tidak pernah membedakan ketiganya karena dulu belum ada. Ketiganya
**berbeda tabel dan berbeda makna**, dan mencampurnya membuat Bab II keliru:

| Entitas | Tempat hidup | Artinya | Contoh |
|---|---|---|---|
| **Research pipeline** | kode (bawaan) atau tabel `research_pipelines` (kontribusi) | Satu penelitian beserta identitas, kredit, dan kontrak datasetnya | "Rayyan (2024) — HIKARI2021" |
| **Pipeline terdaftar (versi algoritma)** | tabel `registered_pipelines` | Satu algoritma pada satu versi berkas, dengan hash-nya | `uploaded.deteksi_x_randomforest@v2` |
| **Pengajuan (submission)** | tabel `submissions` | Satu berkas/paket yang sedang menunggu ditinjau | `#7 pending` |

Satu research pipeline dapat memuat **beberapa** algoritma; satu algoritma dapat
punya **beberapa** versi; satu pengajuan dapat melahirkan **beberapa** baris
registry sekaligus.

---

## 3. Alur end-to-end (bahan untuk gambar baru, lihat Bagian 17)

```
KONTRIBUTOR                         RESEARCH ADMIN                 SISTEM
     |                                    |                          |
 (1) unggah paket .py + metadata          |                          |
     |----------------------------------->|                          |
     |                              [GERBANG 1]                      |
     |                       validasi statis (AST)  <----------------|
     |                       tanpa impor, tanpa eksekusi             |
     |                                    |                          |
     |                       gagal -> pengajuan tidak dapat lanjut   |
     |                       lulus -> masuk antrean tinjauan         |
     |                                    |                          |
 (2) lampirkan dataset uji coba           |                          |
     |----------------------------------->|                          |
     |                              [GERBANG 2]                      |
     |                       uji coba (trial) di proses terpisah     |
     |                       batas 300 detik / 50.000 baris          |
     |                                    |                          |
     |                       gagal -> tidak dapat disetujui          |
     |                       lulus -> sidik jari paket dicatat       |
     |                                    |                          |
     |                              [GERBANG 3]                      |
     |                       persetujuan: hanya Research Admin,      |
     |                       hanya bila sidik jari masih cocok       |
     |                                    |                          |
     |                                    |---> berkas dipindah ke   |
     |                                    |     area approved        |
     |                                    |---> baris registry per   |
     |                                    |     algoritma (v1)       |
     |                                    |---> identitas research   |
     |                                    |     + dataset terikat    |
     |                                    |                          |
 (3) research pipeline muncul di halaman Jalankan Eksperimen         |
     dan dapat dijalankan siapa pun, seperti pipeline bawaan         |
```

**Empat sifat yang dijaga sepanjang alur, dan layak ditulis sebagai klaim:**

1. **Kode kontributor tidak pernah dieksekusi sebelum lulus Gerbang 1.**
   Validasi memakai `ast.parse`, bukan `import` — dibuktikan empiris pada
   Bagian 15 (kasus KTR-V-05).
2. **Uji coba tidak menyentuh basis data penelitian.** Artefak dan barisnya
   terpisah (`pipeline_trials`, `storage/trials/`), dan jumlah baris
   `experiments` terbukti tidak berubah sepanjang rangkaian uji coba.
3. **Persetujuan tidak dapat dilakukan dari tampilan.** Izin diperiksa di dalam
   fungsi layanan (`require_approve`), sehingga menyembunyikan tombol tidak
   pernah menjadi satu-satunya penghalang.
4. **Setiap penyuntingan menambah versi, tidak pernah menimpa.** Versi lama tetap
   ada di disk beserta hash-nya, sehingga eksperimen lama tetap dapat ditelusuri.

---

## 4. Ruang penyimpanan yang dipakai

| Direktori | Isi |
|---|---|
| storage/datasets/ | dataset platform (HIKARI2021, EVE) — tidak berubah |
| storage/artifacts/ | artefak eksperimen resmi — tidak berubah |
| storage/uploaded_pipelines/pending/ | paket yang menunggu ditinjau |
| storage/uploaded_pipelines/approved/ | paket yang telah disetujui |
| storage/uploaded_pipelines/rejected/ | paket yang ditolak (tidak dihapus) |
| storage/uploaded_pipelines/versions/ | versi hasil penyuntingan |
| storage/uploaded_pipelines/trial_datasets/ | dataset lampiran milik paket |
| storage/trials/ | artefak uji coba (dibersihkan setelah keputusan) |

**Prinsip yang layak ditulis:** berkas yang ditolak **tidak dihapus**, hanya
berpindah status. Penghapusan hanya terjadi pada artefak uji coba, dan itu pun
setelah keputusan diambil.

---

## 5. Kebutuhan sistem tambahan (untuk 2.2.2)

**Kebutuhan fungsional tambahan (lanjutkan penomoran draf yang berhenti di 6):**

7. Menerima unggahan berkas pipeline dan dataset dari pengguna berperan
   kontributor, beserta metadata penelitiannya.
8. Memeriksa kode yang diunggah secara statis terhadap kontrak struktural dan
   aturan keamanan, tanpa mengimpor maupun mengeksekusi kode tersebut.
9. Menjalankan uji coba terkendali atas paket yang lulus pemeriksaan statis, di
   bawah batas waktu dan batas ukuran data yang ditetapkan.
10. Menyediakan alur peninjauan dan persetujuan bagi Research Admin, beserta
    catatan alasannya.
11. Mendaftarkan pipeline yang disetujui ke registry dinamis sehingga langsung
    dapat dipilih pada halaman eksekusi, tanpa perubahan kode.
12. Menyimpan riwayat versi setiap pipeline kontribusi beserta hash berkasnya,
    dan memungkinkan penonaktifan tanpa menghapus.
13. Mengelola akun pengguna beserta perannya.

**Kebutuhan non-fungsional tambahan (draf berhenti di 5):**

6. Keamanan eksekusi: kode pihak ketiga tidak boleh dijalankan sebelum lolos
   pemeriksaan statis, dan tidak boleh memperoleh akses ke sistem berkas,
   jaringan, maupun proses lain.
7. Otorisasi berlapis: setiap aksi yang mengubah keadaan sistem diperiksa pada
   lapisan layanan, bukan hanya disembunyikan pada antarmuka.
8. Ketertelusuran kontribusi: setiap eksperimen yang memakai pipeline kontribusi
   harus dapat ditelusuri ke versi dan hash berkas yang benar-benar dijalankan.

---

## 6. Fase pengembangan lanjutan (untuk Tabel 10)

Draf berhenti di **Phase 11 (Pipeline EVE)**. Tambahkan baris berikut. Nama fase
bebas disesuaikan; yang penting hasil utamanya benar.

| Fase | Hasil utama |
|---|---|
| Phase 12 | Autentikasi dan peran (users, PBKDF2, tiga peran, layar masuk) |
| Phase 13 | Unggah pipeline dan dataset (area staging, sanitasi nama berkas, batas ukuran) |
| Phase 14 | Validator statis berbasis AST beserta laporan per-berkas dua kelompok cek |
| Phase 15 | Uji coba terkendali (proses terpisah, batas waktu dan baris, artefak terpisah) |
| Phase 16 | Registry dinamis, versioning, penonaktifan, dan penyunting versi |
| Phase 17 | Identitas research pipeline kontribusi dan dataset terikat |
| Phase 18 | Dua mode eksekusi (resmi/eksplorasi) beserta parameter terlindungi |
| Phase 19 | Dwibahasa (1.309 kunci) dan penyeragaman sistem desain antarmuka |
| Phase 20 | Pengujian lapangan subsistem kontribusi (38 kasus) |

**[PERLU_DIPASTIKAN PENULIS: apakah urutan fase ini sesuai urutan kerja
sebenarnya; bila tidak, susun ulang.]**

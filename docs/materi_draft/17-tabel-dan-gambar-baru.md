# BAGIAN 17/19 — SPESIFIKASI TABEL & GAMBAR BARU + RENCANA PENOMORAN

Draf sekarang berakhir pada **Tabel 20** dan **Gambar 14**. Bagian ini memberi
rencana penomoran yang sudah dihitung, agar kamu tidak perlu menomori sendiri.

---

## 1. Aturan penomoran

Tabel dan gambar dinomori **menurut urutan kemunculan di dokumen**, bukan menurut
urutan pembuatan. Karena sebagian tabel baru disisipkan **di tengah** Bab II,
seluruh nomor sesudahnya bergeser.

**Dua pilihan, pilih satu dan konsisten:**

- **Pilihan A (disarankan):** nomori ulang seluruhnya menurut urutan kemunculan.
  Lebih rapi, tetapi seluruh rujukan silang di dalam teks harus disesuaikan.
- **Pilihan B:** letakkan seluruh tabel baru **sesudah** Tabel 20 dan
  gambar baru sesudah Gambar 14, meski letak fisiknya di Bab II. Tidak lazim dan
  membingungkan pembaca; hanya pakai bila waktu sangat terbatas.

Materi di bawah memakai **Pilihan A**.

---

## 2. Rencana penomoran tabel (Pilihan A)

| Nomor baru | Judul | Nomor lama | Letak |
|---|---|---|---|
| 1 | Lima prinsip perancangan dan kontribusinya terhadap tujuan sistem | 1 | 2.2.3.1 |
| 2 | Muatan kontrak data antara orchestrator dan pipeline | 2 | 2.2.3.1 |
| 3 | Service inti eksekusi pada layer Orchestrator | 3 (dipecah) | 2.2.3.2 |
| **4** | **Modul subsistem kontribusi dan lintas fungsi pada layer Orchestrator** | **baru** | 2.2.3.2 |
| 5 | Aturan ketergantungan antarlayer | 4 | 2.2.3.3 |
| 6 | Stack teknologi yang digunakan beserta justifikasi pemilihannya | 5 | 2.2.3.4 |
| 7 | Tiga layanan dalam Docker Compose | 6 | 2.2.3.7 |
| **8** | **Perbandingan run resmi dan run eksplorasi** | **baru** | 2.2.3.8 |
| **9** | **Parameter yang tidak dapat disesuaikan beserta alasannya** | **baru** | 2.2.3.8 |
| 10 | Pipeline bawaan yang terdaftar pada registry | 7 | 2.2.4.1 |
| 11 | Penerapan transformasi anti-leakage pada pipeline HIKARI | 8 | 2.2.4.2 |
| 12 | Tujuh fase pipeline yang distandarkan | 9 | 2.2.4.3 |
| **13** | **Pemeriksaan struktural pada kode kontributor** | **baru** | 2.2.4.7 |
| **14** | **Jenis temuan keamanan pada kode kontributor** | **baru** | 2.2.4.7 |
| **15** | **Batas sumber daya uji coba** | **baru** | 2.2.4.7 |
| **16** | **Penghalang persetujuan beserta artinya** | **baru** | 2.2.4.7 |
| **17** | **Peran pengguna dan kewenangannya** | **baru** | 2.2.4.8 |
| **18** | **Tabel basis data beserta penulisnya** | **baru** | 2.2.3.2 atau subbab skema |
| **19** | **Ringkasan 31 migrasi skema** | **baru** | subbab skema |
| 20 | Fase pengembangan sistem dan hasil setiap fase | 10 | 2.2.5.2 |
| 21 | Rancangan pengujian dan kriteria keberhasilan sistem | 11 (diperluas) | 2.2.6 |
| 22 | Karakteristik dataset yang digunakan | 12 | 3.1 |
| 23 | Distribusi kelas pada tiap dataset | 13 | 3.1 |
| **24** | **Berkas fikstur pengujian subsistem kontribusi** | **baru** | 3.1 |
| 25 | Hasil pengujian fungsional | 14 | 3.2.1 |
| 26 | Rincian eksekusi tiap pipeline | 15 | 3.2.1 |
| 27 | Hasil pengujian reproducibility | 16 | 3.2.2 |
| 28 | Bukti reproducibility pipeline HIKARI2021 | 17 | 3.2.2 |
| 29 | Bukti reproducibility pipeline EVE Suricata | 18 | 3.2.2 |
| 30 | Hasil pengujian stabilitas | 19 | 3.2.3 |
| 31 | Hasil evaluasi kinerja pipeline | 20 | 3.2.4 |
| **32** | **Rekapitulasi hasil pengujian subsistem kontribusi** | **baru** | 3.2.5 |
| **33** | **Ketepatan deteksi pelanggaran beserta nomor baris** | **baru** | 3.2.5 |
| **34** | **Hasil uji coba tiga pipeline kontribusi** | **baru** | 3.2.5 |
| **35** | **Bukti reproducibility pipeline kontribusi** | **baru** | 3.2.5 |
| **36** | **Hasil pengujian otorisasi peran** | **baru** | 3.2.5 |

Total menjadi **36 tabel** (dari 20). Bila terlalu banyak, gabungkan Tabel 13
dan 14 menjadi satu, serta Tabel 18 dan 19 menjadi satu.

---

## 3. Rencana penomoran gambar (Pilihan A)

| Nomor baru | Judul | Nomor lama | Catatan |
|---|---|---|---|
| 1–6 | (landasan teori) | 1–6 | tidak berubah |
| 7 | Layered architecture sistem | 7 | **perlu diperbarui** — tambahkan kotak modul baru |
| 8 | Diagram alur pengguna eksekusi eksperimen | 8 | tidak berubah |
| **9** | **Diagram alur kontribusi: tiga gerbang berurutan** | **baru** | spesifikasi di pasal 4 |
| 10 | Arsitektur sistem: tiga kontainer Docker | 9 | tidak berubah |
| 11 | Tujuh fase prosedural | 10 | tidak berubah |
| 12 | Lima lapis pertahanan anti-leakage EVE | 11 | tidak berubah |
| **13** | **Skema basis data dan relasinya** | **baru** | opsional tetapi sangat membantu |
| 14 | Halaman Run Experiment | 12 | **ambil ulang** |
| 15 | Halaman Progress & Status | 13 | **ambil ulang** |
| **16** | **Halaman Tambah Pipeline & Dataset** | **baru** | tangkapan layar |
| **17** | **Laporan validasi statis dengan nomor baris** | **baru** | tangkapan layar |
| 18 | Hasil eksekusi test suite (pytest) | 14 | **wajib ambil ulang** |

---

## 4. Spesifikasi Gambar baru "Alur kontribusi: tiga gerbang"

Bentuk yang disarankan: alur mendatar dengan tiga gerbang sebagai palang, mirip
gaya Gambar 11 (lima lapis pertahanan) yang sudah ada, agar konsisten.

**Isi tiap gerbang:**

```
[UNGGAH]                paket .py + metadata + dataset lampiran
    |
=== GERBANG 1: VALIDASI STATIS ===
    ast.parse, tanpa import, tanpa eksekusi
    Struktur: 6 cek   |   Keamanan: 6 jenis temuan
    27 modul diizinkan | 25 dilarang | 9 pemanggilan dilarang
    -> gagal: pengajuan tidak dapat lanjut
    |
=== GERBANG 2: UJI COBA TERKENDALI ===
    proses terpisah | 300 detik | 50.000 baris | 25 MB
    artefak di storage/trials, tabel pipeline_trials
    -> gagal: tidak dapat disetujui
    |
=== GERBANG 3: PERSETUJUAN ===
    hanya Research Admin (ditegakkan di layanan)
    sidik jari paket harus masih cocok dengan yang diuji
    -> lulus: berkas pindah ke approved,
              baris registry per algoritma (v1 + hash),
              identitas research + dataset terikat
    |
[TERDAFTAR]  muncul di katalog, dapat dijalankan siapa pun
    |
=== PENGAMAN LANJUTAN ===
    verifikasi hash SHA-256 pada SETIAP pemuatan
    penyuntingan selalu menambah versi, tidak pernah menimpa
```

Tambahkan satu kotak catatan di bawah, gaya yang sama dengan Gambar 11:

> Kode kontributor tidak pernah dieksekusi sebelum Gerbang 1 terlewati.
> Terverifikasi: penanda tingkat modul tidak terbentuk sesudah validasi.

---

## 5. Perubahan pada Gambar 7 (layered architecture)

Tidak perlu digambar ulang seluruhnya. Cukup:

- **Lapisan UI:** ubah "Run Experiment | Experiment History | Environment Info"
  menjadi tiga halaman yang sebenarnya, dan tambahkan penanda layar masuk.
- **Lapisan Orchestration:** tambahkan kotak kedua berisi modul subsistem
  kontribusi (submission, validator, trial, registry, versions, research, auth,
  run_mode).
- **Lapisan Storage:** ubah "SQLite (experiment metadata)" menjadi
  "SQLite (6 tabel: eksperimen, pengguna, pengajuan, uji coba, registry, research)".
- **Catatan kaki gambar:** tambahkan pengecualian keempat pada aturan impor.

---

## 6. Daftar Tabel dan Daftar Gambar

Keduanya harus disusun ulang mengikuti penomoran di atas, lengkap dengan nomor
halaman yang baru. Kerjakan **paling akhir**, sesudah seluruh teks selesai,
karena nomor halamannya baru pasti setelah itu.

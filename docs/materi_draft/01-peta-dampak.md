# BAGIAN 1/19 — RINGKASAN PERUBAHAN & PETA DAMPAK

## 1. Apa yang berubah, dalam satu paragraf

Draf menggambarkan platform sebagai **alat eksekusi tertutup**: sepuluh
pipeline yang dikunci di dalam kode, dua halaman antarmuka, satu pengguna,
tanpa akun. Sistem sekarang adalah **platform kontribusi**: peneliti lain dapat
mengunggah research pipeline beserta datasetnya, kodenya diperiksa secara
statis tanpa pernah dieksekusi, diuji coba di bawah batas sumber daya,
disetujui oleh Research Admin, lalu terdaftar sebagai research pipeline
tersendiri yang dapat dijalankan siapa pun lewat antarmuka yang sama —
dengan versi, hash, dan riwayatnya tercatat. Ditambah: tiga peran pengguna,
dua mode eksekusi (resmi/eksplorasi), antarmuka dwibahasa, dan test suite yang
tumbuh dari 227 menjadi 3.073 pengujian.

**Kontribusi ilmiah yang bertambah:** platform tidak lagi hanya membuktikan
*reproducibility* untuk pipeline milik sendiri, tetapi menjadi **kerangka yang
memaksa pipeline pihak ketiga masuk ke standar yang sama** — struktural,
metodologis, dan prosedural — sebelum boleh dijalankan. Inilah yang membuat
klaim "standarisasi" pada draf naik dari deskriptif menjadi *enforced*.

## 2. Peta dampak per subbab draf

Legenda: **[T]** tambah baru · **[R]** revisi isi · **[K]** koreksi fakta ·
**[—]** tidak berubah.

| Subbab draf | Aksi | Sumber materi |
|---|---|---|
| ABSTRAK & ABSTRACT | **[R]** | Bagian 18 |
| 1.1 Latar Belakang | **[T]** 2 paragraf | Bagian 4 |
| 1.2 Landasan Teori | **[T]** 1.2.8 baru | Bagian 5 |
| 1.3 Rumusan Masalah | **[R]** | Bagian 18 |
| 1.4.1 Tujuan | **[R]** | Bagian 18 |
| 1.4.2 Manfaat | **[T]** 2 butir | Bagian 18 |
| 1.5 Ruang Lingkup | **[T]** 2 butir | Bagian 18 |
| 2.1 Lokasi & Waktu | **[K]** spesifikasi mesin | Bagian 2 butir K-8 |
| 2.2.2 Analisis Kebutuhan | **[T]** fungsional 7–13, non-fungsional 6–8 | Bagian 4 §5 |
| 2.2.3 Perancangan Arsitektur | **[R]** paragraf pembuka | Bagian 13 |
| 2.2.3.1 Prinsip Perancangan | **[R] PENTING** — prinsip *fixed pipeline* | Bagian 10 |
| 2.2.3.2 Layered Architecture | **[R]** Tabel 3 (5 → 19 modul), halaman 2 → 3 | Bagian 13 |
| 2.2.3.3 Aturan Ketergantungan | **[R]** Tabel 4 + pengecualian baru | Bagian 13 §3 |
| 2.2.3.4 Stack Teknologi | **[R]** Tabel 5 + 3 baris baru | Bagian 13 §4 |
| 2.2.3.5 Alur Data Eksekusi | **[T]** alur kontribusi (Gambar baru) | Bagian 4 §3 |
| 2.2.3.6 Mode Sinkron/Asinkron | **[K]** jangan tertukar dengan run_mode | Bagian 10 §1 |
| 2.2.3.7 Arsitektur Deployment | **[K]** memori WSL2 | Bagian 2 butir K-7 |
| 2.2.4 Standarisasi Pipeline | **[R]** paragraf pembuka: standar kini ditegakkan pada kode pihak ketiga | Bagian 5 |
| 2.2.4.1 Standarisasi Struktural | **[T]** kontrak yang sama dipaksakan ke kontributor | Bagian 5 §2 |
| 2.2.4.2 Standarisasi Metodologis | **[—]** (tiga kasus leakage tetap) | — |
| 2.2.4.3 Tujuh Fase | **[—]** | — |
| 2.2.4.4 Penerapan per Dataset | **[T]** dataset kontribusi terikat | Bagian 8 §4 |
| 2.2.4.5 Metrik Tambahan | **[—]** | — |
| 2.2.4.6 Verifikasi Test Suite | **[K] PENTING** 227 → 3.073 | Bagian 14 |
| **2.2.4.7 (BARU)** Standarisasi bagi pipeline kontribusi | **[T]** | Bagian 5–7 |
| 2.2.5.1 Lingkungan & Dependensi | **[R]** | Bagian 13 §4 |
| 2.2.5.2 Pengembangan Bertahap | **[T]** Tabel 10 + fase 12–19 | Bagian 4 §6 |
| 2.2.5.3 Struktur Direktori | **[R]** ukuran & modul baru | Bagian 3 §6 |
| 2.2.5.4 Kesiapan Sistem | **[K]** angka test suite | Bagian 14 |
| 2.2.6 Pengujian & Evaluasi | **[R]** Tabel 11 + 7 kategori uji baru | Bagian 15 §1 |
| 3.1 Data | **[T]** dataset fikstur uji lapangan | Bagian 15 §3 |
| 3.2.1–3.2.4 Hasil lama | **[—]** | — |
| **3.2.5 (BARU)** Hasil pengujian subsistem kontribusi | **[T] BESAR** | Bagian 15 |
| 3.2.5 Pembahasan (menjadi 3.2.6) | **[R]** | Bagian 16 |
| 4.1 Kesimpulan | **[T]** butir 6–7 | Bagian 16 §4 |
| 4.2 Saran | **[R]** | Bagian 16 §5 |
| DAFTAR PUSTAKA | **[T]** 1–2 rujukan | Bagian 18 §4 |
| DAFTAR SINGKATAN | **[T]** 8 singkatan | Bagian 18 §3 |
| DAFTAR TABEL / GAMBAR | **[R]** | Bagian 17 |

## 3. Prioritas kalau waktu terbatas

Kalau tidak semuanya sempat dikerjakan, urutan kepentingannya:

1. **Bagian 2** (kontradiksi) — draf saat ini memuat pernyataan yang dapat
   dibantah penguji dengan membuka aplikasinya. Ini wajib.
2. **Bagian 15** (Bab III baru) — bukti empiris subsistem baru; tanpa ini
   penambahan sistem tidak punya dasar hasil.
3. **Bagian 10** (prinsip *fixed pipeline*) — satu prinsip perancangan inti
   pada Tabel 1 sudah tidak akurat.
4. **Bagian 5–7** (subsistem kontribusi di Bab II) — metodologinya.
5. Sisanya.

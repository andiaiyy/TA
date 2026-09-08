# BAGIAN 12/19 — BASIS DATA: SKEMA DAN 31 MIGRASI

Bahan untuk **2.2.3.2 Layer Storage** (perluasan), **subbab baru** tentang skema,
dan tabel baru. Memperbaiki **K-5** dan **K-6** pada Bagian 2.

---

## 1. Enam tabel aplikasi (bahan tabel baru)

| Tabel | Kolom | Isi | Ditulis oleh |
|---|---:|---|---|
| `experiments` | 23 | satu baris per eksekusi eksperimen | experiment_service (pembuatan), worker (pembaruan status) |
| `users` | 11 | akun, peran, status, kata sandi ber-hash | auth_service |
| `submissions` | 16 | pengajuan unggahan beserta hasil validasi, uji coba, dan lampiran | submission_service |
| `pipeline_trials` | 16 | catatan uji coba sebelum persetujuan; dibersihkan setelah keputusan | trial_service |
| `registered_pipelines` | 19 | satu baris per algoritma per versi, beserta hash dan riwayat suntingan | dynamic_registry, pipeline_versions |
| `research_pipelines` | 10 | identitas research pipeline kontribusi, skema, atribusi, dataset terikat | research_registry |

Ditambah `_schema_version` sebagai catatan migrasi yang sudah diterapkan.

**Prinsip penulisan yang tetap berlaku dari draf:** pembuatan record eksperimen
terpusat pada satu service, dan artefak besar tetap di luar basis data. Yang
bertambah: tabel-tabel di atas punya penulis tunggalnya masing-masing, sehingga
pembagian tanggung jawab tetap terdefinisi meski jumlah tabel bertambah.

---

## 2. Kolom `experiments` yang belum disebut draf (perbaikan K-5)

Draf menyebut "pengenal eksperimen, jenis dan jalur dataset, nilai hash dataset,
pengenal pipeline, status, penanda waktu, empat metrik utama, dan jalur artefak".
Enam kolom berikut belum disebut, dan seluruhnya berkaitan langsung dengan klaim
ketertelusuran:

| Kolom | Fungsi |
|---|---|
| `owner` | pemilik eksperimen; kosong untuk mode pengunjung |
| `pipeline_version` | nomor versi pipeline kontribusi yang dipakai |
| `pipeline_hash` | SHA-256 berkas pipeline yang benar-benar dijalankan |
| `run_mode` | `official` atau `exploration` |
| `params_used` | nilai parameter yang benar-benar dipakai (JSON) |
| `params_changed` | jumlah parameter yang berbeda dari nilai terkunci |

**Kalimat yang layak, dan cukup kuat untuk Bab IV:**

> Dengan `dataset_hash` di satu sisi dan `pipeline_hash` beserta
> `pipeline_version` di sisi lain, setiap baris eksperimen menyimpan sidik jari
> **data masukan** sekaligus **kode yang memprosesnya**. Ditambah `run_mode` dan
> `params_used`, sebuah hasil dapat ditelusuri sampai ke berkas dan konfigurasi
> yang persis dipakai, bukan sekadar ke nama pipeline-nya.

---

## 3. Migrasi: 31 langkah, seluruhnya aditif

Skema tidak pernah dibangun ulang; ia tumbuh lewat migrasi bernomor yang
diterapkan berurutan dan dicatat pada `_schema_version`. **Tidak satu pun
migrasi menghapus kolom atau tabel**, sehingga basis data lama selalu dapat
dinaikkan tanpa kehilangan data.

| # | Isi |
|---|---|
| 1–2 | tabel `experiments`; kolom `task_id` untuk Celery |
| 3–5 | tabel `users`; kolom `owner`; penyeragaman nama peran lama |
| 6–7 | tabel `submissions`; tabel `registered_pipelines` |
| 8–9 | `pipeline_version` dan `pipeline_hash` pada `experiments` |
| 10–15 | status akun, metadata pendaftaran mandiri, dan jejak persetujuan akun |
| 16–18 | `run_mode`, `params_used`, `params_changed` pada `experiments` |
| 19–21 | jejak penyuntingan versi (`edited_by`, `edited_at`, `change_note`) |
| 22 | penyesuaian akun kontributor lama |
| 23–25 | tabel `pipeline_trials`; jejak uji coba dan dataset lampiran pada `submissions` |
| 26–27 | tabel `research_pipelines`; dataset yang terikat padanya |
| 28–29 | `stages_json` dan `info_json` pada `registered_pipelines` |
| 30–31 | `updated_at` dan `updated_by` pada `research_pipelines` |

Daftar lengkap satu-per-satu tersedia bila diperlukan; tabel ringkas di atas
sudah cukup untuk Bab II.

**Dua sifat yang layak ditulis sebagai keputusan rancangan:**

1. **Setiap migrasi ditambahkan pada dua jalur sekaligus** — daftar migrasi
   (untuk basis data yang sudah ada) dan pernyataan pembuatan tabel (untuk basis
   data baru). Bila hanya salah satu yang diperbarui, basis data baru dan basis
   data lama akan berakhir dengan skema yang berbeda — kesalahan yang pernah
   terjadi selama pengembangan dan kini dijaga oleh pengujian otomatis pada
   kedua jalur.
2. **Mundur-kompatibel.** Seluruh kolom baru bersifat *nullable*: baris yang
   lahir sebelum kolomnya ada memang tidak punya nilai, dan itu keadaan yang sah,
   bukan isian yang terlewat.

**Catatan jujur yang perlu masuk:** basis data penelitian yang dipakai
melaporkan hasil Bab III saat ini berada pada **versi skema 29**; migrasi 30 dan
31 belum diterapkan padanya karena keduanya hanya menyangkut fasilitas
pengelolaan metadata, bukan eksekusi maupun hasil. **[PERLU_DIPASTIKAN PENULIS:
apakah migrasi 30–31 akan diterapkan sebelum sidang; bila ya, hapus catatan ini.]**

---

## 4. Mode WAL dan penulis yang terdefinisi

Bagian ini sudah ada di draf dan **tetap benar**; yang perlu ditambahkan hanyalah
bahwa pola yang sama kini berlaku untuk enam tabel, bukan satu. Penanganan galat
"database is locked" lewat mekanisme percobaan ulang juga tetap berlaku.

---

## 5. Catatan metodologis untuk pengujian

Satu praktik yang layak disebut pada 2.2.6 atau Bagian 15: **seluruh pengujian
otomatis dijalankan terhadap salinan basis data**, tidak pernah terhadap basis
data penelitian. Alasannya, angka pada Bab III berasal dari berkas itu dan tidak
dapat dibuat ulang tanpa mengulang eksekusi berjam-jam. Pengujian mengarahkan
variabel `DB_PATH` ke salinan, dan pengujian yang membutuhkan penyimpanan
mengarahkan akar penyimpanannya ke direktori sementara.

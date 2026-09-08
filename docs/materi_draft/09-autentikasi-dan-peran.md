# BAGIAN 9/19 — AUTENTIKASI DAN OTORISASI PERAN

Bahan untuk **subbab baru pada 2.2.3 atau 2.2.4**, **2.2.2 kebutuhan
non-fungsional**, dan koreksi **K-14** (klaim "satu pengguna").

---

## 1. Mengapa peran diperlukan (argumen untuk Bab II)

Begitu platform menerima kode dari luar, pertanyaan "siapa boleh melakukan apa"
berubah dari urusan kenyamanan menjadi urusan keamanan. Mengunggah kode yang akan
dieksekusi mesin, dan **menyetujui** kode itu untuk dijalankan orang lain, adalah
dua kewenangan yang berbeda tingkatannya dan tidak boleh dipegang oleh peran yang
sama tanpa pembedaan.

Karena itu platform membedakan tiga peran, dengan prinsip **hak paling kecil**:
setiap peran hanya memperoleh kewenangan yang benar-benar dibutuhkan perannya.

---

## 2. Tiga peran dan kewenangannya (bahan tabel baru)

| Aksi | Visitor (tanpa akun) | Kontributor | Research Admin |
|---|:---:|:---:|:---:|
| Melihat dan menjalankan eksperimen | ya | ya | ya |
| Mengunggah dataset atau pipeline | tidak | ya | ya |
| Menyetujui/menolak unggahan | tidak | tidak | ya |
| Menjalankan uji coba | tidak | tidak | ya |
| Menyunting versi pipeline | tidak | tidak | ya |
| Mengaktifkan/menonaktifkan pipeline | tidak | tidak | ya |
| Mengelola akun pengguna | tidak | tidak | ya |

Baris pertama disengaja: **menjalankan eksperimen tidak menuntut akun sama
sekali**. Platform ini dibangun untuk dibaca dan dipakai peninjau, dan menuntut
pendaftaran hanya untuk melihat hasil justru menghalangi tujuan itu. Yang
menuntut akun hanyalah tindakan yang **menambah atau mengubah** isi platform.

Terbukti pada kasus **KTR-F** (Bagian 15): matriks izin terukur persis seperti
tabel di atas.

---

## 3. Penegakan berlapis: tampilan bukan penghalang

Prinsip yang layak ditulis sebagai klaim metodologis:

> Menyembunyikan tombol tidak pernah menjadi satu-satunya penghalang.

Setiap aksi yang mengubah keadaan diperiksa **dua kali**: sekali di antarmuka
(untuk tidak menawarkan hal yang akan ditolak) dan sekali lagi **di dalam fungsi
layanan** lewat `require_upload`, `require_approve`, atau `require_manage_users`,
yang melempar galat bila izin tidak terpenuhi.

Terbukti pada kasus **KTR-A-01**: fungsi `submit_pipeline()` dan
`approve_submission()` dipanggil **langsung**, melewati seluruh lapisan
antarmuka, dengan identitas berperan rendah — keduanya tetap menolak dengan
`PermissionDenied`.

Terbukti pula pada **KTR-A-02**: peran yang tidak dikenal diperlakukan sebagai
**hak paling rendah**, bukan sebagai kontributor. Ini penting karena kesalahan
data pada kolom `role` tidak boleh berubah menjadi kenaikan hak.

---

## 4. Penyimpanan kata sandi

| Ruas | Nilai |
|---|---|
| Algoritma | PBKDF2-HMAC-SHA256 |
| Iterasi | 260.000 |
| Panjang salt | 16 byte (acak per pengguna) |
| Format simpanan | `pbkdf2_sha256$<iterasi>$<salt_hex>$<hash_hex>` |
| Pustaka | `hashlib` dari pustaka standar Python |

**Justifikasi yang jujur dan layak ditulis:** bcrypt atau Argon2 umumnya lebih
disarankan untuk kata sandi, tetapi keduanya menuntut dependensi baru, sedangkan
salah satu kriteria pemilihan teknologi pada penelitian ini adalah membawa
dependensi seminimal mungkin demi reproduksibilitas jangka panjang.
PBKDF2-HMAC-SHA256 tersedia di pustaka standar, dan dengan 260.000 iterasi ia
memadai untuk ancaman yang relevan pada lingkungan on-premise satu laboratorium.
Format simpanannya menyertakan jumlah iterasi, sehingga migrasi ke algoritma lain
di kemudian hari tidak memerlukan pengaturan ulang kata sandi seluruh pengguna.

**Sifat lain yang layak disebut:** akun Research Admin pertama dibuat dari
variabel lingkungan secara **idempoten** — bila akun dengan nama itu sudah ada,
kata sandinya tidak pernah ditimpa; bila variabelnya tidak diset, tidak ada akun
yang dibuat sama sekali. Tidak ada kata sandi bawaan yang tertanam di kode.

---

## 5. Status akun

Tiga status: `active`, `pending`, `disabled`. Status `pending` mendukung alur
pendaftaran yang menunggu persetujuan Research Admin, sehingga penambahan
kontributor tetap merupakan keputusan manusia.

---

## 6. Dampak pada draf yang harus diperbaiki

Lihat **K-14** pada Bagian 2: kalimat "menyasar lingkungan penelitian satu
pengguna" dan "target pengguna tunggal" sudah tidak akurat.

**Kalimat pengganti yang disarankan untuk 2.2.3.4 (justifikasi SQLite):**

> SQLite dipilih daripada PostgreSQL atau MySQL karena skala datanya, bukan
> karena jumlah penggunanya. Platform memang mendukung beberapa pengguna dengan
> peran berbeda dalam satu instans, tetapi seluruhnya berbagi satu basis data
> pada satu mesin laboratorium, dengan jumlah baris pada tabel eksperimen yang
> diperkirakan bertahan di orde ribuan. Pada skala itu, basis data berbasis server
> menambah kerumitan tanpa manfaat yang sepadan, sementara mode Write-Ahead
> Logging sudah mencukupi untuk pembacaan yang berlangsung bersamaan dengan
> penulisan.

**Kalimat pengganti untuk 2.2.3.7 (arsitektur tiga layanan):**

> Arsitektur tiga layanan ini sengaja dibuat sederhana karena menyasar satu
> instans laboratorium dengan sejumlah kecil pengguna, bukan layanan publik
> multi-penyewa. Komponen tambahan seperti basis data terpisah, object storage,
> atau load balancer dapat ditambahkan bila kelak platform dikembangkan ke arah
> itu.

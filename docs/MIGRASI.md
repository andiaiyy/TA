# Checklist migrasi ke mesin server

Dibuat setelah latihan cadangan-dan-pulih pada 2026-09-21. Setiap perintah di
bawah **sudah dijalankan** di mesin pengembangan; yang belum diuji ditandai
dengan **[BELUM DIUJI]** supaya Anda tahu di mana harus lebih berhati-hati.

Urutannya penting. Langkah 1-4 dikerjakan di mesin LAMA, sisanya di server.

---

## Di mesin lama

### 1. Ambil cadangan

```bash
python scripts/backup.py --out /d/ta_cadangan_drill
```

**Jangan menyalin `storage/experiments.db` mentah-mentah.** Ia berjalan dengan
`journal_mode=WAL`: menyalin berkasnya saat ada penulisan menghasilkan salinan
yang kehilangan transaksi yang masih berada di berkas `-wal`. Skrip ini memakai
API backup sqlite3, yang mengambil snapshot konsisten tanpa menghentikan
aplikasi.

Yang ikut: basis data, `uploaded_pipelines/`, `artifacts/`.
Yang TIDAK ikut: `storage/datasets/` (berukuran giga; salin terpisah atau
unduh ulang dari sumbernya) dan `storage/tmp/`.

Acuan waktu: 688 MB menjadi arsip 143 MB dalam 31 detik.

### 2. Catat angka pembanding

```bash
python -c "
import sqlite3
db = sqlite3.connect('storage/experiments.db')
for t in ('experiments','submissions','users','registered_pipelines'):
    print(t, db.execute(f'select count(*) from {t}').fetchone()[0])
print('skema', db.execute('select max(version) from _schema_version').fetchone()[0])"
```

Simpan keluarannya. Inilah yang dibandingkan setelah pemulihan; tanpa angka
pembanding, "kelihatannya jalan" adalah satu-satunya bukti yang Anda punya.

### 3. Salin dataset secara terpisah

`storage/datasets/` sengaja tidak masuk cadangan. Salin dengan cara apa pun
yang Anda suka (rsync, hard disk eksternal), atau unduh ulang dari sumber
aslinya.

### 4. Pindahkan arsip + dataset ke server

---

## Di server

### 5. Pasang prasyarat

Docker Engine + plugin Compose. **[BELUM DIUJI]** pada distribusi tertentu.

### 6. Klon repositori, lalu buat `.env` SEBELUM start pertama

```bash
git clone <repo> ids_platform && cd ids_platform
cat > .env <<'EOF'
ADMIN_USERNAME=admin
ADMIN_PASSWORD=ganti-dengan-sandi-kuat-minimal-8-karakter
REQUIRE_LOGIN_TO_RUN=true
EOF
chmod 600 .env
```

Heredoc-nya **dikutip** (`<<'EOF'`): tanpa kutip itu, sandi yang mengandung
`$` atau backtick akan ditafsirkan shell dan yang tersimpan bukan sandi yang
Anda ketik.

**Ini yang paling sering menjatuhkan orang.** Server baru berarti basis data
kosong. Tanpa `ADMIN_PASSWORD`, **tidak ada admin yang dibuat sama sekali**,
dan tidak ada jalan masuk. Tidak ada sandi bawaan: itu disengaja.

`REQUIRE_LOGIN_TO_RUN=true` menutup jalur "siapa pun boleh menjalankan". Di
laptop hal itu tidak berbahaya karena tidak ada yang dapat menjangkaunya; di
server, mitigasi itu hilang.

Ketiganya bekerja karena `docker-compose.yml` MENERUSKAN ketiganya di blok
`environment:`. Compose membaca `.env` hanya untuk substitusi di dalam berkas
compose, bukan untuk menyuntikkannya ke container: variabel yang tidak
diteruskan di sana tidak akan pernah sampai ke aplikasi. Kalau Anda menambah
variabel baru, tambahkan juga barisnya di compose.

Periksa sebelum melanjutkan:

```bash
docker compose config | grep -E "ADMIN_USERNAME|REQUIRE_LOGIN_TO_RUN"
```

Nilainya harus muncul. `ADMIN_PASSWORD` sengaja tidak ikut dicetak di sini.

### 7. Pulihkan data

```bash
tar -xzf cadangan_*.tar.gz
PULIH=$(ls -d cadangan_*/ | head -1)

cp -a "$PULIH/experiments.db" storage/
cp -a "$PULIH/uploaded_pipelines/." storage/uploaded_pipelines/
cp -a "$PULIH/artifacts/."          storage/artifacts/
# dataset disalin terpisah dari langkah 3
```

**Jangan `mv`.** Repositori ini MELACAK 512 berkas di bawah `storage/`
(fixture diagnosa, `.gitkeep`, keluaran pemeriksaan), jadi folder tujuannya
sudah ada dan berisi setelah klon. `mv cadangan_*/uploaded_pipelines storage/`
gagal dengan *"Directory not empty"*, dan pada varian lain justru
menyarangkannya menjadi `storage/uploaded_pipelines/uploaded_pipelines/`.

`cp -a <sumber>/. <tujuan>/` menyalin ISI-nya: berkas bernama sama ditimpa
data pulih, berkas repositori yang tidak ada di cadangan tetap ada.

Periksa tidak ada yang tersarang:

```bash
ls storage/uploaded_pipelines/     # TIDAK boleh ada "uploaded_pipelines" di sini
```

### 8. Sesuaikan pagu memori — DUA tempat, harus sama

Di `docker-compose.yml`:

| Tempat | Service | Sekarang |
|---|---|---|
| `mem_limit:` | `worker` | `3500m` |
| `WORKER_MEM_LIMIT_MB` | `ui` | `3500` |

Server dengan RAM lebih besar: naikkan **keduanya** ke angka yang sama.

Menaikkan `WORKER_MEM_LIMIT_MB` saja membuat UI mengizinkan dataset yang pasti
membunuh worker: gagal diam-diam di tengah run. Menaikkan `mem_limit` saja
hanya membuat UI terlalu kaku, yang aman tetapi menjengkelkan. Sisakan RAM
untuk sistem; jangan berikan seluruhnya.

### 9. Build sebagai non-root

```bash
docker compose build --build-arg RUN_AS=app
sudo chown -R 10001:10001 ./storage
```

UID 10001 tetap antar build, jadi `chown` tidak perlu diulang.

**Kalau `chown` terlewat**, gejalanya adalah
*"attempt to write a readonly database"*. Itu bukan kerusakan data; jalankan
`chown`-nya lalu `docker compose restart`.

Bawaannya tetap `root` khusus untuk Docker Desktop di Windows, yang memasang
bind mount lewat 9p dengan `uid=0;gid=0` sehingga non-root tidak dapat menulis.
Di Linux, pakai non-root.

### 10. Nyalakan HTTPS

```bash
docker compose --profile proxy up -d
```

Lalu **hapus blok `ports:` pada service `ui`** di `docker-compose.yml` supaya
tidak ada jalan memutar lewat HTTP polos, dan `docker compose up -d` lagi.

Untuk domain publik, sunting `docker/proxy/Caddyfile`: ganti `:443` dengan nama
domainnya dan hapus baris `tls internal` — Caddy mengurus sertifikat Let's
Encrypt sendiri. **[BELUM DIUJI]** dengan domain sungguhan.

### 11. Firewall

Izinkan 80 dan 443. **Tutup 8501 dan 6379** dari luar. Redis sudah tidak
dipublikasikan oleh compose, tetapi periksa sekali lagi setelah semuanya
menyala:

```bash
sudo ss -tlnp | grep -E "6379|8501"
```

### 12. Jadwalkan cadangan

```bash
crontab -e
# Minggu 02:00, simpan 4 terakhir
0 2 * * 0 cd /path/ids_platform && python scripts/backup.py --out /var/backups/ids --keep 4
```

**[BELUM DIUJI]** sebagai entri cron; skripnya sendiri sudah diuji.

---

## Verifikasi setelah start

Jangan lewati bagian ini. Urutannya dari yang paling murah.

### A. Angkanya cocok

```bash
docker compose exec ui python -c "
import sqlite3
db = sqlite3.connect('/app/storage/experiments.db')
for t in ('experiments','submissions','users','registered_pipelines'):
    print(t, db.execute(f'select count(*) from {t}').fetchone()[0])
print('skema', db.execute('select max(version) from _schema_version').fetchone()[0])
print('integritas', db.execute('pragma integrity_check').fetchone()[0])"
```

Bandingkan dengan catatan langkah 2. `integritas` harus `ok`.

### B. Migrasi berjalan

Skema harus **34** atau lebih. Migrasi berjalan otomatis saat container start.

### C. Anda dapat masuk

Buka `https://<server>`, masuk dengan akun dari `.env`. Kalau tidak bisa,
periksa log: `docker compose logs ui | grep -i admin`.

### D. Satu eksperimen sungguhan berjalan

Jalankan satu pipeline bawaan pada dataset kecil lewat UI. Ini yang
membuktikan worker, Redis, penulisan artefak, dan izin berkas bekerja
bersama-sama — empat hal yang tidak terbukti oleh langkah mana pun di atas.

### E. Cadangan pertama di server

```bash
python scripts/backup.py --out /var/backups/ids
```

Jalankan **sekali secara manual** sebelum mengandalkan cron.

---

## Yang TIDAK diselesaikan oleh pindah server

* **Tidak ada rate limiting maupun kuota per pengguna.** Satu pengguna yang
  masuk tetap dapat memenuhi antrean (concurrency 1).
* **Tidak ada monitoring, alerting, atau rotasi log.**
* **Belum pernah diuji beban maupun diuji secara adversarial.** 3.960 test
  menguji yang sudah terpikirkan.
* **SQLite tetap penulis-tunggal.** Cukup pada skala ini, tetapi ia bukan
  Postgres.

# BAGIAN 14/19 — TEST SUITE: 227 → 3.073 PENGUJIAN

Bahan untuk **2.2.4.6** (tulis ulang hampir seluruhnya), **2.2.5.4**, dan
**Gambar 14**. Memperbaiki **K-1** pada Bagian 2.

---

## 1. Angka yang benar

| Ruas | Draf lama | Sekarang |
|---|---:|---:|
| Pengujian dikumpulkan | 227 | **3.073** |
| Lulus | 225 | **3.071** |
| Dilewati | 2 | **2** |
| Gagal | 0 | **0** |
| Berkas tes | ± 25 | **103** |
| Baris kode uji | — | **33.441** |
| Durasi satu putaran penuh | ± 60 detik | **± 4–7 menit** |

Kedua pengujian yang dilewati tetap sama sebabnya: keduanya membutuhkan berkas
fikstur NDJSON opsional, dan bukan merupakan kegagalan.

---

## 2. Cakupan test suite sekarang (bahan tabel baru)

Seratus tiga berkas tes dapat dikelompokkan menjadi tujuh kelompok. Kelompok
1 sudah ada di draf; kelompok 2–7 seluruhnya baru.

| Kelompok | Cakupan | Contoh berkas |
|---|---|---|
| 1. Inti eksekusi | parser, validator, basis data, migrasi, artifact saver, service orchestrator, keenam pipeline HIKARI, pipeline EVE | test_parser, test_validator, test_db, test_migration, test_artifact_saver, test_hikari_all_pipelines, test_eve_pipeline |
| 2. Subsistem kontribusi | pengajuan, validator statis, uji coba, registry dinamis, versioning, identitas research | test_submission_service, test_pipeline_validator, test_pipeline_trial, test_dynamic_registry, test_pipeline_versions, test_research_registry |
| 3. Rantai end-to-end | unggah sampai eksperimen sungguhan berjalan | test_standalone_end_to_end, test_contributed_pipeline_chain, test_the_chain_says_what_happened |
| 4. Keamanan & izin | otorisasi peran, gerbang unggahan, gerbang identitas, sanitasi pesan galat | test_permissions, test_upload_permission_gate, test_approval_identity_gate, test_error_sanitizer, test_login_gate |
| 5. Mode run | parameter terlindungi, penerapan penyesuaian, pencatatan | test_run_mode, test_mode_switch_and_cards |
| 6. Antarmuka & i18n | tata letak, kepadatan teks, katalog, pencarian, kelengkapan dua bahasa | test_i18n_framework, test_i18n_closeout, test_catalog_search_and_filters, test_text_quota_and_layout, test_boxed_counts_responsive_and_cost |
| 7. Ketahanan lintas lingkungan | jalur berkas yang tetap sahih di host maupun kontainer | test_path_fallback, test_stored_path_survives_the_move |

---

## 3. Jenis pengujian yang layak disebut khusus (menaikkan bobot Bab II)

Ketiga pola berikut tidak lazim ada pada skripsi, dan seluruhnya benar-benar
dipakai:

### 3.1 Pengujian yang membaca teks sumbernya sendiri

Sebagian pengujian mengurai berkas sumber dengan `ast` dan memeriksa
**strukturnya**, bukan keluarannya. Contoh yang berlaku sekarang:

- memastikan fungsi penyusun katalog **tidak** memuat kueri basis data, sehingga
  biaya render tidak tumbuh seiring jumlah research pipeline;
- memastikan tidak ada teks bahasa Inggris yang tertanam langsung pada komponen
  yang seharusnya melewati katalog terjemahan;
- memastikan urutan penggambaran elemen pada satu halaman tetap seperti yang
  dirancang.

Nilainya: aturan arsitektural yang biasanya hanya berupa dokumentasi menjadi
**dapat gagal secara otomatis** ketika dilanggar.

### 3.2 Pengujian anggaran biaya render

Sejumlah pengujian mengukur **berapa kali** sebuah halaman menyentuh basis data
dan sistem berkas pada satu penggambaran, lalu membandingkannya dengan anggaran
yang ditetapkan. Ini mencegah kemunduran kinerja yang tidak terlihat mata tetapi
tumbuh seiring bertambahnya data.

Contoh terukur: biaya penyusunan katalog pengelolaan research pipeline pernah
mencapai **19 kueri** dan tumbuh linear terhadap jumlah research; sesudah
penggabungan atribusi dipisahkan menjadi fungsi murni, biayanya menjadi
**4 kueri dan tetap segitu** berapa pun jumlah research-nya.

### 3.3 Pengujian antarmuka tanpa peramban

Halaman Streamlit digambar secara *headless* memakai `AppTest`, lalu elemennya
diperiksa dan tombolnya benar-benar ditekan dari dalam pengujian. Dengan ini,
alur seperti "buka formulir sunting, ubah satu isian, simpan, lalu periksa
daftarnya sudah berubah" dapat diuji tanpa perkakas pengujian peramban.

---

## 4. Pengujian reproducibility yang sudah ada tetap berlaku

Draf menyebut bahwa tiap pipeline dijalankan dua kali dengan masukan identik
lalu metriknya dibandingkan. **Itu masih ada dan masih berlaku**, ditambah satu
praktik baru:

> Setiap tahap pengembangan sesudah seminar hasil ditutup dengan pemeriksaan
> reproduktibilitas tersendiri: satu pipeline bawaan dijalankan ulang dan
> metriknya dibandingkan dengan artefak lama, dengan syarat **identik pada
> seluruh digit**. Seluruh pemeriksaan sepanjang pengembangan subsistem
> kontribusi menghasilkan selisih nol, sehingga penambahan subsistem tersebut
> terbukti tidak menggeser satu pun angka yang dilaporkan pada Bab III.

Kalimat itu **penting** dan sebaiknya juga muncul di Bab III atau Bab IV: ia
menjawab keberatan paling wajar dari penguji — "kalau sistemnya berubah banyak,
apakah hasil lamanya masih berlaku?"

---

## 5. Yang masih belum ada (tetap harus jujur)

Draf sudah menyatakan dua keterbatasan; keduanya **masih berlaku** dan jangan
dihapus:

- belum ada pengujian anti-*leakage* khusus yang secara otomatis menolak
  kemunduran metodologis;
- belum ada *pre-commit hook* maupun *continuous integration*; eksekusi test
  suite masih manual sebelum tiap checkpoint.

Yang boleh ditambahkan: dengan 3.073 pengujian dan durasi ± 4–7 menit, eksekusi
manual masih layak untuk satu pengembang, tetapi otomatisasi menjadi kebutuhan
nyata bila kontributor bertambah.

---

## 6. Gambar 14 wajib diambil ulang

Gambar 14 pada draf menampilkan `225 passed, 2 skipped` beserta daftar berkas
yang sudah tidak lengkap. Perintah untuk mengambilnya kembali:

```
python -m pytest -q
```

dengan `DB_PATH` menunjuk **salinan** basis data (bukan berkas penelitian).
Pastikan tangkapan layar memuat baris ringkasan terakhir yang menyebut jumlah
lulus, dilewati, dan durasi.

**[PERLU_DIPASTIKAN PENULIS: ambil ulang tangkapan layarnya sebelum draf
dicetak; angkanya harus cocok dengan yang ditulis di teks.]**

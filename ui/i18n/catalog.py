"""
Kamus teks dua bahasa.

Bentuknya ``{kunci: {"id": ..., "en": ...}}`` — bukan dua kamus terpisah —
supaya kedua bahasa satu teks selalu bersebelahan. Terjemahan yang tertinggal
karena dua berkas terpisah tidak sinkron adalah kegagalan paling umum pada
pendekatan dua-kamus, dan bentuk ini membuatnya tidak mungkin: kunci baru hanya
punya satu tempat untuk ditulis.

**Lingkup Tahap 1** — kerangka saja: navigasi, jejak lokasi, judul blok sidebar,
label mode & tombol masuk/keluar, judul halaman, dan tombol umum yang berulang.
Isi ketiga halaman menyusul di Tahap 2; pesan validasi/diagnosa/laporan di
Tahap 3. Kunci yang belum ada terjemahan Inggrisnya cukup dikosongkan
(``"en": ""``) — pengambilnya akan memakai teks Indonesia sebagai cadangan, dan
:func:`ui.i18n.missing_keys` mendaftarnya.

Penulisan kunci: ``<bagian>.<nama>``, huruf kecil, bagian dulu. Bagian yang
dipakai: ``nav``, ``crumb``, ``sidebar``, ``mode``, ``auth``, ``page``,
``action``, ``lang``.
"""
from __future__ import annotations

CATALOG: dict[str, dict[str, str]] = {

    # ── Navigasi ─────────────────────────────────────────────────────────
    # Nama halaman. Dipakai menu sidebar DAN jejak lokasi, jadi keduanya tidak
    # mungkin berbeda sebutan.
    "nav.section": {"id": "Navigasi", "en": "Navigation"},
    "nav.run_experiment": {"id": "Jalankan Eksperimen", "en": "Run Experiment"},
    "nav.progress": {"id": "Progres & Status", "en": "Progress & Status"},
    "nav.contribute": {"id": "Tambah Pipeline & Dataset",
                       "en": "Add Pipeline & Dataset"},

    # ── Jejak lokasi ─────────────────────────────────────────────────────
    # Akar jejak lokasi. Kata yang sama di kedua bahasa — dan sengaja tetap
    # "Menu" seperti sebelumnya: Tahap 1 menerjemahkan, bukan mengganti kata.
    "crumb.root": {"id": "Menu", "en": "Menu"},
    "crumb.separator": {"id": "›", "en": "›"},

    # ── Blok sidebar ─────────────────────────────────────────────────────
    "sidebar.progress_title": {"id": "Sedang berjalan", "en": "Running now"},
    "sidebar.progress_empty": {"id": "Tidak ada eksperimen berjalan",
                               "en": "No experiments running"},
    "sidebar.identity_title": {"id": "Identitas", "en": "Identity"},
    "sidebar.language_title": {"id": "Bahasa", "en": "Language"},

    # ── Mode pengguna ────────────────────────────────────────────────────
    # Label peran. "Research Admin" TIDAK diterjemahkan — ia nama peran yang
    # dipakai apa adanya di kedua bahasa, sama seperti nama algoritma.
    "mode.label": {"id": "Mode", "en": "Mode"},
    "mode.visitor": {"id": "Pengunjung", "en": "Visitor"},
    "mode.contributor": {"id": "Kontributor", "en": "Contributor"},
    "mode.research_admin": {"id": "Research Admin", "en": "Research Admin"},
    "mode.visitor_line": {"id": "Mode pengunjung", "en": "Visitor mode"},

    # ── Masuk / daftar / keluar ──────────────────────────────────────────
    "auth.sign_in": {"id": "Masuk", "en": "Sign in"},
    "auth.sign_up": {"id": "Daftar", "en": "Sign up"},
    "auth.sign_out": {"id": "Keluar", "en": "Sign out"},
    "auth.username": {"id": "Username", "en": "Username"},
    "auth.password": {"id": "Password", "en": "Password"},
    "auth.sign_in_hint": {
        "id": "Masuk lewat pemilih mode di kiri bawah sidebar.",
        "en": "Sign in from the mode picker at the bottom left of the sidebar."},

    # ── Judul halaman ────────────────────────────────────────────────────
    "page.run_experiment": {"id": "Jalankan Eksperimen", "en": "Run Experiment"},
    "page.progress": {"id": "Progres & Status", "en": "Progress & Status"},
    "page.contribute": {"id": "Tambah Pipeline & Dataset",
                        "en": "Add Pipeline & Dataset"},

    # ── Tombol umum, dipakai berulang di banyak tempat ───────────────────
    # Justru karena berulang, kunci-kunci ini yang paling menguntungkan untuk
    # dipusatkan: satu perbaikan kata berlaku di seluruh platform.
    "action.back": {"id": "Kembali", "en": "Back"},
    "action.close": {"id": "Tutup", "en": "Close"},
    "action.save": {"id": "Simpan", "en": "Save"},
    "action.cancel": {"id": "Batal", "en": "Cancel"},
    "action.check": {"id": "Periksa", "en": "Check"},
    "action.open": {"id": "Buka", "en": "Open"},
    "action.approve": {"id": "Setujui", "en": "Approve"},
    "action.reject": {"id": "Tolak", "en": "Reject"},
    "action.refresh": {"id": "Muat ulang", "en": "Refresh"},
    "action.download": {"id": "Unduh", "en": "Download"},
    "action.upload": {"id": "Unggah", "en": "Upload"},
    "action.delete": {"id": "Hapus", "en": "Delete"},
    "action.edit": {"id": "Sunting", "en": "Edit"},
    "action.compare": {"id": "Bandingkan", "en": "Compare"},

    # ── Pengalih bahasa ──────────────────────────────────────────────────
    "lang.help": {
        "id": "Ganti bahasa antarmuka. Pilihan Anda di halaman ini tidak hilang.",
        "en": "Change the interface language. Your choices on this page are kept."},


    # ═══════════════════════════════════════════════════════════════════
    # HALAMAN: Progress & Status                            (Tahap 2)
    # ═══════════════════════════════════════════════════════════════════

    # ── Judul bagian ─────────────────────────────────────────────────────
    "ps.running_title": {"id": "Sedang Berjalan", "en": "Running Now"},
    "ps.history_title": {"id": "Riwayat Eksperimen", "en": "Experiment History"},

    # ── Dialog & sub-tampilan ────────────────────────────────────────────
    "ps.dlg_columns": {"id": "Kolom", "en": "Columns"},
    "ps.dlg_filter": {"id": "Filter", "en": "Filter"},
    "ps.dlg_compare": {"id": "Bandingkan Eksperimen", "en": "Compare Experiments"},

    # ── Label widget (frasa pendek di KEDUA bahasa) ──────────────────────
    "ps.f_pipeline": {"id": "Pipeline", "en": "Pipeline"},
    "ps.f_dataset": {"id": "Dataset", "en": "Dataset"},
    "ps.f_status": {"id": "Status", "en": "Status"},
    "ps.f_run_mode": {"id": "Mode eksekusi", "en": "Run mode"},
    "ps.f_date_from": {"id": "Dari tanggal", "en": "From date"},
    "ps.f_date_to": {"id": "Sampai tanggal", "en": "To date"},
    "ps.f_metric_search": {"id": "Cari metrik", "en": "Search metrics"},
    "ps.f_metric_hint": {"id": "mis. f1 > 0.8 and accuracy >= 0.9",
                         "en": "e.g. f1 > 0.8 and accuracy >= 0.9"},
    "ps.autorefresh": {"id": "Auto-refresh", "en": "Auto-refresh"},

    # ── Tombol ───────────────────────────────────────────────────────────
    # Pendek di kedua bahasa: kolom tombol di sini sempit.
    "ps.btn_core_columns": {"id": "Kembalikan ke set inti", "en": "Reset to core set"},
    "ps.btn_clear_filter": {"id": "Bersihkan filter", "en": "Clear filters"},
    "ps.btn_open": {"id": "Buka", "en": "Open"},
    "ps.btn_drop": {"id": "Buang", "en": "Remove"},
    "ps.btn_refresh_now": {"id": "Perbarui", "en": "Refresh"},
    "ps.btn_cancel_run": {"id": "Batalkan", "en": "Cancel"},
    "ps.btn_pdf": {"id": "Unduh Laporan PDF", "en": "Download PDF Report"},
    "ps.btn_rerun": {"id": "Jalankan ulang", "en": "Re-run"},
    "ps.btn_detail": {"id": "Lihat detail", "en": "View details"},
    "ps.btn_open_detail": {"id": "Buka detail", "en": "Open details"},
    "ps.btn_drop_compare": {"id": "Buang dari perbandingan",
                            "en": "Remove from comparison"},
    "ps.btn_csv": {"id": "Unduh CSV", "en": "Download CSV"},
    "ps.btn_compare_n": {"id": "Bandingkan terpilih ({count})",
                         "en": "Compare selected ({count})"},

    # ── Keadaan kosong ───────────────────────────────────────────────────
    "ps.empty_running": {
        "id": "Tidak ada eksperimen yang sedang berjalan. Buka "
              "**Run Experiment** dari menu di sidebar untuk memulai.",
        "en": "No experiments are running. Open **Run Experiment** from the "
              "sidebar menu to start one."},
    "ps.empty_history": {
        "id": "Belum ada eksperimen. Buka halaman 'Run Experiment' untuk "
              "membuat satu.",
        "en": "No experiments yet. Open the 'Run Experiment' page to create one."},
    "ps.empty_filtered": {
        "id": "Tidak ada eksperimen yang cocok dengan filter. Bersihkan filter "
              "lewat tombol **Filter**.",
        "en": "No experiments match the filters. Clear them with the "
              "**Filter** button."},
    "ps.empty_columns": {
        "id": "Tidak ada kolom yang dipilih. Pilih kolom lewat tombol **Kolom**.",
        "en": "No columns selected. Choose columns with the **Columns** button."},
    "ps.empty_artifacts": {
        "id": "Artefak belum tersedia atau direktori artefak kosong.",
        "en": "No artifacts yet, or the artifact directory is empty."},

    # ── Pesan hasil aksi ─────────────────────────────────────────────────
    "ps.msg_cancelled": {"id": "Eksperimen dibatalkan.",
                         "en": "Experiment cancelled."},
    "ps.msg_cancelled_by_user": {"id": "Eksperimen dibatalkan oleh pengguna.",
                                 "en": "Experiment cancelled by the user."},
    "ps.msg_not_found": {"id": "Eksperimen tidak ditemukan.",
                         "en": "Experiment not found."},
    "ps.msg_waiting_worker": {
        "id": "Menunggu worker mengambil tugas…",
        "en": "Waiting for a worker to pick up the task…"},
    "ps.msg_no_granular": {
        "id": "Progres granular tidak tersedia untuk eksperimen ini.",
        "en": "Granular progress is not available for this experiment."},
    "ps.msg_broker_down": {
        "id": "Broker (Redis) tidak tersambung — progres granular tidak "
              "tersedia; menampilkan status & elapsed saja.",
        "en": "The broker (Redis) is not connected — granular progress is "
              "unavailable; showing status and elapsed time only."},
    "ps.msg_status_no_result": {
        "id": "Eksperimen berstatus {status}. Hasil belum tersedia.",
        "en": "The experiment is {status}. No results yet."},
    "ps.msg_pdf_failed": {"id": "PDF tidak dapat dibuat:",
                          "en": "The PDF could not be created:"},

    # ── Perbandingan ─────────────────────────────────────────────────────
    "ps.cmp_manage": {"id": "**Kelola eksperimen dalam perbandingan ini**",
                      "en": "**Manage the experiments in this comparison**"},
    "ps.cmp_hide_same": {"id": "Baris yang nilainya sama disembunyikan.",
                         "en": "Rows with identical values are hidden."},

    # ── Parameter ────────────────────────────────────────────────────────
    "ps.params_locked": {
        "id": "Seluruh parameter sama dengan nilai terkunci pipeline.",
        "en": "All parameters match the pipeline's locked values."},
    "ps.params_differs": {"id": "Berbeda dari bawaan:", "en": "Differs from default:"},


    # ── Progress & Status: tampilan hasil ────────────────────────────────
    # Nama metrik & nama grafik (Confusion Matrix, ROC Curve, Accuracy, …)
    # TIDAK diterjemahkan — istilah metrik dipakai apa adanya di kedua bahasa.
    "ps.rv_security_reading": {"id": "**Interpretasi keamanan**",
                               "en": "**Security reading**"},
    "ps.rv_attacks_caught": {"id": "Serangan terdeteksi", "en": "Attacks detected"},
    "ps.rv_attacks_missed": {"id": "Serangan lolos (FN)", "en": "Attacks missed (FN)"},
    "ps.rv_false_alarms": {"id": "Alarm palsu (FP)", "en": "False alarms (FP)"},
    "ps.rv_tpr": {"id": "TPR — serangan terdeteksi", "en": "TPR — attacks detected"},
    "ps.rv_fpr": {"id": "FPR — benign salah ditandai",
                  "en": "FPR — benign wrongly flagged"},
    "ps.rv_cell_detail": {"id": "Lihat detail sel:", "en": "Cell details:"},
    "ps.rv_top_features": {"id": "Jumlah fitur teratas", "en": "Top features"},
    "ps.rv_roc_point": {"id": "Titik operasi pada kurva (indeks)",
                        "en": "Operating point on the curve (index)"},
    "ps.rv_show_std": {"id": "Tampilkan pita standar deviasi",
                       "en": "Show standard-deviation band"},
    "ps.rv_dual_holdout": {"id": "Evaluasi Dual-Holdout", "en": "Dual-Holdout Evaluation"},
    "ps.rv_no_cm": {"id": "Confusion matrix tidak tersedia atau bukan biner.",
                    "en": "No confusion matrix available, or it is not binary."},
    "ps.rv_no_roc": {"id": "ROC / AUC tidak tersedia untuk eksperimen ini.",
                     "en": "ROC / AUC is not available for this experiment."},
    "ps.rv_no_roc_points": {
        "id": "Titik kurva ROC (fpr/tpr) tidak tersedia; hanya nilai AUC yang "
              "dilaporkan.",
        "en": "ROC curve points (fpr/tpr) are not available; only the AUC "
              "value is reported."},


    # ═══════════════════════════════════════════════════════════════════
    # HALAMAN: Run Experiment                                (Tahap 2)
    # ═══════════════════════════════════════════════════════════════════
    # Sebagian judul di halaman ini SEBELUMNYA hanya berbahasa Inggris
    # ("Dataset Selection", "Execute", "Results") padahal bahasa bawaan
    # platform adalah Indonesia. Di sini keduanya diberi teks penuh — jadi
    # halaman ini justru menjadi lebih konsisten, bukan sekadar diterjemahkan.

    # ── Judul bagian ─────────────────────────────────────────────────────
    "re.sec_dataset": {"id": "Pemilihan Dataset", "en": "Dataset Selection"},
    "re.sec_pipeline": {"id": "Pemilihan Research Pipeline",
                        "en": "Research Pipeline Selection"},
    "re.sec_algorithm": {"id": "Pilih Algoritma", "en": "Choose Algorithm"},
    "re.sec_execute": {"id": "Jalankan", "en": "Execute"},
    "re.sec_results": {"id": "Hasil", "en": "Results"},
    "re.sec_download": {"id": "Unduh Laporan", "en": "Download Report"},

    # ── Dialog & sub-tampilan ────────────────────────────────────────────
    "re.dlg_check_detail": {"id": "Rincian pemeriksaan", "en": "Check details"},
    "re.dlg_compat_test": {"id": "Uji Kecocokan Dataset",
                           "en": "Dataset Compatibility Test"},
    "re.dlg_pipeline_detail": {"id": "Detail Research Pipeline",
                               "en": "Research Pipeline Details"},
    "re.dlg_run_pipeline": {"id": "Jalankan Research Pipeline",
                            "en": "Run Research Pipeline"},
    "re.dlg_dataset_detail": {"id": "Detail dataset (preview & validasi)",
                              "en": "Dataset details (preview & validation)"},
    "re.dlg_about_pipeline": {"id": "Tentang Research Pipeline (Baca-saja)",
                              "en": "About the Research Pipeline (read-only)"},
    "re.dlg_diag_detail": {"id": "Detail diagnostik", "en": "Diagnostic details"},
    "re.dlg_dataset_req": {"id": "Persyaratan dataset", "en": "Dataset requirements"},

    # ── Label widget (frasa pendek) ──────────────────────────────────────
    "re.lbl_pick_dataset": {"id": "Pilih dataset", "en": "Choose dataset"},
    "re.ph_pick_dataset": {"id": "Pilih berkas dataset…",
                           "en": "Choose a dataset file…"},
    "re.lbl_pick_pipeline": {"id": "Pilih research pipeline",
                             "en": "Choose research pipeline"},
    "re.ph_pick_pipeline": {"id": "Pilih research pipeline…",
                            "en": "Choose a research pipeline…"},
    "re.lbl_algorithm": {"id": "Algoritma", "en": "Algorithm"},
    "re.lbl_pick_algorithm": {"id": "Pilih algoritma", "en": "Choose algorithm"},
    "re.ph_pick_algorithm": {"id": "Pilih algoritma…", "en": "Choose an algorithm…"},
    "re.lbl_run_mode": {"id": "Mode eksekusi", "en": "Run mode"},

    # ── Tombol ───────────────────────────────────────────────────────────
    "re.btn_run": {"id": "Jalankan Eksperimen", "en": "Run Experiment"},
    "re.btn_run_pipeline": {"id": "Jalankan pipeline ini", "en": "Run this pipeline"},
    "re.btn_run_short": {"id": "Jalankan", "en": "Run Pipeline"},
    "re.btn_detail": {"id": "Detail", "en": "Details"},
    "re.btn_cancel_exp": {"id": "Batalkan Eksperimen", "en": "Cancel Experiment"},
    "re.btn_use_dataset": {"id": "Pakai dataset ini", "en": "Use this dataset"},
    "re.btn_compat_test": {"id": "Uji kecocokan", "en": "Test compatibility"},
    "re.btn_recheck": {"id": "Periksa ulang", "en": "Check again"},
    "re.btn_catalog": {"id": "← Katalog", "en": "← Catalog"},
    "re.btn_pick": {"id": "Pilih", "en": "Select"},
    "re.btn_reset_defaults": {"id": "Kembalikan ke bawaan", "en": "Reset to defaults"},
    "re.btn_pdf": {"id": "Unduh Laporan PDF", "en": "Download PDF Report"},

    # ── help= ────────────────────────────────────────────────────────────
    "re.help_dataset": {
        "id": "Berkas di storage/datasets/. Pilihannya menentukan research "
              "pipeline mana yang tersedia.",
        "en": "Files in storage/datasets/. Your choice determines which "
              "research pipelines are available."},
    "re.help_pipeline": {
        "id": "Research pipeline yang kompatibel dengan dataset terpilih.",
        "en": "Research pipelines compatible with the selected dataset."},
    "re.help_execute": {"id": "Menjalankan pipeline terpilih pada dataset terpilih.",
                        "en": "Runs the selected pipeline on the selected dataset."},
    "re.help_order": {"id": "Pilih dataset lebih dulu, lalu pipeline & algoritma.",
                      "en": "Choose a dataset first, then a pipeline and algorithm."},
    "re.help_algorithm": {
        "id": "Preprocessing & hyperparameter yang ditampilkan mengikuti "
              "algoritma yang dipilih di sini.",
        "en": "The preprocessing and hyperparameters shown follow the "
              "algorithm selected here."},
    "re.help_find_dataset": {"id": "Cari dataset yang cocok untuk pipeline ini.",
                             "en": "Find a dataset that fits this pipeline."},
    "re.help_full_detail": {"id": "Keterangan lengkap & tahapan pipeline.",
                            "en": "Full description and pipeline stages."},

    # ── Keadaan kosong & pesan ───────────────────────────────────────────
    "re.empty_no_compatible": {
        "id": "Tidak ada pipeline yang kompatibel untuk dataset ini.",
        "en": "No pipeline is compatible with this dataset."},
    "re.empty_no_dataset_for_pipeline": {
        "id": "Belum ada dataset di server yang cocok untuk research pipeline ini.",
        "en": "No dataset on the server fits this research pipeline yet."},
    "re.msg_dataset_valid": {"id": "Dataset lolos validasi skema.",
                             "en": "Dataset is valid!"},
    "re.msg_dataset_invalid": {
        "id": "Dataset tidak lolos validasi skema — ringkasannya ada di bawah "
              "panel ini.",
        "en": "The dataset failed schema validation — the summary is below "
              "this panel."},
    "re.msg_not_compatible": {"id": "**Dataset belum cocok untuk pipeline ini.**",
                              "en": "**This dataset does not fit this pipeline yet.**"},
    "re.msg_exp_not_found": {"id": "Eksperimen tidak ditemukan.",
                             "en": "Experiment not found."},
    "re.msg_exp_cancelled": {"id": "Eksperimen dibatalkan.",
                             "en": "Experiment cancelled."},
    "re.msg_exp_was_cancelled": {"id": "Eksperimen telah dibatalkan.",
                                 "en": "Experiment was cancelled."},
    "re.msg_exp_failed": {"id": "Eksperimen gagal:", "en": "Experiment failed:"},
    "re.msg_log_later": {
        "id": "Log proses lengkap akan muncul di hasil setelah selesai.",
        "en": "The full process log will appear in the results once finished."},
    "re.msg_preview_unavailable": {"id": "Preview tidak tersedia untuk berkas ini.",
                                   "en": "No preview available for this file."},
    "re.msg_no_stages": {"id": "Tahapan pipeline ini tidak terdaftar.",
                         "en": "This pipeline's stages are not registered."},
    "re.msg_no_requirements": {"id": "Persyaratan dataset tidak tersedia.",
                               "en": "Dataset requirements are not available."},

    # ── Keterangan WAJIB — maknanya harus sama persis ────────────────────
    "re.note_locked_params": {
        "id": "Nilai di atas adalah parameter TERKUNCI yang dipakai run resmi. "
              "Run eksplorasi dapat mengubahnya.",
        "en": "The values above are the LOCKED parameters used by official "
              "runs. Exploration runs may change them."},
    "re.note_follows_pipeline": {
        "id": "Mengikuti research pipeline, bukan algoritmanya.",
        "en": "Follows the research pipeline, not the algorithm."},

    # ── Status broker/worker ─────────────────────────────────────────────
    "re.broker_connected": {"id": "Broker: tersambung", "en": "Broker: connected"},
    "re.broker_down": {"id": "Broker: terputus", "en": "Broker: disconnected"},
    "re.worker_none": {"id": "Worker: tidak terdeteksi", "en": "Worker: not detected"},
    "re.help_sync_mode": {"id": "Broker/worker tidak diperlukan pada mode sinkron.",
                          "en": "No broker or worker is needed in synchronous mode."},


    # ═══════════════════════════════════════════════════════════════════
    # HALAMAN: Add Pipeline & Dataset                        (Tahap 2)
    # ═══════════════════════════════════════════════════════════════════

    # ── Judul bagian ─────────────────────────────────────────────────────
    # Konfirmasi persetujuan. Sebelumnya ia hanya menyebut pengenal mesin dan
    # hash — benar, tetapi tidak menjawab pertanyaan peninjau: "berhasil, lalu
    # ada di mana?"
    "ap.msg_approved_live": {"id": "Disetujui. **{research}** kini aktif dan dapat dijalankan di halaman **Jalankan Eksperimen** ({count} algoritma).",
                             "en": "Approved. **{research}** is now active and runnable on the **Run Experiment** page ({count} algorithms)."},
    "ap.msg_approved_no_dataset": {"id": "Disetujui, tetapi **{research}** belum dapat dijalankan: dataset paketnya tidak ditemukan.",
                                   "en": "Approved, but **{research}** cannot be run yet: its package dataset is missing."},
    "ap.sec_review": {"id": "Peninjauan Pengajuan", "en": "Submission Review"},
    "ap.sec_pending": {"id": "Menunggu tinjauan ({count})",
                       "en": "Awaiting review ({count})"},
    "ap.sec_active": {"id": "Aktif", "en": "Active"},
    "ap.sec_active_n": {"id": "Aktif ({count})", "en": "Active ({count})"},
    "ap.sec_history": {"id": "Riwayat versi", "en": "Version history"},
    "ap.sec_users": {"id": "Kelola Pengguna", "en": "Manage Users"},
    "ap.sec_upload_pipeline": {"id": "Unggah Pipeline", "en": "Upload Pipeline"},
    "ap.sec_add_dataset": {"id": "Tambah Dataset", "en": "Add Dataset"},
    "ap.sec_validation": {"id": "Hasil validasi", "en": "Validation result"},
    "ap.sec_dataset_profile": {"id": "Profil dataset", "en": "Dataset profile"},
    "ap.sec_compatibility": {"id": "Kecocokan", "en": "Compatibility"},
    "ap.sec_editor": {"id": "Sunting berkas", "en": "Edit files"},
    "ap.sec_compare": {"id": "Bandingkan versi", "en": "Compare versions"},

    # ── Label widget (frasa pendek) ──────────────────────────────────────
    "ap.lbl_review_note": {"id": "Catatan tinjauan", "en": "Review note"},
    "ap.ph_review_note": {"id": "Opsional saat menyetujui; WAJIB saat menolak.",
                          "en": "Optional when approving; REQUIRED when rejecting."},
    "ap.lbl_role": {"id": "Peran", "en": "Role"},
    "ap.lbl_pipeline_files": {"id": "Berkas pipeline", "en": "Pipeline files"},
    # Fase progres yang TERBACA dari kode berkas. Ditampilkan untuk
    # diperiksa, bukan ditanyakan: urutannya sudah ada di dalam kode, dan
    # pembacaan statis memberi urutan KEMUNCULAN — belum tentu urutan
    # saat berjalan.
    # Kelengkapan `get_info()`. Tiap kalimat menyebut apa yang HILANG bila
    # kuncinya kosong — dan tiap akibat di bawah punya pembaca nyata di kode
    # ini, bukan peringatan yang dikarang untuk menakut-nakuti.
    "ap.info_incomplete": {"id": "`{filename}` — metadata `get_info()` terisi {have} dari {total}. Yang belum ada, dan akibatnya:",
                           "en": "`{filename}` — `get_info()` metadata filled {have} of {total}. What is missing, and what it costs:"},
    "ap.info_incomplete_note": {"id": "Kekurangan ini TIDAK menghalangi pengajuan: pipelinenya tetap berjalan. Yang hilang adalah keterbacaannya — dan yang perlu diperbaiki adalah `get_info()` pada kode Anda, bukan isian di halaman ini.",
                                "en": "None of this blocks your submission: the pipeline still runs. What is lost is how well it reads — and the fix belongs in `get_info()` in your code, not in a field on this page."},
    "ap.cost_paper": {"id": "kredit penelitian tidak muncul pada entri registry maupun laporan eksperimen.",
                      "en": "the research credit will not appear in the registry entry or the experiment report."},
    "ap.cost_algorithm": {"id": "nama algoritma jatuh ke nama paket pada pemilih dan tabel riwayat.",
                          "en": "the algorithm name falls back to the package name in the picker and the history table."},
    "ap.cost_preprocessing": {"id": "langkah preprocessing tidak terbaca di katalog maupun laporan.",
                              "en": "the preprocessing steps will not be readable in the catalogue or the report."},
    "ap.cost_feature_selection": {"id": "keterangan seleksi fitur tidak terbaca di katalog maupun laporan.",
                                  "en": "the feature selection note will not be readable in the catalogue or the report."},
    "ap.cost_fixed_params": {"id": "**tidak ada satu pun parameter yang tampil** — transparansi hyperparameter hilang, dan mode eksplorasi tidak dapat dipakai sama sekali.",
                             "en": "**no parameter will be shown at all** — hyperparameter transparency is lost, and exploration mode cannot be used."},
    "ap.cost_train_test_split": {"id": "pembagian train/test tidak terbaca di katalog maupun laporan.",
                                 "en": "the train/test split will not be readable in the catalogue or the report."},
    # Kunci OPSIONAL: ditawarkan, tidak dituntut. Kalimatnya menyebut apa yang
    # DIDAPAT bila diisi — bukan apa yang hilang bila tidak.
    "ap.info_optional": {"id": "`{filename}` — tiga kunci opsional ini tidak diminta kontrak, tetapi panel \"Tentang Research Pipeline\" menampilkannya bila ada:",
                         "en": "`{filename}` — these three optional keys are not required by the contract, but the \"About Research Pipeline\" panel shows them when present:"},
    "ap.gain_app": {"id": "fokus aplikasi/trafik yang dicakup pipeline ini.",
                    "en": "the application/traffic focus this pipeline covers."},
    "ap.gain_anti_leakage": {"id": "langkah yang Anda ambil supaya data uji tidak bocor ke pelatihan.",
                             "en": "the steps you took to keep test data out of training."},
    "ap.gain_metrics_policy": {"id": "metrik mana yang dijadikan patokan, dan mengapa.",
                               "en": "which metric is treated as the headline, and why."},
    # Kredit penelitian TERSTRUKTUR. Nama tampil research pipeline disusun
    # sebagai "<kredit> — <nama>", pola yang sama dengan atribusi bawaan.
    "ap.sec_credit": {"id": "Kredit penelitian", "en": "Research credit"},
    "ap.lbl_researcher": {"id": "Peneliti", "en": "Researcher"},
    "ap.lbl_year": {"id": "Tahun", "en": "Year"},
    "ap.lbl_source_type": {"id": "Jenis", "en": "Kind"},
    "ap.ph_source_type": {"id": "Skripsi, tesis, jurnal…", "en": "Thesis, journal…"},
    "ap.lbl_title": {"id": "Judul penelitian", "en": "Research title"},
    "ap.lbl_institution": {"id": "Institusi", "en": "Institution"},
    "ap.lbl_scope": {"id": "Cakupan penelitian", "en": "Research scope"},
    # Dari mana datanya berasal, dan milik siapa. Pipeline bawaan menyebutnya;
    # tanpa ini baris "Sumber dataset" pada panel unggahan kosong.
    "ap.sec_dataset_source": {"id": "Sumber dataset", "en": "Dataset source"},
    "ap.lbl_dataset_name": {"id": "Nama dataset", "en": "Dataset name"},
    "ap.lbl_dataset_attribution": {"id": "Atribusi / pemilik", "en": "Attribution / owner"},
    "ap.lbl_dataset_note": {"id": "Catatan sumber", "en": "Source note"},
    "ap.ph_dataset_note": {"id": "mis. varian, tahun pengambilan, atau tautan",
                           "en": "e.g. variant, collection year, or link"},
    "ap.credit_preview": {"id": "Akan tampil sebagai **{credit} — {name}** pada pemilih research pipeline.",
                          "en": "Will appear as **{credit} — {name}** in the research pipeline picker."},
    # Kolom DIPILIH dari dataset lampiran, bukan diketik: salah ketik satu
    # huruf membuat kontraknya tidak cocok tanpa ada yang memberi tahu.
    "ap.columns_from_dataset": {"id": "{count} kolom terbaca dari dataset yang Anda lampirkan — pilih dari daftar agar namanya tidak meleset.",
                                "en": "{count} columns read from the dataset you attached — pick from the list so the names cannot drift."},
    "ap.detected_stages": {"id": "Fase progres terbaca: {stages} — periksa urutannya.",
                           "en": "Progress phases detected: {stages} — check the order."},
    "ap.lbl_file_role": {"id": "Peran berkas", "en": "File role"},
    "ap.lbl_pipeline_name": {"id": "Nama pipeline", "en": "Pipeline name"},
    "ap.lbl_note": {"id": "Catatan", "en": "Note"},
    "ap.lbl_dataset_file": {"id": "Berkas dataset", "en": "Dataset file"},
    "ap.ph_pick_file": {"id": "Pilih berkas…", "en": "Choose a file…"},
    "ap.lbl_section": {"id": "Bagian", "en": "Section"},
    "ap.lbl_old_version": {"id": "Versi lama", "en": "Older version"},
    "ap.lbl_compared_with": {"id": "Dibandingkan dengan", "en": "Compared with"},
    "ap.lbl_files": {"id": "Berkas", "en": "Files"},
    "ap.lbl_pipeline": {"id": "Pipeline", "en": "Pipeline"},
    "ap.lbl_pipeline_code": {"id": "Kode pipeline", "en": "Pipeline code"},
    "ap.lbl_change_note": {"id": "Catatan perubahan", "en": "Change note"},
    "ap.help_change_note": {"id": "Wajib — menjelaskan versi ini di riwayat.",
                            "en": "Required — explains this version in the history."},

    # ── Tombol ───────────────────────────────────────────────────────────
    "ap.btn_finish": {"id": "Selesaikan", "en": "Finish"},
    "ap.btn_download_file": {"id": "Unduh berkas ini", "en": "Download this file"},
    "ap.btn_create_account": {"id": "Buat akun", "en": "Create account"},
    "ap.btn_submit_review": {"id": "Ajukan untuk ditinjau", "en": "Submit for review"},
    "ap.btn_upload_validate": {"id": "Unggah & Validasi", "en": "Upload & Validate"},
    "ap.btn_save_dataset": {"id": "Simpan dataset", "en": "Save dataset"},
    "ap.btn_check_compat": {"id": "Periksa kecocokan dataset",
                            "en": "Check dataset compatibility"},
    "ap.btn_back": {"id": "← Kembali", "en": "← Back"},
    "ap.btn_deactivate": {"id": "Nonaktifkan", "en": "Deactivate"},
    "ap.btn_reactivate": {"id": "Aktifkan kembali", "en": "Reactivate"},
    "ap.btn_history": {"id": "Riwayat", "en": "History"},
    "ap.btn_yes_deactivate": {"id": "Ya, nonaktifkan", "en": "Yes, deactivate"},
    "ap.btn_back_history": {"id": "← Kembali ke riwayat", "en": "← Back to history"},
    "ap.btn_compare_versions": {"id": "Bandingkan versi", "en": "Compare versions"},
    "ap.btn_back_active": {"id": "← Kembali ke daftar aktif",
                           "en": "← Back to the active list"},
    "ap.btn_close_editor": {"id": "Tutup penyunting", "en": "Close editor"},
    "ap.btn_save_version": {"id": "Simpan sebagai versi baru",
                            "en": "Save as a new version"},
    "ap.btn_revert": {"id": "Kembalikan", "en": "Revert"},
    "ap.btn_yes_revert": {"id": "Ya, kembalikan", "en": "Yes, revert"},

    # ── Penolakan izin ───────────────────────────────────────────────────
    "ap.denied_review": {"id": "Hanya Research Admin yang dapat meninjau pengajuan.",
                         "en": "Only a Research Admin can review submissions."},
    "ap.denied_users": {"id": "Hanya Research Admin yang dapat mengelola pengguna.",
                        "en": "Only a Research Admin can manage users."},

    # ── Pesan hasil ──────────────────────────────────────────────────────
    "ap.msg_need_reject_reason": {
        "id": "Isi alasan penolakan pada Catatan tinjauan dulu.",
        "en": "Enter the reason for rejection in the Review note first."},
    "ap.msg_not_compatible_yet": {
        "id": "Belum cocok dengan research pipeline mana pun — tetap boleh disimpan.",
        "en": "Not compatible with any research pipeline yet — it can still be saved."},
    "ap.msg_versions_unreadable": {
        "id": "Berkas kedua versi tidak terbaca — tidak ada yang dapat dibandingkan.",
        "en": "Neither version's files could be read — there is nothing to compare."},
    "ap.msg_validation_passed": {"id": "Validasi lolos untuk seluruh berkas.",
                                 "en": "Validation passed for every file."},
    "ap.msg_validation_failed": {"id": "Validasi belum lolos.",
                                 "en": "Validation has not passed."},
    "ap.msg_check_stale": {
        "id": "Hasil pemeriksaan sebelumnya tidak berlaku lagi karena kode berubah.",
        "en": "The previous check no longer applies because the code changed."},

    # ── help= ────────────────────────────────────────────────────────────
    "ap.help_pending": {
        "id": "Hanya pipeline yang ditinjau — isinya kode yang dieksekusi; "
              "dataset tersimpan langsung.",
        "en": "Only pipelines are reviewed — they contain code that gets "
              "executed; datasets are stored directly."},
    "ap.help_reject_reason": {"id": "Alasan wajib diisi pada Catatan tinjauan.",
                              "en": "A reason is required in the Review note."},
    "ap.help_multi_file": {
        "id": "Boleh lebih dari satu berkas .py. Tepat satu di antaranya "
              "menjadi entry point.",
        "en": "More than one .py file is allowed. Exactly one of them must be "
              "the entry point."},
    "ap.help_file_role": {"id": "Penjelasan singkat untuk peninjau.",
                          "en": "A short explanation for the reviewer."},
    "ap.help_registry_type": {"id": "Menentukan dataset_type pada entri registry.",
                              "en": "Sets dataset_type on the registry entry."},
    "ap.help_optional_report": {"id": "Opsional — ikut ditampilkan pada laporan.",
                                "en": "Optional — also shown on the report."},
    "ap.help_open_outside": {"id": "Membuka penuh di luar aplikasi bila berkasnya panjang.",
                             "en": "Opens in full outside the app if the file is long."},
    "ap.help_edit_new_version": {"id": "Menyimpan akan membuat versi baru.",
                                 "en": "Saving creates a new version."},
    "ap.help_reactivate": {"id": "Pipeline dapat dipilih lagi untuk eksperimen baru.",
                           "en": "The pipeline can be chosen again for new experiments."},
    "ap.help_compare_readonly": {
        "id": "Baca-saja. Tidak ada versi yang dapat dipulihkan atau diterapkan "
              "dari sini.",
        "en": "Read-only. No version can be restored or applied from here."},
    "ap.help_show_diff": {"id": "Tunjukkan baris mana yang berbeda antar dua versi.",
                          "en": "Show which lines differ between two versions."},
    "ap.help_check_first": {"id": "Periksa dulu; simpan hanya mungkin setelah lolos.",
                            "en": "Check first; saving is only possible once it passes."},
    "ap.help_entry_first": {"id": "Titik masuk lebih dulu; tanda • berarti berkas itu berubah.",
                            "en": "Entry point first; • marks a changed file."},
    "ap.help_static_only": {"id": "Validasi statis seluruh berkas; kode tidak dijalankan.",
                            "en": "Static validation of every file; the code is not executed."},
    "ap.help_revert_all": {"id": "Kembalikan seluruh berkas ke isi versi aktif.",
                           "en": "Revert every file to the active version's content."},
    "ap.help_unsaved_kept": {
        "id": "Suntingan yang belum disimpan tetap tersimpan di sesi ini dan "
              "masih ada saat penyunting dibuka lagi.",
        "en": "Unsaved edits stay in this session and are still there when the "
              "editor is reopened."},
    "ap.help_dataset_direct": {
        "id": "Tersimpan langsung setelah berkas lolos pemeriksaan kecocokan — "
              "dataset tidak melewati peninjauan.",
        "en": "Stored immediately once the file passes the compatibility "
              "check — datasets do not go through review."},
    "ap.help_submit_review": {
        "id": "Paket diajukan untuk ditinjau Research Admin. Menyetujui "
              "menandai paket sebagai layak, bukan mengaktifkannya.",
        "en": "The package is submitted for Research Admin review. Approving "
              "marks it as acceptable, not active."},


    # ═══════════════════════════════════════════════════════════════════
    # PESAN VALIDATOR  (Tahap 3)
    # ═══════════════════════════════════════════════════════════════════
    # Nilai sisipan TIDAK diterjemahkan: {module}, {call}, {cls}, {line} adalah
    # nama dan angka apa adanya. Yang berbahasa hanya kalimat pembungkusnya.
    #
    # Alasan penolakan keamanan tetap SPESIFIK di kedua bahasa — nama modul /
    # pemanggilan yang terdeteksi dan sebabnya ikut tercetak, tidak pernah
    # menyusut menjadi "kode tidak aman".

    # ── Struktur ─────────────────────────────────────────────────────────
    "vc.no_base_class": {
        "id": "Tidak ditemukan kelas turunan `{base}`. Pipeline harus berupa "
              "kelas yang mewarisi `{base}` (lihat `pipelines/base.py`).",
        "en": "No subclass of `{base}` was found. A pipeline must be a class "
              "that inherits `{base}` (see `pipelines/base.py`)."},
    "vc.base_class_ok": {
        "id": "Kelas `{cls}` mewarisi `{base}`.",
        "en": "Class `{cls}` inherits `{base}`."},
    "vc.base_class_indirect": {
        "id": "Kelas `{cls}` tidak mewarisi `{base}` secara langsung, melainkan "
              "{bases}. Pastikan kelas induk itu turunan `{base}`.",
        "en": "Class `{cls}` does not inherit `{base}` directly, but {bases}. "
              "Make sure that parent class is a subclass of `{base}`."},
    "vc.method_ok": {
        "id": "`{method}()` diimplementasi pada `{cls}`.",
        "en": "`{method}()` is implemented on `{cls}`."},
    "vc.method_missing": {
        "id": "Method `{method}()` belum diimplementasi pada `{cls}`.",
        "en": "Method `{method}()` is not implemented on `{cls}`."},
    "vc.method_missing_inherited": {
        "id": "Method `{method}()` belum diimplementasi pada `{cls}` (mungkin "
              "diwarisi dari kelas induk — tidak dapat diperiksa dari berkas "
              "ini saja).",
        "en": "Method `{method}()` is not implemented on `{cls}` (it may be "
              "inherited from a parent class — this file alone cannot tell)."},

    # ── Keamanan: import & pemanggilan ───────────────────────────────────
    "vc.import_forbidden": {
        "id": "Penggunaan modul `{module}` tidak diizinkan pada pipeline yang "
              "diunggah ({reason}). Terdeteksi di baris {line}.",
        "en": "Module `{module}` is not allowed in an uploaded pipeline "
              "({reason}). Detected on line {line}."},
    "vc.call_forbidden": {
        "id": "Pemanggilan `{call}()` tidak diizinkan ({reason}). Terdeteksi "
              "di baris {line}.",
        "en": "Calling `{call}()` is not allowed ({reason}). Detected on "
              "line {line}."},
    "vc.reflection_on_module": {
        "id": "`{call}()` pada objek modul `{target}` tidak diizinkan "
              "(menghindari pemeriksaan import). Terdeteksi di baris {line}.",
        "en": "`{call}()` on module object `{target}` is not allowed (it "
              "bypasses the import check). Detected on line {line}."},
    "vc.reflection_warn": {
        "id": "`{call}()` dipakai di baris {line} — pastikan targetnya bukan "
              "modul.",
        "en": "`{call}()` is used on line {line} — make sure its target is "
              "not a module."},
    "vc.file_write": {
        "id": "`open()` dengan mode tulis/timpa tidak diizinkan (baris {line}); "
              "pipeline hanya boleh membaca dataset dan mengembalikan "
              "PipelineResult.",
        "en": "`open()` in a write/overwrite mode is not allowed (line "
              "{line}); a pipeline may only read the dataset and return a "
              "PipelineResult."},
    "vc.module_unknown": {
        "id": "Modul `{module}` bukan pustaka ML yang biasa dipakai platform "
              "ini (baris {line}). Periksa manual sebelum diaktifkan.",
        "en": "Module `{module}` is not one of the ML libraries this platform "
              "normally uses (line {line}). Review it manually before "
              "activating."},

    # ── Keterangan WAJIB yang menyertai hasil pemeriksaan ────────────────
    "vc.static_only": {
        "id": "Pemeriksaan bersifat statis — berkas dibaca, tidak dijalankan.",
        "en": "The check is static — the file is read, never executed."},
    "vc.pass_is_not_active": {
        "id": "Lolos pemeriksaan tidak berarti pipeline langsung aktif.",
        "en": "Passing the check does not make the pipeline active."},
    "vc.sample_based": {
        "id": "Angka di atas berbasis cuplikan, bukan seluruh berkas.",
        "en": "The numbers above are based on a sample, not the whole file."},
    "vc.metric_semantics": {
        "id": "Metrik antar keluarga pipeline tidak selalu bermakna sama — "
              "bandingkan hanya dalam satu keluarga.",
        "en": "Metrics do not mean the same thing across pipeline families — "
              "compare only within one family."},
    "vc.run_mode_note": {
        "id": "Run resmi memakai parameter terkunci; run eksplorasi boleh "
              "mengubahnya, jadi keduanya tidak sebanding langsung.",
        "en": "Official runs use locked parameters; exploration runs may "
              "change them, so the two are not directly comparable."},
    "vc.old_versions_kept": {
        "id": "Versi lama tetap tersimpan — eksperimen terdahulu tetap "
              "tertelusur.",
        "en": "Older versions are kept — earlier experiments stay traceable."},


    # ═══════════════════════════════════════════════════════════════════
    # DIAGNOSA KECOCOKAN DATASET  (Tahap 3)
    # ═══════════════════════════════════════════════════════════════════
    # `key` pemeriksaan ("format", "label", …) adalah PENGENAL keputusan dan
    # tidak diterjemahkan; yang berbahasa hanya judul & kalimatnya.
    "dx.title_format": {"id": "Format berkas", "en": "File format"},
    "dx.title_label": {"id": "Kolom label", "en": "Label column"},
    "dx.title_features": {"id": "Kolom fitur", "en": "Feature columns"},
    "dx.title_dtype": {"id": "Tipe data fitur", "en": "Feature data types"},
    "dx.title_classes": {"id": "Distribusi kelas", "en": "Class distribution"},

    # Saran tindakan tetap DAPAT DITINDAKLANJUTI di kedua bahasa: nama kolom
    # yang diharapkan dan format berkasnya ikut disebut, bukan disamarkan.
    "dx.unknown_type": {
        "id": "Tipe dataset `{dataset_type}` tidak dikenal.",
        "en": "Dataset type `{dataset_type}` is not recognised."},
    "dx.sample_note": {
        "id": "Angka di atas berasal dari cuplikan {rows} baris pertama, bukan "
              "seluruh berkas.",
        "en": "The numbers above come from a sample of the first {rows} rows, "
              "not the whole file."},

    # ═══════════════════════════════════════════════════════════════════
    # LAPORAN PDF & EKSPOR TABEL  (Tahap 3)
    # ═══════════════════════════════════════════════════════════════════
    # Istilah metrik (accuracy, precision, …) dan nama pipeline TIDAK
    # diterjemahkan — keduanya termasuk daftar yang dilindungi.
    "rpt.title": {"id": "Laporan Eksperimen", "en": "Experiment Report"},
    "rpt.sec_summary": {"id": "Ringkasan", "en": "Summary"},
    "rpt.sec_metrics": {"id": "Metrik", "en": "Metrics"},
    "rpt.sec_dataset": {"id": "Dataset", "en": "Dataset"},
    "rpt.sec_pipeline": {"id": "Research Pipeline", "en": "Research Pipeline"},
    "rpt.sec_params": {"id": "Parameter", "en": "Parameters"},
    "rpt.lbl_run_mode": {"id": "Mode eksekusi", "en": "Run mode"},
    "rpt.lbl_generated": {"id": "Dibuat pada", "en": "Generated at"},
    "rpt.note_official": {
        "id": "Run resmi — memakai parameter terkunci pipeline.",
        "en": "Official run — uses the pipeline's locked parameters."},
    "rpt.note_exploration": {
        "id": "Run eksplorasi — parameter diubah dari nilai terkunci, jadi "
              "hasilnya tidak sebanding langsung dengan run resmi.",
        "en": "Exploration run — parameters were changed from the locked "
              "values, so the result is not directly comparable to an "
              "official run."},
    "rpt.note_reproducibility": {
        "id": "Seed tetap dan parameter tercatat, sehingga eksperimen ini "
              "dapat dijalankan ulang dengan hasil yang sama.",
        "en": "The seed is fixed and the parameters are recorded, so this "
              "experiment can be re-run with the same result."},

    "csv.col_metric_semantics": {
        "id": "Catatan semantik metrik",
        "en": "Metric semantics note"},
    "csv.note_metric_semantics": {
        "id": "Metrik antar keluarga pipeline tidak selalu bermakna sama — "
              "bandingkan hanya dalam satu keluarga.",
        "en": "Metrics do not mean the same thing across pipeline families — "
              "compare only within one family."},


    # ═══════════════════════════════════════════════════════════════════
    # KALIMAT DIAGNOSA KECOCOKAN DATASET  (Tahap 3A)
    # ═══════════════════════════════════════════════════════════════════
    # Nilai sisipan TIDAK diterjemahkan: {column}, {columns}, {keys},
    # {classes}, {count}, {tls}, {alerts} adalah nama kolom, nama kunci JSON,
    # nilai kelas, dan angka — apa adanya dari berkas pengguna.
    #
    # Saran tindakan tetap DAPAT DITINDAKLANJUTI: format yang dibutuhkan dan
    # nama kolom yang diharapkan ikut disebut, tidak digeneralisasi.

    # ── Format berkas ────────────────────────────────────────────────────
    "dx.format_ok_csv": {
        "id": "Terdeteksi {format} (satu baris per flow).",
        "en": "Detected {format} (one row per flow)."},
    "dx.format_ok_ndjson": {
        "id": "Terdeteksi {format} (satu objek JSON per baris).",
        "en": "Detected {format} (one JSON object per line)."},
    "dx.format_wrong": {
        "id": "Format terdeteksi **{detected}**, tetapi pipeline ini "
              "membutuhkan **{needed}**.",
        "en": "Detected format is **{detected}**, but this pipeline requires "
              "**{needed}**."},

    # ── Dilewati — BUKAN gagal ───────────────────────────────────────────
    # Bedanya harus terbaca: "belum sempat diperiksa", bukan "tidak memenuhi".
    "dx.skipped_format": {
        "id": "Tidak diperiksa karena format berkas belum sesuai.",
        "en": "Not checked — the file format does not match yet."},
    "dx.skipped_no_features": {
        "id": "Tidak ada kolom fitur untuk diperiksa.",
        "en": "No feature columns to check."},
    "dx.skipped_no_label": {
        "id": "Tidak dapat diperiksa tanpa kolom `{column}`.",
        "en": "Cannot be checked without the `{column}` column."},

    # ── Kolom label ──────────────────────────────────────────────────────
    "dx.label_found": {
        "id": "Kolom label `{column}` ditemukan.",
        "en": "Label column `{column}` was found."},
    "dx.label_missing": {
        "id": "Dataset Anda kurang kolom label `{column}`.",
        "en": "Your dataset is missing the label column `{column}`."},

    # ── Kolom fitur ──────────────────────────────────────────────────────
    "dx.features_none": {
        "id": "Tidak ada kolom fitur — berkas hanya berisi kolom label.",
        "en": "No feature columns — the file contains only the label column."},
    "dx.features_missing": {
        "id": "Dataset Anda kurang {count} kolom yang diminta skema: {columns}.",
        "en": "Your dataset is missing {count} columns required by the "
              "schema: {columns}."},
    "dx.features_ok": {
        "id": "{count} kolom selain label ditemukan; seluruh kolom yang "
              "diminta skema lengkap.",
        "en": "{count} columns besides the label were found; every column the "
              "schema requires is present."},

    # ── Tipe data fitur ──────────────────────────────────────────────────
    "dx.dtype_ok": {
        "id": "Seluruh kolom fitur bertipe numerik.",
        "en": "Every feature column is numeric."},
    "dx.dtype_non_numeric": {
        "id": "{count} kolom fitur bukan numerik dan akan diabaikan pipeline: "
              "{columns}.",
        "en": "{count} feature columns are not numeric and will be ignored by "
              "the pipeline: {columns}."},

    # ── Distribusi kelas ─────────────────────────────────────────────────
    "dx.classes_ok": {
        "id": "{count} kelas terdeteksi pada kolom `{column}`: {classes}.",
        "en": "{count} classes detected in column `{column}`: {classes}."},
    "dx.classes_single": {
        "id": "Hanya satu kelas terdeteksi pada kolom `{column}` ({classes}); "
              "pipeline butuh dua kelas (benign & attack).",
        "en": "Only one class was detected in column `{column}` ({classes}); "
              "the pipeline needs two classes (benign & attack)."},

    # ── EVE / Suricata ───────────────────────────────────────────────────
    # Maknanya harus UTUH: label tidak ada di berkas mentah, melainkan
    # DITURUNKAN dari alert Suricata. Menghilangkan bagian itu membuat
    # pengguna mengira berkasnya kurang kolom.
    "dx.eve_label_derived": {
        "id": "Kolom `{column}` tidak perlu ada — pipeline menurunkannya dari "
              "**alert Suricata**; {events} event dengan bukti alert ditemukan "
              "pada sampel.",
        "en": "The `{column}` column does not need to exist — the pipeline "
              "derives it from **Suricata alerts**; {events} events carrying "
              "alert evidence were found in the sample."},
    "dx.eve_label_no_alert": {
        "id": "Tidak ada bukti alert Suricata pada sampel, padahal `{column}` "
              "diturunkan dari alert (`event_type` = `alert`, atau objek "
              "`alert` yang memiliki `severity`). Label tidak dapat dibentuk.",
        "en": "No Suricata alert evidence in the sample, yet `{column}` is "
              "derived from alerts (`event_type` = `alert`, or an `alert` "
              "object carrying `severity`). The label cannot be built."},
    "dx.eve_keys_missing": {
        "id": "Dataset Anda kurang {count} kunci JSON yang diminta skema: "
              "{keys}.",
        "en": "Your dataset is missing {count} JSON keys required by the "
              "schema: {keys}."},
    "dx.eve_keys_ok": {
        "id": "Seluruh kunci skema ada; {events} event TLS ditemukan pada "
              "sampel.",
        "en": "Every schema key is present; {events} TLS events were found in "
              "the sample."},
    "dx.eve_no_tls": {
        "id": "Tidak ditemukan event TLS pada sampel (`app_proto`/`event_type` "
              "= `tls`, atau port TLS); pipeline ini hanya menganalisis "
              "trafik TLS.",
        "en": "No TLS events were found in the sample (`app_proto`/"
              "`event_type` = `tls`, or a TLS port); this pipeline analyses "
              "TLS traffic only."},
    "dx.eve_dtype_na": {
        "id": "Tidak berlaku — pipeline merekayasa & menyeleksi fiturnya "
              "sendiri (MI/RFE/PCA) dari field EVE mentah.",
        "en": "Not applicable — the pipeline engineers and selects its own "
              "features (MI/RFE/PCA) from the raw EVE fields."},
    "dx.eve_classes_ok": {
        "id": "Dua kelas dapat terbentuk pada sampel: {tls} event TLS dan "
              "{alerts} event beralert.",
        "en": "Both classes can be formed from the sample: {tls} TLS events "
              "and {alerts} alerting events."},
    "dx.eve_classes_no_alert": {
        "id": "Hanya satu kelas yang dapat terbentuk: tidak ada event `alert` "
              "pada sampel, sehingga kelas attack akan kosong.",
        "en": "Only one class can be formed: there are no `alert` events in "
              "the sample, so the attack class would be empty."},
    "dx.eve_classes_no_tls": {
        "id": "Hanya satu kelas yang dapat terbentuk: tidak ada event TLS pada "
              "sampel, sehingga kelas benign TLS akan kosong.",
        "en": "Only one class can be formed: there are no TLS events in the "
              "sample, so the benign TLS class would be empty."},


    # ── Perenderan hasil diagnosa ────────────────────────────────────────
    "dx.skipped_one": {
        "id": "dilewati: {reason}",
        "en": "skipped: {reason}"},
    "dx.skipped_others": {
        "id": "Pemeriksaan lain ({names}) dilewati: {reason}",
        "en": "Other checks ({names}) were skipped: {reason}"},
    "dx.unit_column": {"id": "kolom", "en": "columns"},
    "dx.unit_json_key": {"id": "kunci JSON", "en": "JSON keys"},


    # ── Kolom KETERANGAN pada ekspor CSV  (Tahap 3A) ─────────────────────
    # Hanya kolom keterangan yang berbahasa. Nama kolom DATA (metrik,
    # identitas eksperimen, nama pipeline) tetap sama supaya berkasnya dapat
    # diolah lintas bahasa.
    "csv.col_semantics": {"id": "Semantik metrik", "en": "Metric semantics"},
    "csv.col_mode": {"id": "Mode eksekusi", "en": "Run mode"},
    "csv.col_params": {"id": "Parameter dipakai", "en": "Parameters used"},
    "csv.family_unknown": {
        "id": "keluarga pipeline tidak dikenal",
        "en": "unknown pipeline family"},


    # ── Mode eksekusi: label, lencana, petunjuk  (Tahap 3A) ──────────────
    # Konstanta di orchestrator/run_mode.py TIDAK diubah — ia nilai bawaan
    # yang diimpor & diuji test lama. Yang ditambahkan hanya terjemahannya.
    "mode.official_label": {"id": "Run resmi", "en": "Official run"},
    "mode.exploration_label": {"id": "Run eksplorasi", "en": "Exploration run"},
    "mode.official_badge": {"id": "🔒 Resmi", "en": "🔒 Official"},
    "mode.exploration_badge": {"id": "🧪 Eksplorasi", "en": "🧪 Exploration"},
    "mode.official_hint": {
        "id": "Parameter terkunci sesuai paper rujukan.",
        "en": "Parameters locked to match the reference paper."},
    "mode.exploration_hint": {
        "id": "Parameter disesuaikan — di luar perbandingan resmi.",
        "en": "Parameters adjusted — outside the official comparison."},


    # Berkas gagal dibaca. Teks galatnya sendiri ({error}) berasal dari
    # pembacaan berkas dan termasuk lingkup Tahap 3B — diteruskan apa adanya.
    "dx.file_unreadable": {"id": "{error}", "en": "{error}"},
    "dx.skipped_unreadable": {
        "id": "Tidak dapat diperiksa karena berkas gagal dibaca.",
        "en": "Cannot be checked because the file could not be read."},


    # ── Sisa teks tertanam yang dipindahkan  (Tahap 3A) ──────────────────
    "ap.msg_no_match_anywhere": {
        "id": "Belum cocok dengan research pipeline mana pun. Penyebab dan "
              "langkah perbaikannya per pipeline ada di bawah.",
        "en": "Not compatible with any research pipeline yet. The cause and "
              "the fix for each pipeline are listed below."},


    # Header kolom tabel "Pengajuan saya".


    # ── Teks tertanam yang dipindahkan, batch 1  (Tahap 3A) ──────────────
    "app.menu_missing": {
        "id": "Catatan: streamlit-option-menu belum terpasang. Jalankan "
              "`pip install streamlit-option-menu` untuk tampilan menu yang "
              "lengkap.",
        "en": "Note: streamlit-option-menu is not installed. Run "
              "`pip install streamlit-option-menu` for the full menu."},
    "ctx.after_upload_q": {
        "id": "Apa yang terjadi setelah saya mengunggah?",
        "en": "What happens after I upload?"},
    "cat.stages_differ": {
        "id": "Tahapannya berbeda antar algoritma — grafnya mengikuti tahap "
              "yang benar-benar dijalankan masing-masing.",
        "en": "The stages differ between algorithms — the graph follows the "
              "stages each one actually runs."},
    "rv.no_feature_importance": {
        "id": "Pipeline ini tidak menyediakan *feature importance* (mis. "
              "K-Nearest Neighbors atau Gaussian Naive Bayes).",
        "en": "This pipeline provides no *feature importance* (e.g. "
              "K-Nearest Neighbors or Gaussian Naive Bayes)."},
    "rv.roc_reading": {
        "id": "Semakin kurva menjauhi garis diagonal (acuan acak, TPR = FPR), "
              "semakin baik model membedakan serangan dari trafik benign.",
        "en": "The further the curve sits from the diagonal (random baseline, "
              "TPR = FPR), the better the model separates attacks from benign "
              "traffic."},
    "rv.no_roc_points": {
        "id": "Titik kurva ROC (fpr/tpr) tidak tersedia; hanya nilai AUC yang "
              "dilaporkan.",
        "en": "ROC curve points (fpr/tpr) are not available; only the AUC "
              "value is reported."},
    "rmc.no_fixed_params": {
        "id": "Pipeline ini tidak mendeklarasikan `fixed_params`.",
        "en": "This pipeline declares no `fixed_params`."},
    "rmc.locked_params": {
        "id": "Parameter terkunci pipeline ini",
        "en": "This pipeline's locked parameters"},
    "rmc.adjustable_params": {
        "id": "**Parameter yang dapat disesuaikan**",
        "en": "**Parameters you can adjust**"},
    "rmc.reset_help": {
        "id": "Nilai bawaan pipeline menjadi titik awal; tombol ini "
              "mengembalikan seluruh isian ke nilai itu.",
        "en": "The pipeline's default values are the starting point; this "
              "button returns every field to them."},
    "rmc.differs_from_default": {
        "id": "Berbeda dari bawaan:",
        "en": "Differs from the default:"},
    "rmc.still_locked": {
        "id": "Parameter yang tetap terkunci",
        "en": "Parameters that stay locked"},


    # ═══════════════════════════════════════════════════════════════════
    # PESAN KESALAHAN — jalur galat  (Tahap 3B)
    # ═══════════════════════════════════════════════════════════════════
    # Tiap pesan menyebut APA yang terjadi dan, bila ada, APA yang dapat
    # dilakukan pengguna. Nilai sisipan (nama berkas, nama pipeline, nilai
    # hash) TIDAK diterjemahkan.

    # ── Integritas berkas ────────────────────────────────────────────────
    # Ini PENANDA INTEGRITAS, bukan kegagalan biasa: kalimatnya harus tetap
    # menyatakan bahwa berkasnya BERBEDA dari yang tercatat, lengkap dengan
    # kedua nilai hash — supaya dapat ditelusuri.
    "err.hash_mismatch": {
        "id": "Hash berkas tidak cocok untuk {file}: tercatat {recorded}…, "
              "ditemukan {found}…. Berkas berubah atau rusak — pemuatan "
              "ditolak. Muat ulang versi yang benar atau simpan ulang sebagai "
              "versi baru.",
        "en": "File hash does not match for {file}: recorded {recorded}…, "
              "found {found}…. The file changed or is corrupt — loading was "
              "refused. Restore the correct version, or save it again as a "
              "new version."},

    # ── Berkas tidak ditemukan ───────────────────────────────────────────
    "err.entry_file_missing": {
        "id": "Berkas entry point tidak ditemukan: {path}. Pastikan berkasnya "
              "masih ada sebelum mendaftarkan pipeline.",
        "en": "Entry-point file not found: {path}. Make sure the file still "
              "exists before registering the pipeline."},
    "err.pipeline_file_missing": {
        "id": "Berkas pipeline tidak ditemukan: {path}. Berkasnya mungkin "
              "dipindahkan atau dihapus dari server.",
        "en": "Pipeline file not found: {path}. It may have been moved or "
              "deleted on the server."},
    "err.research_name_taken": {"id": "Nama research \"{name}\" sudah dipakai research pipeline lain. Pilih nama yang berbeda.",
                                "en": "The research name \"{name}\" is already used by another research pipeline. Choose a different name."},
    "err.info_snapshot_failed": {"id": "Keterangan `{pipeline}` tidak dapat dibaca dari berkasnya.",
                                 "en": "The details for `{pipeline}` could not be read from its file."},
    "err.pipeline_not_registered": {
        "id": "Pipeline terdaftar tidak ditemukan: {pipeline}. Periksa daftar "
              "pipeline aktif di halaman Add Pipeline & Dataset.",
        "en": "Registered pipeline not found: {pipeline}. Check the active "
              "pipeline list on the Add Pipeline & Dataset page."},
    "err.research_not_found": {
        "id": "Research pipeline tidak ditemukan: {research}. Mungkin seluruh "
              "algoritmanya sudah dihapus.",
        "en": "Research pipeline not found: {research}. All of its algorithms "
              "may already have been deleted."},
    "err.research_builtin_readonly": {
        "id": "{research} adalah research pipeline bawaan: ia menjadi "
              "pembanding tetap, jadi kodenya tidak disunting dan "
              "ketersediaannya tidak diubah dari halaman ini.",
        "en": "{research} is a built-in research pipeline: it serves as the "
              "fixed baseline, so its code is not edited and its availability "
              "is not changed from this page."},

    # ── Hak akses ────────────────────────────────────────────────────────
    # Harus terbaca sebagai DITOLAK KARENA HAK, bukan kesalahan sistem.
    "err.denied_pending_account": {
        "id": "Akun Anda masih menunggu persetujuan Research Admin, jadi belum "
              "dapat mengunggah.",
        "en": "Your account is still awaiting Research Admin approval, so you "
              "cannot upload yet."},
    "err.denied_upload": {
        "id": "Masuk sebagai Kontributor atau Research Admin untuk mengunggah.",
        "en": "Sign in as a Contributor or Research Admin to upload."},
    "err.denied_approve": {
        "id": "Hanya Research Admin yang dapat menyetujui unggahan.",
        "en": "Only a Research Admin can approve uploads."},
    "err.denied_manage_users": {
        "id": "Hanya Research Admin yang dapat mengelola pengguna.",
        "en": "Only a Research Admin can manage users."},


    # ═══════════════════════════════════════════════════════════════════
    # LAPORAN PDF  (Tahap 3C)
    # ═══════════════════════════════════════════════════════════════════
    # Nama teknis pada kepala laporan ("Experiment ID", "Pipeline",
    # "Algoritma", "Dataset") sengaja TIDAK diterjemahkan — sama seperti nama
    # kolom pada ekspor CSV, supaya laporan tetap terbaca lintas bahasa.

    "rpt.main_title": {
        "id": "Laporan Eksperimen Deteksi Intrusi",
        "en": "Intrusion Detection Experiment Report"},
    "rpt.subtitle": {
        "id": "IDS Research Pipeline Execution System &mdash; artefak "
              "penelitian yang reproducible",
        "en": "IDS Research Pipeline Execution System &mdash; a reproducible "
              "research artifact"},
    "rpt.abstract_h": {"id": "Abstrak", "en": "Abstract"},
    "rpt.lbl_time": {"id": "Waktu (dibuat → selesai)",
                     "en": "Time (created → completed)"},
    "rpt.lbl_language": {"id": "Bahasa laporan", "en": "Report language"},
    "rpt.language_name": {"id": "Indonesia", "en": "English"},

    # ── Judul bagian ─────────────────────────────────────────────────────
    "rpt.sec_config": {"id": "Konfigurasi Eksperimen",
                       "en": "Experiment Configuration"},
    "rpt.sec_results": {"id": "Hasil dan Metrik", "en": "Results and Metrics"},
    "rpt.sec_security": {"id": "Interpretasi Keamanan",
                         "en": "Security Interpretation"},
    "rpt.sec_analysis": {"id": "Analisis Metrik", "en": "Metric Analysis"},
    "rpt.sec_features": {"id": "Fitur Berpengaruh", "en": "Influential Features"},
    "rpt.sec_diagnostics": {"id": "Diagnostik", "en": "Diagnostics"},
    "rpt.sec_methodology": {"id": "Catatan Metodologis",
                            "en": "Methodological Notes"},
    "rpt.sec_reproducibility": {"id": "Reproducibility", "en": "Reproducibility"},
    # ^ "Reproducibility" dipakai apa adanya di kedua bahasa: ia istilah baku
    #   dalam penulisan ilmiah Indonesia di bidang ini, dan padanan seperti
    #   "keterulangan" justru lebih sulit dikenali pembacanya.

    # ── Mode eksekusi pada laporan ───────────────────────────────────────
    "rpt.exploration_badge": {"id": "Run eksplorasi.", "en": "Exploration run."},
    "rpt.exploration_warning": {
        "id": "Parameter diubah dari nilai terkunci pipeline. Hasilnya TIDAK "
              "dipakai sebagai dasar replikasi paper rujukan maupun "
              "perbandingan resmi antar pipeline.",
        "en": "Parameters were changed from the pipeline's locked values. The "
              "result is NOT used as a basis for replicating the reference "
              "paper, nor for official comparison between pipelines."},


    # ═══════════════════════════════════════════════════════════════════
    # PANDUAN KONTRAK PIPELINE  (Tahap 4A)
    # ═══════════════════════════════════════════════════════════════════
    # Nama field kontrak (`fixed_params`, `PipelineResult`, `get_info`),
    # potongan kode, nama kelas, dan nama metode TIDAK diterjemahkan — ia
    # dibaca mesin dan disalin apa adanya oleh pengunggah.

    # ── Tahapan eksekusi ─────────────────────────────────────────────────
    # Pembagian tugas harus tetap terbaca: tahap 1 & 8 dikerjakan PLATFORM
    # sebelum/sesudah pipeline dipanggil; sisanya tanggung jawab PIPELINE.
    # Kalimatnya tidak boleh menyiratkan pipeline mengerjakan semuanya.
    "ins.stage1_name": {"id": "Validasi masukan", "en": "Validate input"},
    "ins.stage1_note": {
        "id": "Dataset diparsing & diperiksa platform SEBELUM pipeline "
              "dipanggil.",
        "en": "The platform parses and checks the dataset BEFORE the pipeline "
              "is called."},
    "ins.stage2_name": {"id": "Pisah latih/uji", "en": "Split train/test"},
    "ins.stage2_note": {"id": "Split sebelum praproses apa pun.",
                        "en": "Split before any preprocessing."},
    "ins.stage3_name": {"id": "Fit praproses pada data latih SAJA",
                        "en": "Fit preprocessing on the TRAINING data only"},
    "ins.stage3_note": {
        "id": "Scaler/PCA/penyeimbang di-fit hanya di data latih.",
        "en": "Scaler/PCA/balancer are fitted on the training data only."},
    "ins.stage4_name": {"id": "Transformasi latih & uji",
                        "en": "Transform train & test"},
    "ins.stage4_note": {
        "id": "Data uji hanya ditransformasi, tidak pernah ikut di-fit.",
        "en": "Test data is only transformed, never fitted on."},
    "ins.stage5_name": {"id": "Latih model", "en": "Train the model"},
    "ins.stage5_note": {"id": "Parameter terkunci dari fixed_params.",
                        "en": "Parameters locked from fixed_params."},
    "ins.stage6_name": {"id": "Prediksi data uji", "en": "Predict the test data"},
    "ins.stage7_name": {"id": "Hitung metrik", "en": "Compute metrics"},
    "ins.stage8_name": {"id": "Simpan artefak", "en": "Store artifacts"},
    "ins.stage8_note": {
        "id": "Model, metrik, dan metadata ditulis PLATFORM, bukan pipeline.",
        "en": "The model, metrics, and metadata are written by the PLATFORM, "
              "not by the pipeline."},
    "ins.stage9_name": {"id": "Kembalikan PipelineResult",
                        "en": "Return a PipelineResult"},

    # ── Daftar LARANGAN — tegas, tidak diperhalus ────────────────────────
    # Inilah rumusan yang memisahkan masukan yang dikendalikan pengguna dari
    # parameter yang ditetapkan eksperimen. Melemahkannya menghapus dasar
    # perbandingan yang adil.
    "ins.forbid_dataset": {
        "id": "Mengubah dataset asli.",
        "en": "Modifying the original dataset."},
    "ins.forbid_params": {
        "id": "Mengubah hyperparameter terkunci sendiri saat berjalan — "
              "penyesuaian hanya lewat run eksplorasi platform, yang mencatat "
              "& menandainya.",
        "en": "Changing its own locked hyperparameters at run time — "
              "adjustments happen only through the platform's exploration "
              "run, which records and flags them."},
    "ins.forbid_fit_test": {
        "id": "Fit praproses pada data uji.",
        "en": "Fitting preprocessing on the test data."},
    "ins.forbid_algorithm": {
        "id": "Mengganti algoritma secara dinamis.",
        "en": "Swapping the algorithm dynamically."},
    "ins.forbid_features": {
        "id": "Mengubah seleksi fitur secara acak / tidak dideklarasikan.",
        "en": "Changing feature selection arbitrarily or without declaring it."},
    "ins.forbid_frame": {
        "id": "Ini yang memisahkan masukan yang dikendalikan pengguna dari "
              "parameter yang ditetapkan eksperimen — dasar perbandingan yang "
              "adil dan hasil yang dapat diulang.",
        "en": "This is what separates user-controlled input from the "
              "parameters the experiment fixes — the basis for a fair "
              "comparison and a repeatable result."},

    # ── Keterangan WAJIB ─────────────────────────────────────────────────
    "ins.anti_leak": {
        "id": "Langkah 2–3 adalah aturan anti-kebocoran: split DULU, baru fit "
              "praproses — dan hanya pada data latih.",
        "en": "Steps 2–3 are the anti-leakage rule: split FIRST, then fit "
              "preprocessing — and only on the training data."},
    "ins.suggested_info": {
        "id": "Disarankan, bukan wajib: tidak diperiksa validator dan pipeline "
              "bawaan pun belum menyediakannya.",
        "en": "Suggested, not required: the validator does not check it, and "
              "the built-in pipelines do not provide it either."},
    "ins.required_info": {
        "id": "Wajib: disebut kontrak BasePipeline dan diperiksa validator.",
        "en": "Required: named by the BasePipeline contract and checked by "
              "the validator."},
    "ins.static_check": {
        "id": "Pemeriksaan bersifat statis — berkas DIBACA, tidak dijalankan.",
        "en": "The check is static — the file is READ, never executed."},
    "ins.pass_not_active": {
        "id": "Lolos pemeriksaan tidak berarti pipeline langsung aktif: ia "
              "masih menunggu tinjauan Research Admin.",
        "en": "Passing the check does not make the pipeline active: it still "
              "awaits Research Admin review."},

    # ── Pemilik tahap ────────────────────────────────────────────────────
    "ins.owner_platform": {"id": "Platform", "en": "Platform"},
    "ins.owner_pipeline": {"id": "Pipeline", "en": "Pipeline"},


    # ── Run Experiment: sisa teks tertanam  (Tahap 4A) ───────────────────
    "re.help_pick_dataset": {
        "id": "Pilih satu berkas untuk melihat preview, hasil validasi, dan "
              "pipeline yang kompatibel.",
        "en": "Choose one file to see its preview, validation result, and "
              "compatible pipelines."},


    # ── Run Experiment: sisa teks tertanam, lanjutan  (Tahap 4A) ─────────
    # Nilai sisipan (nama tipe dataset, ekstensi berkas, jumlah, nama pipeline)
    # TIDAK diterjemahkan.
    "re.empty_no_file_of_type": {
        "id": "Belum ada berkas dataset bertype **{dtype}** (`{ext}`) di "
              "`storage/datasets/`. Tambahkan berkas ke folder tersebut untuk "
              "memulai.",
        "en": "No dataset file of type **{dtype}** (`{ext}`) in "
              "`storage/datasets/` yet. Add a file to that folder to start."},
    # PROMPT, bukan label pendek: ia pertanyaan lengkap di atas daftar
    # pilihan, dan teksnya memang sudah begitu sebelum dipindahkan ke
    # kamus. Aturan "label widget = frasa pendek" berlaku untuk label
    # yang berdiri di samping kontrol, bukan untuk prompt seperti ini.
    "re.prompt_matching_files": {
        "id": "Berkas yang cocok di `storage/datasets/` (filter: `{ext}`):",
        "en": "Matching files in `storage/datasets/` (filter: `{ext}`):"},
    "re.msg_probably_wrong_type": {
        "id": "Sepertinya berkas ini **bukan** dataset `{dtype}`. Jalankan "
              "**Uji kecocokan** pada kotak di bawah untuk melihat research "
              "pipeline yang sesuai beserta langkah perbaikannya.",
        "en": "This file is probably **not** a `{dtype}` dataset. Run the "
              "**compatibility test** in the box below to see which research "
              "pipelines fit, and how to fix it."},
    "re.exp_see_all_missing": {
        "id": "Lihat semua {count} {unit} yang diminta skema",
        "en": "See all {count} {unit} the schema requires"},
    "re.msg_no_auto_match": {
        "id": "Dataset belum otomatis cocok dengan pipeline mana pun. Pilih "
              "salah satu untuk menjalankan uji kecocokan.",
        "en": "The dataset does not automatically fit any pipeline yet. "
              "Choose one to run the compatibility test."},
    "re.msg_catalog_pick_dropped": {
        "id": "`{pipeline}` tidak kompatibel dengan dataset yang dipilih, jadi "
              "pilihan dari katalog tidak dipasang. Pilih dataset yang sesuai, "
              "atau pilih pipeline lain di bawah.",
        "en": "`{pipeline}` is not compatible with the selected dataset, so "
              "the catalog choice was not applied. Pick a matching dataset, or "
              "choose another pipeline below."},
    "re.msg_n_datasets_match": {
        "id": "{count} dataset di server cocok untuk research pipeline ini. "
              "Pilih satu untuk melanjutkan.",
        "en": "{count} datasets on the server fit this research pipeline. "
              "Choose one to continue."},
    "re.empty_no_dataset_files": {
        "id": "Belum ada berkas dataset di `storage/datasets/`. Tambahkan "
              "berkas CSV (HIKARI2021) atau NDJSON (EVE Suricata) untuk "
              "memulai.",
        "en": "No dataset files in `storage/datasets/` yet. Add a CSV "
              "(HIKARI2021) or NDJSON (EVE Suricata) file to start."},
    "re.msg_upload_qualifying": {
        "id": "Unggah dataset yang memenuhi syarat di atas lewat halaman "
              "**Add Pipeline & Dataset**; berkasnya langsung dapat dipilih "
              "di sini.",
        "en": "Upload a dataset meeting the requirements above from the "
              "**Add Pipeline & Dataset** page; it becomes selectable here "
              "right away."},
    "re.help_pick_algorithm_first": {
        "id": "Pilih algoritma di bawah untuk melihat preprocessing & "
              "hyperparameter spesifik algoritma tersebut.",
        "en": "Choose an algorithm below to see the preprocessing and "
              "hyperparameters specific to it."},


    # ── Add Pipeline & Dataset: sisa teks tertanam  (Tahap 4A) ───────────
    # Nilai sisipan (nama berkas, ukuran, nomor pengajuan) TIDAK diterjemahkan.
    "ap.help_only_pipelines_reviewed": {
        "id": "Hanya pipeline yang ditinjau — isinya kode yang dieksekusi; "
              "dataset tersimpan langsung.",
        "en": "Only pipelines are reviewed — they contain code that gets "
              "executed; datasets are stored directly."},
    "ap.msg_legacy_dataset_submission": {
        "id": "**Pengajuan dataset lama** — dataset tidak lagi memerlukan "
              "persetujuan. Selesaikan pengajuan ini untuk membersihkan "
              "antrean.",
        "en": "**Legacy dataset submission** — datasets no longer need "
              "approval. Finish this one to clear the queue."},
    "ap.note_support_file": {
        "id": "Berkas pendukung: kontrak pipeline tidak berlaku, aturan "
              "keamanan tetap penuh — berkas ini ikut dieksekusi saat pipeline "
              "berjalan.",
        "en": "Support file: the pipeline contract does not apply, but the "
              "security rules do in full — this file is executed too when the "
              "pipeline runs."},
    "ap.note_user_list": {
        "id": "**Daftar pengguna** — password tidak pernah ditampilkan; hanya "
              "turunan bersaltnya yang disimpan.",
        "en": "**User list** — passwords are never shown; only their salted "
              "derivative is stored."},
    "ap.empty_no_accounts": {"id": "Belum ada akun.", "en": "No accounts yet."},
    "ap.msg_fix_then_reupload": {
        "id": "Perbaiki poin ✖ di atas lalu unggah ulang. Unduhan dan cuplikan "
              "registry muncul setelah paket valid.",
        "en": "Fix the ✖ items above, then upload again. The download and the "
              "registry snippet appear once the package is valid."},
    "ap.msg_valid_not_active": {
        "id": "Paket valid — pipeline **belum aktif**, menunggu aktivasi "
              "manual.",
        "en": "Package is valid — the pipeline is **not active yet**, it "
              "awaits manual activation."},
    "ap.msg_submitted_n": {
        "id": "Diajukan sebagai pengajuan #{number}. Menunggu peninjauan "
              "Research Admin — pipeline ini **belum** aktif dan belum dapat "
              "dijalankan.",
        "en": "Submitted as submission #{number}. Awaiting Research Admin "
              "review — this pipeline is **not** active and cannot be run "
              "yet."},
    "ap.step_place_files": {
        "id": "1. Letakkan berkas paket di `pipelines/<subdirektori riset>/`.",
        "en": "1. Place the package files in "
              "`pipelines/<research subdirectory>/`."},
    "ap.note_static_not_absolute": {
        "id": "Validasi statis menyaring masalah umum, bukan jaminan mutlak — "
              "tinjauan manusia tetap diperlukan.",
        "en": "Static validation filters common problems; it is not an "
              "absolute guarantee — human review is still required."},
    "ap.note_metadata": {
        "id": "**Metadata pipeline** — mengisi cuplikan entri registry; tidak "
              "memengaruhi hasil validasi.",
        "en": "**Pipeline metadata** — fills the registry snippet; it does not "
              "affect the validation result."},
    "ap.note_checked_against_all": {
        "id": "Kecocokan berkas diperiksa terhadap seluruh research pipeline "
              "sekaligus — tidak perlu memilih pipeline lebih dulu.",
        "en": "The file's compatibility is checked against every research "
              "pipeline at once — no need to choose a pipeline first."},
    "ap.err_file_exists": {
        "id": "`{filename}` sudah ada di `storage/datasets/`. Ganti nama "
              "berkasnya — platform tidak menimpa dataset yang sudah ada.",
        "en": "`{filename}` already exists in `storage/datasets/`. Rename the "
              "file — the platform never overwrites an existing dataset."},
    "ap.msg_saved_as": {
        "id": "Tersimpan sebagai `{filename}` ({size}). Sudah dapat dipilih di "
              "halaman Run Experiment.",
        "en": "Saved as `{filename}` ({size}). It can now be selected on the "
              "Run Experiment page."},
    "ap.help_register_existing": {
        "id": "Berkas yang sudah berada di `storage/datasets/`. Tidak ada "
              "penyalinan dan tidak ada batas ukuran.",
        "en": "Files already in `storage/datasets/`. Nothing is copied and "
              "there is no size limit."},
    "ap.empty_no_files_on_server": {
        "id": "Belum ada berkas di `storage/datasets/`. Salin berkas ke folder "
              "tersebut di server, lalu segarkan halaman ini.",
        "en": "No files in `storage/datasets/` yet. Copy a file into that "
              "folder on the server, then refresh this page."},


    "ap.note_no_registry_write": {
        "id": "Platform tidak menulis ke registry atau ke `pipelines/`, dan "
              "tidak menjalankan berkas yang diunggah.",
        "en": "The platform does not write to the registry or to `pipelines/`, "
              "and never executes an uploaded file."},


    # ── Sisa berkas UI  (Tahap 4A) ───────────────────────────────────────
    # _artifact_browser
    "ab.empty_no_files": {"id": "Tidak ada berkas untuk ditampilkan.",
                          "en": "No files to show."},
    "ab.binary_no_preview": {
        "id": "Berkas biner tidak dapat di-preview. Gunakan tombol unduh di "
              "bawah.",
        "en": "Binary files cannot be previewed. Use the download button "
              "below."},

    # login
    "auth.account_created": {
        "id": "Akun dibuat dan langsung aktif — silakan masuk.",
        "en": "Account created and active right away — please sign in."},
    "auth.no_account_yet": {
        "id": "Belum punya akun? Pilih **Daftar** di atas untuk mengajukan "
              "akun Kontributor.",
        "en": "No account yet? Choose **Sign up** above to request a "
              "Contributor account."},
    "auth.bad_credentials": {
        "id": "Username atau password salah.",
        "en": "Wrong username or password."},
    "auth.too_many_signups": {
        "id": "Terlalu banyak pendaftaran dari sesi ini. Muat ulang halaman "
              "bila memang perlu mendaftar lagi.",
        "en": "Too many sign-ups from this session. Reload the page if you "
              "genuinely need to register again."},
    "auth.reason_help": {
        "id": "Dicatat untuk ketertelusuran; tidak menahan pembuatan akun.",
        "en": "Recorded for traceability; it does not hold up account "
              "creation."},
    "auth.have_account": {
        "id": "Sudah punya akun? Pilih **Masuk** di atas.",
        "en": "Already have an account? Choose **Sign in** above."},
    "auth.dialog_title": {"id": "Masuk atau Daftar", "en": "Sign in or Sign up"},

    # manage_pipelines
    "ap.help_active_list": {
        "id": "Pipeline kontribusi beserta versi, hash, dan pemakaiannya. Yang "
              "dinonaktifkan tetap tampil.",
        "en": "Contributed pipelines with their version, hash, and usage. "
              "Deactivated ones are still listed."},
    "ap.note_inactive_n": {
        "id": "**Nonaktif ({count})** — tidak dapat dipilih untuk eksperimen "
              "baru; catatan & berkasnya tetap utuh.",
        "en": "**Inactive ({count})** — cannot be chosen for new experiments; "
              "its records and files stay intact."},
    "ap.help_history_columns": {
        "id": "Setiap versi beserta hash, penyunting, waktu, catatan, status, "
              "dan jumlah pemakaiannya.",
        "en": "Every version with its hash, editor, time, note, status, and "
              "usage count."},
    "ap.empty_no_versions": {
        "id": "Tidak ada versi tercatat untuk `{pipeline}`.",
        "en": "No versions recorded for `{pipeline}`."},
    "ap.diff_unchanged_lines": {
        "id": "{count} baris tidak berubah",
        "en": "{count} unchanged lines"},
    "ap.msg_running_uses_version": {
        "id": "{count} eksperimen sedang BERJALAN memakai versi ini. Menyimpan "
              "versi baru tidak mengubahnya — eksekusi itu sudah memuat berkas "
              "versi lama, yang tetap tersimpan.",
        "en": "{count} experiments are RUNNING on this version. Saving a new "
              "version does not change them — those runs already loaded the "
              "old version's files, which stay stored."},
    "ap.msg_saved_new_version": {
        "id": "Tersimpan sebagai **v{version}** (`{pipeline}`), hash "
              "`{hash}` — versi ini kini aktif. Versi sebelumnya tetap "
              "tersimpan.",
        "en": "Saved as **v{version}** (`{pipeline}`), hash `{hash}` — this "
              "version is now active. The previous one stays stored."},

    # view_results
    "ps.empty_history_alt": {
        "id": "Belum ada eksperimen. Buka halaman 'Run Experiment' untuk "
              "membuat satu.",
        "en": "No experiments yet. Open the 'Run Experiment' page to create "
              "one."},
    "ps.help_csv_export": {
        "id": "Mengikuti kolom & filter yang sedang aktif, lengkap dengan "
              "keterangan semantik metrik per baris.",
        "en": "Follows the active columns and filters, including the "
              "per-row metric-semantics note."},
    "ps.msg_new_experiments": {
        "id": "Baru: `{ids}` — tutup dan segarkan.",
        "en": "New: `{ids}` — close and refresh."},
    "ps.note_params_legacy": {
        "id": "Parameter (definisi pipeline saat ini — eksperimen ini "
              "dijalankan sebelum parameter dicatat per eksperimen).",
        "en": "Parameters (the pipeline's current definition — this "
              "experiment ran before parameters were recorded per "
              "experiment)."},


    # ═══════════════════════════════════════════════════════════════════
    # PESAN KESALAHAN: auth_service  (Tahap 4B)
    # ═══════════════════════════════════════════════════════════════════
    # Nilai sisipan (username, batas panjang, nama peran/status) TIDAK
    # diterjemahkan. Tiap pesan menyebut APA yang salah dan apa yang harus
    # dilakukan pengguna.
    "err.password_empty": {
        "id": "Password tidak boleh kosong.",
        "en": "The password cannot be empty."},
    "err.username_empty": {
        "id": "Username tidak boleh kosong.",
        "en": "The username cannot be empty."},
    "err.password_min": {
        "id": "Password minimal {min} karakter.",
        "en": "The password must be at least {min} characters."},
    "err.username_min": {
        "id": "Username minimal {min} karakter.",
        "en": "The username must be at least {min} characters."},
    "err.username_max": {
        "id": "Username maksimal {max} karakter.",
        "en": "The username may be at most {max} characters."},
    "err.username_charset": {
        "id": "Username hanya boleh huruf, angka, titik, garis bawah, atau "
              "tanda hubung.",
        "en": "A username may contain only letters, digits, dots, "
              "underscores, or hyphens."},
    "err.password_mismatch": {
        "id": "Konfirmasi password tidak sama.",
        "en": "The password confirmation does not match."},
    "err.username_taken": {
        "id": "Username '{username}' sudah dipakai. Pilih nama lain.",
        "en": "Username '{username}' is already taken. Choose another one."},
    "err.unknown_role": {
        "id": "Role tidak dikenal: {role}",
        "en": "Unknown role: {role}"},
    "err.unknown_status": {
        "id": "Status tidak dikenal: {status}",
        "en": "Unknown status: {status}"},
    "err.user_not_found": {
        "id": "Pengguna '{username}' tidak ditemukan.",
        "en": "User '{username}' was not found."},
    "err.cannot_disable_self": {
        "id": "Anda tidak dapat menonaktifkan akun Anda sendiri.",
        "en": "You cannot deactivate your own account."},


    # ═══════════════════════════════════════════════════════════════════
    # PESAN KESALAHAN: pipeline_versions  (Tahap 4B)
    # ═══════════════════════════════════════════════════════════════════
    "err.not_contributed": {
        "id": "`{pipeline}` bukan pipeline kontribusi. Pipeline bawaan berasal "
              "dari registry statis dan tidak dapat disunting dari sini.",
        "en": "`{pipeline}` is not a contributed pipeline. Built-in pipelines "
              "come from the static registry and cannot be edited here."},
    "err.version_file_missing": {
        "id": "Berkas versi ini tidak ditemukan: {path}. Berkasnya mungkin "
              "dipindahkan di server.",
        "en": "This version's file was not found: {path}. It may have been "
              "moved on the server."},
    "err.version_folder_missing": {
        "id": "Folder versi tidak ditemukan: {folder}.",
        "en": "Version folder not found: {folder}."},
    "err.entry_not_in_package": {
        "id": "Berkas titik masuk `{filename}` tidak ada di antara berkas yang "
              "disimpan.",
        "en": "Entry-point file `{filename}` is not among the files being "
              "saved."},
    "err.entry_file_not_found": {
        "id": "Berkas titik masuk tidak ditemukan: {filename}.",
        "en": "Entry-point file not found: {filename}."},
    "err.change_note_required": {
        "id": "Catatan perubahan wajib diisi — ia yang menjelaskan versi ini "
              "di riwayat.",
        "en": "A change note is required — it is what explains this version "
              "in the history."},
    "err.source_empty": {
        "id": "Sumber kosong — tidak ada yang dapat disimpan.",
        "en": "The source is empty — there is nothing to save."},
    "err.version_file_exists": {
        "id": "Berkas versi {version} sudah ada — penyimpanan dibatalkan agar "
              "tidak menimpa apa pun.",
        "en": "Version {version} files already exist — the save was cancelled "
              "so that nothing is overwritten."},


    # ═══════════════════════════════════════════════════════════════════
    # PESAN KESALAHAN: submission_service  (Tahap 4B)
    # ═══════════════════════════════════════════════════════════════════
    "err.unsafe_filename": {
        "id": "Nama berkas tidak aman: {filename}",
        "en": "Unsafe file name: {filename}"},
    "err.filename_charset": {
        "id": "Nama berkas hanya boleh huruf/angka/._- : {filename}",
        "en": "A file name may contain only letters/digits/._- : {filename}"},
    "err.unsupported_extension": {
        "id": "Ekstensi tidak didukung: {ext} (diizinkan: {allowed})",
        "en": "Unsupported extension: {ext} (allowed: {allowed})"},
    "err.too_many_similar_names": {
        "id": "Terlalu banyak berkas dengan nama serupa. Ganti nama berkasnya.",
        "en": "Too many files with a similar name. Rename the file."},
    "err.no_files_to_submit": {
        "id": "Tidak ada berkas untuk diajukan.",
        "en": "There are no files to submit."},
    "err.submission_not_found": {
        "id": "Pengajuan #{number} tidak ditemukan.",
        "en": "Submission #{number} was not found."},
    "err.submission_already": {
        "id": "Pengajuan #{number} sudah berstatus {status}.",
        "en": "Submission #{number} is already {status}."},
    "err.submission_file_missing": {
        "id": "Berkas pengajuan tidak ditemukan: {path}",
        "en": "Submission file not found: {path}"},
    "err.no_dataset_type": {
        "id": "Pipeline ini belum punya dataset_type. Tentukan dataset target "
              "saat meninjau sebelum menyetujui.",
        "en": "This pipeline has no dataset_type yet. Choose the target "
              "dataset while reviewing, before approving."},
    "err.no_entry_class": {
        "id": "Nama kelas entry point tidak diketahui pada metadata pengajuan.",
        "en": "The entry-point class name is not recorded in the submission "
              "metadata."},
    "err.reject_reason_required": {
        "id": "Catatan alasan wajib diisi saat menolak.",
        "en": "A reason note is required when rejecting."},
    "err.dataset_file_exists": {
        "id": "`{filename}` sudah ada di `{folder}/`. Ganti nama berkasnya — "
              "platform tidak menimpa berkas yang sudah ada.",
        "en": "`{filename}` already exists in `{folder}/`. Rename the file — "
              "the platform never overwrites an existing file."},
    "err.entry_not_in_files": {
        "id": "Entry point `{filename}` tidak ada di antara berkas paket.",
        "en": "Entry point `{filename}` is not among the package files."},


    # ═══════════════════════════════════════════════════════════════════
    # PESAN KESALAHAN: run_mode & dynamic_registry  (Tahap 4B)
    # ═══════════════════════════════════════════════════════════════════
    # Nama parameter, nilai bawaan, dan daftar pilihan TIDAK diterjemahkan —
    # ia disalin apa adanya dari `fixed_params` pipeline.
    "err.param_not_bool": {
        "id": "`{param}` harus bernilai benar/salah (boolean).",
        "en": "`{param}` must be true or false (boolean)."},
    "err.param_not_int": {
        "id": "`{param}` harus bilangan bulat (bawaannya {default}).",
        "en": "`{param}` must be a whole number (its default is {default})."},
    "err.param_not_number": {
        "id": "`{param}` harus bilangan (bawaannya {default}).",
        "en": "`{param}` must be a number (its default is {default})."},
    "err.param_not_finite": {
        "id": "`{param}` harus bilangan berhingga.",
        "en": "`{param}` must be a finite number."},
    "err.param_not_choice_type": {
        "id": "`{param}` harus salah satu pilihan yang tersedia.",
        "en": "`{param}` must be one of the available choices."},
    "err.param_bad_choice": {
        "id": "`{param}` = {value} bukan pilihan yang tersedia ({choices}).",
        "en": "`{param}` = {value} is not an available choice ({choices})."},
    "err.param_not_a_mapping": {
        "id": "Parameter harus berupa pasangan nama–nilai.",
        "en": "Parameters must be name–value pairs."},
    "err.param_locked": {
        "id": "`{param}` terkunci: {reason}.",
        "en": "`{param}` is locked: {reason}."},
    "err.bad_pipeline_name": {
        "id": "Nama pipeline tidak sah.",
        "en": "The pipeline name is not valid."},
    "err.cannot_prepare_load": {
        "id": "Tidak dapat menyiapkan pemuatan untuk {path}.",
        "en": "Could not prepare loading for {path}."},
    "err.class_not_in_file": {
        "id": "Kelas {cls} tidak ada di {filename}.",
        "en": "Class {cls} is not present in {filename}."},
    "err.not_a_base_pipeline": {
        "id": "{cls} bukan turunan BasePipeline — ditolak.",
        "en": "{cls} is not a subclass of BasePipeline — refused."},
    "err.missing_contract_method": {
        "id": "{cls} tidak mengimplementasi {method}() — ditolak.",
        "en": "{cls} does not implement {method}() — refused."},


    # Kegagalan memuat pipeline: HARUS menyebut pipeline mana & sebabnya.
    "err.pipeline_load_failed": {
        "id": "Gagal memuat {filename}: {kind}: {detail}",
        "en": "Failed to load {filename}: {kind}: {detail}"},


    # ═══════════════════════════════════════════════════════════════════
    # LAPORAN PDF — isi bagian  (Tahap 4C)
    # ═══════════════════════════════════════════════════════════════════
    # Nilai sisipan (nama kelas dari data, jumlah, persentase, hash, versi
    # pustaka) TIDAK diterjemahkan. Nama kelas {attack}/{normal} datang dari
    # label_mapping artefak — nilai data, bukan teks antarmuka.

    # ── Catatan kaki SEMANTIK METRIK ─────────────────────────────────────
    # Kedua kalimat harus tetap menyatakan (a) metrik mana yang dipakai dan
    # (b) bahwa keduanya BUKAN hal yang sama. Melemahkannya membuat angka dua
    # keluarga pipeline terbaca seolah sebanding.
    "rpt.foot_metric_eve": {
        "id": "<b>Catatan semantik metrik.</b> Precision/Recall/F1 di atas "
              "adalah metrik <b>kelas attack pada natural-holdout</b> "
              "(distribusi kelas asli), <i>bukan</i> rata-rata berbobot. "
              "Dipilih agar jujur terhadap kelas minoritas (serangan).",
        "en": "<b>Metric semantics.</b> The Precision/Recall/F1 above are "
              "<b>attack-class metrics on the natural holdout</b> (the "
              "original class distribution), <i>not</i> a weighted average. "
              "Chosen to stay honest about the minority class (attacks)."},
    "rpt.foot_metric_hikari": {
        "id": "<b>Catatan semantik metrik.</b> Precision/Recall/F1 di atas "
              "adalah <b>rata-rata berbobot (weighted)</b> seluruh kelas, "
              "<i>bukan</i> kelas attack natural-holdout seperti pada pipeline "
              "EVE-cbr. Untuk fokus kelas serangan, lihat Interpretasi "
              "Keamanan (kuadran) dan Per-Class Report.",
        "en": "<b>Metric semantics.</b> The Precision/Recall/F1 above are a "
              "<b>weighted average</b> across all classes, <i>not</i> the "
              "natural-holdout attack class as in the EVE-cbr pipeline. For "
              "the attack class specifically, see Security Interpretation "
              "(quadrants) and the Per-Class Report."},

    # ── INTERPRETASI KEAMANAN ────────────────────────────────────────────
    # Istilahnya harus tetap TEPAT: "lolos" berarti tidak terdeteksi sama
    # sekali, bukan "gagal diklasifikasi".
    "rpt.sec_no_confusion": {
        "id": "Confusion matrix tidak tersedia atau bukan biner, sehingga "
              "hasil tidak dapat diterjemahkan ke kuadran operasional.",
        "en": "No confusion matrix is available, or it is not binary, so the "
              "result cannot be mapped onto operational quadrants."},
    "rpt.sec_quadrant_intro": {
        "id": "Empat kuadran berikut diterjemahkan langsung dari confusion "
              "matrix (kelas positif = {attack}). Tiap angka adalah jumlah "
              "aliran nyata pada data uji.",
        "en": "The four quadrants below are read directly from the confusion "
              "matrix (positive class = {attack}). Each number is a count of "
              "real flows in the test data."},
    "rpt.col_category": {"id": "Kategori", "en": "Category"},
    "rpt.col_count": {"id": "Jumlah", "en": "Count"},
    "rpt.col_meaning": {"id": "Arti operasional", "en": "Operational meaning"},
    "rpt.quad_tp": {"id": "Serangan terdeteksi (TP)", "en": "Attacks detected (TP)"},
    "rpt.quad_fn": {"id": "Serangan LOLOS (FN)", "en": "Attacks MISSED (FN)"},
    "rpt.quad_fp": {"id": "False alarm (FP)", "en": "False alarm (FP)"},
    "rpt.quad_tn": {"id": "Normal benar (TN)", "en": "Correctly allowed (TN)"},
    "rpt.quad_tp_note": {
        "id": "{attack} yang berhasil dikenali model — deteksi yang benar.",
        "en": "{attack} the model recognised — a correct detection."},
    "rpt.quad_fn_note": {
        "id": "{attack} yang TIDAK terdeteksi (dianggap {normal}) — risiko "
              "keamanan paling kritis.",
        "en": "{attack} that went UNDETECTED (treated as {normal}) — the most "
              "critical security risk."},
    "rpt.quad_fp_note": {
        "id": "{normal} salah ditandai sebagai serangan — membebani analis "
              "(alert fatigue).",
        "en": "{normal} wrongly flagged as an attack — a burden on analysts "
              "(alert fatigue)."},
    "rpt.quad_tn_note": {
        "id": "{normal} yang benar dibiarkan lewat — tidak mengganggu operasi.",
        "en": "{normal} correctly allowed through — no disruption to "
              "operations."},
    "rpt.cap_quadrants": {
        "id": "Kuadran deteksi operasional (dihitung dari confusion matrix).",
        "en": "Operational detection quadrants (computed from the confusion "
              "matrix)."},
    "rpt.cap_metrics": {"id": "Metrik performa utama eksperimen.",
                        "en": "Headline performance metrics of the experiment."},
    "rpt.sec_summary_sentence": {
        "id": "Secara operasional, model <b>melewatkan {missed} serangan dari "
              "{total}</b> (tingkat deteksi {recall}) dan <b>menandai {fp} "
              "lalu lintas benign sebagai serangan</b> (false positive rate "
              "{fpr}).",
        "en": "Operationally, the model <b>misses {missed} of {total} "
              "attacks</b> (detection rate {recall}) and <b>flags {fp} benign "
              "flows as attacks</b> (false positive rate {fpr})."},
    "rpt.callout_missed_label": {
        "id": "Serangan lolos (paling kritis):",
        "en": "Attacks missed (most critical):"},
    "rpt.callout_missed_body": {
        "id": "{missed} dari {total} serangan ({pct}) tidak terdeteksi dan "
              "melewati sistem tanpa alarm.",
        "en": "{missed} of {total} attacks ({pct}) went undetected and passed "
              "through the system without an alarm."},
    "rpt.callout_fp_label": {"id": "Beban false alarm:",
                             "en": "False-alarm burden:"},
    "rpt.callout_fp_body": {
        "id": "{fp} dari {total} aliran normal ({pct}) memicu alarm palsu — "
              "biaya investigasi bagi analis.",
        "en": "{fp} of {total} normal flows ({pct}) raised a false alarm — an "
              "investigation cost for analysts."},

    # ── REPRODUCIBILITY ──────────────────────────────────────────────────
    "rpt.repro_intro": {
        "id": "Selama hash dataset, kode pipeline, dan environment sama, "
              "metrik yang dihasilkan identik antar eksekusi — dasar klaim "
              "reproducibility artefak penelitian ini.",
        "en": "As long as the dataset hash, pipeline code, and environment "
              "stay the same, the metrics are identical across runs — the "
              "basis of this artifact's reproducibility claim."},
    "rpt.repro_how": {
        "id": "Untuk membuktikan reproducibility: jalankan pipeline yang sama "
              "dua kali pada dataset yang sama; nilai metrik "
              "(accuracy/precision/recall/F1/AUC) harus identik dan hash "
              "dataset sama.",
        "en": "To demonstrate reproducibility: run the same pipeline twice on "
              "the same dataset; the metric values "
              "(accuracy/precision/recall/F1/AUC) must be identical and the "
              "dataset hash the same."},
    # Nilai seed SELALU dibaca dari parameter yang tercatat — ketiga kalimat
    # di bawah hanya membungkusnya.
    "rpt.seed_locked": {
        "id": "{seed} (terkunci untuk seluruh operasi stokastik)",
        "en": "{seed} (locked for every stochastic operation)"},
    "rpt.seed_adjusted": {
        "id": "{seed} (disesuaikan pada run eksplorasi; nilai terkunci {base})",
        "en": "{seed} (adjusted in an exploration run; locked value {base})"},
    "rpt.repro_exploration": {
        "id": "Eksperimen ini adalah <b>run eksplorasi</b>: dapat diulang "
              "dengan parameter yang tercantum pada Tabel Konfigurasi, tetapi "
              "TIDAK dipakai sebagai dasar replikasi paper rujukan maupun "
              "perbandingan resmi antar pipeline.",
        "en": "This experiment is an <b>exploration run</b>: it can be "
              "repeated with the parameters listed in the Configuration "
              "table, but it is NOT used as a basis for replicating the "
              "reference paper, nor for official comparison between "
              "pipelines."},
    "rpt.lbl_seed": {"id": "random_state / seed", "en": "random_state / seed"},
    "rpt.lbl_wall_clock": {"id": "Wall-clock (queue + eksekusi)",
                           "en": "Wall clock (queue + execution)"},
    "rpt.yes": {"id": "Ya", "en": "Yes"},
    "rpt.no": {"id": "Tidak", "en": "No"},
    "rpt.not_recorded": {"id": "[tidak tercatat]", "en": "[not recorded]"},


    # ── Verdict metrik  (Tahap 4C) ───────────────────────────────────────
    # AMBANGNYA ada di `report_generator` dan TIDAK berubah; ini hanya
    # kalimatnya. Istilah metrik (Recall/Precision/F1/ROC-AUC) tidak
    # diterjemahkan.
    "vd.unavailable": {"id": "tidak tersedia", "en": "not available"},
    "vd.excellent": {"id": "sangat baik", "en": "very good"},
    "vd.good": {"id": "baik", "en": "good"},
    "vd.attention": {"id": "perlu perhatian", "en": "needs attention"},
    "vd.weak": {"id": "lemah", "en": "weak"},

    "vd.recall_excellent": {
        "id": "hampir seluruh serangan berhasil tertangkap",
        "en": "almost every attack was caught"},
    "vd.recall_good": {
        "id": "sebagian besar serangan tertangkap, sebagian kecil lolos",
        "en": "most attacks were caught, a few slipped through"},
    "vd.recall_attention": {
        "id": "cukup banyak serangan lolos tanpa terdeteksi",
        "en": "a fair number of attacks went undetected"},
    "vd.recall_weak": {
        "id": "mayoritas serangan lolos tanpa terdeteksi",
        "en": "most attacks went undetected"},

    "vd.precision_excellent": {
        "id": "hampir setiap alarm benar-benar serangan",
        "en": "almost every alarm was a real attack"},
    "vd.precision_good": {
        "id": "mayoritas alarm benar, sebagian kecil false alarm",
        "en": "most alarms were correct, a few were false"},
    "vd.precision_attention": {
        "id": "hampir separuh alarm adalah false alarm",
        "en": "almost half of the alarms were false"},
    "vd.precision_weak": {
        "id": "mayoritas alarm ternyata bukan serangan (banyak false alarm)",
        "en": "most alarms were not attacks (many false alarms)"},

    "vd.f1_excellent": {
        "id": "keseimbangan deteksi dan ketepatan alarm sangat baik",
        "en": "the balance between detection and alarm accuracy is very good"},
    "vd.f1_good": {
        "id": "keseimbangan deteksi dan ketepatan alarm tergolong baik",
        "en": "the balance between detection and alarm accuracy is good"},
    "vd.f1_attention": {
        "id": "ada kompromi antara serangan lolos dan false alarm",
        "en": "there is a trade-off between missed attacks and false alarms"},
    "vd.f1_weak": {
        "id": "deteksi dan ketepatan alarm sama-sama belum memadai",
        "en": "both detection and alarm accuracy fall short"},

    "vd.auc_excellent": {
        "id": "model memisahkan serangan dari trafik normal dengan jelas",
        "en": "the model separates attacks from normal traffic clearly"},
    "vd.auc_good": {
        "id": "model cukup mampu memisahkan serangan dari trafik normal",
        "en": "the model separates attacks from normal traffic reasonably "
              "well"},
    "vd.auc_attention": {
        "id": "kemampuan memisahkan serangan dari normal masih terbatas",
        "en": "its ability to separate attacks from normal traffic is still "
              "limited"},
    "vd.auc_weak": {
        "id": "kemampuan memisahkan serangan dari normal mendekati tebakan "
              "acak",
        "en": "its ability to separate attacks from normal traffic is close "
              "to random guessing"},

    "vd.accuracy_careful": {"id": "baca dengan hati-hati",
                            "en": "read with care"},
    "vd.accuracy_informative": {"id": "informatif", "en": "informative"},


    # ── Analisis metrik: kalimat UTUH, tidak disambung  (penutup) ────────
    # Nama metrik (Recall/Precision/F1-score/Accuracy/ROC-AUC) TIDAK
    # diterjemahkan; hanya keterangan dalam kurung yang ikut bahasa.
    "rpt.metric_recall": {"id": "Recall (tingkat deteksi serangan)",
                          "en": "Recall (attack detection rate)"},
    "rpt.metric_precision": {"id": "Precision (ketepatan alarm)",
                             "en": "Precision (alarm accuracy)"},
    "rpt.metric_f1": {"id": "F1-score (keseimbangan)",
                      "en": "F1-score (balance)"},
    "rpt.metric_accuracy": {"id": "Accuracy (akurasi keseluruhan)",
                            "en": "Accuracy (overall correctness)"},
    "rpt.metric_auc": {"id": "ROC-AUC (daya pisah)",
                       "en": "ROC-AUC (separability)"},

    "rpt.analysis_intro_attack": {
        "id": "Recall, Precision, dan F1 berikut ditinjau untuk <b>kelas "
              "serangan</b> (paling relevan secara operasional), dihitung "
              "langsung dari confusion matrix.",
        "en": "The Recall, Precision, and F1 below are reported for the "
              "<b>attack class</b> (the most operationally relevant), computed "
              "directly from the confusion matrix."},
    "rpt.analysis_intro_plain": {
        "id": "Nilai metrik diambil apa adanya dari hasil eksperimen.",
        "en": "The metric values are taken exactly as recorded in the "
              "experiment results."},

    "rpt.desc_recall": {
        "id": "Dari semua serangan yang ada, {pct} terdeteksi (sisanya lolos).",
        "en": "Of all the attacks present, {pct} were detected; the rest "
              "slipped through."},
    "rpt.desc_recall_detail": {
        "id": "Dari semua serangan yang ada, {pct} terdeteksi (sisanya lolos). "
              "Artinya {missed} dari {total} serangan lolos.",
        "en": "Of all the attacks present, {pct} were detected; the rest "
              "slipped through. That means {missed} of {total} attacks got "
              "past the system."},

    "rpt.desc_precision": {
        "id": "Dari semua yang ditandai serangan, {pct} benar-benar serangan.",
        "en": "Of everything flagged as an attack, {pct} really were attacks."},
    "rpt.desc_precision_detail": {
        "id": "Dari semua yang ditandai serangan, {pct} benar-benar serangan. "
              "Dari {alarms} alarm, {fp} adalah false alarm.",
        "en": "Of everything flagged as an attack, {pct} really were attacks. "
              "Of {alarms} alarms, {fp} were false alarms."},

    # F1: satu kalimat per tingkat penilaian. AMBANGNYA tidak berubah — yang
    # dipetakan di sini hanya kalimat yang menyertainya.
    "rpt.desc_f1": {
        "id": "Keseimbangan antara tidak meloloskan serangan dan tidak "
              "membuat false alarm.",
        "en": "The balance between not letting attacks through and not "
              "raising false alarms."},
    "rpt.desc_f1_excellent": {
        "id": "Keseimbangan antara tidak meloloskan serangan dan tidak "
              "membuat false alarm — dan keseimbangan itu sangat baik.",
        "en": "The balance between not letting attacks through and not "
              "raising false alarms — and that balance is very good."},
    "rpt.desc_f1_good": {
        "id": "Keseimbangan antara tidak meloloskan serangan dan tidak "
              "membuat false alarm — dan keseimbangan itu tergolong baik.",
        "en": "The balance between not letting attacks through and not "
              "raising false alarms — and that balance is good."},
    "rpt.desc_f1_attention": {
        "id": "Keseimbangan antara tidak meloloskan serangan dan tidak "
              "membuat false alarm — masih ada kompromi antara serangan yang "
              "lolos dan false alarm.",
        "en": "The balance between not letting attacks through and not "
              "raising false alarms — there is still a trade-off between "
              "missed attacks and false alarms."},
    "rpt.desc_f1_weak": {
        "id": "Keseimbangan antara tidak meloloskan serangan dan tidak "
              "membuat false alarm — deteksi dan ketepatan alarm sama-sama "
              "belum memadai.",
        "en": "The balance between not letting attacks through and not "
              "raising false alarms — both detection and alarm accuracy fall "
              "short."},

    "rpt.desc_accuracy": {
        "id": "Proporsi seluruh prediksi yang benar ({pct}).",
        "en": "The share of all predictions that were correct ({pct})."},
    "rpt.desc_accuracy_imbalanced": {
        "id": "Proporsi seluruh prediksi yang benar ({pct}). Perhatian: data "
              "timpang (serangan hanya {share} dari total), accuracy dapat "
              "terlihat tinggi meski sebagian serangan lolos — utamakan "
              "Recall & Precision.",
        "en": "The share of all predictions that were correct ({pct}). "
              "Caution: the data is imbalanced (attacks are only {share} of "
              "the total), so accuracy can look high even when some attacks "
              "slip through — rely on Recall & Precision instead."},

    # ROC-AUC: {perfect}/{chance} disisipkan dari satu sumber di kode.
    "rpt.desc_auc": {
        "id": "Kemampuan memisahkan serangan dari trafik normal "
              "({perfect} = sempurna; {chance} = tebak acak).",
        "en": "Its ability to separate attacks from normal traffic "
              "({perfect} = perfect; {chance} = random guessing)."},
    "rpt.desc_auc_excellent": {
        "id": "Kemampuan memisahkan serangan dari trafik normal "
              "({perfect} = sempurna; {chance} = tebak acak) — model "
              "memisahkan keduanya dengan jelas.",
        "en": "Its ability to separate attacks from normal traffic "
              "({perfect} = perfect; {chance} = random guessing) — the model "
              "separates the two clearly."},
    "rpt.desc_auc_good": {
        "id": "Kemampuan memisahkan serangan dari trafik normal "
              "({perfect} = sempurna; {chance} = tebak acak) — model cukup "
              "mampu memisahkan keduanya.",
        "en": "Its ability to separate attacks from normal traffic "
              "({perfect} = perfect; {chance} = random guessing) — the model "
              "separates them reasonably well."},
    "rpt.desc_auc_attention": {
        "id": "Kemampuan memisahkan serangan dari trafik normal "
              "({perfect} = sempurna; {chance} = tebak acak) — kemampuan itu "
              "masih terbatas.",
        "en": "Its ability to separate attacks from normal traffic "
              "({perfect} = perfect; {chance} = random guessing) — that "
              "ability is still limited."},
    "rpt.desc_auc_weak": {
        "id": "Kemampuan memisahkan serangan dari trafik normal "
              "({perfect} = sempurna; {chance} = tebak acak) — kemampuan itu "
              "mendekati tebakan acak.",
        "en": "Its ability to separate attacks from normal traffic "
              "({perfect} = perfect; {chance} = random guessing) — that "
              "ability is close to random guessing."},

    # Penanda sel kosong. Satu string, tetapi bocor ke SETIAP sel kosong.
    "rpt.na": {"id": "[tidak tersedia]", "en": "[not available]"},


    # ── Arti fitur jaringan pada laporan  (penutup) ──────────────────────
    # Nama fiturnya sendiri (kolom dataset) TIDAK diterjemahkan; yang
    # diterjemahkan hanya penjelasannya.

    "rpt.feat_bytes_per_sec": {"id": "laju volume data (byte per detik) pada aliran — throughput koneksi",
                                  "en": "data rate (bytes per second) on the flow — connection throughput"},
    "rpt.feat_pkts_per_sec": {"id": "laju paket per detik — kepadatan pengiriman paket",
                                 "en": "packets per second — how densely packets are sent"},
    "rpt.feat_bytes_per_pkt": {"id": "rata-rata ukuran paket (byte/paket) — besar tiap paket",
                                  "en": "average packet size (bytes/packet) — how large each packet is"},
    "rpt.feat_total_bytes": {"id": "total byte yang ditransfer dalam aliran",
                                "en": "total bytes transferred in the flow"},
    "rpt.feat_total_pkts": {"id": "total paket dalam aliran",
                               "en": "total packets in the flow"},
    "rpt.feat_flow_duration": {"id": "durasi aliran (lama koneksi berlangsung)",
                                  "en": "flow duration (how long the connection lasted)"},
    "rpt.feat_bytes_toserver": {"id": "volume byte dari klien ke server (arah unggah)",
                                   "en": "bytes from client to server (the upload direction)"},
    "rpt.feat_pkts_toserver": {"id": "jumlah paket dari klien ke server",
                                  "en": "packets from client to server"},
    "rpt.feat_pkts_toclient": {"id": "jumlah paket dari server ke klien (arah unduh)",
                                  "en": "packets from server to client (the download direction)"},
    "rpt.feat_bytes_toserver_ratio": {"id": "porsi byte yang menuju server dibanding total — arah dominan trafik",
                                         "en": "share of bytes going to the server out of the total — the dominant direction of the traffic"},
    "rpt.feat_pkts_toserver_ratio": {"id": "porsi paket yang menuju server dibanding total — arah dominan trafik",
                                        "en": "share of packets going to the server out of the total — the dominant direction of the traffic"},
    "rpt.feat_src_port": {"id": "port sumber koneksi",
                             "en": "the connection's source port"},
    "rpt.feat_src_port_class": {"id": "kategori port sumber (well-known / registered / ephemeral)",
                                   "en": "source port category (well-known / registered / ephemeral)"},
    "rpt.feat_dest_port_class": {"id": "kategori port tujuan — menyiratkan jenis layanan yang dihubungi",
                                    "en": "destination port category — implies the kind of service contacted"},
    "rpt.feat_unique_dest_port_window": {"id": "banyak port tujuan unik dalam satu jendela waktu — indikator port scanning",
                                            "en": "number of unique destination ports within one time window — an indicator of port scanning"},
    "rpt.feat_unique_dest_ip_window": {"id": "banyak IP tujuan unik dalam satu jendela waktu — indikator sweep/penyebaran",
                                          "en": "number of unique destination IPs within one time window — an indicator of a sweep or spread"},
    "rpt.feat_event_count_window": {"id": "jumlah event log dalam jendela waktu — intensitas aktivitas",
                                       "en": "number of log events within the time window — the intensity of activity"},
    "rpt.feat_no_alert_count_window": {"id": "jumlah event tanpa alert dalam jendela waktu",
                                          "en": "number of events without an alert within the time window"},
    "rpt.feat_total_bytes_window": {"id": "akumulasi byte dalam jendela waktu — burst volume",
                                       "en": "bytes accumulated within the time window — a volume burst"},
    "rpt.feat_total_pkts_window": {"id": "akumulasi paket dalam jendela waktu — burst paket",
                                      "en": "packets accumulated within the time window — a packet burst"},
    "rpt.feat_bytes_per_event_window": {"id": "rata-rata byte per event dalam jendela waktu",
                                           "en": "average bytes per event within the time window"},
    "rpt.feat_pkts_per_event_window": {"id": "rata-rata paket per event dalam jendela waktu",
                                          "en": "average packets per event within the time window"},
    "rpt.feat_ts_hour": {"id": "jam terjadinya aktivitas — pola waktu (temporal) trafik",
                            "en": "the hour the activity occurred — the temporal pattern of the traffic"},
    "rpt.feat_app_proto_h": {"id": "protokol aplikasi (hash) — jenis layanan pada aliran",
                                "en": "application protocol (hashed) — the kind of service on the flow"},
    "rpt.feat_interaction_bytes_rate_packet_rate": {"id": "interaksi antara laju byte dan laju paket per detik",
                                                       "en": "the interaction between byte rate and packet rate per second"},
    "rpt.feat_interaction_total_bytes_duration": {"id": "interaksi antara total byte dan durasi aliran",
                                                     "en": "the interaction between total bytes and flow duration"},
    "rpt.feat_interaction_total_pkts_duration": {"id": "interaksi antara total paket dan durasi aliran",
                                                    "en": "the interaction between total packets and flow duration"},
    "rpt.feat_down_up_ratio_flow": {"id": "rasio volume unduh terhadap unggah pada aliran",
                                       "en": "the ratio of download to upload volume on the flow"},
    "rpt.feat_fwd_subflow_bytes": {"id": "volume byte pada subflow arah maju (klien->server)",
                                      "en": "bytes on the forward subflow (client->server)"},
    "rpt.feat_bwd_subflow_bytes": {"id": "volume byte pada subflow arah balik (server->klien)",
                                      "en": "bytes on the backward subflow (server->client)"},
    "rpt.feat_fwd_init_window_size": {"id": "ukuran TCP receive window awal arah maju (kontrol aliran)",
                                         "en": "initial TCP receive window size in the forward direction (flow control)"},
    "rpt.feat_bwd_init_window_size": {"id": "ukuran TCP receive window awal arah balik (kontrol aliran)",
                                         "en": "initial TCP receive window size in the backward direction (flow control)"},
    "rpt.feat_init_window": {"id": "ukuran TCP receive window awal (kontrol aliran)",
                                "en": "initial TCP receive window size (flow control)"},
    "rpt.feat_window_size": {"id": "ukuran TCP receive window (kontrol aliran)",
                                "en": "TCP receive window size (flow control)"},
    "rpt.feat_duration_short": {"id": "durasi aliran (lama koneksi)",
                                   "en": "flow duration (how long the connection lasted)"},
    "rpt.feat_iat": {"id": "inter-arrival time — jeda waktu antar paket",
                        "en": "inter-arrival time — the gap between packets"},
    "rpt.feat_per_sec": {"id": "laju per detik (kecepatan) suatu besaran trafik",
                            "en": "a per-second rate (speed) of some traffic quantity"},
    "rpt.feat_rate": {"id": "laju (kecepatan) suatu besaran trafik",
                         "en": "a rate (speed) of some traffic quantity"},
    "rpt.feat_down_up_ratio": {"id": "rasio volume unduh terhadap unggah",
                                  "en": "the ratio of download to upload volume"},
    "rpt.feat_ratio": {"id": "rasio antar komponen/arah trafik",
                          "en": "a ratio between traffic components or directions"},
    "rpt.feat_unique_dest_port": {"id": "banyak port tujuan unik — indikator port scanning",
                                     "en": "number of unique destination ports — an indicator of port scanning"},
    "rpt.feat_unique_dest_ip": {"id": "banyak IP tujuan unik — indikator sweep jaringan",
                                   "en": "number of unique destination IPs — an indicator of a network sweep"},
    "rpt.feat_port_class": {"id": "kategori port (jenis layanan)",
                               "en": "port category (the kind of service)"},
    "rpt.feat_dest_port": {"id": "port tujuan — layanan yang dihubungi",
                              "en": "destination port — the service contacted"},
    "rpt.feat_toserver": {"id": "volume/arah trafik dari klien ke server",
                             "en": "the volume and direction of traffic from client to server"},
    "rpt.feat_toclient": {"id": "volume/arah trafik dari server ke klien",
                             "en": "the volume and direction of traffic from server to client"},
    "rpt.feat_subflow": {"id": "volume/jumlah pada subflow (segmen aliran)",
                            "en": "volume or count on a subflow (a segment of the flow)"},
    "rpt.feat_payload": {"id": "statistik ukuran payload (byte) paket",
                            "en": "statistics of packet payload size (bytes)"},
    "rpt.feat_header": {"id": "ukuran header paket",
                           "en": "packet header size"},
    "rpt.feat_flag": {"id": "jumlah TCP flag (mis. SYN/PSH/URG) pada aliran",
                         "en": "the count of TCP flags (e.g. SYN/PSH/URG) on the flow"},
    "rpt.feat_bulk": {"id": "transfer data bulk (burst) pada aliran",
                         "en": "bulk (burst) data transfer on the flow"},
    "rpt.feat_active": {"id": "lama koneksi dalam keadaan aktif",
                           "en": "how long the connection stayed active"},
    "rpt.feat_idle": {"id": "lama koneksi dalam keadaan idle (menganggur)",
                         "en": "how long the connection stayed idle"},
    "rpt.feat_seg_size": {"id": "ukuran segmen paket",
                             "en": "packet segment size"},
    "rpt.feat_window": {"id": "agregasi dalam jendela waktu — perilaku per periode (burst/berulang)",
                           "en": "aggregation within a time window — behaviour per period (bursty or repeating)"},
    "rpt.feat_bytes": {"id": "volume data (byte) yang ditransfer",
                          "en": "the volume of data (bytes) transferred"},
    "rpt.feat_pkts": {"id": "jumlah paket",
                         "en": "packet count"},
    "rpt.feat_alert": {"id": "jumlah alert pada aliran",
                          "en": "the count of alerts on the flow"},
    "rpt.feat_event": {"id": "jumlah event log pada aliran",
                          "en": "the count of log events on the flow"},
    "rpt.feat_proto": {"id": "protokol aplikasi yang dipakai",
                          "en": "the application protocol in use"},
    "rpt.feat_hour": {"id": "jam aktivitas — pola waktu (temporal)",
                         "en": "the hour of activity — the temporal pattern"},
    "rpt.feat_flow": {"id": "karakteristik aliran (flow) jaringan",
                         "en": "characteristics of the network flow"},
    "rpt.feat_unmapped": {"id": "statistik aliran jaringan (makna spesifik tidak dipetakan)",
                             "en": "a network flow statistic (its specific meaning is not mapped)"},

    # Awalan nama fitur. Disusun BERSARANG lewat {meaning}, bukan disambung,
    # supaya urutan katanya boleh berbeda antar bahasa.
    "rpt.feat_log_of": {"id": "skala logaritmik dari {meaning}",
                        "en": "the logarithmic scale of {meaning}"},
    "rpt.feat_interaction_of": {"id": "kombinasi (interaksi) dari {meaning}",
                                "en": "the combination (interaction) of "
                                      "{meaning}"},


    # ── Ringkasan / abstrak  (penutup) ───────────────────────────────────
    # Kalimatnya UTUH per bahasa. Versi lama menyambung f-string Indonesia
    # dengan kategori penilaian dari katalog — dua bahasa dalam satu kalimat.
    "rpt.abs_algo_fallback": {"id": "Model machine learning",
                              "en": "A machine learning model"},
    "rpt.abs_dataset_eve": {"id": "EVE/Suricata (trafik TLS)",
                            "en": "EVE/Suricata (TLS traffic)"},
    "rpt.abs_dataset_fallback": {"id": "dataset terpilih",
                                 "en": "the selected dataset"},
    "rpt.abs_semantics_eve": {"id": "kelas serangan pada natural-holdout",
                              "en": "the attack class on the natural holdout"},
    "rpt.abs_semantics_weighted": {
        "id": "rata-rata berbobot (weighted) seluruh kelas",
        "en": "a weighted average across all classes"},
    "rpt.abs_main": {
        "id": "Eksperimen ini mengevaluasi algoritma {algo} sebagai "
              "<i>detection engine</i> pada dataset {dataset}. Dari {total} "
              "aliran uji ({attacks} serangan dan {normals} normal), model "
              "mendeteksi {recall} serangan ({tp} dari {attacks}) dengan "
              "ketepatan alarm {precision}. Sebanyak {missed} serangan lolos "
              "tanpa terdeteksi dan {false_alarms} aliran normal salah "
              "ditandai sebagai serangan (false alarm), menempatkan performa "
              "deteksi pada kategori “{verdict}”. Seluruh metrik dilaporkan "
              "sebagai {semantics}; rincian dan catatan semantik disajikan "
              "pada bagian-bagian berikut.",
        "en": "This experiment evaluates the {algo} algorithm as a "
              "<i>detection engine</i> on the {dataset} dataset. Out of "
              "{total} test flows ({attacks} attacks and {normals} normal), "
              "the model detected {recall} of the attacks ({tp} of "
              "{attacks}) with an alarm accuracy of {precision}. In total "
              "{missed} attacks went undetected and {false_alarms} normal "
              "flows were wrongly flagged as attacks (false alarms), placing "
              "detection performance in the “{verdict}” category. Every "
              "metric is reported as {semantics}; the details and semantic "
              "notes follow in the sections below."},
    "rpt.abs_main_f1": {
        "id": "Eksperimen ini mengevaluasi algoritma {algo} sebagai "
              "<i>detection engine</i> pada dataset {dataset}. Dari {total} "
              "aliran uji ({attacks} serangan dan {normals} normal), model "
              "mendeteksi {recall} serangan ({tp} dari {attacks}) dengan "
              "ketepatan alarm {precision}, dengan F1 kelas serangan {f1}. "
              "Sebanyak {missed} serangan lolos tanpa terdeteksi dan "
              "{false_alarms} aliran normal salah ditandai sebagai serangan "
              "(false alarm), menempatkan performa deteksi pada kategori "
              "“{verdict}”. Seluruh metrik dilaporkan sebagai {semantics}; "
              "rincian dan catatan semantik disajikan pada bagian-bagian "
              "berikut.",
        "en": "This experiment evaluates the {algo} algorithm as a "
              "<i>detection engine</i> on the {dataset} dataset. Out of "
              "{total} test flows ({attacks} attacks and {normals} normal), "
              "the model detected {recall} of the attacks ({tp} of "
              "{attacks}) with an alarm accuracy of {precision}, and an "
              "attack-class F1 of {f1}. In total {missed} attacks went "
              "undetected and {false_alarms} normal flows were wrongly "
              "flagged as attacks (false alarms), placing detection "
              "performance in the “{verdict}” category. Every metric is "
              "reported as {semantics}; the details and semantic notes "
              "follow in the sections below."},
    "rpt.abs_metrics_fallback": {"id": "metrik tersedia pada tabel hasil",
                                 "en": "the metrics are available in the "
                                       "results table"},
    "rpt.abs_no_confusion": {
        "id": "Eksperimen ini mengevaluasi algoritma {algo} pada dataset "
              "{dataset}. Metrik utama: {metrics}. Confusion matrix biner "
              "tidak tersedia sehingga interpretasi operasional (serangan "
              "terdeteksi/lolos, false alarm) tidak dapat dihitung; metrik "
              "dilaporkan sebagai {semantics}.",
        "en": "This experiment evaluates the {algo} algorithm on the "
              "{dataset} dataset. Headline metrics: {metrics}. A binary "
              "confusion matrix is not available, so the operational reading "
              "(attacks detected/missed, false alarms) cannot be computed; "
              "the metrics are reported as {semantics}."},

    # ── 1. Konfigurasi ───────────────────────────────────────────────────
    "rpt.fmt_ndjson": {
        "id": "NDJSON (catatan EVE Suricata, satu objek JSON per baris)",
        "en": "NDJSON (EVE Suricata records, one JSON object per line)"},
    "rpt.fmt_csv": {
        "id": "CSV (fitur flow ALLFLOWMETER yang sudah diekstraksi)",
        "en": "CSV (pre-extracted ALLFLOWMETER flow features)"},
    "rpt.label_origin_eve": {
        "id": "turunan alert Suricata pada trafik TLS (disempurnakan "
              "konservatif) — bukan ground-truth eksternal",
        "en": "derived from Suricata alerts on TLS traffic (conservatively "
              "refined) — not external ground truth"},
    "rpt.label_origin_hikari": {
        "id": "ground-truth bawaan HIKARI2021 (benign vs malicious)",
        "en": "the ground truth shipped with HIKARI2021 (benign vs malicious)"},
    "rpt.lbl_algorithm": {"id": "Algoritma", "en": "Algorithm"},
    "rpt.lbl_paper": {"id": "Rujukan (paper)", "en": "Reference (paper)"},
    "rpt.lbl_dataset_format": {"id": "Format dataset", "en": "Dataset format"},
    "rpt.lbl_label_origin": {"id": "Asal label", "en": "Label origin"},
    "rpt.lbl_source_file": {"id": "Berkas sumber", "en": "Source file"},
    "rpt.lbl_class_distribution": {"id": "Distribusi kelas (data uji)",
                                   "en": "Class distribution (test data)"},
    "rpt.class_distribution_value": {
        "id": "{total} aliran — serangan {attacks} ({share}) / normal "
              "{normals}",
        "en": "{total} flows — attacks {attacks} ({share}) / normal "
              "{normals}"},
    "rpt.lbl_preprocessing": {"id": "Praproses:", "en": "Preprocessing:"},
    "rpt.params_heading_used": {
        "id": "Hyperparameter yang dipakai run ini, disertai split & seed:",
        "en": "The hyperparameters used for this run, with split & seed:"},
    "rpt.params_heading_used_changed": {
        "id": "Hyperparameter yang dipakai run ini (tanda * = berbeda dari "
              "nilai terkunci):",
        "en": "The hyperparameters used for this run (* = differs from the "
              "locked value):"},
    "rpt.params_caption_used": {
        "id": "Parameter tercatat saat eksperimen berjalan.",
        "en": "Parameters recorded while the experiment was running."},
    "rpt.params_caption_used_changed": {
        "id": "Parameter tercatat saat eksperimen berjalan; nilai bertanda * "
              "disesuaikan pengguna pada run eksplorasi, sehingga hasil ini "
              "TIDAK sebanding dengan run resmi.",
        "en": "Parameters recorded while the experiment was running; values "
              "marked * were adjusted by the user on an exploration run, so "
              "these results are NOT comparable with an official run."},
    "rpt.params_heading_locked": {
        "id": "Hyperparameter terkunci (paper-faithful), disertai split & "
              "seed:",
        "en": "Locked hyperparameters (paper-faithful), with split & seed:"},
    "rpt.params_caption_locked": {
        "id": "Konfigurasi terkunci pipeline, dibaca dari definisi pipeline "
              "pada kode saat ini — eksperimen ini dijalankan sebelum "
              "parameter dicatat per run.",
        "en": "The pipeline's locked configuration, read from the pipeline "
              "definition in the current code — this experiment ran before "
              "parameters were recorded per run."},
    "rpt.col_locked_value": {"id": "Nilai terkunci", "en": "Locked value"},
    "rpt.val_same": {"id": "sama", "en": "same"},

    # ── 2. Hasil & metrik ────────────────────────────────────────────────
    "rpt.col_metric": {"id": "Metrik", "en": "Metric"},
    "rpt.col_value": {"id": "Nilai", "en": "Value"},
    "rpt.col_scope": {"id": "Cakupan", "en": "Scope"},
    "rpt.scope_all_classes": {"id": "seluruh kelas", "en": "all classes"},
    "rpt.scope_eve": {"id": "kelas attack, natural-holdout",
                      "en": "attack class, natural holdout"},
    "rpt.scope_binary": {"id": "biner", "en": "binary"},

    # ── Gambar & kegagalan render ────────────────────────────────────────
    "rpt.cap_confusion": {
        "id": "Confusion matrix dalam istilah jaringan (hijau = benar, "
              "amber = false alarm, merah = serangan lolos).",
        "en": "The confusion matrix in network terms (green = correct, "
              "amber = false alarm, red = missed attack)."},
    "rpt.err_render_confusion": {
        "id": "<i>Gagal merender confusion matrix: {error}</i>",
        "en": "<i>Could not render the confusion matrix: {error}</i>"},
    "rpt.err_render_fi": {
        "id": "<i>Gagal merender feature importance: {error}</i>",
        "en": "<i>Could not render the feature importance chart: {error}</i>"},
    "rpt.err_render_roc": {
        "id": "<i>Gagal merender ROC curve: {error}</i>",
        "en": "<i>Could not render the ROC curve: {error}</i>"},
    "rpt.err_render_lc": {
        "id": "<i>Gagal merender learning curve: {error}</i>",
        "en": "<i>Could not render the learning curve: {error}</i>"},

    # ── 5. Fitur berpengaruh ─────────────────────────────────────────────
    "rpt.fi_unavailable": {
        "id": "Algoritma {algo} tidak menghasilkan skor kepentingan fitur "
              "(feature importance) yang dapat dipetakan ke fitur jaringan "
              "asli (mis. K-Nearest Neighbors atau Gaussian Naive Bayes); "
              "bagian ini dilewati tanpa grafik kosong.",
        "en": "The {algo} algorithm produces no feature importance scores "
              "that can be mapped back to the original network features "
              "(e.g. K-Nearest Neighbors or Gaussian Naive Bayes); this "
              "section is skipped rather than shown as an empty chart."},
    "rpt.fi_algo_fallback": {"id": "ini", "en": "used here"},
    "rpt.fi_intro": {
        "id": "Fitur berikut paling menentukan keputusan model — menunjukkan "
              "sinyal trafik yang paling membedakan serangan dari trafik "
              "normal.",
        "en": "The features below weigh most heavily on the model's "
              "decision — they are the traffic signals that best separate "
              "attacks from normal traffic."},
    "rpt.cap_feature_importance": {
        "id": "Kepentingan fitur (top-N); nilai diambil apa adanya dari "
              "metrics.json.",
        "en": "Feature importance (top-N); values taken as recorded in "
              "metrics.json."},
    "rpt.fi_meanings_heading": {
        "id": "Arti fitur teratas dalam istilah jaringan:",
        "en": "What the top features mean in network terms:"},

    # ── 6. Diagnostik ────────────────────────────────────────────────────
    "rpt.sub_roc": {"id": "Kurva ROC", "en": "ROC Curve"},
    "rpt.cap_roc": {
        "id": "Kurva ROC; garis diagonal = tebakan acak. Semakin menjauhi "
              "diagonal, semakin baik.",
        "en": "The ROC curve; the diagonal line is random guessing. The "
              "further from the diagonal, the better."},
    "rpt.cap_learning_curve": {
        "id": "Learning curve (skor training vs validation terhadap ukuran "
              "data latih).",
        "en": "Learning curve (training vs validation score against training "
              "set size)."},
    "rpt.sub_dual_holdout": {
        "id": "Evaluasi Dual-Holdout (pengganti learning curve)",
        "en": "Dual-Holdout Evaluation (in place of a learning curve)"},
    "rpt.dual_holdout_intro": {
        "id": "Pipeline EVE-cbr tidak menghasilkan learning curve; sebagai "
              "gantinya dilaporkan dua holdout: <b>natural</b> (distribusi "
              "asli — metrik yang dilaporkan) dan <b>balanced</b> (kelas "
              "diseimbangkan, pembanding separabilitas).",
        "en": "The EVE-cbr pipeline produces no learning curve; two holdouts "
              "are reported instead: <b>natural</b> (the original "
              "distribution — the metrics reported here) and <b>balanced</b> "
              "(classes balanced, as a separability comparison)."},
    "rpt.cap_dual_holdout": {
        "id": "Perbandingan natural- vs balanced-holdout (metrik dilaporkan "
              "= natural).",
        "en": "Natural- vs balanced-holdout comparison (the metrics reported "
              "are the natural ones)."},
    "rpt.sub_per_class": {"id": "Laporan Per-Kelas", "en": "Per-Class Report"},
    "rpt.col_class": {"id": "Kelas", "en": "Class"},
    "rpt.cap_per_class": {
        "id": "Metrik precision/recall/F1 per kelas (HIKARI).",
        "en": "Per-class precision/recall/F1 metrics (HIKARI)."},
    "rpt.no_extra_diagnostics": {
        "id": "Tidak ada diagnostik grafik tambahan yang tersedia untuk "
              "eksperimen ini.",
        "en": "No additional diagnostic charts are available for this "
              "experiment."},

    # ── 7. Catatan metodologis ───────────────────────────────────────────
    # Ketegasan dipertahankan: yang dinyatakan BUKAN ground-truth tetap
    # dinyatakan begitu, dan anti-kebocoran tetap menyebut "hanya pada data
    # latih" secara eksplisit.
    "rpt.note_semantics_eve": {
        "id": "Semantik metrik: precision/recall/F1 dihitung untuk <b>kelas "
              "serangan</b> pada <b>natural-holdout</b> (distribusi asli) — "
              "bukan rata-rata berbobot.",
        "en": "Metric semantics: precision/recall/F1 are computed for the "
              "<b>attack class</b> on the <b>natural holdout</b> (the "
              "original distribution) — not as a weighted average."},
    "rpt.note_semantics_hikari": {
        "id": "Semantik metrik: precision/recall/F1 headline adalah "
              "<b>rata-rata berbobot (weighted)</b> antar kelas — berbeda "
              "dari EVE-cbr yang memakai kelas attack natural-holdout.",
        "en": "Metric semantics: the headline precision/recall/F1 are a "
              "<b>weighted average</b> across classes — unlike EVE-cbr, "
              "which uses the attack class on the natural holdout."},
    "rpt.note_label_origin_eve": {
        "id": "Asal label: diturunkan dari <b>alert Suricata</b> "
              "(disempurnakan konservatif) — bukan kebenaran lapangan "
              "eksternal; hasil dibaca sebagai kesepakatan model terhadap "
              "alert.",
        "en": "Label origin: derived from <b>Suricata alerts</b> "
              "(conservatively refined) — not external ground truth; the "
              "results read as the model's agreement with those alerts."},
    "rpt.note_label_origin_hikari": {
        "id": "Asal label: <b>ground-truth</b> bawaan HIKARI2021 (benign vs "
              "malicious).",
        "en": "Label origin: the <b>ground truth</b> shipped with HIKARI2021 "
              "(benign vs malicious)."},
    "rpt.note_antileak": {"id": "Anti-kebocoran: {parts}.",
                          "en": "Anti-leakage: {parts}."},
    "rpt.leak_group_split": {"id": "pemisahan berbasis grup ({value})",
                             "en": "group-based splitting ({value})"},
    "rpt.leak_pipeline_scaling": {
        "id": "penskalaan di dalam pipeline (tanpa kebocoran ke data uji)",
        "en": "scaling inside the pipeline (with no leakage into the test "
              "data)"},
    "rpt.leak_dual_holdout": {
        "id": "dual holdout: natural (utama) + balanced (sekunder)",
        "en": "dual holdout: natural (primary) + balanced (secondary)"},
    "rpt.leak_forbidden_guard": {
        "id": "penjaga fitur terlarang (kolom pembocor label diblokir)",
        "en": "a forbidden-feature guard (label-leaking columns are blocked)"},
    "rpt.note_antileak_hikari": {
        "id": "Anti-kebocoran: scaler/PCA/penyeimbang di-<i>fit</i> hanya "
              "pada data latih setelah split, lalu diterapkan ke data uji.",
        "en": "Anti-leakage: the scaler/PCA/balancer is <i>fit</i> on the "
              "training data only, after the split, and then applied to the "
              "test data."},
    "rpt.note_class_balance": {
        "id": "Keseimbangan kelas (data uji): serangan {share} dari total "
              "({attacks} vs {normals} normal); pada data timpang accuracy "
              "tunggal dapat menyesatkan.",
        "en": "Class balance (test data): attacks are {share} of the total "
              "({attacks} vs {normals} normal); on imbalanced data, accuracy "
              "alone can mislead."},
    "rpt.note_svc_limit": {
        "id": "Keterbatasan algoritma: Support Vector Classifier berskala "
              "O(n²) dan lambat pada data ratusan ribu baris.",
        "en": "Algorithm limitation: the Support Vector Classifier scales as "
              "O(n²) and is slow on data with hundreds of thousands of rows."},

    # ── Kaki halaman ─────────────────────────────────────────────────────
    "rpt.footer": {
        "id": "Dihasilkan oleh IDS Research Pipeline System &middot; {time} "
              "&middot; experiment {experiment}",
        "en": "Generated by the IDS Research Pipeline System &middot; {time} "
              "&middot; experiment {experiment}"},

    # ── Teks di dalam grafik ─────────────────────────────────────────────
    "rpt.cm_tn": {"id": "Normal benar\n(TN)", "en": "Correct normal\n(TN)"},
    "rpt.cm_fp": {"id": "False alarm\n(FP)", "en": "False alarm\n(FP)"},
    "rpt.cm_fn": {"id": "Serangan LOLOS\n(FN)", "en": "Attack MISSED\n(FN)"},
    "rpt.cm_tp": {"id": "Serangan terdeteksi\n(TP)",
                  "en": "Attack detected\n(TP)"},
    "rpt.cm_predicted": {"id": "Prediksi: {name}", "en": "Predicted: {name}"},
    "rpt.cm_actual": {"id": "Aktual: {name}", "en": "Actual: {name}"},
    "rpt.chart_random_guess": {"id": "Tebak acak", "en": "Random guess"},
    "rpt.chart_roc_title": {"id": "Kurva ROC (AUC = {auc})",
                            "en": "ROC Curve (AUC = {auc})"},
    "rpt.chart_fi_title": {"id": "Top {shown} Feature Importance",
                           "en": "Top {shown} Feature Importance"},
    "rpt.chart_fi_title_total": {
        "id": "Top {shown} Feature Importance (dari {total} fitur)",
        "en": "Top {shown} Feature Importance (of {total} features)"},


    # ── Panduan: diagram alur ────────────────────────────────────────────
    "ins.flow_upload": {"id": "Unggah", "en": "Upload"},
    "ins.flow_auto_check": {"id": "Periksa otomatis",
                            "en": "Automatic check"},
    "ins.flow_admin_review": {"id": "Tinjau Research Admin",
                              "en": "Research Admin review"},
    "ins.flow_active": {"id": "Aktif", "en": "Active"},
    "ins.flow_pipeline_alt": {
        "id": "Alur: unggah berkas, diperiksa otomatis secara statis, "
              "ditinjau Research Admin, lalu aktif.",
        "en": "The flow: upload the file, it is checked automatically and "
              "statically, reviewed by a Research Admin, then it goes active."},
    "ins.flow_match_check": {"id": "Periksa kecocokan",
                             "en": "Compatibility check"},
    "ins.flow_available": {"id": "Tersedia", "en": "Available"},
    "ins.flow_dataset_alt": {
        "id": "Alur: unggah berkas, diperiksa kecocokannya dengan tiap "
              "research pipeline, lalu langsung tersedia untuk eksperimen.",
        "en": "The flow: upload the file, its compatibility is checked "
              "against every research pipeline, and it is then immediately "
              "available for experiments."},

    "ins.chip_more": {"id": "+{count} lainnya", "en": "+{count} more"},

    # ── Panduan: tabel kontrak pipeline ──────────────────────────────────
    # Pemilih research pipeline pada halaman Tambah Dataset. Menggantikan
    # sederet tab, yang tumbuh ke samping setiap kali sebuah research pipeline
    # kontribusi disetujui.
    "ins.lbl_research_pipeline": {"id": "Research Pipeline",
                                  "en": "Research Pipeline"},
    "ins.col_aspect": {"id": "Aspek", "en": "Aspect"},
    "ins.col_rule": {"id": "Ketentuan", "en": "Requirement"},
    "ins.row_base_class": {"id": "Kelas induk", "en": "Parent class"},
    "ins.row_required_methods": {"id": "Metode wajib",
                                 "en": "Required methods"},
    "ins.row_run_signature": {"id": "Tanda tangan `run`",
                              "en": "`run` signature"},
    "ins.row_entry_point": {"id": "Titik masuk", "en": "Entry point"},
    "ins.rule_entry_point": {
        "id": "tepat **satu** berkas memuat kelas turunan itu; berkas lain "
              "pendukung",
        "en": "exactly **one** file holds that subclass; the other files are "
              "supporting ones"},
    "ins.row_anti_leak": {"id": "Anti-kebocoran", "en": "Anti-leakage"},
    "ins.rule_anti_leak": {
        "id": "scaler/PCA/penyeimbang di-*fit* hanya pada data latih "
              "(setelah split)",
        "en": "the scaler/PCA/balancer is *fit* on the training data only "
              "(after the split)"},
    "ins.row_info_keys": {"id": "Kunci `get_info()`",
                          "en": "`get_info()` keys"},

    "ins.modules_allowed": {"id": "**Modul diizinkan ({count})**",
                            "en": "**Allowed modules ({count})**"},
    "ins.modules_rejected": {"id": "**Modul ditolak ({count})**",
                             "en": "**Rejected modules ({count})**"},

    # Ketegasan dipertahankan: "tidak dijalankan" dan "lolos BUKAN berarti
    # aktif" harus tetap terbaca sekeras aslinya.
    "ins.static_check_note": {
        "id": "🔒 Pemeriksaan <b>statis</b> — berkas dibaca, <b>tidak "
              "dijalankan</b>. Lolos <b>bukan</b> berarti aktif: menunggu "
              "tinjauan Research Admin.",
        "en": "🔒 The check is <b>static</b> — the file is read, <b>not "
              "executed</b>. Passing does <b>not</b> mean active: it waits "
              "for Research Admin review."},

    "ins.expected_shape": {"id": "**Bentuk yang diharapkan**",
                           "en": "**The expected shape**"},
    "ins.mistakes_pipeline_title": {
        "id": "Paling sering membuat paket ditolak",
        "en": "What most often gets a package rejected"},
    "ins.mistakes_dataset_title": {
        "id": "Paling sering membuat dataset dinyatakan belum cocok",
        "en": "What most often makes a dataset come back as not matching"},

    "ins.exp_full_requirements": {
        "id": "Persyaratan lengkap — modul & pemanggilan",
        "en": "Full requirements — modules & calls"},
    "ins.modules_reasonable": {"id": "**Modul yang wajar dipakai**",
                               "en": "**Modules it is reasonable to use**"},
    "ins.modules_forbidden": {"id": "**Modul yang dilarang**",
                              "en": "**Forbidden modules**"},
    "ins.calls_forbidden": {"id": "**Pemanggilan yang dilarang**",
                            "en": "**Forbidden calls**"},
    "ins.outside_list_caption": {
        "id": "Di luar daftar → ditandai, tidak menggagalkan. Sumber: "
              "konstanta validator.",
        "en": "Outside the list → flagged, not failed. Source: the "
              "validator's own constants."},
    "ins.outside_list_help": {
        "id": "Pemanggilan terlarang mencakup `os.system()`, `open()` mode "
              "tulis, dan atribut sandbox-escape (`__subclasses__`, "
              "`__globals__`, `__builtins__`).",
        "en": "Forbidden calls include `os.system()`, `open()` in write mode, "
              "and sandbox-escape attributes (`__subclasses__`, "
              "`__globals__`, `__builtins__`)."},

    # ── Panduan: dokumen kontrak ─────────────────────────────────────────
    "ins.contract_intro": {
        "id": "**Kontrak pipeline** — nama field dibaca langsung dari "
              "`contracts/pipeline_contracts.py`.",
        "en": "**The pipeline contract** — field names are read directly "
              "from `contracts/pipeline_contracts.py`."},
    "ins.tab_input": {"id": "Masukan", "en": "Input"},
    "ins.tab_return": {"id": "Kembalian", "en": "Return"},
    "ins.tab_stages": {"id": "Tahapan", "en": "Stages"},
    "ins.tab_forbidden": {"id": "Larangan", "en": "Prohibitions"},
    "ins.exp_minimal_skeleton": {"id": "Kerangka kelas minimal",
                                 "en": "Minimal class skeleton"},

    "ins.col_type": {"id": "Tipe", "en": "Type"},
    "ins.col_meaning": {"id": "Arti", "en": "Meaning"},
    "ins.required": {"id": "wajib", "en": "required"},
    "ins.optional": {"id": "opsional", "en": "optional"},

    "ins.col_stage": {"id": "Tahap", "en": "Stage"},
    "ins.col_owner": {"id": "Dikerjakan", "en": "Done by"},
    "ins.col_note": {"id": "Catatan", "en": "Note"},
    # Aturan anti-kebocoran: urutannya (split DULU) harus tetap tegas.
    "ins.anti_leak_note": {
        "id": "Langkah 2–3 adalah aturan anti-kebocoran: split DULU, baru fit "
              "praproses — dan hanya pada data latih.",
        "en": "Steps 2–3 are the anti-leakage rule: split FIRST, then fit the "
              "preprocessing — and only on the training data."},

    "ins.required_heading": {"id": "**Wajib**", "en": "**Required**"},
    "ins.suggested_note": {
        "id": "Disarankan, bukan wajib: tidak diperiksa validator dan "
              "pipeline bawaan pun belum menyediakannya.",
        "en": "Suggested, not required: the validator does not check them, "
              "and even the built-in pipelines do not provide them yet."},
    "ins.suggested_line": {
        "id": "**Disarankan** — {note} Kunci wajib yang hilang menghasilkan "
              "{severity}, bukan kegagalan.",
        "en": "**Suggested** — {note} A missing required key produces "
              "{severity}, not a failure."},
    "ins.severity_warning": {"id": "peringatan", "en": "a warning"},

    # Daftar larangan: kerangkanya tetap menyebut alasannya, tidak diperhalus.
    "ins.forbidden_frame": {
        "id": "Ini yang memisahkan masukan yang dikendalikan pengguna dari "
              "parameter yang ditetapkan eksperimen — dasar perbandingan yang "
              "adil dan hasil yang dapat diulang.",
        "en": "This is what separates user-controlled input from the "
              "parameters the experiment fixes — the basis for a fair "
              "comparison and for results that can be reproduced."},

    # ── Panduan: kesalahan tersering pada pipeline ───────────────────────
    "ins.mis_entry_point": {
        "id": "Titik masuk tidak tepat satu — tidak ada berkas dengan kelas "
              "turunan `{base_class}`, atau justru lebih dari satu.",
        "en": "The entry point is not exactly one — no file holds a "
              "`{base_class}` subclass, or more than one does."},
    "ins.mis_pipeline_class": {
        "id": "Kelas pipeline tidak mewarisi `{base_class}`.",
        "en": "The pipeline class does not inherit from `{base_class}`."},
    "ins.mis_method_run": {"id": "Metode wajib `{method}()` belum ada.",
                           "en": "The required `{method}()` method is missing."},
    "ins.mis_method_get_info": {
        "id": "Metode wajib `{method}()` belum ada.",
        "en": "The required `{method}()` method is missing."},
    "ins.mis_forbidden_import": {
        "id": "Mengimpor modul terlarang — mis. `{module}`.",
        "en": "Importing a forbidden module — e.g. `{module}`."},
    "ins.mis_forbidden_call": {
        "id": "Memakai pemanggilan terlarang — mis. `{call}()`.",
        "en": "Using a forbidden call — e.g. `{call}()`."},
    "ins.mis_syntax": {"id": "Berkas gagal diurai — bukan Python yang valid.",
                       "en": "The file could not be parsed — it is not valid "
                             "Python."},
    "ins.mis_dunder": {
        "id": "Menyentuh atribut pelolos sandbox (`__globals__`, "
              "`__subclasses__`).",
        "en": "Touching sandbox-escape attributes (`__globals__`, "
              "`__subclasses__`)."},
    "ins.mis_file_write": {"id": "Membuka berkas dalam mode tulis.",
                           "en": "Opening a file in write mode."},
    "ins.mis_get_info_dict": {
        "id": "`{method}()` tidak mengembalikan dict.",
        "en": "`{method}()` does not return a dict."},

    # ── Panduan: kesalahan tersering pada dataset ────────────────────────
    "ins.dsmis_format": {
        "id": "ekstensi/bentuk berkas tidak sesuai, atau isinya gagal diparse",
        "en": "the file extension or shape does not match, or its contents "
              "could not be parsed"},
    "ins.dsmis_label": {
        "id": "kolom label yang diminta research pipeline tidak ditemukan",
        "en": "the label column the research pipeline asks for is not there"},
    "ins.dsmis_features": {
        "id": "kolom fitur yang diharapkan skema banyak yang hilang",
        "en": "many of the feature columns the schema expects are missing"},
    "ins.dsmis_dtype": {
        "id": "kolom fitur tidak numerik sehingga tidak dapat dilatih",
        "en": "the feature columns are not numeric, so they cannot be "
              "trained on"},
    "ins.dsmis_classes": {
        "id": "hanya satu kelas yang muncul — tidak ada contoh attack",
        "en": "only one class appears — there are no attack examples"},

    # ── Panduan: persyaratan dataset ─────────────────────────────────────
    "ins.dsrow_format": {"id": "Format berkas", "en": "File format"},
    "ins.dsrow_label_column": {"id": "Kolom label", "en": "Label column"},
    "ins.dsrow_feature_nature": {"id": "Sifat fitur", "en": "Feature nature"},
    "ins.dsrow_class_count": {"id": "Jumlah kelas", "en": "Number of classes"},
    "ins.dsval_two_classes": {"id": "dua kelas (benign & attack)",
                              "en": "two classes (benign & attack)"},
    "ins.dslabel_from_suricata": {
        "id": "`{column}` — dibentuk pipeline dari **alert Suricata**, tidak "
              "perlu ada di berkas",
        "en": "`{column}` — built by the pipeline from **Suricata alerts**; "
              "it need not be present in the file"},
    "ins.dslabel_binary": {"id": "`{column}` — `0` = benign, `1` = malicious",
                           "en": "`{column}` — `0` = benign, `1` = malicious"},
    # Kontrak yang DIDEKLARASIKAN kontributor: ia menyebut nama kolomnya,
    # bukan arti nilainya — jadi artinya tidak dikarang di sini.
    "ins.dslabel_declared": {"id": "`{column}` — sesuai kontrak yang dinyatakan pengunggah",
                             "en": "`{column}` — as declared by the uploader"},
    "ins.dsrow_required_columns": {"id": "Kolom wajib", "en": "Required columns"},
    "ins.dsval_declared_columns": {"id": "{count} kolom sesuai kontrak yang dinyatakan",
                                   "en": "{count} columns per the declared contract"},

    "ins.dschk_json_format": {
        "id": "Format {exts}, satu objek JSON per baris.",
        "en": "Format {exts}, one JSON object per line."},
    "ins.dschk_tls_events": {
        "id": "Memuat event TLS (`app_proto`/`event_type` = `tls`).",
        "en": "Contains TLS events (`app_proto`/`event_type` = `tls`)."},
    "ins.dschk_no_label_column": {
        "id": "Tidak perlu kolom `{column}` — dibentuk dari alert Suricata.",
        "en": "No `{column}` column needed — it is built from Suricata "
              "alerts."},
    "ins.dschk_alert_events": {
        "id": "Ada event `alert`, sehingga kelas attack tidak kosong.",
        "en": "There are `alert` events, so the attack class is not empty."},
    "ins.dschk_csv_format": {"id": "Format {exts}, satu baris per flow.",
                             "en": "Format {exts}, one row per flow."},
    "ins.dschk_label_column": {
        "id": "Ada kolom label `{column}` berisi `0`/`1`.",
        "en": "There is a `{column}` label column holding `0`/`1`."},
    "ins.dschk_numeric_features": {
        "id": "Kolom fitur numerik (non-numerik diabaikan otomatis).",
        "en": "The feature columns are numeric (non-numeric ones are ignored "
              "automatically)."},
    "ins.dschk_two_classes": {"id": "Berisi dua kelas: benign dan malicious.",
                              "en": "It holds two classes: benign and "
                                    "malicious."},

    "ins.dataset_sample_note": {
        "id": "🔍 Angka berasal dari <b>cuplikan</b> berkas, bukan seluruh "
              "isinya. Dataset <b>tersimpan langsung</b> — tinjauan hanya "
              "untuk pipeline, yang berisi kode.",
        "en": "🔍 Figures come from a <b>sample</b>, not the whole file. "
              "Datasets are <b>stored at once</b> — review covers only "
              "pipelines, which hold code."},
    "ins.exp_dataset_requirements": {"id": "Persyaratan dataset lengkap",
                                     "en": "Full dataset requirements"},

    # ── Persyaratan per dataset (konstanta di run_experiment tidak diubah) ─
    "ins.req_hikari_row_unit": {"id": "satu baris per **flow** jaringan",
                                "en": "one row per network **flow**"},
    "ins.req_hikari_feature_nature": {
        "id": "Kolom **numerik berbasis flow** — durasi, hitungan "
              "paket/header, statistik payload & inter-arrival time.",
        "en": "**Flow-based numeric** columns — duration, packet/header "
              "counts, payload statistics & inter-arrival time."},
    "ins.req_hikari_summary": {"id": "fitur numerik berbasis flow",
                               "en": "flow-based numeric features"},
    "ins.req_eve_row_unit": {
        "id": "satu objek JSON per baris (satu **event**)",
        "en": "one JSON object per line (one **event**)"},
    "ins.req_eve_feature_nature": {
        "id": "Field mentah **Suricata EVE log**. Pipeline memfilter **event "
              "TLS** lalu merekayasa & menyeleksi fiturnya sendiri — berkas "
              "tidak perlu berisi kolom fitur siap pakai.",
        "en": "Raw **Suricata EVE log** fields. The pipeline filters **TLS "
              "events**, then engineers and selects its own features — the "
              "file need not contain ready-made feature columns."},
    "ins.req_eve_summary": {
        "id": "field EVE mentah, fokus event TLS (label dari alert)",
        "en": "raw EVE fields, focused on TLS events (labels from alerts)"},
    "ins.req_eve_class_hint": {"id": "dua kelas setelah pelabelan dari alert",
                               "en": "two classes once labelled from alerts"},


    # ── Arti field kontrak (nama fieldnya sendiri tetap apa adanya) ──────
    "ins.fld_df": {"id": "DataFrame dataset yang sudah diparsing platform.",
                   "en": "The dataset DataFrame, already parsed by the "
                         "platform."},
    "ins.fld_label_column": {"id": "Nama kolom label pada `df`.",
                             "en": "Name of the label column in `df`."},
    "ins.fld_dataset_type": {
        "id": "Research pipeline yang dituju (mis. HIKARI2021).",
        "en": "The research pipeline this is meant for (e.g. HIKARI2021)."},
    "ins.fld_test_size": {"id": "Proporsi data uji.",
                          "en": "The proportion held out for testing."},
    "ins.fld_random_state": {"id": "Benih acak — kunci hasil dapat diulang.",
                             "en": "The random seed — the key to reproducible "
                                   "results."},
    "ins.fld_dataset_path": {
        "id": "Path berkas mentah, untuk pipeline yang membaca berkas sendiri.",
        "en": "Path to the raw file, for pipelines that read the file "
              "themselves."},
    "ins.fld_param_overrides": {
        "id": "Penyesuaian hyperparameter untuk run eksplorasi; KOSONG pada "
              "run resmi. Isinya hanya kunci yang ada di `fixed_params` dan "
              "sudah divalidasi orchestrator.",
        "en": "Hyperparameter adjustments for an exploration run; EMPTY on an "
              "official run. It holds only keys that exist in `fixed_params`, "
              "already validated by the orchestrator."},
    "ins.fld_accuracy": {"id": "Akurasi keseluruhan.",
                         "en": "Overall accuracy."},
    "ins.fld_precision": {"id": "Presisi.", "en": "Precision."},
    "ins.fld_recall": {"id": "Recall.", "en": "Recall."},
    "ins.fld_f1_score": {"id": "F1-score.", "en": "F1-score."},
    "ins.fld_confusion_matrix": {
        "id": "Matriks kebingungan sebagai list of list.",
        "en": "The confusion matrix as a list of lists."},
    "ins.fld_model": {"id": "Objek model terlatih.",
                      "en": "The trained model object."},
    "ins.fld_feature_names": {"id": "Nama fitur yang benar-benar dipakai.",
                              "en": "Names of the features actually used."},
    "ins.fld_label_mapping": {"id": "Peta nama kelas → nilai label.",
                              "en": "A map from class name to label value."},
    "ins.fld_extra_info": {"id": "Tambahan bebas (ROC, learning curve, dll).",
                           "en": "Anything extra (ROC, learning curve, etc.)."},

    # ── Panel persyaratan dataset (halaman Run Experiment) ───────────────
    "re.req_col_aspect": {"id": "Aspek", "en": "Aspect"},
    "re.req_col_requirement": {"id": "Persyaratan", "en": "Requirement"},
    "re.req_row_format": {"id": "**Format berkas**", "en": "**File format**"},
    "re.req_row_label": {"id": "**Kolom label (target)**",
                         "en": "**Label column (target)**"},
    "re.req_row_features": {"id": "**Fitur yang diharapkan**",
                            "en": "**Expected features**"},
    "re.req_unknown_format": {"id": "- **Format berkas:** {exts}",
                              "en": "- **File format:** {exts}"},
    "re.req_unknown_label": {"id": "- **Kolom label (target):** `{column}`",
                             "en": "- **Label column (target):** `{column}`"},
    "re.req_label_hikari": {"id": "`{column}` — `0` = {benign}, `1` = "
                                  "{malicious}",
                            "en": "`{column}` — `0` = {benign}, `1` = "
                                  "{malicious}"},
    "re.req_features_counted": {
        "id": "{nature} Skema mencatat **{count} kolom fitur**.",
        "en": "{nature} The schema records **{count} feature columns**."},
    "re.req_label_eve": {
        "id": "`{column}` — dibentuk **oleh pipeline dari alert Suricata** "
              "(`event_type` = `alert` atau alert valid)",
        "en": "`{column}` — built **by the pipeline from Suricata alerts** "
              "(`event_type` = `alert`, or a valid alert)"},
    "re.req_label_eve_refined": {"id": "{base}, lalu disempurnakan menjadi "
                                       "`{target}`",
                                 "en": "{base}, then refined into `{target}`"},
    # Ketegasan dipertahankan: label EVE BUKAN ground-truth eksternal.
    "re.req_label_eve_tail": {
        "id": "{base}; `0` = {benign}, `1` = {attack}. Bukan anotasi "
              "*ground-truth* eksternal — berkas mentah tidak perlu kolom "
              "label.",
        "en": "{base}; `0` = {benign}, `1` = {attack}. This is not external "
              "*ground-truth* annotation — the raw file needs no label "
              "column."},
    "re.req_dropped_columns": {
        "id": "Kolom non-fitur berikut dibuang otomatis oleh preprocessing "
              "(boleh ada, boleh tidak — akan diabaikan): {columns}. Kolom "
              "non-numerik lain juga otomatis dibuang.",
        "en": "The following non-feature columns are dropped automatically by "
              "preprocessing (they may or may not be present — either way "
              "they are ignored): {columns}. Other non-numeric columns are "
              "dropped automatically too."},
    "re.req_structure_example": {"id": "**Contoh struktur**",
                                 "en": "**Example structure**"},
    "re.req_caption_columns": {
        "id": "Nama kolom diambil dari `contracts/dataset_schemas.py`; "
              "nilainya ilustratif. `…` = kolom lain — ini **bukan** daftar "
              "kolom lengkap.",
        "en": "Column names come from `contracts/dataset_schemas.py`; the "
              "values are illustrative. `…` = other columns — this is "
              "**not** the complete column list."},
    "re.req_caption_fields": {
        "id": "Nama field diambil dari `expected_top_level_keys` pada "
              "`contracts/dataset_schemas.py`; nilainya ilustratif. Contoh "
              "disederhanakan — event lain (mis. `event_type` = `alert` "
              "dengan objek `alert`) tetap diperlukan karena dipakai untuk "
              "membentuk label.",
        "en": "Field names come from `expected_top_level_keys` in "
              "`contracts/dataset_schemas.py`; the values are illustrative. "
              "The example is simplified — other events (e.g. `event_type` = "
              "`alert` carrying an `alert` object) are still required, "
              "because they are what the labels are built from."},
    "re.req_checklist_heading": {"id": "**Dataset Anda cocok jika…**",
                                 "en": "**Your dataset matches if…**"},
    "re.req_chk_format": {"id": "Format berkasnya {exts} — {row_unit}.",
                          "en": "Its file format is {exts} — {row_unit}."},
    "re.req_chk_label_hikari": {
        "id": "Ada kolom label bernama persis `{column}` berisi `0`/`1`.",
        "en": "There is a label column named exactly `{column}` holding "
              "`0`/`1`."},
    "re.req_chk_numeric": {
        "id": "Kolom fiturnya **numerik** (kolom non-numerik & non-fitur di "
              "atas otomatis diabaikan).",
        "en": "Its feature columns are **numeric** (the non-numeric and "
              "non-feature columns above are ignored automatically)."},
    "re.req_chk_two_classes_hikari": {
        "id": "Berisi **dua kelas**: `0` = {benign} dan `1` = {malicious}.",
        "en": "It holds **two classes**: `0` = {benign} and `1` = "
              "{malicious}."},
    "re.req_chk_tls_events": {
        "id": "Berisi **event TLS** (`app_proto` / `event_type` = `tls`, atau "
              "port 443/8443) — pipeline yang memisahkannya.",
        "en": "It contains **TLS events** (`app_proto` / `event_type` = "
              "`tls`, or port 443/8443) — the pipeline is what separates "
              "them."},
    "re.req_chk_no_label": {
        "id": "Tidak perlu kolom label: `{column}` dibentuk pipeline dari "
              "alert Suricata pada berkas yang sama.",
        "en": "No label column is needed: `{column}` is built by the pipeline "
              "from Suricata alerts in the same file."},
    "re.req_chk_two_classes_eve": {
        "id": "Berisi **dua kelas** setelah pelabelan — ada event `alert` "
              "sehingga kelas {attack} tidak kosong.",
        "en": "It holds **two classes** once labelled — there are `alert` "
              "events, so the {attack} class is not empty."},


    # ── Kartu kontribusi (P4) ───────────────────────────────────────
    "ap.card_pipeline_title": {"id": "Unggah Pipeline",
                              "en": "Upload Pipeline"},
    "ap.card_pipeline_text": {"id": "Berkas .py pipeline. Diperiksa statis terhadap kontrak & aturan keamanan sebelum ditinjau.",
                             "en": "A .py pipeline file. Checked statically against the contract & security rules before review."},
    "ap.card_pipeline_button": {"id": "Unggah pipeline",
                               "en": "Upload pipeline"},
    "ap.card_dataset_title": {"id": "Unggah Dataset",
                             "en": "Upload Dataset"},
    "ap.card_dataset_text": {"id": "Berkas .csv / .ndjson / .jsonl. Langsung diperiksa kecocokannya dengan tiap research pipeline.",
                            "en": "A .csv / .ndjson / .jsonl file. Checked straight away for a match against every research pipeline."},
    "ap.card_dataset_button": {"id": "Unggah dataset",
                              "en": "Upload dataset"},
    "ap.card_review_title": {"id": "Peninjauan Pengajuan",
                            "en": "Submission Review"},
    "ap.card_review_text": {"id": "Baca pengajuan yang masuk, lalu setujui atau tolak berikut catatan alasannya.",
                           "en": "Read the incoming submissions, then approve or reject them with a note giving the reason."},
    "ap.card_review_button": {"id": "Buka peninjauan",
                             "en": "Open review"},
    "ap.card_users_title": {"id": "Kelola Pengguna",
                           "en": "Manage Users"},
    "ap.card_users_text": {"id": "Ubah peran, nonaktifkan atau aktifkan kembali akun, dan lihat daftar pengguna.",
                          "en": "Change roles, deactivate or reactivate accounts, and see the list of users."},
    "ap.card_users_button": {"id": "Buka kelola pengguna",
                            "en": "Open manage users"},
    "ap.card_need_contributor": {"id": "Perlu akun Kontributor.",
                                "en": "A Contributor account is required."},
    "ap.card_admin_only": {"id": "Khusus Research Admin.",
                          "en": "Research Admin only."},
    "ap.card_denied_hint": {"id": "Masuk lewat pemilih mode di kiri bawah untuk memakainya.",
                           "en": "Sign in through the mode picker at the bottom left to use it."},
    "ap.visitor_admin_note": {"id": "Peninjauan pengajuan & kelola pengguna memerlukan akun Research Admin.",
                             "en": "Submission review & user management require a Research Admin account."},
    "ap.art_pipeline": {"id": "Berkas kode",
                       "en": "A code file"},
    "ap.art_dataset": {"id": "Tumpukan data",
                      "en": "A stack of data"},
    "ap.art_review": {"id": "Dokumen dengan tanda centang",
                     "en": "A document with a tick"},
    "ap.art_users": {"id": "Sosok pengguna",
                    "en": "A user figure"},


    # ── Konteks kontribusi & peran (P4) ───────────────────────────────────────
    "ap.flow_upload": {"id": "Unggah",
                      "en": "Upload"},
    "ap.flow_check_file": {"id": "Periksa berkas",
                          "en": "Check the file"},
    "ap.flow_dataset_stored": {"id": "Dataset tersimpan",
                              "en": "Dataset stored"},
    "ap.flow_pipeline_reviewed": {"id": "Pipeline ditinjau",
                                 "en": "Pipeline reviewed"},
    "ap.after_upload_alt": {"id": "Setelah berkas lolos pemeriksaan otomatis: dataset langsung tersimpan; pipeline menunggu tinjauan Research Admin karena berisi kode yang dieksekusi.",
                           "en": "Once a file passes the automatic check: a dataset is stored straight away; a pipeline waits for Research Admin review, because it contains code that will be executed."},
    "ap.cap_visitor_label": {"id": "Mode pengunjung",
                            "en": "Visitor mode"},
    "ap.cap_visitor_what": {"id": "dapat membaca persyaratan dan memeriksa kecocokan dataset; mengunggah memerlukan akun Kontributor",
                           "en": "can read the requirements and check dataset compatibility; uploading requires a Contributor account"},
    "ap.cap_user_fallback": {"id": "Pengguna",
                            "en": "User"},
    "ap.cap_may_review": {"id": "mengajukan, meninjau, mengelola pengguna",
                         "en": "submit, review, manage users"},
    "ap.cap_may_upload": {"id": "mengajukan pipeline & dataset",
                         "en": "submit pipelines & datasets"},
    "ap.cap_pending": {"id": "menunggu persetujuan — belum dapat mengajukan",
                      "en": "awaiting approval — cannot submit yet"},
    "ap.cap_pending_readable": {"id": "Menunggu persetujuan — halaman tetap dapat dibaca.",
                               "en": "Awaiting approval — the page can still be read."},
    "ap.cap_login_prompt": {"id": "Mengajukan berkas memerlukan akun.",
                           "en": "Submitting a file requires an account."},
    "ap.role_contributor": {"id": "Kontributor",
                           "en": "Contributor"},
    "ap.role_research_admin": {"id": "Research Admin",
                              "en": "Research Admin"},


    # ── Peninjauan: registry (P5) ───────────────────────────────────────
    "rv.col_pipeline": {"id": "Pipeline",
                       "en": "Pipeline"},
    "rv.col_version": {"id": "Versi",
                      "en": "Version"},
    "rv.col_hash": {"id": "Hash",
                   "en": "Hash"},
    "rv.col_dataset": {"id": "Dataset",
                      "en": "Dataset"},
    "rv.col_status": {"id": "Status",
                     "en": "Status"},
    "rv.col_version_count": {"id": "Versi tercatat",
                            "en": "Versions"},
    "rv.col_experiments": {"id": "Eksperimen",
                          "en": "Experiments"},
    "rv.col_by": {"id": "Oleh",
                 "en": "By"},
    "rv.col_when": {"id": "Waktu",
                   "en": "Time"},
    "rv.col_note": {"id": "Catatan",
                   "en": "Note"},
    "rv.col_submission": {"id": "Pengajuan",
                         "en": "Submission"},
    "rv.col_check_result": {"id": "Hasil periksa",
                           "en": "Check result"},
    "rv.col_file": {"id": "Berkas",
                   "en": "File"},
    "rv.col_submitted_by": {"id": "Diajukan oleh",
                           "en": "Submitted by"},
    "rv.empty_active": {"id": "Belum ada pipeline kontribusi — daftar akan terisi setelah ada pengajuan yang disetujui.",
                       "en": "No contributed pipelines yet — the list fills up once a submission is approved."},
    "rv.empty_history": {"id": "Belum ada versi tercatat untuk pipeline ini.",
                        "en": "No versions recorded for this pipeline yet."},
    "rv.retention_note": {"id": "Versi lama tetap tersimpan — eksperimen terdahulu tetap tertelusur.",
                         "en": "Older versions are kept — earlier experiments stay traceable."},
    "rv.read_only_note": {"id": "Baca-saja. Menyunting membuat versi BARU, tidak menimpa.",
                         "en": "Read-only. Editing creates a NEW version; it does not overwrite."},
    "rv.experiment_link_note": {"id": "Saring di Progress & Status lewat kolom Pipeline.",
                               "en": "Filter on Progress & Status using the Pipeline column."},
    "rv.state_missing": {"id": "Berkas versi ini tidak ditemukan di disk — pipeline tidak dapat dimuat dan eksperimen barunya akan gagal.",
                        "en": "This version's file was not found on disk — the pipeline cannot be loaded and new experiments with it will fail."},
    "rv.state_tampered": {"id": "SHA-256 berkas berbeda dari yang tercatat saat pendaftaran — berkas berubah di luar platform. Pemuatan ditolak demi menjaga ketertelusuran.",
                         "en": "The file's SHA-256 differs from the one recorded at registration — the file changed outside the platform. Loading is refused to keep the trail intact."},
    "rv.deactivate_consequence": {"id": "Menonaktifkan hanya menutup pipeline ini dari pilihan eksperimen BARU — eksperimen yang sudah ada tidak terpengaruh, dan berkas serta catatan versinya tetap utuh.",
                                 "en": "Deactivating only removes this pipeline from the choices for NEW experiments — existing experiments are unaffected, and its files and version records stay intact."},
    "rv.lbl_identity": {"id": "Identitas",
                       "en": "Identity"},
    "rv.lbl_active_version": {"id": "Versi aktif",
                             "en": "Active version"},
    "rv.lbl_dataset_type": {"id": "Jenis dataset",
                           "en": "Dataset type"},
    "rv.lbl_algorithm": {"id": "Algoritma",
                        "en": "Algorithm"},
    "rv.lbl_entry_class": {"id": "Kelas titik masuk",
                          "en": "Entry-point class"},
    "rv.lbl_paper": {"id": "Paper / rujukan",
                    "en": "Paper / reference"},
    "rv.lbl_approved": {"id": "Disetujui",
                       "en": "Approved"},
    "rv.lbl_last_edited": {"id": "Disunting terakhir",
                          "en": "Last edited"},
    "rv.lbl_change_note": {"id": "Catatan perubahan",
                          "en": "Change note"},
    "rv.usage_none": {"id": "Belum dipakai eksperimen mana pun.",
                     "en": "Not used by any experiment yet."},
    "rv.usage_some": {"id": "{total} eksperimen — {parts}.",
                     "en": "{total} experiments — {parts}."},
    "rv.running_text": {"id": "Sedang dipakai {count} eksperimen berjalan ({parts}). Menyunting membuat versi baru dan tidak mengganggu eksekusi itu; menonaktifkan juga tidak menghentikannya.",
                       "en": "Currently used by {count} running experiments ({parts}). Editing creates a new version and does not disturb those runs; deactivating does not stop them either."},
    "rv.status_active": {"id": "aktif",
                        "en": "active"},
    "rv.status_inactive": {"id": "nonaktif",
                          "en": "inactive"},
    # Aktif TAPI belum dapat dijalankan. Tanpa kata ini, tabel di halaman
    # peninjauan dan halaman Jalankan Eksperimen mengatakan dua hal berbeda
    # tentang pipeline yang sama.
    "rv.status_no_dataset": {"id": "belum ada datasetnya",
                             "en": "no dataset yet"},
    "rv.state_missing_short": {"id": "berkas hilang",
                              "en": "file missing"},
    "rv.state_tampered_short": {"id": "hash tidak cocok",
                               "en": "hash mismatch"},


    # ── Peninjauan: pengajuan (P5) ───────────────────────────────────────
    "sr.empty_state": {"id": "Tidak ada pengajuan pipeline yang menunggu tinjauan.",
                      "en": "No pipeline submissions are waiting for review."},
    "sr.verdict_clean": {"id": "lolos tanpa catatan",
                        "en": "passed with no findings"},
    "sr.verdict_warned": {"id": "lolos dengan peringatan",
                         "en": "passed with warnings"},
    "sr.verdict_problem": {"id": "ada masalah",
                          "en": "has problems"},
    "sr.approve_consequence": {"id": "Menyetujui membuat versi 1 beserta hash-nya dan pipeline **langsung dapat dijalankan** pengguna.",
                              "en": "Approving creates version 1 together with its hash, and the pipeline becomes **immediately runnable** by users."},
    "sr.warning_note": {"id": "Ada peringatan: belum tentu masalah, tetapi sebaiknya dibaca sebelum menyetujui.",
                       "en": "There are warnings: not necessarily problems, but worth reading before approving."},
    "sr.submitter_note": {"id": "Catatan pengaju",
                         "en": "Submitter's note"},
    "sr.file_unreadable": {"id": "Berkas pengajuan tidak terbaca.",
                          "en": "The submission's file could not be read."},
    "sr.not_checkable": {"id": "Tidak dapat diperiksa.",
                        "en": "It cannot be checked."},


    # ── Peninjauan: kelola pipeline (P5) ───────────────────────────────────────
    "mp.idle_heading": {"id": "**Nonaktif ({count})** — tidak dapat dipilih untuk eksperimen baru; catatan & berkasnya tetap utuh.",
                       "en": "**Inactive ({count})** — cannot be chosen for new experiments; their records & files stay intact."},
    "mp.history_empty": {"id": "Tidak ada versi tercatat untuk `{pipeline}`.",
                        "en": "No versions recorded for `{pipeline}`."},


    # ── Validator: pesan & nama pemeriksaan (P6) ───────────────────────────────────────
    "err.chk_python_valid": {"id": "Berkas adalah Python yang valid.",
                            "en": "The file is valid Python."},
    "err.chk_run_signature": {"id": "Signature berbeda dari kontrak: {problems}.",
                             "en": "The signature differs from the contract: {problems}."},
    "err.chk_run_signature_first": {"id": "parameter pertama `{found}` (kontrak: `{expected}`)",
                                   "en": "first parameter `{found}` (the contract says `{expected}`)"},
    "err.chk_run_signature_progress": {"id": "tidak ada parameter opsional `{param}`",
                                      "en": "the optional `{param}` parameter is missing"},
    "err.chk_get_info_complete": {"id": "`get_info()` mengembalikan dict dengan seluruh kunci metadata yang disarankan.",
                                 "en": "`get_info()` returns a dict carrying every suggested metadata key."},
    "err.chk_get_info_missing": {"id": "`get_info()` mengembalikan dict, tetapi kunci berikut belum ada: {missing} (disarankan oleh `{source}`).",
                                "en": "`get_info()` returns a dict, but these keys are missing yet: {missing} (suggested by `{source}`)."},
    "err.name_python_syntax": {"id": "sintaks Python",
                              "en": "Python syntax"},
    "err.name_file_write": {"id": "penulisan berkas",
                           "en": "file writing"},


    # ── Atribusi: cakupan penelitian (P7) ───────────────────────────────────────
    "re.scope_hikari": {"id": "Perbandingan KNN, Random Forest, Decision Tree, Naive Bayes, SVC, dan Logistic Regression untuk deteksi trafik malicious pada jaringan terenkripsi.",
                       "en": "A comparison of KNN, Random Forest, Decision Tree, Naive Bayes, SVC, and Logistic Regression for detecting malicious traffic on encrypted networks."},
    "re.scope_eve": {"id": "Rekayasa fitur pada Suricata EVE log dengan seleksi fitur Mutual Information (MI), Recursive Feature Elimination (RFE), dan Principal Component Analysis (PCA) untuk deteksi trafik malicious.",
                    "en": "Feature engineering on Suricata EVE logs with Mutual Information (MI), Recursive Feature Elimination (RFE), and Principal Component Analysis (PCA) feature selection, for detecting malicious traffic."},


    # ── Tabel temuan & cakupan penelitian (P6/P7) ───────────────────────────────────────
    "mp.col_check": {"id": "Pemeriksaan",
                    "en": "Check"},
    "mp.col_line": {"id": "Baris",
                   "en": "Line"},
    "mp.col_detail": {"id": "Keterangan",
                     "en": "Detail"},
    "re.lbl_research_scope": {"id": "Cakupan penelitian sumber",
                             "en": "Scope of the source research"},


    # ── Validator: signature run() lolos ───────────────────────────────────────
    "err.chk_run_signature_ok": {"id": "`run(self, {first}, {progress}=None)` sesuai kontrak.",
                                "en": "`run(self, {first}, {progress}=None)` matches the contract."},


    # ── Riwayat versi: status & catatan bawaan (P5) ───────────────────────────────────────
    "rv.status_version_active": {"id": "aktif",
                                "en": "active"},
    "rv.status_version_inactive": {"id": "tidak aktif",
                                  "en": "inactive"},
    "rv.note_initial_version": {"id": "versi awal (dari persetujuan)",
                               "en": "initial version (from approval)"},


    # ── Kaitan halaman & ringkasan pengajuan ───────────────────────────────────────
    "ap.related_pages": {"id": "Dataset langsung tersedia di **{page}**; pipeline muncul setelah disetujui Research Admin.",
                        "en": "Datasets are available in **{page}** straight away; a pipeline appears once a Research Admin approves it."},
    "ap.sub_pending": {"id": "Menunggu tinjauan",
                      "en": "Awaiting review"},
    "ap.sub_approved": {"id": "Disetujui",
                       "en": "Approved"},
    "ap.sub_rejected": {"id": "Ditolak",
                       "en": "Rejected"},
    "ap.sub_other": {"id": "lainnya",
                    "en": "other"},
    "ap.sub_yours": {"id": "Pengajuan Anda — {parts}.",
                    "en": "Your submissions — {parts}."},


    # ── Progress & Status: tabel eksperimen ───────────────────────────────────────
    "ps.col_id": {"id": "ID",
                 "en": "ID"},
    "ps.col_time": {"id": "Waktu",
                   "en": "Time"},
    "ps.col_duration": {"id": "Durasi",
                       "en": "Duration"},
    "ps.col_pipeline": {"id": "Pipeline",
                       "en": "Pipeline"},
    "ps.col_dataset": {"id": "Dataset",
                      "en": "Dataset"},
    "ps.col_file": {"id": "Berkas",
                   "en": "File"},
    "ps.col_owner": {"id": "Pemilik",
                    "en": "Owner"},
    "ps.col_status": {"id": "Status",
                     "en": "Status"},
    "ps.col_dataset_hash": {"id": "Hash dataset",
                           "en": "Dataset hash"},
    "ps.col_pipeline_version": {"id": "Versi pipeline",
                               "en": "Pipeline version"},
    "ps.col_mode_header": {"id": "Mode",
                          "en": "Mode"},
    "ps.group_identity": {"id": "Identitas",
                         "en": "Identity"},
    "ps.group_param": {"id": "Parameter",
                      "en": "Parameters"},
    "ps.group_metric": {"id": "Metrik",
                       "en": "Metrics"},
    "ps.semantics_hikari": {"id": "rata-rata berbobot seluruh kelas (weighted average)",
                           "en": "weighted average across all classes"},
    "ps.semantics_eve": {"id": "kelas serangan pada natural-holdout",
                        "en": "attack class on the natural holdout"},
    "ps.semantics_note": {"id": "Semantik metrik — {parts}.",
                         "en": "Metric semantics — {parts}."},
    "ps.cross_family_warning": {"id": "Eksperimen yang dipilih berasal dari keluarga pipeline berbeda. Precision/recall/F1 keduanya TIDAK sebanding langsung: {parts}.",
                               "en": "The selected experiments come from different pipeline families. Their precision/recall/F1 are NOT directly comparable: {parts}."},
    "ps.dataset_mismatch_warning": {"id": "Eksperimen yang dipilih dijalankan pada dataset dengan hash berbeda — angkanya berasal dari data yang tidak sama.",
                                   "en": "The selected experiments ran on datasets with different hashes — their numbers come from data that is not the same."},
    "ps.param_provenance": {"id": "Parameter bertanda ✓ direkam saat eksperimen itu berjalan; sisanya dibaca dari definisi pipeline (get_info → fixed_params) pada kode saat ini, karena eksperimen lama belum mencatat parameternya.",
                           "en": "Parameters marked ✓ were recorded while that experiment ran; the rest are read from the pipeline definition (get_info → fixed_params) in the current code, because older experiments did not record theirs yet."},
    "ps.mode_column_note": {"id": "Kolom Mode: 🔒 Resmi = parameter terkunci, dasar perbandingan & replikasi; 🧪 Eksplorasi = parameter disesuaikan, di luar perbandingan resmi.",
                           "en": "The Mode column: 🔒 Official = parameters locked, the basis for comparison & replication; 🧪 Exploration = parameters adjusted, outside the official comparison."},
    "ps.best_mark_note": {"id": "Nilai tertinggi disorot per kolom DI DALAM keluarga pipeline masing-masing — bukan peringkat lintas keluarga.",
                         "en": "The highest value is highlighted per column WITHIN each pipeline family — it is not a ranking across families."},
    "ps.mode_filter_default_note": {"id": "Bawaan menampilkan SEMUA mode — run eksplorasi tidak disembunyikan, hanya ditandai.",
                                   "en": "The default shows ALL modes — exploration runs are not hidden, only marked."},
    "ps.result_summary": {"id": "{shown} dari {total} eksperimen",
                         "en": "{shown} of {total} experiments"},
    "ps.expr_help": {"id": "Contoh: `f1 > 0.8`, `accuracy >= 0.9 and auc > 0.85`. Nama yang dikenal: {names}.",
                    "en": "For example: `f1 > 0.8`, `accuracy >= 0.9 and auc > 0.85`. Recognised names: {names}."},
    "ps.expr_unknown_part": {"id": "Bagian `{part}` tidak dikenali. {help}",
                            "en": "The part `{part}` was not recognised. {help}"},
    "ps.expr_not_metric": {"id": "`{name}` bukan nama metrik. {help}",
                          "en": "`{name}` is not a metric name. {help}"},
    "ps.expr_empty": {"id": "Ekspresi kosong. {help}",
                     "en": "The expression is empty. {help}"},
    "ps.only_diff_label": {"id": "Hanya tampilkan yang berbeda",
                          "en": "Show only what differs"},
    "ps.all_same_note": {"id": "Seluruh baris bernilai sama pada eksperimen yang dipilih — tidak ada perbedaan untuk ditampilkan.",
                        "en": "Every row holds the same value across the selected experiments — there is no difference to show."},
    "ps.compare_need_two": {"id": "Pilih minimal dua eksperimen untuk dibandingkan.",
                           "en": "Select at least two experiments to compare."},
    "ps.compare_too_many": {"id": "Maksimal {max} eksperimen dapat dibandingkan sekaligus (dipilih {selected}).",
                           "en": "At most {max} experiments can be compared at once ({selected} selected)."},


    # ── Peringatan campuran mode eksekusi ───────────────────────────────────────
    "ps.mixed_mode_warning": {"id": "Pilihan ini mencampur run resmi (parameter terkunci) dengan run eksplorasi (parameter disesuaikan). Keduanya TIDAK sebanding: perbedaan angka bisa berasal dari perbedaan parameter, bukan dari pipeline-nya.",
                             "en": "This selection mixes official runs (locked parameters) with exploration runs (adjusted parameters). The two are NOT comparable: a difference in the numbers may come from the parameters rather than from the pipeline itself."},


    # ── Progress & Status: halaman & dialog ───────────────────────────────────────
    "ps.cmp_col_experiment": {"id": "Eksperimen",
                             "en": "Experiment"},
    "ps.cmp_row_pipeline": {"id": "Pipeline",
                           "en": "Pipeline"},
    "ps.cmp_row_mode": {"id": "Mode",
                       "en": "Mode"},
    "ps.cmp_reading": {"id": "{diff} dari {total} baris berbeda; baris yang disorot itulah yang berbeda. Tidak ada peringkat otomatis — penilaian mana yang lebih baik tetap milik pembaca.",
                      "en": "{diff} of {total} rows differ; the highlighted rows are the ones that differ. There is no automatic ranking — judging which is better remains the reader's."},
    "ps.btn_open_short": {"id": "Buka",
                         "en": "Open"},
    "ps.btn_drop_short": {"id": "Buang",
                         "en": "Remove"},
    "ps.help_open_detail": {"id": "Buka detail lengkap {id}.",
                           "en": "Open the full details for {id}."},
    "ps.help_drop_too_few": {"id": "Perbandingan memerlukan minimal dua eksperimen — membuang satu lagi akan menutupnya.",
                            "en": "A comparison needs at least two experiments — removing one more will close it."},
    "ps.help_drop": {"id": "Keluarkan {id} dari tabel.",
                    "en": "Remove {id} from the table."},
    "ps.btn_compare_selected": {"id": "Bandingkan terpilih ({count})",
                               "en": "Compare selected ({count})"},
    "ps.table_hint": {"id": "Pilih {min} eksperimen untuk membandingkannya, atau satu baris untuk membuka detail & aksinya.",
                     "en": "Select {min} experiments to compare them, or a single row to open its details & actions."},
    "ps.dlg_detail_title": {"id": "Detail Eksperimen",
                           "en": "Experiment Details"},
    "ps.detail_selected": {"id": "**Terpilih:** `{id}`",
                          "en": "**Selected:** `{id}`"},
    "ps.msg_cancel_failed": {"id": "Gagal membatalkan.",
                            "en": "Cancelling failed."},
    "ps.msg_failed_short": {"id": "Gagal.",
                           "en": "Failed."},
    "ps.msg_failed_with": {"id": "Gagal: {error}",
                          "en": "Failed: {error}"},
    "ps.params_recorded": {"id": "Parameter yang dipakai (direkam saat run):",
                          "en": "The parameters used (recorded at run time):"},
    "ps.uploaded_pipeline_version": {"id": "Pipeline terunggah · versi {version} · hash `{hash}…`",
                                    "en": "Uploaded pipeline · version {version} · hash `{hash}…`"},
    "ps.artifact_read_failed": {"id": "Tidak dapat membaca berkas: {error}",
                               "en": "The file could not be read: {error}"},
    "ps.artifact_last_lines": {"id": "{count} baris terakhir.",
                              "en": "Last {count} lines."},
    "ps.artifact_first_lines": {"id": "{count} baris pertama.",
                               "en": "First {count} lines."},
    "ps.artifact_download_failed": {"id": "Gagal menyiapkan unduhan: {error}",
                                   "en": "Preparing the download failed: {error}"},


    # ── Progress & Status: dialog detail ───────────────────────────────────────
    "ps.btn_cancel_short": {"id": "Batalkan",
                           "en": "Cancel"},
    "ps.detail_identity": {"id": "ID `{id}` · Created {created} · Completed {completed}",
                          "en": "ID `{id}` · Created {created} · Completed {completed}"},
    "ps.detail_traceability": {"id": "Pipeline terunggah · versi {version} · SHA-256 `{pipeline_hash}…` · dataset SHA-256 `{dataset_hash}…`",
                              "en": "Uploaded pipeline · version {version} · SHA-256 `{pipeline_hash}…` · dataset SHA-256 `{dataset_hash}…`"},
    "ps.msg_rerun_started": {"id": "Baru: `{id}…` — tutup dan segarkan.",
                            "en": "New: `{id}…` — close and refresh."},
    "ps.exp_artifact_viewer": {"id": "Artifact Viewer",
                              "en": "Artifact Viewer"},
    "ps.params_legacy_line": {"id": "Parameter (definisi pipeline saat ini — eksperimen ini dijalankan sebelum parameter dicatat per run): {params}",
                             "en": "Parameters (the pipeline's current definition — this experiment ran before parameters were recorded per run): {params}"},
    "ps.params_used_line": {"id": "Parameter yang dipakai (direkam saat run): {params}",
                           "en": "The parameters used (recorded at run time): {params}"},
    "ps.params_differs_line": {"id": "Berbeda dari bawaan: {keys}.",
                              "en": "Differs from the default: {keys}."},
    "ps.msg_pdf_failed_kind": {"id": "PDF tidak dapat dibuat: {kind}",
                              "en": "The PDF could not be created: {kind}"},


    # ── Progress & Status: penyaji hasil ───────────────────────────────────────
    "ps.rv_auc_excellent": {"id": "sangat baik — model memisahkan serangan dari trafik normal dengan jelas",
                           "en": "very good — the model separates attacks from normal traffic clearly"},
    "ps.rv_auc_good": {"id": "baik",
                      "en": "good"},
    "ps.rv_auc_fair": {"id": "cukup",
                      "en": "fair"},
    "ps.rv_auc_weak": {"id": "lemah — hanya sedikit di atas tebakan acak",
                      "en": "weak — only slightly above random guessing"},
    "ps.rv_auc_chance": {"id": "hampir setara tebakan acak (AUC ≈ 0,5)",
                        "en": "close to random guessing (AUC ≈ 0.5)"},
    "ps.rv_of_total": {"id": "{pct} dari total",
                      "en": "{pct} of the total"},
    "ps.rv_predicted": {"id": "Prediksi: {name}",
                       "en": "Predicted: {name}"},
    "ps.rv_actual": {"id": "Aktual: {name}",
                    "en": "Actual: {name}"},
    "ps.rv_cell_tn": {"id": "{name} benar (TN)",
                     "en": "{name} correct (TN)"},
    "ps.rv_cell_fp": {"id": "False alarm (FP)",
                     "en": "False alarm (FP)"},
    "ps.rv_cell_fn": {"id": "{name} LOLOS (FN)",
                     "en": "{name} MISSED (FN)"},
    "ps.rv_cell_tp": {"id": "{name} terdeteksi (TP)",
                     "en": "{name} detected (TP)"},
    "ps.rv_help_caught": {"id": "TP / (TP+FN) — proporsi serangan yang tertangkap. {tp} dari {total} serangan{recall}",
                         "en": "TP / (TP+FN) — the share of attacks caught. {tp} of {total} attacks{recall}"},
    "ps.rv_help_recall_suffix": {"id": " · recall {pct}",
                                "en": " · recall {pct}"},
    "ps.rv_help_missed_pct": {"id": "{pct} serangan lolos",
                             "en": "{pct} of attacks slipped through"},
    "ps.rv_help_missed_unknown": {"id": "Jumlah serangan tidak diketahui.",
                                 "en": "The number of attacks is not known."},
    "ps.rv_help_fp_pct": {"id": "{pct} dari trafik normal",
                         "en": "{pct} of the normal traffic"},
    "ps.rv_help_fp_unknown": {"id": "Proporsi terhadap trafik normal tidak tersedia.",
                             "en": "The share of normal traffic is not available."},
    "ps.rv_explain_tp": {"id": "**{count}** {attack} berhasil dikenali model — deteksi yang benar.",
                        "en": "**{count}** {attack} were recognised by the model — correct detections."},
    "ps.rv_explain_fn": {"id": "**{count}** {attack} TIDAK terdeteksi (dianggap {normal}) — **risiko keamanan paling kritis** pada IDS.",
                        "en": "**{count}** {attack} were NOT detected (treated as {normal}) — the **most critical security risk** for an IDS."},
    "ps.rv_explain_fp": {"id": "**{count}** {normal} salah ditandai sebagai serangan — alarm palsu yang membebani analis (alert fatigue).",
                        "en": "**{count}** {normal} were wrongly flagged as attacks — false alarms that burden the analyst (alert fatigue)."},
    "ps.rv_explain_tn": {"id": "**{count}** {normal} benar dibiarkan lewat — tidak mengganggu operasi.",
                        "en": "**{count}** {normal} were correctly let through — no disruption to operations."},
    "ps.rv_weights_logreg": {"id": "Bobot berasal dari nilai absolut koefisien Logistic Regression (bukan importance berbasis pohon).",
                            "en": "The weights come from the absolute values of the Logistic Regression coefficients (not tree-based importance)."},
    "ps.rv_weights_relative": {"id": "Bobot relatif antar fitur menurut model yang dilatih.",
                              "en": "The relative weight of each feature according to the trained model."},
    "ps.rv_col_feature": {"id": "Fitur",
                         "en": "Feature"},
    "ps.rv_col_weight": {"id": "Bobot",
                        "en": "Weight"},
    "ps.rv_col_metric": {"id": "Metrik",
                        "en": "Metric"},
    "ps.rv_roc_reading": {"id": "{quality}. Semakin kurva menjauhi garis diagonal (acuan acak, TPR = FPR), semakin baik model membedakan serangan dari trafik normal.",
                         "en": "{quality}. The further the curve runs from the diagonal (the random baseline, TPR = FPR), the better the model separates attacks from normal traffic."},
    "ps.rv_tpr_model": {"id": "TPR (model)",
                       "en": "TPR (model)"},
    "ps.rv_roc_point_note": {"id": "Titik pada kurva ROC — bukan nilai threshold; daftar threshold tidak disimpan di metrics.json.",
                            "en": "A point on the ROC curve — not a threshold value; the list of thresholds is not stored in metrics.json."},
    "ps.rv_lc_overfit": {"id": "** (> 0,10) → indikasi **overfitting** (model hafal data latih).",
                        "en": "** (> 0.10) → a sign of **overfitting** (the model memorised the training data)."},
    "ps.rv_lc_underfit": {"id": ") dan berdekatan → indikasi **underfitting**.",
                         "en": ") and close together → a sign of **underfitting**."},
    "ps.rv_lc_good_gap": {"id": ") dan berdekatan (selisih",
                         "en": ") and close together (a gap of"},
    "ps.rv_lc_good_tail": {"id": ") → model **belajar dengan baik**.",
                          "en": ") → the model **learns well**."},
    "ps.rv_no_learning_curve": {"id": "Pipeline EVE-cbr **tidak menghasilkan learning curve**. Sebagai gantinya, platform melaporkan evaluasi **dual-holdout**.",
                               "en": "The EVE-cbr pipeline **produces no learning curve**. The platform reports a **dual-holdout** evaluation instead."},


    # ── Progress & Status: bobot fitur, ROC & learning curve ───────────────────────────────────────
    "ps.rv_chart_random": {"id": "Acuan acak",
                          "en": "Random baseline"},
    "ps.rv_lc_overfitting": {"id": "Selisih train−validation akhir = **{gap}** (> 0,10) → indikasi **overfitting** (model hafal data latih).",
                            "en": "Final train−validation gap = **{gap}** (> 0.10) → a sign of **overfitting** (the model memorised the training data)."},
    "ps.rv_lc_underfitting": {"id": "Train & validation sama-sama rendah (~{score}) dan berdekatan → indikasi **underfitting**.",
                             "en": "Train & validation are both low (~{score}) and close together → a sign of **underfitting**."},
    "ps.rv_lc_learns_well": {"id": "Train & validation sama-sama tinggi (~{score}) dan berdekatan (selisih {gap}) → model **belajar dengan baik**.",
                            "en": "Train & validation are both high (~{score}) and close together (a gap of {gap}) → the model **learns well**."},
    "ps.rv_lc_plain": {"id": "Selisih train−validation akhir = {gap}; skor validasi akhir ~{score}.",
                      "en": "Final train−validation gap = {gap}; final validation score ~{score}."},
    "ps.rv_dual_holdout_note": {"id": "Pipeline EVE-cbr **tidak menghasilkan learning curve**. Sebagai gantinya, platform melaporkan evaluasi **dual-holdout**: *natural-holdout* (distribusi kelas asli — inilah metrik yang dilaporkan) dan *balanced-holdout* (kelas diseimbangkan, sebagai pembanding separabilitas). Metrik yang dilaporkan platform = **natural-holdout** karena mencerminkan distribusi kelas asli (apa adanya).",
                               "en": "The EVE-cbr pipeline **produces no learning curve**. The platform reports a **dual-holdout** evaluation instead: *natural holdout* (the original class distribution — these are the metrics reported) and *balanced holdout* (classes balanced, as a separability comparison). The metrics the platform reports = **natural holdout**, because it reflects the original class distribution as it is."},


    # ── Progress & Status: penjelajah artefak ───────────────────────────────────────
    "ps.art_file_meta": {"id": "`{path}` · {size} · {lines} baris",
                        "en": "`{path}` · {size} · {lines} lines"},
    "ps.art_large_tail": {"id": "Output besar — menampilkan {count} baris terakhir.",
                         "en": "Large output — showing the last {count} lines."},
    "ps.art_large_head": {"id": "Output besar — menampilkan {count} baris pertama.",
                         "en": "Large output — showing the first {count} lines."},
    "ps.art_prepare_download": {"id": "Siapkan unduhan {name}",
                               "en": "Prepare {name} for download"},


    # ── Progress & Status: sisa halaman ───────────────────────────────────────
    "ps.msg_rerun_refresh": {"id": "Baru: `{id}…` — segarkan tabel.",
                            "en": "New: `{id}…` — refresh the table."},
    "ps.detail_selected_line": {"id": "**Terpilih:** `{id}` — {pipeline} · `{status}` · {badge}",
                               "en": "**Selected:** `{id}` — {pipeline} · `{status}` · {badge}"},
    "ps.help_csv_summary": {"id": "{summary}. Mengikuti kolom & filter yang sedang aktif, lengkap dengan keterangan semantik metrik per baris.",
                           "en": "{summary}. It follows the active columns and filters, including the per-row metric-semantics note."},
    "ps.help_compare_hint": {"id": "Centang 2-{max} eksperimen untuk membandingkannya, atau satu baris untuk membuka detail & aksinya.",
                            "en": "Tick 2-{max} experiments to compare them, or a single row to open its details & actions."},


    # ── Uji coba pipeline sebelum persetujuan ───────────────────────────────────────
    "trial.heading": {"id": "Uji coba di platform",
                     "en": "Trial run on the platform"},
    "trial.intro": {"id": "Jalankan pipeline ini pada dataset yang tersedia sebelum menyetujuinya. Uji coba dibatasi {rows} baris dan {seconds} detik.",
                   "en": "Run this pipeline on an available dataset before approving it. A trial is limited to {rows} rows and {seconds} seconds."},
    "trial.lbl_dataset": {"id": "Dataset uji",
                         "en": "Trial dataset"},
    "trial.ph_dataset": {"id": "Pilih dataset…",
                        "en": "Choose a dataset…"},
    "trial.btn_run": {"id": "Jalankan uji coba",
                     "en": "Run trial"},
    "trial.running": {"id": "Menjalankan uji coba…",
                     "en": "Running the trial…"},
    "trial.only_pipeline": {"id": "Hanya pengajuan pipeline yang dapat diuji.",
                           "en": "Only pipeline submissions can be tested."},
    "trial.not_pending": {"id": "Pengajuan ini sudah diputuskan, jadi tidak dapat diuji lagi.",
                         "en": "This submission has already been decided, so it cannot be tested."},
    "trial.static_failed": {"id": "Paket ini belum lolos pemeriksaan statis. Perbaiki temuan yang menggagalkan lebih dulu — kode yang gagal pemeriksaan tidak dijalankan.",
                           "en": "This package has not passed the static check. Fix the failing findings first — code that fails the check is never executed."},
    "trial.gate_untested": {"id": "Belum diuji. Jalankan uji coba lebih dulu sebelum menyetujui.",
                           "en": "Not tested yet. Run a trial before approving."},
    "trial.gate_failed": {"id": "Uji coba terakhir gagal. Perbaiki pipeline lalu uji ulang.",
                         "en": "The last trial failed. Fix the pipeline, then test again."},
    "trial.gate_stale": {"id": "Kode berubah setelah uji coba berhasil, jadi hasil ujinya tidak berlaku lagi. Uji ulang sebelum menyetujui.",
                        "en": "The code changed after the trial passed, so that result no longer applies. Test again before approving."},
    "trial.result_passed": {"id": "Uji coba BERHASIL · {rows} baris · {seconds} detik",
                           "en": "Trial PASSED · {rows} rows · {seconds} seconds"},
    "trial.result_failed": {"id": "Uji coba GAGAL pada tahap **{stage}**",
                           "en": "Trial FAILED at the **{stage}** stage"},
    "trial.failure_detail": {"id": "**{kind}** — {message}",
                            "en": "**{kind}** — {message}"},
    "trial.tested_by": {"id": "Diuji {who} pada {when} · dataset {dataset}",
                       "en": "Tested by {who} on {when} · dataset {dataset}"},
    "trial.no_metrics": {"id": "Pipeline selesai tetapi tidak mengembalikan metrik yang dapat dibaca.",
                        "en": "The pipeline finished but returned no readable metrics."},
    "trial.compat_heading": {"id": "Kecocokan dataset",
                            "en": "Dataset compatibility"},
    "trial.compat_unavailable": {"id": "Ringkasan kecocokan tidak tersedia untuk dataset ini.",
                                "en": "No compatibility summary is available for this dataset."},
    "trial.err_no_entry": {"id": "Pengajuan ini tidak mencatat titik masuk & nama kelasnya, sehingga tidak ada yang dapat dimuat untuk diuji.",
                          "en": "This submission records no entry point or class name, so there is nothing to load for a trial."},
    "trial.err_entry_missing": {"id": "Berkas titik masuk tidak ditemukan: {path}",
                               "en": "The entry-point file was not found: {path}"},
    "trial.err_not_found": {"id": "Pengajuan #{id} tidak ditemukan.",
                           "en": "Submission #{id} was not found."},


    # ── Dataset uji lampiran (Tahap 2) ───────────────────────────────────────
    "td.heading": {"id": "Dataset uji (opsional)",
                  "en": "Trial dataset (optional)"},
    "td.intro": {"id": "Lampirkan berkas contoh bila pipeline Anda memerlukan struktur data yang belum ada di platform. Berkas ini HANYA dipakai peninjau untuk menguji pipeline, tidak menjadi dataset platform, dan dihapus setelah keputusan diambil.",
                "en": "Attach a sample file if your pipeline needs a data structure the platform does not have yet. It is used ONLY by the reviewer to test the pipeline, never becomes a platform dataset, and is deleted once a decision is made."},
    "td.limit_note": {"id": "Batas ukuran {limit}. Format: {formats}.",
                     "en": "Size limit {limit}. Formats: {formats}."},
    "td.lbl_file": {"id": "Berkas dataset uji",
                   "en": "Trial dataset file"},
    "td.lbl_note": {"id": "Keterangan dataset (opsional)",
                   "en": "About this dataset (optional)"},
    "td.ph_note": {"id": "mis. asal data atau apa yang diwakilinya",
                  "en": "e.g. where it came from, or what it represents"},
    "td.err_too_large": {"id": "Dataset uji {size} melampaui batas {limit}.",
                        "en": "The trial dataset is {size}, over the {limit} limit."},
    "td.err_no_attachment": {"id": "Pengajuan ini tidak melampirkan dataset uji.",
                            "en": "This submission has no attached trial dataset."},
    "td.err_file_missing": {"id": "Berkas dataset lampiran tidak ditemukan: {filename}",
                           "en": "The attached dataset file was not found: {filename}"},
    "td.err_hash_mismatch": {"id": "Hash dataset lampiran tidak cocok untuk {filename}: tercatat {recorded}…, ditemukan {found}…. Berkas berubah setelah diajukan — pemakaian ditolak.",
                            "en": "The attached dataset's hash does not match for {filename}: recorded {recorded}…, found {found}…. The file changed after it was submitted — it will not be used."},
    "td.err_no_dataset_chosen": {"id": "Pilih dataset lebih dulu sebelum menjalankan uji coba.",
                                "en": "Choose a dataset before running the trial."},
    "td.attached_ok": {"id": "Terlampir: {filename} · {size}",
                      "en": "Attached: {filename} · {size}"},
    "td.structure_heading": {"id": "Hasil pemeriksaan struktur",
                            "en": "Structure check result"},
    "td.structure_none": {"id": "Struktur berkas ini tidak cocok dengan skema mana pun yang dikenal platform. Peninjau tetap dapat mencobanya — pipeline Anda mungkin memang membaca strukturnya sendiri.",
                         "en": "This file's structure does not match any schema the platform knows. A reviewer can still try it — your pipeline may well read its own structure."},
    "td.compatible_with": {"id": "Cocok dengan {types}",
                          "en": "Matches {types}"},
    "td.lbl_source": {"id": "Sumber dataset",
                     "en": "Dataset source"},
    "td.source_platform": {"id": "Dataset platform",
                          "en": "Platform dataset"},
    "td.source_attached": {"id": "Dataset lampiran pengajuan",
                          "en": "Dataset attached to the submission"},
    "td.attachment_facts": {"id": "**{filename}** · {size} · diunggah {when}",
                           "en": "**{filename}** · {size} · uploaded {when}"},
    "td.contributor_note": {"id": "Keterangan kontributor: {note}",
                           "en": "Contributor's note: {note}"},
    "td.no_attachment_hint": {"id": "Pengajuan ini tidak melampirkan dataset uji, jadi hanya dataset platform yang dapat dipakai.",
                             "en": "This submission has no attached trial dataset, so only a platform dataset can be used."},
    "td.sample_caveat": {"id": "Dataset lampiran adalah CONTOH untuk pengujian, bukan dataset penelitian — hasil ujinya tidak menjadi hasil resmi. Uji ini menilai apakah pipeline BERJALAN, bukan seberapa baik hasilnya, jadi angka yang berbeda jauh dari data sesungguhnya adalah hal yang wajar.",
                        "en": "An attached dataset is a SAMPLE for testing, not research data — its results never become official results. This trial judges whether the pipeline RUNS, not how well it scores, so numbers far from those on real data are entirely expected."},


    # ── Tahap & pesan kegagalan uji coba ───────────────────────────────────────
    "trial.stage_load": {"id": "memuat pipeline",
                        "en": "loading the pipeline"},
    "trial.stage_read": {"id": "membaca dataset",
                        "en": "reading the dataset"},
    "trial.stage_run": {"id": "menjalankan pipeline",
                       "en": "running the pipeline"},
    "trial.stage_timeout": {"id": "batas waktu",
                           "en": "the time limit"},
    "trial.stage_setup": {"id": "menyiapkan pelaksana",
                         "en": "preparing the runner"},
    "trial.msg_timeout": {"id": "Uji coba melampaui batas {seconds} detik dan dihentikan. Pipeline masih berjalan saat batas tercapai — periksa tahap yang paling lama.",
                         "en": "The trial ran past its {seconds}-second limit and was stopped. The pipeline was still running when the limit was reached — look at whichever stage takes longest."},
    "trial.msg_process_died": {"id": "Proses uji berakhir tanpa hasil. Kemungkinan dihentikan sistem karena kehabisan memori.",
                              "en": "The trial process ended without a result. It was most likely stopped by the system for running out of memory."},


    # ── Sisa teks antarmuka peninjauan & katalog ───────────────────────────────────────
    "ap.review_history_heading": {"id": "**Riwayat tinjauan**",
                                 "en": "**Review history**"},
    "ap.review_history_empty": {"id": " — belum ada pengajuan yang ditinjau.",
                               "en": " — no submissions have been reviewed yet."},
    # Kolom & ringkasan tabel berkas paket. Jumlah pemeriksaan tetap DISEBUT:
    # menyembunyikan perinciannya tanpa menyebut berapa yang berjalan akan
    # terbaca seperti tidak diperiksa sama sekali.
    "sr.col_file": {"id": "Berkas", "en": "File"},
    "sr.col_role": {"id": "Peran", "en": "Role"},
    "sr.col_size": {"id": "Ukuran", "en": "Size"},
    "sr.checks_clean": {"id": "{total} pemeriksaan · semua lolos",
                        "en": "{total} checks · all passed"},
    "sr.checks_warned": {"id": "{total} pemeriksaan · {count} peringatan",
                         "en": "{total} checks · {count} warning(s)"},
    "sr.checks_failed": {"id": "{total} pemeriksaan · {count} gagal",
                         "en": "{total} checks · {count} failed"},
    "sr.checks_tally": {"id": "{total} pemeriksaan · {passed} lolos",
                        "en": "{total} checks · {passed} passed"},
    "sr.summary_line": {"id": "**{name}** · {verdict} · {files} berkas · oleh {who} · {when}",
                       "en": "**{name}** · {verdict} · {files} files · by {who} · {when}"},
    "pc.pre_stage_parse": {"id": "Parsing & validasi dataset",
                          "en": "Parsing & validating the dataset"},
    "pc.pre_stage_note": {"id": "Tahap bergaris putus dijalankan platform sebelum pipeline dipanggil, bukan bagian dari pipeline-nya.",
                         "en": "The dashed stages are run by the platform before the pipeline is called; they are not part of the pipeline itself."},


    # ── Pengajuan saya: keadaan kosong ───────────────────────────────────────
    # Alasan penolakan, dipindah dari kolom terakhir tabel "Pengajuan
    # saya" yang sudah dibuang. Nomornya ikut disebut supaya kontributor
    # tahu pengajuan yang mana bila ia mengirim lebih dari satu.
    # Dua zona halaman peninjauan. Keduanya dibaca dengan sikap berbeda:
    # yang satu tidak mengubah apa pun, yang lain setiap kendalinya
    # mengubah keadaan.
    "ap.zone_examined": {"id": "Yang diperiksa", "en": "What was checked"},
    "ap.zone_testing": {"id": "Pengujian", "en": "Testing"},
    "ap.zone_decision": {"id": "Keputusan", "en": "Decision"},
    "ap.rejection_note": {"id": "Pengajuan #{id} ditolak — **{note}**",
                          "en": "Submission #{id} was rejected — **{note}**"},


    # ── Katalog: pipeline kontribusi & keadaannya ───────────────────────────────────────
    # ── Katalog: cari & saring bertingkat ───────────────────────────────────
    # Kategori dipilih dulu, nilainya menyusul. Sebuah kategori hanya muncul
    # bila nilainya lebih dari satu — penyaring dengan satu pilihan tidak
    # menyaring apa pun.
    "re.cat_search": {"id": "Cari research pipeline",
                      "en": "Search research pipelines"},
    "re.cat_search_ph": {"id": "nama, algoritma, institusi, tahun…",
                         "en": "name, algorithm, institution, year…"},
    "re.cat_filter_by": {"id": "Saring menurut", "en": "Filter by"},
    "re.cat_filter_none": {"id": "tanpa penyaring", "en": "no filter"},
    "re.cat_by_origin": {"id": "Asal", "en": "Origin"},
    "re.cat_by_dataset": {"id": "Jenis dataset", "en": "Dataset type"},
    "re.cat_by_format": {"id": "Format berkas", "en": "File format"},
    "re.cat_by_algorithm": {"id": "Algoritma", "en": "Algorithm"},
    "re.cat_by_institution": {"id": "Institusi", "en": "Institution"},
    "re.cat_by_year": {"id": "Tahun", "en": "Year"},
    "re.cat_origin_builtin": {"id": "bawaan", "en": "built-in"},
    "re.cat_origin_uploaded": {"id": "kontribusi", "en": "contributed"},
    "re.cat_value_unspecified": {"id": "tidak disebutkan", "en": "not stated"},
    "re.cat_active_filters": {"id": "Aktif: {filters}", "en": "Active: {filters}"},
    "re.cat_clear_filters": {"id": "Bersihkan", "en": "Clear"},
    "re.cat_shown": {"id": "Menampilkan {shown} dari {total} research pipeline.",
                     "en": "Showing {shown} of {total} research pipelines."},
    "re.cat_empty_filtered": {"id": "Tidak ada yang cocok dengan penyaring yang sedang aktif. Bersihkan salah satunya untuk melihat lebih banyak.",
                              "en": "Nothing matches the filters currently active. Clear one of them to see more."},
    "re.cat_contributed_group": {"id": "Pipeline kontribusi · {dataset}",
                                "en": "Contributed pipeline · {dataset}"},
    "re.cat_badge_contributed": {"id": "kontribusi v{version}",
                                "en": "contributed v{version}"},
    "re.cat_state_broken": {"id": "bermasalah",
                           "en": "unusable"},
    "re.cat_state_no_dataset": {"id": "belum ada dataset",
                               "en": "no dataset yet"},
    "re.cat_no_dataset_reason": {"id": "Belum ada dataset platform berjenis ini, jadi pipeline ini belum dapat dijalankan. Unggah dataset yang sesuai lewat halaman Tambah Pipeline & Dataset.",
                                "en": "No platform dataset of this type exists yet, so this pipeline cannot be run. Upload a matching dataset from the Add Pipeline & Dataset page."},
    # Research pipeline KONTRIBUSI memakai dataset yang terikat pada paketnya,
    # bukan isi `storage/datasets/`. Menyuruhnya mengunggah ke sana adalah
    # instruksi yang tidak mungkin berhasil.
    "re.cat_no_dataset_reason_uploaded": {"id": "Dataset milik paket ini tidak ditemukan, jadi pipeline ini belum dapat dijalankan. Ia memakai dataset yang dilampirkan pengunggahnya — bukan isi storage/datasets — jadi yang memulihkannya adalah pengajuan ulang berisi dataset itu.",
                                          "en": "This package's own dataset is missing, so the pipeline cannot be run. It uses the dataset its uploader attached — not the contents of storage/datasets — so restoring it means a new submission carrying that dataset."},
    "re.cat_broken_heading": {"id": "Tidak dapat dimuat",
                             "en": "Cannot be loaded"},


    # ── Jenis dataset uji coba: penentuan & penolakan ───────────────────────────────────────
    "td.err_unknown_dataset_type": {"id": "Jenis dataset belum diketahui, jadi uji coba tidak dapat dijalankan. Lengkapi dataset target pada metadata pengajuan, atau pilih dataset platform yang jenisnya dikenali.",
                                   "en": "The dataset type is not known yet, so the trial cannot run. Fill in the target dataset in the submission metadata, or choose a platform dataset whose type is recognised."},
    "td.err_trial_failed": {"id": "Uji coba tidak dapat dijalankan karena kesalahan tak terduga ({kind}). Rinciannya tercatat pada log untuk pengembang.",
                           "en": "The trial could not be run because of an unexpected error ({kind}). The details are recorded in the developer log."},
    # Research pipeline yang berdiri sendiri terikat ke datasetnya sendiri
    # setelah disetujui. Meluluskannya atas dataset platform membuat
    # "sudah diuji" berbicara tentang data yang tidak akan pernah ia pakai.
    "td.err_standalone_needs_own_dataset": {"id": "Research pipeline ini berdiri sendiri, jadi ia hanya dapat diuji dengan dataset yang dilampirkan pengunggahnya — bukan dataset platform.",
                                            "en": "This research pipeline stands alone, so it can only be trialled with the dataset its uploader attached — not a platform dataset."},
    "td.missing_dataset_type": {"id": "Dataset target belum diisi pada pengajuan ini.",
                               "en": "The target dataset has not been set on this submission."},
    "ap.lbl_other_dataset": {"id": "Lainnya / belum terdaftar",
                            "en": "Other / not registered yet"},

    # Deklarasi kontrak dataset untuk research pipeline kontribusi yang berdiri
    # sendiri. Platform tidak pernah menebak skema dari isi berkas — kontraknya
    # dinyatakan kontributor, lalu dipakai memeriksa datasetnya.
    # Tinjau ulang: persetujuan bukan lagi keadaan akhir. Pipeline yang
    # dinonaktifkan dapat dikembalikan ke antrean untuk ditinjau penuh.
    "ap.btn_reopen": {"id": "Tinjau ulang",
                     "en": "Review again"},
    "ap.help_reopen": {"id": "Kembalikan pengajuan ini ke antrean tinjauan — seluruh langkah peninjauan beserta keputusannya dapat diulang. Versi yang sudah terdaftar tidak disentuh; menyetujuinya lagi membuat versi baru.",
                      "en": "Send this submission back to the review queue — every review step and its decision can be run again. The registered version is left untouched; approving again creates a new version."},
    "ap.reopen_not_approved": {"id": "Hanya pengajuan yang sudah disetujui yang dapat ditinjau ulang.",
                              "en": "Only an approved submission can be reviewed again."},
    "ap.reopen_only_pipeline": {"id": "Hanya pengajuan pipeline yang melewati peninjauan.",
                               "en": "Only pipeline submissions go through review."},
    "ap.reopen_still_active": {"id": "Nonaktifkan pipelinenya dulu. Menariknya kembali ke antrean selagi masih dapat dijalankan membuat keadaan yang membingungkan: terdaftar sekaligus menunggu tinjauan.",
                              "en": "Deactivate the pipeline first. Pulling it back into the queue while it can still be run creates a confusing state: registered and awaiting review at the same time."},
    "ap.msg_reopened": {"id": "Pengajuan #{number} kembali ke antrean tinjauan. Versi yang terdaftar tidak berubah.",
                       "en": "Submission #{number} is back in the review queue. The registered version is unchanged."},

    # Identitas research yang AKAN dibuat saat pengajuan berdiri sendiri
    # disetujui — menggantikan pertanyaan "ini ikut research pipeline mana".
    # Penolakan saat identitas research tidak dapat dibentuk. Diperiksa
    # SEBELUM satu berkas pun bergerak, jadi pesannya menyebut apa yang harus
    # diperbaiki, bukan sekadar bahwa persetujuan gagal.
    "err.no_research_name": {"id": "Research pipeline ini belum punya nama, jadi pengenalnya tidak dapat dibentuk. Isi nama pipeline pada pengajuan.",
                            "en": "This research pipeline has no name yet, so its identifier cannot be formed. Fill in the pipeline name on the submission."},
    "err.bad_research_name": {"id": "Nama research pipeline tidak menghasilkan pengenal yang sah: {name}. Pakai huruf, angka, atau tanda hubung.",
                             "en": "The research pipeline name does not produce a valid identifier: {name}. Use letters, digits, or hyphens."},

    # Halaman satu pipeline terdaftar.
    # Menghapus — selalu menyebut apa yang ikut hilang sebelum dikonfirmasi.
    # Kolom riwayat peninjauan.
    "sr.col_decision": {"id": "Keputusan", "en": "Decision"},
    # Kuncinya di namespace `trial.` — bukan `sr.` — karena isinya memang
    # konsep uji coba, dan itulah yang dikecualikan glosarium. Bukan
    # melebarkan pengecualian, melainkan memakainya sesuai maksudnya.
    "trial.col_outcome": {"id": "Uji coba", "en": "Trial"},
    "sr.col_reviewed_at": {"id": "Ditinjau", "en": "Reviewed"},
    "sr.col_reviewed_by": {"id": "Oleh", "en": "By"},
    "sr.col_note": {"id": "Catatan", "en": "Note"},

    "mp.btn_delete_version": {"id": "Hapus versi",
                             "en": "Delete version"},
    "mp.delete_blocked_used": {"id": "Versi ini dipakai eksperimen yang sudah tercatat. Menghapusnya membuat eksperimen itu menunjuk kode yang tidak ada lagi. Nonaktifkan saja — ia hilang dari pilihan, catatannya tetap utuh.",
                              "en": "This version is used by recorded experiments. Deleting it would leave those experiments pointing at code that no longer exists. Deactivate it instead — it disappears from the choices while its record stays intact."},
    # ── Kelola research pipeline dari halaman Jalankan Eksperimen ────────
    # Dua tingkat yang sengaja dibedakan: SATU algoritma, atau research
    # pipeline UTUH. Keduanya menghasilkan akibat yang berbeda dan karena itu
    # tidak pernah disatukan menjadi satu tombol.
    "mp.blocked_last_algorithm": {"id": "Ini satu-satunya algoritma yang masih aktif. Menonaktifkannya membuat research pipeline ini lenyap dari pilihan tanpa pernah dinyatakan dimatikan — pakai \"Nonaktifkan research pipeline\" bila memang itu yang dimaksud.",
                                  "en": "This is the only algorithm still active. Deactivating it would make this research pipeline vanish from the choices without ever being declared off — use \"Deactivate research pipeline\" if that is what you mean."},
    "re.sec_manage": {"id": "Kelola research pipeline ini",
                      "en": "Manage this research pipeline"},
    "re.help_manage": {"id": "Hanya Research Admin. Menonaktifkan tidak menghapus apa pun: eksperimen yang sudah tercatat tetap utuh lengkap dengan versi dan hash-nya.",
                       "en": "Research Admin only. Deactivating deletes nothing: recorded experiments stay intact, complete with their version and hash."},
    "re.lbl_algorithm_state": {"id": "Algoritma ({live} dari {total} aktif)",
                               "en": "Algorithms ({live} of {total} active)"},
    "re.btn_research_off": {"id": "Nonaktifkan research pipeline",
                            "en": "Deactivate research pipeline"},
    "re.btn_research_on": {"id": "Aktifkan research pipeline",
                           "en": "Activate research pipeline"},
    "re.btn_algorithm_off": {"id": "Nonaktifkan", "en": "Deactivate"},
    "re.btn_algorithm_on": {"id": "Aktifkan", "en": "Activate"},
    "re.btn_edit_code": {"id": "Sunting kode", "en": "Edit code"},
    "re.btn_delete_algorithm": {"id": "Hapus", "en": "Delete"},
    "re.msg_builtin_readonly": {"id": "Research pipeline bawaan menjadi pembanding tetap penelitian ini: kodenya tidak disunting dan ketersediaannya tidak diubah dari halaman ini.",
                                "en": "Built-in research pipelines are this study's fixed baseline: their code is not edited and their availability is not changed from this page."},
    "re.msg_research_off": {"id": "{research} dinonaktifkan — {count} algoritma hilang dari pilihan eksperimen baru.",
                            "en": "{research} deactivated — {count} algorithms removed from the new-experiment choices."},
    "re.msg_research_on": {"id": "{research} diaktifkan — {count} algoritma dapat dipilih lagi.",
                           "en": "{research} activated — {count} algorithms can be chosen again."},
    "re.msg_algorithm_off": {"id": "{algorithm} dinonaktifkan.",
                             "en": "{algorithm} deactivated."},
    "re.msg_algorithm_on": {"id": "{algorithm} diaktifkan.",
                            "en": "{algorithm} activated."},
    "re.msg_edit_elsewhere": {"id": "Penyunting kode ada di halaman Add Pipeline & Dataset, bagian Aktif — di situ pula riwayat versinya terbaca.",
                              "en": "The code editor lives on the Add Pipeline & Dataset page, Active section — that is also where its version history is read."},
    "mp.delete_blocked_running": {"id": "Ada eksperimen yang sedang berjalan memakai versi ini. Tunggu sampai selesai.",
                                 "en": "An experiment is currently running on this version. Wait until it finishes."},
    "mp.delete_confirm": {"id": "Hapus **{name} v{version}**? Baris registry dan berkas versi ini dibuang permanen. Versi lain tidak tersentuh.",
                         "en": "Delete **{name} v{version}**? This version's registry row and file are removed permanently. Other versions are untouched."},
    "mp.msg_version_deleted": {"id": "{name} v{version} dihapus.",
                              "en": "{name} v{version} has been deleted."},
    "ap.btn_delete_submission": {"id": "Hapus pengajuan",
                                "en": "Delete submission"},
    "ap.delete_confirm": {"id": "Hapus pengajuan #{number}? Yang ikut hilang: {files} berkas paket, {uji} hasil uji{extra}. Tindakan ini tidak dapat dibatalkan.",
                         "en": "Delete submission #{number}? This also removes: {files} package files, {uji} pre-approval test runs{extra}. This cannot be undone."},
    "ap.delete_keeps_dataset": {"id": ", dan dataset yang sudah terikat ke research pipeline TIDAK ikut terhapus",
                               "en": ", and the dataset already bound to a research pipeline is NOT removed"},
    "ap.delete_warns_registered": {"id": "Pengajuan ini sudah menjadi {count} pipeline terdaftar. Pipeline-nya tetap berjalan, tetapi halaman peninjauannya akan kehilangan kartunya.",
                                  "en": "This submission has become {count} registered pipeline(s). They keep working, but their review page will lose its card."},
    "ap.msg_submission_deleted": {"id": "Pengajuan #{number} dihapus.",
                                 "en": "Submission #{number} has been deleted."},
    "mp.submission_deleted": {"id": "Pengajuan asal versi ini sudah dihapus, jadi tidak ada kartu peninjauan yang dapat dibuka. Pipeline-nya sendiri tetap berjalan.",
                             "en": "The submission behind this version has been deleted, so there is no review card to open. The pipeline itself keeps working."},

    "ap.btn_back_to_pipelines": {"id": "‹ Kembali ke daftar pipeline",
                                "en": "‹ Back to the pipeline list"},
    "mp.no_submission_behind": {"id": "Versi ini lahir dari penyuntingan, bukan dari pengajuan — jadi tidak ada kartu peninjauan yang dapat dibuka untuknya.",
                               "en": "This version came from an edit, not from a submission — so there is no review card to open for it."},
    "mp.submission_unreadable": {"id": "Pengajuan asal versi ini tidak dapat dibaca saat ini. Rinciannya tercatat pada log untuk pengembang.",
                                "en": "The submission behind this version cannot be read right now. The details are recorded in the developer log."},

    "ap.lbl_research_identity": {"id": "Research pipeline baru",
                                "en": "New research pipeline"},
    "ap.lbl_research_identifier": {"id": "Pengenal",
                                  "en": "Identifier"},
    "ap.help_research_identity": {"id": "Pengajuan ini berdiri sendiri: ia membawa kontrak datasetnya sendiri, jadi pengenalnya dibentuk dari namanya dan tidak perlu dipilih.",
                                 "en": "This submission stands on its own: it carries its own dataset contract, so its identifier is derived from its name and does not need to be chosen."},

    "ap.sec_declare_schema": {"id": "Kontrak dataset research pipeline ini",
                             "en": "Dataset contract for this research pipeline"},
    "ap.help_declare_schema": {"id": "Paket ini berdiri sendiri, jadi platform tidak punya skema bawaan untuknya. Nyatakan kontraknya di sini — inilah yang dipakai memeriksa dataset yang Anda lampirkan.",
                               "en": "This package stands alone, so the platform has no built-in schema for it. State its contract here — this is what checks the dataset you attach."},
    "ap.lbl_label_column": {"id": "Kolom label",
                           "en": "Label column"},
    "ap.lbl_file_format": {"id": "Format berkas",
                          "en": "File format"},
    "ap.lbl_required_columns": {"id": "Kolom wajib",
                               "en": "Required columns"},
    "ap.help_required_columns": {"id": "Dipisahkan koma atau baris baru. Kolom inilah yang harus ada pada berkas dataset agar dianggap cocok.",
                                "en": "Separated by commas or new lines. These are the columns a dataset file must contain to be considered compatible."},
    "ap.err_schema_incomplete": {"id": "Kontrak dataset belum lengkap: {fields}. Tanpa itu datasetnya tidak dapat diperiksa.",
                                "en": "The dataset contract is incomplete: {fields}. Without it the dataset cannot be checked."},

    # Pipeline kontribusi di katalog: keterangan rincinya TIDAK dibaca di sini,
    # dan alasannya dinyatakan alih-alih meninggalkan bidang kosong.
    "re.cat_uploaded_no_info": {"id": "Keterangan rinci pipeline ini belum pernah dipotret — ia terdaftar sebelum platform menyimpannya. Research Admin dapat mengambilnya lewat \"Perbarui keterangan\" di halaman Jalankan Eksperimen.",
                               "en": "This pipeline's details were never captured — it was registered before the platform stored them. A Research Admin can fetch them with \"Refresh details\" on the Run Experiment page."},
    "re.cat_uploaded_no_info_label": {"id": "Keterangan rinci",
                                     "en": "Detailed information"},
    # Potret `get_info()` yang belum pernah diambil — beserta cara mengambilnya.
    "re.lbl_info_missing": {"id": "Keterangan belum dipotret.",
                            "en": "Details not captured yet."},
    "re.btn_refresh_info": {"id": "Perbarui keterangan", "en": "Refresh details"},
    "re.msg_info_refreshed": {"id": "Keterangan {algorithm} diperbarui.",
                              "en": "Details for {algorithm} refreshed."},

    # ── Daftar antrean peninjauan: cari, urutkan, penggal, buka ──────────────
    "ap.lbl_search_queue": {"id": "Cari pengajuan",
                           "en": "Search submissions"},
    "ap.ph_search_queue": {"id": "nomor, nama, atau pengaju",
                          "en": "number, name, or submitter"},
    "ap.lbl_sort_queue": {"id": "Urutkan",
                         "en": "Sort"},
    "ap.sort_oldest": {"id": "Terlama menunggu",
                      "en": "Waiting longest"},
    "ap.sort_newest": {"id": "Terbaru diajukan",
                      "en": "Most recently submitted"},
    "ap.queue_count": {"id": "Menampilkan {shown} dari {total} pengajuan menunggu.",
                      "en": "Showing {shown} of {total} waiting submissions."},
    "ap.btn_prev_page": {"id": "‹ Sebelumnya",
                        "en": "‹ Previous"},
    "ap.btn_next_page": {"id": "Berikutnya ›",
                        "en": "Next ›"},
    "ap.page_of": {"id": "Halaman {page} dari {total}",
                  "en": "Page {page} of {total}"},
    "ap.lbl_open_submission": {"id": "Buka pengajuan",
                              "en": "Open a submission"},
    "ap.ph_open_submission": {"id": "pilih satu untuk ditinjau",
                             "en": "choose one to review"},
    "ap.btn_back_to_queue": {"id": "‹ Kembali ke antrean",
                            "en": "‹ Back to the queue"},


    # ── Kesalahan tak terduga pada alur pengajuan ───────────────────────────────────────
    "ap.err_unexpected": {"id": "Gagal karena kesalahan tak terduga ({kind}). Rinciannya tercatat pada log untuk pengembang.",
                         "en": "This failed because of an unexpected error ({kind}). The details are recorded in the developer log."},
    # Pembacaan yang gagal pada alur peninjauan. Keduanya menyatakan keadaan
    # "tidak dapat dibaca" — BUKAN "tidak ada" — karena tindakan pemulihannya
    # berbeda, dan gerbang yang tidak terbaca menutup, bukan membuka.
    "ap.err_gate_unreadable": {"id": "Syarat persetujuan tidak dapat diperiksa saat ini, jadi persetujuan ditahan. Muat ulang halaman; bila tetap begini, periksa log untuk pengembang.",
                              "en": "The approval requirements could not be checked right now, so approval is held. Reload the page; if it persists, check the developer log."},
    # Empat sebab sebuah pengajuan TIDAK AKAN PERNAH dapat disetujui apa
    # adanya. Berbeda dari gerbang uji coba ("belum boleh sekarang"), keempatnya
    # hanya dapat diperbaiki dengan mengunggah ulang — jadi kalimatnya menyebut
    # jalan keluar itu, bukan menyuruh peninjau mencoba lagi.
    "ap.err_identity_no_name": {"id": "Pengajuan ini tidak membawa nama research pipeline, jadi pengenalnya tidak dapat dibentuk. Minta pengunggah mengirim ulang dengan nama terisi.",
                                "en": "This submission carries no research pipeline name, so its identifier cannot be formed. Ask the uploader to resubmit with a name filled in."},
    "ap.err_identity_bad_name": {"id": "Nama research pipeline pada pengajuan ini tidak menghasilkan pengenal yang sah. Minta pengunggah mengirim ulang dengan nama yang memuat huruf atau angka.",
                                 "en": "The research pipeline name on this submission does not produce a valid identifier. Ask the uploader to resubmit with a name containing letters or digits."},
    "ap.err_identity_legacy": {"id": "Pengajuan ini dibuat sebelum tiap unggahan berdiri sendiri, dan tidak membawa kontrak dataset maupun jenis dataset. Minta pengunggah mengirim ulang lewat formulir sekarang.",
                               "en": "This submission predates standalone uploads and carries neither a dataset contract nor a dataset type. Ask the uploader to resubmit through the current form."},
    "ap.err_identity_no_entry_class": {"id": "Nama kelas titik masuk tidak tercatat pada pengajuan ini, jadi pipelinenya tidak dapat didaftarkan. Minta pengunggah mengirim ulang.",
                                       "en": "The entry point class name is not recorded on this submission, so its pipeline cannot be registered. Ask the uploader to resubmit."},
    "trial.err_history_unreadable": {"id": "Riwayat uji coba tidak dapat dibaca saat ini. Rinciannya tercatat pada log untuk pengembang.",
                                    "en": "The trial history could not be read right now. The details are recorded in the developer log."},

    # ── Contoh penyisipan BERNAMA ────────────────────────────────────────
    # Perhatikan urutan katanya berbeda: dalam bahasa Inggris satuannya berada
    # di akhir, dalam bahasa Indonesia di tengah. Penyisipan berdasarkan posisi
    # akan menukar keduanya tanpa error; yang bernama tidak bisa.
    "progress.of_total": {
        "id": "{done} dari {total} eksperimen",
        "en": "{done} of {total} experiments"},
    "progress.running_count": {
        "id": "{count} berjalan",
        "en": "{count} running"},
}

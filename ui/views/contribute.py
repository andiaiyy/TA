"""
Halaman "Add Pipeline & Dataset".

Dua jalur kontribusi, dipilih lewat dua kartu di tampilan awal:

  • **Unggah Pipeline** — instruksi persyaratan → unggah beberapa berkas `.py`
    → penjelasan per berkas + metadata → validasi statis seluruh paket →
    laporan rinci → (bila valid) unduh + cuplikan entri registry + panduan
    aktivasi manual.
  • **Unggah Dataset** — persyaratan dataset → unggah berkas → simpan ke
    `storage/datasets/` (nama disanitasi, menimpa ditolak) → diagnosa
    kecocokan yang SUDAH ADA (sampling + cache) terhadap tiap research pipeline.

⚠️ SECURITY (lanjutan Tahap 1–3, tidak dilemahkan):
  - Berkas `.py` yang diunggah TIDAK PERNAH diimpor/`exec`/dijalankan. Seluruh
    pemeriksaan statis lewat `orchestrator/pipeline_validator.py` (`ast.parse`).
  - SETIAP berkas dalam paket divalidasi penuh, bukan hanya entry point-nya —
    berkas pendukung ikut dieksekusi saat pipeline berjalan nanti, jadi
    kegagalan keamanan di berkas mana pun menggagalkan seluruh paket.
  - Registry tetap STATIS. Tidak ada tombol aktivasi, tidak ada penulisan ke
    `config/pipeline_registry.py` maupun ke `pipelines/`.

Logika yang dipakai ulang (tanpa duplikasi): `ui/components/pipeline_upload.py`
untuk validasi paket/cuplikan registry, `orchestrator/dataset_diagnostics.py`
untuk diagnosa dataset, dan penyaji persyaratan/verdict dataset milik halaman
Run Experiment.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import streamlit as st

from config.research_attribution import get_research_short_label
from config.settings import DATASETS_DIR, STORAGE_DIR
from contracts.dataset_schemas import supported_datasets
from database.models import (
    ALL_ROLES, KIND_DATASET, KIND_PIPELINE, ROLE_CONTRIBUTOR,
    ROLE_RESEARCH_ADMIN, STATUS_ACTIVE, STATUS_DISABLED, STATUS_PENDING,
    SUBMISSION_PENDING, role_label,
)
from orchestrator.auth_service import (
    AuthError, PermissionDenied, can_approve, can_manage_users, can_upload,
    create_user_as, list_users, require_upload, set_user_role, set_user_status,
)
from orchestrator.dynamic_registry import (
    DynamicRegistryError, list_registered, set_pipeline_active,
)
from orchestrator.submission_service import (
    approve_submission, list_submissions, read_submission_sources,
    reject_submission, submit_dataset, submit_pipeline,
)
# Konstanta kontrak & keamanan dibaca LANGSUNG dari validator supaya panduan di
# halaman ini tidak pernah menyimpang dari aturan yang benar-benar ditegakkan.
from orchestrator.pipeline_validator import (
    ALLOWED_MODULES, BASE_CLASS_NAME, EXPECTED_INFO_KEYS, FORBIDDEN_CALLS,
    FORBIDDEN_MODULES, REQUIRED_METHODS, RUN_FIRST_PARAM, RUN_PROGRESS_PARAM,
)
from ui.components.pipeline_upload import (
    GROUP_SECURITY, GROUP_STRUCTURE, MAX_UPLOAD_BYTES, PLACEHOLDER, ROLE_ENTRY,
    ROLE_SUPPORT,
    build_registry_snippet, extract_registry_metadata, merge_form_metadata,
    review_package, safe_staging_name, save_to_staging,
)
from ui.components.instructions import (
    render_dataset_instructions, render_pipeline_instructions,
)
from ui.components.contribute_context import render_page_context
from ui.components.upload_cards import render_upload_cards
from ui.views._artifact_browser import format_size
from ui.views.login import current_user, render_login_prompt

logger = logging.getLogger(__name__)

_MODE_KEY = "_contrib_mode"
_RESULT_KEY = "_contrib_pkg_result"
_FORM_KEY = "_contrib_pkg_form"

# Batas unggah peramban. Harus SEJALAN dengan server.maxUploadSize di
# .streamlit/config.toml (dalam MB) — Streamlit menolak lebih dulu di sisi
# server bila nilainya lebih kecil.
MAX_DATASET_UPLOAD_BYTES = 5 * 1024 * 1024 * 1024        # 5 GB

# Potongan awal berkas yang ditulis ke berkas sementara untuk didiagnosa.
# Diagnosa hanya mencuplik 50.000 baris (± 27–30 MB pada dataset di repo ini),
# jadi menyalin SELURUH unggahan 5 GB ke disk hanya untuk diperiksa itu sia-sia.
# Prefix dipotong pada newline terakhir supaya tidak ada baris terpenggal.
DIAGNOSIS_PREFIX_BYTES = 96 * 1024 * 1024                # 96 MB
_COPY_CHUNK_BYTES = 4 * 1024 * 1024                      # 4 MB per tulis

# Berkas sementara untuk diagnosa. DI DALAM proyek (agar lolos path-safety
# resolve_dataset_path) tetapi BUKAN storage/datasets/ — isinya selalu dihapus
# setelah diagnosa selesai.
UPLOAD_TMP_DIR = Path(STORAGE_DIR) / "_upload_tmp"

_DS_DIAG_KEY = "_contrib_ds_diag"

_STATUS_ICON = {"pass": "✔", "warn": "⚠", "fail": "✖"}


# ── Tampilan awal: dua kartu kontribusi ───────────────────────────────────

def _render_choice_boxes() -> None:
    user = current_user()

    # Konteks lebih dulu: keadaan platform → status & hak pengguna → apa yang
    # terjadi setelah mengunggah. Panel ini juga yang menampilkan ajakan masuk
    # bagi pengunjung, jadi tidak ada dua ajakan berturut-turut di sini.
    render_page_context(user)
    st.divider()

    # Empat kartu seragam: dua jalur unggah + dua jalur pengelolaan. Ketiga
    # bendera di sini HANYA menghidupkan/mematikan tombol — izin sebenarnya
    # tetap ditegakkan `require_upload`/`require_approve`/`require_manage_users`
    # di fungsi aksinya, jadi tombol yang hidup pun tidak melewati pemeriksaan.
    mode = render_upload_cards(
        may_upload=bool(can_upload(user)),
        may_approve=bool(can_approve(user)),
        may_manage_users=bool(can_manage_users(user)),
        counts=_admin_queue_notes(user),
    )
    if mode:
        st.session_state[_MODE_KEY] = mode
        st.rerun()

    _render_my_submissions()


def _admin_queue_notes(user: dict | None) -> dict:
    """Baris jumlah antrean pada kartu admin — hanya dibaca bila memang berhak.

    Dipisah dari perenderan supaya kartu tetap bebas dari pembacaan basis data,
    dan supaya pengguna tanpa hak tidak memicu kueri apa pun.
    """
    notes: dict[str, str] = {}
    if can_approve(user):
        try:
            n = len(list_submissions(status=SUBMISSION_PENDING))
            notes["review"] = f"{n} pengajuan menunggu tinjauan."
        except Exception:                   # pragma: no cover - defensive
            pass
    if can_manage_users(user):
        try:
            n = len([u for u in list_users() if u["status"] == STATUS_PENDING])
            notes["users"] = f"{n} pendaftaran menunggu persetujuan."
        except Exception:                   # pragma: no cover - defensive
            pass
    return notes


# ── Pengajuan: milik sendiri & peninjauan ─────────────────────────────────

_STATUS_LABEL = {
    SUBMISSION_PENDING: "Menunggu tinjauan",
    "approved": "Disetujui",
    "rejected": "Ditolak",
}


def _render_my_submissions() -> None:
    """Status pengajuan milik pengguna yang sedang masuk."""
    user = current_user()
    if not can_upload(user):
        return
    try:
        mine = list_submissions(submitted_by=user["username"])
    except Exception as e:                  # pragma: no cover - defensive
        st.caption(f"Daftar pengajuan tidak dapat dibaca: {e}")
        return
    if not mine:
        return

    st.divider()
    st.markdown("Pengajuan saya")
    for item in mine[:10]:
        # SATU baris per pengajuan. Sebelumnya empat caption kecil di empat
        # kolom terpisah — terbaca sebagai serakan, bukan sebagai daftar.
        note = item.get("review_note")
        tail = f"catatan: {note}" if note else (item["submitted_at"] or "")[:19]
        st.markdown(
            f"`#{item['id']}` **{item['original_filename']}** — {item['kind']} · "
            f"{_STATUS_LABEL.get(item['status'], item['status'])} · {tail}")


def _render_review_flow() -> None:
    """Peninjauan pengajuan — hanya Research Admin.

    Izin diperiksa DI SINI dan sekali lagi di dalam ``approve_submission`` /
    ``reject_submission``, jadi menyembunyikan tombol tidak pernah menjadi
    satu-satunya penghalang.
    """
    user = current_user()
    st.subheader("Peninjauan Pengajuan")
    if not can_approve(user):
        st.error("Hanya Research Admin yang dapat meninjau pengajuan.")
        return

    try:
        waiting = list_submissions(status=SUBMISSION_PENDING)
    except Exception as e:                  # pragma: no cover - defensive
        st.error(f"Gagal membaca antrean: {e}")
        return

    # Hanya PIPELINE yang ditinjau: isinya kode yang akan dieksekusi. Dataset
    # tersimpan langsung, jadi tidak pernah masuk antrean ini lagi.
    pending = [s for s in waiting if s["kind"] == KIND_PIPELINE]
    st.caption("Hanya pipeline yang ditinjau — isinya kode yang dieksekusi. "
               "Dataset tersimpan langsung.")
    if not pending:
        st.caption("Tidak ada pengajuan pipeline yang menunggu tinjauan.")
    for item in pending:
        _render_submission_review_card(item, user)

    # Data lama: pengajuan dataset yang terlanjur menunggu sebelum aturan ini
    # berubah. Tidak dibuang — disetujui lewat jalur yang sudah ada, sehingga
    # berkasnya pindah ke storage/datasets/ dan tidak ada yang hilang.
    legacy = [s for s in waiting if s["kind"] == KIND_DATASET]
    if legacy:
        st.divider()
        st.markdown("Pengajuan dataset lama")
        st.caption("Dataset tidak lagi memerlukan persetujuan. Selesaikan "
                   "pengajuan lama ini agar berkasnya masuk ke storage/datasets/.")
        for item in legacy:
            cols = st.columns([5, 2])
            cols[0].markdown(f"`#{item['id']}` **{item['original_filename']}**")
            if cols[1].button("Selesaikan", key=f"legacy_ds_{item['id']}",
                              use_container_width=True):
                try:
                    approve_submission(item["id"], actor=user,
                                       note="Diselesaikan: dataset tidak lagi "
                                            "memerlukan persetujuan.")
                except Exception as e:
                    st.error(f"Gagal menyelesaikan: {e}")
                else:
                    st.success(f"#{item['id']} selesai — berkas masuk ke "
                               f"storage/datasets/.")
                    st.rerun()

    st.divider()
    _render_registered_pipelines(user)

    st.divider()
    st.markdown("Riwayat tinjauan")
    history = [s for s in list_submissions() if s["status"] != SUBMISSION_PENDING]
    if not history:
        st.caption("Belum ada pengajuan yang ditinjau.")
    for item in history[:15]:
        # SATU baris per pengajuan yang sudah ditinjau (sebelumnya 4 caption).
        note = f" · {item['review_note']}" if item.get("review_note") else ""
        st.markdown(
            f"`#{item['id']}` **{item['original_filename']}** — {item['kind']} · "
            f"{_STATUS_LABEL.get(item['status'], item['status'])} · "
            f"oleh {item.get('reviewed_by') or '-'}{note}")


def _render_registered_pipelines(user: dict) -> None:
    """Pipeline terunggah yang sudah terdaftar + aksi aktif/nonaktif.

    Menonaktifkan menarik pipeline dari daftar pilihan TANPA menghapus record
    atau berkasnya, sehingga eksperimen lama tetap dapat ditelusuri lewat
    versi & hash yang sudah tercatat."""
    st.markdown("Pipeline terunggah terdaftar")
    try:
        rows = list_registered()
    except Exception as e:                  # pragma: no cover - defensive
        st.caption(f"Daftar tidak terbaca: {e}")
        return
    if not rows:
        st.caption("Belum ada pipeline terunggah yang disetujui.")
        return

    for row in rows:
        with st.container(border=True):
            cols = st.columns([3, 2, 2, 2])
            cols[0].markdown(f"`{row['pipeline_id']}`")
            # SATU keterangan, bukan tiga potongan di tiga kolom.
            cols[0].caption(
                f"kelas {row['entry_class']} · SHA-256 "
                f"`{row['file_hash'][:12]}…` · "
                f"{get_research_short_label(row['dataset_type'])} · "
                f"{'Aktif' if row['active'] else 'Nonaktif'}")
            label = "Nonaktifkan" if row["active"] else "Aktifkan"
            if cols[3].button(label, key=f"reg_toggle_{row['pipeline_id']}",
                              use_container_width=True):
                try:
                    set_pipeline_active(row["pipeline_id"], not row["active"],
                                        actor=user)
                except (AuthError, DynamicRegistryError) as e:
                    st.error(str(e))
                else:
                    st.rerun()
    st.caption("Versi bersifat immutable: menyetujui nama yang sama lagi "
               "membuat versi baru, versi lama tidak pernah berubah.")


def _render_submission_review_card(item: dict, user: dict) -> None:
    header = (f"#{item['id']} · {item['kind']} · {item['original_filename']} · "
              f"{format_size(item['file_size'])} · oleh {item['submitted_by']}")
    with st.expander(header, expanded=False):
        st.caption(f"Diajukan {(item['submitted_at'] or '')[:19]} · "
                   f"SHA-256 `{item['file_hash'][:16]}…`")

        metadata = item.get("metadata") or {}
        validation = item.get("validation") or {}
        if metadata:
            st.markdown("Metadata")
            st.json(metadata, expanded=False)

        if item["kind"] == KIND_PIPELINE:
            st.markdown("Hasil validasi statis")
            st.json(validation, expanded=False)
            # Kode ditampilkan sebagai TEKS — tidak pernah diimpor/dieksekusi.
            for name, source in read_submission_sources(item):
                st.caption(f"`{name}`")
                st.code(source, language="python")
            st.caption("Kode ditampilkan sebagai teks; platform tidak pernah "
                       "mengimpor atau menjalankannya.")
        else:
            st.markdown("Profil & kompatibilitas saat diajukan")
            st.json(validation, expanded=False)
            st.caption("Angka profil berasal dari sampel saat pengajuan "
                       "(berkas tidak dimuat seluruhnya).")

        chosen_type = None
        if item["kind"] == KIND_PIPELINE:
            options = list(supported_datasets())
            meta_type = (item.get("metadata") or {}).get("dataset_type")
            chosen_type = st.selectbox(
                "Dataset target", options,
                index=options.index(meta_type) if meta_type in options else None,
                format_func=_dataset_label, placeholder="Pilih dataset_type…",
                key=f"review_dtype_{item['id']}",
                help="Menentukan di bawah research pipeline mana pipeline ini muncul.",
            )

        note = st.text_input("Catatan tinjauan", key=f"review_note_{item['id']}",
                             placeholder="Wajib diisi saat menolak")
        cols = st.columns(2)
        if cols[0].button("Setujui", key=f"review_approve_{item['id']}",
                          type="primary", use_container_width=True):
            try:
                approve_submission(item["id"], actor=user, note=note,
                                   dataset_type=chosen_type)
            except AuthError as e:
                st.error(str(e))
            else:
                st.rerun()
        if cols[1].button("Tolak", key=f"review_reject_{item['id']}",
                          use_container_width=True):
            try:
                reject_submission(item["id"], actor=user, note=note)
            except AuthError as e:
                st.error(str(e))
            else:
                st.rerun()

        if item["kind"] == KIND_PIPELINE:
            st.caption("Menyetujui mendaftarkan pipeline sebagai versi baru "
                       "(`uploaded.<nama>@v<N>`) sehingga dapat dipilih & "
                       "dijalankan. `config/pipeline_registry.py` tidak "
                       "disentuh; versi lama tidak pernah ditimpa.")
        else:
            st.caption("Menyetujui memindahkan berkas ke `storage/datasets/` "
                       "sehingga dapat dipilih di Run Experiment.")


# ── Kelola pengguna (Research Admin) ──────────────────────────────────────

def _render_users_flow() -> None:
    """Bagian kelola pengguna. Ditempatkan di halaman ini sebagai jalur ketiga
    (bukan halaman navigasi baru) supaya menu tetap tiga halaman.

    Izinnya diperiksa DI SINI dan sekali lagi di dalam fungsi aksinya
    (`create_user_as` / `set_user_active`), sehingga menyembunyikan menu saja
    tidak pernah menjadi satu-satunya penghalang."""
    user = current_user()
    st.subheader("Kelola Pengguna")
    if not can_manage_users(user):
        st.error("Hanya Research Admin yang dapat mengelola pengguna.")
        return

    pending = [u for u in list_users() if u["status"] == STATUS_PENDING]
    st.markdown(f"Menunggu persetujuan ({len(pending)})")
    if not pending:
        st.caption("Tidak ada pendaftaran yang menunggu.")
    for row in pending:
        with st.container(border=True):
            cols = st.columns([3, 3, 2, 2])
            cols[0].markdown(f"`{row['username']}`")
            # SATU keterangan: waktu daftar + keperluan.
            cols[0].caption(
                f"Didaftarkan {(row.get('requested_at') or '')[:19]} · "
                f"{row.get('reason') or 'tanpa keterangan'}")
            if cols[2].button("Aktifkan", key=f"user_activate_{row['username']}",
                              type="primary", use_container_width=True):
                try:
                    set_user_status(row["username"], STATUS_ACTIVE, actor=user)
                except AuthError as e:
                    st.error(str(e))
                else:
                    st.rerun()
            if cols[3].button("Tolak", key=f"user_reject_{row['username']}",
                              use_container_width=True):
                try:
                    set_user_status(row["username"], STATUS_DISABLED, actor=user)
                except AuthError as e:
                    st.error(str(e))
                else:
                    st.rerun()
    st.caption("Akun yang menunggu tidak memiliki hak apa pun sampai diaktifkan.")

    st.divider()
    st.markdown("Buat akun baru")
    with st.form("contrib_create_user"):
        cols = st.columns(3)
        new_username = cols[0].text_input("Username", key="contrib_new_username")
        new_password = cols[1].text_input("Password", type="password",
                                          key="contrib_new_password")
        new_role = cols[2].selectbox("Peran", ALL_ROLES, index=ALL_ROLES.index(ROLE_CONTRIBUTOR),
                                     format_func=role_label, key="contrib_new_role")
        created = st.form_submit_button("Buat akun", type="primary")
    if created:
        try:
            created_user = create_user_as(user, new_username, new_password, new_role)
        except AuthError as e:            # termasuk PermissionDenied
            st.error(str(e))
        else:
            st.success(f"Akun `{created_user['username']}` dibuat "
                       f"({created_user['role_label']}).")

    st.divider()
    st.markdown("Daftar pengguna")
    try:
        users = list_users()
    except Exception as e:                # pragma: no cover - defensive
        st.error(f"Gagal membaca daftar pengguna: {e}")
        return
    if not users:
        st.caption("Belum ada akun.")
        return

    for row in users:
        with st.container(border=True):
            cols = st.columns([3, 2, 2, 2])
            cols[0].markdown(f"`{row['username']}`")
            # SATU keterangan: peran + status akun (status WAJIB tetap tampil).
            cols[0].caption(f"{row['role_label']} · {row['status_label']}")
            is_self = row["username"] == (user or {}).get("username")
            if is_self:
                cols[2].caption("Akun Anda")
                continue

            active = row["status"] == STATUS_ACTIVE
            label = "Nonaktifkan" if active else "Aktifkan"
            if cols[2].button(label, key=f"contrib_toggle_{row['username']}",
                              use_container_width=True):
                try:
                    set_user_status(row["username"],
                                    STATUS_DISABLED if active else STATUS_ACTIVE,
                                    actor=user)
                except AuthError as e:
                    st.error(str(e))
                else:
                    st.rerun()
            # Peran Research Admin HANYA diberikan dari sini — tidak pernah
            # lewat pendaftaran mandiri.
            promote = row["role"] != ROLE_RESEARCH_ADMIN
            role_label_btn = "Jadikan Admin" if promote else "Jadikan Kontributor"
            if cols[3].button(role_label_btn, key=f"contrib_role_{row['username']}",
                              use_container_width=True):
                try:
                    set_user_role(row["username"],
                                  ROLE_RESEARCH_ADMIN if promote else ROLE_CONTRIBUTOR,
                                  actor=user)
                except AuthError as e:
                    st.error(str(e))
                else:
                    st.rerun()
    st.caption("Password tidak pernah ditampilkan — hanya turunan bersaltnya "
               "yang disimpan.")


def _render_upload_gate(kind: str) -> bool:
    """True bila pengguna saat ini boleh mengunggah; selain itu tampilkan
    keterangan + arahan masuk dan kembalikan False.

    SATU tempat yang menentukan status kontrol unggah di kedua jalur, sehingga
    tampilan tidak pernah menyimpang dari izin yang ditegakkan lapis aksi.
    Halaman & persyaratannya sendiri tidak pernah disembunyikan — hanya
    kontrolnya yang dimatikan.
    """
    user = current_user()
    if can_upload(user):
        return True

    label = "dataset" if kind == "dataset" else "pipeline"
    render_login_prompt(
        f"Masuk sebagai Kontributor untuk mengunggah {label}. Persyaratan di "
        f"atas tetap dapat dibaca tanpa masuk; melihat hasil dan menjalankan "
        f"eksperimen juga tidak memerlukan akun.",
        key=f"contrib_login_gate_{kind}",
    )
    st.caption("Kontrol unggah dinonaktifkan sampai Anda masuk.")
    return False


# ── Jalur pipeline: instruksi persyaratan (dari konstanta validator) ──────

def _render_pipeline_requirements() -> None:
    """Persyaratan pipeline sebagai diagram alur + tabel kontrak + chip modul.

    Isinya sama persis dengan sebelumnya (dan tetap dibaca dari konstanta
    validator), hanya disajikan padat; rinciannya ada di expander.
    """
    render_pipeline_instructions()


# ── Jalur pipeline: laporan ───────────────────────────────────────────────

def _render_group(title: str, checks: list[dict]) -> None:
    if not checks:
        return
    st.markdown(f"**{title}**")
    for c in checks:
        icon = _STATUS_ICON.get(c["status"], "·")
        line = f" _(baris {c['line']})_" if c.get("line") else ""
        st.markdown(f"- {icon} **{c['name']}** — {c['message']}{line}")


def _render_package_report(result: dict, form: dict) -> None:
    st.subheader("Hasil validasi")
    n_files = len(result["files"])
    if result["valid"]:
        st.success(f"Valid — {n_files} berkas lolos, entry point "
                   f"`{result['entry_points'][0]}`.")
    else:
        st.error(result["summary"])
        if result["cause"]:
            st.markdown(result["cause"])

    for item in result["files"]:
        ok = item["package_ok"]
        icon = "✔" if ok else "✖"
        header = (f"{icon} {item['filename']} · {item['role']} · "
                  f"{format_size(item['size'])}")
        with st.expander(header, expanded=not ok):
            if item["description"]:
                st.caption(f"Penjelasan pengguna: {item['description']}")
            if not item["ok"]:
                st.error(item["error"])
                continue
            if not ok:
                st.markdown("Perlu diperbaiki")
                for c in item["blocking_failures"]:
                    line = f" _(baris {c['line']})_" if c.get("line") else ""
                    st.markdown(f"- {c['message']}{line}")
            if item["role"] == ROLE_SUPPORT:
                st.caption(
                    "Berkas pendukung: kontrak pipeline tidak berlaku, aturan "
                    "keamanan tetap penuh — berkas ini ikut dieksekusi saat "
                    "pipeline berjalan."
                )
            _render_group(GROUP_STRUCTURE, item["groups"][GROUP_STRUCTURE])
            _render_group(GROUP_SECURITY, item["groups"][GROUP_SECURITY])

    if not result["valid"]:
        st.caption("Perbaiki poin ✖ di atas lalu unggah ulang. Unduhan dan "
                   "cuplikan registry muncul setelah paket valid.")
        return

    _render_valid_followup(result, form)


def _render_valid_followup(result: dict, form: dict) -> None:
    """Unduh + cuplikan registry terisi metadata + panduan aktivasi manual."""
    st.divider()
    st.info("Paket valid — pipeline **belum aktif**, menunggu aktivasi manual.")

    st.markdown("Unduh berkas tervalidasi")
    cols = st.columns(min(3, len(result["files"])) or 1)
    for i, item in enumerate(result["files"]):
        cols[i % len(cols)].download_button(
            f"⬇ {item['filename']}",
            data=item["source"].encode("utf-8"),
            file_name=safe_staging_name(item["filename"]) or "pipeline.py",
            mime="text/x-python",
            use_container_width=True,
            key=f"contrib_dl_{item['filename']}",
        )

    user = current_user()
    entry_item = next(f for f in result["files"] if f["role"] == ROLE_ENTRY)
    if not can_upload(user):
        render_login_prompt(
            "Masuk sebagai Kontributor untuk mengajukan paket ini. Hasil "
            "validasi di atas tetap dapat dibaca tanpa masuk.",
            key="contrib_login_stage",
        )
    else:
        st.caption("Paket diajukan untuk ditinjau Research Admin. Menyetujui "
                   "menandai paket sebagai layak — pendaftaran ke registry "
                   "tetap dilakukan manual.")
        if st.button("Ajukan untuk ditinjau", key="contrib_submit_pipeline",
                     type="primary"):
            # Nama kelas entry point dibaca STATIS dari AST — dibutuhkan
            # peninjau untuk mendaftarkan pipeline saat menyetujui.
            static_meta = extract_registry_metadata(entry_item["source"],
                                                    entry_item["filename"])
            try:
                submission = submit_pipeline(
                    [(f["filename"], f["source"]) for f in result["files"]],
                    entry_item["filename"], user=user,
                    metadata={**{k: v for k, v in (form or {}).items() if v},
                              "entry_class": static_meta.get("class_name")},
                    validation={
                        "valid": result["valid"],
                        "entry_points": result["entry_points"],
                        "files": [{"filename": f["filename"], "role": f["role"],
                                   "package_ok": f["package_ok"],
                                   "description": f["description"]}
                                  for f in result["files"]],
                    },
                )
            except (AuthError, OSError) as e:
                st.error(f"Gagal mengajukan: {e}")
            else:
                st.success(f"Diajukan sebagai pengajuan #{submission['id']}.")
                st.caption("Menunggu peninjauan Research Admin — pipeline ini "
                           "**belum** aktif dan belum dapat dijalankan.")

    st.divider()
    entry = next(f for f in result["files"] if f["role"] == ROLE_ENTRY)
    meta = merge_form_metadata(
        extract_registry_metadata(entry["source"], entry["filename"]), form)
    st.markdown("Cuplikan entri registry")
    st.caption("Salin manual ke `config/pipeline_registry.py`.")
    st.code(build_registry_snippet(meta), language="python")
    missing = [f for f in ("dataset_type", "name", "paper", "algorithm")
               if not meta.get(f)]
    if missing:
        st.caption(
            f"Placeholder `{PLACEHOLDER}_…` tersisa untuk "
            + ", ".join(f"`{f}`" for f in missing)
            + " — lengkapi formulir metadata atau isi manual; platform tidak "
              "menebak nilainya."
        )
    if form.get("notes"):
        st.caption(f"Catatan pengunggah: {form['notes']}")

    st.divider()
    st.markdown("Langkah aktivasi (manual, oleh pengembang)")
    st.markdown(
        "1. Letakkan berkas paket di `pipelines/<subdirektori riset>/`.\n"
        "2. Import kelas entry point di `config/pipeline_registry.py`.\n"
        "3. Tambahkan entri di atas ke `PIPELINE_REGISTRY`.\n"
        "4. Commit + review lewat git.\n"
        "5. Rebuild/restart aplikasi & worker."
    )
    st.caption(
        "Validasi statis menyaring masalah umum, bukan jaminan mutlak — "
        "tinjauan manusia tetap diperlukan. Platform tidak menulis ke registry "
        "atau ke `pipelines/`, dan tidak menjalankan berkas yang diunggah."
    )


# ── Jalur pipeline ────────────────────────────────────────────────────────

_OTHER_DATASET_OPTION = "Lainnya / belum terdaftar"


def _dataset_label(dataset_type: str) -> str:
    """Label dropdown: nama beratribusi ringkas, nilai internal tetap
    dataset_type. Opsi "lainnya" dibiarkan apa adanya."""
    if dataset_type == _OTHER_DATASET_OPTION:
        return dataset_type
    return get_research_short_label(dataset_type)


def _render_pipeline_flow() -> None:
    st.subheader("Unggah Pipeline")
    _render_pipeline_requirements()
    st.divider()

    # Lapis TAMPILAN: persyaratan di atas tetap terbaca siapa pun, tetapi
    # kontrol unggahnya dimatikan bila belum berhak — supaya tidak ada tombol
    # yang tampak aktif padahal aksinya pasti ditolak lapis aksi.
    may_upload = _render_upload_gate("pipeline")

    uploaded = st.file_uploader(
        "Berkas pipeline", type=["py"], accept_multiple_files=True,
        key="contrib_pipeline_files", disabled=not may_upload,
        help="Boleh lebih dari satu berkas `.py`. Tepat satu di antaranya "
             "menjadi entry point.",
    )
    uploaded = uploaded or []
    descriptions: dict[str, str] = {}
    if uploaded:
        st.markdown("Berkas terunggah")
        for f in uploaded:
            box = st.container(border=True)
            cols = box.columns([2, 3])
            try:
                size = len(f.getvalue())
            except Exception:  # pragma: no cover - defensive
                size = 0
            cols[0].markdown(f"`{f.name}`")
            cols[0].caption(format_size(size))
            descriptions[f.name] = cols[1].text_input(
                "Peran berkas", key=f"contrib_desc_{f.name}",
                placeholder="mis. entry point / helper preprocessing",
                help="Penjelasan singkat untuk peninjau.",
            )

    st.divider()
    st.markdown("Metadata pipeline")
    st.caption("Mengisi cuplikan entri registry. Tidak memengaruhi hasil validasi.")
    c1, c2 = st.columns(2)
    name = c1.text_input("Nama pipeline", key="contrib_meta_name",
                         placeholder="mis. Random Forest — HIKARI2021")
    dtype_options = list(supported_datasets()) + [_OTHER_DATASET_OPTION]
    dtype_choice = c2.selectbox(
        "Research pipeline", dtype_options, index=None,
        format_func=_dataset_label, placeholder="Pilih research pipeline…",
        key="contrib_meta_dtype",
        help="Menentukan `dataset_type` pada entri registry.",
    )
    algorithm = c1.text_input("Algoritma", key="contrib_meta_algo",
                              placeholder="mis. Random Forest")
    paper = c2.text_input("Paper / rujukan", key="contrib_meta_paper",
                          placeholder="mis. Rayyan (2024), Universitas Hasanuddin")
    notes = st.text_area("Catatan", key="contrib_meta_notes", height=80,
                         help="Opsional — ikut ditampilkan pada laporan.")

    form = {
        "name": name,
        "dataset_type": "" if dtype_choice == _OTHER_DATASET_OPTION else (dtype_choice or ""),
        "algorithm": algorithm,
        "paper": paper,
        "notes": notes,
    }

    if st.button("Unggah & Validasi", type="primary", key="contrib_validate",
                 disabled=not may_upload):
        problems = []
        if not uploaded:
            problems.append("unggah minimal satu berkas `.py`")
        if not (name or "").strip():
            problems.append("isi Nama pipeline")
        if problems:
            st.warning("Lengkapi dulu: " + "; ".join(problems) + ".")
        else:
            files: list[tuple[str, bytes]] = []
            progress = st.progress(0.0, text="Menyiapkan…")
            with st.status("Memvalidasi paket…", expanded=True) as status:
                total = len(uploaded)
                for i, f in enumerate(uploaded, 1):
                    st.write(f"Memeriksa `{f.name}` ({i}/{total})")
                    progress.progress(i / total, text=f"Memeriksa {f.name} ({i}/{total})")
                    try:
                        files.append((f.name, f.getvalue()))
                    except Exception as e:  # pragma: no cover - defensive
                        st.write(f"Gagal membaca `{f.name}`: {e}")
                # Validasi statis seluruh paket (tidak menjalankan apa pun).
                result = review_package(files, descriptions)
                status.update(label=f"Selesai — {result['summary']}",
                              state="complete", expanded=False)
            progress.empty()
            st.session_state[_RESULT_KEY] = result
            st.session_state[_FORM_KEY] = form

    result = st.session_state.get(_RESULT_KEY)
    if result:
        st.divider()
        _render_package_report(result, st.session_state.get(_FORM_KEY) or form)


# ── Jalur dataset ─────────────────────────────────────────────────────────

DATASET_EXTENSIONS = (".csv", ".ndjson", ".jsonl", ".json")
_SAFE_DATASET_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def safe_dataset_name(filename: str) -> str | None:
    """Nama berkas dataset yang aman, atau None bila tidak layak.

    Menolak (bukan memotong) nama ber-separator, nama aneh, dan ekstensi di
    luar daftar — sehingga unggahan tidak pernah dapat menulis ke luar
    `storage/datasets/`.
    """
    name = filename or ""
    if "/" in name or "\\" in name or name != Path(name).name:
        return None
    if name in ("", ".", "..") or not _SAFE_DATASET_NAME.match(name):
        return None
    if Path(name).suffix.lower() not in DATASET_EXTENSIONS:
        return None
    return name


def _dataset_target_path(filename: str) -> Path:
    return Path(DATASETS_DIR) / filename


def upload_size(uploaded) -> int:
    """Ukuran unggahan TANPA menyalin isinya ke objek bytes baru."""
    size = getattr(uploaded, "size", None)
    if isinstance(size, int):
        return size
    try:                                   # fallback: hitung lewat seek
        pos = uploaded.tell()
        uploaded.seek(0, 2)
        size = uploaded.tell()
        uploaded.seek(pos)
        return int(size)
    except Exception:                      # pragma: no cover - defensive
        return 0


def save_dataset_upload(src, target: Path, *, user: dict | None) -> int:
    """Simpan berkas dataset ke `storage/datasets/`.

    ``user`` WAJIB (keyword-only, tanpa default): izin diperiksa DI SINI, jadi
    aksi ini tidak dapat dipicu tanpa hak walau tombolnya berhasil ditekan.
    Mengembalikan jumlah byte yang ditulis.
    """
    require_upload(user)
    written, _truncated = copy_stream(src, target)
    return written


def copy_stream(src, target: Path, *, max_bytes: int | None = None,
                chunk: int = _COPY_CHUNK_BYTES) -> tuple[int, bool]:
    """Salin ``src`` ke ``target`` BERTAHAP. Mengembalikan (byte ditulis, terpotong).

    Tidak pernah memuat seluruh isi ke satu objek bytes — penting karena
    ``st.file_uploader`` sudah menahan berkas di RAM; menduplikasinya akan
    melipatgandakan pemakaian memori pada berkas berukuran GB.

    Bila ``max_bytes`` diberikan, penyalinan berhenti di sana dan dipotong pada
    newline TERAKHIR supaya tidak ada baris terpenggal (potongan dipakai untuk
    diagnosa yang memang berbasis sampel).
    """
    src.seek(0)
    written, truncated = 0, False
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "wb") as out:
        while True:
            want = chunk if max_bytes is None else min(chunk, max_bytes - written)
            if want <= 0:
                truncated = bool(src.read(1))     # masih ada sisa → terpotong
                break
            block = src.read(want)
            if not block:
                break
            out.write(block)
            written += len(block)
    src.seek(0)

    if truncated:
        # Rapikan ekor agar baris terakhir utuh.
        with open(target, "r+b") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            tail_start = max(0, size - chunk)
            fh.seek(tail_start)
            tail = fh.read()
            cut = tail.rfind(b"\n")
            if cut != -1:
                fh.truncate(tail_start + cut + 1)
                written = tail_start + cut + 1
    return written, truncated


def _diagnose_uploaded(uploaded, safe_name: str) -> dict | None:
    """Diagnosa unggahan TANPA menaruhnya di `storage/datasets/`.

    Potongan awal berkas ditulis ke berkas sementara di `storage/_upload_tmp/`
    (di dalam proyek agar lolos path-safety), didiagnosa dengan mesin sampling
    yang sudah ada, lalu berkas sementaranya SELALU dihapus. Hasilnya disimpan
    di session_state per (nama, ukuran) supaya rerun berikutnya tidak membaca
    ulang apa pun.
    """
    from orchestrator.dataset_diagnostics import diagnose_all

    key = (safe_name, upload_size(uploaded))
    cached = st.session_state.get(_DS_DIAG_KEY)
    if cached and cached[0] == key:
        return cached[1]

    tmp = UPLOAD_TMP_DIR / f"{os.getpid()}_{safe_name}"
    try:
        _written, truncated = copy_stream(uploaded, tmp,
                                          max_bytes=DIAGNOSIS_PREFIX_BYTES)
        diag = diagnose_all(str(tmp))
    except OSError as e:
        st.error(f"Gagal memeriksa berkas: {e}")
        return None
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:                    # pragma: no cover - defensive
            logger.warning("Berkas sementara %s gagal dihapus", tmp, exc_info=True)

    if truncated and diag.get("profile"):
        # Potongan awal berhenti sebelum akhir berkas: angka apa pun dari sini
        # adalah angka SAMPEL, jangan pernah tampil sebagai total.
        diag["profile"]["sampled"] = True
    st.session_state[_DS_DIAG_KEY] = (key, diag)
    return diag


def _render_dataset_requirements_overview() -> None:
    """Persyaratan kedua research pipeline sebagai diagram + tabel per tab,
    tanpa meminta pengguna memilih — diagnosa yang menyimpulkan kecocokannya.

    Panel persyaratan lengkap milik halaman Run Experiment dipakai apa adanya
    di dalam expander, jadi halaman itu tidak terpengaruh sama sekali.
    """
    render_dataset_instructions()


def _render_dataset_flow() -> None:
    st.subheader("Tambah Dataset")
    st.caption("Berkas diperiksa terhadap seluruh research pipeline — tidak "
               "perlu memilih pipeline lebih dulu.")
    _render_dataset_requirements_overview()

    st.divider()
    tab_upload, tab_server = st.tabs(["Unggah berkas", "Daftarkan dari server"])
    with tab_upload:
        _render_dataset_upload_tab()
    with tab_server:
        _render_dataset_server_tab()


def _render_dataset_upload_tab() -> None:
    limit_gb = MAX_DATASET_UPLOAD_BYTES / (1024 ** 3)
    may_upload = _render_upload_gate("dataset")
    uploaded = st.file_uploader(
        "Berkas dataset", type=["csv", "ndjson", "jsonl", "json"],
        accept_multiple_files=False, key="contrib_dataset_file",
        disabled=not may_upload,
        help=f"Batas unggah {limit_gb:.0f} GB.",
    )
    st.caption(f"Batas unggah {limit_gb:.0f} GB. Berkas yang lebih besar "
               f"didaftarkan lewat tab **Daftarkan dari server**.")
    if uploaded is None:
        return

    safe = safe_dataset_name(uploaded.name)
    if safe is None:
        st.error(
            "Nama berkas tidak valid. Gunakan huruf/angka/`._-` tanpa komponen "
            "direktori, berekstensi `.csv`, `.ndjson`, `.jsonl`, atau `.json`."
        )
        return

    size = upload_size(uploaded)
    if size > MAX_DATASET_UPLOAD_BYTES:
        st.error(f"Berkas terlalu besar ({format_size(size)}, batas "
                 f"{limit_gb:.0f} GB).")
        st.caption("Salin berkas ke `storage/datasets/` di server, lalu pakai "
                   "tab **Daftarkan dari server** — tanpa batas ukuran dan "
                   "tanpa penyalinan.")
        return

    with st.container(border=True):
        cols = st.columns(2)
        cols[0].markdown(f"`{safe}`")
        cols[0].caption(format_size(size))

    # 1. Diagnosa DULU — belum ada apa pun yang ditulis ke storage/datasets/.
    with st.spinner("Memeriksa dataset…"):
        diag = _diagnose_uploaded(uploaded, safe)
    if diag is None:
        return
    if diag.get("error"):
        st.warning(diag["error"])
        return

    st.divider()
    _render_dataset_profile(diag.get("profile") or {}, safe, size)
    st.divider()
    _render_compatibility(diag)

    # 2. Baru menyimpan, atas tindakan eksplisit pengguna.
    st.divider()
    target = _dataset_target_path(safe)
    if target.exists():
        st.error(f"`{safe}` sudah ada di `storage/datasets/`. Ganti nama "
                 f"berkasnya — platform tidak menimpa dataset yang sudah ada.")
        return
    if not diag.get("compatible_types"):
        st.warning("Belum cocok dengan research pipeline mana pun — tetap "
                   "boleh disimpan.")
    st.caption(f"Tujuan: `{target}`")

    user = current_user()
    if not can_upload(user):
        render_login_prompt(
            "Masuk sebagai Kontributor untuk mengajukan dataset ini. "
            "Pemeriksaan di atas tetap dapat Anda baca tanpa masuk.",
            key="contrib_login_dataset",
        )
        return
    # Dataset adalah DATA, bukan kode yang dieksekusi — jadi ia tidak melewati
    # tinjauan: begitu lolos pemeriksaan, berkasnya langsung tersimpan. Seluruh
    # pengaman sebelum titik ini tetap berlaku (batas ukuran, sanitasi nama,
    # penolakan menimpa, ekstensi yang diizinkan), dan `save_dataset_upload`
    # tetap memanggil `require_upload` sehingga izinnya ditegakkan di lapis aksi.
    st.caption("Tersimpan langsung setelah lolos pemeriksaan.")
    if st.button("Simpan dataset", type="primary",
                 key="contrib_submit_dataset"):
        try:
            written = save_dataset_upload(uploaded, target, user=user)
        except (AuthError, PermissionDenied, OSError) as e:
            st.error(f"Gagal menyimpan: {e}")
            return
        st.success(f"Tersimpan sebagai `{safe}` ({format_size(written)}).")
        st.caption("Sudah dapat dipilih di halaman Run Experiment.")


def _render_dataset_server_tab() -> None:
    """Daftarkan berkas yang SUDAH ada di storage/datasets/ — tanpa batas
    ukuran dan tanpa penyalinan. Jalur untuk dataset besar (mis. EVE 5,9 GB)
    yang tidak masuk akal lewat peramban."""
    # Pembacaan folder memakai mekanisme yang SAMA dengan halaman Run Experiment.
    from ui.views.run_experiment import _all_dataset_options, _diagnose_selected

    st.caption("Berkas yang sudah berada di `storage/datasets/`. Tidak ada "
               "penyalinan dan tidak ada batas ukuran.")
    try:
        options = [p for p, _dtype in _all_dataset_options()]
    except Exception as e:                 # pragma: no cover - defensive
        st.error(f"Gagal memindai `storage/datasets/`: {e}")
        return
    if not options:
        st.info("Belum ada berkas di `storage/datasets/`. Salin berkas ke "
                "folder tersebut di server, lalu segarkan halaman ini.")
        return

    def _label(path: str) -> str:
        try:
            return f"{Path(path).name} · {format_size(Path(path).stat().st_size)}"
        except OSError:                    # pragma: no cover - defensive
            return Path(path).name

    chosen = st.selectbox("Berkas dataset", options, index=None,
                          format_func=_label, placeholder="Pilih berkas…",
                          key="contrib_server_dataset")
    if not chosen:
        return

    if st.button("Periksa dataset", type="primary", key="contrib_check_server"):
        st.session_state["_contrib_server_checked"] = chosen
    if st.session_state.get("_contrib_server_checked") != chosen:
        return

    # Memakai diagnosa ber-cache milik Run Experiment (path+mtime+ukuran), jadi
    # berkas besar tidak dibaca ulang antar-rerun.
    with st.spinner("Memeriksa dataset…"):
        diag = _diagnose_selected(chosen)
    if diag.get("error"):
        st.warning(diag["error"])
        return

    try:
        size = Path(chosen).stat().st_size
    except OSError:                        # pragma: no cover - defensive
        size = 0
    st.divider()
    _render_dataset_profile(diag.get("profile") or {}, Path(chosen).name, size)
    st.divider()
    _render_compatibility(diag)


_PROFILE_PREVIEW_COLUMNS = 10       # nama kolom yang disebut sebelum "… (+N lainnya)"


def _sample_note(profile: dict) -> str:
    """Catatan wajib bahwa angka berasal dari sampel, bukan seluruh berkas."""
    n = f"{profile.get('rows_read', 0):,}"
    if profile.get("sampled"):
        return (f"Angka di atas dari {n} baris pertama — berkas tidak dimuat "
                f"seluruhnya.")
    return f"Berdasarkan seluruh {n} baris berkas ini."


def _render_dataset_profile(profile: dict, filename: str, size_bytes: int) -> None:
    """Profil deskriptif berkas — SEMUA dari sampel yang sudah dibaca diagnosa.
    Tidak ada pembacaan berkas tambahan di sini."""
    fmt_names = {"csv": "CSV", "ndjson": "NDJSON", "unknown": "tidak dikenali"}
    is_json = profile.get("detected_format") == "ndjson"
    unit = "Kunci JSON" if is_json else "Kolom"

    rows = profile.get("rows_read", 0)
    # Jumlah baris TIDAK pernah diklaim sebagai total bila hanya dari sampel.
    rows_text = f"≥ {rows:,} (sampel)" if profile.get("sampled") else f"{rows:,}"

    st.subheader("Profil dataset")

    pairs: list[tuple[str, str]] = [
        ("Berkas", f"`{filename}`"),
        ("Ukuran", format_size(size_bytes)),
        ("Format", fmt_names.get(profile.get("detected_format"), "?")),
        ("Baris", rows_text),
        (unit, str(profile.get("column_count", 0))),
    ]
    if profile.get("numeric_columns") is not None:
        pairs.append(("Tipe data", f"{profile['numeric_columns']} numerik · "
                                   f"{profile['non_numeric_columns']} non-numerik"))
    if profile.get("label_column"):
        pairs.append(("Kolom label", f"`{profile['label_column']}`"))
    elif is_json:
        pairs.append(("Kolom label", "dibentuk pipeline dari alert Suricata"))
    if profile.get("encoding") and profile["encoding"] != "utf-8":
        pairs.append(("Encoding", profile["encoding"]))
    if profile.get("malformed_lines"):
        pairs.append(("Baris gagal diparse", f"{profile['malformed_lines']:,} (diabaikan)"))

    with st.container(border=True):
        for label, value in pairs:
            cols = st.columns([1, 2])
            cols[0].caption(label)
            cols[1].markdown(value)

    # Nama kolom: beberapa contoh + daftar lengkap di expander tertutup.
    columns = profile.get("columns") or []
    if columns:
        shown = columns[:_PROFILE_PREVIEW_COLUMNS]
        text = ", ".join(f"`{c}`" for c in shown)
        rest = len(columns) - len(shown)
        if rest > 0:
            text += f", … (+{rest} lainnya)"
        st.caption(text)
        with st.expander(f"Semua {len(columns)} {unit.lower()}", expanded=False):
            st.code("\n".join(str(c) for c in columns), language=None)

    # Distribusi kelas dari sampel — selalu dengan keterangan sampel.
    counts = profile.get("class_counts") or {}
    if counts:
        total = sum(counts.values()) or 1
        st.markdown("Distribusi kelas")
        for value, n in counts.items():
            st.markdown(f"- `{value}` — {n:,} ({n / total * 100:.1f}%)")
    elif is_json:
        st.markdown("Indikasi kelas")
        st.markdown(f"- Event TLS — {profile.get('tls_rows', 0):,}")
        st.markdown(f"- Event beralert (calon kelas attack) — "
                    f"{profile.get('alert_rows', 0):,}")
    st.caption(_sample_note(profile))


def _algorithms_for(dataset_type: str) -> list[str]:
    """Algoritma yang tersedia untuk sebuah dataset_type, DARI REGISTRY."""
    from config.pipeline_registry import get_pipelines_for_dataset
    seen: list[str] = []
    for info in get_pipelines_for_dataset(dataset_type).values():
        algo = info.get("algorithm") or info.get("name")
        if algo and algo not in seen:
            seen.append(algo)
    return seen


def _render_compatibility(diag: dict) -> None:
    """Kecocokan PER RESEARCH PIPELINE (bukan per algoritma).

    Memakai helper penyaji yang sudah ada di halaman Run Experiment supaya
    gayanya identik: _verdict / _cause_sentence / _action_sentence /
    _render_check_list.
    """
    from ui.views.run_experiment import (
        _VERDICT_LABEL, _action_sentence, _cause_sentence, _render_check_list,
        _sorted_results, _verdict,
    )

    results = diag.get("results") or {}
    if not results:
        st.warning(diag.get("error") or "Diagnosa kecocokan tidak tersedia.")
        return

    compatible = diag.get("compatible_types") or []
    st.subheader("Kompatibilitas")
    if not compatible:
        st.warning("Belum cocok dengan research pipeline mana pun. Penyebab dan "
                   "langkah perbaikannya per pipeline ada di bawah.")

    for dtype, result in _sorted_results(diag):
        # Satu blok per research pipeline; nama beratribusi ringkas, bukan ID mentah.
        with st.container(border=True):
            st.markdown(get_research_short_label(dtype))
            verdict = _verdict(result)
            headline = f"{_VERDICT_LABEL[verdict]} — {_cause_sentence(diag, dtype, result)}"

            if result.get("compatible"):
                st.success(headline)
                algos = _algorithms_for(dtype)
                if algos:
                    # Kecocokan ditentukan oleh dataset_type; algoritma adalah
                    # pilihan DI DALAM research pipeline yang sama — bukan
                    # pemeriksaan terpisah.
                    st.caption(f"Tersedia {len(algos)} algoritma:")
                    for algo in algos:
                        st.markdown(f"- {algo}")
            else:
                (st.warning if verdict == "near" else st.error)(headline)
                action = _action_sentence(dtype, result)
                if action:
                    st.markdown(action)

            with st.expander("Rincian pemeriksaan", expanded=False):
                _render_check_list(result, dtype)

    if compatible:
        st.caption("Langkah berikutnya: buka halaman Run Experiment, pilih "
                   "berkas ini, lalu pilih research pipeline & algoritma.")


# ── Entry point halaman ───────────────────────────────────────────────────

def render() -> None:
    st.title("Add Pipeline & Dataset")

    mode = st.session_state.get(_MODE_KEY)
    if mode not in ("pipeline", "dataset", "users", "review"):
        _render_choice_boxes()
        return

    if st.button("← Kembali", key="contrib_back"):
        for key in (_MODE_KEY, _RESULT_KEY, _FORM_KEY):
            st.session_state.pop(key, None)
        st.rerun()

    if mode == "pipeline":
        _render_pipeline_flow()
    elif mode == "users":
        _render_users_flow()
    elif mode == "review":
        _render_review_flow()
    else:
        _render_dataset_flow()

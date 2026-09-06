"""
Penyaji pengelolaan pipeline kontribusi — dipakai DI DALAM sub-tampilan
"Peninjauan Pengajuan" pada halaman "Add Pipeline & Dataset".

Ini BUKAN halaman tersendiri. Modul ini hanya menyediakan penyaji: bagian
**Aktif**, **Riwayat versi**, dan **penyunting berkas**. Bagian "Menunggu
tinjauan" tetap milik ``ui/views/contribute.py`` — kartu tinjauannya di sana
sudah lebih lengkap (ia menyediakan pemilih ``dataset_type`` yang dibutuhkan
``approve_submission`` saat metadata pengajuan belum memuatnya), jadi
menggantinya justru akan menghilangkan kemampuan.

Alurnya: pengajuan yang disetujui menjadi pipeline **aktif**, dan tiap
penyuntingan menambah satu baris ke **riwayat versi**. Riwayat itulah bukti
ketertelusuran — setiap eksperimen dapat dilacak ke berkas dan hash yang
benar-benar dipakainya.

Yang perlu diketahui saat membaca berkas ini:

* **Modul ini tidak menegakkan izin.** Ia hanya menyembunyikan kontrol yang
  tidak relevan; penolakan sebenarnya ada di fungsi aksinya
  (``require_approve`` di ``orchestrator/pipeline_versions`` dan
  ``orchestrator/submission_service``). Menyembunyikan tombol tidak pernah
  menjadi satu-satunya penghalang.
* **Kode kontribusi tidak pernah dijalankan di sini.** Sumbernya dibaca sebagai
  TEKS untuk disunting; pemeriksaannya statis. Tidak ada ``import`` maupun
  eksekusi di jalur mana pun pada modul ini.
* **Menyimpan selalu membuat versi baru.** Modul ini tidak punya jalur yang
  menimpa berkas atau baris versi yang sudah ada.
"""
from __future__ import annotations

import logging

import streamlit as st

from ui.i18n import t

from orchestrator.auth_service import AuthError
from orchestrator.dynamic_registry import (
    DynamicRegistryError, get_registered, list_registered,
    set_pipeline_active,
)
from orchestrator.pipeline_versions import (
    PipelineEditError, current_hash, entry_name, experiment_counts,
    package_rejection_reason, read_package, read_source, rejection_reason,
    running_experiments, save_new_version, validate_package, validate_source,
    version_history,
)
from ui.components import grid
from ui.components import registry_view as rv
from ui.components.validator_messages import (
    check_name,
    check_message, error_message,
)
from ui.components.sections import prose, render_facts, render_section

logger = logging.getLogger(__name__)

# Kunci state penyunting. Semuanya berumur satu halaman; tidak ada yang
# menyentuh basis data sampai tombol ditekan.
_EDIT_KEY = "_mp_editing"           # pipeline_id yang sedang disunting
_SOURCE_KEY = "_mp_source"          # isi penyunting
_REPORT_KEY = "_mp_report"          # hasil "Periksa" terakhir
_HISTORY_KEY = "_mp_history"        # nama pipeline yang riwayatnya dibuka
_HISTORY_PICK_KEY = "_mp_hist_pick"  # pemilih pipeline di bagian riwayat

# Perbandingan versi — tampilan TERSENDIRI di dalam bagian "Riwayat versi".
# Seluruhnya baca-saja: tidak satu pun kunci di bawah ini pernah memicu
# penulisan berkas atau baris basis data.
_COMPARE_KEY = "_mp_compare"        # sedang membandingkan?
_CMP_LEFT_KEY = "_mp_cmp_left"      # pipeline_id sisi "versi lama"
_CMP_RIGHT_KEY = "_mp_cmp_right"    # pipeline_id sisi "dibandingkan dengan"
_CMP_FILE_KEY = "_mp_cmp_file"      # berkas yang sedang dibaca diff-nya

# Bagian yang sedang tampil pada sub-tampilan "Peninjauan Pengajuan".
SECTION_PENDING = "Menunggu tinjauan"
SECTION_ACTIVE = "Aktif"
SECTION_HISTORY = "Riwayat versi"
SECTION_KEY = "_mp_section"

#: Dibaca tepat sebelum tombol Simpan pada PENYUNTING — di situlah "menyunting
#: membuat versi baru" benar-benar menjadi keputusan. Ia tidak lagi ikut
#: tergambar di halaman peninjauan: di sana tidak ada yang disunting, jadi
#: kalimat itu hanya menambah paragraf pada halaman yang sudah padat.
NEW_VERSION_NOTE = (
    "Menyunting membuat **versi baru**; versi yang sudah dipakai eksperimen "
    "sebelumnya tidak berubah dan tetap dapat ditelusuri."
)


# ── Pemisahan bagian ────────────────────────────────────────────────────
#
# MEKANISME YANG DIPILIH: segmented control di atas — satu bagian tampil pada
# satu waktu.
#
# Alasannya, dibanding bagian bertumpuk dengan pemisah tebal:
#
# 1. Ketiganya adalah PEKERJAAN yang berbeda, bukan bacaan berurutan. Meninjau
#    antrean, mengelola registry, dan menelusuri riwayat tidak pernah dilakukan
#    bersamaan; menumpuknya hanya memaksa menggulir melewati dua bagian yang
#    tidak sedang dikerjakan.
# 2. Masing-masing bisa PANJANG (satu kartu per pengajuan, satu blok per
#    pipeline, satu baris per versi). Jarak antar-bagian sebesar apa pun tidak
#    menolong bila bagian di atasnya sendiri sudah beberapa layar tingginya —
#    justru itu sebab ketiganya terbaca menyatu sekarang.
# 3. Hanya bagian terpilih yang dirender, jadi biaya membaca basis data ikut
#    turun: memuat "Menunggu tinjauan" tidak lagi menarik seluruh registry.
#
# KEADAAN TIDAK HILANG saat berpindah: seluruh state bagian hidup di
# ``st.session_state`` (pengajuan yang sedang dibuka, isi penyunting, pilihan
# versi yang dibandingkan) dan tidak ada satu pun yang dibuang oleh perpindahan
# — segmented control hanya mengubah `SECTION_KEY`.


#: Urutan baku ketiga bagian.
SECTIONS = (SECTION_PENDING, SECTION_ACTIVE, SECTION_HISTORY)

#: Bagian terakhir yang benar-benar tampil — BUKAN kunci widget, jadi boleh
#: ditulis kapan saja. `SECTION_KEY` sendiri terikat ke segmented control dan
#: hanya boleh disentuh sebelum widgetnya dibuat atau dari dalam callback.
_SECTION_LAST = "_mp_section_last"


#: Pengenal bagian → kunci labelnya. `SECTION_*` di atas adalah PENGENAL yang
#: disimpan di ``session_state`` dan dipakai untuk memilih bagian; ia TIDAK
#: diterjemahkan, sama seperti pengenal halaman. Yang berbahasa hanya labelnya.
SECTION_LABEL_KEYS = {
    SECTION_PENDING: "ap.sec_pending",
    SECTION_ACTIVE: "ap.sec_active",
    SECTION_HISTORY: "ap.sec_history",
}


def section_label(section: str, pending: int, active: int) -> str:
    """Label bagian + PENANDA JUMLAH, supaya isinya terbaca sebelum dibuka."""
    if section == SECTION_PENDING:
        return t("ap.sec_pending", count=pending)
    if section == SECTION_ACTIVE:
        return t("ap.sec_active_n", count=active)
    return t("ap.sec_history")


def goto_section(section: str, **state) -> None:
    """Pindah bagian dari dalam CALLBACK tombol.

    Menulis ``SECTION_KEY`` langsung di badan skrip akan gagal begitu segmented
    control-nya sudah dibuat pada render yang sama ("cannot be modified after
    the widget is instantiated"). Callback berjalan SEBELUM skrip dijalankan
    ulang, jadi di sinilah tempat yang sah untuk memindahkannya.
    """
    st.session_state[SECTION_KEY] = section
    st.session_state[_SECTION_LAST] = section
    for key, value in state.items():
        st.session_state[key] = value


def render_section_switch(pending: int, active: int) -> str:
    """Segmented control pemilih bagian; mengembalikan bagian yang dipilih."""
    last = st.session_state.get(_SECTION_LAST, SECTION_PENDING)
    # Sebelum widget dibuat — sah, dan ini juga yang memulihkan pilihan bila
    # pengguna membatalkan pilihannya (segmented control dapat dilepas).
    if st.session_state.get(SECTION_KEY) not in SECTIONS:
        st.session_state[SECTION_KEY] = last
    chosen = st.segmented_control(
        t("ap.lbl_section"), list(SECTIONS), key=SECTION_KEY,
        format_func=lambda s: section_label(s, pending, active),
        label_visibility="collapsed")
    section = chosen if chosen in SECTIONS else last
    st.session_state[_SECTION_LAST] = section
    return section


# ── Bagian: Aktif ───────────────────────────────────────────────────────

_CONFIRM_OFF_KEY = "_mp_confirm_off"        # pipeline_id yang menunggu konfirmasi


def registry_snapshot() -> dict:
    """Seluruh pipeline kontribusi + angka pemakaiannya, dibaca SEKALI.

    Dikelompokkan per nama supaya versi-versinya dapat disajikan bersama;
    hitungan eksperimen sudah per VERSI karena nomor versi melekat pada
    ``pipeline_id`` yang dicatat tiap eksperimen.
    """
    try:
        rows = list_registered()
    except Exception:                       # pragma: no cover - defensif
        logger.debug("Registry dinamis tidak terbaca", exc_info=True)
        return {"grouped": {}, "counts": {}, "running": {}}

    counts = experiment_counts()
    running = {row["pipeline_id"]: running_experiments(row["pipeline_id"])
               for row in rows}
    return {"grouped": rv.group_versions(rows), "counts": counts,
            "running": running}


def active_rows() -> list[dict]:
    """Ringkasan tiap pipeline kontribusi — aktif maupun tidak.

    Nama fungsinya dipertahankan karena sudah dipakai pemanggil lain; isinya
    kini SELURUH pipeline, dengan bendera ``is_active`` masing-masing, supaya
    yang dinonaktifkan tidak pernah hilang dari pandangan.
    """
    snap = registry_snapshot()
    out = [rv.pipeline_summary(name, versions, snap["counts"],
                               running=snap["running"])
           for name, versions in snap["grouped"].items()]
    out.sort(key=lambda s: (not s["is_active"], s["name"].lower()))
    return out


#: Pipeline terdaftar yang sedang dibuka halamannya. Berawalan `_mp_` sehingga
#: `page_flags.VIEW_STATE_PREFIXES` sudah membuangnya saat pengguna berpindah
#: halaman — tidak perlu mekanisme baru.
_OPEN_PIPELINE_KEY = "_mp_open_pipeline"


def detail_open() -> bool:
    """Apakah sebuah tampilan DALAM sedang menggantikan daftarnya.

    Empat keadaan, semuanya "satu hal pada satu waktu": halaman satu pipeline,
    penyunting berkas, perbandingan versi. Masing-masing menggambar tombol
    kembalinya SENDIRI, jadi pembungkus halaman tidak boleh menggambar tombol
    kembali kedua di atasnya — dua tombol kembali bertumpuk dengan tujuan
    berbeda tidak memberi tahu pembacanya yang mana yang ia maksud.
    """
    return any(st.session_state.get(key) for key in
               (_OPEN_PIPELINE_KEY, _EDIT_KEY, _COMPARE_KEY))


def open_pipeline(pipeline_id: str) -> None:
    """Buka halaman satu pipeline. Dipanggil dari CALLBACK tombol."""
    st.session_state[_OPEN_PIPELINE_KEY] = pipeline_id


def close_pipeline() -> None:
    st.session_state.pop(_OPEN_PIPELINE_KEY, None)
    # Kunci grid diganti, jika tidak barisnya masih tercentang dan halaman
    # yang barusan ditutup langsung terbuka kembali.
    st.session_state[_GRID_NONCE_KEY] =         st.session_state.get(_GRID_NONCE_KEY, 0) + 1


def _render_pipeline_page(summary: dict, user: dict) -> None:
    """Halaman satu pipeline terdaftar: peninjauan PENUH.

    Berbeda dari daftar sebelumnya yang hanya membawa aksi, halaman ini memuat
    kartu peninjauan lengkap — berkas, temuan, langkah uji coba, dan keputusan.
    Pipeline yang sudah terdaftar karena itu dapat ditinjau ulang langsung dari
    sini, tanpa harus dinonaktifkan lebih dulu.

    Menyetujui dari sini menghasilkan VERSI BARU lewat jalur yang sudah ada;
    versi lama tidak pernah ditimpa, dan konvensi yang berlaku (lihat
    ``pipeline_versions.save_new_version``) menonaktifkannya sebagai versi yang
    digantikan.
    """
    st.button(t("ap.btn_back_to_pipelines"), key="mp_back_pipeline",
              on_click=close_pipeline)

    # Blok identitas & aksi yang sudah ada dipakai ulang apa adanya.
    _render_pipeline_block(summary, user)
    _render_delete(summary, user)

    # Kartu peninjauan penuh, bila pipeline ini memang lahir dari sebuah
    # pengajuan. Versi hasil PENYUNTINGAN tidak punya pengajuan — itu fakta,
    # bukan data yang hilang, dan dinyatakan apa adanya.
    submission_id = _submission_of(summary)
    if not submission_id:
        # `prose`, bukan `caption`: ini kalimat penjelasan setara bagian lain
        # di halaman ini, dan kuota teks kecil per halaman = 3.
        prose(t("mp.no_submission_behind"), key="mp_no_submission")
        return

    from orchestrator.submission_service import get_submission

    item = _safe(lambda: get_submission(submission_id), default=_UNREAD)
    if item is _UNREAD:
        prose(t("mp.submission_unreadable"), key="mp_submission_unreadable")
        return
    if not item:
        # Pengajuannya DIHAPUS — keadaan yang berbeda dari "tidak terbaca",
        # dan tindakannya juga berbeda: tidak ada yang perlu diperiksa di log.
        prose(t("mp.submission_deleted"), key="mp_submission_deleted")
        return

    st.divider()
    from ui.views.contribute import render_review_body

    render_review_body(item, user)


#: Naik satu setiap kali halaman pipeline ditutup. Nilainya ikut ke kunci
#: grid, sehingga tabelnya digambar ulang TANPA baris yang masih tercentang di
#: sisi frontend. Tanpa ini, "kembali ke daftar" langsung membuka lagi
#: pipeline yang barusan ditutup — halaman yang tidak dapat ditinggalkan.
_GRID_NONCE_KEY = "_mp_grid_nonce"


def _render_pipeline_grid(summaries: list[dict]) -> None:
    """Daftar pipeline terdaftar: SATU tabel, barisnya dapat dipilih.

    Bentuknya sama persis dengan riwayat eksperimen dan antrean peninjauan —
    lihat `ui.components.grid`. Tidak ada pembacaan disk maupun basis data di
    sini: `active_rows()` sudah menyusun semuanya, jadi menambah pipeline
    tidak menambah pekerjaan berat pada penggambaran daftar.

    Yang nonaktif TIDAK dipisah ke daftar sendiri: `active_rows()` sudah
    mengurutkan yang aktif lebih dulu, dan kolom "Status" menyebut keadaannya
    apa adanya — termasuk sebab sebuah pipeline dianggap rusak. Satu tabel
    berarti kesepuluh pipeline dapat diurutkan dan dibandingkan berdampingan,
    yang justru mustahil ketika keduanya terpisah.
    """
    nonce = st.session_state.get(_GRID_NONCE_KEY, 0)
    chosen = grid.render(rv.ACTIVE_COLUMNS, rv.active_table_rows(summaries),
                         id_key="pipeline_id",
                         key=f"active_pipelines_grid_{nonce}")
    if chosen is not None:
        open_pipeline(chosen)
        st.rerun()


def _render_pipeline_block(summary: dict, user: dict) -> None:
    """Satu pipeline kontribusi: identitas, ketertelusuran, aksi."""
    mark = rv.STATE_MARK.get(summary["state"], "·")
    state_note = "" if summary["state"] == rv.STATE_OK else f" · {summary['state']}"
    status = "aktif" if summary["is_active"] else "nonaktif"
    pipeline_id = summary["pipeline_id"]

    with st.container(border=False, key=f"mp_active_{pipeline_id}"):
        st.markdown(
            f"{mark} **{summary['name']}** · v{summary['version']} · "
            f"`{summary['dataset_type']}` · {status}{state_note}")

        # Berkas versi ini rusak/hilang: dinyatakan apa adanya, tidak
        # ditampilkan seolah normal dan tidak disembunyikan.
        if summary["state"] != rv.STATE_OK:
            st.error(summary["state_reason"])

        left, right = st.columns([3, 2])
        with left:
            render_facts(rv.summary_facts(summary))
        with right:
            st.markdown(f"Hash: `{rv.short_hash(summary['file_hash'])}`",
                        help=summary["file_hash"])
            st.markdown(rv.usage_text(summary))
            st.markdown(f"{summary['version_count']} versi tercatat. "
                        + t(rv.EXPERIMENT_LINK_NOTE_KEY))

        busy = rv.running_text(summary)
        if busy:
            st.warning(busy)

        _render_pipeline_actions(summary, user)


def _render_pipeline_actions(summary: dict, user: dict) -> None:
    pipeline_id = summary["pipeline_id"]
    cols = st.columns([1, 1, 1, 2])

    if summary["is_active"]:
        if cols[0].button(t("action.edit"), key=f"mp_edit_{pipeline_id}",
                          use_container_width=True,
                          help=t("ap.help_edit_new_version")):
            st.session_state[_EDIT_KEY] = pipeline_id
            st.session_state.pop(_SOURCE_KEY, None)
            st.session_state.pop(_REPORT_KEY, None)
            st.rerun()
        if cols[1].button(t("ap.btn_deactivate"), key=f"mp_off_{pipeline_id}",
                          use_container_width=True,
                          help=t(rv.DEACTIVATE_CONSEQUENCE_KEY)):
            st.session_state[_CONFIRM_OFF_KEY] = pipeline_id
            st.rerun()
    else:
        # Nonaktif TETAP TAMPIL, dengan jalan kembali.
        if cols[0].button(t("ap.btn_reactivate"), key=f"mp_on_{pipeline_id}",
                          use_container_width=True,
                          help=t("ap.help_reactivate")):
            try:
                set_pipeline_active(pipeline_id, True, actor=user)
            except (AuthError, DynamicRegistryError) as e:
                st.error(error_message(e))
            except Exception as e:
                # Mengaktifkan menulis ke basis data: kesalahan basis data
                # bukan turunan AuthError maupun DynamicRegistryError, jadi
                # sebelumnya ia lolos sebagai jejak teknis.
                logger.exception("Aktivasi %s gagal tak terduga", pipeline_id)
                st.error(t("ap.err_unexpected", kind=type(e).__name__))
            else:
                st.rerun()

        # Pipeline yang dinonaktifkan sering dinonaktifkan KARENA bermasalah,
        # dan sampai sekarang satu-satunya jalan memperbaikinya adalah menyunting
        # berkasnya. Peninjauan penuh — uji coba, temuan, keputusan — tidak
        # pernah dapat diulang. Di sinilah jalan itu dibuka; versi yang sudah
        # terdaftar TIDAK disentuh.
        _render_reopen(summary, user)

    # Riwayat adalah BAGIAN tersendiri: berpindah ke sana lewat callback,
    # bukan membentang tabel di tengah daftar pipeline.
    cols[2].button(t("ap.btn_history"), key=f"mp_hist_{pipeline_id}",
                   use_container_width=True, on_click=goto_section,
                   args=(SECTION_HISTORY,),
                   kwargs={_HISTORY_KEY: summary["name"],
                           _HISTORY_PICK_KEY: summary["name"],
                           _COMPARE_KEY: False})

    if st.session_state.get(_CONFIRM_OFF_KEY) == pipeline_id:
        _render_deactivate_confirm(summary, user)


def _submission_of(summary: dict):
    """`submission_id` asal keluarga versi ini, atau None.

    Ditelusuri dari versi TERTUA ke terbaru: versi 1 lahir dari persetujuan dan
    membawa pengajuannya; versi berikutnya lahir dari penyuntingan dan tidak.
    """
    versions = summary.get("versions") or []
    ids = [v.get("pipeline_id") for v in versions if isinstance(v, dict)]
    ids.append(summary.get("pipeline_id"))
    for pipeline_id in ids:
        if not pipeline_id:
            continue
        row = _safe(lambda pid=pipeline_id: get_registered(pid))
        if row and row.get("submission_id"):
            return row["submission_id"]
    return None


_CONFIRM_DEL_KEY = "_mp_confirm_delete"


def _render_delete(summary: dict, user: dict) -> None:
    """Tombol "Hapus versi" + konfirmasinya.

    Aturan boleh/tidaknya dijawab ``pipeline_versions.delete_blocker`` — satu
    tempat, dipakai di sini untuk menonaktifkan tombol beserta alasannya dan
    dipakai fungsi aksinya untuk menolak. Menyembunyikan tombol tidak pernah
    menjadi satu-satunya penghalang.
    """
    from orchestrator.pipeline_versions import delete_blocker, delete_version

    pipeline_id = summary["pipeline_id"]
    blocker = _safe(lambda: delete_blocker(pipeline_id))
    # Tidak tahu = TOLAK. Menghapus sesuatu yang mungkin dipakai eksperimen
    # jauh lebih merusak daripada menahan penghapusan yang sebenarnya aman.
    if blocker is None:
        blocker = "mp.delete_blocked_used"

    if st.session_state.get(_CONFIRM_DEL_KEY) == pipeline_id:
        st.warning(t("mp.delete_confirm", name=summary["name"],
                     version=summary["version"]))
        confirm = st.columns([1, 1, 3])
        if confirm[0].button(t("mp.btn_delete_version"),
                             key=f"mp_del_yes_{pipeline_id}", type="primary",
                             use_container_width=True):
            try:
                delete_version(pipeline_id, actor=user)
            except (AuthError, PipelineEditError) as e:
                st.error(error_message(e))
            except Exception as e:
                logger.exception("Penghapusan %s gagal tak terduga", pipeline_id)
                st.error(t("ap.err_unexpected", kind=type(e).__name__))
            else:
                st.session_state.pop(_CONFIRM_DEL_KEY, None)
                close_pipeline()
                st.success(t("mp.msg_version_deleted", name=summary["name"],
                             version=summary["version"]))
                st.rerun()
        if confirm[1].button(t("action.cancel"), key=f"mp_del_no_{pipeline_id}",
                             use_container_width=True):
            st.session_state.pop(_CONFIRM_DEL_KEY, None)
            st.rerun()
        return

    if st.button(t("mp.btn_delete_version"), key=f"mp_del_{pipeline_id}",
                 use_container_width=True, disabled=bool(blocker),
                 help=t(blocker) if blocker else t("mp.delete_confirm",
                                                   name=summary["name"],
                                                   version=summary["version"])):
        st.session_state[_CONFIRM_DEL_KEY] = pipeline_id
        st.rerun()


def _render_reopen(summary: dict, user: dict) -> None:
    """Tombol "Tinjau ulang" pada pipeline yang sedang nonaktif.

    Aturan boleh/tidaknya dijawab ``submission_service.reopen_blocker`` — satu
    tempat, dipakai tampilan untuk menonaktifkan tombol beserta alasannya dan
    dipakai fungsi aksinya untuk menolak. Menyembunyikan tombol tidak pernah
    menjadi satu-satunya penghalang.
    """
    from orchestrator.submission_service import (
        SubmissionError, get_submission, reopen_blocker, reopen_submission,
    )

    # `summary` tidak membawa `submission_id` — ia meringkas registry, bukan
    # antrean. Pengajuannya dicari lewat KELUARGA versi pipeline ini: hanya
    # versi yang lahir dari PERSETUJUAN yang punya `submission_id`; versi hasil
    # penyuntingan tidak, dan itu fakta, bukan data yang hilang.
    submission_id = _submission_of(summary)
    if not submission_id:
        return

    item = _safe(lambda: get_submission(submission_id))
    if not item:
        return

    blocker = reopen_blocker(item)
    if st.button(t("ap.btn_reopen"), key=f"mp_reopen_{summary['pipeline_id']}",
                 use_container_width=True, disabled=bool(blocker),
                 help=t(blocker) if blocker else t("ap.help_reopen")):
        try:
            reopen_submission(submission_id, actor=user)
        except (AuthError, SubmissionError) as e:
            st.error(error_message(e))
        except Exception as e:
            logger.exception("Tinjau ulang pengajuan #%s gagal tak terduga",
                             submission_id)
            st.error(t("ap.err_unexpected", kind=type(e).__name__))
        else:
            st.success(t("ap.msg_reopened", number=submission_id))
            st.rerun()


#: Penanda "pembacaan GAGAL" — dibedakan dari `None`, yang di sini merupakan
#: jawaban yang sah ("pengajuannya sudah dihapus").
_UNREAD = object()


def _safe(fn, *, default=None):
    """Bacaan yang tidak boleh menjatuhkan daftar pipeline."""
    try:
        return fn()
    except Exception:
        logger.exception("Pembacaan gagal pada blok pipeline")
        return default


def _render_deactivate_confirm(summary: dict, user: dict) -> None:
    """Konfirmasi menonaktifkan — konsekuensinya dinyatakan, dan dapat dibatalkan."""
    pipeline_id = summary["pipeline_id"]
    st.warning(f"Nonaktifkan **{summary['name']}** v{summary['version']}? "
               + t(rv.DEACTIVATE_CONSEQUENCE_KEY))
    confirm = st.columns([1, 1, 3])
    if confirm[0].button(t("ap.btn_yes_deactivate"), key=f"mp_off_yes_{pipeline_id}",
                         type="primary", use_container_width=True):
        try:
            set_pipeline_active(pipeline_id, False, actor=user)
        except (AuthError, DynamicRegistryError) as e:
            st.error(error_message(e))
        except Exception as e:
            logger.exception("Penonaktifan %s gagal tak terduga", pipeline_id)
            st.error(t("ap.err_unexpected", kind=type(e).__name__))
        else:
            st.session_state.pop(_CONFIRM_OFF_KEY, None)
            st.rerun()
    if confirm[1].button(t("action.cancel"), key=f"mp_off_no_{pipeline_id}",
                         use_container_width=True):
        st.session_state.pop(_CONFIRM_OFF_KEY, None)
        st.rerun()


def render_active(user: dict) -> None:
    # Penyunting MENGGANTIKAN isi bagian ini — bukan disisipkan di tengah
    # daftar pipeline, tempat isinya akan tertimbun.
    if st.session_state.get(_EDIT_KEY):
        render_editor(user)
        return

    # Halaman SATU pipeline menggantikan daftarnya — bukan disisipkan di
    # tengahnya, mengikuti pola yang sudah dipakai penyunting dan perbandingan
    # versi.
    open_id = st.session_state.get(_OPEN_PIPELINE_KEY)
    if open_id:
        summary = next((r for r in active_rows()
                        if r["pipeline_id"] == open_id), None)
        if summary is None:
            # Sudah tidak terdaftar (baru dihapus/diganti). Kembali ke daftar
            # alih-alih menggambar halaman kosong.
            close_pipeline()
        else:
            _render_pipeline_page(summary, user)
            return

    # Yang dikelola di sini adalah RESEARCH PIPELINE — bawaan maupun
    # kontribusi, aktif maupun tidak. Sebelumnya bagian ini menggambar tabel
    # `registered_pipelines`, yaitu daftar VERSI ALGORITMA milik unggahan saja:
    # HIKARI2021 dan EVE_SURICATA tidak pernah muncul di sana, padahal
    # keduanya research pipeline yang paling banyak dipakai platform ini.
    #
    # Tabel versinya tidak hilang — ia pindah ke halaman satu pipeline, yang
    # dibuka dari kartu research yang bersangkutan.
    from ui.components import research_manage as rs

    render_section("Aktif", help=t("ap.help_active_list"))
    rs.render(user, heading=False)

    # Tabel VERSI algoritma — tetap ada, tetapi bukan lagi tampilan utamanya.
    # Keadaan kosongnya tetap dinyatakan sebagai kalimat: daftar research di
    # atas tidak pernah kosong (bawaan selalu ada), jadi tanpa kalimat ini
    # ketiadaan pipeline kontribusi menjadi tidak terbaca sama sekali.
    summaries = active_rows()
    with st.expander(t("mp.exp_versions"), expanded=False):
        if summaries:
            _render_pipeline_grid(summaries)
        else:
            prose(t(rv.EMPTY_STATE_KEY), key="mp_active_empty")

    # Kolom "Status" menyebut sebuah pipeline nonaktif, tetapi tidak menyebut
    # AKIBATNYA. Ketika yang nonaktif masih punya sub-judul sendiri, kalimat
    # ini melekat di sana; setelah keduanya menjadi satu tabel, ia harus tetap
    # tertulis — jika tidak, "nonaktif" berubah menjadi kata tanpa arti.
    idle = [s for s in summaries if not s["is_active"]]
    if idle:
        prose(t("mp.idle_heading", count=len(idle)), key="mp_idle_note")


# ── Bagian: Riwayat versi ───────────────────────────────────────────────

def history_table(rows: list[dict]) -> str:
    """Riwayat versi sebagai tabel — bukti ketertelusuran.

    Memakai penyaji tabel bersama supaya angka rata kanan, hash penuh di
    tooltip, dan gulir mendatarnya sama dengan tabel lain di aplikasi.
    """
    return rv.history_table_html(rows)


def compare_defaults(rows: list[dict]) -> tuple[dict | None, dict | None]:
    """Pasangan bawaan: versi AKTIF dibandingkan dengan versi SEBELUMNYA.

    ``rows`` terurut terbaru di atas, jadi "sebelumnya" adalah baris SETELAH
    versi aktif. Bila versi aktif adalah yang tertua (baru satu versi), kedua
    sisi sama — dan tampilan menyatakannya identik alih-alih memilih pasangan
    yang menyesatkan.
    """
    if not rows:
        return None, None
    index = next((i for i, r in enumerate(rows) if r.get("active")), 0)
    right = rows[index]
    left = rows[index + 1] if index + 1 < len(rows) else right
    return left, right


def _drop_stale(key: str, options) -> None:
    """Buang nilai widget yang sudah tidak ada di pilihannya.

    Tanpa ini, berpindah pipeline (atau menyimpan versi baru) meninggalkan
    nilai lama di ``session_state`` dan Streamlit menolak merender selectbox-nya
    — halaman gagal total, bukan sekadar salah pilih.
    """
    if key in st.session_state and st.session_state[key] not in options:
        st.session_state.pop(key, None)


def _version_package(row: dict) -> dict[str, str]:
    """Seluruh berkas satu versi, sebagai TEKS. Tidak pernah di-import."""
    try:
        return read_package(row["pipeline_id"])
    except PipelineEditError:
        # Berkas versi hilang/rusak: titik masuk saja, kalau masih terbaca.
        try:
            return {entry_name(row["pipeline_id"]) or "kode.py":
                    read_source(row["pipeline_id"])}
        except PipelineEditError:
            return {}


def _render_compare(rows: list[dict], name: str) -> None:
    """TAMPILAN TERSENDIRI: perbandingan dua versi, baca-saja.

    Menggantikan isi bagian "Riwayat versi" — bukan disisipkan di tengah tabel.
    Tidak ada aksi memulihkan/menerapkan versi di sini, dan tidak ada jalur
    apa pun dari tampilan ini yang menulis ke berkas atau basis data.
    """
    if st.button(t("ap.btn_back_history"), key="mp_cmp_back"):
        st.session_state.pop(_COMPARE_KEY, None)
        st.rerun()

    render_section(f"Bandingkan versi · {name}",
                   help=t("ap.help_compare_readonly"))

    ids = [r["pipeline_id"] for r in rows]
    labels = {r["pipeline_id"]: f"v{r['version']} · {rv.short_hash(r['hash'])}"
              for r in rows}
    left_default, right_default = compare_defaults(rows)
    for key in (_CMP_LEFT_KEY, _CMP_RIGHT_KEY):
        _drop_stale(key, ids)

    pick = st.columns(2)
    left_id = pick[0].selectbox(
        t("ap.lbl_old_version"), ids, key=_CMP_LEFT_KEY,
        index=ids.index(left_default["pipeline_id"]) if left_default else 0,
        format_func=lambda pid: labels.get(pid, pid))
    right_id = pick[1].selectbox(
        t("ap.lbl_compared_with"), ids, key=_CMP_RIGHT_KEY,
        index=ids.index(right_default["pipeline_id"]) if right_default else 0,
        format_func=lambda pid: labels.get(pid, pid))

    left_row = next(r for r in rows if r["pipeline_id"] == left_id)
    right_row = next(r for r in rows if r["pipeline_id"] == right_id)

    left_files = _version_package(left_row)
    right_files = _version_package(right_row)
    index = rv.file_diff_index(left_files, right_files)
    changed = rv.changed_only(index)

    # ── Ringkasan DI ATAS: jumlah baris berubah + hash kedua versi ──────
    total = {"added": sum(e["added"] for e in index),
             "removed": sum(e["removed"] for e in index)}
    render_facts([
        (f"v{left_row['version']}", rv.short_hash(left_row["hash"])),
        (f"v{right_row['version']}", rv.short_hash(right_row["hash"])),
        ("Baris ditambah", f"+{total['added']}"),
        ("Baris dihapus", f"−{total['removed']}"),
        ("Berkas berubah", f"{len(changed)} dari {len(index)}"),
    ])

    if not index:
        st.warning("Berkas kedua versi tidak terbaca — tidak ada yang dapat "
                   "dibandingkan.")
        return

    if not changed:
        st.success(rv.IDENTICAL_NOTE)
        return

    # ── Pemilih berkas: yang identik ditandai, isinya tidak ditampilkan ──
    st.html(rv.file_diff_index_html(index))
    names = [e["name"] for e in changed]
    by_name = {e["name"]: e for e in changed}
    _drop_stale(_CMP_FILE_KEY, names)
    chosen = st.selectbox(
        "Berkas", names, key=_CMP_FILE_KEY,
        format_func=lambda n: rv.file_label(by_name[n]))

    diff = rv.line_rows(left_files.get(chosen, ""), right_files.get(chosen, ""))
    _render_diff(diff, f"v{left_row['version']}", f"v{right_row['version']}")


def _render_diff(diff_rows: list[dict], left_label: str,
                 right_label: str) -> None:
    """Tabel diff + bagian tak berubah yang dapat dibuka."""
    if rv.is_identical(diff_rows):
        st.success(rv.IDENTICAL_NOTE)
        return

    for i, segment in enumerate(rv.collapse_rows(diff_rows)):
        if segment["shown"]:
            st.html(rv.diff_table_html(segment["rows"], left_label, right_label))
            continue
        # Bagian tak berubah yang panjang: disembunyikan, tetapi DAPAT dibuka —
        # tidak ada isi yang hilang, hanya tidak ditampilkan lebih dulu.
        count = len(segment["rows"])
        with st.expander(f"{count} baris tidak berubah"):
            st.html(rv.diff_table_html(segment["rows"], left_label, right_label))


def render_history() -> None:
    """Bagian "Riwayat versi": riwayat VERSI, lalu riwayat TINJAUAN.

    Keduanya menjawab pertanyaan yang sama — "apa yang sudah terjadi" — jadi
    keduanya tinggal di sini. Sebelumnya riwayat tinjauan terdampar di ujung
    tab "Menunggu tinjauan", yaitu tempat orang datang untuk MEMUTUSKAN; yang
    sudah diputuskan justru mengganggu di sana dan hilang dari tempat orang
    benar-benar mencarinya.
    """
    if _render_version_history():       # perbandingan MENGGANTIKAN bagian ini
        return
    _render_review_history()


def _render_version_history() -> bool:
    """Riwayat versi. True bila tampilan perbandingan mengambil alih bagian."""
    render_section("Riwayat versi",
                   help=t("ap.help_history_columns"))

    names = sorted({s["name"] for s in active_rows()})
    name = st.session_state.get(_HISTORY_KEY)
    if name not in names:
        name = names[0] if names else None
    if not name:
        prose(t(rv.EMPTY_STATE_KEY), key="hist_empty")
        return False

    if len(names) > 1:
        _drop_stale(_HISTORY_PICK_KEY, names)
        name = st.selectbox("Pipeline", names, index=names.index(name),
                            key=_HISTORY_PICK_KEY)
    st.session_state[_HISTORY_KEY] = name

    versions = version_history(name)
    if not versions:
        prose(t("mp.history_empty", pipeline=name), key="hist_none")
        return False

    rows = rv.history_rows(versions, experiment_counts())

    # Perbandingan MENGGANTIKAN isi bagian ini, bukan disisipkan di tengahnya
    # — termasuk riwayat tinjauan di bawahnya.
    if st.session_state.get(_COMPARE_KEY):
        _render_compare(rows, name)
        return True

    render_facts([
        ("Pipeline", name),
        ("Versi tercatat", len(rows)),
        ("Aktif", next((f"v{r['version']}" for r in rows if r["active"]), "—")),
    ])
    st.html(history_table(rows))
    # Dua baris pendek, bukan paragraf: ketertelusuran + baca-saja/versi baru.
    prose(f"{t(rv.RETENTION_NOTE_KEY)} {t(rv.READ_ONLY_NOTE_KEY)}",
          key="hist_notes")

    if st.button(t("ap.btn_compare_versions"), key="mp_cmp_open",
                 disabled=len(rows) < 2,
                 help=t("ap.help_show_diff")):
        st.session_state[_COMPARE_KEY] = True
        st.rerun()
    return False


def _render_review_history() -> None:
    """Riwayat TINJAUAN: pengajuan yang sudah diputuskan.

    TABEL, bukan daftar markdown datar. Tiga hal yang SUDAH tersimpan tetapi
    tidak pernah tampil kini ada: kapan diputuskan, siapa yang mengajukan, dan
    bagaimana hasil uji cobanya — justru itu yang dicari saat membaca riwayat,
    dan sebelumnya harus dibuka satu per satu untuk menemukannya.

    Batas 15 DIPERTAHANKAN, bukan diganti paginasi: riwayat dibaca sebagai "apa
    yang terjadi belakangan ini", bukan ditelusuri seperti antrean. Yang lebih
    lama tetap ada di basis data dan tidak dihapus apa pun.
    """
    from database.models import SUBMISSION_PENDING
    from orchestrator.submission_service import list_submissions
    from ui.components import submission_review as sr
    from ui.components import tables as tbl

    st.divider()
    try:
        decided = [s for s in list_submissions()
                   if s["status"] != SUBMISSION_PENDING]
    except Exception:                       # pragma: no cover - defensive
        logger.warning("Riwayat tinjauan tidak terbaca", exc_info=True)
        return

    st.markdown(t("ap.review_history_heading")
                + ("" if decided else t("ap.review_history_empty")))
    if decided:
        tbl.render_table(sr.HISTORY_COLUMNS,
                         sr.history_rows(decided[:15],
                                         status_label=sr.status_label),
                         empty=t("ap.review_history_empty"))


# ── Penyunting berkas ─────────────────────────────────────────────────────
#
# Ini titik PALING BERISIKO pada seluruh fitur: di sinilah kode yang akan
# DIEKSEKUSI platform diubah manusia. Karena itu penyunting menyimpan SIDIK JARI
# isi paket saat "Periksa" ditekan, lalu membandingkannya dengan isi saat ini
# pada setiap render. Begitu isinya berbeda, hasil pemeriksaan dinyatakan TIDAK
# BERLAKU dan tombol simpan mati lagi.
#
# Tanpa itu ada celah nyata: periksa kode bersih -> ubah menjadi berbahaya ->
# simpan. Lapis aksi memang tetap memvalidasi ulang sebelum menulis (jadi
# penyimpanannya tetap ditolak), tetapi tampilan yang mengatakan "lolos" untuk
# kode yang sudah berubah menyesatkan peninjau — dan peninjau adalah pengaman
# terakhir sebelum kode asing dijalankan.

_FINGERPRINT_KEY = "_mp_checked_fingerprint"    # isi paket saat terakhir diperiksa
_PACKAGE_KEY = "_mp_package"                    # {nama berkas: teks} yang disunting
_ACTIVE_FILE_KEY = "_mp_active_file"            # berkas yang sedang disunting
_REVERT_KEY = "_mp_confirm_revert"              # menunggu konfirmasi kembalikan

STATUS_UNCHECKED = "belum diperiksa"
STATUS_STALE = "kode berubah sejak diperiksa"
STATUS_PASS = "lolos"
STATUS_FAIL = "gagal"

FINDING_NOTE = (
    "Temuan **menggagalkan** harus diperbaiki sebelum dapat disimpan; "
    "**peringatan** tidak menghalangi penyimpanan tetapi sebaiknya dibaca."
)
UNSAVED_NOTE = "Ada perubahan yang belum disimpan."
REVERT_WARNING = (
    "Kembalikan seluruh berkas ke isi versi aktif? Suntingan yang belum "
    "disimpan akan hilang."
)


def package_fingerprint(files: dict) -> str:
    """Sidik jari isi paket — dasar penilaian 'masih berlaku atau tidak'.

    Memakai SHA-256 atas nama+isi tiap berkas, urut nama, sehingga perubahan
    sekecil apa pun (termasuk pada berkas pendukung) mengubah nilainya.
    """
    import hashlib

    digest = hashlib.sha256()
    for name in sorted(files or {}):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update((files[name] or "").encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def check_status(files: dict, report, fingerprint) -> str:
    """Keadaan pemeriksaan SAAT INI, bukan saat tombol ditekan."""
    if report is None:
        return STATUS_UNCHECKED
    if fingerprint != package_fingerprint(files):
        return STATUS_STALE
    return STATUS_PASS if report.get("valid") else STATUS_FAIL


def save_blocker(files: dict, report, fingerprint, note: str) -> str:
    """Alasan tombol simpan nonaktif; "" bila boleh disimpan.

    Alasannya SELALU dinyatakan — tombol yang mati tanpa keterangan membuat
    pengguna menebak.
    """
    status = check_status(files, report, fingerprint)
    if status == STATUS_UNCHECKED:
        return "Belum diperiksa — tekan **Periksa** dulu."
    if status == STATUS_STALE:
        return ("Kode berubah setelah diperiksa, jadi hasil pemeriksaan "
                "sebelumnya tidak berlaku lagi. Tekan **Periksa** ulang.")
    if status == STATUS_FAIL:
        return package_rejection_reason(report)
    if not (note or "").strip():
        return "Isi catatan perubahan dulu."
    return ""


def changed_files(files: dict, original: dict) -> list[str]:
    """Berkas yang isinya berbeda dari versi aktif."""
    return sorted(name for name, text in (files or {}).items()
                  if text != (original or {}).get(name))


def _file_label(name: str, entry: str, files: dict, original: dict) -> str:
    role = "titik masuk" if name == entry else "pendukung"
    mark = " •" if (files or {}).get(name) != (original or {}).get(name) else ""
    return f"{name} · {role}{mark}"


def _load_package(pipeline_id: str) -> tuple[dict, dict, str]:
    """(isi yang disunting, isi versi aktif, nama titik masuk)."""
    original = read_package(pipeline_id)
    entry = entry_name(pipeline_id)
    stored = st.session_state.get(_PACKAGE_KEY)
    if not isinstance(stored, dict) or set(stored) != set(original):
        # Isi penyunting BERTAHAN antar-interaksi; hanya disemai ulang saat
        # penyunting baru dibuka atau daftar berkasnya memang berbeda.
        stored = dict(original)
        st.session_state[_PACKAGE_KEY] = stored
    return stored, original, entry


def _render_findings(reviewed: dict) -> None:
    """Temuan dipisah: MENGGAGALKAN vs PERINGATAN, dengan kutipan barisnya."""
    files = (reviewed or {}).get("files") or []
    failing, warning = [], []
    for entry in files:
        source_lines = (entry.get("source") or "").splitlines()
        for check in (entry.get("report") or {}).get("checks") or []:
            if check.get("status") not in ("fail", "warn"):
                continue
            line = check.get("line")
            quote = ""
            if isinstance(line, int) and 1 <= line <= len(source_lines):
                quote = source_lines[line - 1].strip()
            row = {"file": entry.get("filename", ""), "line": line,
                   "name": check.get("name", ""),
                   "message": check.get("message", ""), "quote": quote}
            (failing if check["status"] == "fail" else warning).append(row)

    if not failing and not warning:
        return
    st.markdown(FINDING_NOTE)
    for title, rows in (("Menggagalkan", failing), ("Peringatan", warning)):
        if not rows:
            continue
        st.markdown(f"**{title} ({len(rows)})**")
        for row in rows:
            where = f"`{row['file']}`"
            if row["line"]:
                where += f" baris **{row['line']}**"
            st.markdown(f"- {where} — {row['message']}")
            if row["quote"]:
                st.code(f"{row['line']} | {row['quote']}", language="python")


def render_editor(user: dict) -> None:
    pipeline_id = st.session_state.get(_EDIT_KEY)
    if not pipeline_id:
        return

    # Penyunting adalah tampilan TERSENDIRI yang menggantikan isi bagian
    # "Aktif"; jalan kembalinya harus terlihat lebih dulu, bukan tersembunyi
    # di bawah kode.
    # Hanya penanda "sedang menyunting" yang dilepas — ISI penyunting sengaja
    # dibiarkan di sesi, jadi keluar dari tampilan ini tidak membuang pekerjaan
    # yang belum disimpan.
    if st.button("← Kembali ke daftar aktif", key="mp_edit_back",
                 help=t("ap.help_unsaved_kept")):
        st.session_state.pop(_EDIT_KEY, None)
        st.rerun()

    render_section(t("ap.sec_editor"),
                   help=t("ap.help_check_first"))

    try:
        files, original, entry = _load_package(pipeline_id)
    except PipelineEditError as e:
        st.error(error_message(e))
        if st.button(t("ap.btn_close_editor"), key="mp_edit_close_err"):
            _clear_editor()
            st.rerun()
        return

    from orchestrator.dynamic_registry import get_registered
    item = get_registered(pipeline_id) or {}
    report = st.session_state.get(_REPORT_KEY)
    fingerprint = st.session_state.get(_FINGERPRINT_KEY)
    status = check_status(files, report, fingerprint)
    changed = changed_files(files, original)

    # Kode & hasil pemeriksaan berdampingan pada layar lebar; aturan kolom
    # menumpuk yang sudah dibakukan membuatnya bertumpuk pada layar sempit.
    left, right = st.columns([3, 2])

    with left:
        names = sorted(files, key=lambda n: (n != entry, n.lower()))
        chosen = st.selectbox(
            "Berkas", names, key=_ACTIVE_FILE_KEY,
            format_func=lambda n: _file_label(n, entry, files, original),
            help=t("ap.help_entry_first"))
        chosen = chosen or entry

        edited = st.text_area(
            t("ap.lbl_pipeline_code"), value=files.get(chosen, ""), height=460,
            key=f"mp_src_{chosen}", label_visibility="collapsed")
        # Isi disimpan kembali ke paket supaya bertahan antar-interaksi dan
        # antar-perpindahan berkas.
        files[chosen] = edited
        st.session_state[_PACKAGE_KEY] = files

    with right:
        render_facts([
            ("Pipeline", pipeline_id),
            ("Versi aktif", f"v{item.get('version', '?')}"),
            ("Hash aktif", rv.short_hash(current_hash(pipeline_id) or "")),
            ("Kelas titik masuk", item.get("entry_class") or ""),
            ("Jenis dataset", item.get("dataset_type") or ""),
            ("Berkas", f"{len(files)} berkas"),
        ])
        st.markdown(NEW_VERSION_NOTE)

        inflight = running_experiments(pipeline_id)
        if inflight:
            st.warning(
                f"{inflight} eksperimen sedang BERJALAN memakai versi ini. "
                f"Menyimpan versi baru tidak mengubahnya — eksekusi itu sudah "
                f"memuat berkas versi lama, yang tetap tersimpan.")

        if changed:
            st.warning(f"{UNSAVED_NOTE} Berkas berubah: "
                       + ", ".join(f"`{n}`" for n in changed))

        st.markdown(f"Status pemeriksaan: **{status}**.")
        if st.button("Periksa", key="mp_check", use_container_width=True,
                     help=t("ap.help_static_only")):
            # Divalidasi dari TEKS di penyunting, seluruh paket. Tidak di-import.
            st.session_state[_REPORT_KEY] = validate_package(files)
            st.session_state[_FINGERPRINT_KEY] = package_fingerprint(files)
            st.rerun()

        if status == STATUS_PASS:
            st.success(t("ap.msg_validation_passed"))
        elif status == STATUS_FAIL:
            st.error(t("ap.msg_validation_failed"))
        elif status == STATUS_STALE:
            st.warning("Hasil pemeriksaan sebelumnya tidak berlaku lagi karena "
                       "kode berubah.")

        if status in (STATUS_PASS, STATUS_FAIL):
            _render_findings(report)

    note = st.text_input(t("ap.lbl_change_note"), key="mp_change_note",
                         placeholder=t("ap.help_change_note"))

    blocked = save_blocker(files, report, fingerprint, note)
    cols = st.columns([2, 1, 1, 2])
    if cols[0].button(t("ap.btn_save_version"), type="primary",
                      key="mp_save", use_container_width=True,
                      disabled=bool(blocked), help=blocked or NEW_VERSION_NOTE):
        try:
            created = save_new_version(pipeline_id, files=files,
                                       change_note=note, actor=user)
        except (AuthError, PipelineEditError) as e:
            st.error(error_message(e))
        except Exception as e:
            # Menyimpan versi menulis BERKAS dan basis data, lalu
            # mendaftarkannya: OSError, kesalahan basis data, dan
            # DynamicRegistryError semuanya mungkin dan tidak tertangkap di
            # atas. Versi lama tidak pernah ditimpa, jadi kegagalan di sini
            # tidak merusak apa pun yang sudah tersimpan.
            logger.exception("Penyimpanan versi baru %s gagal tak terduga",
                             pipeline_id)
            st.error(t("ap.err_unexpected", kind=type(e).__name__))
        else:
            st.success(
                f"Tersimpan sebagai **v{created['version']}** "
                f"(`{created['pipeline_id']}`), hash "
                f"`{rv.short_hash(created['file_hash'])}` — versi ini kini "
                f"aktif. Versi sebelumnya tetap tersimpan.")
            # Penyunting dibuka ulang pada versi BARU sebagai keadaan awal,
            # jadi tidak menyisakan penanda "belum disimpan".
            _clear_editor()
            st.session_state[_EDIT_KEY] = created["pipeline_id"]
            st.rerun()

    if cols[1].button(t("ap.btn_revert"), key="mp_revert",
                      use_container_width=True,
                      help=t("ap.help_revert_all")):
        st.session_state[_REVERT_KEY] = True
        st.rerun()
    # Tidak ada tombol "Tutup" kedua di sini: jalan keluarnya SATU, yaitu
    # "← Kembali ke daftar aktif" di atas. Dua tombol dengan perilaku sama
    # hanya membuat pengguna menebak bedanya.

    if blocked:
        st.markdown(f"Tombol simpan nonaktif — {blocked}")

    if st.session_state.get(_REVERT_KEY):
        _render_revert_confirm(original)


def _render_revert_confirm(original: dict) -> None:
    st.warning(REVERT_WARNING)
    cols = st.columns([1, 1, 3])
    if cols[0].button(t("ap.btn_yes_revert"), key="mp_revert_yes", type="primary",
                      use_container_width=True):
        st.session_state[_PACKAGE_KEY] = dict(original)
        for name in original:
            st.session_state.pop(f"mp_src_{name}", None)
        st.session_state.pop(_REPORT_KEY, None)
        st.session_state.pop(_FINGERPRINT_KEY, None)
        st.session_state.pop(_REVERT_KEY, None)
        st.rerun()
    if cols[1].button(t("action.cancel"), key="mp_revert_no", use_container_width=True):
        st.session_state.pop(_REVERT_KEY, None)
        st.rerun()


def _clear_editor() -> None:
    """Buang seluruh state penyunting — dipakai setelah menyimpan/menutup."""
    package = st.session_state.get(_PACKAGE_KEY) or {}
    for name in package:
        st.session_state.pop(f"mp_src_{name}", None)
    for key in (_EDIT_KEY, _SOURCE_KEY, _REPORT_KEY, _FINGERPRINT_KEY,
                _PACKAGE_KEY, _ACTIVE_FILE_KEY, _REVERT_KEY, "mp_change_note"):
        st.session_state.pop(key, None)


def _render_report(report) -> None:
    """Rincian pemeriksaan satu berkas — dipakai jalur validasi berkas tunggal."""
    checks = list(getattr(report, "checks", []))
    if not checks:
        return
    lines = [f"| | {t('mp.col_check')} | {t('mp.col_line')} | "
             f"{t('mp.col_detail')} |", "| --- | --- | --- | --- |"]
    mark = {"pass": "✔", "warn": "⚠", "fail": "✖"}
    for check in checks:
        status = getattr(check, "status", "")
        if status == "pass":
            continue                        # yang lolos tidak perlu dibaca
        line = getattr(check, "line", None)
        lines.append(f"| {mark.get(status, '·')} | {check_name(check)} | "
                     f"{line if line else '—'} | {check_message(check)} |")
    if len(lines) > 2:
        st.markdown("\n".join(lines))

"""Kelola research pipeline dari tempat ia benar-benar dipakai.

Halaman Jalankan Eksperimen adalah tempat seseorang MELIHAT sebuah research
pipeline dan algoritmanya. Sampai sekarang, mematikan salah satunya berarti
meninggalkan halaman ini, membuka Add Pipeline & Dataset, mencari pipeline yang
sama di daftar lain, lalu kembali. Perjalanan itu tidak menambah pengaman apa
pun — ia hanya membuat tindakan yang wajar terasa jauh.

Dua tingkat sengaja DIBEDAKAN, karena akibatnya berbeda:

* **satu algoritma** — sisanya tetap dapat dipilih;
* **research pipeline utuh** — seluruh algoritmanya sekaligus.

Menonaktifkan algoritma terakhir yang masih hidup menghasilkan akibat yang sama
dengan mematikan research pipeline-nya, tetapi tanpa pernah menyatakannya.
Karena itu jalan itu ditutup dan yang ditawarkan adalah tombol yang menyebut
maksudnya (lihat ``dynamic_registry.last_active_algorithm_blocker``).

Lapis TAMPILAN saja: setiap aksi di sini memanggil fungsi yang memeriksa
izinnya sendiri, jadi menyembunyikan tombol tidak pernah menjadi satu-satunya
penghalang.
"""
from __future__ import annotations

import logging

import streamlit as st

from database.models import is_uploaded_research
from ui.components.sections import prose, render_section
from ui.i18n import t

logger = logging.getLogger(__name__)

#: Konfirmasi hapus yang tertunda, per pipeline_id.
_CONFIRM_KEY = "_re_confirm_delete"


def algorithm_label(row: dict) -> str:
    """Satu algoritma sebagaimana dibaca manusia: nama, versi, keadaannya."""
    algo = (row.get("algorithm") or row.get("name") or "").strip() or "—"
    state = t("rv.status_active") if row.get("active") else t("rv.status_inactive")
    return f"{algo} · v{row.get('version')} · {state}"


def _readonly_note(dataset_type: str) -> bool:
    """True bila research pipeline ini BAWAAN — dan alasannya sudah tergambar.

    Bawaan tidak dikelola dari sini: ia pembanding tetap penelitian ini, dan
    kodenya tidak disunting. Itu dikatakan, bukan disembunyikan — halaman yang
    diam-diam tidak menawarkan apa pun membuat orang mengira platformnya rusak.
    """
    if is_uploaded_research(dataset_type):
        return False
    prose(t("re.msg_builtin_readonly"), key="re_builtin_readonly")
    return True


def render(dataset_type: str, user: dict | None) -> None:
    """Panel Research Admin untuk satu research pipeline."""
    from orchestrator.auth_service import can_approve

    if not can_approve(user):
        return                                  # bukan haknya: tidak digambar

    render_section(t("re.sec_manage"), help=t("re.help_manage"))
    if _readonly_note(dataset_type):
        return

    from orchestrator import dynamic_registry as dr

    try:
        rows = dr.research_algorithms(dataset_type)
    except Exception:                           # pragma: no cover - defensive
        logger.warning("Daftar algoritma %s tidak terbaca", dataset_type,
                       exc_info=True)
        prose(t("err.research_not_found", research=dataset_type),
              key="re_manage_unreadable")
        return

    if not rows:
        prose(t("err.research_not_found", research=dataset_type),
              key="re_manage_empty")
        return

    live = sum(1 for r in rows if r.get("active"))
    _render_research_switch(dataset_type, rows, live, user)
    st.markdown(t("re.lbl_algorithm_state", live=live, total=len(rows)))
    for row in rows:
        _render_algorithm(row, user)
    prose(t("re.msg_edit_elsewhere"), key="re_edit_elsewhere")


def _render_research_switch(dataset_type: str, rows: list[dict], live: int,
                            user: dict | None) -> None:
    """Satu tombol untuk SELURUH research pipeline."""
    from orchestrator import dynamic_registry as dr

    turning_off = live > 0
    label = t("re.btn_research_off" if turning_off else "re.btn_research_on")
    if not st.button(label, key=f"re_research_toggle_{dataset_type}",
                     use_container_width=True):
        return
    try:
        changed = dr.set_research_active(dataset_type, not turning_off,
                                         actor=user)
    except Exception as e:
        st.error(_message(e))
        return
    st.success(t("re.msg_research_off" if turning_off else "re.msg_research_on",
                 research=dataset_type, count=len(changed)))
    st.rerun()


def _render_algorithm(row: dict, user: dict | None) -> None:
    """Satu baris algoritma: keadaannya, lalu aksinya."""
    from orchestrator import dynamic_registry as dr
    from orchestrator.pipeline_versions import delete_blocker, delete_version

    pipeline_id = row["pipeline_id"]
    cols = st.columns([4, 2, 2])
    cols[0].markdown(algorithm_label(row))

    active = bool(row.get("active"))
    # Alasan tombol nonaktif SELALU dinyatakan — tombol mati tanpa keterangan
    # membuat pengguna menebak apa yang kurang.
    blocked = _safe(dr.last_active_algorithm_blocker, pipeline_id) if active else ""
    if cols[1].button(t("re.btn_algorithm_on" if not active
                        else "re.btn_algorithm_off"),
                      key=f"re_algo_toggle_{pipeline_id}",
                      use_container_width=True,
                      disabled=bool(blocked),
                      help=t(blocked) if blocked else None):
        try:
            dr.set_pipeline_active(pipeline_id, not active, actor=user)
        except Exception as e:
            st.error(_message(e))
        else:
            st.success(t("re.msg_algorithm_off" if active
                         else "re.msg_algorithm_on",
                         algorithm=row.get("algorithm") or row.get("name") or
                         pipeline_id))
            st.rerun()

    stop = _safe(delete_blocker, pipeline_id)
    if cols[2].button(t("re.btn_delete_algorithm"),
                      key=f"re_algo_delete_{pipeline_id}",
                      use_container_width=True,
                      disabled=bool(stop), help=t(stop) if stop else None):
        st.session_state[_CONFIRM_KEY] = pipeline_id
        st.rerun()

    if st.session_state.get(_CONFIRM_KEY) == pipeline_id:
        _render_delete_confirm(row, user, delete_version)


def _render_delete_confirm(row: dict, user: dict | None, delete_version) -> None:
    """Menghapus membuang baris registry DAN berkasnya — jadi ia ditanyakan."""
    st.warning(t("mp.delete_confirm", name=row.get("name"),
                 version=row.get("version")))
    cols = st.columns(2)
    if cols[0].button(t("action.delete"), type="primary",
                      key=f"re_algo_delete_yes_{row['pipeline_id']}",
                      use_container_width=True):
        try:
            delete_version(row["pipeline_id"], actor=user)
        except Exception as e:
            st.error(_message(e))
        else:
            st.session_state.pop(_CONFIRM_KEY, None)
            st.success(t("mp.msg_version_deleted", name=row.get("name"),
                         version=row.get("version")))
            st.rerun()
    if cols[1].button(t("action.cancel"),
                      key=f"re_algo_delete_no_{row['pipeline_id']}",
                      use_container_width=True):
        st.session_state.pop(_CONFIRM_KEY, None)
        st.rerun()


def _safe(fn, *args):
    """Penghalang yang tidak terbaca berarti MENUTUP, bukan membuka.

    Pola fail-closed yang sama dipakai gerbang persetujuan: "tidak tahu apakah
    boleh" tidak pernah berarti "boleh".
    """
    try:
        return fn(*args)
    except Exception:                           # pragma: no cover - defensive
        logger.warning("Penghalang tidak terbaca untuk %s", args, exc_info=True)
        return "ap.err_gate_unreadable"


def _message(error: Exception) -> str:
    from ui.components.validator_messages import error_message

    return error_message(error)

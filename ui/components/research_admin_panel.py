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
from html import escape

import streamlit as st

from database.models import is_uploaded_research
from ui.components import code_box
from ui.components import grid
from ui.components.pipeline_upload import ROLE_ENTRY
from ui.components.tables import human_datetime
from ui.components.sections import prose, render_section
from ui.components.theme import dark_button_scope
from ui.i18n import t

logger = logging.getLogger(__name__)

#: Konfirmasi hapus yang tertunda, per pipeline_id.
#: Berawalan `_rs_` supaya `page_flags.VIEW_STATE_PREFIXES` ikut
#: membuangnya saat pengguna berpindah halaman: konfirmasi hapus yang
#: tertinggal terbuka menyambut pengguna berikutnya dengan pertanyaan
#: tentang versi yang tidak sedang ia lihat.
_CONFIRM_KEY = "_rs_confirm_delete"


def algorithm_label(row: dict) -> str:
    """Satu algoritma sebagaimana dibaca manusia: nama, versi, keadaannya."""
    algo = (row.get("algorithm") or row.get("name") or "").strip() or "-"
    state = t("rv.status_active") if row.get("active") else t("rv.status_inactive")
    return f"{algo} · v{row.get('version')} · {state}"


def _is_builtin(dataset_type: str) -> bool:
    """True bila research pipeline ini BAWAAN, jadi panelnya tidak digambar.

    Dahulu fungsi ini juga MENGGAMBAR kalimat yang menjelaskan kenapa tidak
    ada apa pun yang ditawarkan. Kalimat itu dicabut; yang menggantikannya
    bukan judul dengan isi kosong, melainkan tidak ada panel sama sekali —
    judul yang berdiri sendiri tanpa isi justru terbaca seperti sesuatu yang
    gagal dimuat, dan itu lebih buruk daripada keduanya.
    """
    return not is_uploaded_research(dataset_type)


def render(dataset_type: str, user: dict | None) -> None:
    """Panel Research Admin untuk satu research pipeline."""
    from orchestrator.auth_service import can_approve

    if not can_approve(user):
        return                                  # bukan haknya: tidak digambar

    # Bawaan diperiksa SEBELUM judulnya digambar: tidak ada yang dapat
    # dikelola di sini untuknya, jadi yang benar adalah tidak menggambar
    # apa-apa — bukan judul yang isinya kosong.
    if _is_builtin(dataset_type):
        return

    render_section(t("re.sec_manage"), help=t("re.help_manage"))

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


def _render_research_switch(dataset_type: str, rows: list[dict], live: int,
                            user: dict | None) -> None:
    """Satu tombol untuk SELURUH research pipeline."""
    from orchestrator import dynamic_registry as dr

    turning_off = live > 0
    label = t("re.btn_research_off" if turning_off else "re.btn_research_on")
    # Hitam HANYA saat ia mematikan. Menyalakan kembali tidak menghilangkan
    # apa pun dari pilihan orang lain; mematikan iya.
    with dark_button_scope(st, dark=turning_off, key=f"rr_{dataset_type}"):
        ditekan = st.button(label, key=f"re_research_toggle_{dataset_type}",
                            use_container_width=True)
    if not ditekan:
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


#: Versi yang paketnya sedang disunting. Berawalan `_rs_` supaya
#: `page_flags.VIEW_STATE_PREFIXES` ikut membuangnya saat pengguna berpindah
#: halaman: penyunting yang tertinggal terbuka akan menyambut pengguna
#: berikutnya dengan layar yang bukan miliknya.
_EDIT_KEY = "_rs_edit_package"


def _render_algorithm(row: dict, user: dict | None) -> None:
    """Satu baris algoritma: keadaannya, lalu aksinya."""
    from orchestrator import dynamic_registry as dr
    from orchestrator.pipeline_versions import delete_blocker, delete_version

    pipeline_id = row["pipeline_id"]
    cols = st.columns([4, 2, 2, 2, 2])
    cols[0].markdown(algorithm_label(row))

    active = bool(row.get("active"))
    # Alasan tombol nonaktif SELALU dinyatakan — tombol mati tanpa keterangan
    # membuat pengguna menebak apa yang kurang.
    blocked = _safe(dr.last_active_algorithm_blocker, pipeline_id) if active else ""
    with dark_button_scope(cols[1], dark=active, key=f"ra_{pipeline_id}"):
        matikan = st.button(t("re.btn_algorithm_on" if not active
                              else "re.btn_algorithm_off"),
                            key=f"re_algo_toggle_{pipeline_id}",
                            use_container_width=True,
                            disabled=bool(blocked),
                            help=t(blocked) if blocked else None)
    if matikan:
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

    # Dua aksi yang layanannya lengkap tetapi kehilangan pemicunya ketika
    # halaman satu-pipeline dicabut: menyunting paket menjadi versi baru, dan
    # meninjau ulang pengajuannya. Keduanya kembali DI SINI, di baris algoritma
    # yang memang menjadi tempat aksi lain algoritma itu.
    if cols[3].button(t("re.btn_edit_package"),
                      key=f"re_algo_edit_{pipeline_id}",
                      use_container_width=True,
                      help=t("re.help_edit_package")):
        st.session_state[_EDIT_KEY] = pipeline_id
        st.rerun()

    _render_reopen(row, user, cols[4])
    _render_info_refresh(row, user)

    # Urutannya mengikuti urutan pekerjaannya: menyunting paket, lalu menguji
    # apa yang baru disunting, lalu membaca apa yang sudah pernah diubah.
    # Ketiganya hanya digambar untuk algoritma yang memang sedang dibuka —
    # tiga algoritma berarti tiga kali tabel ini, dan tidak satu pun dibaca.
    if st.session_state.get(_EDIT_KEY) == pipeline_id:
        _render_package_editor(row, user)
        _render_testing(row, user)
        _render_version_history(row, user)
    if st.session_state.get(_CONFIRM_KEY) == pipeline_id:
        _render_delete_confirm(row, user, delete_version)


def _render_reopen(row: dict, user: dict | None, kolom) -> None:
    """Kembalikan pengajuannya ke antrean tinjauan.

    Sampai sekarang persetujuan adalah keadaan akhir: yang tersedia hanya
    menyalakan/mematikan dan menyunting berkasnya. Peninjauan penuh, dengan uji
    coba dan keputusannya, tidak pernah dapat diulang, padahal justru itu yang
    dibutuhkan ketika sebuah pipeline dinonaktifkan karena bermasalah.

    Penghalangnya dibaca dari lapis aksi yang sama yang akan menolaknya nanti,
    jadi tombol yang mati selalu menyebutkan sebabnya.
    """
    from orchestrator.submission_service import (
        get_submission, reopen_blocker, reopen_submission,
    )

    sid = row.get("submission_id")
    if not sid:
        # Versi yang lahir dari penyuntingan, bukan dari pengajuan: tidak ada
        # pengajuan yang dapat ditinjau ulang.
        return
    item, _ = _safe_data(get_submission, sid)
    stop = _safe(reopen_blocker, item) if item else "ap.reopen_not_approved"
    if kolom.button(t("re.btn_reopen"), key=f"re_algo_reopen_{pipeline_id_of(row)}",
                    use_container_width=True, disabled=bool(stop),
                    help=t(stop) if stop else t("re.help_reopen")):
        try:
            reopen_submission(sid, actor=user)
        except Exception as e:
            st.error(_message(e))
        else:
            st.success(t("re.msg_reopened", number=sid))
            st.rerun()


def pipeline_id_of(row: dict) -> str:
    return str(row.get("pipeline_id") or "")


#: Suntingan TERTUNDA per pipeline: {pipeline_id: {nama berkas: teks}}.
#:
#: Tanpa ini, menyunting berkas A lalu berpindah ke berkas B dan menyimpan
#: membuang suntingan A TANPA SUARA: penyimpan hanya menerima berkas yang
#: sedang dipilih. Pola dan alasannya sama persis dengan layar penyuntingan
#: pengajuan (`_DRAFT_KEY` pada `ui/views/contribute.py`).
_DRAFT_KEY = "_rs_source_draft"

#: Berkas yang SEDANG dibuka per pipeline. Diperlukan saat berpindah berkas:
#: kunci radio sudah berisi nilai BARU ketika `on_change` berjalan, jadi nama
#: berkas yang ditinggalkan harus diingat sendiri.
_FILE_KEY = "_rs_edit_file"


def _draft_of(pipeline_id: str) -> dict:
    """Suntingan tertunda milik satu pipeline."""
    return st.session_state.get(_DRAFT_KEY, {}).get(str(pipeline_id), {})


def _stash_edit(pipeline_id: str, filename: str, asli: dict) -> None:
    """Simpan isi kotak berkas yang DITINGGALKAN ke suntingan tertunda.

    Yang isinya kembali sama dengan aslinya DIBUANG dari daftar, bukan
    disimpan sebagai suntingan kosong: berkas yang tercatat "disunting"
    padahal tidak berubah membuat penanda jumlah suntingan berbohong.
    """
    if not filename:
        return
    kunci = f"re_edit_box_{pipeline_id}_{filename}"
    if kunci not in st.session_state:
        return
    teks = code_box.current_text(kunci, asli.get(filename, ""))
    draft = st.session_state.setdefault(_DRAFT_KEY, {}).setdefault(
        str(pipeline_id), {})
    if teks == asli.get(filename):
        draft.pop(filename, None)
    else:
        draft[filename] = teks


def _forget_drafts(pipeline_id: str) -> None:
    """Buang suntingan tertunda sesudah tersimpan atau dibatalkan."""
    st.session_state.get(_DRAFT_KEY, {}).pop(str(pipeline_id), None)
    st.session_state.get(_FILE_KEY, {}).pop(str(pipeline_id), None)


#: Fase bawaan, dibaca dari tempat yang SAMA dengan halaman pengajuan supaya
#: kedua layar tidak pernah menawarkan daftar fase yang berbeda.
def _phase_options() -> list:
    from ui.components.submission_review import DEFAULT_PHASES

    return list(DEFAULT_PHASES)


def _class_names(files: dict) -> set:
    """Nama kelas yang benar-benar ada di paket, dibaca STATIS dengan `ast`.

    Tidak pernah mengimpor berkasnya: aturan yang sama dengan seluruh jalur
    peninjauan.
    """
    import ast

    keluar: set = set()
    for teks in (files or {}).values():
        try:
            pohon = ast.parse(teks or "")
        except SyntaxError:
            continue
        for simpul in ast.walk(pohon):
            if isinstance(simpul, ast.ClassDef):
                keluar.add(simpul.name)
    return keluar


def disunting_awal(pipeline_id: str) -> dict:
    """Suntingan tertunda, dibaca saat menghitung daftar kelas yang tersedia.

    Kelas yang BARU diketik pada berkas yang belum disimpan harus ikut dapat
    dipilih; kalau tidak, menambah kelas dan menunjuknya sebagai titik masuk
    menjadi dua penyimpanan yang terpisah.
    """
    return _draft_of(pipeline_id)


def _placement_now(row: dict) -> list:
    """Penempatan berkas yang TERSIMPAN pada baris versi ini."""
    import json

    mentah = row.get("info_json")
    if isinstance(mentah, str):
        try:
            mentah = json.loads(mentah)
        except (TypeError, ValueError):
            mentah = {}
    berkas = (mentah or {}).get("file_placement")
    return berkas if isinstance(berkas, list) else []


def _render_placement_fields(pipeline_id: str, row: dict,
                             berkas: dict) -> list:
    """Fase tiap berkas, beserta penanda "dipakai semua algoritma".

    Bentuk yang disimpan sama persis dengan yang ditulis jalur persetujuan
    (`submission_service._info_extra_for`): satu entri per berkas, berisi
    nama, daftar fase, dan `shared`. Menyimpannya dalam bentuk lain akan
    membuat katalog membaca peta yang tidak dikenalinya.
    """
    tersimpan = {str(e.get("filename") or ""): e for e in _placement_now(row)}
    fase_pilihan = _phase_options()

    st.markdown(f"**{t('re.sec_placement')}**")
    keluar = []
    for nama in berkas:
        entri = tersimpan.get(nama) or {}
        kol = st.columns([3, 2])
        fase = kol[0].multiselect(
            t("re.f_phase", filename=nama), fase_pilihan,
            default=[f for f in (entri.get("phases") or [])
                     if f in fase_pilihan],
            key=f"re_edit_phase_{pipeline_id}_{nama}")
        bersama = kol[1].checkbox(
            t("re.f_shared"), value=bool(entri.get("shared")),
            key=f"re_edit_shared_{pipeline_id}_{nama}",
            help=t("re.help_shared"))
        keluar.append({"filename": nama, "phases": list(fase),
                       "shared": bool(bersama)})
    return keluar


#: Kolom tabel berkas paket pipeline AKTIF. Sengaja sama persis dengan
#: `contribute._FILE_COLS`: pertanyaan yang dijawab pembacanya sama — berkas
#: ini apa, lolos periksa atau tidak, sebesar apa, dari mana, bekerja di mana.
#: Yang berbeda hanya kolom terakhirnya, sebab di sini berkas LANGSUNG
#: disunting sedangkan di pengajuan ia dibaca lebih dulu.
_PKG_COLS = (
    ("sr.col_file", 8),
    ("sr.col_role", 4),
    ("rv.col_check_result", 6),
    ("sr.col_size", 3),
    ("sr.col_origin", 4),
    ("sr.col_placement", 6),
    ("", 3),
)


def _package_rows(row: dict, berkas: dict) -> list[dict]:
    """Baris tabel berkas paket versi ini.

    Bentuk barisnya SAMA dengan `submission_review.file_rows`, supaya penyusun
    tabel yang sama (`file_table_rows`) dapat memakainya: hasil periksa, ukuran
    terbaca, penempatan, dan asal sudah dihitung di sana dan tidak dihitung
    ulang di sini.

    Penempatan pipeline aktif menyimpan `shared`, bukan daftar algoritma —
    sebab satu baris registry memetakan ke SATU kelas. Di tabel, keduanya
    ditulis dengan kalimat yang sama: berkas bersama menjadi "semua algoritma",
    yang lain menjadi nama kelas titik masuknya.
    """
    from orchestrator.pipeline_versions import validate_package
    from ui.components.submission_review import ALGO_ALL

    periksa, _ = _safe_data(validate_package, berkas, default={})
    entri_per_nama = {e.get("filename"): e
                      for e in (periksa or {}).get("files") or []}
    tersimpan = {str(e.get("filename") or ""): e for e in _placement_now(row)}
    kelas = (row.get("entry_class") or "").strip()
    asal = t("re.origin_version", version=row.get("version") or "-")

    keluar = []
    for nama, teks in (berkas or {}).items():
        entri = entri_per_nama.get(nama) or {}
        simpan = tersimpan.get(nama) or {}
        fase = list(simpan.get("phases") or [])
        if simpan.get("shared"):
            algo = [ALGO_ALL]
        else:
            algo = [kelas] if (kelas and fase) else []
        keluar.append({
            "filename": nama,
            "role": entri.get("role") or "",
            "size": len((teks or "").encode("utf-8")),
            "description": "",
            "ok": bool(entri.get("package_ok")),
            "origin": asal,
            "placement": {"phases": fase, "algorithms": algo},
            "entry": entri,
        })
    keluar.sort(key=lambda r: (r["role"] != ROLE_ENTRY,
                               r["filename"].lower()))
    return keluar


def _render_package_table(row: dict, berkas: dict) -> str:
    """Daftar berkas versi ini sebagai TABEL. Mengembalikan berkas terpilih.

    Menggantikan `st.radio` mendatar yang dahulu berdiri di sini. Radio hanya
    menjawab "berkas mana yang sedang saya sunting"; ia tidak mengatakan berkas
    mana yang gagal periksa, sebesar apa, atau bekerja di fase mana — padahal
    justru itu yang menentukan berkas mana yang perlu disunting. Sebagai tabel,
    keenam jawabannya berdiri sekaligus dan pemilihannya tetap satu klik.
    """
    from ui.components import submission_review as sr
    from ui.views._artifact_browser import format_size

    pipeline_id = row["pipeline_id"]
    baris = sr.file_table_rows(_package_rows(row, berkas),
                               size_text=format_size)
    terbuka = st.session_state.setdefault(_FILE_KEY, {}).get(str(pipeline_id))
    if not any(b["filename"] == terbuka for b in baris):
        terbuka = baris[0]["filename"] if baris else ""
        st.session_state.setdefault(_FILE_KEY, {})[str(pipeline_id)] = terbuka

    lebar = [b for _, b in _PKG_COLS]
    with st.container():
        st.markdown('<span class="ids-queue-head"></span>',
                    unsafe_allow_html=True)
        kepala = st.columns(lebar, vertical_alignment="center")
        for kol, (kunci, _) in zip(kepala, _PKG_COLS):
            kol.markdown(f"**{t(kunci)}**" if kunci else "")

    for b in baris:
        nama = b["filename"]
        with st.container(border=True):
            st.markdown('<span class="ids-queue-row"></span>',
                        unsafe_allow_html=True)
            sel = st.columns(lebar, vertical_alignment="center")
            tanda = "**" if nama == terbuka else ""
            sel[0].markdown(f"{tanda}{escape(str(nama))}{tanda}")
            sel[1].markdown(escape(str(b.get("role") or "")))
            sel[2].markdown(
                grid.state_badge(b.get("check_text") or "", sr.file_state(b)),
                unsafe_allow_html=True)
            sel[3].markdown(escape(str(b.get("size_text") or "")))
            sel[4].markdown(escape(str(b.get("origin_text") or "")))
            sel[5].markdown(escape(str(b.get("placement_text") or "")))
            if sel[6].button(t("re.btn_edit_file"),
                             key=f"re_pick_{pipeline_id}_{nama}",
                             use_container_width=True,
                             disabled=nama == terbuka):
                # Berpindah berkas MENYIMPAN suntingan berkas sebelumnya,
                # aturan yang sama dengan pemilih radio yang digantikannya.
                _stash_edit(pipeline_id, terbuka, berkas)
                st.session_state.setdefault(
                    _FILE_KEY, {})[str(pipeline_id)] = nama
                st.rerun()
    return terbuka


def _render_package_downloads(row: dict, berkas: dict, nama: str) -> None:
    """Unduh berkas ini, dan unduh seluruh paketnya. SATU baris.

    Paketnya dirakit di memori dari isi yang sudah dibaca — tidak ada berkas
    yang dibaca ulang dari disk, dan tidak ada arsip yang ditinggalkan.
    """
    import io
    import zipfile

    pipeline_id = row["pipeline_id"]
    kolom = st.columns([1, 1, 2])
    kolom[0].download_button(
        t("ap.btn_download_file"),
        data=(berkas.get(nama) or "").encode("utf-8"),
        file_name=nama or "berkas.py", mime="text/x-python",
        key=f"re_dl_{pipeline_id}_{nama}", use_container_width=True,
        help=t("ap.help_open_outside"))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as arsip:
        for berkas_nama, teks in (berkas or {}).items():
            arsip.writestr(berkas_nama, teks or "")
    kolom[1].download_button(
        t("ap.btn_download_package", count=len(berkas or {})),
        data=buf.getvalue(),
        file_name=f"{pipeline_id}_paket.zip", mime="application/zip",
        key=f"re_dl_pkg_{pipeline_id}", use_container_width=True,
        help=t("ap.help_download_package"))


def _render_package_editor(row: dict, user: dict | None) -> None:
    """Sunting paket versi ini, hasilnya VERSI BARU.

    Tidak ada jalan pintas ke registry: yang menulis tetap
    `pipeline_versions.save_new_version`, dengan catatan perubahan wajib,
    validasi statis sebelum ada berkas ditulis, dan versi lama tidak tersentuh.
    """
    from orchestrator.pipeline_versions import read_package, save_new_version

    pipeline_id = row["pipeline_id"]
    berkas, galat = _safe_data(read_package, pipeline_id, default={})
    if galat is not None:
        # Sebabnya disebut apa adanya. Paling sering: berkas versi ini tidak
        # ada di jalur yang tercatat — misalnya record dibuat di host lain
        # daripada tempat aplikasi ini berjalan.
        st.error(_message(galat))
        return
    if not isinstance(berkas, dict) or not berkas:
        st.error(t("re.err_package_unreadable"))
        return

    with st.container(border=True):
        st.markdown(f"**{t('re.sec_edit_package', pipeline=pipeline_id)}**")

        st.session_state.setdefault(_FILE_KEY, {}).setdefault(
            str(pipeline_id), list(berkas)[0])
        # Tabel berkas MENDAHULUI kotak sunting: berkas mana yang perlu
        # disunting ditentukan oleh hasil periksanya, dan itu yang dijawab
        # tabel ini. Nilai kembaliannya berkas yang sedang dibuka.
        nama = _render_package_table(row, berkas) or list(berkas)[0]
        _render_package_downloads(row, berkas, nama)
        tertunda = _draft_of(pipeline_id)
        if tertunda:
            st.markdown(t("re.draft_pending", count=len(tertunda)))

        # Label tidak pernah terlihat: nama berkasnya sudah dipilih tepat di
        # atas kotak ini, tetapi pembaca layar tetap memerlukannya.
        #
        # Isinya dibaca dari suntingan tertunda bila berkas ini pernah
        # disunting lalu ditinggalkan, bukan dari paket tersimpan.
        isi = code_box.source_editor(
            tertunda.get(nama, berkas[nama]),
            key=f"re_edit_box_{pipeline_id}_{nama}",
            label=t("re.lbl_edit_source", filename=nama), lines=20)
        # ── Keterangan yang ikut disunting ───────────────────────────
        #
        # Ketiganya ada di halaman pengajuan tetapi tidak pernah dapat diubah
        # lagi sesudah pipeline terdaftar: algoritma, kelas titik masuk, dan
        # penempatan berkas. Yang menulis tetap `save_new_version`, jadi
        # perubahannya melahirkan VERSI BARU dengan catatan perubahan, bukan
        # menimpa versi yang sedang berjalan.
        st.markdown(f"**{t('re.sec_edit_meta')}**")
        m1, m2 = st.columns(2)
        algoritma = m1.text_input(t("re.f_algorithm"),
                                  value=row.get("algorithm") or "",
                                  key=f"re_edit_algo_{pipeline_id}")
        # Kelas titik masuk DIPILIH dari kelas yang benar-benar ada di paket,
        # bukan diketik: nama yang salah ketik membuat pipeline gagal dimuat,
        # dan kegagalan itu baru terasa saat eksperimen dijalankan.
        kelas_ada = _class_names({**berkas, **disunting_awal(pipeline_id)})
        pilihan = sorted(kelas_ada or {row.get("entry_class") or ""})
        kini = row.get("entry_class") or ""
        titik_masuk = m2.selectbox(
            t("re.f_entry_class"), pilihan,
            index=pilihan.index(kini) if kini in pilihan else 0,
            key=f"re_edit_class_{pipeline_id}",
            help=t("re.help_entry_class"))

        penempatan = _render_placement_fields(pipeline_id, row, berkas)

        catatan = st.text_area(t("re.lbl_change_note"), height=80,
                               key=f"re_edit_note_{pipeline_id}",
                               help=t("re.help_change_note"))

        # SELURUH berkas yang disunting ikut, bukan hanya yang sedang dibuka.
        disunting = {**tertunda}
        if isi != berkas[nama]:
            disunting[nama] = isi
        else:
            disunting.pop(nama, None)

        # Keterangan yang berubah dihitung setara dengan berkas yang berubah:
        # menyunting algoritma saja tetap perubahan yang layak disimpan.
        meta_berubah = (
            (algoritma or "").strip() != (row.get("algorithm") or "").strip()
            or titik_masuk != kini
            or penempatan != _placement_now(row))

        aksi = st.columns([1, 1, 3])
        siap = ((bool(disunting) or meta_berubah)
                and bool((catatan or "").strip()))
        if aksi[0].button(t("re.btn_save_version"), type="primary",
                          key=f"re_edit_save_{pipeline_id}",
                          use_container_width=True, disabled=not siap,
                          help=None if siap else t("re.help_edit_incomplete")):
            try:
                versi = save_new_version(pipeline_id,
                                         files={**berkas, **disunting},
                                         change_note=catatan, actor=user,
                                         entry_class=titik_masuk,
                                         algorithm=algoritma,
                                         file_placement=penempatan)
            except Exception as e:
                st.error(_message(e))
            else:
                _forget_drafts(pipeline_id)
                st.session_state.pop(_EDIT_KEY, None)
                st.success(t("re.msg_version_saved",
                             version=versi.get("version", "")))
                st.rerun()
        if aksi[1].button(t("action.cancel"), key=f"re_edit_cancel_{pipeline_id}",
                          use_container_width=True):
            _forget_drafts(pipeline_id)
            st.session_state.pop(_EDIT_KEY, None)
            st.rerun()


def _render_testing(row: dict, user: dict | None) -> None:
    """Pengujian pipeline AKTIF: apa yang berlaku sekarang, dan apa hasilnya.

    Dua hal yang berbeda, dan keduanya disebut versinya supaya tidak tertukar:

    * **Pemeriksaan paket** — validasi STATIS atas paket yang sedang disunting,
      termasuk suntingan yang BELUM disimpan. Inilah yang menjawab "apakah
      suntingan saya masih sah" sebelum ia melahirkan versi baru, dan ia
      memakai validator yang sama dengan jalur unggah maupun peninjauan.
    * **Hasil menjalankan** — eksperimen yang benar-benar pernah dijalankan
      dengan pipeline ini, beserta statusnya.

    TIDAK ada kotak pasir dataset di sini, dan itu disengaja. Uji coba
    berdataset kecil adalah alat PENINJAUAN: catatannya terikat pada sebuah
    pengajuan (`pipeline_trials.submission_id NOT NULL`), dan pipeline yang
    sudah aktif diuji dengan cara yang sesungguhnya — dijalankan sebagai
    eksperimen. Membuat jalur uji kedua di sini berarti dua mesin untuk satu
    pertanyaan.
    """
    from orchestrator.pipeline_versions import (
        package_rejection_reason, read_package, validate_package,
    )

    pipeline_id = row["pipeline_id"]
    with st.container(border=True):
        st.markdown(f"**{t('re.sec_testing', version=row.get('version') or '-')}**")

        berkas, galat = _safe_data(read_package, pipeline_id, default={})
        if galat is not None or not isinstance(berkas, dict) or not berkas:
            # Penyunting tepat di atas bagian ini SUDAH menyebut sebabnya
            # dengan kalimat yang sama. Mengulangnya di sini hanya memberi
            # kotak merah kedua untuk satu kegagalan.
            return

        # Suntingan yang belum disimpan IKUT diperiksa: memeriksa paket
        # tersimpan sementara yang di layar sudah berubah akan menjawab
        # pertanyaan yang tidak sedang ditanyakan.
        tertunda = _draft_of(pipeline_id)
        periksa, galat = _safe_data(validate_package,
                                    {**berkas, **tertunda}, default={})
        if galat is not None:
            st.error(_message(galat))
        else:
            sebab = package_rejection_reason(periksa)
            # Pil hanya memuat LABEL pendek. Sebuah pil `white-space: nowrap`
            # (lihat `.ids-badge`) yang diisi kalimat penuh tidak pernah
            # patah: ia tumbuh mendatar sampai keluar dari kotaknya dan
            # menabrak tepi layar. Sebabnya ditulis di bawahnya, sebagai teks
            # biasa yang memang boleh patah.
            if sebab:
                st.markdown(grid.state_badge(t("re.test_static_failed"), "bad"),
                            unsafe_allow_html=True)
            else:
                st.markdown(
                    grid.state_badge(
                        t("re.test_static_clean",
                          count=len(periksa.get("files") or [])), "ok"),
                    unsafe_allow_html=True)
            # Penanda "termasuk suntingan" berdiri sebagai barisnya sendiri:
            # menempelkannya di sebelah pil membuat baris itu ikut melebar.
            if tertunda:
                st.markdown(t("re.test_with_drafts", count=len(tertunda)))
            if sebab:
                st.error(sebab)

        _render_run_results(pipeline_id)


def _render_run_results(pipeline_id: str) -> None:
    """Eksperimen terakhir yang memakai pipeline ini, beserta statusnya.

    Membaca yang SUDAH tercatat; tidak menjalankan apa pun. Menjalankan
    eksperimen baru tetap di halamannya sendiri — di sanalah dataset dipilih
    atau diunggah, dan menyalin pemilihnya ke sini berarti dua tempat yang
    harus sama-sama benar.
    """
    from database.db import list_experiments

    rows, galat = _safe_data(list_experiments, default=[])
    if galat is not None:
        return
    milik = [r for r in (rows or [])
             if (r.get("pipeline_id") or "") == pipeline_id][:5]
    if not milik:
        st.markdown(t("re.test_never_run"))
        return

    lebar = [6, 5, 5]
    with st.container():
        st.markdown('<span class="ids-queue-head"></span>',
                    unsafe_allow_html=True)
        kepala = st.columns(lebar, vertical_alignment="center")
        for kol, kunci in zip(kepala, ("ps.col_id", "ps.col_status",
                                       "ps.lbl_created")):
            kol.markdown(f"**{t(kunci)}**")

    for r in milik:
        status = str(r.get("status") or "")
        keadaan = {"COMPLETED": "ok", "FAILED": "bad"}.get(status, "warn")
        with st.container(border=True):
            st.markdown('<span class="ids-queue-row"></span>',
                        unsafe_allow_html=True)
            sel = st.columns(lebar, vertical_alignment="center")
            sel[0].markdown(escape(_ringkas(str(r.get("id") or ""), 12)))
            sel[1].markdown(grid.state_badge(status, keadaan),
                            unsafe_allow_html=True)
            sel[2].markdown(escape(human_datetime(r.get("created_at"))))


#: Kolom riwayat versi pipeline AKTIF. Sejajar dengan riwayat revisi
#: pengajuan (`contribute._ROUND_COLS`) — pertanyaannya sama: siapa mengubah
#: apa, kapan, dan kenapa. Yang berbeda hanya namanya: di sini "Versi", di
#: pengajuan "Putaran", sebab yang satu melahirkan baris registry baru dan
#: yang lain belum melahirkan apa pun.
_VERSION_COLS = (
    ("re.col_version", 4),
    ("re.col_by", 5),
    ("re.col_when", 6),
    ("re.col_touched", 6),
    ("re.col_note", 9),
    ("", 3),
)

#: Versi yang sedang dibaca, per pipeline.
_OPEN_VERSION_KEY = "_rs_open_version"


def _ringkas(teks: str, batas: int) -> str:
    """Potong teks panjang supaya satu baris tabel tetap setinggi barisnya.

    Yang dipotong DITANDAI. Teks yang berhenti begitu saja terbaca seperti
    nilai yang memang sependek itu, dan pembacanya tidak akan tahu ada yang
    tidak terlihat.
    """
    teks = str(teks or "").strip()
    return teks if len(teks) <= batas else teks[:batas - 1] + "…"


def _touched_between(baris: dict, sebelumnya: dict | None) -> str:
    """Berkas yang BERUBAH pada satu versi, dibanding versi sebelumnya.

    Skemanya tidak mencatatnya — `registered_pipelines` menyimpan paket, bukan
    daftar perubahan. Jadi dihitung di sini dengan membandingkan isi kedua
    paket. Versi pertama tidak punya pembanding: ia lahir dari PERSETUJUAN,
    bukan penyuntingan, dan itu dinyatakan apa adanya alih-alih ditulis
    seolah-olah tidak ada berkas yang tersentuh.

    Paket yang tidak terbaca menghasilkan tanda tanya, BUKAN daftar kosong:
    "tidak tahu" dan "tidak ada yang berubah" adalah dua jawaban berbeda.
    """
    from orchestrator.pipeline_versions import read_package

    if sebelumnya is None:
        return t("re.version_first")

    kini, galat_a = _safe_data(read_package, baris.get("pipeline_id") or "",
                               default=None)
    lalu, galat_b = _safe_data(read_package,
                               sebelumnya.get("pipeline_id") or "",
                               default=None)
    if galat_a or galat_b or not isinstance(kini, dict) \
            or not isinstance(lalu, dict):
        return t("re.version_unknown_touch")

    berubah = sorted(
        {n for n, teks in kini.items() if lalu.get(n) != teks}
        | {n for n in lalu if n not in kini})
    return ", ".join(berubah) if berubah else t("re.version_no_file_change")


def _render_version_history(row: dict, user: dict | None) -> None:
    """Riwayat versi pipeline ini: siapa mengubah apa, kapan, dan kenapa.

    Datanya SUDAH ada sejak versi pertama platform ini — `save_new_version`
    mencatat `edited_by`, `edited_at`, dan `change_note` pada tiap baris, dan
    versi lama tidak pernah ditimpa. Yang belum ada hanyalah tempat
    membacanya: ketertelusuran yang tersimpan rapi tetapi tak pernah
    ditampilkan sama saja dengan tidak tercatat, bagi orang yang perlu
    menjawab "kenapa pipeline ini berubah minggu lalu".
    """
    from orchestrator.pipeline_versions import version_history

    riwayat, galat = _safe_data(version_history, row.get("name") or "",
                                default=[])
    if galat is not None:
        st.error(_message(galat))
        return
    if not riwayat:
        return

    pipeline_id = row["pipeline_id"]
    with st.container(border=True):
        st.markdown(f"**{t('re.sec_versions')}**")

        # `version_history` mengurutkan terbaru lebih dulu; pembanding tiap
        # baris adalah versi TEPAT di bawahnya pada urutan itu.
        lebar = [b for _, b in _VERSION_COLS]
        with st.container():
            st.markdown('<span class="ids-queue-head"></span>',
                        unsafe_allow_html=True)
            kepala = st.columns(lebar, vertical_alignment="center")
            for kol, (kunci, _) in zip(kepala, _VERSION_COLS):
                kol.markdown(f"**{t(kunci)}**" if kunci else "")

        terbuka = st.session_state.get(_OPEN_VERSION_KEY, {}).get(
            str(pipeline_id))
        for i, baris in enumerate(riwayat):
            versi = baris.get("version")
            sebelum = riwayat[i + 1] if i + 1 < len(riwayat) else None
            # Versi pertama dicatat oleh jalur PERSETUJUAN, jadi pelakunya
            # ada di `registered_by`, bukan `edited_by`. Yang kosong ditulis
            # dengan KATA: sama seperti kolom Catatan, sebuah tanda hubung
            # sendirian akan digambar markdown sebagai butir daftar.
            oleh = (baris.get("edited_by") or baris.get("registered_by")
                    or t("re.value_unrecorded"))
            kapan = baris.get("edited_at") or baris.get("registered_at")
            with st.container(border=True):
                st.markdown('<span class="ids-queue-row"></span>',
                            unsafe_allow_html=True)
                sel = st.columns(lebar, vertical_alignment="center")
                tanda = "**" if versi == terbuka else ""
                sel[0].markdown(f"{tanda}{escape(str(versi))}{tanda}")
                sel[1].markdown(escape(str(oleh)))
                sel[2].markdown(escape(human_datetime(kapan)))
                sel[3].markdown(escape(_ringkas(
                    _touched_between(baris, sebelum), 46)))
                # Catatan KOSONG ditulis dengan kata, bukan dengan tanda
                # hubung: `st.markdown("-")` adalah sintaks daftar, dan yang
                # muncul di kolom ini justru sebuah butir bulat.
                catatan = str(baris.get("change_note") or "").strip()
                sel[4].markdown(escape(_ringkas(catatan, 64)) if catatan
                                else t("re.version_no_note"))
                if sel[5].button(t("re.btn_read_version"),
                                 key=f"re_ver_open_{pipeline_id}_{versi}",
                                 use_container_width=True,
                                 disabled=versi == terbuka):
                    st.session_state.setdefault(
                        _OPEN_VERSION_KEY, {})[str(pipeline_id)] = versi
                    st.rerun()

        if terbuka is not None:
            _render_version_read(riwayat, terbuka)


def _render_version_read(riwayat: list, versi) -> None:
    """Isi satu versi lama, DIBACA saja.

    Tidak ada tombol sunting di sini, dan itu disengaja: menyunting versi lama
    berarti menulis ke sesuatu yang sudah dipakai eksperimen yang tercatat.
    Yang boleh disunting hanyalah versi yang sedang berjalan, dan hasilnya
    selalu versi BARU.
    """
    from orchestrator.pipeline_versions import read_package

    baris = next((b for b in riwayat if b.get("version") == versi), None)
    if baris is None:
        return

    berkas, galat = _safe_data(read_package, baris.get("pipeline_id") or "",
                               default={})
    if galat is not None or not isinstance(berkas, dict) or not berkas:
        st.error(t("re.version_unreadable", version=versi))
        return

    st.divider()
    st.markdown(f"**{t('re.sec_version_read', version=versi)}**")
    nama = st.selectbox(t("re.lbl_version_file"), list(berkas),
                        key=f"re_ver_file_{baris.get('pipeline_id')}")
    st.code(berkas.get(nama) or "", language="python", line_numbers=True,
            height=320)


def _render_info_refresh(row: dict, user: dict | None) -> None:
    """Tawaran mengambil potret keterangan — HANYA bila memang belum ada.

    Baris yang terdaftar sebelum platform menyimpan potret `get_info()` tidak
    dapat menjelaskan dirinya di katalog. Ia tidak diperbaiki diam-diam saat
    halaman digambar: memuat kode kontribusi adalah tindakan, jadi ia diminta
    sebagai tindakan.
    """
    from orchestrator import dynamic_registry as dr

    if str(row.get("info_json") or "").strip():
        return

    pipeline_id = row["pipeline_id"]
    note, act = st.columns([6, 2])
    note.markdown(t("re.lbl_info_missing"))
    if not act.button(t("re.btn_refresh_info"),
                      key=f"re_algo_info_{pipeline_id}",
                      use_container_width=True):
        return
    try:
        dr.refresh_info(pipeline_id, actor=user)
    except Exception as e:
        st.error(_message(e))
        return
    st.success(t("re.msg_info_refreshed",
                 algorithm=row.get("algorithm") or row.get("name")
                 or pipeline_id))
    st.rerun()


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
    """PENGHALANG yang tidak terbaca berarti MENUTUP, bukan membuka.

    Pola fail-closed yang sama dipakai gerbang persetujuan: "tidak tahu apakah
    boleh" tidak pernah berarti "boleh".

    HANYA untuk fungsi yang mengembalikan alasan berupa UNTAI. Memakainya pada
    fungsi yang mengembalikan data membuat kunci galat di bawah ini menyamar
    sebagai datanya sendiri: `read_package` yang gagal pernah berakhir sebagai
    untai yang dibaca sebagai peta berkas, sehingga pemilih berkas menampilkan
    "a p . e r r _ g a t e ..." satu huruf per pilihan lalu jatuh dengan
    `TypeError: string indices must be integers`. Untuk data, pakai
    :func:`_safe_data`.
    """
    try:
        return fn(*args)
    except Exception:                           # pragma: no cover - defensive
        logger.warning("Penghalang tidak terbaca untuk %s", args, exc_info=True)
        return "ap.err_gate_unreadable"


def _safe_data(fn, *args, default=None):
    """Fungsi yang mengembalikan DATA. Gagal berarti `default`, bukan untai.

    Mengembalikan pasangan ``(nilai, galat)`` supaya pemanggilnya dapat
    menyebutkan SEBABNYA alih-alih menampilkan kalimat umum: "paket tidak
    terbaca" tidak memberi tahu siapa pun berkas mana yang hilang.
    """
    try:
        return fn(*args), None
    except Exception as e:                      # noqa: BLE001 - dilaporkan
        logger.warning("Data tidak terbaca untuk %s", args, exc_info=True)
        return default, e


def _message(error: Exception) -> str:
    from ui.components.validator_messages import error_message

    return error_message(error)

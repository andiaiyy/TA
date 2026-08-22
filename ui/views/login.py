"""
Identitas & switch mode — FASE 2.

Model: platform terbuka dalam **mode pengunjung**. Tidak ada gerbang login di
depan: siapa pun dapat membuka semua halaman, melihat seluruh eksperimen, dan
menjalankan eksperimen. Login hanya dibutuhkan untuk AKSI BERISIKO (mengunggah
dataset/pipeline, menyetujui, mengelola pengguna) — penegakannya ada di
``orchestrator/auth_service`` dan dipanggil baik oleh UI maupun oleh fungsi
aksinya.

Session SEDERHANA: identitas hanya hidup di ``st.session_state`` (refresh =
kembali jadi pengunjung). Tidak ada cookie/token persisten. Yang disimpan hanya
`username` dan `role` — password mentah maupun hash TIDAK PERNAH masuk
session_state.
"""
from __future__ import annotations

import time

import streamlit as st

from database.models import ALL_ROLES, role_label
from ui.components import dialogs as dlg
from ui.components.sidebar_chrome import render_line
from orchestrator.auth_service import (
    MAX_REASON_LENGTH, MAX_USERNAME_LENGTH, AuthError, authenticate,
    is_account_active, register_account,
)

SESSION_USER_KEY = "auth_user"
_ATTEMPTS_KEY = "_auth_failed_attempts"
_SIGNUP_ATTEMPTS_KEY = "_auth_signup_attempts"
_SIGNUP_DONE_KEY = "_auth_signup_done"

# Flag pembuka modal auth: "login" | "signup". Tombol mana pun hanya menulis
# flag ini; modalnya sendiri dirender dari alur utama ui/app.py.
#
# SIKLUS HIDUP flag (penting — pernah menjadi bug "modal muncul sendiri"):
# flag ini dibaca dari ui/app.py, yaitu alur yang dijalankan pada SEMUA
# halaman. Berbeda dengan `_detail_id` (view_results) dan `_compat_check_type`
# (run_experiment) yang hanya dibaca di dalam `render()` halamannya
# masing-masing sehingga tidak mungkin terbawa ke halaman lain. Karena itu flag
# ini harus dibersihkan secara eksplisit di SETIAP jalur keluar, termasuk saat
# dialog ditutup lewat tombol X/Esc dan saat pengguna berpindah halaman.
_DIALOG_KEY = dlg.AUTH_KEY
# Halaman yang sedang dirender pada run sebelumnya — pembanding untuk mendeteksi
# perpindahan halaman. Diisi oleh `maybe_render_auth_dialog`, yang menerima
# halaman aktif dari ui/app.py (bukan mengimpornya: app.py adalah script).
_DIALOG_PAGE_KEY = "_auth_dialog_page"
_MODE_LOGIN = "login"
_MODE_SIGNUP = "signup"

# Pembatasan sederhana untuk lingkungan internal: cukup menahan pendaftaran
# beruntun dalam satu sesi. Tidak ada CAPTCHA / verifikasi surel (di luar lingkup).
_SIGNUP_LIMIT = 5

# Kalimat penunjuk jalur masuk. Satu tempat, dipakai halaman mana pun yang perlu
# memberi tahu pengguna cara masuk — jadi arah yang ditunjuk tidak pernah
# berbeda-beda antar halaman.
SIGN_IN_HINT = "Masuk lewat pemilih mode di kiri bawah sidebar."

# Peran yang DAPAT DIPILIH di pemilih mode sidebar. Daftar ini hanya menentukan
# tombol mana yang tampil; memilihnya tidak pernah memberikan peran apa pun.
_PICKABLE_ROLES = tuple(ALL_ROLES)

# Label & keterangan pemilih mode. Labelnya PENDEK (satu kata/frasa); seluruh
# penjelasan pindah ke tooltip supaya daftarnya tetap ringkas.
_MODE_VISITOR = "Pengunjung"
_ROLE_HELP = ("Membuka formulir masuk. Memilih di sini tidak memberikan peran "
              "tersebut — peran ditentukan akun & statusnya.")
_CURRENT_MODE_HELP = "Mode saat ini: membaca tanpa akun."
_CURRENT_ROLE_HELP = "Peran akun Anda saat ini."
_OTHER_ROLE_HELP = "Peran ditentukan akun & statusnya, bukan dipilih di sini."

# Penanda tak terlihat yang menandai wadah blok mode. CSS terpusat
# (ui/components/theme.py) mencari wadah yang MEMUAT penanda ini lalu
# memberinya margin-top:auto, sehingga blok terdorong ke dasar sidebar.
#
# Harus berada DI DALAM st.container() yang sama dengan isi bloknya: Streamlit
# membungkus tiap elemen dalam wadahnya sendiri, jadi <div> yang dibuka di satu
# panggilan markdown dan ditutup di panggilan lain TIDAK pernah membungkus apa
# pun (itu sebab percobaan sebelumnya gagal).
_MODE_ANCHOR = '<span class="ids-mode-anchor"></span>'

# Jeda kecil setelah beberapa kegagalan berturut-turut dalam satu session.
# Sekadar memperlambat tebakan beruntun; bukan pengganti rate limiting nyata.
_THROTTLE_AFTER = 3
_THROTTLE_SECONDS = 1.5


def current_user() -> dict | None:
    """Identitas yang sedang aktif, atau None untuk pengunjung."""
    user = st.session_state.get(SESSION_USER_KEY)
    return user if isinstance(user, dict) and user.get("username") else None


def is_authenticated() -> bool:
    return current_user() is not None


def logout() -> None:
    """Kembali ke mode pengunjung. Tidak menyentuh data/state eksperimen."""
    st.session_state.pop(SESSION_USER_KEY, None)
    st.session_state.pop(_ATTEMPTS_KEY, None)
    close_auth_dialog()


def _attempt_login(username: str, password: str) -> bool:
    """True bila berhasil. Menyimpan HANYA username & role."""
    attempts = int(st.session_state.get(_ATTEMPTS_KEY, 0))
    if attempts >= _THROTTLE_AFTER:
        time.sleep(_THROTTLE_SECONDS)

    user = authenticate(username, password)
    if user is None:
        st.session_state[_ATTEMPTS_KEY] = attempts + 1
        return False

    # `status` ikut disimpan supaya TAMPILAN tahu akun ini masih menunggu
    # persetujuan (kontrol unggah ikut mati). Lapis aksi tetap membaca ulang
    # status dari DB, jadi salinan ini tidak pernah menjadi otoritas.
    st.session_state[SESSION_USER_KEY] = {
        "username": user["username"],
        "role": user["role"],
        "status": user["status"],
    }
    st.session_state.pop(_ATTEMPTS_KEY, None)
    # Jangan tinggalkan password yang barusan diketik di session_state; formulir
    # tidak dirender lagi setelah ini, jadi nilainya tidak dibutuhkan.
    for widget_key in ("login_username", "login_password"):
        try:
            del st.session_state[widget_key]
        except (KeyError, Exception):      # pragma: no cover - defensif
            pass
    return True


def render_mode_switch() -> None:
    """Panel identitas RINGKAS di bagian bawah sidebar.

    Hanya status + satu tombol. Tidak ada satu pun input teks/password di
    sini — seluruh pengisian ada di modal (lihat ``_auth_dialog_body``).
    Tombolnya HANYA menyimpan flag; dialog dipanggil dari alur utama
    ``ui/app.py``, di luar blok sidebar.
    """
    with st.sidebar:
        # SATU wadah untuk seluruh blok, ditandai jangkar tak terlihat. CSS
        # terpusat memberi wadah ini margin-top:auto di dalam kolom fleksibel
        # sidebar, sehingga ia terdorong ke dasar berapa pun panjang isi di
        # atasnya. Blok ini juga HARUS dirender terakhir — lihat ui/app.py.
        with st.container():
            st.markdown(_MODE_ANCHOR, unsafe_allow_html=True)
            st.divider()
            user = current_user()

            if st.session_state.pop(_SIGNUP_DONE_KEY, False):
                st.success("Pendaftaran diterima — menunggu persetujuan.")

            # `st.popover` membuka panel mengambang; karena blok ini elemen
            # TERAKHIR di sidebar, panelnya membuka ke ATAS mengikuti ruang
            # yang tersedia — tanpa perlu trik CSS posisi.
            label = (f"{user['username']} · {role_label(user.get('role'))}"
                     if user else "Mode pengunjung")
            # Daftar pilihan sengaja RINGKAS: hanya nama mode, satu baris per
            # pilihan, tanpa kalimat penjelas di dalamnya. Penjelasannya pindah
            # ke `help=` masing-masing tombol (butir 9) — termasuk penegasan
            # bahwa memilih peran TIDAK memberikan peran itu.
            #
            # `use_container_width` sengaja TIDAK dipakai di sini: tombol yang
            # memuai membuat panel selebar sidebar. Lebarnya kini mengikuti
            # isinya, dibatasi max-width di CSS terpusat.
            with st.popover(label, use_container_width=True):
                if user:
                    if st.button(_MODE_VISITOR, key="auth_logout",
                                 help="Keluar dan kembali membaca tanpa akun."):
                        logout()
                        st.rerun()
                    for role in _PICKABLE_ROLES:
                        st.button(role_label(role), key=f"auth_pick_{role}",
                                  disabled=True,
                                  help=_CURRENT_ROLE_HELP
                                       if role == user.get("role")
                                       else _OTHER_ROLE_HELP)
                    if not is_account_active(user):
                        # Status akun — WAJIB tetap tersampaikan, diringkas
                        # menjadi dua kata.
                        render_line("⏳ Menunggu persetujuan", muted=True,
                                    small=True)
                else:
                    # Memilih peran di sini TIDAK memberikan peran itu — tombolnya
                    # hanya membuka jalur masuk. Peran yang berlaku selalu datang
                    # dari akun & statusnya di basis data, dibaca ulang oleh
                    # orchestrator.auth_service pada setiap aksi berisiko. Karena
                    # itu tidak ada satu pun penulisan peran ke session_state di
                    # sini; yang ditulis hanya flag pembuka modal.
                    st.button(_MODE_VISITOR, key="auth_pick_visitor",
                              disabled=True, help=_CURRENT_MODE_HELP)
                    for role in _PICKABLE_ROLES:
                        if st.button(role_label(role), key=f"auth_pick_{role}",
                                     help=_ROLE_HELP):
                            request_auth_dialog(_MODE_LOGIN)
                            st.rerun()


# ── Siklus hidup flag modal ───────────────────────────────────────────────
# Didefinisikan SEBELUM dekorasi `st.dialog` di bawah karena
# `close_auth_dialog` dipasang sebagai `on_dismiss`-nya.

def request_auth_dialog(mode: str = _MODE_LOGIN) -> None:
    """Tandai bahwa modal auth harus terbuka. HANYA menyimpan flag — dipanggil
    dari tombol mana pun (sidebar, ajakan masuk di halaman lain).

    Selalu dipanggil DI DALAM blok `if st.button(...)`, tidak pernah sebagai
    efek samping render; kalau tidak, flag akan terisi ulang setiap rerun dan
    modal tidak akan pernah bisa ditutup.
    """
    st.session_state[_DIALOG_KEY] = mode if mode in (_MODE_LOGIN, _MODE_SIGNUP) else _MODE_LOGIN


def close_auth_dialog() -> None:
    """Bersihkan flag supaya modal tidak terbuka lagi pada rerun berikutnya.

    Dipanggil dari SEMUA jalur keluar: berhasil masuk, berhasil daftar, tombol
    Tutup, keluar (logout), penutupan bawaan dialog (`on_dismiss`), dan
    perpindahan halaman.

    Hanya flag yang dihapus — state widget di dalam modal dibiarkan Streamlit
    yang mengelola (menghapus kunci widget yang masih hidup berisiko error).
    """
    dlg.close_dialog(_DIALOG_KEY)


# ── Modal masuk/daftar (satu dialog, dua tab) ─────────────────────────────

def _auth_dialog_body() -> None:
    """Isi modal: pemilih Masuk/Daftar + formulirnya.

    Satu modal untuk kedua keperluan supaya pengguna dapat berpindah tanpa
    menutup apa pun. Logika auth-nya tidak diubah sama sekali — hanya dipanggil
    dari sini (``_attempt_login`` / ``register_account``).
    """
    modes = [_MODE_LOGIN, _MODE_SIGNUP]
    labels = {_MODE_LOGIN: "Masuk", _MODE_SIGNUP: "Daftar"}
    requested = st.session_state.get(_DIALOG_KEY, _MODE_LOGIN)
    index = modes.index(requested) if requested in modes else 0

    # Key mengikuti mode yang DIMINTA: membuka modal dari tombol "Daftar" atau
    # "Masuk" selalu mulai pada tab yang tepat, tanpa perlu menghapus state
    # widget yang sedang hidup (menghapusnya bisa menimbulkan error).
    widget_key = f"auth_dialog_mode_{requested}"
    if hasattr(st, "segmented_control"):
        mode = st.segmented_control(
            "Mode", modes, default=modes[index], selection_mode="single",
            format_func=lambda m: labels[m], key=widget_key,
            label_visibility="collapsed",
        ) or modes[index]
    else:                                   # pragma: no cover - Streamlit lama
        mode = st.radio("Mode", modes, index=index, horizontal=True,
                        format_func=lambda m: labels[m], key=widget_key,
                        label_visibility="collapsed")

    if mode == _MODE_LOGIN:
        _render_login_tab()
    else:
        _render_signup_tab()

    if st.button("Tutup", key="auth_dialog_close"):
        close_auth_dialog()
        st.rerun()


def _render_login_tab() -> None:
    with st.form("auth_login_form"):
        username = st.text_input("Username", key="login_username")
        password = st.text_input("Password", type="password", key="login_password")
        submitted = st.form_submit_button("Masuk", type="primary",
                                          use_container_width=True)
    st.caption("Belum punya akun? Pilih **Daftar** di atas untuk mengajukan "
               "akun Kontributor.")

    if not submitted:
        return
    if _attempt_login(username, password):
        close_auth_dialog()
        st.rerun()
    # Pesan generik: tidak membocorkan apakah username-nya yang tidak ada.
    st.error("Username atau password salah.")


def _render_signup_tab() -> None:
    """Pendaftaran mandiri. Akun SELALU Kontributor berstatus menunggu
    persetujuan — peran tidak pernah diambil dari masukan pengguna."""
    attempts = int(st.session_state.get(_SIGNUP_ATTEMPTS_KEY, 0))
    if attempts >= _SIGNUP_LIMIT:
        st.warning("Terlalu banyak pendaftaran dari sesi ini. Muat ulang "
                   "halaman bila memang perlu mendaftar lagi.")
        return

    with st.form("auth_signup_form"):
        username = st.text_input("Username", key="signup_username",
                                 max_chars=MAX_USERNAME_LENGTH)
        password = st.text_input("Password", type="password", key="signup_password")
        confirm = st.text_input("Ulangi password", type="password",
                                key="signup_confirm")
        reason = st.text_area("Keperluan (opsional)", key="signup_reason",
                              max_chars=MAX_REASON_LENGTH, height=70,
                              help="Membantu Research Admin menilai permintaan.")
        submitted = st.form_submit_button("Daftar", type="primary",
                                          use_container_width=True)
    st.caption("Sudah punya akun? Pilih **Masuk** di atas.")

    if not submitted:
        return
    try:
        register_account(username, password, confirm, reason)
    except AuthError as e:
        st.session_state[_SIGNUP_ATTEMPTS_KEY] = attempts + 1
        st.error(str(e))          # pesan spesifik: ini pendaftaran, bukan login
        return

    # Jangan tinggalkan password yang barusan diketik di session_state.
    for widget_key in ("signup_username", "signup_password", "signup_confirm"):
        try:
            del st.session_state[widget_key]
        except (KeyError, Exception):      # pragma: no cover - defensif
            pass
    st.session_state.pop(_SIGNUP_ATTEMPTS_KEY, None)
    st.session_state[_SIGNUP_DONE_KEY] = True
    close_auth_dialog()
    st.rerun()


# `st.dialog` HANYA ada di modul `st`. Dekorasi sekali di tingkat modul —
# pola yang sama dengan `_detail_dialog` (view_results.py) dan `_compat_dialog`
# (run_experiment.py). Jalur cadangan untuk Streamlit lama memakai expander,
# bukan atribut .dialog pada container.
_HAS_ST_DIALOG = hasattr(st, "dialog")

if _HAS_ST_DIALOG:
    # `on_dismiss=close_auth_dialog` MENUTUP KEBOCORAN UTAMA: bawaan Streamlit
    # adalah `on_dismiss="ignore"`, artinya menutup modal lewat tombol X, Esc,
    # atau klik di luar hanya menutupnya di peramban — flag di session_state
    # tetap ada. Rerun berikutnya (mis. saat pengguna menekan menu halaman lain)
    # membaca flag yang masih hidup itu dan membuka modal lagi. Dengan callback
    # ini penutupan bawaan ikut membersihkan flag.
    try:
        _auth_dialog = st.dialog(
            "Masuk atau Daftar", on_dismiss=close_auth_dialog)(_auth_dialog_body)
    except TypeError:                       # pragma: no cover - Streamlit < 1.49
        _auth_dialog = st.dialog("Masuk atau Daftar")(_auth_dialog_body)
else:                                       # pragma: no cover - Streamlit < 1.37
    def _auth_dialog() -> None:
        with st.expander("Masuk atau Daftar", expanded=True):
            _auth_dialog_body()


def _page_changed(current_page: str | None) -> bool:
    """True bila halaman yang dirender berbeda dari run sebelumnya.

    Halaman aktif DIKIRIM oleh ui/app.py, bukan diimpor dari sana: app.py adalah
    script Streamlit (mengeksekusi init_db, seed, dsb. saat diimpor), jadi
    mengimpornya dari modul ini tidak aman.
    """
    if current_page is None:
        return False
    previous = st.session_state.get(_DIALOG_PAGE_KEY)
    st.session_state[_DIALOG_PAGE_KEY] = current_page
    return previous is not None and previous != current_page


def maybe_render_auth_dialog(current_page: str | None = None) -> None:
    """Buka modal bila ada flag. Dipanggil dari ALUR UTAMA ui/app.py — di luar
    blok sidebar/kolom/callback, sesuai pola yang sudah terbukti bekerja.

    Sebelum memeriksa flag, perpindahan halaman dibuang lebih dulu: modal yang
    diminta di halaman A tidak boleh ikut terbuka di halaman B. Ini menyamakan
    perilakunya dengan `_maybe_render_compat_dialog` (run_experiment), yang juga
    membuang flag basi lebih dulu lalu keluar tanpa merender.
    """
    if _page_changed(current_page):
        close_auth_dialog()
        return
    if not st.session_state.get(_DIALOG_KEY):
        return
    if is_authenticated():                  # sudah masuk lewat jalur lain
        close_auth_dialog()
        return
    _auth_dialog()


def render_login_prompt(message: str, *, key: str | None = None) -> None:
    """Keterangan mengapa sebuah aksi belum tersedia.

    TIDAK ADA tombol di sini. Jalur masuk satu-satunya adalah pemilih mode di
    kiri bawah sidebar, jadi menaruh tombol kedua di badan halaman hanya
    menduakan jalurnya; keterangannya menunjuk ke sana. ``key`` dipertahankan
    agar pemanggil lama tidak perlu berubah, tetapi tidak lagi dipakai — tanpa
    widget, tidak ada kunci yang perlu unik.
    """
    st.info(f"{message} {SIGN_IN_HINT}")

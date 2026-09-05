"""
Kartu kontribusi dua panel untuk halaman "Add Pipeline & Dataset".

Empat kartu dengan bentuk yang SAMA: panel atas berisi ilustrasi sederhana di
atas latar warna lembut, panel bawah berisi satu-dua baris teks dan satu tombol
aksi. Dua jalur kontribusi (unggah pipeline, unggah dataset) dan dua jalur
pengelolaan (peninjauan pengajuan, kelola pengguna) — semuanya seragam ukuran,
tinggi, radius, dan jaraknya, disusun dua baris berisi dua kartu.

**Ilustrasinya SVG inline** — bentuk geometris sederhana yang digambar di sini,
tanpa berkas gambar eksternal dan tanpa pustaka tambahan.

**Aman di tema terang maupun gelap.** Latar panel ilustrasi memakai warna
transparan (``rgba`` beralfa rendah): di atas latar terang menjadi pastel
lembut, di atas latar gelap menjadi rona tipis. Garis ilustrasinya memakai
``currentColor``, jadi selalu mengikuti warna teks tema yang aktif.

**Izin tidak diubah di sini.** Kartu hanya MEMBACA hasil ``can_upload`` /
``can_approve`` / ``can_manage_users`` untuk menentukan apakah tombolnya hidup;
penegakan sebenarnya tetap di ``orchestrator.auth_service`` yang dipanggil
fungsi aksinya. Kartu yang tombolnya hidup pun tetap melewati pemeriksaan itu,
dan kartu yang tombolnya mati tetap tampil lengkap dengan keterangannya —
supaya pengguna tahu kemampuan platform meski belum berhak memakainya.

Gaya kartunya sendiri didefinisikan sekali di ``ui/components/theme.py``.
"""
from __future__ import annotations

from html import escape

import streamlit as st

# Rona latar panel ilustrasi. Alfa rendah supaya lembut di kedua tema.
TINT_PIPELINE = "rgba(59,130,246,.12)"      # biru
TINT_DATASET = "rgba(16,185,129,.12)"       # hijau
TINT_REVIEW = "rgba(245,158,11,.12)"        # kuning
TINT_USERS = "rgba(139,92,246,.12)"         # ungu

ART_HEIGHT_PX = 116
BODY_MIN_HEIGHT_PX = 84

# Ajakan masuk TIDAK lagi berupa tombol di halaman ini — jalur masuk satu-satunya
# adalah pemilih mode di kiri bawah sidebar, jadi keterangannya menunjuk ke sana.
SIGN_IN_HINT = "Masuk lewat pemilih mode di kiri bawah untuk memakainya."


def _svg(label: str, body: str) -> str:
    return (
        f'<svg viewBox="0 0 64 64" role="img" aria-label="{escape(label)}" '
        'fill="none" stroke="currentColor" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round" opacity=".85">'
        f"{body}</svg>"
    )


def _art_alt(key: str) -> str:
    """Teks alternatif gambar kartu pada bahasa aktif."""
    from ui.i18n import t

    return t(key)


def pipeline_art() -> str:
    """Berkas kode: lembar dengan sudut terlipat + tanda kurung sudut."""
    return _svg(_art_alt("ap.art_pipeline"),
                '<path d="M16 6h22l12 12v40a2 2 0 0 1-2 2H16a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z"/>'
                '<path d="M38 6v12h12"/>'
                '<path d="M26 34l-6 6 6 6"/>'
                '<path d="M38 34l6 6-6 6"/>')


def dataset_art() -> str:
    """Tumpukan data: tiga lapis silinder — lambang kumpulan baris data."""
    return _svg(_art_alt("ap.art_dataset"),
                '<ellipse cx="32" cy="14" rx="20" ry="7"/>'
                '<path d="M12 14v12c0 3.9 9 7 20 7s20-3.1 20-7V14"/>'
                '<path d="M12 26v12c0 3.9 9 7 20 7s20-3.1 20-7V26"/>'
                '<path d="M12 38v12c0 3.9 9 7 20 7s20-3.1 20-7V38"/>')


def review_art() -> str:
    """Dokumen bertanda centang — pengajuan yang ditinjau lalu disetujui."""
    return _svg(_art_alt("ap.art_review"),
                '<path d="M14 6h26l10 10v30a2 2 0 0 1-2 2H14a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z"/>'
                '<path d="M40 6v10h10"/>'
                '<path d="M20 26h16M20 34h10"/>'
                '<path d="M34 46l6 6 12-12"/>')


def users_art() -> str:
    """Sosok pengguna dengan kartu identitas — pengelolaan akun & peran."""
    return _svg(_art_alt("ap.art_users"),
                '<circle cx="24" cy="20" r="8"/>'
                '<path d="M10 48c0-7.7 6.3-14 14-14s14 6.3 14 14"/>'
                '<rect x="34" y="30" width="20" height="14" rx="2"/>'
                '<path d="M38 36h4M38 40h10"/>')


def card_html(*, art: str, tint: str, title: str, text: str,
              badge: str = "") -> str:
    """Markup kartu dua panel. Judul, teks, dan penanda peran di-escape."""
    badge_html = (f'<span class="ids-card-badge">{escape(badge)}</span>'
                  if badge else "")
    return (
        '<div class="ids-card">'
        f'<div class="ids-card-art" style="background:{tint};'
        f'height:{ART_HEIGHT_PX}px;">{art}</div>'
        '<div class="ids-card-body" '
        f'style="min-height:{BODY_MIN_HEIGHT_PX}px;">'
        f'<div class="ids-card-title">{escape(title)}{badge_html}</div>'
        f'<div class="ids-card-text">{escape(text)}</div>'
        "</div></div>"
    )


# Isi keempat kartu. Teksnya SINGKAT — keterangan lengkap tetap tinggal di panel
# instruksi/expander masing-masing jalur, bukan dipindah ke sini.
#
# `need` menunjuk hak yang diperlukan; halaman yang menghitungnya, kartu hanya
# membaca hasilnya.
# Nilainya KUNCI, bukan kalimat: konstanta modul dievaluasi sekali saat
# impor, jadi kalimat di sini akan membeku pada bahasa yang kebetulan aktif.
# `mode`, `need`, `tint`, dan `badge` tetap pengenal — ia tidak berbahasa.
CARDS = (
    {
        "mode": "pipeline",
        "title": "ap.card_pipeline_title",
        "text": "ap.card_pipeline_text",
        "button": "ap.card_pipeline_button",
        "tint": TINT_PIPELINE,
        "need": "upload",
        "badge": "",
        "denied": "ap.card_need_contributor",
    },
    {
        "mode": "dataset",
        "title": "ap.card_dataset_title",
        "text": "ap.card_dataset_text",
        "button": "ap.card_dataset_button",
        "tint": TINT_DATASET,
        "need": "upload",
        "badge": "",
        "denied": "ap.card_need_contributor",
    },
    {
        "mode": "review",
        "title": "ap.card_review_title",
        "text": "ap.card_review_text",
        "button": "ap.card_review_button",
        "tint": TINT_REVIEW,
        "need": "approve",
        "badge": "Research Admin",
        "denied": "ap.card_admin_only",
    },
    {
        "mode": "users",
        "title": "ap.card_users_title",
        "text": "ap.card_users_text",
        "button": "ap.card_users_button",
        "tint": TINT_USERS,
        "need": "manage_users",
        "badge": "Research Admin",
        "denied": "ap.card_admin_only",
    },
)

_ART = {"pipeline": pipeline_art, "dataset": dataset_art,
        "review": review_art, "users": users_art}

# Dua baris berisi dua kartu.
CARDS_PER_ROW = 2

#: Kartu yang HANYA milik Research Admin.
ADMIN_MODES = ("review", "users")

#: Satu baris bagi pengunjung: jalur peninjauan tetap disebut keberadaannya,
#: tanpa menampilkan kartunya. Kontributor TIDAK mendapat baris ini — bagi
#: mereka jalur itu memang bukan sesuatu yang bisa ditempuh.
VISITOR_ADMIN_NOTE = "ap.visitor_admin_note"


def visible_cards(*, may_approve: bool, may_manage_users: bool,
                  signed_in: bool, cards=CARDS) -> tuple:
    """Kartu yang DIRENDER. Murni — mudah diperiksa tanpa menjalankan halaman.

    Tiga keadaan:

    * **Research Admin** — keempat kartu.
    * **Kontributor** — hanya dua kartu unggah. Kartu admin tidak ditampilkan
      sama sekali: bagi kontributor, kartu mati hanya menjadi gangguan atas
      jalur yang memang tidak bisa mereka tempuh.
    * **Pengunjung** — dua kartu unggah (tombolnya mati, dengan ajakan masuk)
      plus satu baris keterangan; lihat :data:`VISITOR_ADMIN_NOTE`.

    Ini SEMATA tampilan. Penegakan izin tetap di fungsi aksinya
    (``require_approve`` / ``require_manage_users``), jadi menyembunyikan kartu
    tidak pernah menjadi satu-satunya penghalang.
    """
    admin = bool(may_approve or may_manage_users)
    if admin and signed_in:
        return tuple(cards)
    return tuple(c for c in cards if c["mode"] not in ADMIN_MODES)


def card_rows(cards=CARDS, per_row: int = CARDS_PER_ROW) -> list[tuple]:
    """Bagi kartu menjadi baris-baris berisi ``per_row`` kartu. Murni.

    Baris terakhir yang tidak penuh tetap dibagi rata oleh pemanggilnya
    (``st.columns(len(row))``), sehingga dua kartu mengisi lebar yang sama
    dengan empat kartu — tidak ada kolom kosong yang menganga.
    """
    cards = tuple(cards)
    return [cards[i:i + per_row] for i in range(0, len(cards), per_row)]


def render_upload_cards(*, may_upload: bool, may_approve: bool = False,
                        may_manage_users: bool = False,
                        signed_in: bool | None = None,
                        on_choose=None) -> str | None:
    """Keempat kartu, dua baris berisi dua. Mengembalikan mode terpilih atau None.

    Ketiga bendera izin HANYA menentukan tampilan tombol. Pemeriksaan yang
    sebenarnya tetap dilakukan fungsi aksinya (``require_upload`` /
    ``require_approve`` / ``require_manage_users``) — kartu ini tidak pernah
    menjadi satu-satunya penghalang, dan kartu yang tombolnya mati tetap
    menjelaskan fungsinya.

    """
    from ui.i18n import t

    allowed = {"upload": bool(may_upload), "approve": bool(may_approve),
               "manage_users": bool(may_manage_users)}

    # `signed_in` tidak diwajibkan supaya pemanggil lama tetap bekerja: bila
    # tidak diberikan, ia disimpulkan dari hak yang ada.
    if signed_in is None:
        signed_in = bool(may_upload or may_approve or may_manage_users)

    cards = visible_cards(may_approve=may_approve,
                          may_manage_users=may_manage_users,
                          signed_in=signed_in)

    chosen = None
    for row in card_rows(cards):
        cols = st.columns(len(row), gap="medium")
        for col, card in zip(cols, row):
            with col:
                permitted = allowed.get(card["need"], False)
                st.markdown(
                    card_html(art=_ART[card["mode"]](), tint=card["tint"],
                              title=t(card["title"]), text=t(card["text"]),
                              badge=card["badge"]),
                    unsafe_allow_html=True)

                # SATU-SATUNYA keterangan pada kartu: sebab tombolnya mati.
                # Baris jumlah antrean dahulu juga tinggal di sini; ia dibuang
                # karena angkanya sudah tampak begitu bagian peninjauan dibuka,
                # dan mengulanginya di halaman muka berarti satu kueri basis
                # data untuk kabar yang belum tentu dibaca.
                note = ("" if permitted
                        else f"{t(card['denied'])} {t('ap.card_denied_hint')}")
                if note:
                    st.markdown(
                        f'<div class="ids-card-note">{escape(note)}</div>',
                        unsafe_allow_html=True)

                if st.button(t(card["button"]),
                             key=f"contrib_go_{card['mode']}",
                             use_container_width=True, type="primary",
                             disabled=not permitted):
                    chosen = card["mode"]
                    if on_choose is not None:
                        on_choose(chosen)

    # Pengunjung: keberadaan jalur admin tetap disebut, kartunya tidak.
    if not signed_in:
        st.markdown(
            f'<div class="ids-card-note">'
            f'{escape(t(VISITOR_ADMIN_NOTE))}</div>',
            unsafe_allow_html=True)
    return chosen

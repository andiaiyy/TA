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


def pipeline_art() -> str:
    """Berkas kode: lembar dengan sudut terlipat + tanda kurung sudut."""
    return _svg("Berkas kode",
                '<path d="M16 6h22l12 12v40a2 2 0 0 1-2 2H16a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z"/>'
                '<path d="M38 6v12h12"/>'
                '<path d="M26 34l-6 6 6 6"/>'
                '<path d="M38 34l6 6-6 6"/>')


def dataset_art() -> str:
    """Tumpukan data: tiga lapis silinder — lambang kumpulan baris data."""
    return _svg("Tumpukan data",
                '<ellipse cx="32" cy="14" rx="20" ry="7"/>'
                '<path d="M12 14v12c0 3.9 9 7 20 7s20-3.1 20-7V14"/>'
                '<path d="M12 26v12c0 3.9 9 7 20 7s20-3.1 20-7V26"/>'
                '<path d="M12 38v12c0 3.9 9 7 20 7s20-3.1 20-7V38"/>')


def review_art() -> str:
    """Dokumen bertanda centang — pengajuan yang ditinjau lalu disetujui."""
    return _svg("Dokumen dengan tanda centang",
                '<path d="M14 6h26l10 10v30a2 2 0 0 1-2 2H14a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z"/>'
                '<path d="M40 6v10h10"/>'
                '<path d="M20 26h16M20 34h10"/>'
                '<path d="M34 46l6 6 12-12"/>')


def users_art() -> str:
    """Sosok pengguna dengan kartu identitas — pengelolaan akun & peran."""
    return _svg("Sosok pengguna",
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
CARDS = (
    {
        "mode": "pipeline",
        "title": "Unggah Pipeline",
        "text": "Berkas .py pipeline. Diperiksa statis terhadap kontrak & "
                "aturan keamanan sebelum ditinjau.",
        "button": "Unggah pipeline",
        "tint": TINT_PIPELINE,
        "need": "upload",
        "badge": "",
        "denied": "Perlu akun Kontributor.",
    },
    {
        "mode": "dataset",
        "title": "Unggah Dataset",
        "text": "Berkas .csv / .ndjson / .jsonl. Langsung diperiksa "
                "kecocokannya dengan tiap research pipeline.",
        "button": "Unggah dataset",
        "tint": TINT_DATASET,
        "need": "upload",
        "badge": "",
        "denied": "Perlu akun Kontributor.",
    },
    {
        "mode": "review",
        "title": "Peninjauan Pengajuan",
        "text": "Baca pengajuan yang masuk, lalu setujui atau tolak berikut "
                "catatan alasannya.",
        "button": "Buka peninjauan",
        "tint": TINT_REVIEW,
        "need": "approve",
        "badge": "Research Admin",
        "denied": "Khusus Research Admin.",
    },
    {
        "mode": "users",
        "title": "Kelola Pengguna",
        "text": "Aktifkan akun yang menunggu persetujuan, ubah peran, dan "
                "lihat daftar pengguna.",
        "button": "Buka kelola pengguna",
        "tint": TINT_USERS,
        "need": "manage_users",
        "badge": "Research Admin",
        "denied": "Khusus Research Admin.",
    },
)

_ART = {"pipeline": pipeline_art, "dataset": dataset_art,
        "review": review_art, "users": users_art}

# Dua baris berisi dua kartu.
CARDS_PER_ROW = 2


def card_rows(cards=CARDS, per_row: int = CARDS_PER_ROW) -> list[tuple]:
    """Bagi kartu menjadi baris-baris berisi ``per_row`` kartu. Murni."""
    cards = tuple(cards)
    return [cards[i:i + per_row] for i in range(0, len(cards), per_row)]


def render_upload_cards(*, may_upload: bool, may_approve: bool = False,
                        may_manage_users: bool = False,
                        counts: dict | None = None,
                        on_choose=None) -> str | None:
    """Keempat kartu, dua baris berisi dua. Mengembalikan mode terpilih atau None.

    Ketiga bendera izin HANYA menentukan tampilan tombol. Pemeriksaan yang
    sebenarnya tetap dilakukan fungsi aksinya (``require_upload`` /
    ``require_approve`` / ``require_manage_users``) — kartu ini tidak pernah
    menjadi satu-satunya penghalang, dan kartu yang tombolnya mati tetap
    menjelaskan fungsinya.

    ``counts`` opsional: {"review": n, "users": n} untuk menambahkan satu baris
    keterangan jumlah antrean pada kartu yang bersangkutan.
    """
    allowed = {"upload": bool(may_upload), "approve": bool(may_approve),
               "manage_users": bool(may_manage_users)}
    counts = counts or {}

    chosen = None
    for row in card_rows():
        cols = st.columns(len(row), gap="medium")
        for col, card in zip(cols, row):
            with col:
                permitted = allowed.get(card["need"], False)
                st.markdown(
                    card_html(art=_ART[card["mode"]](), tint=card["tint"],
                              title=card["title"], text=card["text"],
                              badge=card["badge"]),
                    unsafe_allow_html=True)

                note = counts.get(card["mode"], "")
                if not permitted:
                    # Kartu tetap tampil; keterangannya menunjuk ke pemilih mode
                    # di sidebar, karena tidak ada lagi tombol "Masuk" di sini.
                    note = f"{card['denied']} {SIGN_IN_HINT}"
                if note:
                    st.markdown(
                        f'<div class="ids-card-note">{escape(note)}</div>',
                        unsafe_allow_html=True)

                if st.button(card["button"], key=f"contrib_go_{card['mode']}",
                             use_container_width=True, type="primary",
                             disabled=not permitted):
                    chosen = card["mode"]
                    if on_choose is not None:
                        on_choose(chosen)
    return chosen

"""
POLA BAKU sebuah "bagian" halaman — didefinisikan SEKALI, dipakai ulang.

Bagian "Pilih algoritma" dan "Execute" dulu tampil berbeda dari bagian di
atasnya (Dataset Selection, Pipeline Selection): yang pertama sebenarnya bukan
bagian sama sekali — hanya label widget yang tersembunyi di dalam blok lain —
dan yang kedua berjudul benar tetapi isinya berserakan tanpa pengelompokan.

Modul ini menghapus kemungkinan itu terulang: judul bagian TIDAK boleh ditulis
langsung dengan ``st.header``/``st.subheader`` di halaman, melainkan lewat
:func:`render_section`. Nilai jaraknya diambil dari ``ui/components/theme`` —
sumber yang sama dengan stylesheet aplikasi — sehingga pola ini tidak mungkin
berbeda antar bagian.

Nilai konkret pola:

======================  ==========================================
Ukuran judul            ``st.header`` (satu tingkat, sama di semua bagian)
Perataan judul          kiri (``text_alignment="left"``)
Jarak ANTAR-bagian      :data:`SECTION_GAP` (dari ``theme.GAP_SECTION``)
Jarak judul → isi       :data:`TITLE_GAP` (dari ``theme.GAP_IN_BLOCK``)
Keterangan judul        ``help=`` pada judulnya, bukan baris teks kecil
Pembungkus isi          ``st.container(border=True)`` lewat :func:`section_body`
Tombol aksi utama       ``type="primary"`` — tepat SATU per bagian
======================  ==========================================
"""
from __future__ import annotations

import streamlit as st

from ui.components import theme

#: Jarak vertikal ANTAR bagian (di atas judul).
SECTION_GAP = theme.GAP_SECTION
#: Jarak judul bagian ke isinya.
TITLE_GAP = theme.GAP_IN_BLOCK
#: Perataan judul bagian. Satu garis kiri untuk seluruh halaman.
SECTION_ALIGN = "left"

#: Kelas penanda wadah isi bagian — dipakai stylesheet terpusat.
SECTION_BODY_CLASS = "ids-section-body"


def render_section(title: str, *, help: str | None = None) -> None:
    """Buka sebuah bagian dengan judul BAKU.

    ``help`` adalah tempat keterangan bagian — bukan baris teks kecil di bawah
    judul. Ini juga yang menjaga kuota teks kecil per halaman tetap terpenuhi.
    """
    st.header(title, anchor=False, help=help, text_alignment=SECTION_ALIGN)


#: Awalan kunci container penanda prosa — sama dengan `theme.PROSE_KEY`.
PROSE_KEY = theme.PROSE_KEY


#: Kunci katalog label tombol kembali. SATU label untuk seluruh halaman.
BACK_LABEL_KEY = "ap.btn_back"


def back_button(target=None, *, key: str, **kwargs) -> bool:
    """Tombol "kembali", DIDEFINISIKAN SEKALI.

    Sebelumnya tiap halaman menulis tombolnya sendiri: "← Katalog",
    "‹ Kembali ke antrean", "‹ Kembali ke peninjauan", "‹ Kembali ke
    daftar research". Empat label, dua bentuk panah, dan satu di antaranya
    selebar kolomnya sementara sisanya seukuran teksnya — empat tombol yang
    tugasnya sama tetapi tidak ada dua yang terlihat sama.

    Ke mana tombol ini kembali sudah dikatakan halamannya sendiri: ia berdiri
    di puncak tampilan yang sedang dibuka, dan hanya ada satu tempat untuk
    kembali dari sana.

    ``target`` boleh kolom atau wadah; tanpa itu ia digambar di badan halaman.
    """
    from ui.i18n import t

    tempat = target if target is not None else st
    return tempat.button(t(BACK_LABEL_KEY), key=key, **kwargs)


def prose(text: str, *, key: str) -> None:
    """PROSA: kalimat penjelasan yang lebar bacanya dibatasi.

    Dipakai HANYA untuk kalimat & paragraf. Blok data — tabel, blok kode,
    tampilan perbandingan, daftar berkas, pasangan label-nilai, baris katalog,
    formulir — tidak boleh melewati fungsi ini: semuanya mengikuti lebar penuh
    kolomnya.

    Batasnya dipasang lewat kelas `st-key-<key>` yang ditambahkan Streamlit pada
    container berkunci, bukan lewat aturan umum yang mengenai setiap paragraf.
    Itu pembedanya: aturan umum tidak bisa membedakan prosa dari blok data, dan
    dulu justru itulah yang membuat tabel & kotak angka berhenti di ~3/4 lebar.

    ``key`` wajib dan harus unik per pemanggilan dalam satu render.
    """
    with st.container(key=f"{PROSE_KEY}{key}"):
        st.markdown(text)


def section_body(*, border: bool = True):
    """Pembungkus isi sebuah bagian.

    Dipakai untuk mengelompokkan elemen pendukung (status, keterangan, kontrol)
    supaya tidak berserakan di antara judul dan tombol aksinya. Mengembalikan
    context manager, jadi pemakaiannya ``with section_body(): ...``.
    """
    return st.container(border=border)


def render_facts(pairs, *, columns: int = 2) -> None:
    """Pasangan label–nilai RINGKAS — bukan paragraf.

    Dipakai untuk mengisi kolom di samping sebuah kontrol dengan informasi yang
    memang sudah dihitung di tempat lain (diagnosa, registry, ``get_info()``,
    basis data). Bentuknya sengaja tabel dua kolom: menambah kepadatan visual
    tanpa menambah satu kalimat pun.

    Pasangan yang nilainya kosong DIBUANG — tidak ada baris "—" yang hanya
    memenuhi ruang. Ukuran teksnya sama dengan teks isi, jadi tidak menambah
    hitungan "teks kecil" halaman.

    ``columns`` membagi pasangan ke beberapa kolom DI DALAM blok ini. Blok
    ringkasan berada di BAWAH kontrolnya (bukan di sebelahnya), jadi tanpa
    pembagian ini ia akan menjadi daftar tinggi satu nilai per baris dan
    membuat halaman panjang. Pembagiannya mendatar per baris, sehingga urutan
    bacanya kiri→kanan lalu turun.
    """
    from html import escape

    kept = [(label, value) for label, value in (pairs or [])
            if value is not None and str(value).strip() not in ("", "-")]
    if not kept:
        return

    per_row = max(int(columns), 1)
    body = []
    for start in range(0, len(kept), per_row):
        cells = "".join(
            f'<th class="ids-fact-k">{escape(str(label))}</th>'
            f'<td class="ids-fact-v">{escape(str(value))}</td>'
            for label, value in kept[start:start + per_row])
        # Baris terakhir bisa kurang dari `per_row` pasangan; sel kosong
        # ditambahkan supaya kolomnya tetap sejajar dengan baris di atasnya.
        missing = per_row - len(kept[start:start + per_row])
        cells += '<th class="ids-fact-k"></th><td class="ids-fact-v"></td>' * missing
        body.append(f"<tr>{cells}</tr>")

    st.html(f'<table class="ids-facts">{"".join(body)}</table>')


#: Nilai yang lebih panjang daripada ini mengambil sisa lebar barisnya
#: sendiri. Catatan panjang yang melipat menjadi empat baris di dalam kolom
#: sempit, sementara separuh baris di sebelahnya kosong, adalah persis yang
#: dihindari ambang ini.
DETAIL_WIDE_AT = 48


def detail_facts(pairs, *, columns: int = 2, wide_at: int = DETAIL_WIDE_AT):
    """Pasangan label-nilai sebagai SATU formulir detail yang datar.

    Bedanya dengan :func:`render_facts`: hierarkinya dibawa ukuran, bobot, dan
    warna alih-alih garis, dan sebuah nilai PANJANG mengambil sisa lebar
    barisnya sendiri. Tanpa yang terakhir, catatan pengaju melipat menjadi
    empat baris di dalam kolom sempit sementara separuh baris di sebelahnya
    kosong.

    Pasangan yang nilainya kosong DIBUANG: baris berisi tanda hubung hanya
    memberi tahu bahwa tidak ada apa-apa di situ.
    """
    from html import escape

    isi = [(str(label), str(value)) for label, value in (pairs or [])
           if value is not None and str(value).strip() not in ("", "-")]
    if not isi:
        return

    per_baris = max(int(columns), 1)
    baris: list[str] = []
    antre: list[tuple[str, str]] = []

    def _sel(label: str, nilai: str, *, lebar: bool = False) -> str:
        kelas = "ids-fact-v ids-fact-wide" if lebar else "ids-fact-v"
        span = ' colspan="%d"' % (per_baris * 2 - 1) if lebar else ""
        return ('<th class="ids-fact-k">%s</th><td class="%s"%s>%s</td>'
                % (escape(label), kelas, span, escape(nilai)))

    def _buang_antrean() -> None:
        """Gambar pasangan yang sudah terkumpul, lalu kosongkan antreannya."""
        while antre:
            potongan = antre[:per_baris]
            del antre[:per_baris]
            sel = "".join(_sel(l, v) for l, v in potongan)
            # Baris terakhir bisa kurang dari `per_baris` pasangan; sel kosong
            # menjaga kolomnya tetap sejajar dengan baris di atasnya.
            sel += ('<th class="ids-fact-k"></th><td class="ids-fact-v"></td>'
                    * (per_baris - len(potongan)))
            baris.append("<tr>%s</tr>" % sel)

    for label, nilai in isi:
        if len(nilai) > wide_at:
            # Urutan bacanya dijaga: yang sudah mengantre digambar lebih dulu,
            # baru baris lebar ini.
            _buang_antrean()
            baris.append("<tr>%s</tr>" % _sel(label, nilai, lebar=True))
        else:
            antre.append((label, nilai))
    _buang_antrean()

    st.html('<table class="ids-facts ids-facts-detail">%s</table>'
            % "".join(baris))


def render_counts(pairs) -> None:
    """KOTAK berisi sel-sel angka — bukan satu baris teks yang menempel.

    Tiap sel: ANGKA besar dan tegas di atas, LABEL kecil di bawahnya, dengan
    jarak yang jelas di antaranya. Sel-selnya berdampingan di dalam satu wadah
    berbatas, dipisahkan garis tipis. Sebelumnya ketiganya ditulis sebagai satu
    baris ("4 dataset tersedia · 6 algoritma · …") sehingga angka dan labelnya
    sulit dibedakan.

    ``pairs`` boleh berupa ``(label, nilai)`` atau ``(label, nilai, tooltip)``.
    Keterangan tambahan masuk ke tooltip, bukan ke dalam sel — label di dalam
    sel sengaja dijaga pendek.

    Semua angkanya harus datang dari sumber nyata (isi folder, registry, basis
    data); modul ini tidak pernah mengarang angka dan tidak pernah mengubah
    nilai yang diberikan padanya.
    """
    from html import escape

    cells = []
    for pair in (pairs or []):
        label, value = pair[0], pair[1]
        tooltip = pair[2] if len(pair) > 2 else ""
        if value is None:
            continue
        title = f' title="{escape(str(tooltip))}"' if tooltip else ""
        cells.append(
            f'<div class="ids-count"{title}>'
            f'<span class="ids-count-n">{escape(str(value))}</span>'
            f'<span class="ids-count-l">{escape(str(label))}</span></div>')
    if not cells:
        return
    st.html(f'<div class="ids-counts">{"".join(cells)}</div>')

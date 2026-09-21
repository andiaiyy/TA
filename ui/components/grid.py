"""Tabel yang barisnya dapat DIPILIH — satu mekanisme untuk seluruh aplikasi.

Dua daftar memakai bentuk ini: riwayat eksperimen dan antrean peninjauan.
Keduanya menjawab pertanyaan yang sama — "yang mana yang saya maksud?" — jadi
keduanya harus dijawab dengan cara yang sama: satu tabel berkolom, kolomnya
dapat diurutkan, klik barisnya, halamannya terbuka. Daftar pipeline terdaftar
dahulu yang ketiga; ia sudah dicabut bersama tabel versi algoritma.

Sebelum modul ini ada, daftar itu digambar sebagai tabel HTML mati DITAMBAH
tumpukan tombol berisi data yang sama. Dua benda untuk satu maksud, dan yang
dapat diklik justru yang tidak berkolom: tidak dapat diurutkan, tidak dapat
dibandingkan berdampingan, dan bertambah panjang seiring bertambahnya baris.

Nilai selnya diambil dari :func:`ui.components.tables.cell` — formatter yang
sama dengan tabel HTML — sehingga waktu tampil identik di mana pun ia muncul.
Kolom ANGKA sengaja dibiarkan numerik, tidak diubah jadi teks, supaya
pengurutannya benar (11 di atas 9, bukan sebaliknya).
"""
from __future__ import annotations

from ui.components import tables as tbl

#: Kolom pembawa identitas baris. Disembunyikan dari pandangan tetapi ikut
#: terkirim, dan itulah yang dibaca kembali saat sebuah baris dipilih.
ID_FIELD = "_full_id"

#: Akhiran kolom penyimpan nilai PENUH untuk tooltip. Sebuah catatan tinjauan
#: yang panjang terpotong pada lebar kolomnya; isi lengkapnya tetap harus dapat
#: dicapai, dan tidak boleh hilang hanya karena kolomnya sempit.
TIP_SUFFIX = "__tip"

#: Akhiran kolom penyimpan KEADAAN sebuah sel — dibawa apa adanya, tidak
#: ditampilkan, dan dibaca gaya selnya. Dipisah dari nilai tampilnya karena
#: keadaan adalah pengenal ("bersih"/"peringatan"/"bermasalah") sedangkan yang
#: tampil adalah kalimat berbahasa: mewarnai berdasarkan kalimatnya akan
#: berhenti bekerja begitu bahasanya berganti.
STATE_SUFFIX = "__state"

#: Keadaan → nama kelas CSS pilnya. Kelas, bukan gaya inline: gaya inline
#: menuntut sebuah `cellRenderer`, dan renderer yang mengembalikan elemen DOM
#: diserahkan pembungkus React st_aggrid langsung ke React — yang menolaknya
#: dengan "Objects are not valid as a React child" dan menggugurkan SELURUH
#: tabel. Aturan kelas bersifat deklaratif: AgGrid yang memasangnya, dan CSS
#: yang mewarnainya.
STATE_CLASS = {
    "ok": "ids-pill-ok",
    "warn": "ids-pill-warn",
    "bad": "ids-pill-bad",
}

#: Keadaan → rona latar & warna teks. Hijau/kuning/merah yang SAMA dengan yang
#: dipakai halaman peninjauan, diff versi, dan chip katalog — supaya "merah"
#: berarti hal yang sama di seluruh aplikasi.
#:
#: `rgba` beralfa rendah, BUKAN heksa pekat: rona tipis menjadi pastel di tema
#: terang dan rona gelap di tema gelap, sementara teksnya mengikuti
#: `currentColor` sehingga tetap terbaca pada keduanya. Warna pekat pada latar
#: yang tidak diketahui adalah cara membuat teks hilang.
STATE_TINT = {
    "ok": "rgba(46,160,67,.16)",
    "warn": "rgba(200,150,60,.20)",
    "bad": "rgba(200,70,70,.20)",
}

def state_badge(text: str, state: str) -> str:
    """Satu pil keadaan, sewarna dengan seluruh aplikasi.

    Ronanya dibaca dari KEADAAN dan bukan dari kalimatnya: mewarnai
    berdasarkan teks berbahasa akan berhenti bekerja begitu pengguna berganti
    bahasa.

    Tinggal di sini, bersama `STATE_TINT`, sebab dua halaman memakainya —
    tabel berkas pengajuan dan tabel berkas pipeline aktif. Keduanya menjawab
    pertanyaan yang sama ("berkas ini lolos periksa atau tidak"), jadi
    keduanya harus terlihat sama.
    """
    from html import escape

    latar = STATE_TINT.get(state, STATE_TINT["warn"])
    return (f'<span class="ids-badge ids-badge-solid" '
            f'style="background:{latar};">{escape(str(text or ""))}</span>')


#: Tinggi maksimum tabel dalam piksel, dan tinggi satu baris. Baris dinaikkan
#: dari 32 menjadi 38 supaya pil keadaan punya ruang vertikal dan barisnya
#: terbaca lapang — dan `height_for` memakai angka yang SAMA dengan `rowHeight`
#: yang dikirim ke AgGrid, sebab dua nilai yang berbeda akan memunculkan gulir
#: vertikal pada tabel yang sebenarnya muat.
MAX_HEIGHT = 400
ROW_HEIGHT = 38
HEAD_HEIGHT = 80


def grid_css() -> dict:
    """Gaya tabel AgGrid, DIBANGKITKAN dari konstanta tema.

    PENTING — mengapa ini ada dan bukan aturan di `theme.py`: AgGrid dirender
    sebagai komponen Streamlit, yaitu **iframe**. Stylesheet aplikasi tidak
    pernah menjangkau isinya, jadi satu-satunya jalan yang didukung adalah
    parameter `custom_css` milik `AgGrid()`, yang menyuntikkan `<style>` ke
    dalam dokumen iframe itu.

    Karena itu ada DUA konsumen untuk nilai yang sama (garis, rona header,
    font, padding). Nilainya diambil dari `theme` supaya bukan dua salinan:
    mengubah warna garis di tema mengubah keduanya.

    Nilainya ditulis TANPA titik koma: st_aggrid sendiri yang
    menyisipkannya saat merakit — `n += prop + ": " + value + ""` di
    bundel frontend yang terpasang. Itu kontrak yang aturan multi-properti
    di sini bergantung padanya: tanpa pemisah, CSS membuang SELURUH blok
    tanpa galat. Karena itu ada tes yang memeriksanya pada bundel yang
    benar-benar terpasang, bukan mempercayainya dari ingatan.
    """
    from ui.components import theme

    return {
        # Bingkai luar & kisi dicabut: tabel yang ditiru tidak punya kotak.
        ".ag-root-wrapper": {"border": "none",
                             "background-color": "transparent"},
        ".ag-header": {"background-color": f"{theme.HEAD_TINT}",
                       "border-bottom": f"1px solid {theme.LINE_SOFT}"},
        ".ag-header-cell": {"font-weight": f"{theme.WEIGHT_STRONG}",
                            "font-size": f"{theme.FONT_BODY}"},
        # Garis HANYA di bawah baris — tidak ada garis antar kolom.
        ".ag-row": {"border-bottom": f"1px solid {theme.LINE_SOFT}",
                    "border-top": "none",
                    "background-color": "transparent"},
        ".ag-cell": {"font-size": f"{theme.FONT_BODY}",
                     "display": "flex",
                     "align-items": "center",
                     "border": "none"},
        # Baris yang disorot menandai bahwa ia DAPAT diklik. Rona tipis, bukan
        # warna pekat: latar iframe mengikuti tema terang/gelap pengguna.
        ".ag-row-hover": {"background-color": f"{theme.HEAD_TINT}",
                          "cursor": "pointer"},
        # PIL keadaan. Yang diberi latar adalah `.ag-cell-value` — span teks di
        # dalam selnya — bukan selnya sendiri: span itu inline, jadi pilnya
        # memeluk kata alih-alih memenuhi lebar kolom.
        **{f".ag-cell.{kelas} .ag-cell-value": {
            "background-color": STATE_TINT[keadaan],
            "border-radius": "999px",
            "padding": ".1rem .55rem",
            "font-weight": f"{theme.WEIGHT_STRONG}",
            "white-space": "nowrap",
        } for keadaan, kelas in STATE_CLASS.items()},
    }


def _tip_needed(col: dict) -> bool:
    """Kolom yang nilai tampilnya TIDAK utuh perlu tooltip.

    Dahulu ada dua sebab: kolom yang menunjuk nilai penuhnya lewat
    ``title_key``, dan kolom hash yang dipendekkan penyajinya. Jenis hash sudah
    dicabut, jadi tinggal sebab yang pertama — dan ia masih dipakai kolom
    "Catatan" pada riwayat tinjauan.
    """
    return bool(col.get("title_key"))


def dataframe(columns, rows, *, id_key: str, state_of=None,
              state_column: str = ""):
    """DataFrame siap-tampil: kolom bernama sesuai LABEL-nya pada bahasa aktif.

    ``id_key`` menyebut kolom baris mana yang menjadi identitas — id pengajuan,
    id pipeline, id eksperimen. Nilainya dibawa apa adanya di :data:`ID_FIELD`
    dan tidak pernah ditampilkan.

    ``state_of`` OPSIONAL: fungsi baris → keadaan ("ok"/"warn"/"bad") yang
    dipakai mewarnai sel pada ``state_column``. Keadaannya dibawa TERPISAH dari
    nilai tampilnya karena ia pengenal, sedangkan yang tampil adalah kalimat
    berbahasa — mewarnai berdasarkan kalimatnya akan berhenti bekerja begitu
    bahasanya berganti.

    Hanya SATU kolom keadaan yang ditulis, bukan satu per kolom: seluruh isi
    DataFrame menyeberang ke browser sebagai Arrow, dan kolom yang tidak dibaca
    siapa pun tetap menambah muatan tiap kali tabelnya digambar ulang.
    """
    import pandas as pd

    columns = list(columns or [])
    state_field = next((tbl._label(c) + STATE_SUFFIX for c in columns
                        if c["key"] == state_column), "") if state_column else ""
    data = []
    for row in rows or []:
        rec = {ID_FIELD: row.get(id_key)}
        for col in columns:
            label = tbl._label(col)
            text, full = tbl.cell(row, col)
            # Angka tetap angka: diubah jadi teks, "11" akan berurut sebelum
            # "9" dan tabel yang diurutkan justru menyesatkan.
            rec[label] = row.get(col["key"]) if col["kind"] == tbl.KIND_NUM \
                else text
            if _tip_needed(col):
                rec[label + TIP_SUFFIX] = full
        if state_of is not None and state_field:
            rec[state_field] = state_of(row)
        data.append(rec)
    return pd.DataFrame(data)


def state_class_rules(state_field: str) -> dict:
    """Aturan kelas sel: keadaan mana → kelas pil mana.

    Bentuk yang sama dengan `.ids-badge` di seluruh aplikasi — radius penuh,
    padding kecil, bobot tebal — supaya "keadaan" terbaca sebagai satu penanda,
    bukan sebagai kolom yang kebetulan berwarna. Gayanya sendiri ada di
    `grid_css()`; di sini hanya PEMASANGAN kelasnya.

    Deklaratif dengan sengaja. Percobaan pertama memakai `cellRenderer` yang
    membangun `document.createElement('span')`; pembungkus React st_aggrid
    menyerahkan nilai kembalian itu ke React, dan React menolak elemen DOM
    sebagai anak — "Minified React error #31" — sehingga SELURUH tabel gagal
    digambar. `cellClassRules` tidak pernah melewati React: AgGrid sendiri yang
    menambahkan kelasnya ke elemen sel.

    Ekspresinya dievaluasi AgGrid dengan `data` di dalam lingkupnya. Keadaan
    yang tidak dikenal tidak cocok dengan aturan mana pun, jadi selnya tetap
    teks biasa tanpa pil — memberi penanda berwarna pada sesuatu yang tidak
    dipahami akan menyampaikan keterangan yang tidak dimiliki siapa pun.

    Warna tetap BUKAN satu-satunya pembawa keterangan: teks di dalam pil adalah
    kata keadaannya ("Cocok", "Tidak cocok", "lolos tanpa catatan").
    """
    return {kelas: f"data['{state_field}'] == '{keadaan}'"
            for keadaan, kelas in STATE_CLASS.items()}


def options(df, columns, *, selection_mode: str = "single",
            use_checkbox: bool = False, state_column: str = "") -> dict:
    """Setelan grid: kolom dapat diurutkan, identitas & tooltip disembunyikan.

    ``selection_mode`` "single" untuk daftar yang membuka SATU hal — membuka
    dua pipeline sekaligus tidak berarti apa-apa — dan "multiple" untuk daftar
    yang memang membandingkan.

    ``state_column`` menyebut kunci kolom yang selnya DIWARNAI menurut keadaan.
    Warnanya menandai keadaan, tidak menghias, dan tidak pernah menjadi
    satu-satunya pembawa keterangan: teks selnya tetap menyebut keadaannya.
    """
    from st_aggrid import GridOptionsBuilder

    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(sortable=True, resizable=True, filterable=False)
    gb.configure_selection(selection_mode=selection_mode,
                           use_checkbox=use_checkbox)
    gb.configure_column(ID_FIELD, hide=True)
    for col in columns or []:
        if _tip_needed(col):
            label = tbl._label(col)
            gb.configure_column(label + TIP_SUFFIX, hide=True)
            gb.configure_column(label, tooltipField=label + TIP_SUFFIX)
        if state_column and col["key"] == state_column:
            label = tbl._label(col)
            gb.configure_column(label + STATE_SUFFIX, hide=True)
            gb.configure_column(
                label,
                cellClassRules=state_class_rules(label + STATE_SUFFIX))

    built = gb.build()
    # Tinggi baris & header dikirim EKSPLISIT, dengan angka yang sama dengan
    # yang dipakai `height_for` — lihat ROW_HEIGHT.
    built["rowHeight"] = ROW_HEIGHT
    built["headerHeight"] = ROW_HEIGHT
    built["suppressHorizontalScroll"] = False
    built["enableBrowserTooltips"] = True
    # Lebar kolom diatur lewat gridOptions, bukan `fit_columns_on_grid_load`
    # yang sudah usang di st-aggrid.
    built["autoSizeStrategy"] = {"type": "fitGridWidth"}
    return built


def height_for(row_count: int) -> int:
    """Tinggi tabel: cukup untuk isinya, tetapi tidak menelan halaman."""
    return min(MAX_HEIGHT, HEAD_HEIGHT + ROW_HEIGHT * max(int(row_count), 1))


def selected_ids(response, *, cast=None) -> list:
    """Identitas baris yang dipilih.

    Bentuk kembalian AgGrid berbeda antar versi — DataFrame pada sebagian
    versi, list of dict pada sebagian lain — jadi keduanya ditangani. Yang
    kosong menghasilkan daftar kosong, bukan galat.
    """
    import pandas as pd

    sel = getattr(response, "get", lambda _k: None)("selected_rows")
    if isinstance(sel, pd.DataFrame):
        if sel.empty or ID_FIELD not in sel.columns:
            return []
        values = sel[ID_FIELD].tolist()
    elif isinstance(sel, list):
        values = [r.get(ID_FIELD) for r in sel if isinstance(r, dict)]
    else:
        return []
    values = [v for v in values if v is not None and v != ""]
    return [cast(v) for v in values] if cast else values


def selected_id(response, *, cast=None):
    """Identitas SATU baris terpilih, atau None."""
    found = selected_ids(response, cast=cast)
    return found[0] if found else None


def render(columns, rows, *, id_key: str, key: str,
           selection_mode: str = "single", cast=None,
           state_column: str = "", state_of=None):
    """Gambar tabelnya, kembalikan identitas baris terpilih (atau None).

    Seluruh pemanggil memakai jalur ini, sehingga mengubah perilaku tabel
    berarti mengubahnya di SATU tempat — bukan menambal tiga salinan yang
    perlahan menyimpang satu sama lain.
    """
    from st_aggrid import AgGrid, GridUpdateMode

    columns = list(columns or [])
    rows = list(rows or [])
    df = dataframe(columns, rows, id_key=id_key, state_of=state_of,
                   state_column=state_column)
    response = AgGrid(
        df,
        gridOptions=options(df, columns, selection_mode=selection_mode,
                            state_column=state_column),
        allow_unsafe_jscode=True,
        theme="streamlit",
        custom_css=grid_css(),
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        height=height_for(len(rows)),
        key=key,
    )
    return selected_id(response, cast=cast)

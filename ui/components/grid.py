"""Tabel yang barisnya dapat DIPILIH — satu mekanisme untuk seluruh aplikasi.

Tiga daftar memakai bentuk ini: riwayat eksperimen, antrean peninjauan, dan
daftar pipeline terdaftar. Ketiganya menjawab pertanyaan yang sama — "yang
mana yang saya maksud?" — jadi ketiganya harus dijawab dengan cara yang sama:
satu tabel berkolom, kolomnya dapat diurutkan, klik barisnya, halamannya
terbuka.

Sebelum modul ini ada, daftar pipeline terdaftar digambar sebagai tabel HTML
mati DITAMBAH tumpukan tombol berisi data yang sama. Dua benda untuk satu
maksud, dan yang dapat diklik justru yang tidak berkolom: tidak dapat
diurutkan, tidak dapat dibandingkan berdampingan, dan bertambah panjang
seiring bertambahnya pipeline.

Nilai selnya diambil dari :func:`ui.components.tables.cell` — formatter yang
sama dengan tabel HTML — sehingga hash, waktu, dan nomor versi tampil identik
di mana pun ia muncul. Kolom ANGKA sengaja dibiarkan numerik, tidak diubah
jadi teks, supaya pengurutannya benar (11 di atas 9, bukan sebaliknya).
"""
from __future__ import annotations

from ui.components import tables as tbl

#: Kolom pembawa identitas baris. Disembunyikan dari pandangan tetapi ikut
#: terkirim, dan itulah yang dibaca kembali saat sebuah baris dipilih.
ID_FIELD = "_full_id"

#: Akhiran kolom penyimpan nilai PENUH untuk tooltip. Kolom hash menampilkan
#: 12 karakter; yang lengkap tetap harus dapat dicapai, dan alasan sebuah
#: pipeline dianggap rusak tidak boleh hilang hanya karena kolomnya sempit.
TIP_SUFFIX = "__tip"

#: Tinggi maksimum tabel dalam piksel, dan tinggi satu baris.
MAX_HEIGHT = 400
ROW_HEIGHT = 32
HEAD_HEIGHT = 80


def _tip_needed(col: dict) -> bool:
    """Kolom yang nilai tampilnya TIDAK utuh perlu tooltip."""
    return bool(col.get("title_key")) or col["kind"] == tbl.KIND_HASH


def dataframe(columns, rows, *, id_key: str):
    """DataFrame siap-tampil: kolom bernama sesuai LABEL-nya pada bahasa aktif.

    ``id_key`` menyebut kolom baris mana yang menjadi identitas — id pengajuan,
    id pipeline, id eksperimen. Nilainya dibawa apa adanya di :data:`ID_FIELD`
    dan tidak pernah ditampilkan.
    """
    import pandas as pd

    columns = list(columns or [])
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
        data.append(rec)
    return pd.DataFrame(data)


def options(df, columns, *, selection_mode: str = "single",
            use_checkbox: bool = False) -> dict:
    """Setelan grid: kolom dapat diurutkan, identitas & tooltip disembunyikan.

    ``selection_mode`` "single" untuk daftar yang membuka SATU hal — membuka
    dua pipeline sekaligus tidak berarti apa-apa — dan "multiple" untuk daftar
    yang memang membandingkan.
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

    built = gb.build()
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
           selection_mode: str = "single", cast=None):
    """Gambar tabelnya, kembalikan identitas baris terpilih (atau None).

    Seluruh pemanggil memakai jalur ini, sehingga mengubah perilaku tabel
    berarti mengubahnya di SATU tempat — bukan menambal tiga salinan yang
    perlahan menyimpang satu sama lain.
    """
    from st_aggrid import AgGrid, GridUpdateMode

    columns = list(columns or [])
    rows = list(rows or [])
    df = dataframe(columns, rows, id_key=id_key)
    response = AgGrid(
        df,
        gridOptions=options(df, columns, selection_mode=selection_mode),
        allow_unsafe_jscode=True,
        theme="streamlit",
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        height=height_for(len(rows)),
        key=key,
    )
    return selected_id(response, cast=cast)

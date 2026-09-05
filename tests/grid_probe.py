"""Membaca isi tabel AgGrid dari sebuah AppTest.

AgGrid adalah komponen pihak ketiga, jadi AppTest hanya melihatnya sebagai
satu `component_instance` tanpa isi yang dapat ditelusuri lewat API biasa.
Isinya tetap dapat diperiksa: barisnya dikirim sebagai Arrow IPC pada
`special_args`, dan setelan gridnya sebagai JSON pada `json_args`.

Tanpa modul ini, uji tabel hanya sanggup memastikan "ada sebuah komponen" —
yang akan tetap hijau meskipun tabelnya kosong, kolomnya salah, atau barisnya
tidak dapat dipilih sama sekali.
"""
from __future__ import annotations

import io
import json

from ui.components import grid as grid_mod


def element(at, *, index: int = 0):
    """Elemen komponen tabel ke-``index``; memastikan ia memang AgGrid."""
    els = at.get("component_instance")
    assert els, "tidak ada tabel yang tergambar"
    el = els[index]
    assert el.proto.component_name.endswith("agGrid"), el.proto.component_name
    return el


def count(at) -> int:
    """Berapa tabel yang tergambar — 0 pun jawaban yang sah."""
    return len(at.get("component_instance"))


def table(at, *, index: int = 0):
    """Baris tabel sebagai tabel Arrow."""
    import pyarrow as pa

    raw = element(at, index=index).proto.special_args[0].arrow_dataframe.data.data
    return pa.ipc.open_stream(io.BytesIO(raw)).read_all()


def rows(at, *, index: int = 0) -> list[dict]:
    """Baris tabel sebagai daftar dict — persis yang dilihat pengguna."""
    return table(at, index=index).to_pylist()


def options(at, *, index: int = 0) -> dict:
    """`gridOptions` yang dikirim ke komponen."""
    return json.loads(element(at, index=index).proto.json_args)["gridOptions"]


def shown_columns(at, *, index: int = 0) -> list[str]:
    """Judul kolom yang BENAR-BENAR tampil, sesuai urutannya."""
    return [c["headerName"] for c in options(at, index=index)["columnDefs"]
            if not c.get("hide")]


def ids(at, *, index: int = 0) -> list:
    """Identitas tiap baris — kolom tersembunyi yang dibaca saat baris dipilih."""
    return [r[grid_mod.ID_FIELD] for r in rows(at, index=index)]

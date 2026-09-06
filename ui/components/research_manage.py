"""Kelola research pipeline — SELURUHNYA, bawaan maupun kontribusi.

Halaman ini menjawab "research pipeline apa saja yang ada di platform ini, apa
keadaannya, dan bagaimana mengubah keterangannya" — bukan "pengajuan apa yang
baru masuk". Keduanya berbeda, dan sebelumnya hanya yang kedua yang punya
tampilan.

**Sumbernya bukan satu tabel.** Research bawaan hidup di kode
(`contracts/dataset_schemas.py`, `config/research_attribution.py`,
`config/pipeline_registry.py`); research kontribusi hidup di tabel
`research_pipelines`; `registered_pipelines` memuat VERSI ALGORITMA, bukan
research; `submissions` adalah alur tinjauan. Yang dipakai di sini adalah
pembaca GABUNGAN di `orchestrator/research_registry.py` — satu-satunya tempat
yang mengetahui ketiganya.

**Bawaan pun dapat disunting.** Suntingannya disimpan sebagai baris timpaan di
`research_pipelines`, bukan dengan mengubah berkas di `contracts/` dan
`config/` — hasilnya sama bagi pembaca, berkas definisi tetap utuh, dan
suntingan bawaan selalu dapat dikembalikan ke definisi git.
"""
from __future__ import annotations

from html import escape

import streamlit as st

from ui.i18n import t

#: Naik setiap kali sebuah research disunting/diubah statusnya. Menjadi bagian
#: kunci cache, sehingga daftar yang tampil TIDAK PERNAH tertinggal di
#: belakang perubahan yang barusan disimpan pengguna.
NONCE_KEY = "_rs_nonce"
QUERY_KEY = "_rs_query"
STATUS_KEY = "_rs_status"
ORIGIN_KEY = "_rs_origin"
SORT_KEY = "_rs_sort"
EDIT_KEY = "_rs_editing"
#: Pesan yang harus SELAMAT dari `st.rerun()`. Tanpa ini konfirmasi
#: penyimpanan digambar lalu langsung terhapus oleh rerun yang menyegarkan
#: daftarnya — pengguna menekan Simpan dan tidak melihat apa pun.
FLASH_KEY = "_rs_flash"

ORIGIN_BUILTIN = "builtin"
ORIGIN_UPLOADED = "uploaded"

SORT_UPDATED = "updated"
SORT_NAME = "name"
SORT_YEAR = "year"
SORT_LABELS = {
    SORT_UPDATED: "rs.sort_updated",
    SORT_NAME: "rs.sort_name",
    SORT_YEAR: "rs.sort_year",
}


# ── Katalog: fungsi MURNI, dapat diuji tanpa Streamlit ────────────────────

def _experiment_counts(db_path=None) -> dict:
    """{pipeline_id: jumlah eksperimen} untuk SELURUH pipeline — satu kueri.

    `pipeline_versions.experiment_counts()` sengaja hanya menghitung ruang nama
    kontribusi; halaman ini juga menampilkan research bawaan, jadi hitungannya
    harus mencakup keduanya.
    """
    from database.db import get_connection

    try:
        with get_connection(db_path) as conn:
            rows = conn.execute(
                "SELECT pipeline_id, COUNT(*) FROM experiments "
                "GROUP BY pipeline_id").fetchall()
        return {r[0]: int(r[1]) for r in rows}
    except Exception:                       # pragma: no cover - defensif
        return {}


def research_catalog(db_path=None) -> list[dict]:
    """Satu baris per RESEARCH PIPELINE — bawaan dan kontribusi, aktif maupun
    tidak.

    Bukan per algoritma dan bukan per versi: keduanya dihitung menjadi angka
    pada barisnya. Kegagalan membaca satu research tidak menjatuhkan daftarnya.
    """
    from database.models import is_uploaded_research
    from orchestrator.dynamic_registry import get_all_pipelines
    from contracts.dataset_schemas import supported_datasets
    from orchestrator.research_registry import (
        list_research, merge_attribution, merge_schema, short_label_from,
    )
    # Ekstensi berkas dibaca dari mekanisme yang SAMA dengan file picker —
    # skema HIKARI2021 tidak menyimpan `file_format` sama sekali, dan EVE
    # menyimpannya sebagai `json_or_csv`, yang bukan kalimat untuk dibaca.
    from ui.views.run_experiment import _dataset_extensions

    try:
        merged = get_all_pipelines(db_path) or {}
    except Exception:                       # pragma: no cover - defensif
        merged = {}
    counts = _experiment_counts(db_path)

    algoritma: dict[str, list] = {}
    for pipeline_id, entry in merged.items():
        dtype = (entry or {}).get("dataset_type")
        if dtype:
            algoritma.setdefault(dtype, []).append(pipeline_id)

    # `all_dataset_types()` sengaja hanya menyebut yang AKTIF — ia dipakai
    # menawarkan pilihan kepada pengguna. Halaman pengelolaan justru harus
    # memuat yang nonaktif: di sinilah satu-satunya tempat ia dapat dihidupkan
    # kembali, dan daftar yang menyembunyikannya membuat pemiliknya mengira
    # research itu hilang.
    # Seluruh baris timpaan dibaca SEKALI. Memanggil `attribution_for()` dan
    # `schema_for()` per research akan membaca barisnya lagi setiap kali —
    # tiga kueri per research, tumbuh linear terhadap jumlah kontribusi.
    timpaan = {b["dataset_type"]: b
               for b in list_research(active_only=False, db_path=db_path)}
    # Tiga sumber jenis, dan ketiganya perlu: skema bawaan, baris identitas
    # research, DAN registry algoritma. Yang ketiga tidak boleh dilewat —
    # sebuah pipeline kontribusi dapat terdaftar tanpa baris identitas
    # (mis. yang menumpang jenis bawaan, atau baris lama), dan daftar yang
    # melewatkannya menyembunyikan research yang benar-benar dapat dijalankan.
    tipe = list(supported_datasets())
    for nama_tipe in list(timpaan) + sorted(algoritma):
        if nama_tipe and nama_tipe not in tipe:
            tipe.append(nama_tipe)

    out: list[dict] = []
    for dtype in tipe:
        row = timpaan.get(dtype)
        try:
            attribution = merge_attribution(dtype, row) or {}
            schema = merge_schema(dtype, row) or {}
        except Exception:                   # pragma: no cover - defensif
            attribution, schema = {}, {}

        source = attribution.get("pipeline_source") or {}
        dataset_source = attribution.get("dataset_source") or {}
        ids = algoritma.get(dtype, [])
        uploaded = is_uploaded_research(dtype)

        out.append({
            "dataset_type": dtype,
            "title": short_label_from(dtype, attribution) or dtype,
            "name": attribution.get("short_name") or dtype,
            "origin": ORIGIN_UPLOADED if uploaded else ORIGIN_BUILTIN,
            # Research bawaan selalu tersedia: ketersediaannya tidak disimpan
            # sebagai bendera, ia ada karena kodenya ada.
            "active": bool(row["active"]) if (row and uploaded) else True,
            "institution": str(source.get("institution") or "").strip(),
            "year": str(source.get("year") or "").strip(),
            "source_type": str(source.get("type") or "").strip(),
            "authors": str(source.get("authors") or "").strip(),
            "paper_title": str(source.get("title") or "").strip(),
            "scope": str(attribution.get("scope") or "").strip(),
            "dataset_name": str(dataset_source.get("name") or "").strip(),
            "dataset_attribution": str(dataset_source.get("attribution") or "").strip(),
            "dataset_note": str(dataset_source.get("note") or "").strip(),
            "file_format": str(schema.get("file_format") or "").strip(),
            "extensions": list(_dataset_extensions(dtype) or ()),
            "label_column": str(schema.get("label_column") or "").strip(),
            "expected_columns": list(schema.get("expected_columns") or []),
            "algorithms": len(ids),
            "experiments": sum(counts.get(pid, 0) for pid in ids),
            # Cap waktu TIDAK PERNAH dikarang: research bawaan tidak punya
            # baris basis data, jadi ia memang tidak punya tanggal.
            "created_at": (row or {}).get("registered_at") or "",
            "updated_at": (row or {}).get("updated_at") or "",
            "updated_by": (row or {}).get("updated_by") or "",
            "edited": bool(row) and not uploaded,
        })
    return out


def search_text(row: dict) -> str:
    """Teks yang dicari untuk satu research, huruf kecil."""
    bagian = [row.get(k) or "" for k in
              ("title", "name", "dataset_type", "institution", "year",
               "authors", "paper_title", "scope", "dataset_name",
               "source_type", "file_format", "label_column")]
    return " ".join(str(b) for b in bagian if b).lower()


def filter_rows(rows, query: str = "", status=None, origin=None):
    """Cari + saring. Kosong berarti tidak menyaring apa pun."""
    hasil = list(rows or [])
    teks = str(query or "").strip().lower()
    if teks:
        hasil = [r for r in hasil if teks in search_text(r)]
    if status in (True, False):
        hasil = [r for r in hasil if bool(r.get("active")) is status]
    if origin in (ORIGIN_BUILTIN, ORIGIN_UPLOADED):
        hasil = [r for r in hasil if r.get("origin") == origin]
    return hasil


def sort_rows(rows, key: str = SORT_UPDATED):
    """Urutkan. Yang tidak punya cap waktu jatuh ke BELAKANG, bukan ke depan:
    ketiadaan tanggal bukan "paling lama diperbarui"."""
    hasil = list(rows or [])
    if key == SORT_NAME:
        return sorted(hasil, key=lambda r: str(r.get("title", "")).lower())
    if key == SORT_YEAR:
        return sorted(hasil, key=lambda r: (not r.get("year"),
                                            str(r.get("year") or "")),
                      reverse=False)
    return sorted(hasil, key=lambda r: (
        r.get("updated_at") or r.get("created_at") or ""), reverse=True)


def last_touched(row: dict) -> str:
    """Cap waktu paling akhir yang BENAR-BENAR ada; "" bila tidak ada."""
    return row.get("updated_at") or row.get("created_at") or ""


def format_stamp(raw: str) -> str:
    """`2026-09-06T21:42:11+00:00` -> `6 Sep 2026, 21:42`; "" tetap ""."""
    from datetime import datetime

    teks = str(raw or "").strip()
    if not teks:
        return ""
    try:
        saat = datetime.fromisoformat(teks.replace("Z", "+00:00"))
    except ValueError:
        return teks[:16]
    bulan = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
             "Jul", "Agu", "Sep", "Okt", "Nov", "Des")
    return (f"{saat.day} {bulan[saat.month - 1]} {saat.year}, "
            f"{saat.hour:02d}:{saat.minute:02d}")


def status_label(row: dict) -> str:
    """Kata keadaannya — SELALU lewat i18n, tidak pernah literal Inggris."""
    return t("rs.status_active" if row.get("active") else "rs.status_inactive")


def meta_line(row: dict) -> str:
    """Baris metadata ringkas: apa datanya, berapa algoritmanya."""
    bagian = [f"{t('rs.lbl_dataset')}: `{row['dataset_type']}`"]
    format_teks = " / ".join(
        e.lstrip(".").upper() for e in (row.get("extensions") or [])[:2])
    if format_teks:
        bagian.append(format_teks)
    bagian.append(t("rs.n_algorithms", count=row.get("algorithms", 0)))
    bagian.append(t("rs.n_experiments", count=row.get("experiments", 0)))
    return " · ".join(bagian)


def detail_line(row: dict) -> str:
    """Baris halus: institusi + kapan terakhir disentuh."""
    from ui.components.pipeline_catalog import institution_label

    # Nama LEMBAGANYA, bukan seluruh alamat afiliasi: "Program Studi …,
    # Fakultas …, Universitas Hasanuddin, Gowa" tidak muat pada satu baris
    # kartu, dan yang membedakan satu research dari yang lain hanya lembaganya.
    bagian = [f"{t('rs.lbl_institution')}: "
              f"{institution_label(row.get('institution')) or '—'}"]
    stamp = format_stamp(last_touched(row))
    if stamp:
        kunci = "rs.lbl_updated" if row.get("updated_at") else "rs.lbl_created"
        bagian.append(f"{t(kunci)}: {stamp}")
    else:
        # Research bawaan: definisinya ada di git, bukan di basis data.
        bagian.append(t("rs.no_timestamp"))
    return " · ".join(bagian)


# ── Tampilan ─────────────────────────────────────────────────────────────

def bump() -> None:
    """Paksa daftar dibaca ulang setelah sesuatu benar-benar tersimpan."""
    st.session_state[NONCE_KEY] = st.session_state.get(NONCE_KEY, 0) + 1


@st.cache_data(ttl=10, show_spinner=False)
def _catalog_cached(nonce: int) -> list[dict]:
    """Katalog, dibaca sekali per perubahan.

    Menyusunnya menyentuh basis data beberapa kali (registry gabungan, hitungan
    eksperimen, timpaan per research). Tanpa cache, biaya itu dibayar ulang
    pada setiap rerun Streamlit — termasuk saat mengetik di kotak cari.
    ``nonce`` naik begitu ada yang tersimpan, jadi hasilnya tidak pernah
    tertinggal di belakang perubahan pengguna.
    """
    return research_catalog()


def _controls(rows) -> tuple:
    """Kotak cari + penyaring + pengurut. Mengembalikan (query, status, origin,
    sort)."""
    cari, saring = st.columns([3, 2])
    query = cari.text_input(t("rs.search"), key=QUERY_KEY,
                            placeholder=t("rs.search_ph"),
                            label_visibility="collapsed")

    kolom = saring.columns(3)
    status_opsi = {None: t("rs.any_status"), True: t("rs.status_active"),
                   False: t("rs.status_inactive")}
    status = kolom[0].selectbox(t("rs.lbl_status"), list(status_opsi),
                                format_func=lambda k: status_opsi[k],
                                key=STATUS_KEY, label_visibility="collapsed")
    asal_opsi = {None: t("rs.any_origin"),
                 ORIGIN_BUILTIN: t("rs.origin_builtin"),
                 ORIGIN_UPLOADED: t("rs.origin_uploaded")}
    origin = kolom[1].selectbox(t("rs.lbl_origin"), list(asal_opsi),
                                format_func=lambda k: asal_opsi[k],
                                key=ORIGIN_KEY, label_visibility="collapsed")
    sort = kolom[2].selectbox(t("rs.lbl_sort"), list(SORT_LABELS),
                              format_func=lambda k: t(SORT_LABELS[k]),
                              key=SORT_KEY, label_visibility="collapsed")
    return query, status, origin, sort


def _render_card(row: dict, user: dict | None) -> None:
    """Satu kartu research — ringkas, tinggi tetap berapa pun isinya."""
    dtype = row["dataset_type"]
    with st.container(border=True):
        judul, lencana = st.columns([5, 1])
        judul.markdown(f"**{escape(row['title'])}**")
        titik = "🟢" if row.get("active") else "⚪"
        lencana.markdown(f"{titik} {status_label(row)}")

        st.markdown(meta_line(row))
        st.markdown(detail_line(row))

        aksi = st.columns([1, 1, 1, 3])
        if aksi[0].button(t("rs.btn_edit"), key=f"rs_edit_{dtype}",
                          use_container_width=True):
            st.session_state[EDIT_KEY] = dtype
            st.rerun()

        # Status hanya dapat diubah untuk research KONTRIBUSI: keluarga bawaan
        # adalah pembanding tetap penelitian ini, dan mematikannya akan
        # menghapus dasar pembandingnya dari halaman Jalankan Eksperimen.
        kontribusi = row["origin"] == ORIGIN_UPLOADED
        label = t("rs.btn_deactivate" if row.get("active")
                  else "rs.btn_activate")
        if aksi[1].button(label, key=f"rs_toggle_{dtype}",
                          use_container_width=True,
                          disabled=not kontribusi,
                          help=None if kontribusi else t("rs.builtin_always_on")):
            _toggle(row, user)

        if row.get("edited") and aksi[2].button(
                t("rs.btn_revert"), key=f"rs_revert_{dtype}",
                use_container_width=True, help=t("rs.help_revert")):
            _revert(row, user)

    if st.session_state.get(EDIT_KEY) == dtype:
        _render_edit_form(row, user)


def _toggle(row: dict, user: dict | None) -> None:
    from orchestrator import dynamic_registry as dr

    try:
        dr.set_research_active(row["dataset_type"], not row.get("active"),
                               actor=user)
    except Exception as exc:
        st.error(_message(exc))
        return
    bump()
    st.rerun()


def _revert(row: dict, user: dict | None) -> None:
    from orchestrator.research_registry import revert_research

    try:
        revert_research(row["dataset_type"], actor=user)
    except Exception as exc:
        st.error(_message(exc))
        return
    bump()
    st.rerun()


def _message(exc: Exception) -> str:
    key = getattr(exc, "key", "")
    return t(key, **getattr(exc, "values", {})) if key else str(exc)


def _render_edit_form(row: dict, user: dict | None) -> None:
    """Formulir SEBARIS di bawah kartunya — bukan halaman lain.

    Yang disunting seluruhnya KETERANGAN. `dataset_type` tidak ikut: ia
    identitas research ini dan baris `experiments` yang sudah ada menunjuk
    padanya, jadi mengubahnya memutus hubungan itu tanpa dapat dibatalkan.
    """
    from orchestrator.research_registry import attribution_for, update_research

    dtype = row["dataset_type"]
    with st.container(border=True):
        st.markdown(f"**{t('rs.sec_edit')}**")

        k1, k2, k3 = st.columns([3, 2, 1])
        nama = k1.text_input(t("rs.f_name"), value=row["name"],
                             key=f"rs_f_name_{dtype}")
        jenis = k2.text_input(t("rs.f_source_type"), value=row["source_type"],
                              key=f"rs_f_type_{dtype}")
        tahun = k3.text_input(t("rs.f_year"), value=row["year"], max_chars=4,
                              key=f"rs_f_year_{dtype}")

        k4, k5 = st.columns(2)
        penulis = k4.text_input(t("rs.f_authors"), value=row["authors"],
                                key=f"rs_f_authors_{dtype}")
        institusi = k5.text_input(t("rs.f_institution"),
                                  value=row["institution"],
                                  key=f"rs_f_inst_{dtype}")
        judul = st.text_input(t("rs.f_title"), value=row["paper_title"],
                              key=f"rs_f_title_{dtype}")
        cakupan = st.text_input(t("rs.f_scope"), value=row["scope"],
                                key=f"rs_f_scope_{dtype}")

        d1, d2 = st.columns(2)
        ds_nama = d1.text_input(t("rs.f_dataset_name"),
                                value=row["dataset_name"],
                                key=f"rs_f_dsname_{dtype}")
        ds_atribusi = d2.text_input(t("rs.f_dataset_attribution"),
                                    value=row["dataset_attribution"],
                                    key=f"rs_f_dsattr_{dtype}")
        ds_catatan = st.text_input(t("rs.f_dataset_note"),
                                   value=row["dataset_note"],
                                   key=f"rs_f_dsnote_{dtype}")

        # Kontrak dataset. Mengubahnya mengubah cara berkas dataset DIPERIKSA,
        # jadi akibatnya dinyatakan — bukan disembunyikan di balik isian biasa.
        st.markdown(f"**{t('rs.sec_contract')}**")
        st.warning(t("rs.warn_contract"))
        c1, c2 = st.columns([1, 1])
        label_kolom = c1.text_input(t("rs.f_label_column"),
                                    value=row["label_column"],
                                    key=f"rs_f_label_{dtype}")
        format_berkas = c2.text_input(t("rs.f_file_format"),
                                      value=row["file_format"],
                                      key=f"rs_f_fmt_{dtype}")
        kolom_wajib = st.text_area(
            t("rs.f_expected_columns"),
            value="\n".join(row["expected_columns"]), height=90,
            key=f"rs_f_cols_{dtype}",
            help=t("rs.help_expected_columns"))

        simpan, batal = st.columns([1, 1])
        if batal.button(t("rs.btn_cancel"), key=f"rs_cancel_{dtype}",
                        use_container_width=True):
            st.session_state.pop(EDIT_KEY, None)
            st.rerun()

        if simpan.button(t("rs.btn_save"), type="primary",
                         key=f"rs_save_{dtype}", use_container_width=True):
            atribusi = dict(attribution_for(dtype) or {})
            atribusi["short_name"] = nama.strip() or row["name"]
            atribusi["scope"] = cakupan.strip()
            atribusi["pipeline_source"] = _clean({
                "type": jenis, "authors": penulis, "title": judul,
                "institution": institusi, "year": tahun})
            atribusi["dataset_source"] = _clean({
                "name": ds_nama, "attribution": ds_atribusi,
                "note": ds_catatan})
            # Nama tampil disusun ulang dari bagiannya, pola yang sama dengan
            # atribusi bawaan: "<kredit> — <nama>".
            kredit = _credit(penulis, tahun, institusi)
            atribusi["display_name"] = (
                f"{kredit} — {nama.strip()}" if kredit and nama.strip()
                else (nama.strip() or row["name"]))
            atribusi["paper_credit"] = kredit

            skema = {"label_column": label_kolom.strip(),
                     "expected_columns": [c.strip() for c in
                                          kolom_wajib.splitlines() if c.strip()]}
            if format_berkas.strip():
                skema["file_format"] = format_berkas.strip().lstrip(".").lower()
            if row.get("expected_top_level_keys"):
                skema["expected_top_level_keys"] = row["expected_top_level_keys"]

            try:
                update_research(dtype, name=nama.strip() or row["name"],
                                attribution=atribusi, schema=skema, actor=user)
            except Exception as exc:
                st.error(_message(exc))
                return
            st.session_state.pop(EDIT_KEY, None)
            st.session_state[FLASH_KEY] = t(
                "rs.msg_saved", research=nama.strip() or row["name"])
            bump()
            st.rerun()


def _clean(values: dict) -> dict:
    return {k: str(v).strip() for k, v in values.items() if str(v or "").strip()}


def _credit(authors: str, year: str, institution: str) -> str:
    """"<penulis> (<tahun>), <institusi>" — bagian kosong DIBUANG, bukan
    diisi tanda hubung."""
    from orchestrator.submission_service import research_credit

    return research_credit(authors, year, institution)


def render(user: dict | None, *, heading: bool = True) -> None:
    """Daftar kelola research pipeline: cari, saring, urut, sunting.

    ``heading`` dimatikan bila pemanggil sudah menggambar judul bagiannya
    sendiri — dua judul bertumpuk di atas satu daftar tidak memberi tahu
    pembacanya yang mana yang ia baca.
    """
    from ui.components.sections import render_section

    if heading:
        render_section(t("rs.sec_manage"), help=t("rs.help_manage"))

    pesan = st.session_state.pop(FLASH_KEY, "")
    if pesan:
        st.success(pesan)

    semua = _catalog_cached(st.session_state.get(NONCE_KEY, 0))
    query, status, origin, sort = _controls(semua)
    tampil = sort_rows(filter_rows(semua, query, status, origin), sort)

    st.markdown(t("rs.count", shown=len(tampil), total=len(semua)))
    if not tampil:
        st.info(t("rs.empty"))
        return

    for row in tampil:
        _render_card(row, user)

"""
Pemilih mode eksekusi + formulir parameter.

Satu tempat untuk seluruh kontrol yang berhubungan dengan run resmi vs run
eksplorasi, supaya aturan berikut tidak mungkin berbeda antar halaman:

* **Bawaan selalu run resmi.** Pemilihnya ``st.tabs``, dan tab resmi berada di
  posisi 0 — jadi tampilan pertama kali, dan setiap kali session state kosong,
  jatuh ke run resmi. Mode eksplorasi hanya aktif bila pengguna membuka tabnya
  sendiri; berpindah pipeline mengembalikan formulir ke nilai bawaan pipeline
  yang baru.
* **Formulir dibangun dari ``fixed_params`` pipeline terpilih**, lewat
  ``orchestrator.run_mode.param_rows`` — tidak ada daftar parameter yang
  ditulis di modul ini.
* **Mode resmi tetap MENAMPILKAN parameter** (transparansi), hanya tidak dapat
  diubah.
* **Yang terkunci disebut alasannya**, bukan sekadar disembunyikan.

Modul ini hanya menyusun tampilan dan mengembalikan nilai; validasi sebenarnya
tetap milik ``orchestrator.run_mode.validate_overrides``, yang dipanggil ulang
di orchestrator sebelum pipeline dijalankan.
"""
from __future__ import annotations

import logging

import streamlit as st

from ui.components.validator_messages import error_message

from ui.i18n import t

from orchestrator.run_mode import (
    ALL_RUN_MODES, DEFAULT_RUN_MODE, PARAM_BOUNDS,
    RUN_MODE_EXPLORATION, RUN_MODE_LABELS, RUN_MODE_OFFICIAL, ParamError,
    param_rows, validate_overrides,
)

logger = logging.getLogger(__name__)

#: Mode yang BERLAKU, sebagai pengenal (`official` / `exploration`). Dibaca
#: `selected_mode()` dan halaman Jalankan Eksperimen. Sejak pemilihnya menjadi
#: tab, kunci ini TIDAK lagi terikat ke widget mana pun — ia ditulis penyaji
#: dari keadaan tabnya, jadi boleh disentuh kapan saja.
MODE_STATE_KEY = "_run_mode_choice"

#: Kunci widget tabnya sendiri. Nilainya LABEL tab, bukan pengenal mode —
#: karena itu ia dipisah: menyimpan label berbahasa sebagai pengenal akan
#: membuat mode terpilih hilang begitu pengguna berganti bahasa.
MODE_TAB_KEY = "_run_mode_tab"
CHANGED_MARK = "•"

NO_TUNABLE_NOTE = (
    "Pipeline ini tidak mendeklarasikan hyperparameter model yang dapat "
    "disesuaikan: seluruh `fixed_params`-nya mengunci tahapan, split, "
    "algoritma, seleksi fitur, atau batas sumber daya."
)
LOCKED_TABLE_NOTE = (
    "Parameter selalu ditampilkan, juga pada run resmi. Yang terkunci disertai "
    "alasannya."
)


def _widget_key(pipeline_id: str, key: str) -> str:
    return f"_pov_{pipeline_id}_{key}"


def selected_mode() -> str:
    """Mode yang sedang dipilih. Tanpa pilihan apa pun -> RESMI."""
    value = st.session_state.get(MODE_STATE_KEY)
    return value if value in ALL_RUN_MODES else DEFAULT_RUN_MODE


def reset_overrides(pipeline_id: str) -> None:
    """Buang seluruh nilai formulir milik satu pipeline (kembali ke bawaan)."""
    for row in param_rows(pipeline_id):
        st.session_state.pop(_widget_key(pipeline_id, row["key"]), None)


def render_mode_tabs():
    """Tab pemilih mode. Mengembalikan ``(mode, wadah per mode)``.

    RESMI selalu di posisi 0, jadi tampilan pertama kali — dan setiap kali
    session state kosong — jatuh ke run resmi. Tidak ada jalur yang menjadikan
    eksplorasi bawaan.

    ``on_change="rerun"`` bukan hiasan: dengan ``"ignore"`` (bawaannya) atribut
    ``.open`` mengembalikan ``None`` untuk SEMUA tab, dan penyajinya tidak punya
    cara mengetahui mode mana yang dimaksud saat tombol Run ditekan. Itulah
    satu-satunya alasannya ada di sini.

    Yang TIDAK dijanjikan: dokumentasi Streamlit menyebut mode ini memungkinkan
    "lazy execution", tetapi diukur di sini isi KEDUA tab tetap dijalankan pada
    setiap penggambaran. Jadi widget formulir eksplorasi ikut dibuat meskipun
    pengguna sedang di tab resmi — dan karena itu `render_run_mode_block`
    memaksa ``param_overrides`` kosong pada mode resmi alih-alih mengandalkan
    formulirnya tidak berjalan.
    """
    modes = [RUN_MODE_OFFICIAL, RUN_MODE_EXPLORATION]
    wadah = st.tabs([RUN_MODE_LABELS[m] for m in modes],
                    key=MODE_TAB_KEY, on_change="rerun")
    terbuka = [m for m, w in zip(modes, wadah) if w.open]
    mode = terbuka[0] if terbuka else DEFAULT_RUN_MODE
    if mode not in ALL_RUN_MODES:                # pragma: no cover - defensif
        mode = DEFAULT_RUN_MODE
    # Pengenalnya disimpan terpisah dari label tabnya — lihat `MODE_TAB_KEY`.
    st.session_state[MODE_STATE_KEY] = mode
    return mode, dict(zip(modes, wadah))


def _number_input(pipeline_id: str, row: dict):
    spec = row["spec"]
    key = _widget_key(pipeline_id, row["key"])
    default = spec["default"]
    is_int = spec["type"] == "int"
    step = 1 if is_int else 0.01
    value = st.session_state.get(key, default)
    help_text = (f"Bawaan {default}. Batas {spec['min']}–{spec['max']}."
                 if row["key"] in PARAM_BOUNDS
                 else f"Bawaan {default}.")
    return st.number_input(
        row["key"], min_value=spec["min"], max_value=spec["max"],
        value=value, step=step, key=key, help=help_text,
        format="%d" if is_int else None,
    )


def _control_for(pipeline_id: str, row: dict):
    """Kontrol masukan sesuai TIPE nilai bawaannya."""
    spec = row["spec"]
    key = _widget_key(pipeline_id, row["key"])
    if spec["type"] == "bool":
        return st.checkbox(row["key"], value=st.session_state.get(key, spec["default"]),
                           key=key, help=f"Bawaan {spec['default']}.")
    if spec["type"] == "choice":
        options = spec["choices"]
        current = st.session_state.get(key, spec["default"])
        return st.selectbox(row["key"], options,
                            index=options.index(current) if current in options else 0,
                            key=key, help=f"Bawaan {spec['default']}.")
    return _number_input(pipeline_id, row)


def render_locked_table(rows: list[dict]) -> None:
    """Seluruh ``fixed_params`` sebagai tabel — dipakai pada mode RESMI."""
    if not rows:
        st.caption(t("rmc.no_fixed_params"))
        return
    lines = ["| Parameter | Nilai | Status |", "| --- | --- | --- |"]
    for row in rows:
        status = ("dapat disesuaikan pada run eksplorasi" if row["tunable"]
                  else f"terkunci · {row['reason']}")
        lines.append(f"| `{row['key']}` | `{row['default']}` | {status} |")
    st.markdown(chr(10).join(lines))
    st.caption(LOCKED_TABLE_NOTE)


def render_param_form(pipeline_id: str) -> dict:
    """Formulir parameter untuk run EKSPLORASI. Mengembalikan override bersih.

    Hanya kunci yang benar-benar BERBEDA dari bawaan yang dikembalikan: mengirim
    nilai yang sama dengan bawaan bukan "penyesuaian", dan tidak perlu tercatat
    sebagai perubahan.
    """
    rows = param_rows(pipeline_id)
    tunable = [r for r in rows if r["tunable"]]
    locked = [r for r in rows if not r["tunable"]]

    if not tunable:
        if locked:
            with st.expander("Parameter terkunci pipeline ini", expanded=False):
                render_locked_table(rows)
        return {}

    head = st.columns([3, 1])
    head[0].markdown(t("rmc.adjustable_params"))
    if head[1].button(t("re.btn_reset_defaults"), key=f"_pov_reset_{pipeline_id}",
                      use_container_width=True,
                      help=t("rmc.reset_help")):
        reset_overrides(pipeline_id)
        st.rerun()

    values: dict = {}
    columns = st.columns(min(len(tunable), 3))
    for index, row in enumerate(tunable):
        with columns[index % len(columns)]:
            values[row["key"]] = _control_for(pipeline_id, row)

    defaults = {r["key"]: r["spec"]["default"] for r in tunable}
    overrides = {k: v for k, v in values.items() if v != defaults[k]}

    # Penanda visual: parameter yang BERBEDA dari bawaan disebut satu per satu.
    if overrides:
        marks = ", ".join(f"`{k}` {overrides[k]} (bawaan {defaults[k]})"
                          for k in sorted(overrides))
        st.markdown(f"{CHANGED_MARK} Berbeda dari bawaan: {marks}")

    if locked:
        with st.expander(t("rmc.still_locked"), expanded=False):
            render_locked_table(locked)

    # Validasi lapis-UI: pesan muncul di dekat formulirnya, bukan setelah
    # eksperimen gagal. Orchestrator tetap memvalidasi ulang — ini bukan
    # penggantinya.
    try:
        return validate_overrides(pipeline_id, overrides)
    except ParamError as e:
        st.error(error_message(e))
        return {}


def render_run_mode_block(pipeline_id: str) -> dict:
    """Blok lengkap: tab mode, keterangannya, dan parameternya.

    Mengembalikan ``{"run_mode": str, "param_overrides": dict}`` — siap
    diteruskan ke ``create_and_run_experiment``. Pada mode resmi
    ``param_overrides`` SELALU kosong.

    Isi tiap mode digambar DI DALAM tabnya; expander parameter terkunci tetap
    ada di dalam tab resmi, karena tabel itu bahan rujukan dan isi tab terpilih
    langsung terlihat.

    ``param_overrides`` dikosongkan pada mode resmi SEBAGAI ATURAN, bukan karena
    formulirnya kebetulan tidak berjalan — isi kedua tab memang dijalankan
    (lihat `render_mode_tabs`). Tanpa pemaksaan ini, nilai yang tertinggal di
    formulir eksplorasi dapat ikut terkirim pada run yang dicatat sebagai resmi.
    """
    mode, tab = render_mode_tabs()
    overrides: dict = {}

    with tab[RUN_MODE_OFFICIAL]:
        # Expander DIPERTAHANKAN di dalam tabnya. Sempat saya buang dengan
        # alasan "tab sudah merupakan lipatan" — dan itu keliru: isi tab yang
        # TERPILIH langsung terlihat, tidak seperti expander yang tertutup.
        # Tabel parameter terkunci adalah bahan rujukan, bukan sesuatu yang
        # dibaca tiap kali menjalankan eksperimen.
        with st.expander("Parameter terkunci pipeline ini", expanded=False):
            render_locked_table(param_rows(pipeline_id))

    with tab[RUN_MODE_EXPLORATION]:
        overrides = render_param_form(pipeline_id)

    if mode != RUN_MODE_EXPLORATION:
        return {"run_mode": RUN_MODE_OFFICIAL, "param_overrides": {}}
    return {"run_mode": RUN_MODE_EXPLORATION, "param_overrides": overrides}

"""
Pemilih mode eksekusi + formulir parameter.

Satu tempat untuk seluruh kontrol yang berhubungan dengan run resmi vs run
eksplorasi, supaya aturan berikut tidak mungkin berbeda antar halaman:

* **Bawaan selalu run resmi.** ``st.radio`` diberi ``index=0`` pada opsi resmi
  dan session state disemai dengan nilai resmi. Mode eksplorasi hanya aktif
  bila pengguna memilihnya sendiri; berpindah pipeline mengembalikan formulir
  ke nilai bawaan pipeline yang baru.
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

from orchestrator.run_mode import (
    ALL_RUN_MODES, DEFAULT_RUN_MODE, EXPLORATION_WARNING, PARAM_BOUNDS,
    RUN_MODE_EXPLORATION, RUN_MODE_LABELS, RUN_MODE_OFFICIAL, ParamError,
    RUN_MODE_HINTS, param_rows, validate_overrides,
)

logger = logging.getLogger(__name__)

MODE_STATE_KEY = "_run_mode_choice"
CHANGED_MARK = "•"

NO_TUNABLE_NOTE = (
    "Pipeline ini tidak mendeklarasikan hyperparameter model yang dapat "
    "disesuaikan — seluruh `fixed_params`-nya mengunci tahapan, split, "
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


def render_mode_picker() -> str:
    """Pilihan mode. Mengembalikan mode terpilih; bawaannya RESMI.

    ``index`` dihitung dari daftar mode dengan resmi di posisi 0, jadi tampilan
    pertama kali — dan setiap kali session state kosong — selalu jatuh ke run
    resmi. Tidak ada jalur yang menjadikan eksplorasi bawaan.
    """
    modes = [RUN_MODE_OFFICIAL, RUN_MODE_EXPLORATION]
    current = selected_mode()
    choice = st.radio(
        "Mode eksekusi",
        modes,
        index=modes.index(current),
        key=MODE_STATE_KEY,
        format_func=lambda m: f"{RUN_MODE_LABELS[m]} — {RUN_MODE_HINTS[m]}",
        horizontal=False,
    )
    return choice if choice in ALL_RUN_MODES else DEFAULT_RUN_MODE


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
        st.caption("Pipeline ini tidak mendeklarasikan `fixed_params`.")
        return
    lines = ["| Parameter | Nilai | Status |", "| --- | --- | --- |"]
    for row in rows:
        status = ("dapat disesuaikan pada run eksplorasi" if row["tunable"]
                  else f"terkunci — {row['reason']}")
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
        st.info(NO_TUNABLE_NOTE)
        if locked:
            with st.expander("Parameter terkunci pipeline ini", expanded=False):
                render_locked_table(rows)
        return {}

    head = st.columns([3, 1])
    head[0].markdown("**Parameter yang dapat disesuaikan**")
    if head[1].button("Kembalikan ke bawaan", key=f"_pov_reset_{pipeline_id}",
                      use_container_width=True,
                      help="Nilai bawaan pipeline menjadi titik awal; tombol "
                           "ini mengembalikan seluruh isian ke nilai itu."):
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
        with st.expander("Parameter yang tetap terkunci", expanded=False):
            render_locked_table(locked)

    # Validasi lapis-UI: pesan muncul di dekat formulirnya, bukan setelah
    # eksperimen gagal. Orchestrator tetap memvalidasi ulang — ini bukan
    # penggantinya.
    try:
        return validate_overrides(pipeline_id, overrides)
    except ParamError as e:
        st.error(str(e))
        return {}


def render_run_mode_block(pipeline_id: str) -> dict:
    """Blok lengkap: pilihan mode, peringatan, dan parameter.

    Mengembalikan ``{"run_mode": str, "param_overrides": dict}`` — siap
    diteruskan ke ``create_and_run_experiment``. Pada mode resmi
    ``param_overrides`` SELALU kosong.
    """
    mode = render_mode_picker()

    if mode != RUN_MODE_EXPLORATION:
        with st.expander("Parameter terkunci pipeline ini", expanded=False):
            render_locked_table(param_rows(pipeline_id))
        return {"run_mode": RUN_MODE_OFFICIAL, "param_overrides": {}}

    st.warning(EXPLORATION_WARNING)
    return {"run_mode": RUN_MODE_EXPLORATION,
            "param_overrides": render_param_form(pipeline_id)}

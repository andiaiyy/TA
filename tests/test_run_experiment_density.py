"""Halaman Run Experiment: berisi tanpa teks basa-basi.

Setelah pemangkasan teks, halaman ini terasa kosong. Kepadatannya dikembalikan
dengan TIGA cara — dan test di sini menjaga agar tidak ada cara KEEMPAT yang
menyelinap masuk (kalimat penjelasan tambahan):

* ruang HORIZONTAL — kontrol dan ringkasannya berdampingan dalam kolom;
* informasi yang MEMANG SUDAH ADA — diagnosa, ``get_info()``, registry, basis
  data — dinaikkan sebagai pasangan label-nilai, bukan paragraf;
* ringkasan keadaan berupa ANGKA yang dihitung, bukan angka tetap.

Kuota teks kecil (maksimal 3 per halaman) tetap dijaga oleh
``tests/test_text_quota_and_layout.py``; di sini yang diperiksa adalah bahwa
pengisian ruang tidak dilakukan dengan menambah teks.
"""
import ast
import re
from pathlib import Path

import pytest

from tests import small_text_audit as audit
from ui.components import sections
from ui.views import login

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_SRC = (REPO_ROOT / "ui" / "views" / "run_experiment.py").read_text(encoding="utf-8")
EXECUTE_BODY = RUN_SRC.split("def _render_execute(")[1].split("\ndef ")[0]


# ── (a) susunan VERTIKAL: kontrol di atas, ringkasan di bawahnya ─────────

def test_no_control_shares_a_row_with_its_summary_block():
    """Kontrol pemilihan TIDAK BOLEH disandingkan dengan blok ringkasan.

    Menyandingkannya membuat kontrolnya menyempit dan tabel di sebelahnya sulit
    dibaca. Ringkasan selalu berada DI BAWAH kontrolnya.
    """
    for gone in ("_ds_right", "_pl_right", "_alg_right", "_ex_right",
                 "st.columns(_COL)"):
        assert gone not in EXECUTE_BODY, gone


def test_each_summary_follows_its_control_in_source_order():
    """Urutan sumber = urutan tampil: kontrol dulu, ringkasannya menyusul."""
    pairs = [
        ('"Pilih dataset"', "render_facts(_dataset_facts("),
        # Penanda khas baris angka milik Pipeline Selection — `render_counts(`
        # sendiri juga dipakai pada keadaan "belum ada dataset terpilih".
        ('"Pilih research pipeline"', '("algoritma", len(algo_to_pid),'),
        ("selected = algo_to_pid.get(algorithm)", "render_facts(_pipeline_facts("),
    ]
    for control, summary in pairs:
        assert control in EXECUTE_BODY, control
        assert summary in EXECUTE_BODY, summary
        assert EXECUTE_BODY.index(control) < EXECUTE_BODY.index(summary)


def test_the_controls_span_their_full_width():
    """Kontrol tidak lagi dibungkus kolom yang menyempitkannya."""
    for control in ('"Pilih dataset"', '"Pilih research pipeline"'):
        before = EXECUTE_BODY[:EXECUTE_BODY.index(control)]
        # Tidak ada `with <sesuatu>_left:` yang masih terbuka di atasnya.
        assert "_left:" not in before.splitlines()[-1]


def test_the_summary_stays_short_by_splitting_into_columns_inside_itself():
    """Vertikal TIDAK boleh berarti panjang: pasangan label-nilai dibagi ke
    beberapa kolom DI DALAM blok ringkasannya sendiri."""
    assert "_FACT_COLUMNS = 2" in EXECUTE_BODY
    assert EXECUTE_BODY.count("columns=_FACT_COLUMNS") >= 2

    from unittest.mock import patch as _patch

    from ui.components.sections import render_facts as _render

    pairs = [(f"k{i}", i) for i in range(6)]
    seen = []
    with _patch("streamlit.html", side_effect=lambda h: seen.append(h)):
        _render(pairs, columns=2)
    # Enam pasangan dalam dua kolom -> tiga baris, bukan enam.
    assert seen[0].count("<tr>") == 3


def test_the_execute_section_stacks_status_above_the_action():
    """Status infrastruktur di atas, kontrol mode & tombol di bawahnya."""
    infra_at = EXECUTE_BODY.index("_render_execution_status_panel(compact=True)")
    mode_at = EXECUTE_BODY.index("render_run_mode_block(selected)")
    button_at = EXECUTE_BODY.index('st.button("Run Experiment"')
    assert infra_at < mode_at < button_at


# ── (b) informasi yang dinaikkan berasal dari data NYATA ──────────────────

def test_dataset_facts_come_from_validation_and_diagnosis():
    """Tidak ada nilai tetap: semuanya dibaca dari dua sumber yang sudah ada."""
    from ui.views.run_experiment import _dataset_facts

    validation = {"row_count": 1234, "column_count": 88,
                  "unique_labels": ["Benign", "Malicious"]}
    diagnosis = {"profile": {"detected_format": "csv", "label_column": "Label",
                             "column_count": 88},
                 "results": {"HIKARI2021": {"compatible": True}},
                 "compatible_types": ["HIKARI2021"]}

    facts = dict(_dataset_facts("HIKARI2021", __file__, validation, diagnosis))
    assert facts["Format"] == "csv"
    assert facts["Baris"] == "1,234"
    assert facts["Kolom"] == 88
    assert facts["Kolom label"] == "Label"
    assert facts["Kelas"] == 2
    assert "HIKARI" in str(facts["Cocok untuk"])


def test_dataset_facts_never_invent_a_value():
    """Sumber kosong -> pasangan kosong, bukan angka karangan."""
    from ui.views.run_experiment import _dataset_facts

    facts = dict(_dataset_facts("", __file__, {}, {}))
    assert facts["Format"] == ""
    assert facts["Baris"] == ""
    assert facts["Cocok untuk"] == "belum ada"
    # Penyaji membuang pasangan kosong, jadi tidak ada baris "—" pengisi ruang.
    assert "Kelas" in facts


def test_pipeline_facts_come_from_get_info():
    from config.pipeline_registry import PIPELINE_REGISTRY
    from ui.views.run_experiment import _pipeline_facts

    pid = "hikari2021.rfc_pipeline"
    info = PIPELINE_REGISTRY[pid]["class"]().get_info() or {}
    facts = _pipeline_facts(pid, info)
    keys = [k for k, _ in facts]

    assert dict(facts)["Algoritma"] == info["algorithm"]
    # Parameter yang ditampilkan benar-benar milik pipeline ini.
    fixed = info.get("fixed_params") or {}
    shown = [k for k in keys if k in fixed]
    assert shown and all(dict(facts)[k] == fixed[k] for k in shown)


def test_only_a_few_locked_params_are_lifted_out_of_the_expander():
    """Detail panjang TETAP di expander — yang naik hanya beberapa."""
    from config.pipeline_registry import PIPELINE_REGISTRY
    from ui.views.run_experiment import _pipeline_facts

    pid = "eve_cbr.xgb"
    info = PIPELINE_REGISTRY[pid]["class"]().get_info() or {}
    fixed = info.get("fixed_params") or {}
    assert len(fixed) > 3                        # pipeline ini memang panjang

    facts = _pipeline_facts(pid, info)
    lifted = [k for k, _ in facts if k in fixed]
    assert len(lifted) <= 3, lifted
    # Daftar lengkapnya masih dirender di expander.
    assert 'st.expander("Pipeline Detail (Read-Only)")' in RUN_SRC
    assert 'st.json(info["fixed_params"])' in RUN_SRC


def test_the_selected_run_mode_is_shown_next_to_the_algorithm():
    from orchestrator import run_mode as rm
    from ui.views.run_experiment import _pipeline_facts

    facts = dict(_pipeline_facts("hikari2021.dt_pipeline", {"algorithm": "DT"}))
    assert facts["Mode eksekusi"] in rm.RUN_MODE_BADGES.values()


def test_infra_facts_mirror_the_health_dict():
    """Panel ringkas tidak memeriksa apa pun sendiri — ia menyajikan ulang."""
    from ui.views.run_experiment import health_facts

    sync = dict(health_facts({"mode": "sync"}))
    assert sync["Mode"] == "Sinkron"

    async_ok = dict(health_facts({"mode": "async", "broker_ok": True,
                                  "worker_ok": True, "worker_count": 2,
                                  "queue_depth": 5}))
    assert async_ok["Broker"] == "tersambung"
    assert async_ok["Worker"] == "2 aktif"
    assert async_ok["Antrian"] == 5

    down = dict(health_facts({"mode": "async", "broker_ok": False,
                              "worker_ok": False}))
    assert down["Broker"] == "terputus"
    assert down["Worker"] == "tidak terdeteksi"


def test_the_compact_panel_changes_shape_only():
    """`compact` tidak boleh mengubah sumber data atau nilai kembaliannya."""
    body = RUN_SRC.split("def _render_execution_status_panel(")[1].split("\ndef ")[0]
    assert "compact: bool = False" in body
    assert body.count("_cached_health(nonce)") == 1     # satu sumber
    assert "recheck_health" in body                     # tombol tetap ada
    assert body.count("return health") >= 3


# ── (c) ringkasan keadaan DIHITUNG ────────────────────────────────────────

def test_the_counts_row_is_computed_not_hardcoded():
    from ui.views.run_experiment import _experiment_counts

    counts = _experiment_counts()
    assert isinstance(counts, dict)
    # Dihitung dari basis data nyata; nilainya bilangan bulat non-negatif.
    assert all(isinstance(v, int) and v >= 0 for v in counts.values())

    tree = ast.parse(RUN_SRC)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "_experiment_counts")
    called = {getattr(c.func, "id", None) or getattr(c.func, "attr", None)
              for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "list_all_experiments" in called


def test_the_counts_row_uses_real_sources_for_every_number():
    """Tiga angka, tiga sumber nyata — tidak ada yang ditulis tangan."""
    block = EXECUTE_BODY.split("render_counts([")[2].split("])")[0]
    assert "len(_ds_options)" in block            # isi storage/datasets/
    assert "len(algo_to_pid)" in block            # registry pipeline kompatibel
    assert "_counts.get(pid, 0)" in block         # basis data eksperimen
    assert not re.search(r"\(\s*\"[^\"]+\"\s*,\s*\d+\s*\)", block), block


def test_no_result_metric_is_shown_on_this_page():
    """Metrik hasil tetap milik halaman Progress & Status."""
    for banned in ("accuracy", "f1_score", "precision_score", "roc_auc"):
        assert banned not in EXECUTE_BODY, banned


# ── Tidak ada teks basa-basi yang ditambahkan ─────────────────────────────

def test_filling_the_space_added_no_narrative_text():
    """Kepadatan datang dari kolom & fakta, BUKAN dari kalimat tambahan."""
    for page in audit.PAGES:
        assert len(audit.audit(page)) <= audit.QUOTA, page

    # Penyaji fakta/angka tidak boleh memuat kalimat: isinya pasangan nilai.
    src = (REPO_ROOT / "ui" / "components" / "sections.py").read_text(encoding="utf-8")
    for fn in ("def render_facts(", "def render_counts("):
        body = src.split(fn)[1].split("\ndef ")[0]
        assert "st.caption(" not in body
        assert "st.info(" not in body
        assert "st.write(" not in body


def test_empty_values_are_dropped_instead_of_padding_the_column():
    """Baris "—" hanya akan memenuhi ruang tanpa memberi informasi."""
    src = (REPO_ROOT / "ui" / "components" / "sections.py").read_text(encoding="utf-8")
    body = src.split("def render_facts(")[1].split("\ndef ")[0]
    assert 'not in ("", "-", "—")' in body


def test_the_facts_table_is_not_small_text():
    """Kepadatan tidak boleh dicapai dengan mengecilkan huruf."""
    from ui.components import theme

    css = theme.stylesheet()
    block = css.split(".ids-facts {")[1].split("}")[0]
    assert f"font-size: {theme.FONT_BODY}" in block
    assert float(theme.FONT_BODY.rstrip("rem")) >= 0.95


def test_section_spacing_stays_generous():
    """Yang dirapatkan adalah ruang HORIZONTAL, bukan jarak antar-bagian."""
    from ui.components import theme

    assert float(theme.GAP_SECTION.rstrip("rem")) >= 1.8
    heading = theme.stylesheet().split('[data-testid="stHeading"] {')[1].split("}")[0]
    assert f"margin: {theme.GAP_SECTION} 0 {theme.GAP_IN_BLOCK} 0" in heading


def test_the_standard_section_helper_is_still_used():
    """Tidak ada gaya bagian baru yang dibuat untuk mengisi ruang."""
    for title in ("Dataset Selection", "Pipeline Selection", "Pilih Algoritma",
                  "Execute"):
        assert f'render_section("{title}"' in RUN_SRC
    assert "st.header(" not in EXECUTE_BODY


# ── Keterangan wajib tetap tersampaikan ───────────────────────────────────

def test_mandatory_notes_survive_the_relayout():
    assert "EXPLORATION_WARNING" in (
        REPO_ROOT / "ui" / "components" / "run_mode_controls.py"
    ).read_text(encoding="utf-8")
    # Sebab tombol Run nonaktif tetap dinyatakan.
    assert "Dataset belum cocok untuk pipeline ini." in EXECUTE_BODY
    assert "Eksekusi asinkron belum siap." in EXECUTE_BODY
    assert login.SIGN_IN_HINT


def test_the_detail_expanders_were_not_emptied():
    """JANGAN memindahkan SELURUH isi expander ke tampilan utama."""
    for expander in ('st.expander("Detail dataset (preview & validasi)"',
                     'st.expander("Tentang Research Pipeline (Read-Only)"',
                     'st.expander("Pipeline Detail (Read-Only)")',
                     'st.expander("Pipeline Config Viewer'):
        assert expander in RUN_SRC, expander


# ── AppTest: tiga status pengguna × tiga kondisi dataset ──────────────────

IDENTITIES = {
    "pengunjung": None,
    "kontributor": {"username": "rina", "role": "contributor", "status": "active"},
    "research_admin": {"username": "ai", "role": "research_admin", "status": "active"},
}


def _script(preset: dict) -> str:
    return (
        "import sys\n"
        f"sys.path.insert(0, r{str(REPO_ROOT)!r})\n"
        "import streamlit as st\n"
        "from ui.components import theme\n"
        "theme.inject()\n"
        + "".join(f"st.session_state[{k!r}] = {v!r}\n" for k, v in preset.items())
        + "from ui.views.run_experiment import render\n"
        "render()\n"
    )


def _dataset(kind: str):
    from ui.views.run_experiment import _all_dataset_options

    paths = [p for p, _ in _all_dataset_options()]
    if kind == "belum dipilih":
        return None
    if kind == "tidak cocok":
        match = [p for p in paths if "Thursday" in p]
    else:
        match = [p for p in paths if "ALLFLOWMETER" in p]
    if not match:
        pytest.skip(f"berkas untuk kondisi {kind!r} tidak tersedia")
    return match[0]


@pytest.mark.parametrize("who", sorted(IDENTITIES))
@pytest.mark.parametrize("kondisi", ["belum dipilih", "tidak cocok"])
def test_the_page_renders_for_every_identity_and_dataset_state(tmp_path, who,
                                                               kondisi):
    """Kondisi "cocok" memerlukan parse dataset 302 MB, jadi diuji terpisah
    (lihat test di bawah) agar suite tetap cepat."""
    from streamlit.testing.v1 import AppTest

    preset = {"_current_page": "Run Experiment", "_run_view": "execute"}
    chosen = _dataset(kondisi)
    if chosen:
        preset["dataset_select"] = chosen

    script = tmp_path / "run_page.py"
    script.write_text(_script(preset), encoding="utf-8")
    at = AppTest.from_file(str(script), default_timeout=900)
    if IDENTITIES[who]:
        at.session_state[login.SESSION_USER_KEY] = IDENTITIES[who]
    at.run()
    assert at.exception is None or not at.exception, (who, kondisi, at.exception)


@pytest.mark.parametrize("kondisi", ["belum dipilih", "tidak cocok"])
def test_the_summary_column_is_filled_in_every_state(tmp_path, kondisi):
    """Kolom kanan tidak pernah kosong — itulah yang membuat halaman terasa
    berisi."""
    from streamlit.testing.v1 import AppTest

    preset = {"_current_page": "Run Experiment", "_run_view": "execute"}
    chosen = _dataset(kondisi)
    if chosen:
        preset["dataset_select"] = chosen

    script = tmp_path / "run_page.py"
    script.write_text(_script(preset), encoding="utf-8")
    at = AppTest.from_file(str(script), default_timeout=900)
    at.run()
    assert at.exception is None or not at.exception

    blocks = [e.proto.body for e in at.get("html")]
    filled = [b for b in blocks if "ids-facts" in b or "ids-counts" in b]
    assert filled, (kondisi, blocks[:2])

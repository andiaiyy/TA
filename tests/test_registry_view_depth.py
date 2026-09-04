"""Bagian "Aktif" & "Riwayat versi" — tempat ketertelusuran terlihat.

Kalau seseorang bertanya *"eksperimen ini memakai kode yang mana persisnya"*,
jawabannya harus ada di kedua bagian ini. Yang dijaga:

* angkanya cocok dengan basis data, dan dipecah PER VERSI — di situlah dampak
  penyuntingan terlihat;
* menonaktifkan tidak menghapus apa pun dan dapat dibatalkan;
* pipeline nonaktif maupun yang GAGAL DIMUAT tetap tampil, tidak disembunyikan
  dan tidak tampak normal;
* riwayat bersifat baca-saja, dan kode tiap versi tetap dapat dibaca.
"""
import ast
import sqlite3
from pathlib import Path

import pytest

from database.db import create_experiment, init_db, set_running
from orchestrator.auth_service import PermissionDenied
from orchestrator.dynamic_registry import (
    file_sha256, get_registered, list_registered, register_pipeline,
    set_pipeline_active,
)
from orchestrator.pipeline_versions import (
    experiment_counts, running_experiments, save_new_version, version_history,
)
from ui.components import registry_view as rv
from ui.views import manage_pipelines as mp

REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE_SRC = (REPO_ROOT / "ui" / "views"
            / "manage_pipelines.py").read_text(encoding="utf-8")

ADMIN = {"username": "boss", "role": "research_admin", "status": "active"}
CONTRIBUTOR = {"username": "rina", "role": "contributor", "status": "active"}
VISITOR = None

VALID = '''
from pipelines.base import BasePipeline


class Up(BasePipeline):
    def run(self, pipeline_input, progress=None):
        return "v1"

    def get_info(self):
        return {"paper": "Uploaded (2026)", "algorithm": "Uploaded RF"}
'''
EDITED = VALID.replace('return "v1"', 'return "v2"')


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Satu pipeline kontribusi dua versi, dengan eksperimen di keduanya."""
    import orchestrator.pipeline_versions as pv

    db_path = str(tmp_path / "reg.db")
    init_db(db_path)
    monkeypatch.setattr(pv, "VERSIONS_ROOT", tmp_path / "versions")

    def _conn(path=None):
        conn = sqlite3.connect(path or db_path)
        conn.row_factory = sqlite3.Row
        return conn

    for module in ("database.db", "orchestrator.dynamic_registry",
                   "orchestrator.pipeline_versions"):
        monkeypatch.setattr(f"{module}.get_connection", _conn)

    entry = tmp_path / "approved" / "up.py"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(VALID, encoding="utf-8")
    v1 = register_pipeline(name="contoh", dataset_type="HIKARI2021",
                           entry_class="Up", entry_file=entry,
                           registered_by="boss", algorithm="Uploaded RF",
                           paper="Uploaded (2026)", db_path=db_path)
    v2 = save_new_version(v1["pipeline_id"], EDITED,
                          change_note="perbaiki label", actor=ADMIN,
                          db_path=db_path)

    # Dua eksperimen di v1, satu di v2 (yang terakhir sedang BERJALAN).
    for index, pid in enumerate([v1["pipeline_id"], v1["pipeline_id"],
                                 v2["pipeline_id"]]):
        create_experiment(experiment_id=f"e{index}", dataset_type="HIKARI2021",
                          dataset_path="/d.csv", dataset_hash="h",
                          created_at=f"2026-01-0{index + 1}T00:00:00",
                          pipeline_id=pid, db_path=db_path)
    set_running("e2", started_at="2026-01-03T00:01:00", db_path=db_path)

    return {"db": db_path, "v1": v1, "v2": v2, "entry": entry, "tmp": tmp_path}


# ── Data berasal dari catatan tersimpan ───────────────────────────────────

def test_the_summary_reads_every_stored_column(env):
    versions = version_history("contoh", db_path=env["db"])
    summary = rv.pipeline_summary("contoh", versions,
                                  experiment_counts(db_path=env["db"]))

    assert summary["pipeline_id"] == env["v2"]["pipeline_id"]
    assert summary["version"] == 2
    assert summary["dataset_type"] == "HIKARI2021"
    assert summary["algorithm"] == "Uploaded RF"
    assert summary["paper"] == "Uploaded (2026)"
    assert summary["entry_class"] == "Up"
    assert summary["file_hash"] == env["v2"]["file_hash"]
    assert summary["registered_by"] == "boss"
    assert summary["registered_at"]
    # Penyunting & catatan perubahan — kolom yang sebelumnya tak pernah tampil.
    assert summary["edited_by"] == ADMIN["username"]
    assert summary["edited_at"]
    assert summary["change_note"] == "perbaiki label"
    assert summary["version_count"] == 2


def test_the_facts_include_the_editor_only_when_there_was_an_edit(env):
    versions = version_history("contoh", db_path=env["db"])
    counts = experiment_counts(db_path=env["db"])

    edited = dict(rv.summary_facts(
        rv.pipeline_summary("contoh", versions, counts)))
    assert "Disunting terakhir" in edited
    assert "Catatan perubahan" in edited

    # Versi 1 lahir dari PERSETUJUAN — tidak punya penyunting, dan barisnya
    # memang tidak muncul (bukan "—" yang hanya memenuhi ruang).
    first = dict(rv.summary_facts(
        rv.pipeline_summary("contoh", [versions[-1]], counts)))
    assert "Disunting terakhir" not in first
    assert "Catatan perubahan" not in first


def test_nothing_is_invented_for_an_unknown_pipeline():
    summary = rv.pipeline_summary("kosong", [], {})
    assert summary["experiments"] == 0
    assert summary["versions"] == []
    assert rv.usage_text(summary) == "Belum dipakai eksperimen mana pun."
    assert rv.running_text(summary) == ""


# ── Hitungan per pipeline & per versi ─────────────────────────────────────

def test_experiment_counts_are_already_per_version(env):
    """Nomor versi melekat pada pipeline_id, jadi hitungannya per versi."""
    counts = experiment_counts(db_path=env["db"])
    assert counts[env["v1"]["pipeline_id"]] == 2
    assert counts[env["v2"]["pipeline_id"]] == 1

    conn = sqlite3.connect(env["db"])
    rows = dict(conn.execute(
        "SELECT pipeline_id, COUNT(*) FROM experiments GROUP BY pipeline_id"))
    conn.close()
    assert counts == {k: v for k, v in rows.items() if k.startswith("uploaded.")}


def test_the_summary_splits_usage_by_version(env):
    summary = rv.pipeline_summary("contoh",
                                  version_history("contoh", db_path=env["db"]),
                                  experiment_counts(db_path=env["db"]))
    assert summary["experiments"] == 3                # total seluruh versi
    per_version = {v["version"]: v["experiments"] for v in summary["versions"]}
    assert per_version == {1: 2, 2: 1}

    text = rv.usage_text(summary)
    assert "3 eksperimen" in text
    assert "v1: 2" in text and "v2: 1" in text


def test_a_running_experiment_is_flagged(env):
    running = {env["v2"]["pipeline_id"]:
               running_experiments(env["v2"]["pipeline_id"], env["db"])}
    summary = rv.pipeline_summary("contoh",
                                  version_history("contoh", db_path=env["db"]),
                                  experiment_counts(db_path=env["db"]),
                                  running=running)
    assert summary["running"] == 1
    text = rv.running_text(summary)
    assert "1 eksperimen berjalan" in text
    assert "v2: 1" in text
    assert "tidak mengganggu" in text


# ── Menonaktifkan & mengaktifkan kembali ─────────────────────────────────

def test_deactivating_hides_it_from_new_experiments_only(env):
    from orchestrator.dynamic_registry import get_pipelines_for_dataset_merged

    available = get_pipelines_for_dataset_merged("HIKARI2021", db_path=env["db"])
    assert env["v2"]["pipeline_id"] in available

    set_pipeline_active(env["v2"]["pipeline_id"], False, actor=ADMIN,
                        db_path=env["db"])
    after = get_pipelines_for_dataset_merged("HIKARI2021", db_path=env["db"])
    assert env["v2"]["pipeline_id"] not in after


def test_deactivating_deletes_nothing(env):
    path = Path(env["v2"]["entry_file"])
    before = path.read_bytes()

    set_pipeline_active(env["v2"]["pipeline_id"], False, actor=ADMIN,
                        db_path=env["db"])

    row = get_registered(env["v2"]["pipeline_id"], env["db"])
    assert row is not None and row["active"] == 0
    assert row["file_hash"] == env["v2"]["file_hash"]
    assert path.read_bytes() == before                 # berkas utuh
    # Riwayat versinya juga tetap lengkap.
    assert len(version_history("contoh", db_path=env["db"])) == 2


def test_old_experiments_are_untouched_by_deactivation(env):
    conn = sqlite3.connect(env["db"])
    before = conn.execute("SELECT id, pipeline_id FROM experiments "
                          "ORDER BY id").fetchall()
    conn.close()

    set_pipeline_active(env["v2"]["pipeline_id"], False, actor=ADMIN,
                        db_path=env["db"])

    conn = sqlite3.connect(env["db"])
    after = conn.execute("SELECT id, pipeline_id FROM experiments "
                         "ORDER BY id").fetchall()
    conn.close()
    assert before == after


def test_it_can_be_reactivated(env):
    set_pipeline_active(env["v2"]["pipeline_id"], False, actor=ADMIN,
                        db_path=env["db"])
    set_pipeline_active(env["v2"]["pipeline_id"], True, actor=ADMIN,
                        db_path=env["db"])
    assert get_registered(env["v2"]["pipeline_id"], env["db"])["active"] == 1


def test_a_deactivated_pipeline_is_still_listed(env):
    set_pipeline_active(env["v2"]["pipeline_id"], False, actor=ADMIN,
                        db_path=env["db"])

    rows = list_registered(db_path=env["db"])
    summaries = [rv.pipeline_summary(name, versions,
                                     experiment_counts(db_path=env["db"]))
                 for name, versions in rv.group_versions(rows).items()]
    assert [s["name"] for s in summaries] == ["contoh"]
    assert summaries[0]["is_active"] is False          # tertandai, bukan hilang


def test_deactivation_asks_for_confirmation_and_can_be_cancelled():
    body = PAGE_SRC.split("def _render_deactivate_confirm(")[1].split(
        chr(10) + "def ")[0]
    assert "DEACTIVATE_CONSEQUENCE" in body
    assert 't("ap.btn_yes_deactivate")' in body
    assert 't("action.cancel")' in body
    # Tombol Nonaktifkan hanya MENANDAI, tidak langsung mengubah apa pun.
    actions = PAGE_SRC.split("def _render_pipeline_actions(")[1].split(
        chr(10) + "def ")[0]
    off_at = actions.index('t("ap.btn_deactivate")')
    assert "_CONFIRM_OFF_KEY] = pipeline_id" in actions[off_at:]


def test_the_consequence_is_stated_plainly():
    assert "eksperimen BARU" in rv.DEACTIVATE_CONSEQUENCE
    assert "tidak terpengaruh" in rv.DEACTIVATE_CONSEQUENCE
    assert "tetap utuh" in rv.DEACTIVATE_CONSEQUENCE


# ── Pipeline yang gagal dimuat ────────────────────────────────────────────

def test_a_tampered_version_is_shown_as_broken_with_its_reason(env):
    path = Path(env["v2"]["entry_file"])
    path.write_text(EDITED + "\n# diubah di luar platform\n", encoding="utf-8")
    assert file_sha256(path) != env["v2"]["file_hash"]

    summary = rv.pipeline_summary("contoh",
                                  version_history("contoh", db_path=env["db"]),
                                  experiment_counts(db_path=env["db"]))
    assert summary["state"] == rv.STATE_TAMPERED
    assert "hash" in rv.STATE_TAMPERED                 # nama keadaannya
    assert "SHA-256" in summary["state_reason"]        # sebabnya dinyatakan
    assert "ditolak" in summary["state_reason"]
    assert rv.STATE_MARK[summary["state"]] != rv.STATE_MARK[rv.STATE_OK]


def test_a_missing_file_is_shown_as_broken(env):
    Path(env["v2"]["entry_file"]).unlink()
    state, reason = rv.version_state(
        get_registered(env["v2"]["pipeline_id"], env["db"]))
    assert state == rv.STATE_MISSING
    assert "tidak ditemukan" in reason


def test_a_broken_version_does_not_break_the_rest_of_the_list(env):
    Path(env["v2"]["entry_file"]).unlink()

    rows = list_registered(db_path=env["db"])
    grouped = rv.group_versions(rows)
    summaries = [rv.pipeline_summary(name, versions,
                                     experiment_counts(db_path=env["db"]))
                 for name, versions in grouped.items()]
    assert len(summaries) == 1
    # Versi 1 tetap sehat dan tetap terbaca di riwayat.
    history = rv.history_rows(version_history("contoh", db_path=env["db"]),
                              experiment_counts(db_path=env["db"]))
    states = {row["version"]: row["state"] for row in history}
    assert states[1] == rv.STATE_OK
    assert states[2] == rv.STATE_MISSING


def test_checking_for_breakage_never_runs_the_code():
    """Keadaan rusak diketahui dari hash, bukan dari mencoba memuatnya."""
    banned = {"exec", "eval", "compile", "__import__",
              "spec_from_file_location", "exec_module", "load_pipeline_class",
              "load_registered_instance", "get_pipeline_instance_merged"}
    src = (REPO_ROOT / "ui" / "components"
           / "registry_view.py").read_text(encoding="utf-8")
    called = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call):
            func = node.func
            called.add(getattr(func, "id", None) or getattr(func, "attr", None))
    assert not (called & banned), called & banned
    assert "file_sha256" in src


# ── Riwayat versi ─────────────────────────────────────────────────────────

def test_the_history_lists_every_version_newest_first(env):
    rows = rv.history_rows(version_history("contoh", db_path=env["db"]),
                           experiment_counts(db_path=env["db"]))
    assert [r["version"] for r in rows] == [2, 1]
    assert rows[0]["active"] is True and rows[1]["active"] is False
    assert rows[0]["who"] == ADMIN["username"]
    assert rows[0]["note"] == "perbaiki label"
    assert rows[1]["note"] == "versi awal (dari persetujuan)"
    assert rows[0]["experiments"] == 1 and rows[1]["experiments"] == 2


def test_the_active_version_is_marked_in_the_table(env):
    rows = rv.history_rows(version_history("contoh", db_path=env["db"]),
                           experiment_counts(db_path=env["db"]))
    table = rv.history_table_html(rows)
    assert "v2 ←" in table                              # penanda TEKSTUAL
    assert "v1 ←" not in table
    assert "ids-tbl-on" in table                        # barisnya disorot


def test_the_history_table_right_aligns_the_numbers_and_keeps_full_hashes(env):
    rows = rv.history_rows(version_history("contoh", db_path=env["db"]),
                           experiment_counts(db_path=env["db"]))
    table = rv.history_table_html(rows)

    assert 'class="ids-tbl-num"' in table               # angka rata kanan
    assert "ids-tbl-scroll" in table                    # gulir mendatar
    for row in rows:
        assert rv.short_hash(row["hash"]) in table      # dipendekkan
        assert f'title="{row["hash"]}"' in table        # penuh di tooltip


def test_the_history_offers_no_way_to_change_a_version():
    body = PAGE_SRC.split("def render_history(")[1].split(chr(10) + "def ")[0]
    for forbidden in ("save_new_version", "set_pipeline_active", "delete",
                      "hapus", "rollback", "putar balik"):
        assert forbidden not in body, forbidden
    assert "READ_ONLY_NOTE" in body
    assert "RETENTION_NOTE" in body


def test_the_read_only_note_points_at_the_right_path():
    """Tiga hal WAJIB tersampaikan — dan harus RINGKAS.

    Yang diperiksa adalah informasinya, bukan kalimatnya: (1) versi lama tetap
    tersimpan sehingga tertelusur, (2) perbandingan/riwayat baca-saja,
    (3) menyunting menghasilkan versi baru.
    """
    read_only = rv.READ_ONLY_NOTE.lower()
    assert "baca-saja" in read_only                     # (2)
    assert "versi BARU" in rv.READ_ONLY_NOTE            # (3)
    retention = rv.RETENTION_NOTE.lower()
    assert "versi lama tetap tersimpan" in retention    # (1)
    assert "telusur" in retention                       # (1) alasannya

    # PADAT: masing-masing satu baris pendek, bukan paragraf.
    for note in (rv.RETENTION_NOTE, rv.READ_ONLY_NOTE, rv.EXPERIMENT_LINK_NOTE):
        assert "\n" not in note
        assert len(note) <= 90, (len(note), note)


def test_each_version_code_can_be_read_back(env):
    """Inti ketertelusuran: kode yang dipakai eksperimen lama tetap terbaca."""
    from orchestrator.pipeline_versions import read_source

    assert read_source(env["v1"]["pipeline_id"], env["db"]) == VALID
    assert read_source(env["v2"]["pipeline_id"], env["db"]) == EDITED


def test_the_code_viewer_is_read_only():
    """Tampilan perbandingan membaca, tidak pernah menulis.

    Tidak ada penyuntingan, tidak ada penyimpanan, dan — yang diminta secara
    khusus — tidak ada aksi MEMULIHKAN/menerapkan versi lama dari sini.
    """
    import ast

    body = PAGE_SRC.split("def _render_compare(")[1].split(chr(10) + "def ")[0]
    assert "_version_package(" in body
    assert "text_area" not in body                      # tidak dapat disunting

    # Tidak ada satu pun pemanggilan yang MENULIS — diperiksa dari pemanggilan
    # nyata, bukan dari kata yang kebetulan muncul di teks bantuan (teks itu
    # justru MENYATAKAN bahwa pemulihan tidak tersedia).
    tree = ast.parse(PAGE_SRC)
    func = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "_render_compare")
    called = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            target = node.func
            called.add(target.attr if isinstance(target, ast.Attribute)
                       else getattr(target, "id", ""))
    for writer in ("save_new_version", "set_pipeline_active",
                   "register_pipeline", "write_text", "unlink"):
        assert writer not in called, writer

    # …dan tidak ada TOMBOL yang menawarkan pemulihan versi.
    # Label tombol kini dibaca dari kamus, jadi argumennya sebuah PANGGILAN
    # `t("...")` — kuncinya yang diperiksa, bukan teks harfiahnya.
    keys = [n.args[0].args[0].value for n in ast.walk(func)
            if isinstance(n, ast.Call)
            and getattr(n.func, "attr", "") == "button"
            and n.args and isinstance(n.args[0], ast.Call)
            and getattr(n.args[0].func, "id", "") == "t"]
    assert keys == ["ap.btn_back_history"], keys


def test_comparing_two_versions_reports_the_hash_difference(env):
    versions = version_history("contoh", db_path=env["db"])
    note = rv.compare_note(versions[1], versions[0])
    assert rv.short_hash(versions[0]["file_hash"]) in note
    assert rv.short_hash(versions[1]["file_hash"]) in note

    same = rv.compare_note(versions[0], versions[0])
    assert "identik" in same
    # Keterangannya PADAT: satu baris, bukan kalimat penjelasan.
    assert "\n" not in note and len(note) <= 80, (len(note), note)


def test_the_experiment_link_states_its_limitation():
    assert "Progress & Status" in rv.EXPERIMENT_LINK_NOTE
    assert "Pipeline" in rv.EXPERIMENT_LINK_NOTE


# ── Izin ditegakkan di FUNGSI ────────────────────────────────────────────

@pytest.mark.parametrize("actor", [VISITOR, CONTRIBUTOR],
                         ids=["pengunjung", "kontributor"])
def test_only_a_research_admin_may_deactivate(env, actor):
    with pytest.raises(PermissionDenied):
        set_pipeline_active(env["v2"]["pipeline_id"], False, actor=actor,
                            db_path=env["db"])
    assert get_registered(env["v2"]["pipeline_id"], env["db"])["active"] == 1


@pytest.mark.parametrize("actor", [VISITOR, CONTRIBUTOR],
                         ids=["pengunjung", "kontributor"])
def test_only_a_research_admin_may_reactivate(env, actor):
    set_pipeline_active(env["v2"]["pipeline_id"], False, actor=ADMIN,
                        db_path=env["db"])
    with pytest.raises(PermissionDenied):
        set_pipeline_active(env["v2"]["pipeline_id"], True, actor=actor,
                            db_path=env["db"])
    assert get_registered(env["v2"]["pipeline_id"], env["db"])["active"] == 0


# ── AppTest ───────────────────────────────────────────────────────────────

def _script(repo: str, db: str, tmp: str, seed: bool) -> str:
    return f'''
import sqlite3, sys
sys.path.insert(0, r"{repo}")
import streamlit as st
import database.db as dbmod
import orchestrator.dynamic_registry as dr
import orchestrator.pipeline_versions as pv
from database.db import init_db
from pathlib import Path

DB = r"{db}"
TMP = Path(r"{tmp}")

def conn(path=None):
    c = sqlite3.connect(path or DB)
    c.row_factory = sqlite3.Row
    return c

dbmod.get_connection = conn
dr.get_connection = conn
pv.get_connection = conn
pv.VERSIONS_ROOT = TMP / "versions"
init_db(DB)

if {seed!r} and not dr.list_registered(db_path=DB):
    entry = TMP / "approved" / "up.py"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text({VALID!r}, encoding="utf-8")
    v1 = dr.register_pipeline(name="contoh", dataset_type="HIKARI2021",
                              entry_class="Up", entry_file=entry,
                              registered_by="boss", db_path=DB)
    pv.save_new_version(v1["pipeline_id"], {EDITED!r},
                        change_note="perbaiki label",
                        actor={{"username": "boss", "role": "research_admin"}},
                        db_path=DB)
    st.session_state["_mp_history"] = "contoh"

from ui.components import theme
theme.inject()
st.session_state["_current_page"] = "Add Pipeline & Dataset"
st.session_state["_contrib_mode"] = "review"
from ui.views.contribute import render
render()
'''


def _run(tmp_path, *, seed: bool, section: str = "Aktif"):
    """Jalankan halaman pada SATU bagian, lalu KEMBALIKAN state global.

    ``section`` wajib dipilih sejak dulu bagian-bagiannya benar-benar saling
    meniadakan. Sebelumnya bagian "Menunggu tinjauan" ikut menggambar "Aktif"
    dan "Riwayat versi" di bawahnya, jadi test ini dapat memeriksa keduanya
    tanpa pernah memilihnya — dan karena itu tidak dapat membedakan
    "penyajinya bekerja" dari "bagiannya bocor".

    AppTest menjalankan skripnya di proses yang sama dan skrip itu memasang
    sambungan basis data sementara lewat penugasan langsung; tanpa pemulihan,
    test berikutnya akan melihat basis data kosong lalu melewati dirinya
    sendiri tanpa suara.
    """
    import database.db as dbmod
    import orchestrator.dynamic_registry as dr
    import orchestrator.pipeline_versions as pv
    from streamlit.testing.v1 import AppTest

    from ui.views import login

    saved = (dbmod.get_connection, dr.get_connection, pv.get_connection,
             pv.VERSIONS_ROOT)
    try:
        script = tmp_path / "page.py"
        script.write_text(_script(str(REPO_ROOT), str(tmp_path / "at.db"),
                                  str(tmp_path), seed), encoding="utf-8")
        at = AppTest.from_file(str(script), default_timeout=900)
        at.session_state[login.SESSION_USER_KEY] = ADMIN
        at.session_state[mp.SECTION_KEY] = section
        at.session_state["_mp_section_last"] = section
        at.run()
        assert at.exception is None or not at.exception, at.exception
        return at
    finally:
        (dbmod.get_connection, dr.get_connection, pv.get_connection,
         pv.VERSIONS_ROOT) = saved


def test_both_sections_render_for_a_research_admin(tmp_path):
    """Keduanya tergambar — masing-masing DI BAGIANNYA SENDIRI.

    Dulu satu penggambaran cukup untuk memeriksa keduanya, karena bagian
    "Menunggu tinjauan" ikut menggambar keduanya di bawahnya. Sekarang tiap
    bagian dipilih secara eksplisit, sehingga test ini membuktikan penyajinya
    benar-benar bekerja alih-alih menumpang kebocoran.
    """
    active = _run(tmp_path, seed=True, section="Aktif")
    text = " ".join(m.value for m in active.markdown)
    assert "contoh" in text                             # bagian Aktif
    assert "eksperimen" in text
    labels = {b.label for b in active.button}
    assert {"Sunting", "Nonaktifkan", "Riwayat"} <= labels

    # Riwayat versi tampil sebagai tabel, dengan versi aktif tertandai.
    history = _run(tmp_path, seed=True, section="Riwayat versi")
    htext = " ".join(m.value for m in history.markdown)
    tables = [e.proto.body for e in history.get("html")
              if "ids-tbl" in e.proto.body]
    assert tables
    assert any("v2 ←" in t for t in tables)
    assert rv.RETENTION_NOTE in htext
    assert rv.READ_ONLY_NOTE in htext


def test_each_section_leaves_the_other_out(tmp_path):
    """Sisi lain dari test di atas: yang TIDAK dipilih memang tidak tergambar.

    Tanpa ini, kebocoran yang sama dapat kembali tanpa satu test pun gagal.
    """
    active = _run(tmp_path, seed=True, section="Aktif")
    atext = " ".join(m.value for m in active.markdown)
    assert rv.RETENTION_NOTE not in atext        # milik "Riwayat versi"

    history = _run(tmp_path, seed=True, section="Riwayat versi")
    hlabels = {b.label for b in history.button}
    assert "Nonaktifkan" not in hlabels          # milik "Aktif"


def test_the_empty_state_renders(tmp_path):
    """Keadaan kosong ada DI DALAM tabel — bukan tabel kosong tanpa penjelasan."""
    at = _run(tmp_path, seed=False, section="Aktif")
    tables = [e.proto.body for e in at.get("html") if "ids-tbl" in e.proto.body]
    assert tables, "tabel tetap digambar meski tanpa isi"
    assert any(rv.EMPTY_STATE in t for t in tables)
    assert any("ids-tbl-empty" in t for t in tables)

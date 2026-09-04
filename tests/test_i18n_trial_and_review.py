"""
Sisa terjemahan: hasil uji coba & bagian peninjauan.

Yang dijaga di sini terutama satu cacat yang sempat kembali: nama tahap uji
coba adalah teks Indonesia yang DISISIPKAN mentah ke kalimat katalog, sehingga
mode Inggris menampilkan

    Trial FAILED at the **menjalankan pipeline** stage

— satu kalimat, dua bahasa. Pola yang sama pernah diperbaiki pada catatan kaki
metrik laporan PDF; test ini mencegahnya muncul lagi di jalur uji coba.

Satu hal yang justru TIDAK diterjemahkan dan diuji begitu: pesan kegagalan
yang datang dari pipeline yang sedang diuji. Itu kata-kata pipeline itu
sendiri, dan menggantinya berarti mengarang isi laporan kegagalan.
"""
import re

import pytest

import ui.i18n.core as core
from ui.i18n import CATALOG
from ui.i18n.core import lookup

INDONESIAN = {
    "yang", "tidak", "belum", "dapat", "untuk", "dengan", "pada", "dari",
    "akan", "sudah", "harus", "adalah", "atau", "dan", "karena", "hanya",
    "ini", "itu", "masih", "tetap", "saat", "oleh", "ada", "berkas",
    "pengguna", "eksperimen", "pengajuan", "memuat", "membaca", "menjalankan",
    "tahap", "batas", "waktu", "dihentikan", "melampaui",
}
_WORD = re.compile(r"[A-Za-z]+")
_TAG = re.compile(r"<[^>]+>")


def _words(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(_TAG.sub(" ", text or ""))}


@pytest.fixture(autouse=True)
def indonesian():
    core.st.session_state[core.LANG_KEY] = "id"
    yield
    core.st.session_state[core.LANG_KEY] = "id"


# ── Tahap uji coba ───────────────────────────────────────────────────────

def test_every_trial_stage_has_a_label_in_both_languages():
    from ui.components.validator_messages import TRIAL_STAGE_KEYS
    from workers import trial_runner

    stages = {trial_runner.STAGE_LOAD, trial_runner.STAGE_READ,
              trial_runner.STAGE_RUN, trial_runner.STAGE_TIMEOUT}
    assert stages <= set(TRIAL_STAGE_KEYS), stages - set(TRIAL_STAGE_KEYS)
    for key in TRIAL_STAGE_KEYS.values():
        assert lookup(key, "id") and lookup(key, "en"), key


def test_the_stage_identifier_never_changes_with_the_language():
    """Nilai tahap TERSIMPAN pada catatan uji — ia pengenal, bukan kalimat."""
    from workers import trial_runner

    core.st.session_state[core.LANG_KEY] = "en"
    assert trial_runner.STAGE_RUN == "menjalankan pipeline"
    assert trial_runner.STAGE_TIMEOUT == "batas waktu"


@pytest.mark.parametrize("lang, expected", [
    ("id", "menjalankan pipeline"),
    ("en", "running the pipeline"),
])
def test_the_stage_label_follows_the_language(lang, expected):
    from ui.components.validator_messages import trial_stage
    from workers import trial_runner

    core.st.session_state[core.LANG_KEY] = lang
    assert trial_stage(trial_runner.STAGE_RUN) == expected


def test_the_failure_sentence_is_never_half_indonesian():
    """Cacat yang dijaga berkas ini: satu kalimat, dua bahasa."""
    from ui.components.validator_messages import trial_stage
    from ui.i18n import t
    from workers import trial_runner

    core.st.session_state[core.LANG_KEY] = "en"
    for stage in (trial_runner.STAGE_LOAD, trial_runner.STAGE_READ,
                  trial_runner.STAGE_RUN, trial_runner.STAGE_TIMEOUT):
        sentence = t("trial.result_failed", stage=trial_stage(stage))
        leaked = _words(sentence) & INDONESIAN
        assert not leaked, (stage, sorted(leaked))


def test_the_renderer_translates_the_stage_before_inserting_it():
    """Sisipan mentah adalah cara cacat itu masuk; jalurnya ditutup."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "ui" / "views"
           / "contribute.py").read_text(encoding="utf-8")
    assert 'stage=trial_stage(trial.get("error_stage"))' in src
    assert 'stage=trial.get("error_stage") or "—"' not in src


# ── Pesan kegagalan ──────────────────────────────────────────────────────

@pytest.mark.parametrize("lang", ["id", "en"])
def test_a_platform_failure_message_follows_the_language(lang):
    from ui.components.validator_messages import trial_failure_message

    core.st.session_state[core.LANG_KEY] = lang
    timeout = trial_failure_message("TrialTimeout", "pesan lama apa pun")
    died = trial_failure_message("ProcessDied", "pesan lama apa pun")
    assert timeout and died
    if lang == "en":
        assert not (_words(timeout) & INDONESIAN), timeout
        assert not (_words(died) & INDONESIAN), died


def test_the_timeout_message_states_the_actual_limit():
    from orchestrator.trial_service import TRIAL_LIMITS
    from ui.components.validator_messages import trial_failure_message

    core.st.session_state[core.LANG_KEY] = "en"
    message = trial_failure_message("TrialTimeout", "")
    assert str(TRIAL_LIMITS["max_seconds"]) in message


@pytest.mark.parametrize("lang", ["id", "en"])
def test_a_pipeline_message_is_returned_verbatim(lang):
    """Kata-kata pipeline TIDAK diterjemahkan — itu isi yang dicari peninjau."""
    from ui.components.validator_messages import trial_failure_message

    core.st.session_state[core.LANG_KEY] = lang
    detail = "KeyError: kolom 'flow_duration' tidak ada"
    assert trial_failure_message("KeyError", detail) == detail


def test_only_platform_written_failures_are_translated():
    """Daftarnya sempit dan disengaja."""
    from ui.components.validator_messages import TRIAL_FAILURE_KEYS

    assert set(TRIAL_FAILURE_KEYS) == {"TrialTimeout", "ProcessDied"}


# ── Sisa teks bagian peninjauan ──────────────────────────────────────────

REVIEW_KEYS = [
    "ap.review_pending_count", "ap.review_history_heading",
    "ap.review_history_empty", "ap.my_submissions_empty",
    "sr.summary_line", "pc.pre_stage_parse", "pc.pre_stage_note",
]


@pytest.mark.parametrize("key", REVIEW_KEYS)
def test_the_review_texts_exist_in_both_languages(key):
    assert key in CATALOG
    assert lookup(key, "id") and lookup(key, "en")
    assert not (_words(lookup(key, "en")) & INDONESIAN), key


def test_the_submission_status_labels_reuse_the_existing_keys():
    """Tiga label yang sama tidak boleh punya dua salinan."""
    import ui.views.contribute as c

    assert set(c._STATUS_LABEL_KEYS.values()) == {
        "ap.sub_pending", "ap.sub_approved", "ap.sub_rejected"}
    core.st.session_state[core.LANG_KEY] = "en"
    assert c._status_label("approved") == lookup("ap.sub_approved", "en")


def test_the_platform_stage_labels_are_not_frozen_at_import():
    """Konstanta modul dievaluasi sekali — kalimatnya harus dari katalog."""
    from ui.components import pipeline_catalog as pc

    core.st.session_state[core.LANG_KEY] = "id"
    indonesian = pc.pre_stage_labels()
    core.st.session_state[core.LANG_KEY] = "en"
    english = pc.pre_stage_labels()
    assert indonesian != english
    assert len(indonesian) == len(english) == len(pc.PRE_STAGE_KEYS)


def test_the_phase_graph_still_shows_the_platform_stages():
    """Parameter `pre_stages` sempat MENUTUPI fungsi bernama sama."""
    from ui.components import pipeline_catalog as pc

    stages = [{"label": "Training", "kind": "pipeline", "note": ""}]
    alt = pc.phase_graph_alt(stages)
    for label in pc.pre_stage_labels():
        assert label in alt, label

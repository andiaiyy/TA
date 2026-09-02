"""
Pengambil teks, bahasa aktif, dan alat pemeriksa kelengkapan.

Modul ini sengaja tidak mengimpor Streamlit di tingkat atas untuk fungsi
murninya: :func:`lookup`, :func:`missing_keys`, dan :func:`untranslated_report`
dapat dipakai dan diuji tanpa sesi Streamlit sama sekali.
"""
from __future__ import annotations

import logging

import streamlit as st

from ui.i18n.catalog import CATALOG

logger = logging.getLogger(__name__)

#: Kode bahasa → label singkat pada pengalih.
LANGUAGES: dict[str, str] = {"id": "ID", "en": "EN"}

#: Bahasa bawaan, dan sekaligus bahasa CADANGAN saat terjemahan belum ada.
DEFAULT_LANG = "id"

#: Kunci bahasa aktif di ``session_state``. Satu-satunya keadaan yang disentuh
#: saat berpindah bahasa — itulah sebabnya berpindah bahasa tidak dapat
#: mengganggu halaman aktif, pilihan pengguna, dialog, atau eksperimen.
LANG_KEY = "_lang"

#: Kunci yang sudah dilaporkan hilang, supaya log tidak membanjir: satu kunci
#: cukup dicatat sekali per proses.
_reported: set[tuple[str, str]] = set()


def current_lang() -> str:
    """Bahasa aktif. Indonesia bila belum dipilih atau nilainya tidak dikenal."""
    try:
        lang = st.session_state.get(LANG_KEY)
    except Exception:                       # pragma: no cover - di luar sesi
        return DEFAULT_LANG
    return lang if lang in LANGUAGES else DEFAULT_LANG


def set_lang(lang: str) -> None:
    """Pilih bahasa. HANYA menulis satu kunci — tidak menyentuh keadaan lain.

    Tidak memanggil ``st.rerun()``: pemanggilnya yang memutuskan, dan pengalih
    di sidebar memakai ``on_change`` sehingga Streamlit menjalankan ulang skrip
    sekali dengan sendirinya. Rerun tambahan di sini akan menjadi rerun kedua
    untuk satu aksi.
    """
    if lang in LANGUAGES:
        st.session_state[LANG_KEY] = lang


def humanise(key: str) -> str:
    """Teks darurat yang terbaca manusia dari sebuah kunci.

    Dipakai HANYA bila kunci sama sekali tidak terdaftar — keadaan yang berarti
    ada salah tulis di kode. Pengguna tidak boleh melihat ``nav.run_experiment``
    atau kotak kosong, jadi yang tampil adalah ruas terakhirnya sebagai kalimat
    biasa. Kejadiannya dicatat ke log supaya tetap ketahuan saat pengembangan.
    """
    tail = (key or "").rsplit(".", 1)[-1].replace("_", " ").strip()
    return tail[:1].upper() + tail[1:] if tail else "…"


def lookup(key: str, lang: str) -> str:
    """Teks mentah untuk ``key``, dengan CADANGAN Indonesia. Murni.

    Tiga tingkat, berurutan:

    1. teks pada bahasa yang diminta;
    2. teks bahasa Indonesia — dipakai selama Tahap 2 & 3 belum menerjemahkan
       kunci ini, sehingga antarmuka tetap terbaca alih-alih kosong;
    3. :func:`humanise` atas kuncinya, HANYA bila kunci itu memang tidak
       terdaftar sama sekali. Tidak pernah kunci mentah, tidak pernah kosong.
    """
    entry = CATALOG.get(key)
    if entry is None:
        if ("__missing__", key) not in _reported:
            _reported.add(("__missing__", key))
            logger.warning("i18n: kunci tidak terdaftar: %s", key)
        return humanise(key)

    text = entry.get(lang)
    if text:
        return text

    if (lang, key) not in _reported:
        _reported.add((lang, key))
        logger.info("i18n: '%s' belum diterjemahkan ke '%s' — memakai %s",
                    key, lang, DEFAULT_LANG)
    return entry.get(DEFAULT_LANG) or humanise(key)


def t(key: str, /, **values) -> str:
    """Teks pada bahasa aktif, dengan penyisipan BERNAMA.

    Penyisipannya bernama justru karena urutan kata berbeda antar bahasa::

        t("progress.of_total", done=3, total=48)
        id: "3 dari 48 eksperimen"
        en: "3 of 48 experiments"

    Dengan penyisipan berdasarkan posisi, kalimat yang menukar urutan angkanya
    akan tertukar tanpa ada yang error. Penyisipan bernama tidak bisa tertukar.

    Nilai yang kurang tidak menggagalkan render: kalimatnya dikembalikan apa
    adanya dan kejadiannya dicatat. Antarmuka yang tetap tampil lebih berguna
    daripada halaman yang gagal karena satu placeholder.
    """
    text = lookup(key, current_lang())
    if not values:
        return text
    try:
        return text.format(**values)
    except (KeyError, IndexError, ValueError) as e:   # pragma: no cover
        logger.warning("i18n: penyisipan gagal untuk '%s': %s", key, e)
        return text


# ── Alat pemeriksa kelengkapan ───────────────────────────────────────────

def missing_keys(lang: str, catalog: dict | None = None) -> list[str]:
    """Kunci yang BELUM punya teks pada ``lang``, urut. Murni.

    Inilah alat yang membuat Tahap 2 & 3 dapat diverifikasi: setelah sebuah
    halaman diterjemahkan, kunci-kunci halaman itu harus hilang dari daftar ini.
    """
    catalog = CATALOG if catalog is None else catalog
    return sorted(key for key, entry in catalog.items()
                  if not (entry.get(lang) or "").strip())


def untranslated_report(catalog: dict | None = None) -> dict:
    """Ringkasan kelengkapan per bahasa: jumlah, persentase, dan kunci.

    Dipakai dari terminal::

        python -c "from ui.i18n import untranslated_report as r; print(r()['en']['done'])"
    """
    catalog = CATALOG if catalog is None else catalog
    total = len(catalog)
    report: dict[str, dict] = {}
    for lang in LANGUAGES:
        missing = missing_keys(lang, catalog)
        done = total - len(missing)
        report[lang] = {
            "total": total,
            "done": done,
            "missing": missing,
            "percent": round(100 * done / total, 1) if total else 100.0,
        }
    return report

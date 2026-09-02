"""
Dua bahasa: Indonesia (bawaan) dan Inggris.

**Tanpa pustaka eksternal.** Kamusnya biasa saja — dua ``dict`` Python dengan
kunci bermakna — dan pengambilnya satu fungsi. Untuk dua bahasa dan teks yang
seluruhnya dikarang di dalam repo ini, mesin gettext beserta berkas `.po`/`.mo`
hanya menambah langkah kompilasi tanpa memberi apa pun yang belum ada di sini.

Empat hal yang menentukan bentuknya:

* **Kunci bermakna, bukan nomor.** ``nav.run_experiment``, bukan ``msg_042``.
  Kunci yang terbaca membuat teks yang belum diterjemahkan mudah dikenali, dan
  membuat kode tetap terbaca di tempat pemakaiannya.
* **Penyisipan BERNAMA, bukan posisi.** Urutan kata berbeda antar bahasa;
  ``{count} dari {total}`` boleh berpindah tempat di kalimat Inggrisnya tanpa
  merusak apa pun, sedangkan ``{}``/``%s`` akan tertukar diam-diam. Lihat
  :func:`t`.
* **Cadangan Indonesia, tidak pernah kunci mentah.** Terjemahan Inggris akan
  lama tidak lengkap (Tahap 2 & 3 menyusul). Selama itu antarmuka harus tetap
  terbaca, bukan menampilkan ``nav.run_experiment`` atau kotak kosong.
* **Yang TIDAK boleh diterjemahkan ditulis sebagai aturan**, bukan diingat-ingat
  — lihat :data:`NEVER_TRANSLATE` di ``ui.i18n.rules``.

Bahasa aktif hidup di ``st.session_state``; mengubahnya tidak menyentuh apa pun
selain kunci itu, sehingga berpindah bahasa tidak dapat mengganggu halaman,
pilihan, dialog, maupun eksperimen yang sedang berjalan.
"""
from __future__ import annotations

from ui.i18n.catalog import CATALOG
from ui.i18n.core import (
    DEFAULT_LANG, LANGUAGES, LANG_KEY, current_lang, missing_keys,
    set_lang, t, untranslated_report,
)
from ui.i18n.rules import NEVER_TRANSLATE, is_protected

__all__ = [
    "CATALOG", "DEFAULT_LANG", "LANGUAGES", "LANG_KEY", "NEVER_TRANSLATE",
    "current_lang", "is_protected", "missing_keys", "set_lang", "t",
    "untranslated_report",
]

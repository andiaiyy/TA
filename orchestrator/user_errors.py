"""
Penanda pesan pada pengecualian yang TAMPIL ke pengguna.

**Ini jalur galat**, jadi bentuknya sengaja sekecil mungkin: satu mixin yang
menambahkan dua atribut opsional dan tidak mengubah apa pun yang sudah ada.

Yang dijaga:

* ``str(exc)`` tetap **persis sama**. Itu penting karena pesan kegagalan
  eksperimen TERSIMPAN di basis data apa adanya — mengubahnya berarti mengubah
  catatan lama. Test lama juga membandingkan teks ini.
* Jenis pengecualian, kondisi pemicu, dan alur ``raise``/``except`` tidak
  tersentuh. Mixin ini tidak pernah menangkap, menelan, atau mengganti apa pun.
* ``key`` + ``values`` bersifat OPSIONAL. Pengecualian yang belum diberi kunci
  tetap bekerja seperti sebelumnya dan tetap tampil — kalimat Indonesianya yang
  dipakai. Tidak ada jalur yang menjadi diam.

Lapisan tampilan menyusun kalimatnya lewat
``ui.components.validator_messages.error_message``.
"""
from __future__ import annotations


class UserFacingMixin:
    """Dua atribut opsional untuk pengecualian yang dibaca pengguna.

    Dipasang pada kelas dasar pengecualian yang memang ditampilkan, sehingga
    seluruh turunannya ikut mendapatkannya tanpa satu pun pemanggil berubah.

    ``values`` membawa nilai SPESIFIK yang membuat pesan dapat ditelusuri —
    nama berkas, nama pipeline, nilai hash, batas ukuran. Nilai-nilai itu tidak
    pernah diterjemahkan; yang berbahasa hanya kalimat pembungkusnya.
    """

    def __init__(self, *args, key: str = "", values: dict | None = None):
        # `*args` diteruskan apa adanya supaya `str(exc)` tidak berubah sedikit
        # pun, termasuk untuk pemanggil lama yang hanya memberi satu pesan.
        super().__init__(*args)
        self.key = key
        self.values = dict(values or {})

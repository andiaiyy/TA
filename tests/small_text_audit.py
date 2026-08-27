"""Penghitung ELEMEN TEKS KECIL pada tampilan utama tiap halaman.

Permintaan "rapikan teks kecil" tiga kali gagal karena kriterianya subjektif.
Modul ini membuatnya TERUKUR: satu definisi, dipakai oleh laporan maupun test,
sehingga angkanya tidak mungkin berbeda antara yang dilaporkan dan yang diuji.

**Yang dihitung** (sesuai kesepakatan):

1. setiap pemanggilan ``st.caption(...)`` — termasuk lewat objek kolom
   (``cols[0].caption(...)``);
2. setiap teks di markdown kustom dengan ``font-size`` di bawah ukuran teks isi
   (:data:`FONT_BODY`);
3. setiap teks redup yang berdiri sebagai baris terpisah — di basis kode ini
   diwakili ``render_line(..., small=True)`` dan ``render_line(..., muted=True)``.

**Yang TIDAK dihitung**: isi ``with st.expander(...)`` dan isi badan modal.
Keduanya bukan "tampilan utama": pengguna membukanya sendiri.

**Cara menghitung.** Analisis statis atas AST, menelusuri graf panggilan mulai
dari ``render()`` tiap halaman dan menembus modul lain di dalam paket ``ui``.
Sebuah fungsi dihitung sebagai tampilan utama bila ada SATU jalur mencapainya
yang tidak melewati expander maupun badan modal — jadi helper bersama yang
dipakai di kedua tempat tetap terhitung sekali, di jalur utamanya.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
UI_ROOT = REPO_ROOT / "ui"

#: Kuota yang disepakati: tampilan utama sebuah halaman maksimal segini.
QUOTA = 3

#: Halaman -> (modul, fungsi masuk)
PAGES = {
    "Progress & Status": ("ui/views/view_results.py", "render"),
    "Run Experiment": ("ui/views/run_experiment.py", "render"),
    "Add Pipeline & Dataset": ("ui/views/contribute.py", "render"),
}

#: Ukuran teks isi. Apa pun di bawah ini dianggap "teks kecil".
FONT_BODY_REM = 0.95


# ── Pemuatan modul ────────────────────────────────────────────────────────

def _module_path(dotted: str) -> Path | None:
    """`ui.views.login` -> Path berkasnya, bila ada di dalam paket ui."""
    if not dotted.startswith("ui."):
        return None
    candidate = REPO_ROOT / (dotted.replace(".", "/") + ".py")
    return candidate if candidate.exists() else None


class _Module:
    """Satu modul UI: AST-nya, fungsinya, dan peta nama impornya."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.rel = path.relative_to(REPO_ROOT).as_posix()
        self.tree = ast.parse(path.read_text(encoding="utf-8"))
        self.functions: dict[str, ast.FunctionDef] = {}
        # nama lokal -> (modul dotted, nama asli)
        self.imported: dict[str, tuple[str, str]] = {}
        # alias modul (import ui.x as y) -> modul dotted
        self.module_alias: dict[str, str] = {}
        self._collect()

    def _collect(self) -> None:
        for node in self.tree.body:
            self._collect_node(node)
        # Impor di dalam fungsi juga nyata dipakai basis kode ini.
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self._collect_node(node)
            elif isinstance(node, ast.FunctionDef):
                self.functions.setdefault(node.name, node)

    def _collect_node(self, node: ast.AST) -> None:
        if isinstance(node, ast.FunctionDef):
            self.functions.setdefault(node.name, node)
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                self.imported.setdefault(alias.asname or alias.name,
                                         (node.module, alias.name))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    self.module_alias.setdefault(alias.asname, alias.name)


_CACHE: dict[str, _Module] = {}


def _load(rel_or_dotted: str) -> _Module | None:
    if rel_or_dotted in _CACHE:
        return _CACHE[rel_or_dotted]
    path = (REPO_ROOT / rel_or_dotted if rel_or_dotted.endswith(".py")
            else _module_path(rel_or_dotted))
    if path is None or not path.exists():
        return None
    module = _Module(path)
    _CACHE[rel_or_dotted] = module
    return module


# ── Pengenalan konteks: expander & badan modal ────────────────────────────

def _is_expander(node: ast.AST) -> bool:
    """`with st.expander(...)` — apa pun objek pemanggilnya."""
    if not isinstance(node, ast.With):
        return False
    for item in node.items:
        call = item.context_expr
        if isinstance(call, ast.Call) and getattr(call.func, "attr", "") == "expander":
            return True
    return False


def dialog_bodies(module: _Module) -> set[str]:
    """Nama fungsi yang dipakai sebagai BADAN MODAL di modul ini.

    Polanya seragam di basis kode ini::

        _x_dialog = dlg.dialog_decorator("Judul", KEY)(_x_body)

    jadi nama yang dioper ke hasil ``dialog_decorator(...)`` adalah badan modal.
    """
    found: set[str] = set()
    for node in ast.walk(module.tree):
        if not isinstance(node, ast.Call):
            continue
        inner = node.func
        if not (isinstance(inner, ast.Call)
                and getattr(inner.func, "attr", "") == "dialog_decorator"):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Name):
                found.add(arg.id)
    # Dekorator langsung @st.dialog(...) juga dihitung.
    for func in module.functions.values():
        for deco in func.decorator_list:
            target = deco.func if isinstance(deco, ast.Call) else deco
            if getattr(target, "attr", "") == "dialog":
                found.add(func.name)
    return found


# ── Pengenalan elemen teks kecil ──────────────────────────────────────────

def _small_font_texts(node: ast.Call) -> bool:
    """Markdown kustom dengan font-size di bawah teks isi."""
    for arg in list(node.args) + [k.value for k in node.keywords]:
        for text in _string_parts(arg):
            if "font-size:" not in text:
                continue
            # Regex, bukan pemenggalan tanda baca: nilai bisa diakhiri `;`,
            # `}`, kutip, atau langsung `>` pada atribut style inline. Versi
            # sebelumnya melewatkan bentuk terakhir itu — dan penghitung yang
            # buta membuat kuotanya tidak bermakna.
            for value in re.findall(r"font-size:\s*([0-9.]+)rem", text):
                try:
                    if float(value) < FONT_BODY_REM:
                        return True
                except ValueError:      # pragma: no cover - defensif
                    continue
    return False


def _string_parts(node: ast.AST) -> list[str]:
    out: list[str] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            out.append(sub.value)
    return out


def _classify(node: ast.Call) -> str | None:
    """Jenis elemen teks kecil, atau None bila bukan."""
    attr = getattr(node.func, "attr", None)
    name = getattr(node.func, "id", None)

    if attr == "caption":
        return "caption"
    if name == "render_line" or attr == "render_line":
        for keyword in node.keywords:
            if keyword.arg in ("small", "muted"):
                value = keyword.value
                if isinstance(value, ast.Constant) and value.value:
                    return "dim-line"
        return None
    if attr in ("markdown", "html") or name in ("markdown", "html"):
        if _small_font_texts(node):
            return "small-font-markdown"
    return None


# ── Penelusuran ───────────────────────────────────────────────────────────

def _resolve(module: _Module, node: ast.Call):
    """Fungsi yang dipanggil `node`, sebagai (modul, FunctionDef) atau None."""
    func = node.func
    if isinstance(func, ast.Name):
        if func.id in module.functions:
            return module, module.functions[func.id]
        target = module.imported.get(func.id)
        if target:
            other = _load(target[0])
            if other and target[1] in other.functions:
                return other, other.functions[target[1]]
        return None
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        dotted = module.module_alias.get(func.value.id)
        if dotted is None:
            target = module.imported.get(func.value.id)
            dotted = target[0] + "." + target[1] if target else None
        if dotted:
            other = _load(dotted)
            if other and func.attr in other.functions:
                return other, other.functions[func.attr]
    return None


def _scan(module: _Module, func: ast.FunctionDef, *, sheltered: bool,
          seen: set, found: list) -> None:
    """Telusuri satu fungsi.

    ``sheltered`` berarti jalur ini sudah berada di dalam expander/modal —
    isinya tidak dihitung, tetapi tetap ditelusuri supaya helper yang JUGA
    dipakai di jalur utama tidak ikut tertutup.
    """
    key = (module.rel, func.name, sheltered)
    if key in seen:
        return
    seen.add(key)
    bodies = dialog_bodies(module)

    # Peta anak -> induk, untuk mengetahui apakah sebuah panggilan berada di
    # dalam `with st.expander(...)`.
    parents: dict = {}
    for node in ast.walk(func):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def _in_expander(node: ast.AST) -> bool:
        current = node
        while current in parents:
            current = parents[current]
            if _is_expander(current):
                return True
        return False

    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        inside = sheltered or _in_expander(node)

        kind = _classify(node)
        if kind and not inside:
            found.append({
                "file": module.rel,
                "line": node.lineno,
                "func": func.name,
                "kind": kind,
                "text": _first_text(node),
            })

        resolved = _resolve(module, node)
        if resolved is None:
            continue
        other, target = resolved
        # Badan modal tidak pernah dihitung sebagai tampilan utama.
        child_sheltered = inside or (target.name in dialog_bodies(other))
        _scan(other, target, sheltered=child_sheltered, seen=seen, found=found)

    del bodies


def _first_text(node: ast.Call) -> str:
    parts = [t for a in node.args for t in _string_parts(a)]
    text = " ".join(parts).strip()
    return (text[:70] + "…") if len(text) > 70 else text


def audit(page: str) -> list[dict]:
    """Daftar elemen teks kecil pada TAMPILAN UTAMA sebuah halaman."""
    rel, entry = PAGES[page]
    module = _load(rel)
    assert module is not None, rel
    assert entry in module.functions, (rel, entry)

    found: list[dict] = []
    _scan(module, module.functions[entry], sheltered=False, seen=set(),
          found=found)
    # Satu baris kode = satu elemen, walau tercapai lewat beberapa jalur.
    unique = {(f["file"], f["line"]): f for f in found}
    return sorted(unique.values(), key=lambda f: (f["file"], f["line"]))


def counts() -> dict[str, int]:
    return {page: len(audit(page)) for page in PAGES}


if __name__ == "__main__":                  # pragma: no cover - alat laporan
    import io
    import sys

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    total = 0
    for page in PAGES:
        items = audit(page)
        total += len(items)
        flag = "OK " if len(items) <= QUOTA else "LEBIH"
        print(f"\n=== {page}: {len(items)} elemen  [{flag}] (kuota {QUOTA})")
        for item in items:
            print(f"  {item['file']}:{item['line']:<5} {item['kind']:<20} "
                  f"{item['func']:<32} {item['text']}")
    print(f"\nTOTAL: {total}")

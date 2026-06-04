"""Extract code cells from .ipynb files to plain .py for audit. Diagnostic helper, read-only."""
import json
import sys
from pathlib import Path

def extract(nb_path: Path, out_dir: Path) -> Path:
    nb = json.loads(nb_path.read_text(encoding="utf-8"))
    chunks = []
    for i, cell in enumerate(nb.get("cells", [])):
        if cell.get("cell_type") != "code":
            continue
        src = "".join(cell.get("source", []))
        if not src.strip():
            continue
        chunks.append(f"# --- CELL {i} ---\n{src}\n")
    out = out_dir / (nb_path.stem + ".cells.py")
    out.write_text("\n".join(chunks), encoding="utf-8")
    return out

if __name__ == "__main__":
    nbs = list(Path("reference_scripts").glob("*.ipynb"))
    out_dir = Path("experiments/_nb_cells")
    out_dir.mkdir(parents=True, exist_ok=True)
    for nb in nbs:
        out = extract(nb, out_dir)
        print(f"{nb.name:40s} -> {out.name} ({out.stat().st_size//1024} KB)")

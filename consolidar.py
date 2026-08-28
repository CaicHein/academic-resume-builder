#!/usr/bin/env python3
"""
consolidar.py — Junta as saídas dos coletores (ementa do Jupiter + notas do
Moodle) num único JSON por disciplina, em vez de arquivos separados que o
próximo passo (o gerador de competências) precisaria cruzar na mão.

Cada coletor continua desacoplado e gerando seu próprio arquivo — fiel ao
princípio do projeto de fontes independentes, testáveis isoladamente (ver
CLAUDE.md). Este script é só a etapa de junção, rodada por último, depois de
`jupiter_disciplinas.py` e `moodle_notas.py`.

--- USO ---
    python3 consolidar.py

Entrada: materiais_moodle/jupiter_disciplinas.json (base — cada entrada já é
         uma disciplina com moodle_id/moodle_nome/ementa) e
         materiais_moodle/notas.json (itens de nota, casados pelo moodle_id).
Saída:   materiais_moodle/disciplinas_consolidado.json — cada disciplina com
         sua ementa (Jupiter) e a lista de itens de nota (Moodle) aninhada.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BASE = "https://edisciplinas.usp.br"


def main():
    base_dir = Path("materiais_moodle")
    jupiter_path = base_dir / "jupiter_disciplinas.json"
    notas_path = base_dir / "notas.json"
    out_path = base_dir / "disciplinas_consolidado.json"

    if not jupiter_path.exists():
        print(f"Não achei {jupiter_path}. Rode antes: python3 jupiter_disciplinas.py", file=sys.stderr)
        sys.exit(1)
    if not notas_path.exists():
        print(f"Não achei {notas_path}. Rode antes: python3 moodle_notas.py", file=sys.stderr)
        sys.exit(1)

    disciplinas = json.loads(jupiter_path.read_text(encoding="utf-8"))
    notas = json.loads(notas_path.read_text(encoding="utf-8"))

    notas_por_disciplina = defaultdict(list)
    for item in notas:
        cid = item.get("moodle_id")
        # moodle_id/moodle_nome já ficam no nível da disciplina — não repete por item.
        item_limpo = {k: v for k, v in item.items() if k not in ("moodle_id", "moodle_nome")}
        notas_por_disciplina[cid].append(item_limpo)

    for d in disciplinas:
        cid = d.get("moodle_id")
        d["notas_url"] = f"{BASE}/grade/report/user/index.php?id={cid}"
        d["notas"] = notas_por_disciplina.get(cid, [])

    out_path.write_text(json.dumps(disciplinas, ensure_ascii=False, indent=2), encoding="utf-8")

    com_notas = sum(1 for d in disciplinas if d["notas"])
    total_itens = sum(len(d["notas"]) for d in disciplinas)
    print(f"{len(disciplinas)} disciplina(s), {com_notas} com item(ns) de nota, "
          f"{total_itens} item(ns) de nota no total")
    print(f"Salvo em {out_path}")


if __name__ == "__main__":
    main()

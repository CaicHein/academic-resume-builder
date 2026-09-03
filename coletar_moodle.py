#!/usr/bin/env python3
"""
coletar_moodle.py — Orquestra tudo que é Moodle num passo só: lista as
disciplinas e extrai as notas/entregas. Não reimplementa nada — só chama, em
sequência, os scripts que já existem (mesmo princípio de app.py), cada um
como subprocesso, deixando a saída de cada um passar direto pro log de quem
chamou este script.

Não inclui download de materiais/arquivos (harvester_moodle.py sem
--list-only) — esse passo já está validado (ver CLAUDE.md), mas baixa muito
arquivo (1.237 nas 40 disciplinas reais) e demora bastante; não é sempre
necessário, então fica de fora do "coletar tudo" por padrão. Rode
`harvester_moodle.py` direto (sem `--list-only`) quando quiser os materiais
de fato — é pré-requisito de `extrair_texto_materiais.py`/
`indexar_materiais.py` (currículo interativo).

--- USO ---
    python3 coletar_moodle.py
"""

import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ETAPAS = [
    ("Moodle — listar disciplinas", [sys.executable, "harvester_moodle.py", "--list-only"]),
    ("Moodle — notas/entregas", [sys.executable, "moodle_notas.py"]),
]


def main():
    for nome, comando in ETAPAS:
        print(f"\n=== {nome} ===")
        resultado = subprocess.run(comando)
        if resultado.returncode != 0:
            print(f"\n! Falhou em '{nome}' (código {resultado.returncode}). "
                  f"Interrompendo — as próximas etapas não rodaram.", file=sys.stderr)
            sys.exit(resultado.returncode)

    print("\n=== Pronto ===")
    print("Moodle coletado: disciplinas.json + notas.json em materiais_moodle/.")


if __name__ == "__main__":
    main()

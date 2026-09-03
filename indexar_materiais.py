#!/usr/bin/env python3
"""
indexar_materiais.py — Orquestra o "currículo interativo" (RAG) num passo
só: extrai texto dos materiais e gera os embeddings. Não reimplementa nada —
só chama, em sequência, extrair_texto_materiais.py e gerar_embeddings.py.

Precisa de materiais_moodle/manifesto.json (rode harvester_moodle.py sem
--list-only primeiro) e do Ollama rodando com `nomic-embed-text` baixado
(`ollama pull nomic-embed-text`).

--- USO ---
    python3 indexar_materiais.py
"""

import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ETAPAS = [
    ("Currículo interativo — extrair texto dos materiais", [sys.executable, "extrair_texto_materiais.py"]),
    ("Currículo interativo — gerar embeddings (Ollama)", [sys.executable, "gerar_embeddings.py"]),
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
    print("Índice semântico salvo em indice_semantico/ — pronto pra usar em /api/perguntar.")


if __name__ == "__main__":
    main()

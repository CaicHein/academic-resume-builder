#!/usr/bin/env python3
"""
gerar_curriculo_completo.py — Orquestra a geração do currículo num passo só:
sintetiza as competências via LLM e já renderiza o .tex. Não reimplementa
nada — só chama, em sequência, gerar_competencias.py e renderizar_curriculo.py.

Precisa de ANTHROPIC_API_KEY no .env (configurável pela interface do painel)
e de pelo menos uma fonte de dado coletada (trajetória acadêmica e/ou
GitHub e/ou informações adicionais).

--- USO ---
    python3 gerar_curriculo_completo.py
"""

import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ETAPAS = [
    ("Currículo — gerar competências (LLM)", [sys.executable, "gerar_competencias.py"]),
    ("Currículo — gerar .tex", [sys.executable, "renderizar_curriculo.py"]),
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
    print("Currículo em LaTeX salvo em dados_extra/curriculo.tex.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
gerar_curriculo_completo.py — Orquestra a geração do currículo num passo só:
sintetiza as competências via LLM e já renderiza o .tex. Não reimplementa
nada — só chama, em sequência, gerar_competencias.py e renderizar_curriculo.py.

Precisa de ANTHROPIC_API_KEY no .env (configurável pela interface do painel)
e de pelo menos uma fonte de dado coletada (trajetória acadêmica e/ou
GitHub e/ou informações adicionais). Ou, sem chave nenhuma, `--provider
ollama` pra testar com um LLM aberto local (ver gerar_competencias.py).

--- USO ---
    python3 gerar_curriculo_completo.py
    python3 gerar_curriculo_completo.py --provider ollama --model qwen2.5:14b
"""

import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def main():
    # argumentos da linha de comando (ex.: --provider/--model) valem só pro
    # passo de geração de competências — renderizar_curriculo.py não lê a
    # rede, não tem opções, e quebraria com um argv que não espera.
    extra_args = sys.argv[1:]
    etapas = [
        ("Currículo — gerar competências (LLM)", [sys.executable, "gerar_competencias.py", *extra_args]),
        ("Currículo — gerar .tex", [sys.executable, "renderizar_curriculo.py"]),
    ]
    for nome, comando in etapas:
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

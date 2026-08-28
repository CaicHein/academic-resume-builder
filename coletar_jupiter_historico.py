#!/usr/bin/env python3
"""
coletar_jupiter_historico.py — Orquestra tudo que é Jupiter/histórico escolar
num passo só: ementas, consolidação com as notas do Moodle, download do PDF
do histórico e extração final. Não reimplementa nada — só chama, em
sequência, os scripts que já existem, cada um como subprocesso.

Precisa de materiais_moodle/disciplinas.json e materiais_moodle/notas.json já
coletados (rode coletar_moodle.py antes) — cada etapa avisa sozinha se faltar
pré-requisito, este script só para na primeira que falhar.

A etapa "baixar histórico" abre uma janela pra login manual no Jupiter (login
PRÓPRIO, diferente do Moodle — ver CLAUDE.md); o script espera até você
logar, igual as outras etapas que abrem navegador.

--- USO ---
    python3 coletar_jupiter_historico.py
"""

import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ETAPAS = [
    ("Jupiter — ementas", [sys.executable, "jupiter_disciplinas.py"]),
    ("Consolidar (ementas + notas)", [sys.executable, "consolidar.py"]),
    ("Jupiter — baixar histórico (PDF)", [sys.executable, "baixar_historico.py"]),
    ("Histórico — processar PDF (arquivo final)", [sys.executable, "parse_historico.py"]),
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
    print("Trajetória acadêmica completa em materiais_moodle/trajetoria_academica.json.")


if __name__ == "__main__":
    main()

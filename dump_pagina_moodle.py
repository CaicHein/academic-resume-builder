#!/usr/bin/env python3
"""
dump_pagina_moodle.py — Utilitário de calibração: abre uma página do Moodle
(reaproveitando a sessão salva em .perfil_navegador/) e salva o HTML
renderizado num arquivo, pra inspecionar contra o DOM real em vez de
adivinhar seletores (mesma lógica de sempre no projeto: calibrar contra o
HTML verdadeiro).

IMPORTANTE: precisa rodar com janela visível (headless=False, o padrão
daqui) — o WAF da USP bloqueia Chromium headless (a página volta com "The
URL you requested has been blocked"). A sessão salva em .perfil_navegador/
expira; quando expirar, este script espera você logar de novo (reusa a
mesma lógica de `harvester_moodle.esperar_login`, com detecção multi-aba).

--- USO ---
    python3 dump_pagina_moodle.py "https://edisciplinas.usp.br/grade/report/user/index.php?id=144360"
    python3 dump_pagina_moodle.py "https://edisciplinas.usp.br/course/view.php?id=144360" --out saida.html
"""

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Playwright não instalado. Rode:\n"
          "    pip install playwright\n"
          "    playwright install chromium", file=sys.stderr)
    sys.exit(1)

import harvester_moodle as hm  # reusa esperar_login/goto_seguro já testados


def main():
    ap = argparse.ArgumentParser(
        description="Dump do HTML renderizado de uma página do Moodle, pra calibração de seletores."
    )
    ap.add_argument("url")
    ap.add_argument("--out", default="_dump.html")
    ap.add_argument("--espera", type=int, default=2000, help="Espera extra (ms) após o load, pra JS renderizar.")
    args = ap.parse_args()

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(user_data_dir=hm.PERFIL, headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        page = hm.esperar_login(context, page)

        hm.goto_seguro(page, args.url)
        page.wait_for_timeout(args.espera)
        html = page.content()
        Path(args.out).write_text(html, encoding="utf-8")
        print(f"URL final: {page.url}")
        print(f"Salvo em {args.out} ({len(html)} chars)")
        context.close()


if __name__ == "__main__":
    main()

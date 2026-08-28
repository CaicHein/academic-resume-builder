#!/usr/bin/env python3
"""
dump_pagina_jupiter.py — Utilitário de calibração: loga no Jupiter Web
autenticado (via jupiter_auth) e salva o HTML renderizado de uma URL, pra
inspecionar contra o DOM real em vez de adivinhar (mesmo padrão de
dump_pagina_moodle.py, mas para o login nativo do Jupiter).

--- USO ---
    python3 dump_pagina_jupiter.py                          # dump da home pós-login
    python3 dump_pagina_jupiter.py "https://uspdigital.usp.br/jupiterweb/..."
"""

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Playwright não instalado. Rode:\n"
          "    pip install playwright\n"
          "    playwright install chromium", file=sys.stderr)
    sys.exit(1)

import harvester_moodle as hm
import jupiter_auth as ja


def main():
    ap = argparse.ArgumentParser(description="Dump do HTML renderizado de uma página autenticada do Jupiter.")
    ap.add_argument("url", nargs="?", default=None, help="Se omitido, usa a home pós-login.")
    ap.add_argument("--out", default="_dump_jupiter.html")
    ap.add_argument("--espera", type=int, default=2000)
    args = ap.parse_args()

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(user_data_dir=ja.PERFIL, headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        page = ja.esperar_login(context, page)

        if args.url:
            hm.goto_seguro(page, args.url)
            page.wait_for_timeout(args.espera)

        html = page.content()
        Path(args.out).write_text(html, encoding="utf-8")
        print(f"URL final: {page.url}")
        print(f"Salvo em {args.out} ({len(html)} chars)")
        context.close()


if __name__ == "__main__":
    main()

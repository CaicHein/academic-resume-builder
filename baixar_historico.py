#!/usr/bin/env python3
"""
baixar_historico.py — Gera e baixa o PDF do histórico escolar (Jupiter Web).

A página "Histórico escolar" não expõe os dados em HTML: é um formulário que,
ao clicar "Gerar", seta o `src` de um <iframe> pra
`historicoescolarListar?cmd=cmd&<form serializado>` — essa URL devolve o PDF
direto (confirmado lendo `emissaoHistoricoEscolarGrupo.js`). Em vez de montar
essa URL/query string na mão (arrisca esquecer um campo obrigatório que o
jQuery preencheria sozinho), este script deixa o próprio JS da página
construir o `src` — clica no botão de verdade, lê o `src` resultante, e busca
essa URL autenticado (via context.request, reaproveitando os cookies da
sessão) pra pegar os bytes do PDF.

--- USO ---
    python3 baixar_historico.py

Saída: materiais_moodle/historico_escolar.pdf
"""

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

import jupiter_auth as ja

BASE = ja.BASE


def main():
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(user_data_dir=ja.PERFIL, headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        page = ja.esperar_login(context, page)

        page.goto(f"{BASE}/historicoEscolar?codmnu=4538", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)

        # curso é obrigatório (select) — escolhe a primeira opção real (não a vazia).
        curso_select = page.locator("#codcur")
        opcoes = curso_select.locator("option").all()
        valores = [o.get_attribute("value") for o in opcoes if o.get_attribute("value")]
        print(f"Opções de curso encontradas: {valores}")
        if valores:
            curso_select.select_option(valores[0])
            print(f"Selecionado: {valores[0]}")

        page.locator("#enviar").click()
        page.wait_for_timeout(3000)

        src = page.locator("#documento").get_attribute("src")
        print(f"src do iframe após 'Gerar': {src}")
        if not src:
            print("Não apareceu um src no iframe — o clique pode ter falhado "
                  "(campo obrigatório vazio?). Confira _debug_historico.png.", file=sys.stderr)
            page.screenshot(path="_debug_historico.png")
            context.close()
            sys.exit(1)

        pdf_url = src if src.startswith("http") else f"{BASE}/{src}"
        resp = context.request.get(pdf_url)
        print(f"status={resp.status} content-type={resp.headers.get('content-type')}")

        out_dir = Path("materiais_moodle")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "historico_escolar.pdf"
        out_path.write_bytes(resp.body())
        print(f"Salvo em {out_path} ({len(resp.body())} bytes)")

        context.close()


if __name__ == "__main__":
    main()

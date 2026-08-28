#!/usr/bin/env python3
"""
moodle_notas.py — Extrai o "livro de notas" (grade report) de cada disciplina
no Moodle: todo item avaliado (tarefa, questionário, fórum, prova manual...),
com categoria, peso, nota, porcentagem e feedback do professor.

Por quê: se o objetivo fosse só saber QUAIS disciplinas foram cursadas, o
Jupiter Web já dá isso de graça (`jupiter_disciplinas.py`), sem precisar do
Moodle. O valor de raspar o Moodle está em pegar o que o aluno EFETIVAMENTE
fez e como foi avaliado em cada entrega — a peça que faltava pra entender
desempenho real, não só presença/matrícula.

Usa a mesma sessão SSO autenticada por humano do harvester_moodle.py (importa
de lá esperar_login/goto_seguro/BASE/PERFIL — não duplica login).

Página usada: .../grade/report/user/index.php?id=<course_id> — o "relatório
do usuário" do livro de notas do Moodle: uma única página por disciplina com
TODOS os itens avaliados (calibrado contra HTML real de disciplinas do tema
da USP, via dump_pagina_moodle.py).

--- USO ---
    python3 moodle_notas.py                      # todas as disciplinas de materiais_moodle/disciplinas.json
    python3 moodle_notas.py --course-id 144360    # testa 1 disciplina só
    python3 moodle_notas.py --headless            # cuidado: o WAF da USP costuma bloquear headless

Saída: materiais_moodle/notas.json
"""

import argparse
import html
import json
import re
import sys
import time
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

import harvester_moodle as hm  # reusa esperar_login/goto_seguro/BASE/PERFIL já testados

TR_RE = re.compile(r"<tr\b.*?</tr>", re.S)
CATEGORIA_RE = re.compile(
    r'class="[^"]*\bcategory\b[^"]*column-itemname[^"]*"[^>]*>.*?<span>([^<]*)</span>', re.S
)
ITEM_ID_RE = re.compile(r'id="row_(\d+)_\d+"')
TIPO_RE = re.compile(r'<span class="d-block text-uppercase small[^"]*"[^>]*title="([^"]*)"')
LINK_RE = re.compile(r'<a[^>]*class="gradeitemheader[^"]*"[^>]*href="([^"]*)"[^>]*>([^<]*)</a>')
SPAN_RE = re.compile(r'<span[^>]*class="gradeitemheader[^"]*"[^>]*title="([^"]*)"[^>]*>([^<]*)</span>')
TD_RE = re.compile(r"<td\b[^>]*>(.*?)</td>", re.S)


def _texto(fragmento):
    t = re.sub(r"<[^>]+>", " ", fragmento)
    t = html.unescape(t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _valor_celula(fragmento):
    """Como _texto(), mas pra colunas de valor (peso/nota/porcentagem): quando
    a nota tem 'Análise de nota' disponível, o Moodle injeta um menu 'Ações'
    dropdown DENTRO da mesma célula, colado no valor (ex.: "10,00 Ações
    Análise de nota"). Corta tudo a partir de 'Ações' pra sobrar só o valor.
    """
    t = _texto(fragmento)
    t = re.split(r"\bAções\b", t)[0].strip()
    return t


def parse_linha(row_html):
    """Devolve ("categoria", nome) | ("item", dict) | None (linha espaçadora)."""
    m_cat = CATEGORIA_RE.search(row_html)
    if m_cat:
        return "categoria", html.unescape(m_cat.group(1)).strip()

    m_id = ITEM_ID_RE.search(row_html)
    if not m_id:
        return None  # linha espaçadora/vazia, sem item de nota

    m_tipo = TIPO_RE.search(row_html)
    tipo = html.unescape(m_tipo.group(1)).strip() if m_tipo else None

    m_link = LINK_RE.search(row_html)
    if m_link:
        url, nome = m_link.group(1), _texto(m_link.group(2))
    else:
        m_span = SPAN_RE.search(row_html)
        url = None
        nome = _texto(m_span.group(2)) if m_span else None

    tds = TD_RE.findall(row_html)
    peso = _valor_celula(tds[0]) if len(tds) > 0 else None
    nota = _valor_celula(tds[1]) if len(tds) > 1 else None
    porcentagem = _valor_celula(tds[2]) if len(tds) > 2 else None
    feedback = _texto(tds[3]) if len(tds) > 3 else None

    item = {
        "tipo": tipo,
        "nome": nome,
        "url": url,
        "peso": peso if peso and peso != "-" else None,
        "nota": nota if nota and nota != "-" else None,
        "porcentagem": porcentagem if porcentagem and porcentagem != "-" else None,
        "feedback": feedback if feedback else None,
        # linha de agregação (ex.: "Total do curso"), não um item avaliado de verdade
        "total": ("courseitem" in row_html) or ("baggt" in row_html),
    }
    return "item", item


def parse_relatorio(raw_html):
    itens = []
    categoria_atual = None
    for row_html in TR_RE.findall(raw_html):
        resultado = parse_linha(row_html)
        if resultado is None:
            continue
        kind, valor = resultado
        if kind == "categoria":
            categoria_atual = valor
        else:
            valor["categoria"] = categoria_atual
            itens.append(valor)
    return itens


def coletar_notas(page, disc, notas):
    course_id = disc["id"]
    url = f"{hm.BASE}/grade/report/user/index.php?id={course_id}"
    print(f"\n[notas] {disc.get('nome') or course_id}")
    hm.goto_seguro(page, url)
    time.sleep(0.8)
    raw = page.content()
    itens = parse_relatorio(raw)
    if not itens:
        print("      (nenhum item de nota encontrado — pode ser disciplina sem livro "
              "de notas configurado, ou a página não é a esperada; conferir manualmente)")
    for it in itens:
        it["moodle_id"] = course_id
        it["moodle_nome"] = disc.get("nome")
        it["origem_url"] = url
        notas.append(it)
        marca = "Σ" if it["total"] else "•"
        print(f"      {marca} [{it['tipo']}] {it['nome']} — nota: {it['nota']}")
    time.sleep(hm.PAUSA)


def main():
    ap = argparse.ArgumentParser(
        description="Extrai o livro de notas (todos os itens avaliados) de cada disciplina do Moodle."
    )
    ap.add_argument("--in", dest="entrada", default="materiais_moodle/disciplinas.json")
    ap.add_argument("--out", default="materiais_moodle/notas.json")
    ap.add_argument("--course-id", help="Testa 1 disciplina só, pelo id do Moodle.")
    ap.add_argument("--headless", action="store_true",
                     help="Cuidado: o WAF da USP costuma bloquear Chromium headless.")
    args = ap.parse_args()

    if args.course_id:
        discs = [{"id": args.course_id, "nome": ""}]
    else:
        entrada_path = Path(args.entrada)
        if not entrada_path.exists():
            print(f"Não achei {entrada_path}. Rode antes: "
                  f"python3 harvester_moodle.py --list-only", file=sys.stderr)
            sys.exit(1)
        discs = json.loads(entrada_path.read_text(encoding="utf-8"))

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(user_data_dir=hm.PERFIL, headless=args.headless)
        page = context.pages[0] if context.pages else context.new_page()
        page = hm.esperar_login(context, page)

        notas = []
        for d in discs:
            try:
                coletar_notas(page, d, notas)
            except Exception as e:
                print(f"   ! erro na disciplina {d.get('id')}: {e}")

        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(notas, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"\n=== Pronto ===")
        print(f"{len(notas)} item(ns) de nota em {len(discs)} disciplina(s)")
        print(f"Salvo em {out_path}")
        context.close()


if __name__ == "__main__":
    main()

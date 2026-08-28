#!/usr/bin/env python3
"""
harvester_moodle.py — Coleta automatizada da sua trajetória no Moodle (via SSO).

A ideia (que você mesmo apontou): o valor NÃO está em mandar texto pra uma LLM
— isso você faz copiando e colando. O valor está em VARRER sozinho dezenas de
disciplinas espalhadas por vários semestres e baixar tudo, organizado, com
registro de ONDE veio cada arquivo. É isso que um "joga no chat" não faz.

Como ele contorna o SSO (Senha Única USP): ele NÃO tenta autenticar por conta
própria. Ele abre um navegador real, VOCÊ loga na mão pela Senha USP (o SSO
acontece normal), e o script pega carona na sessão já autenticada. Zero senha
no código.

Saída:
  materiais_moodle/
    <nome da disciplina>/
      <arquivos baixados>
  materiais_moodle/manifesto.json   <- o "recibo": cada arquivo + de onde veio

--- SETUP (uma vez) ---
    pip install playwright
    playwright install chromium

--- USO ---
    python3 harvester_moodle.py                 # varre tudo
    python3 harvester_moodle.py --list-only      # só lista disciplinas, não baixa
    python3 harvester_moodle.py --course-id 12345  # testa numa disciplina só

Na primeira vez, a janela abre em /my/. Faça login pela Senha USP e, quando
suas disciplinas aparecerem, volte ao terminal e tecle Enter. A sessão fica
guardada na pasta .perfil_navegador, então nas próximas vezes já entra logado.

AVISO: automatizar acesso, mesmo à sua própria conta, pode esbarrar nos termos
de uso da instituição. É seu dado e uso pessoal, mas seja gentil com o servidor
(o script já espera um pouco entre downloads) e não abuse.
"""

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    # line_buffering=True: sem isso, o print() fica bufferizado quando a saída
    # não é um terminal (ex.: redirecionada pra arquivo por um processo em
    # background) — nada aparece até acumular ~8KB ou o processo terminar,
    # o que inviabiliza acompanhar o progresso de um login em andamento.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Playwright não instalado. Rode:\n"
          "    pip install playwright\n"
          "    playwright install chromium", file=sys.stderr)
    sys.exit(1)

BASE = "https://edisciplinas.usp.br"
PERFIL = ".perfil_navegador"   # sessão persistente: loga uma vez, reusa depois
PAUSA = 0.7                    # segundos entre requisições (educação com o servidor)

PLUGINFILE_RE = re.compile(r"""https?://[^\s"']*pluginfile\.php/[^\s"']*""")
COURSE_RE = re.compile(r"/course/view\.php\?id=(\d+)")


def sanitize(name, fallback="arquivo"):
    name = html.unescape(name or "").strip()
    name = re.sub(r'[<>:"/\\|?*\n\r\t]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(". ")
    return name[:120] or fallback


def is_logged_in(page):
    """Detecta login com várias heurísticas, pois o tema da USP customiza o
    Moodle e o link de logout pode não bater com o seletor padrão do Boost.

    Ordem: (1) link de logout clássico; (2) elementos do menu de usuário
    (avatar/dropdown), presentes no DOM mesmo com o menu fechado; (3) fallback
    por URL — de volta em edisciplinas, fora de /login/, e sem formulário/botão
    de login visível na página.
    """
    try:
        if page.locator("a[href*='logout']").count() > 0:
            return True
        if page.locator(
            ".usermenu, .userpicture, [data-region='drawer-toggle'], "
            "#action-menu-toggle-0, .initialswrap"
        ).count() > 0:
            return True
        url = page.url
        if "edisciplinas.usp.br" in url and "/login/" not in url:
            sem_login = page.locator(
                "form#login, a:has-text('Senha USP'), a:has-text('Acessar')"
            ).count() == 0
            if sem_login:
                return True
        return False
    except Exception:
        return False


def goto_seguro(page, url, wait_until="domcontentloaded"):
    """goto tolerante a redirects do SSO.

    Quando não se está logado, /my/ dispara uma cadeia de redirecionamentos
    (Moodle -> idpcafe -> volta). O Playwright levanta 'interrupted by another
    navigation' nesses casos. Isso NÃO é falha real: engolimos e seguimos, que
    o polling depois confirma o estado final.
    """
    try:
        page.goto(url, wait_until=wait_until, timeout=60000)
    except Exception as e:
        msg = str(e).lower()
        if "interrupt" in msg or "navigation" in msg or "timeout" in msg:
            return  # redirect em andamento — normal, segue o baile
        raise


def pagina_logada(context):
    """Varre TODAS as abas abertas no contexto e devolve a primeira que estiver
    logada no e-Disciplinas, ou None. Precisa checar todas porque o clique em
    'Senha USP' pode abrir o fluxo SSO numa aba nova — nesse caso a `page`
    original nunca sai do idpcafe, mesmo com o login concluído numa outra aba."""
    for candidata in context.pages:
        try:
            url = candidata.url
            if ("edisciplinas.usp.br" in url and "/login/" not in url
                    and is_logged_in(candidata)):
                return candidata
        except Exception:
            pass  # aba pode estar em trânsito (navegando) nesse instante
    return None


def esperar_login(context, page, timeout=300):
    """Dispara o fluxo indo em /my/ e ESPERA (polling) você concluir o SSO.

    Não navega de novo no meio do caminho: o SSO da USP (SAML via idpcafe) é
    iniciado pelo Moodle, então a gente só deixa o fluxo rolar e observa até
    você voltar logado ao e-Disciplinas — em QUALQUER aba do contexto, não só
    na que foi aberta primeiro.

    Retorna a Page logada, que deve ser usada pelo resto do script (pode ser
    uma aba diferente da `page` recebida).
    """
    goto_seguro(page, f"{BASE}/my/")
    if is_logged_in(page):
        print("Já estava logado (sessão reaproveitada).")
        return page

    print("\n>>> Na JANELA do navegador, conclua o login:")
    print(">>>   1. clique no botão 'Senha USP' (ou 'Acessar') na tela do e-Disciplinas")
    print(">>>   2. no idpcafe.usp.br, entre com seu número USP + Senha Única")
    print(">>>   3. aguarde ser redirecionado de volta ao e-Disciplinas")
    print(">>> (Se o login abrir numa aba nova, pode deixar — o script cobre "
          "todas as abas abertas.)")
    print(">>> O script está esperando você terminar (não precisa teclar nada)...\n")

    inicio = time.time()
    ultimo_status = 0
    while time.time() - inicio < timeout:
        logada = pagina_logada(context)
        if logada is not None:
            print(f"Login detectado! (aba: {logada.url}) Seguindo...\n")
            return logada
        # status a cada ~10s, pra não ficarmos às cegas se a detecção falhar de novo
        if time.time() - ultimo_status > 10:
            urls = [p.url for p in context.pages]
            print(f"    [ainda esperando] abas abertas: {urls}")
            # screenshot da(s) aba(s) que o script REALMENTE está vendo — prova
            # visual em caso de dúvida se é a mesma janela que você está olhando.
            for i, p_ in enumerate(context.pages):
                try:
                    p_.screenshot(path=f"_debug_estado_{i}.png")
                except Exception:
                    pass
            ultimo_status = time.time()
        time.sleep(2)

    if sys.stdin.isatty():
        print("Passaram-se 5 min sem detectar login. Se você já logou, tecle Enter "
              "pra tentar seguir mesmo assim (ou Ctrl+C pra abortar).")
        input()
    else:
        # stdin não interativo (ex.: rodando em background) — input() aqui
        # travaria pra sempre. Só segue com o que tiver.
        print("Passaram-se 5 min sem detectar login (stdin não interativo, "
              "seguindo sem esperar Enter).")
    return pagina_logada(context) or page


def listar_disciplinas(page):
    """Coleta links /course/view.php?id=NNN do dashboard, deduplicando por id."""
    goto_seguro(page, f"{BASE}/my/")
    time.sleep(2)  # deixa os cards de curso renderizarem
    anchors = page.eval_on_selector_all(
        "a[href*='/course/view.php?id=']",
        "els => els.map(e => ({href: e.href, text: e.textContent.trim()}))",
    )
    vistos = {}
    for a in anchors:
        m = COURSE_RE.search(a["href"])
        if not m:
            continue
        cid = m.group(1)
        nome = a["text"]
        # o texto do link às vezes vem vazio; guarda o melhor nome que aparecer
        if cid not in vistos or (nome and not vistos[cid]["nome"]):
            vistos[cid] = {"id": cid, "nome": nome, "url": f"{BASE}/course/view.php?id={cid}"}
    return list(vistos.values())


def extrair_pluginfiles(conteudo_html):
    urls = set()
    for u in PLUGINFILE_RE.findall(conteudo_html):
        urls.add(html.unescape(u))
    return urls


def nome_de_url(file_url, resp_headers=None):
    # tenta Content-Disposition primeiro
    if resp_headers:
        cd = resp_headers.get("content-disposition", "")
        m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^"\r\n;]+)"?', cd)
        if m:
            return sanitize(urllib.parse.unquote(m.group(1)))
    # senão, último segmento do path da URL
    path = urllib.parse.urlparse(file_url).path
    seg = urllib.parse.unquote(path.rstrip("/").split("/")[-1])
    return sanitize(seg)


def baixar(context, file_url, destino_dir, manifesto, disciplina, origem):
    try:
        resp = context.request.get(file_url)
    except Exception as e:
        print(f"      ! falha ao buscar {file_url[:70]}... ({e})")
        return
    if resp.status >= 400:
        print(f"      ! status {resp.status} em {file_url[:70]}...")
        return

    ctype = resp.headers.get("content-type", "")
    # Se veio HTML, provavelmente é uma página intermediária: procura o arquivo real.
    if "text/html" in ctype:
        alvo = extrair_pluginfiles(resp.text())
        if not alvo:
            return  # não é arquivo (pode ser uma "página" de texto); ignora aqui
        for u in alvo:
            baixar(context, u, destino_dir, manifesto, disciplina, origem)
        return

    nome = nome_de_url(resp.url, resp.headers)
    destino_dir.mkdir(parents=True, exist_ok=True)
    caminho = destino_dir / nome
    # evita sobrescrever arquivos de mesmo nome
    i = 1
    while caminho.exists():
        caminho = destino_dir / f"{caminho.stem}_{i}{caminho.suffix}"
        i += 1
    try:
        caminho.write_bytes(resp.body())
    except Exception as e:
        print(f"      ! erro ao salvar {nome}: {e}")
        return
    print(f"      ✔ {nome}")
    manifesto.append({
        "disciplina": disciplina,
        "arquivo": str(caminho),
        "origem_url": origem,      # o "recibo": de onde este material veio
        "download_url": resp.url,
    })
    time.sleep(PAUSA)


def coletar_disciplina(context, page, disc, saida, manifesto):
    print(f"\n[disciplina] {disc['nome'] or disc['id']}")
    goto_seguro(page, disc["url"])
    time.sleep(0.8)
    conteudo = page.content()

    destino = Path(saida) / sanitize(disc["nome"] or f"curso_{disc['id']}")

    # 1) links de recurso (arquivo único) e de pasta
    links = page.eval_on_selector_all(
        "a[href*='/mod/resource/view.php'], a[href*='/mod/folder/view.php']",
        "els => els.map(e => e.href)",
    )
    # 2) pluginfiles que já aparecem direto na página do curso
    diretos = extrair_pluginfiles(conteudo)

    achou = 0
    for u in diretos:
        baixar(context, u, destino, manifesto, disc["nome"], disc["url"])
        achou += 1

    for link in dict.fromkeys(links):  # dedup preservando ordem
        baixar(context, link, destino, manifesto, disc["nome"], link)
        achou += 1

    if achou == 0:
        print("      (nenhum material baixável encontrado — pode ser disciplina "
              "só com páginas/links, ou o tema da USP usa outra estrutura)")


def main():
    ap = argparse.ArgumentParser(description="Harvester de materiais do Moodle via sessão SSO.")
    ap.add_argument("--out", default="materiais_moodle", help="Pasta de saída.")
    ap.add_argument("--list-only", action="store_true", help="Só lista disciplinas, não baixa.")
    ap.add_argument("--course-id", help="Coleta só uma disciplina (pra testar).")
    ap.add_argument("--headless", action="store_true",
                    help="Sem janela (só use depois que o login já estiver salvo).")
    args = ap.parse_args()

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=PERFIL,
            headless=args.headless,
            accept_downloads=True,
        )
        page = context.pages[0] if context.pages else context.new_page()

        page = esperar_login(context, page)

        if args.course_id:
            discs = [{"id": args.course_id, "nome": "",
                      "url": f"{BASE}/course/view.php?id={args.course_id}"}]
        else:
            discs = listar_disciplinas(page)

        print(f"\nEncontrei {len(discs)} disciplina(s):")
        for d in discs:
            print(f"  • [{d['id']}] {d['nome'] or '(sem nome no card)'}")

        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        disc_path = out_dir / "disciplinas.json"
        disc_path.write_text(json.dumps(discs, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Lista salva em {disc_path} (entrada para jupiter_disciplinas.py)")

        if args.list_only:
            context.close()
            return

        manifesto = []
        for d in discs:
            try:
                coletar_disciplina(context, page, d, args.out, manifesto)
            except Exception as e:
                print(f"   ! erro na disciplina {d['id']}: {e}")

        Path(args.out).mkdir(parents=True, exist_ok=True)
        manif_path = Path(args.out) / "manifesto.json"
        manif_path.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2),
                              encoding="utf-8")

        print(f"\n=== Pronto ===")
        print(f"{len(manifesto)} arquivo(s) baixado(s) em '{args.out}/'")
        print(f"Manifesto (proveniência) salvo em {manif_path}")
        context.close()


if __name__ == "__main__":
    main()
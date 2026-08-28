#!/usr/bin/env python3
"""
jupiter_auth.py — Login manual no Jupiter Web autenticado (área do aluno).

IMPORTANTE: isso NÃO é o SSO SAML do Moodle (ver CLAUDE.md). O Jupiter tem um
formulário de login PRÓPRIO (`webLogin.jsp`, POST pra `autenticar`, campos
`codpes`/`senusu`). Mesma régua de segurança do resto do projeto: o humano
digita usuário+senha na janela real, o script só espera e pega carona na
sessão — nunca toca na senha.

Reusa `.perfil_navegador/` (mesmo profile do harvester_moodle.py — cookies
são por domínio, não há conflito com a sessão do e-Disciplinas).
"""

import sys
import time

import harvester_moodle as hm  # reusa PERFIL/goto_seguro (genéricos, não SAML-specific)

BASE = "https://uspdigital.usp.br/jupiterweb"
PERFIL = hm.PERFIL


def is_logged_in(page):
    """Confirmado contra HTML real: a barra superior pós-login mostra
    'NUSP - Nome | Aluno | Alterar Senha | Sair' — usa o link 'Sair' como
    indicador positivo. Fallback: ausência do form de login / link 'Entrar'."""
    try:
        if page.locator("a:has-text('Sair')").count() > 0:
            return True
        if page.locator("form[action='autenticar']").count() > 0:
            return False
        if page.locator("a[href='webLogin.jsp']").count() > 0:
            return False
        return True
    except Exception:
        return False


def esperar_login(context, page, timeout=300):
    hm.goto_seguro(page, f"{BASE}/webLogin.jsp")
    if is_logged_in(page):
        print("Já estava logado no Jupiter (sessão reaproveitada).")
        return page

    print("\n>>> Na JANELA do navegador, faça login no JUPITER — repare que é um "
          "login DIFERENTE do Moodle:")
    print(">>>   1. preencha 'Usuário' (seu número USP) e 'Senha'")
    print(">>>   2. clique em 'Entrar'")
    print(">>> O script está esperando você terminar (não precisa teclar nada)...\n")

    inicio = time.time()
    ultimo_status = 0
    while time.time() - inicio < timeout:
        for candidata in context.pages:
            try:
                if "uspdigital.usp.br" in candidata.url and is_logged_in(candidata):
                    print(f"Login detectado! (aba: {candidata.url}) Seguindo...\n")
                    return candidata
            except Exception:
                pass
        if time.time() - ultimo_status > 10:
            urls = [p.url for p in context.pages]
            print(f"    [ainda esperando] abas abertas: {urls}")
            for i, p_ in enumerate(context.pages):
                try:
                    p_.screenshot(path=f"_debug_estado_jupiter_{i}.png")
                except Exception:
                    pass
            ultimo_status = time.time()
        time.sleep(2)

    if sys.stdin.isatty():
        print("Passaram-se 5 min sem detectar login. Se já logou, tecle Enter "
              "pra tentar seguir mesmo assim (ou Ctrl+C pra abortar).")
        input()
    else:
        print("Passaram-se 5 min sem detectar login (stdin não interativo, "
              "seguindo sem esperar Enter).")
    for candidata in context.pages:
        try:
            if "uspdigital.usp.br" in candidata.url and is_logged_in(candidata):
                return candidata
        except Exception:
            pass
    return page

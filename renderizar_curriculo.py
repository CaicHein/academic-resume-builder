#!/usr/bin/env python3
"""
renderizar_curriculo.py — Transforma dados_extra/competencias.json (gerado
por gerar_competencias.py) num currículo em LaTeX, dados_extra/curriculo.tex.

Sem chamada de rede, sem LLM aqui — só monta strings e escapa caracteres
especiais do LaTeX. O preâmbulo/estilo visual (cores, tipografia, formato de
seção) é adaptado do exemplo de currículo fornecido pelo usuário; o conteúdo
de cada seção é montado dinamicamente e seções sem dado real são omitidas
(não aparecem em branco).

--- USO ---
    python3 renderizar_curriculo.py

Entrada: dados_extra/competencias.json (rode gerar_competencias.py antes)
Saída:   dados_extra/curriculo.tex — compile com pdflatex/xelatex ou suba
         no Overleaf.
"""

import sys
from pathlib import Path
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

PREAMBULO_LATEX = r"""\documentclass[a4paper,9pt]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[portuguese]{babel}
\usepackage[left=1.0cm, right=1.0cm, top=0.75cm, bottom=0.75cm]{geometry}
\usepackage{enumitem}
\usepackage{hyperref}
\usepackage{titlesec}
\usepackage{xcolor}

\definecolor{darkblue}{rgb}{0.0, 0.0, 0.45}

\hypersetup{colorlinks=true, linkcolor=darkblue, urlcolor=darkblue, pdftitle={%s}}

\titleformat{\section}{\small\bfseries\MakeUppercase}{}{0em}{}[\vspace{-2pt}\rule{\linewidth}{0.4pt}]
\titlespacing{\section}{0pt}{5pt}{3pt}

\setlength{\parindent}{0pt}
\pagestyle{empty}

\begin{document}
"""


def escapar_latex(texto):
    if texto is None:
        return ""
    substituicoes = [
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ]
    texto = str(texto)
    for alvo, novo in substituicoes:
        texto = texto.replace(alvo, novo)
    return texto


def render_cabecalho(contato):
    contato = contato or {}
    nome = escapar_latex(contato.get("nome")) or "Currículo"

    linha_contato = []
    if contato.get("cidade_estado"):
        linha_contato.append(escapar_latex(contato["cidade_estado"]))
    if contato.get("email"):
        email = escapar_latex(contato["email"])
        linha_contato.append(r"\href{mailto:%s}{%s}" % (email, email))
    if contato.get("telefone"):
        linha_contato.append(escapar_latex(contato["telefone"]))
    if contato.get("linkedin_url"):
        url = contato["linkedin_url"]
        rotulo = escapar_latex(url.replace("https://", "").replace("http://", ""))
        linha_contato.append(r"\href{%s}{%s}" % (url, rotulo))
    if contato.get("github_url"):
        url = contato["github_url"]
        rotulo = escapar_latex(url.replace("https://", "").replace("http://", ""))
        linha_contato.append(r"\href{%s}{%s}" % (url, rotulo))

    contato_tex = " \\;\\textbullet{}\\; ".join(linha_contato)

    partes = ["\\begin{center}", "    {\\Large \\textbf{%s}} \\\\[2pt]" % nome]
    if contato_tex:
        partes.append("    {\\footnotesize %s}" % contato_tex)
    partes.append("\\end{center}\n")
    return "\n".join(partes)


def render_resumo(resumo):
    if not resumo:
        return ""
    return "\\section{Resumo}\n%s\n\n" % escapar_latex(resumo)


def render_habilidades(habilidades):
    if not habilidades:
        return ""
    linhas = ["\\section{Habilidades Técnicas}",
              "\\begin{itemize}[noitemsep, topsep=0pt, leftmargin=*, itemsep=0pt]"]
    for grupo in habilidades:
        categoria = escapar_latex(grupo.get("categoria"))
        itens = ", ".join(escapar_latex(i) for i in grupo.get("itens", []))
        if not itens:
            continue
        linhas.append("    \\item \\textbf{%s:} %s" % (categoria, itens))
    linhas.append("\\end{itemize}\n")
    return "\n".join(linhas)


def render_experiencia(experiencias):
    if not experiencias:
        return ""
    linhas = ["\\section{Experiência Profissional}"]
    for exp in experiencias:
        instituicao = escapar_latex(exp.get("instituicao"))
        local = escapar_latex(exp.get("local")) if exp.get("local") else ""
        cargo = escapar_latex(exp.get("cargo"))
        periodo = escapar_latex(exp.get("periodo"))
        cabeca = "\\textbf{%s}" % instituicao
        if local:
            cabeca += " \\hfill %s \\\\" % local
        else:
            cabeca += " \\\\"
        linhas.append(cabeca)
        linhas.append("\\textit{%s} \\hfill %s" % (cargo, periodo))
        bullets = exp.get("bullets", [])
        if bullets:
            linhas.append("\\begin{itemize}[noitemsep, topsep=2pt, leftmargin=*, itemsep=1pt]")
            for b in bullets:
                linhas.append("    \\item %s" % escapar_latex(b.get("texto")))
            linhas.append("\\end{itemize}")
        linhas.append("\\vspace{3pt}\n")
    return "\n".join(linhas)


def render_projetos(projetos):
    if not projetos:
        return ""
    linhas = ["\\section{Projetos}",
              "\\begin{itemize}[noitemsep, topsep=1pt, leftmargin=*, itemsep=1pt]"]
    for p in projetos:
        nome = escapar_latex(p.get("nome"))
        descricao = escapar_latex(p.get("descricao"))
        if p.get("url"):
            titulo = "\\textbf{%s} (\\href{%s}{link})" % (nome, p["url"])
        else:
            titulo = "\\textbf{%s}" % nome
        linhas.append("    \\item %s: %s" % (titulo, descricao))
    linhas.append("\\end{itemize}\n")
    return "\n".join(linhas)


def render_formacao(formacoes):
    if not formacoes:
        return ""
    linhas = ["\\section{Formação Acadêmica}"]
    for f in formacoes:
        instituicao = escapar_latex(f.get("instituicao"))
        local = escapar_latex(f.get("local")) if f.get("local") else ""
        curso = escapar_latex(f.get("curso"))
        periodo = escapar_latex(f.get("periodo"))
        cabeca = "\\textbf{%s}" % instituicao
        if local:
            cabeca += " \\hfill %s \\\\" % local
        else:
            cabeca += " \\\\"
        linhas.append(cabeca)
        linhas.append("\\textit{%s} \\hfill %s\n" % (curso, periodo))
    return "\n".join(linhas)


def render_certificacoes(certificacoes):
    if not certificacoes:
        return ""
    itens = " \\quad\\textbullet\\quad ".join(escapar_latex(c) for c in certificacoes)
    return "\\section{Certificações}\n%s\n\n" % itens


def render_idiomas(idiomas):
    if not idiomas:
        return ""
    itens = " \\quad\\textbullet\\quad ".join(
        "\\textbf{%s:} %s" % (escapar_latex(i.get("idioma")), escapar_latex(i.get("nivel")))
        for i in idiomas
    )
    return "\\section{Idiomas}\n%s\n\n" % itens


def montar_curriculo(competencias):
    contato = competencias.get("contato") or {}
    nome_pdftitle = escapar_latex(contato.get("nome")) or "Curriculo"

    partes = [
        PREAMBULO_LATEX % ("Curriculo %s" % nome_pdftitle),
        render_cabecalho(contato),
        render_resumo(competencias.get("resumo")),
        render_habilidades(competencias.get("habilidades_tecnicas", [])),
        render_experiencia(competencias.get("experiencia_profissional", [])),
        render_projetos(competencias.get("projetos", [])),
        render_formacao(competencias.get("formacao_academica", [])),
        render_certificacoes(competencias.get("certificacoes", [])),
        render_idiomas(competencias.get("idiomas", [])),
        "\\end{document}\n",
    ]
    return "\n".join(p for p in partes if p)


def main():
    entrada = Path("dados_extra/competencias.json")
    if not entrada.exists():
        print("Falta dados_extra/competencias.json. Rode gerar_competencias.py primeiro.",
              file=sys.stderr)
        sys.exit(1)

    competencias = json.loads(entrada.read_text(encoding="utf-8"))
    tex = montar_curriculo(competencias)

    saida = Path("dados_extra/curriculo.tex")
    saida.write_text(tex, encoding="utf-8")

    print(f"=== Pronto ===")
    print(f"Currículo em LaTeX salvo em {saida}")
    print("Compile com pdflatex/xelatex, ou suba o arquivo no Overleaf.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
jupiter_disciplinas.py — Enriquece a lista de disciplinas (vinda do Moodle) com
os dados oficiais de cada disciplina no Jupiter Web (Sistema Júpiter da USP).

Por quê: o Moodle só dá o NOME da disciplina — não diz o que ela ensina. O
Jupiter Web tem, para cada disciplina, um cadastro público (sem login) com
ementa, objetivos, conteúdo programático, forma de avaliação, bibliografia,
docentes e créditos/carga horária. Isso é matéria-prima muito melhor para
gerar competências de currículo do que só o nome da disciplina — e os créditos
servem de conferência (bate com o histórico escolar? esqueceu alguma
disciplina?).

Diferença importante em relação ao harvester_moodle.py: a busca de disciplina
do Jupiter (`obterDisciplina`) é uma página PÚBLICA, sem SSO. Não precisa de
Playwright nem de sessão logada — é um GET HTTP simples.

Entrada: o `disciplinas.json` gerado por `harvester_moodle.py --list-only`
(lista de {id, nome, url} vindos do card do Moodle). Para cada disciplina,
tenta extrair um código/sigla USP do nome (ex: "SCC0201") e consulta o
Jupiter. Quando o nome não tem um código reconhecível, ou a sigla não bate
com nada, cai para busca por nome — que pode ser ambígua (várias disciplinas
com nome parecido em unidades diferentes); nesse caso NÃO adivinha: registra
os candidatos e marca como "ambiguo" para revisão manual (ou por um passo de
LLM mais adiante, mas com a lista de candidatos explícita, não uma escolha
silenciosa).

--- USO ---
    python3 jupiter_disciplinas.py                       # usa materiais_moodle/disciplinas.json
    python3 jupiter_disciplinas.py --in outro/lista.json
    python3 jupiter_disciplinas.py --sigla SCC0201        # testa 1 disciplina pela sigla
    python3 jupiter_disciplinas.py --nome "Cálculo Diferencial e Integral I"  # testa por nome

Saída: materiais_moodle/jupiter_disciplinas.json — uma entrada por disciplina
de entrada, com status ("ok" | "ambiguo" | "nao_encontrado"), os dados
extraídos e a URL de origem (o "recibo").
"""

import argparse
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# console do Windows costuma abrir em cp1252/cp437 e trava (UnicodeEncodeError)
# ao imprimir nomes de disciplina/docente com acentos. Força UTF-8 na saída.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BASE = "https://uspdigital.usp.br/jupiterweb"
PAUSA = 0.7  # segundos entre requisições (mesma cortesia do harvester_moodle.py)
UA = "Mozilla/5.0 (compatible; harvester-curriculo/1.0; uso pessoal)"

# códigos USP: 2-4 letras + 4 dígitos (ex.: SCC0201, MAC0110) ou 7 dígitos
# (código antigo, comum em algumas unidades como FFCLRP, ex.: 5950106).
# NÃO usar \b no final: nomes reais do Moodle colam o código com "_" antes do
# ano (ex.: "PMR3408_2026") — "_" conta como \w, então \b falha bem ali e a
# sigla nunca é extraída. Em vez disso: não pode vir antes de letra/dígito
# (evita casar no meio de outro código) e não pode ser seguido de outro
# dígito (evita pegar só um pedaço de um código maior).
SIGLA_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{2,4}\d{4}|\d{7})(?!\d)")

# labels que delimitam as seções de texto livre da página de disciplina, NA
# ORDEM em que aparecem. Servem só de fronteira; o conteúdo de cada seção é
# tudo que estiver entre um label e o próximo desta lista.
SECOES = [
    "Ementa",
    "Objetivos",
    "Conteúdo Programático",
    "Instrumentos e Critérios de Avaliação",
    "Método de Avaliação",
    "Critério de Avaliação",
    "Norma de Recuperação",
    "Bibliografia",
    "Docente(s) Responsável(eis)",
]

CAMPO_INLINE_RE = {
    "creditos_aula": re.compile(r"^Cr[ée]ditos Aula:\s*(.*)$"),
    "creditos_trabalho": re.compile(r"^Cr[ée]ditos Trabalho:\s*(.*)$"),
    "carga_horaria_total": re.compile(r"^Carga Hor[áa]ria Total:\s*(.*)$"),
    "tipo": re.compile(r"^Tipo:\s*(.*)$"),
}
# Ativação e Desativação ficam na MESMA linha de tabela (2 pares label/valor
# no mesmo <tr>), por isso um regex combinado em vez de um por campo.
ATIVACAO_RE = re.compile(r"^Ativa[çc][ãa]o:\s*(.*?)\s*Desativa[çc][ãa]o:\s*(.*)$")

CANDIDATO_RE = re.compile(
    r"href='obterDisciplina\?sgldis=([^&']+)&verdis=(\d+)'\s*class=\"link_gray\">([^<]+)<"
)
DOCENTE_RE = re.compile(r"^(\d+)\s*-\s*(.+)$")


def buscar_url(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    time.sleep(PAUSA)
    # a página se declara iso-8859-1 no <meta charset>, mas na prática usa
    # bytes windows-1252 (bullets, aspas curvas etc. na faixa 0x80-0x9F que
    # em iso-8859-1 puro viram controles inválidos). cp1252 é compatível com
    # iso-8859-1 pros acentos e decodifica esses bytes corretamente também.
    return raw.decode("cp1252", errors="replace")


def extrair_candidatos(raw_html):
    """Página de desambiguação: várias disciplinas casaram com a busca."""
    vistos = {}
    for sigla, verdis, nome in CANDIDATO_RE.findall(raw_html):
        nome = html.unescape(nome).strip()
        vistos[(sigla, verdis)] = {"sigla": sigla, "verdis": verdis, "nome": nome}
    return list(vistos.values())


def html_para_linhas(raw_html):
    """Achata a página numa lista de linhas: uma por <tr> (preservando pares
    label/valor que ficam em <td>s da mesma linha) e por quebra dentro de
    <pre>. Convertida a partir do HTML real da página de disciplina.

    O HTML de origem já vem com quebras de linha "cosméticas" dentro de cada
    <tr> (formatação do código-fonte da página, sem <br>). Se a gente só
    quebrasse linha em <br>/</tr>, essas quebras cosméticas separariam label
    e valor que logicamente estão juntos (ex.: "Créditos Aula:" e "4" ficam
    em <td>s da MESMA linha, mas em linhas de texto-fonte diferentes).
    Por isso: primeiro marca as quebras que IMPORTAM com um marcador único,
    depois colapsa todo o resto do espaço em branco (inclusive quebras
    cosméticas) em espaço simples, só então divide pelo marcador.
    """
    texto = re.sub(r"<br\s*/?>", "\x01", raw_html, flags=re.I)
    texto = re.sub(r"</tr>", "\x01", texto, flags=re.I)
    texto = re.sub(r"\s+", " ", texto)
    texto = re.sub(r"<[^>]+>", " ", texto)
    texto = html.unescape(texto)
    linhas = [re.sub(r" +", " ", l).strip() for l in texto.split("\x01")]
    return [l for l in linhas if l]


def parse_disciplina(raw_html, origem_url):
    linhas = html_para_linhas(raw_html)

    disc = {
        "sigla": None, "nome_pt": None, "nome_en": None,
        "unidade": None, "departamento": None,
        "creditos_aula": None, "creditos_trabalho": None,
        "carga_horaria_total": None, "tipo": None,
        "ativacao": None, "desativacao": None,
        "ementa": None, "objetivos": None, "conteudo_programatico": None,
        "metodo_avaliacao": None, "criterio_avaliacao": None,
        "norma_recuperacao": None, "bibliografia": None,
        "docentes": [],
        "origem_url": origem_url,
    }

    idx_disc = None
    for i, l in enumerate(linhas):
        m = re.match(r"^Disciplina:\s*(\S+)\s+-\s+(.+)$", l)
        if m:
            disc["sigla"], disc["nome_pt"] = m.group(1), m.group(2)
            idx_disc = i
            break
    if idx_disc is None:
        return None  # não é uma página de disciplina válida

    if idx_disc >= 2:
        disc["unidade"] = linhas[idx_disc - 2]
    if idx_disc >= 1:
        disc["departamento"] = linhas[idx_disc - 1]

    # campos inline (label e valor na mesma linha) — escaneia tudo
    for l in linhas:
        for campo, regex in CAMPO_INLINE_RE.items():
            m = regex.match(l)
            if m:
                disc[campo] = m.group(1).strip() or None
        m = ATIVACAO_RE.match(l)
        if m:
            disc["ativacao"] = m.group(1).strip() or None
            disc["desativacao"] = m.group(2).strip() or None

    # nome em inglês: linha entre "Disciplina: ..." e "Créditos Aula:"
    idx_creditos = next(
        (i for i, l in enumerate(linhas) if l.startswith("Créditos Aula:")), None
    )
    if idx_creditos and idx_creditos > idx_disc + 1:
        candidato = linhas[idx_disc + 1]
        if not candidato.startswith("Créditos"):
            disc["nome_en"] = candidato

    # seções de texto livre, delimitadas pelos labels em SECOES (nesta ordem)
    indices = {}
    cursor = idx_disc
    for label in SECOES:
        achou = next(
            (i for i in range(cursor, len(linhas)) if linhas[i] == label), None
        )
        if achou is not None:
            indices[label] = achou
            cursor = achou + 1

    campo_por_secao = {
        "Ementa": "ementa",
        "Objetivos": "objetivos",
        "Conteúdo Programático": "conteudo_programatico",
        "Método de Avaliação": "metodo_avaliacao",
        "Critério de Avaliação": "criterio_avaliacao",
        "Norma de Recuperação": "norma_recuperacao",
        "Bibliografia": "bibliografia",
    }
    ordem_labels = list(indices.keys())
    for pos, label in enumerate(ordem_labels):
        campo = campo_por_secao.get(label)
        if not campo:
            continue
        ini = indices[label] + 1
        fim = indices[ordem_labels[pos + 1]] if pos + 1 < len(ordem_labels) else len(linhas)
        conteudo = "\n".join(linhas[ini:fim]).strip()
        disc[campo] = conteudo or None

    if "Docente(s) Responsável(eis)" in indices:
        ini = indices["Docente(s) Responsável(eis)"] + 1
        fim = next(
            (i for i in range(ini, len(linhas)) if linhas[i].startswith("Clique para consultar")),
            len(linhas),
        )
        for l in linhas[ini:fim]:
            m = DOCENTE_RE.match(l)
            if m:
                disc["docentes"].append({"nusp": m.group(1), "nome": m.group(2).strip()})

    return disc


def consultar(sigla=None, nome=None, verdis=None):
    """Consulta o Jupiter por sigla e/ou nome. Retorna
    ("ok", disciplina_dict) | ("ambiguo", lista_candidatos) | ("nao_encontrado", None).
    """
    params = {"sgldis": sigla or "", "nomdis": nome or ""}
    if verdis:
        params["verdis"] = verdis
    url = f"{BASE}/obterDisciplina?{urllib.parse.urlencode(params)}"
    raw = buscar_url(url)

    candidatos = extrair_candidatos(raw)
    if candidatos:
        return "ambiguo", candidatos, url

    disc = parse_disciplina(raw, url)
    if disc is None:
        return "nao_encontrado", None, url
    return "ok", disc, url


def resolver_disciplina(nome_moodle):
    """Estratégia: tenta achar uma sigla no nome do Moodle e buscar direto por
    ela. Se não achar sigla, ou a sigla não bater com nada, cai pra busca por
    nome (que pode ser ambígua — não escolhemos por você)."""
    m = SIGLA_RE.search(nome_moodle or "")
    sigla = m.group(1) if m else None

    if sigla:
        status, dado, url = consultar(sigla=sigla)
        if status == "ok":
            return {"status": "ok", "sigla_tentada": sigla, "disciplina": dado, "origem_url": url}
        if status == "ambiguo":
            # se a busca por sigla (que deveria ser exata) ainda voltou uma
            # lista, filtra pra só os candidatos com ESSA sigla exata.
            batem = [c for c in dado if c["sigla"] == sigla]
            if len(batem) == 1:
                c = batem[0]
                status2, dado2, url2 = consultar(sigla=c["sigla"], verdis=c["verdis"])
                if status2 == "ok":
                    return {"status": "ok", "sigla_tentada": sigla, "disciplina": dado2, "origem_url": url2}
            if batem:
                return {
                    "status": "ambiguo", "sigla_tentada": sigla,
                    "candidatos": batem, "origem_url": url,
                }
        # sigla não achou nada — cai para busca por nome abaixo

    status, dado, url = consultar(nome=nome_moodle)
    if status == "ok":
        return {"status": "ok", "sigla_tentada": sigla, "disciplina": dado, "origem_url": url}
    if status == "ambiguo":
        return {"status": "ambiguo", "sigla_tentada": sigla, "candidatos": dado, "origem_url": url}
    return {"status": "nao_encontrado", "sigla_tentada": sigla, "origem_url": url}


def main():
    ap = argparse.ArgumentParser(description="Busca ementa/dados de disciplinas no Jupiter Web.")
    ap.add_argument("--in", dest="entrada", default="materiais_moodle/disciplinas.json",
                     help="JSON de entrada (saída de harvester_moodle.py --list-only).")
    ap.add_argument("--out", default="materiais_moodle/jupiter_disciplinas.json")
    ap.add_argument("--sigla", help="Testa uma disciplina só, pela sigla (ex.: SCC0201).")
    ap.add_argument("--nome", help="Testa uma disciplina só, pelo nome.")
    args = ap.parse_args()

    if args.sigla or args.nome:
        # aqui é teste direto (você já sabe a sigla/nome) — não passa pela
        # heurística de extrair sigla de um nome de disciplina do Moodle.
        status, dado, url = consultar(sigla=args.sigla, nome=args.nome)
        if status == "ok":
            resultado = {"status": "ok", "disciplina": dado, "origem_url": url}
        elif status == "ambiguo":
            resultado = {"status": "ambiguo", "candidatos": dado, "origem_url": url}
        else:
            resultado = {"status": "nao_encontrado", "origem_url": url}
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
        return

    entrada_path = Path(args.entrada)
    if not entrada_path.exists():
        print(f"Não achei {entrada_path}. Rode antes: "
              f"python3 harvester_moodle.py --list-only", file=sys.stderr)
        sys.exit(1)

    discs = json.loads(entrada_path.read_text(encoding="utf-8"))
    resultados = []
    contagem = {"ok": 0, "ambiguo": 0, "nao_encontrado": 0}

    for d in discs:
        nome = d.get("nome") or ""
        print(f"[{d.get('id')}] {nome or '(sem nome)'}")
        r = resolver_disciplina(nome)
        r["moodle_id"] = d.get("id")
        r["moodle_nome"] = nome
        resultados.append(r)
        contagem[r["status"]] += 1
        if r["status"] == "ok":
            print(f"    ✔ {r['disciplina']['sigla']} — "
                  f"{r['disciplina']['creditos_aula']}+{r['disciplina']['creditos_trabalho']} créditos")
        elif r["status"] == "ambiguo":
            print(f"    ? ambíguo — {len(r['candidatos'])} candidato(s), revisar manualmente")
        else:
            print(f"    ✗ não encontrado no Jupiter")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n=== Resumo ===")
    print(f"ok: {contagem['ok']}  ambíguo: {contagem['ambiguo']}  "
          f"não encontrado: {contagem['nao_encontrado']}")
    print(f"Salvo em {out_path}")
    if contagem["ambiguo"] or contagem["nao_encontrado"]:
        print("(Debug: confira as disciplinas ambíguas/não encontradas — pode ser "
              "sigla não reconhecida no nome do Moodle, ou nome que não bate "
              "exatamente com o cadastro do Jupiter.)")


if __name__ == "__main__":
    main()

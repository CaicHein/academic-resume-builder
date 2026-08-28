#!/usr/bin/env python3
"""
parse_historico.py — Extrai os dados do PDF do histórico escolar
(`materiais_moodle/historico_escolar.pdf`, gerado por `baixar_historico.py`)
e:

Junta tudo (ementa do Jupiter + notas do Moodle + histórico) num ÚNICO json
final, `materiais_moodle/trajetoria_academica.json`: `{"perfil": {...dados
pessoais, créditos/médias globais, período de intercâmbio...}, "disciplinas":
[...cada uma com ementa+notas+histórico aninhados...]}`. Esse é o arquivo pra
consumir daqui pra frente (não os .json brutos de cada coletor, que continuam
existindo só como proveniência/recibo de cada fonte — ver "Arquitetura de
dados" no CLAUDE.md).

Disciplinas do histórico que não batem com nenhuma sigla do consolidado são
listadas à parte (não descartadas em silêncio) — é sinal de disciplina sem
harvest do Moodle correspondente, útil pro "será que esqueci alguma
disciplina" que motivou esse pipeline todo.

--- USO ---
    python3 parse_historico.py
"""

import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

try:
    import pdfplumber
except ImportError:
    print("pdfplumber não instalado. Rode:\n    pip install pdfplumber", file=sys.stderr)
    sys.exit(1)

SEMESTRE_RE = re.compile(r"^(\d{4})\s+(\d)[ºo]\.\s*(Semestre|Anual)$")
LINHA_BOILERPLATE_RE = re.compile(
    r"^(UNIVERSIDADE DE SÃO PAULO|Júpiter -|HISTÓRICO ESCOLAR|Unidade:|Aluno:|"
    r"Ingresso:|Curso:|Habilitação:|Módulo:|_{5,}|Emitido em|Creditos Atividade|"
    r"Sigla Nome da Disciplina)"
)
SITUACOES_VALIDAS = {
    "A", "MA", "T", "RN", "RA", "RF", "DI", "DS", "AE",
    "I", "IR", "IT", "IP", "P", "IL",
}
# sigla: letras/dígitos, sem espaço; nome pode ter qualquer coisa (não-guloso).
LINHA_DISC_RE = re.compile(
    r"^(?P<sigla>[A-Z0-9]+)\s+(?P<resto>.+)$"
)
CREDITOS_SEMESTRE_RE = re.compile(
    r"^Créditos (?:acumulados|pretendidos) no Semestre\s+(\d+)\s+(\d+)"
    r"(?:\s+Média ponderada com reprovações:\s+([\d.]+))?$"
)
# "Dispensa(s) Específica(s)": disciplina dispensada + 1+ disciplinas
# equivalentes que geraram o crédito. Layout de tabela linearizado em texto —
# ver comentário em parse_dispensas() sobre como isso é reconstruído.
DISPENSA_HEADER_RE = re.compile(r"^Dispensa\(s\) Específica\(s\)$")
DISPENSA_COLUNAS_RE = re.compile(r"^Universidade de São Paulo Equivalente")
EQUIVALENTE_RE = re.compile(r"^(.+?)\s+(\d+)\s+(\d+)\s+([\d.]+)\s+(\d{4}/\d)$")
UNIDADE_CONTINUACAO_RE = re.compile(r"^\d+\s+\S.*$")
CREDITOS_TIPO_HEADER = "Totais de Créditos Acumulados por Tipo de Obrigatoriedade:"
CREDITOS_TIPO_LINHA_RE = re.compile(r"^(\S+)\s+(\d+)\s+(\d+)$")


def extrair_texto(pdf_path):
    linhas = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            texto = page.extract_text() or ""
            linhas.extend(texto.split("\n"))
    return linhas


def limpar_linhas(linhas):
    """Remove boilerplate repetido por página (cabeçalho/rodapé) e linhas
    vazias, preservando a ordem — usado pelos parsers que dependem de
    posição sequencial (dispensas, créditos por tipo)."""
    limpas = []
    for linha in linhas:
        linha = linha.strip()
        if not linha or LINHA_BOILERPLATE_RE.match(linha):
            continue
        limpas.append(linha)
    return limpas


def parse_dispensas(linhas_limpas):
    """"Dispensa(s) Específica(s)": disciplina(s) dispensada(s) por
    equivalência com disciplina(s) já cursada(s) em outro lugar (ex.: crédito
    por matéria cursada antes de ingressar, ou em outra unidade).

    O texto linearizado intercala assim (visto no PDF real):
        PMR3100 Introdução a Engenharia          <- nome da dispensada, pode quebrar linha
        Mecatrônica                              <- continuação do nome (quebra de linha)
        Matérias Primas Minerais 2 0 6.7 2022/1  <- 1º equivalente: nome + créd.aula + créd.trab + nota + período
        3 Escola Politécnica                     <- unidade do equivalente (linha seguinte)
        Introdução à Engenharia de Petróleo 2 0 8.6 2022/1  <- 2º equivalente
        3 Escola Politécnica
    Uma linha de equivalente é reconhecida pelo padrão fixo no final
    (aula trabalho nota período) — tudo antes disso, ainda sem bater esse
    padrão, é acumulado como nome da disciplina dispensada.
    """
    dispensas = []
    i, n = 0, len(linhas_limpas)
    while i < n:
        if not DISPENSA_HEADER_RE.match(linhas_limpas[i]):
            i += 1
            continue
        i += 1
        if i < n and DISPENSA_COLUNAS_RE.match(linhas_limpas[i]):
            i += 1

        nome_partes = []
        while i < n and not EQUIVALENTE_RE.match(linhas_limpas[i]) and linhas_limpas[i] != "Observações":
            nome_partes.append(linhas_limpas[i])
            i += 1

        # a partir daqui, lê os equivalentes — mas o texto linearizado às vezes
        # intercala uma quebra de linha do NOME DA DISPENSADA entre dois
        # equivalentes (visto no PDF real: a continuação "Mecatrônica" aparece
        # DEPOIS do primeiro equivalente, não antes). Uma linha que não é
        # equivalente nem unidade só pode ser essa continuação (são as 2
        # únicas colunas de texto livre da tabela) — guarda à parte em vez de
        # desistir e perder os equivalentes seguintes.
        equivalentes = []
        linhas_extra = []

        def continua_secao():
            return i < n and linhas_limpas[i] != "Observações" and not DISPENSA_HEADER_RE.match(linhas_limpas[i])

        while continua_secao():
            m = EQUIVALENTE_RE.match(linhas_limpas[i])
            if not m:
                linhas_extra.append(linhas_limpas[i])
                i += 1
                continue
            nome_eq, aul, trab, nota, periodo = m.groups()
            i += 1
            # a unidade nem sempre vem logo em seguida — pode ter uma quebra
            # de nome da dispensada no meio (visto no PDF real). Continua
            # procurando até achar a unidade ou esbarrar no próximo
            # equivalente (aí desiste, esse não teve unidade capturada).
            unidade = None
            while continua_secao() and not EQUIVALENTE_RE.match(linhas_limpas[i]):
                if UNIDADE_CONTINUACAO_RE.match(linhas_limpas[i]):
                    unidade = linhas_limpas[i]
                    i += 1
                    break
                linhas_extra.append(linhas_limpas[i])
                i += 1
            equivalentes.append({
                "nome": nome_eq.strip(),
                "creditos_aula": int(aul),
                "creditos_trabalho": int(trab),
                "nota": float(nota),
                "periodo": periodo,
                "unidade": unidade,
            })

        nome_completo = " ".join(nome_partes + linhas_extra).strip()
        m_sigla = re.match(r"^(\S+)\s+(.+)$", nome_completo) if nome_completo else None
        disciplina_dispensada = {
            "sigla": m_sigla.group(1) if m_sigla else None,
            "nome": m_sigla.group(2) if m_sigla else (nome_completo or None),
        }

        dispensas.append({
            "disciplina_dispensada": disciplina_dispensada,
            "equivalentes": equivalentes,
        })
    return dispensas


def parse_creditos_por_tipo(linhas_limpas):
    """"Totais de Créditos Acumulados por Tipo de Obrigatoriedade": quanto dos
    créditos é Obrigatória vs. Optativa Eletiva vs. Optativa Livre."""
    if CREDITOS_TIPO_HEADER not in linhas_limpas:
        return None
    j = linhas_limpas.index(CREDITOS_TIPO_HEADER) + 1
    n = len(linhas_limpas)
    if j < n and linhas_limpas[j] == "Aula Trabalho":
        j += 1
    resultado = {}
    while j < n:
        m = CREDITOS_TIPO_LINHA_RE.match(linhas_limpas[j])
        if not m:
            break
        chave, aula, trabalho = m.groups()
        resultado[chave] = {"aula": int(aula), "trabalho": int(trabalho)}
        j += 1
    return resultado or None


def parse_linha_disciplina(linha):
    """Devolve dict com sigla/nome/creditos/frequencia/nota/situacao, ou None
    se a linha não bater com o formato de linha de disciplina."""
    m = LINHA_DISC_RE.match(linha)
    if not m:
        return None
    sigla, resto = m.group("sigla"), m.group("resto")

    tokens = resto.split()
    if not tokens:
        return None

    # a situação é sempre o ÚLTIMO token, e é um código conhecido (A, MA, RN...).
    situacao = tokens[-1]
    if situacao not in SITUACOES_VALIDAS:
        return None  # não é uma linha de disciplina de verdade

    # entre o nome e a situação: uma sequência de números. NOTA (quando existe)
    # é o único valor com ponto decimal, e vem logo antes de FREQ (inteiro).
    resto_tokens = tokens[:-1]
    numeros_idx = next(
        (i for i, t in enumerate(resto_tokens) if re.fullmatch(r"\d+(\.\d+)?", t)),
        None,
    )
    if numeros_idx is None:
        return None  # nenhum número achado — não é linha de disciplina

    nome = " ".join(resto_tokens[:numeros_idx]).strip()
    numeros = resto_tokens[numeros_idx:]

    nota = None
    frequencia = None
    if numeros and re.fullmatch(r"\d+\.\d+", numeros[-1]):
        nota = float(numeros[-1])
        numeros = numeros[:-1]
        if numeros:
            frequencia = int(numeros[-1])
            numeros = numeros[:-1]

    creditos_aula = int(numeros[0]) if numeros else None
    carga_horaria = int(numeros[-1]) if len(numeros) >= 2 else None
    # colunas do meio (TR/CE/CP/EXT/ATPA) são ambíguas só pelo texto — o PDF
    # omite colunas zeradas em vez de imprimir "0", e sem as coordenadas X de
    # cada coluna não dá pra saber com certeza qual é qual quando há mais de
    # uma. Guarda cru, sem rotular além do que é seguro (aula/carga horária).
    creditos_meio_ambiguo = [int(x) for x in numeros[1:-1]] if len(numeros) > 2 else []

    return {
        "sigla": sigla,
        "nome_historico": nome,
        "creditos_aula": creditos_aula,
        "carga_horaria": carga_horaria,
        "creditos_meio_ambiguo": creditos_meio_ambiguo or None,
        "frequencia": frequencia,
        "nota": nota,
        "situacao": situacao,
    }


def parse_historico(linhas):
    semestres = []
    semestre_atual = None
    nao_estruturado = []  # linhas que não reconhecemos — guardadas pra não perder nada

    for linha in linhas:
        linha = linha.strip()
        if not linha or LINHA_BOILERPLATE_RE.match(linha):
            continue

        m_sem = SEMESTRE_RE.match(linha)
        if m_sem:
            semestre_atual = {
                "ano": int(m_sem.group(1)),
                "periodo": f"{m_sem.group(2)}º",
                "tipo": m_sem.group(3),
                "disciplinas": [],
                "creditos_aula_semestre": None,
                "creditos_trabalho_semestre": None,
                "media_ponderada_semestre": None,
            }
            semestres.append(semestre_atual)
            continue

        m_cred = CREDITOS_SEMESTRE_RE.match(linha)
        if m_cred and semestre_atual is not None:
            semestre_atual["creditos_aula_semestre"] = int(m_cred.group(1))
            semestre_atual["creditos_trabalho_semestre"] = int(m_cred.group(2))
            if m_cred.group(3):
                semestre_atual["media_ponderada_semestre"] = float(m_cred.group(3))
            continue

        if linha.startswith(("Modalidade:", "Instituição de Intercâmbio:", "País:",
                              "Cursando Disciplinas no Exterior")):
            if semestre_atual is not None:
                semestre_atual.setdefault("observacoes", []).append(linha)
            continue

        disc = parse_linha_disciplina(linha)
        if disc:
            if semestre_atual is not None:
                disc["ano"] = semestre_atual["ano"]
                disc["periodo"] = semestre_atual["periodo"]
                semestre_atual["disciplinas"].append(disc)
            continue

        nao_estruturado.append(linha)

    return semestres, nao_estruturado


def extrair_resumo(linhas_completas):
    """Campos avulsos de proveniência pessoal/geral (não por disciplina)."""
    texto = "\n".join(linhas_completas)

    def buscar(padrao, grupo=1, multiline=False):
        m = re.search(padrao, texto, re.M if multiline else 0)
        return m.group(grupo).strip() if m else None

    return {
        "aluno": buscar(r"Aluno:\s*(.+)"),
        "unidade": buscar(r"Unidade:\s*(.+)"),
        "curso": buscar(r"Curso:\s*(.+)"),
        "habilitacao": buscar(r"Habilitação:\s*(.+)"),
        "modulo": buscar(r"Módulo:\s*(.+)"),
        "ingresso": buscar(r"Ingresso:\s*(.+)"),
        "forma_ingresso": buscar(r"Forma de ingresso\s*:\s*(.+)"),
        "classificacao_na_carreira": buscar(r"Classificação na carreira:\s*(.+)"),
        "quantidade_reingressos": buscar(r"Quantidade de reingressos:\s*(\d+)"),
        "data_nascimento": buscar(r"Data de nascimento:\s*(.+)"),
        "naturalidade": buscar(r"Naturalidade:\s*(.+)"),
        "nacionalidade": buscar(r"Nacionalidade:\s*(.+)"),
        "cedula_identidade": buscar(r"Cédula de identidade:\s*(.+)"),
        "creditos_obtidos": buscar(r"Créditos obtidos:\s*(.+)"),
        "creditos_matriculados": buscar(r"Créditos matriculados:\s*(.+)"),
        "carga_horaria_total": buscar(r"Carga Horária Total:\s*(.+)"),
        # a mesma frase aparece por semestre ("Créditos acumulados no Semestre
        # N M Média ponderada com reprovações: X") — só a versão RESUMO GERAL
        # começa a linha com o rótulo (^), sem o prefixo de créditos do semestre.
        "media_ponderada_com_reprovacoes": buscar(
            r"^Média ponderada com reprovações:\s*([\d.]+)", multiline=True
        ),
        "media_normalizada": buscar(r"Média normalizada\s*:\s*([\d.]+)"),
        "media_ponderada_do_curso": buscar(r"Média ponderada de seu curso\s*:\s*([\d.]+)"),
        "valores_selecao_optativas": buscar(r"Valores para seleção das optativas\s*:\s*([\d.]+)"),
        "observacoes_gerais": buscar(r"^Observações\n(.+)", multiline=True),
    }


def main():
    pdf_path = Path("materiais_moodle/historico_escolar.pdf")
    consolidado_path = Path("materiais_moodle/disciplinas_consolidado.json")
    # trajetoria_academica.json é o ÚNICO arquivo final sobre "disciplinas
    # cursadas" (ementa + notas + histórico + perfil) — os outros .json em
    # materiais_moodle/ são saída bruta de cada coletor (proveniência
    # isolada por fonte, ver "Princípios de design" no CLAUDE.md), não pra
    # consumo direto. É este arquivo que deve alimentar o gerador de
    # competências, e mais tarde ser integrado com github.json/linkedin.json.
    saida_path = Path("materiais_moodle/trajetoria_academica.json")

    if not pdf_path.exists():
        print(f"Não achei {pdf_path}. Rode antes: python3 baixar_historico.py", file=sys.stderr)
        sys.exit(1)
    if not consolidado_path.exists():
        print(f"Não achei {consolidado_path}. Rode antes: python3 consolidar.py", file=sys.stderr)
        sys.exit(1)

    linhas = extrair_texto(pdf_path)
    linhas_limpas = limpar_linhas(linhas)
    semestres, nao_estruturado = parse_historico(linhas)
    perfil = extrair_resumo(linhas)
    perfil["dispensas_especificas"] = parse_dispensas(linhas_limpas)
    perfil["creditos_por_tipo_obrigatoriedade"] = parse_creditos_por_tipo(linhas_limpas)

    # index sigla -> registro de histórico (achata os semestres)
    historico_por_sigla = {}
    for sem in semestres:
        for disc in sem["disciplinas"]:
            historico_por_sigla.setdefault(disc["sigla"], []).append(disc)

    disciplinas = json.loads(consolidado_path.read_text(encoding="utf-8"))
    siglas_consolidado = set()
    for d in disciplinas:
        sigla = d.get("sigla_tentada") or (d.get("disciplina") or {}).get("sigla")
        if sigla:
            siglas_consolidado.add(sigla)
        registros = historico_por_sigla.get(sigla, [])
        # mais de um registro (ex.: repetiu a disciplina) — guarda todos, mais
        # recente primeiro, sem decidir por você qual "vale".
        d["historico"] = registros

    nao_casadas = {
        sigla: registros
        for sigla, registros in historico_por_sigla.items()
        if sigla not in siglas_consolidado
    }

    # ordem cronológica (semestre em que foi cursada) — importa pras próximas
    # etapas (currículo/portfólio contam a trajetória em ordem). Usa o
    # primeiro registro de histórico de cada disciplina (já é o mais antigo,
    # porque o histórico é lido do PDF em ordem cronológica); quem não tem
    # nenhum registro casado vai pro fim, sem embaralhar as demais.
    def chave_cronologica(disc):
        historico = disc.get("historico") or []
        if not historico:
            return (9999, 9)
        h = historico[0]
        periodo_num = int(h["periodo"].rstrip("º")) if h.get("periodo") else 9
        return (h.get("ano", 9999), periodo_num)

    disciplinas.sort(key=chave_cronologica)

    perfil["semestres"] = semestres
    saida = {
        "perfil": perfil,
        "disciplinas": disciplinas,
        "disciplinas_no_historico_sem_match_no_consolidado": nao_casadas,
        "linhas_nao_reconhecidas": nao_estruturado,
    }
    saida_path.write_text(json.dumps(saida, ensure_ascii=False, indent=2), encoding="utf-8")

    com_historico = sum(1 for d in disciplinas if d["historico"])
    print(f"{len(disciplinas)} disciplina(s), {com_historico} com "
          f"registro de histórico casado por sigla (ordenadas cronologicamente).")
    print(f"{len(perfil['dispensas_especificas'])} dispensa(s) específica(s) "
          f"encontrada(s) e {'' if perfil['creditos_por_tipo_obrigatoriedade'] else 'NÃO '}"
          f"achei o quadro de créditos por tipo de obrigatoriedade.")
    print(f"{len(nao_casadas)} sigla(s) no histórico sem disciplina correspondente "
          f"no consolidado (normal p/ disciplinas sem harvest do Moodle): "
          f"{sorted(nao_casadas)}")
    if nao_estruturado:
        print(f"{len(nao_estruturado)} linha(s) do PDF não reconhecidas — guardadas em "
              f"'linhas_nao_reconhecidas' pra não perder nada.")
    print(f"\nSalvo: {saida_path}")


if __name__ == "__main__":
    main()

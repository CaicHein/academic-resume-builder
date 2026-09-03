#!/usr/bin/env python3
"""
busca_semantica.py — Módulo compartilhado do "currículo interativo" (RAG).
Diferente dos outros passos (extrair_texto_materiais.py, gerar_embeddings.py,
indexar_materiais.py — scripts batch, um-tiro-só via subprocess), este módulo
é IMPORTADO diretamente por app.py: uma pergunta precisa de resposta rápida,
então o índice (chunks + embeddings) fica cacheado em memória entre
requisições em vez de recarregar do disco a cada pergunta.

Fluxo de responder():
  1. embeda a pergunta (mesmo endpoint Ollama de gerar_embeddings.py)
  2. busca os top-k chunks mais similares (cosseno, força bruta em numpy —
     ver "Perguntas em aberto" em IDEIA_curriculo_interativo.md: dado o
     volume do projeto, ~poucas dezenas de milhares de chunks no máximo,
     não precisa de banco vetorial de verdade)
  3. complementa com dado ESTRUTURADO (nota/situação/período) de
     trajetoria_academica.json pras disciplinas que apareceram nos chunks —
     esse dado já existe estruturado, não precisa de embedding nenhum
  4. chama o LLM (Claude ou Ollama — reusa chamar_claude/chamar_ollama de
     gerar_competencias.py, formato=None pra texto livre) pra sintetizar
     uma resposta em prosa citando disciplina/arquivo

As "fontes" devolvidas pro chamador NÃO vêm do texto que o LLM escreveu —
vêm direto dos chunks recuperados na busca (passo 2), que têm proveniência
real (disciplina/arquivo/origem_url do manifesto). Isso evita citação
inventada pelo modelo: a lista de fontes é sempre fiel ao que foi
efetivamente recuperado, o LLM só escreve o texto explicativo em cima delas.
"""

import json
from pathlib import Path

import numpy as np

from gerar_competencias import (
    ANTHROPIC_MODEL_PADRAO,
    OLLAMA_MODEL_PADRAO,
    chamar_claude,
    chamar_ollama,
)
from gerar_embeddings import embed

INDICE_DIR = Path("indice_semantico")
TRAJETORIA_PATH = Path("materiais_moodle/trajetoria_academica.json")

SYSTEM_PROMPT_PERGUNTA = """\
Você responde perguntas sobre a trajetória acadêmica de um estudante de \
graduação, usando SÓ os trechos de material de disciplina e o histórico \
fornecidos abaixo — nunca invente fato que não apareça neles (mesma regra \
inegociável do resto do sistema). Se os trechos não cobrirem a pergunta, \
diga isso claramente em vez de especular.

Ao responder, cite a disciplina (e o arquivo, quando fizer diferença) de \
onde tirou cada afirmação — não é preciso formatar como lista de \
referências, basta mencionar naturalmente no texto (ex.: "em PMR3409, o \
material de..."). Quando houver nota/situação disponível pra uma \
disciplina relevante, pode usar como contexto de desempenho.
"""

_indice_cache = None


def carregar_indice():
    """Carrega chunks + embeddings uma vez, cacheia em memória (módulo é
    importado por app.py e reusado entre requisições — não recarrega do
    disco a cada pergunta)."""
    global _indice_cache
    if _indice_cache is not None:
        return _indice_cache

    chunks_path = INDICE_DIR / "chunks.jsonl"
    embeddings_path = INDICE_DIR / "embeddings.npy"
    if not chunks_path.exists() or not embeddings_path.exists():
        return None

    chunks = [json.loads(linha) for linha in chunks_path.read_text(encoding="utf-8").splitlines()]
    embeddings = np.load(embeddings_path)
    _indice_cache = {"chunks": chunks, "embeddings": embeddings}
    return _indice_cache


def indice_disponivel():
    return carregar_indice() is not None


def buscar(pergunta, k=8):
    indice = carregar_indice()
    if indice is None:
        raise RuntimeError("Índice semântico não encontrado — rode indexar_materiais.py primeiro.")

    vetor_pergunta = np.array(embed(pergunta), dtype="float32")
    embeddings = indice["embeddings"]

    normas = np.linalg.norm(embeddings, axis=1) * np.linalg.norm(vetor_pergunta)
    normas[normas == 0] = 1e-9  # evita divisão por zero num embedding vazio (não deveria acontecer, mas não derruba a busca)
    scores = (embeddings @ vetor_pergunta) / normas

    top_idx = np.argsort(-scores)[:k]
    return [{**indice["chunks"][i], "score": float(scores[i])} for i in top_idx]


def _disciplinas_por_moodle_nome():
    if not TRAJETORIA_PATH.exists():
        return {}
    dado = json.loads(TRAJETORIA_PATH.read_text(encoding="utf-8"))
    return {d["moodle_nome"]: d for d in dado.get("disciplinas", []) if d.get("moodle_nome")}


def _contexto_estruturado(nomes_disciplinas):
    by_nome = _disciplinas_por_moodle_nome()
    partes = []
    for nome in nomes_disciplinas:
        d = by_nome.get(nome)
        if not d:
            continue
        ementa = (d.get("disciplina") or {}).get("nome_pt", "")
        historico = d.get("historico") or []
        registros = "; ".join(
            f"{h.get('ano')}/{h.get('periodo')}: nota {h.get('nota')}, situação {h.get('situacao')}"
            for h in historico
        )
        partes.append(f"- {nome}" + (f" ({ementa})" if ementa else "") + f" — {registros or 'sem histórico'}")
    return "\n".join(partes)


def _montar_prompt(pergunta, chunks_relevantes):
    nomes_disciplinas = list(dict.fromkeys(c["disciplina"] for c in chunks_relevantes))
    contexto_estruturado = _contexto_estruturado(nomes_disciplinas)

    partes = [f"Pergunta: {pergunta}\n", "=== TRECHOS DE MATERIAL RECUPERADOS ==="]
    for c in chunks_relevantes:
        partes.append(f"\n[{c['disciplina']} — {Path(c['arquivo']).name}]\n{c['texto']}")

    if contexto_estruturado:
        partes.append("\n\n=== HISTÓRICO (nota/situação por disciplina) ===")
        partes.append(contexto_estruturado)

    return "\n".join(partes)


def responder(pergunta, provider="claude", model=None, api_key=None, k=8):
    chunks_relevantes = buscar(pergunta, k=k)
    prompt = _montar_prompt(pergunta, chunks_relevantes)

    if provider == "claude":
        modelo = model or ANTHROPIC_MODEL_PADRAO
        resposta = chamar_claude(SYSTEM_PROMPT_PERGUNTA, prompt, api_key, modelo, None)
    else:
        modelo = model or OLLAMA_MODEL_PADRAO
        resposta = chamar_ollama(SYSTEM_PROMPT_PERGUNTA, prompt, modelo, None)

    fontes = [
        {
            "disciplina": c["disciplina"],
            "arquivo": Path(c["arquivo"]).name,
            "trecho": c["texto"][:280] + ("…" if len(c["texto"]) > 280 else ""),
            "origem_url": c["origem_url"],
            "score": round(c["score"], 3),
        }
        for c in chunks_relevantes
    ]
    return {"resposta": resposta, "fontes": fontes}

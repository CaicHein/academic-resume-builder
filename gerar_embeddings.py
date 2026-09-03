#!/usr/bin/env python3
"""
gerar_embeddings.py — Segundo passo do "currículo interativo" (RAG). Lê
`indice_semantico/chunks.jsonl` (gerado por extrair_texto_materiais.py, sem
rede) e chama o Ollama local pra transformar cada chunk num vetor, salvando
`indice_semantico/embeddings.npy` (linha i = embedding do chunk i do jsonl).

Decisão consciente: embeddings via Ollama local (`nomic-embed-text`), não
Voyage AI (que seria a primeira dependência de API paga além de Claude/
GitHub) — mesma filosofia de dependência mínima do resto do projeto. Chamada
HTTP pura via `urllib`, sem SDK novo (mesmo padrão de chamar_ollama() em
gerar_competencias.py).

CONFIRMADO contra dado real (2026-09-02): esta máquina roda o modelo 100% em
CPU (sem GPU), e uma chamada por chunk (`/api/embeddings`, 1 texto) leva
~3.5s — pra 10 mil chunks, isso são ~10h. O custo por chamada é
majoritariamente overhead fixo, não o tamanho do texto: em lote de 50 textos
por chamada (`/api/embed`, endpoint mais novo, aceita lista em "input"), caiu
pra ~0.3s/item — a mesma carga em ~1h. Por isso os chunks são embedados em
lote, não um por um.

Mesmo em ~1h, o processo já foi interrompido mais de uma vez no meio (a
máquina é a mesma que o usuário precisa usar pra outras coisas). Por isso
salva um checkpoint (`embeddings.parcial.npy`) a cada lote — interromper e
rodar de novo retoma do lote seguinte, não do zero.

--- SETUP ---
    ollama pull nomic-embed-text

--- USO ---
    python3 gerar_embeddings.py

Entrada: indice_semantico/chunks.jsonl
Saída:   indice_semantico/embeddings.npy
"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

try:
    import numpy as np
except ImportError:
    print("numpy não instalado. Rode:\n    pip install numpy", file=sys.stderr)
    sys.exit(1)

OLLAMA_EMBED_URL = "http://localhost:11434/api/embed"
MODELO_EMBEDDING = "nomic-embed-text"
TAMANHO_LOTE = 50


MAX_TENTATIVAS = 3


def embed_lote(textos, model=MODELO_EMBEDDING):
    """CONFIRMADO contra dado real: numa máquina sob carga variável (a mesma
    usada pra outras coisas entre pausas), um lote ocasionalmente passa de
    180s e o timeout de leitura do urllib chega como `TimeoutError` puro, não
    `URLError` — por isso o except cobre os dois. Retry com backoff porque
    isso já aconteceu mais de uma vez nesta sessão; sem isso, uma lentidão
    passageira derruba o processo inteiro (o checkpoint salva o já feito, mas
    ainda exige alguém notar e rodar de novo)."""
    corpo = {"model": model, "input": textos}
    ultimo_erro = None
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        req = urllib.request.Request(
            OLLAMA_EMBED_URL,
            data=json.dumps(corpo).encode("utf-8"),
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                resposta = json.loads(resp.read().decode("utf-8"))
            vetores = resposta.get("embeddings")
            if not vetores:
                raise RuntimeError(f"Resposta do Ollama sem embeddings: {resposta}")
            return vetores
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            ultimo_erro = e
            print(f"    ! tentativa {tentativa}/{MAX_TENTATIVAS} falhou ({e}) — "
                  f"{'tentando de novo...' if tentativa < MAX_TENTATIVAS else 'desistindo.'}",
                  file=sys.stderr)
            if tentativa < MAX_TENTATIVAS:
                time.sleep(5 * tentativa)

    print(f"Não consegui falar com o Ollama em {OLLAMA_EMBED_URL} depois de "
          f"{MAX_TENTATIVAS} tentativas — confirme que `ollama serve` está rodando "
          f"e que o modelo '{model}' foi baixado (`ollama pull {model}`).", file=sys.stderr)
    raise RuntimeError(f"Falha de conexão com Ollama: {ultimo_erro}") from ultimo_erro


def embed(texto, model=MODELO_EMBEDDING):
    """Embeda um texto só — usado por busca_semantica.py pra embedar a
    pergunta do usuário (1 de cada vez, não é o gargalo de volume)."""
    return embed_lote([texto], model=model)[0]


def main():
    chunks_path = Path("indice_semantico/chunks.jsonl")
    if not chunks_path.exists():
        print("indice_semantico/chunks.jsonl não encontrado. Rode "
              "extrair_texto_materiais.py primeiro.", file=sys.stderr)
        sys.exit(1)

    linhas = chunks_path.read_text(encoding="utf-8").splitlines()
    chunks = [json.loads(linha) for linha in linhas]
    print(f"{len(chunks)} chunk(s) pra gerar embedding (modelo: {MODELO_EMBEDDING}, "
          f"lote de {TAMANHO_LOTE}).")

    out_path = Path("indice_semantico/embeddings.npy")
    parcial_path = Path("indice_semantico/embeddings.parcial.npy")

    vetores = []
    if parcial_path.exists():
        parcial = np.load(parcial_path)
        if parcial.shape[0] <= len(chunks):
            vetores = parcial.tolist()
            print(f"Retomando checkpoint: {len(vetores)} embedding(s) já feito(s) "
                  f"({parcial_path}).")
        else:
            print(f"Checkpoint {parcial_path} não bate com {chunks_path} atual "
                  f"(mais linhas que chunks) — ignorando, começando do zero.")

    inicio = time.time()
    for i in range(len(vetores), len(chunks), TAMANHO_LOTE):
        lote = chunks[i:i + TAMANHO_LOTE]
        vetores.extend(embed_lote([c["texto"] for c in lote]))
        feitos = min(i + TAMANHO_LOTE, len(chunks))
        decorrido = time.time() - inicio
        print(f"  {feitos}/{len(chunks)} embeddings ({decorrido:.0f}s)")
        np.save(parcial_path, np.array(vetores, dtype="float32"))

    matriz = np.array(vetores, dtype="float32")
    np.save(out_path, matriz)
    parcial_path.unlink(missing_ok=True)

    print(f"\n=== Pronto ===")
    print(f"{matriz.shape[0]} embedding(s) de dimensão {matriz.shape[1]} — salvo em {out_path}")


if __name__ == "__main__":
    main()

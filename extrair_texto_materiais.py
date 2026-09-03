#!/usr/bin/env python3
"""
extrair_texto_materiais.py — Primeiro passo do "currículo interativo" (RAG
sobre os materiais reais das disciplinas — ver IDEIA_curriculo_interativo.md).
Sem chamada de rede: lê `materiais_moodle/manifesto.json` (gerado por
harvester_moodle.py), extrai texto de cada arquivo suportado e quebra em
chunks com proveniência, pra depois `gerar_embeddings.py` (que aí sim chama
o Ollama) transformar em vetores buscáveis.

Escopo v1 (decisão consciente pra não adicionar dependência nova de parsing
de documento): PDF (`pdfplumber`, já é dependência do projeto) + arquivos de
código/texto puro (.py/.ipynb/.m/.c/.mod/.json/.xml/.csv). Slides (.pptx) e
Word (.docx) ficam de fora por enquanto — cobrem ~16% dos arquivos baixados,
registrados em `nao_indexados.json` com o motivo, não perdidos, só adiados.

Cada chunk carrega a mesma proveniência do manifesto: disciplina, arquivo,
origem_url — o mesmo princípio do resto do projeto (ver CLAUDE.md, princípio 1).

--- USO ---
    python3 extrair_texto_materiais.py

Entrada: materiais_moodle/manifesto.json
Saída:
    indice_semantico/chunks.jsonl       (1 objeto por linha, sem vetor ainda)
    indice_semantico/nao_indexados.json (o que foi pulado e por quê)
"""

import json
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

EXTENSOES_TEXTO_PURO = {".py", ".m", ".c", ".mod", ".json", ".xml", ".csv"}
TAMANHO_ALVO_CHUNK = 1000   # chars — parágrafos são agrupados até chegar perto disso
TAMANHO_MAX_CHUNK = 1600    # acima disso, um parágrafo isolado é quebrado à força

# Confirmado contra dado real: professores às vezes anexam livro-texto/handbook
# inteiro como material de apoio (ex.: um handbook de engenharia gerou 5.608
# chunks sozinho — mais que o resto do curso somado). Isso domina tempo de
# indexação e dilui a busca com conteúdo genérico de bibliografia, não sobre o
# trabalho do aluno — então um arquivo que passaria desse limite é excluído
# inteiro (não truncado, pra não indexar um pedaço arbitrário e enganoso) e
# registrado em nao_indexados.json.
LIMITE_CHUNKS_POR_ARQUIVO = 150

# CONFIRMADO contra dado real (2026-09-02): o limite de chunks acima só
# descarta o resultado — ainda paga o custo de abrir o PDF inteiro com
# pdfplumber antes de poder contar os chunks. Um handbook de 49MB (diagramas
# vetoriais de metalurgia) ficou mais de 3h nisso, memória subindo até quase
# 4GB, sem sinal de terminar — travamento real, não só lentidão (outro
# handbook de 62MB, no mesmo lote, levou só uns 29min: tamanho de arquivo não
# prediz tempo linearmente quando tem conteúdo vetorial complexo). Por isso
# um PDF acima deste tamanho nem chega a ser aberto — pulado direto, sem
# pagar o custo de extração pra só descartar depois.
TAMANHO_MAX_PDF_BYTES = 10 * 1024 * 1024  # 10 MB


def extrair_texto_pdf(caminho):
    with pdfplumber.open(caminho) as pdf:
        paginas = [p.extract_text() or "" for p in pdf.pages]
    return "\n\n".join(paginas)


def extrair_texto_ipynb(caminho):
    dado = json.loads(Path(caminho).read_text(encoding="utf-8", errors="replace"))
    partes = []
    for celula in dado.get("cells", []):
        if celula.get("cell_type") not in ("code", "markdown"):
            continue
        fonte = celula.get("source", "")
        texto = "".join(fonte) if isinstance(fonte, list) else str(fonte)
        if texto.strip():
            partes.append(texto)
    return "\n\n".join(partes)


def extrair_texto(caminho):
    ext = Path(caminho).suffix.lower()
    if ext == ".pdf":
        return extrair_texto_pdf(caminho)
    if ext == ".ipynb":
        return extrair_texto_ipynb(caminho)
    if ext in EXTENSOES_TEXTO_PURO:
        return Path(caminho).read_text(encoding="utf-8", errors="replace")
    return None  # extensão não suportada


def dividir_em_chunks(texto):
    """Agrupa parágrafos (separados por linha em branco) até ~TAMANHO_ALVO_CHUNK
    chars; um parágrafo sozinho maior que TAMANHO_MAX_CHUNK é quebrado à força
    por linha. Sem overlap sofisticado — v1 simples, dá pra refinar depois se
    a qualidade de busca pedir."""
    paragrafos = [p.strip() for p in texto.split("\n\n") if p.strip()]
    chunks = []
    atual = ""
    for p in paragrafos:
        if len(p) > TAMANHO_MAX_CHUNK:
            if atual:
                chunks.append(atual)
                atual = ""
            linhas = p.split("\n")
            bloco = ""
            for linha in linhas:
                if len(bloco) + len(linha) + 1 > TAMANHO_MAX_CHUNK and bloco:
                    chunks.append(bloco)
                    bloco = linha
                else:
                    bloco = f"{bloco}\n{linha}" if bloco else linha
            if bloco:
                chunks.append(bloco)
            continue
        candidato = f"{atual}\n\n{p}" if atual else p
        if len(candidato) > TAMANHO_ALVO_CHUNK and atual:
            chunks.append(atual)
            atual = p
        else:
            atual = candidato
    if atual:
        chunks.append(atual)
    return chunks


def main():
    manifesto_path = Path("materiais_moodle/manifesto.json")
    if not manifesto_path.exists():
        print("materiais_moodle/manifesto.json não encontrado. Rode "
              "harvester_moodle.py primeiro (não --list-only).", file=sys.stderr)
        sys.exit(1)

    manifesto = json.loads(manifesto_path.read_text(encoding="utf-8"))
    print(f"{len(manifesto)} arquivo(s) no manifesto.")

    chunks_saida = []
    nao_indexados = []
    chunk_id = 0

    for idx, entrada in enumerate(manifesto, 1):
        caminho = entrada["arquivo"]
        print(f"[{idx}/{len(manifesto)}] {Path(caminho).name}...")
        if not Path(caminho).exists():
            nao_indexados.append({"arquivo": caminho, "motivo": "arquivo não encontrado em disco"})
            continue
        tamanho = Path(caminho).stat().st_size
        if Path(caminho).suffix.lower() == ".pdf" and tamanho > TAMANHO_MAX_PDF_BYTES:
            nao_indexados.append({
                "arquivo": caminho,
                "motivo": f"PDF de {tamanho / 1e6:.0f}MB, acima do limite de "
                          f"{TAMANHO_MAX_PDF_BYTES / 1e6:.0f}MB (evita abrir PDF gigante/"
                          f"complexo demais — provável handbook/livro de referência)",
            })
            continue
        try:
            texto = extrair_texto(caminho)
        except Exception as e:
            nao_indexados.append({"arquivo": caminho, "motivo": f"falha na extração: {e}"})
            continue
        if texto is None:
            nao_indexados.append({
                "arquivo": caminho,
                "motivo": f"extensão '{Path(caminho).suffix}' fora do escopo v1 (só PDF + código/texto)",
            })
            continue
        if not texto.strip():
            nao_indexados.append({"arquivo": caminho, "motivo": "sem texto extraível (PDF escaneado/imagem?)"})
            continue

        pedacos = dividir_em_chunks(texto)
        if len(pedacos) > LIMITE_CHUNKS_POR_ARQUIVO:
            nao_indexados.append({
                "arquivo": caminho,
                "motivo": f"arquivo grande demais ({len(pedacos)} chunks estimados, limite "
                          f"{LIMITE_CHUNKS_POR_ARQUIVO}) — provável livro-texto/handbook de "
                          f"referência, não conteúdo específico da disciplina",
            })
            continue

        for i, pedaco in enumerate(pedacos):
            chunks_saida.append({
                "id": chunk_id,
                "disciplina": entrada["disciplina"],
                "arquivo": caminho,
                "chunk_index": i,
                "texto": pedaco,
                "origem_url": entrada["origem_url"],
            })
            chunk_id += 1
        print(f"  ✔ {Path(caminho).name} — {len(pedacos)} chunk(s)")

    out_dir = Path("indice_semantico")
    out_dir.mkdir(parents=True, exist_ok=True)

    chunks_path = out_dir / "chunks.jsonl"
    with chunks_path.open("w", encoding="utf-8") as f:
        for c in chunks_saida:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    nao_indexados_path = out_dir / "nao_indexados.json"
    nao_indexados_path.write_text(json.dumps(nao_indexados, ensure_ascii=False, indent=2), encoding="utf-8")

    n_arquivos_ok = len({c["arquivo"] for c in chunks_saida})
    print(f"\n=== Pronto ===")
    print(f"{len(chunks_saida)} chunk(s) de {n_arquivos_ok} arquivo(s) — salvo em {chunks_path}")
    print(f"{len(nao_indexados)} arquivo(s) fora do escopo v1 — detalhe em {nao_indexados_path}")


if __name__ == "__main__":
    main()

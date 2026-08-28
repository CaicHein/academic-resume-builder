#!/usr/bin/env python3
"""
gerar_competencias.py — Sintetiza tudo que já foi coletado (trajetória
acadêmica + GitHub + informações adicionais em texto livre) num currículo
estruturado, via LLM (API da Claude, chamada HTTP direta — sem SDK, mesmo
padrão stdlib-only de coletar_github.py/jupiter_disciplinas.py).

Regra inegociável: o modelo só pode preencher com fatos que aparecem nos
dados de entrada. Se não há experiência profissional real (comum pra quem
ainda está na graduação), a seção sai vazia — nunca inventada. Cada bullet de
experiência/projeto carrega uma "fonte" (proveniência), na mesma lógica do
resto do projeto (ver CLAUDE.md, princípio 1).

Não gera o .tex — isso é renderizar_curriculo.py, sem chamada de rede. Este
script só produz o JSON estruturado intermediário.

--- SETUP ---
    .env na raiz do projeto:
        ANTHROPIC_API_KEY=sk-ant-...

--- USO ---
    python3 gerar_competencias.py

Entrada (todas opcionais, mas precisa de pelo menos uma):
    materiais_moodle/trajetoria_academica.json
    dados_github/github.json
    dados_extra/informacoes_adicionais.json

Saída: dados_extra/competencias.json
"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from coletar_github import carregar_env

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = "claude-opus-5"

ESQUEMA_COMPETENCIAS = {
    "type": "object",
    "properties": {
        "contato": {
            "type": "object",
            "properties": {
                "nome": {"type": ["string", "null"]},
                "email": {"type": ["string", "null"]},
                "telefone": {"type": ["string", "null"]},
                "cidade_estado": {"type": ["string", "null"]},
                "linkedin_url": {"type": ["string", "null"]},
                "github_url": {"type": ["string", "null"]},
            },
            "required": ["nome", "email", "telefone", "cidade_estado", "linkedin_url", "github_url"],
            "additionalProperties": False,
        },
        "resumo": {"type": ["string", "null"]},
        "habilidades_tecnicas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "categoria": {"type": "string"},
                    "itens": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["categoria", "itens"],
                "additionalProperties": False,
            },
        },
        "experiencia_profissional": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "instituicao": {"type": "string"},
                    "cargo": {"type": "string"},
                    "local": {"type": ["string", "null"]},
                    "periodo": {"type": "string"},
                    "bullets": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "texto": {"type": "string"},
                                "fonte": {"type": ["string", "null"]},
                            },
                            "required": ["texto", "fonte"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["instituicao", "cargo", "local", "periodo", "bullets"],
                "additionalProperties": False,
            },
        },
        "projetos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "nome": {"type": "string"},
                    "url": {"type": ["string", "null"]},
                    "descricao": {"type": "string"},
                    "fonte": {"type": ["string", "null"]},
                },
                "required": ["nome", "url", "descricao", "fonte"],
                "additionalProperties": False,
            },
        },
        "formacao_academica": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "instituicao": {"type": "string"},
                    "curso": {"type": "string"},
                    "local": {"type": ["string", "null"]},
                    "periodo": {"type": "string"},
                },
                "required": ["instituicao", "curso", "local", "periodo"],
                "additionalProperties": False,
            },
        },
        "certificacoes": {"type": "array", "items": {"type": "string"}},
        "idiomas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "idioma": {"type": "string"},
                    "nivel": {"type": "string"},
                },
                "required": ["idioma", "nivel"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "contato", "resumo", "habilidades_tecnicas", "experiencia_profissional",
        "projetos", "formacao_academica", "certificacoes", "idiomas",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """\
Você monta currículos em português (Brasil) pra estudantes de graduação em \
tecnologia, no mesmo tom e estrutura de um currículo profissional enxuto: \
bullets diretos, cada um combinando tecnologia/ação com resultado concreto \
quando o dado permitir. Seções típicas: Resumo, Habilidades Técnicas, \
Experiência Profissional, Projetos, Formação Acadêmica, Certificações, \
Idiomas.

Regra inegociável, mais importante que parecer completo: só preencha com \
fatos que aparecem literalmente nos dados fornecidos (trajetória acadêmica, \
repositórios do GitHub, texto livre de "informações adicionais"). Nunca \
invente empresa, cargo, tecnologia, certificação ou experiência que não \
esteja nos dados. Se não houver nenhum dado real de experiência \
profissional — comum pra quem ainda está cursando —, devolva \
"experiencia_profissional" como lista vazia. O mesmo vale pra qualquer outra \
seção sem dado real: lista vazia, nunca um item fabricado.

Proveniência: todo bullet de "experiencia_profissional" e todo item de \
"projetos" carrega um campo "fonte" — uma referência curta a de onde veio \
(ex.: "disciplina SCC0201", "repositório joaquimrafael/API-Store", "texto \
livre do usuário"). Isso é parte do valor do currículo, não um detalhe \
opcional.

Diferencial pedido: quando fizer sentido, conecte nota a contexto usando \
"perfil.semestres" da trajetória acadêmica — por exemplo, se o aluno manteve \
a média cursando várias disciplinas pesadas no mesmo semestre, isso é um \
ponto forte real pro currículo (mais forte que só listar a disciplina). Não \
force essa conexão onde não há dado que a sustente.

O campo "contato" só deve ser preenchido com dado que realmente aparece nos \
dados de entrada (nome do aluno, e-mail/localização públicos do GitHub, \
telefone só se o usuário tiver digitado em informações adicionais) — deixe \
null o que não tiver fonte real.
"""


def ler_json_seguro(caminho):
    p = Path(caminho)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"! Não consegui ler {caminho}: {e}", file=sys.stderr)
        return None


def ler_texto_extra(caminho):
    d = ler_json_seguro(caminho)
    if not d:
        return ""
    return d.get("texto", "") or ""


def montar_mensagem_usuario(trajetoria, github, texto_extra):
    partes = ["Gere o currículo estruturado a partir dos dados abaixo.\n"]

    if trajetoria:
        partes.append("=== TRAJETÓRIA ACADÊMICA (Jupiter + Moodle + histórico escolar) ===")
        partes.append(json.dumps(trajetoria, ensure_ascii=False))
    else:
        partes.append("=== TRAJETÓRIA ACADÊMICA === (não coletada ainda)")

    if github:
        partes.append("\n=== GITHUB (perfil + repositórios) ===")
        partes.append(json.dumps(github, ensure_ascii=False))
    else:
        partes.append("\n=== GITHUB === (não coletado ainda)")

    partes.append("\n=== INFORMAÇÕES ADICIONAIS (texto livre do usuário) ===")
    partes.append(texto_extra if texto_extra else "(vazio)")

    return "\n".join(partes)


def chamar_claude(system_text, user_content, api_key):
    corpo = {
        "model": MODEL,
        "max_tokens": 16000,
        "system": [{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user_content}],
        "output_config": {
            "effort": "high",
            "format": {"type": "json_schema", "schema": ESQUEMA_COMPETENCIAS},
        },
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(corpo).encode("utf-8"),
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            resposta = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detalhe = e.read().decode("utf-8", errors="replace")
        if e.code == 401:
            print("ANTHROPIC_API_KEY inválida ou ausente.", file=sys.stderr)
        elif e.code == 429:
            print(f"Rate limit da API da Claude atingido. Retry-After: "
                  f"{e.headers.get('retry-after', '?')}s", file=sys.stderr)
        print(f"Detalhe: {detalhe}", file=sys.stderr)
        raise

    bloco_texto = next((b["text"] for b in resposta.get("content", []) if b.get("type") == "text"), None)
    if bloco_texto is None:
        raise RuntimeError(f"Resposta sem bloco de texto: {resposta}")
    return json.loads(bloco_texto)


def main():
    env = carregar_env()
    api_key = env.get("ANTHROPIC_API_KEY") or ""
    if not api_key:
        print("Falta ANTHROPIC_API_KEY no .env. Veja o cabeçalho deste script "
              "pro formato esperado.", file=sys.stderr)
        sys.exit(1)

    trajetoria = ler_json_seguro("materiais_moodle/trajetoria_academica.json")
    github = ler_json_seguro("dados_github/github.json")
    texto_extra = ler_texto_extra("dados_extra/informacoes_adicionais.json")

    if not trajetoria and not github and not texto_extra:
        print("Nenhuma fonte de dado encontrada (trajetória acadêmica, GitHub "
              "ou informações adicionais). Rode os coletores primeiro.", file=sys.stderr)
        sys.exit(1)

    print("Fontes disponíveis:",
          f"trajetória acadêmica: {'sim' if trajetoria else 'não'},",
          f"GitHub: {'sim' if github else 'não'},",
          f"informações adicionais: {'sim' if texto_extra else 'não'}")

    mensagem = montar_mensagem_usuario(trajetoria, github, texto_extra)

    print(f"Chamando a API da Claude ({MODEL})... pode demorar um pouco "
          f"(entrada grande + raciocínio).")
    inicio = time.time()
    competencias = chamar_claude(SYSTEM_PROMPT, mensagem, api_key)
    print(f"Resposta recebida em {time.time() - inicio:.1f}s.")

    out_dir = Path("dados_extra")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "competencias.json"
    out_path.write_text(json.dumps(competencias, ensure_ascii=False, indent=2), encoding="utf-8")

    n_exp = len(competencias.get("experiencia_profissional", []))
    n_proj = len(competencias.get("projetos", []))
    print(f"\n=== Pronto ===")
    print(f"{n_exp} experiência(s) profissional(is), {n_proj} projeto(s) — salvo em {out_path}")


if __name__ == "__main__":
    main()

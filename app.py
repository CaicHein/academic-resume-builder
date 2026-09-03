#!/usr/bin/env python3
"""
app.py — Painel de controle local (servidor Flask, SÓ na sua máquina, não
exposto à internet) pra disparar os coletores e visualizar os dados
coletados, sem precisar ficar no terminal.

Não reimplementa nenhuma lógica de coleta — só orquestra os scripts que já
existem, como subprocessos (inclusive os que abrem uma janela de navegador
pra você logar manualmente no Moodle/Jupiter — isso continua exatamente
igual, só que disparado por um clique em vez de um comando).

Nada aqui é obrigatório: a aba de visualização nunca trava por causa de uma
fonte que ainda não foi coletada — mostra "ainda não coletado" e segue.

--- USO ---
    python3 app.py
Abre http://127.0.0.1:5000 no navegador.
"""

import json
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from coletar_github import carregar_env
import busca_semantica

BASE_DIR = Path(__file__).parent
PYTHON = sys.executable
ENV_PATH = BASE_DIR / ".env"

app = Flask(__name__, static_folder="static", static_url_path="")

# tarefas disparáveis pela interface: cada uma roda um ORQUESTRADOR (não o
# script individual) que encadeia vários passos como subprocessos, um após o
# outro, parando no primeiro que falhar. Os scripts individuais continuam
# existindo e são rodáveis por terminal pra debugar/recalibrar um passo
# específico (ex.: sigla não encontrada no Jupiter) — só não aparecem mais
# como botão separado aqui, pra manter a interface simples.
TAREFAS = {
    "moodle": {
        "rotulo": "Moodle — coletar tudo",
        "comando": [PYTHON, "coletar_moodle.py"],
        "descricao": "Lista disciplinas + extrai notas/entregas. Abre uma janela pra logar no e-Disciplinas se precisar. Não baixa arquivos/materiais ainda (não validado).",
    },
    "jupiter_historico": {
        "rotulo": "Jupiter + Histórico — coletar tudo",
        "comando": [PYTHON, "coletar_jupiter_historico.py"],
        "descricao": "Ementas + consolidação + PDF do histórico + trajetória acadêmica final. Precisa do Moodle já coletado. Abre uma janela pra logar no Jupiter (login próprio, diferente do Moodle).",
    },
    "github": {
        "rotulo": "GitHub — coletar",
        "comando": [PYTHON, "coletar_github.py"],
        "descricao": "Busca perfil e repositórios via API oficial do GitHub. Precisa de GITHUB_TOKEN/GITHUB_USERNAME no .env.",
    },
    "curriculo": {
        "rotulo": "Currículo — gerar (LLM + .tex)",
        "comando": [PYTHON, "gerar_curriculo_completo.py"],
        "descricao": "Sintetiza competências via LLM e já monta o .tex. Precisa de pelo menos uma fonte coletada. Provider \"Claude\" precisa de ANTHROPIC_API_KEY (configura acima) e é uma chamada paga; provider \"Ollama\" roda local e de graça, mas precisa do Ollama instalado e do modelo já baixado (`ollama pull <modelo>`), e é bem menos confiável seguindo a regra de não inventar dado — serve pra testar o pipeline.",
    },
    "indexar": {
        "rotulo": "Currículo interativo — indexar materiais",
        "comando": [PYTHON, "indexar_materiais.py"],
        "descricao": "Extrai texto dos materiais baixados (PDF + código/texto, v1) e gera embeddings via Ollama local, pra habilitar a aba \"Currículo interativo\". Precisa de materiais_moodle/manifesto.json (rode \"Moodle\" com download completo, sem --list-only — ver harvester_moodle.py) e do Ollama rodando com `nomic-embed-text` baixado.",
    },
}

_tarefas_estado = {}
_lock = threading.Lock()


def _rodar_em_thread(task_id, comando):
    estado = _tarefas_estado[task_id]
    try:
        processo = subprocess.Popen(
            comando,
            cwd=str(BASE_DIR),
            stdin=subprocess.DEVNULL,  # crítico: sem isso, um script que cair no
            # fallback de "tecle Enter" ficaria esperando input que nunca chega
            # pela interface web (stdin herdaria o terminal do app.py, não o browser).
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        estado["processo"] = processo
        for linha in processo.stdout:
            with _lock:
                estado["log"].append(linha.rstrip("\n"))
        processo.wait()
        with _lock:
            estado["status"] = "concluido" if processo.returncode == 0 else "erro"
            estado["returncode"] = processo.returncode
    except Exception as e:
        with _lock:
            estado["status"] = "erro"
            estado["log"].append(f"! Falha ao iniciar: {e}")


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/tarefas", methods=["GET"])
def listar_tarefas():
    return jsonify({k: {"rotulo": v["rotulo"], "descricao": v["descricao"]} for k, v in TAREFAS.items()})


@app.route("/api/executar/<script_id>", methods=["POST"])
def executar(script_id):
    if script_id not in TAREFAS:
        return jsonify({"erro": "tarefa desconhecida"}), 404

    comando = list(TAREFAS[script_id]["comando"])
    if script_id == "curriculo":
        # única tarefa com opções: escolha de provider do LLM (Claude por
        # padrão, ou Ollama local pra testar sem custo/chave — ver
        # gerar_competencias.py). Repassado como argv pro orquestrador, que
        # por sua vez repassa só pro passo de geração de competências.
        corpo = request.get_json(silent=True) or {}
        provider = (corpo.get("provider") or "claude").strip()
        if provider not in ("claude", "ollama"):
            return jsonify({"erro": "provider inválido"}), 400
        comando += ["--provider", provider]
        modelo = (corpo.get("model") or "").strip()
        if modelo:
            comando += ["--model", modelo]

    with _lock:
        em_andamento = [
            tid for tid, st in _tarefas_estado.items()
            if st["script_id"] == script_id and st["status"] == "rodando"
        ]
        if em_andamento:
            return jsonify({"erro": "já rodando", "task_id": em_andamento[0]}), 409

        task_id = str(uuid.uuid4())
        _tarefas_estado[task_id] = {
            "script_id": script_id,
            "rotulo": TAREFAS[script_id]["rotulo"],
            "status": "rodando",
            "log": [],
            "processo": None,
            "returncode": None,
            "iniciado_em": time.time(),
        }

    thread = threading.Thread(
        target=_rodar_em_thread, args=(task_id, comando), daemon=True
    )
    thread.start()
    return jsonify({"task_id": task_id})


@app.route("/api/tarefa/<task_id>", methods=["GET"])
def status_tarefa(task_id):
    estado = _tarefas_estado.get(task_id)
    if not estado:
        return jsonify({"erro": "tarefa não encontrada"}), 404
    with _lock:
        return jsonify({
            "rotulo": estado["rotulo"],
            "status": estado["status"],
            "log": estado["log"],
            "returncode": estado["returncode"],
        })


@app.route("/api/parar/<task_id>", methods=["POST"])
def parar_tarefa(task_id):
    estado = _tarefas_estado.get(task_id)
    if not estado or not estado.get("processo"):
        return jsonify({"erro": "tarefa não encontrada ou já terminou"}), 404
    estado["processo"].terminate()
    return jsonify({"ok": True})


# --- dados coletados (leitura, sempre tolerante a arquivo ausente) ---

def _ler_json_seguro(caminho):
    p = BASE_DIR / caminho
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return {"_erro_leitura": str(e)}


@app.route("/api/dados/status", methods=["GET"])
def dados_status():
    def info(caminho):
        p = BASE_DIR / caminho
        if not p.exists():
            return {"existe": False}
        return {"existe": True, "tamanho_bytes": p.stat().st_size, "modificado_em": p.stat().st_mtime}

    linkedin_dir = BASE_DIR / "dados_linkedin"
    n_arquivos_linkedin = len(list(linkedin_dir.iterdir())) if linkedin_dir.exists() else 0

    return jsonify({
        "trajetoria_academica": info("materiais_moodle/trajetoria_academica.json"),
        "notas": info("materiais_moodle/notas.json"),
        "jupiter_disciplinas": info("materiais_moodle/jupiter_disciplinas.json"),
        "historico_pdf": info("materiais_moodle/historico_escolar.pdf"),
        "github": info("dados_github/github.json"),
        "linkedin": {"existe": n_arquivos_linkedin > 0, "quantidade_arquivos": n_arquivos_linkedin},
        "informacoes_adicionais": info("dados_extra/informacoes_adicionais.json"),
        "competencias": info("dados_extra/competencias.json"),
        "curriculo_tex": info("dados_extra/curriculo.tex"),
        "indice_semantico": info("indice_semantico/embeddings.npy"),
    })


@app.route("/api/dados/indice-status", methods=["GET"])
def dados_indice_status():
    chunks_path = BASE_DIR / "indice_semantico" / "chunks.jsonl"
    embeddings_path = BASE_DIR / "indice_semantico" / "embeddings.npy"
    if not chunks_path.exists() or not embeddings_path.exists():
        return jsonify({"disponivel": False})

    disciplinas = set()
    n_chunks = 0
    for linha in chunks_path.read_text(encoding="utf-8").splitlines():
        n_chunks += 1
        disciplinas.add(json.loads(linha)["disciplina"])

    return jsonify({
        "disponivel": True,
        "n_chunks": n_chunks,
        "n_disciplinas": len(disciplinas),
        "modificado_em": embeddings_path.stat().st_mtime,
    })


@app.route("/api/perguntar", methods=["POST"])
def perguntar():
    corpo = request.get_json(silent=True) or {}
    pergunta = (corpo.get("pergunta") or "").strip()
    if not pergunta:
        return jsonify({"erro": "pergunta vazia"}), 400

    provider = (corpo.get("provider") or "claude").strip()
    if provider not in ("claude", "ollama"):
        return jsonify({"erro": "provider inválido"}), 400
    modelo = (corpo.get("model") or "").strip() or None

    if not busca_semantica.indice_disponivel():
        return jsonify({"erro": "Índice semântico não encontrado — rode "
                                 "\"Currículo interativo — indexar materiais\" primeiro."}), 409

    api_key = None
    if provider == "claude":
        env = carregar_env(str(ENV_PATH))
        api_key = env.get("ANTHROPIC_API_KEY") or ""
        if not api_key:
            return jsonify({"erro": "ANTHROPIC_API_KEY não configurada."}), 400

    try:
        resultado = busca_semantica.responder(pergunta, provider=provider, model=modelo, api_key=api_key)
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

    return jsonify(resultado)


@app.route("/api/dados/trajetoria", methods=["GET"])
def dados_trajetoria():
    d = _ler_json_seguro("materiais_moodle/trajetoria_academica.json")
    return jsonify(d if d is not None else {"disponivel": False})


@app.route("/api/dados/github", methods=["GET"])
def dados_github():
    d = _ler_json_seguro("dados_github/github.json")
    return jsonify(d if d is not None else {"disponivel": False})


# --- LinkedIn: upload manual (sem scraping — ver CLAUDE.md) ---

@app.route("/api/upload/linkedin", methods=["POST"])
def upload_linkedin():
    if "arquivo" not in request.files:
        return jsonify({"erro": "nenhum arquivo enviado"}), 400
    arquivo = request.files["arquivo"]
    if not arquivo.filename:
        return jsonify({"erro": "nome de arquivo vazio"}), 400

    destino_dir = BASE_DIR / "dados_linkedin"
    destino_dir.mkdir(parents=True, exist_ok=True)
    nome_seguro = Path(arquivo.filename).name  # descarta qualquer path embutido
    destino = destino_dir / nome_seguro
    arquivo.save(destino)
    return jsonify({"ok": True, "salvo_em": str(destino.relative_to(BASE_DIR))})


@app.route("/api/dados/linkedin/arquivos", methods=["GET"])
def linkedin_arquivos():
    destino_dir = BASE_DIR / "dados_linkedin"
    if not destino_dir.exists():
        return jsonify({"arquivos": []})
    arquivos = [
        {"nome": p.name, "tamanho_bytes": p.stat().st_size}
        for p in destino_dir.iterdir() if p.is_file()
    ]
    return jsonify({"arquivos": arquivos})


# --- configuração: chave da API da Claude, guardada no .env local ---

def _atualizar_env(chave, valor):
    linhas = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    encontrada = False
    novas_linhas = []
    for linha in linhas:
        if linha.strip().startswith(f"{chave}="):
            novas_linhas.append(f"{chave}={valor}")
            encontrada = True
        else:
            novas_linhas.append(linha)
    if not encontrada:
        novas_linhas.append(f"{chave}={valor}")
    ENV_PATH.write_text("\n".join(novas_linhas) + "\n", encoding="utf-8")


@app.route("/api/configuracao/anthropic-key", methods=["GET"])
def obter_status_anthropic_key():
    env = carregar_env(str(ENV_PATH))
    return jsonify({"configurada": bool(env.get("ANTHROPIC_API_KEY"))})


@app.route("/api/configuracao/anthropic-key", methods=["POST"])
def salvar_anthropic_key():
    corpo = request.get_json(silent=True) or {}
    chave = (corpo.get("chave") or "").strip()
    _atualizar_env("ANTHROPIC_API_KEY", chave)
    return jsonify({"ok": True, "configurada": bool(chave)})


# --- informações adicionais: texto livre, sempre opcional ---

@app.route("/api/informacoes-adicionais", methods=["GET"])
def obter_info_adicional():
    d = _ler_json_seguro("dados_extra/informacoes_adicionais.json")
    return jsonify(d if d is not None else {"texto": ""})


@app.route("/api/informacoes-adicionais", methods=["POST"])
def salvar_info_adicional():
    corpo = request.get_json(silent=True) or {}
    destino_dir = BASE_DIR / "dados_extra"
    destino_dir.mkdir(parents=True, exist_ok=True)
    destino = destino_dir / "informacoes_adicionais.json"
    destino.write_text(
        json.dumps({"texto": corpo.get("texto", "")}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return jsonify({"ok": True})


if __name__ == "__main__":
    print("Painel em http://127.0.0.1:5000  (Ctrl+C pra parar)")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)

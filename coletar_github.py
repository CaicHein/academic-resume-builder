#!/usr/bin/env python3
"""
coletar_github.py — Coleta o perfil e os repositórios do GitHub via API REST
oficial (não é scraping: é o jeito sancionado de acessar esses dados,
diferente do LinkedIn — ver CLAUDE.md).

Usa um Personal Access Token (PAT) que o usuário mesmo gera em
github.com/settings/personal-access-tokens/new (fine-grained, só leitura) e
planta em `.env` (nunca no código — `.env` está no `.gitignore`).

Pra cada repositório: descrição, linguagens (bytes por linguagem, não só a
"principal"), tópicos, estrelas, datas, e o README (decodificado) — é
matéria-prima de projeto real pro gerador de competências mais tarde, não só
metadado.

--- SETUP ---
    .env na raiz do projeto:
        GITHUB_TOKEN=github_pat_...
        GITHUB_USERNAME=seu_usuario

--- USO ---
    python3 coletar_github.py

Saída: dados_github/github.json
"""

import json
import sys
import time
import urllib.error
import urllib.request
from base64 import b64decode
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

API = "https://api.github.com"
PAUSA = 0.3  # cortesia entre requisições, mesmo a API sendo feita pra isso


def carregar_env(caminho=".env"):
    env = {}
    p = Path(caminho)
    if not p.exists():
        return env
    for linha in p.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        env[chave.strip()] = valor.strip()
    return env


def chamar_api(caminho, token):
    url = caminho if caminho.startswith("http") else f"{API}{caminho}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "harvester-curriculo/1.0 (uso pessoal)",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            corpo = resp.read()
            headers = dict(resp.headers)
    except urllib.error.HTTPError as e:
        # só alerta sozinho o caso acionável (rate limit); outros erros (ex.:
        # 404 esperado quando um repo simplesmente não tem README) ficam por
        # conta de quem chamou decidir se é normal ou não.
        if e.code == 403 and e.headers.get("X-RateLimit-Remaining") == "0":
            print("Limite de requisições da API do GitHub atingido. "
                  "Espere o reset (X-RateLimit-Reset) e rode de novo.", file=sys.stderr)
        raise
    time.sleep(PAUSA)
    return json.loads(corpo.decode("utf-8")), headers


def paginar(caminho, token):
    """Segue Link: rel=\"next\" até acabar as páginas."""
    itens = []
    url = f"{API}{caminho}"
    while url:
        pagina, headers = chamar_api(url, token)
        itens.extend(pagina)
        url = None
        link = headers.get("Link", "")
        for parte in link.split(","):
            if 'rel="next"' in parte:
                url = parte.split(";")[0].strip().strip("<>")
    return itens


def buscar_readme(full_name, token):
    try:
        dado, _ = chamar_api(f"/repos/{full_name}/readme", token)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    if dado.get("encoding") == "base64":
        try:
            return b64decode(dado["content"]).decode("utf-8", errors="replace")
        except Exception:
            return None
    return dado.get("content")


def main():
    env = carregar_env()
    token = env.get("GITHUB_TOKEN") or ""
    username = env.get("GITHUB_USERNAME") or ""
    if not token or not username:
        print("Faltam GITHUB_TOKEN e/ou GITHUB_USERNAME no .env. Veja o cabeçalho "
              "deste script pro formato esperado.", file=sys.stderr)
        sys.exit(1)

    print(f"Buscando perfil de {username}...")
    perfil, _ = chamar_api("/user", token)
    if perfil.get("login", "").lower() != username.lower():
        print(f"    (aviso: token autentica como '{perfil.get('login')}', "
              f"diferente do GITHUB_USERNAME='{username}' no .env)")

    print("Listando repositórios (todos que o token enxerga: públicos + "
          "privados selecionados)...")
    repos_raw = paginar("/user/repos?per_page=100&affiliation=owner", token)
    print(f"{len(repos_raw)} repositório(s) encontrado(s).")

    repos = []
    for r in repos_raw:
        full_name = r["full_name"]
        print(f"  [{full_name}] linguagens + README...")
        try:
            linguagens, _ = chamar_api(f"/repos/{full_name}/languages", token)
        except urllib.error.HTTPError as e:
            linguagens = {}
            if e.code != 404:
                print(f"      ! erro {e.code} buscando linguagens de {full_name}", file=sys.stderr)
        readme = buscar_readme(full_name, token)

        repos.append({
            "nome": r["name"],
            "full_name": full_name,
            "descricao": r.get("description"),
            "url": r["html_url"],
            "privado": r["private"],
            "fork": r["fork"],
            "linguagem_principal": r.get("language"),
            "linguagens_bytes": linguagens,
            "topicos": r.get("topics", []),
            "estrelas": r.get("stargazers_count", 0),
            "forks": r.get("forks_count", 0),
            "criado_em": r.get("created_at"),
            "atualizado_em": r.get("updated_at"),
            "ultimo_push_em": r.get("pushed_at"),
            "tamanho_kb": r.get("size"),
            "branch_padrao": r.get("default_branch"),
            "readme": readme,
        })

    saida = {
        "perfil": {
            "login": perfil.get("login"),
            "nome": perfil.get("name"),
            "bio": perfil.get("bio"),
            "empresa": perfil.get("company"),
            "localizacao": perfil.get("location"),
            "email_publico": perfil.get("email"),
            "blog": perfil.get("blog"),
            "seguidores": perfil.get("followers"),
            "seguindo": perfil.get("following"),
            "url_perfil": perfil.get("html_url"),
            "criado_em": perfil.get("created_at"),
        },
        "repositorios": repos,
    }

    out_dir = Path("dados_github")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "github.json"
    out_path.write_text(json.dumps(saida, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n=== Pronto ===")
    print(f"{len(repos)} repositório(s) salvos em {out_path}")


if __name__ == "__main__":
    main()

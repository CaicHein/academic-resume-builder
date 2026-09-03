# Currículo a partir da trajetória acadêmica

Ferramenta que transforma a trajetória acadêmica de um estudante — disciplinas,
ementas, notas, histórico escolar, repositórios de código — num currículo
pronto, com **proveniência**: cada afirmação do currículo aponta pra
disciplina, nota ou repositório que a comprova. Nada é inventado pelo modelo.

O escopo atual é a USP (Moodle = e-Disciplinas, Jupiter Web) + GitHub, mas a
arquitetura é agnóstica de instituição: qualquer fonte nova vira um coletor
independente que gera seu próprio JSON de domínio.

## O problema

Montar um currículo listando tudo que você aprendeu no curso é chato e
manual — ninguém relê a ementa de 40 disciplinas pra lembrar o que cada uma
cobriu, ou cruza isso com o quanto foi bem (ou mal) em cada uma. O valor
aqui não é "jogar texto num LLM" (isso qualquer um faz copiando e colando) —
é a **coleta automatizada com recibo de origem**: varrer sozinho dezenas de
disciplinas de vários semestres, baixar/consultar tudo organizado, e só
então sintetizar.

## O que faz hoje

1. **Coleta** (cada fonte roda isolada, gera seu próprio JSON bruto):
   - **Moodle (e-Disciplinas)** — lista de disciplinas + notas/entregas de
     cada uma, via sessão de navegador autenticada (SSO SAML da USP) + o
     material de aula de fato (PDFs, slides, código) de cada disciplina,
     com proveniência de cada arquivo (validado contra as 40 disciplinas
     reais: 1.237 arquivos baixados).
   - **Jupiter Web** — ementa oficial, objetivos, conteúdo programático,
     bibliografia e docentes de cada disciplina (busca pública, sem login) +
     histórico escolar completo (PDF autenticado, parseado por texto).
   - **GitHub** — perfil, repositórios, linguagens, tópicos e README de cada
     projeto, via API REST oficial.
2. **Consolidação** — tudo que é acadêmico (Jupiter + Moodle + histórico)
   converge num único JSON por domínio, `trajetoria_academica.json`,
   ordenado cronologicamente.
3. **Geração do currículo** — um modelo de linguagem lê a trajetória
   acadêmica + GitHub + notas complementares do usuário e sintetiza um
   currículo estruturado, **só com fatos que aparecem nos dados** (sem
   experiência real, a seção sai vazia — nunca inventada), com proveniência
   em cada bullet. Provider configurável: **API da Claude** (produção) ou
   um modelo **Ollama local** (grátis, pra testar sem chave/custo). Um
   segundo passo (sem chamada de rede) monta o `.tex` a partir desse JSON.
4. **Currículo interativo** — busca semântica sobre o *conteúdo real* dos
   materiais de cada disciplina (não só a ementa genérica): pergunte algo
   específico ("o aluno viu recursão em alguma disciplina?") e a resposta
   vem com a fonte exata (disciplina + arquivo) de cada afirmação — a
   citação nunca vem do texto que o modelo escreveu, sempre do trecho que a
   busca de fato recuperou. Embeddings via Ollama local
   (`nomic-embed-text`), índice vetorial em memória (numpy, sem banco
   dedicado). Índice atual: 10.662 trechos de 837 arquivos.
5. **Painel local** (Flask, `http://127.0.0.1:5000`, nunca exposto à
   internet) — dispara cada etapa com um clique, mostra o log em tempo real,
   visualiza os dados já coletados, uma timeline da trajetória acadêmica e a
   aba de pergunta-e-resposta do currículo interativo.

## Princípios de design

- **A senha do usuário nunca é manipulada pelo código.** O login no Moodle
  (SSO/SAML) e no Jupiter é feito manualmente pelo humano numa janela de
  navegador real; o script só reaproveita a sessão depois.
- **Proveniência em tudo.** Cada dado coletado registra de onde veio; o
  currículo gerado nunca afirma algo sem apontar a fonte.
- **Sem automação de login em serviços de terceiros com risco assimétrico.**
  O LinkedIn não é acessado por scraping/login automatizado — o risco de
  detecção de bot lá é banimento de conta, não "um script falhou". Em vez
  disso, o usuário exporta os próprios dados pelos canais oficiais e sobe o
  arquivo.
- **Gentileza com o servidor.** Automação de sistemas acadêmicos é uso
  pessoal, não abuso — pausas entre requisições, nada de paralelismo
  agressivo.
- **Ingestão desacoplada do gerador de currículo.** Qualquer fonte nova
  (inclusive de outra instituição) só precisa produzir um JSON no mesmo
  formato; o gerador de competências não sabe nem precisa saber de onde os
  dados vieram.

## Instalação

Requer Python 3.10+ e Windows + PowerShell (testado nesse ambiente).

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install playwright pdfplumber flask numpy
playwright install chromium
```

Crie um `.env` na raiz do projeto (nunca versionado) com as credenciais
necessárias — nenhuma senha, só tokens de API:

```
GITHUB_TOKEN=github_pat_...
GITHUB_USERNAME=seu_usuario

ANTHROPIC_API_KEY=sk-ant-...
```

`GITHUB_TOKEN` é opcional (só necessário pra coletar dados do GitHub) e pode
ser gerado em github.com/settings/personal-access-tokens/new (fine-grained,
só leitura). `ANTHROPIC_API_KEY` é opcional (só necessário pra gerar o
currículo com a Claude) e pode ser gerada em console.anthropic.com — **é um
produto separado da assinatura Claude Pro/Max**, com billing próprio por
token; a chamada de geração de currículo custa tipicamente menos de
US$ 1-2. Ambas também podem ser configuradas direto pela interface do
painel, sem editar o `.env` na mão.

**Opcional — [Ollama](https://ollama.com) local**, pra rodar o gerador de
currículo e o currículo interativo sem `ANTHROPIC_API_KEY`/custo (com
qualidade de resposta menor que a Claude):

```powershell
ollama pull nomic-embed-text   # obrigatório pro currículo interativo (embeddings)
ollama pull llama3.1           # ou outro modelo de chat de sua escolha
```

## Uso

```powershell
python app.py
```

Abre `http://127.0.0.1:5000`. A aba **Coletores** tem um botão por fonte —
cada um abre uma janela de navegador quando precisa de login manual (Moodle,
Jupiter) e mostra o log em tempo real. Rode na ordem: Moodle → Jupiter +
Histórico → GitHub (qualquer ordem entre essas três) → Currículo. Pra
habilitar o currículo interativo, rode também `harvester_moodle.py` sem
`--list-only` (baixa os materiais de fato — não entra no "Moodle: coletar
tudo" por padrão porque demora bastante) e depois o botão "indexar
materiais". A aba **Currículo interativo** fica disponível assim que o
índice existir.

Cada coletor também roda direto por terminal (`python coletar_moodle.py`,
etc.) — útil pra depurar uma etapa específica sem passar pela interface.

## Estrutura

```
harvester_moodle.py        # Moodle: lista disciplinas + baixa materiais
moodle_notas.py             # Moodle: notas/entregas por disciplina
jupiter_disciplinas.py      # Jupiter: ementa/créditos por disciplina
baixar_historico.py         # Jupiter: baixa o PDF do histórico escolar
parse_historico.py          # Extrai o PDF e gera trajetoria_academica.json
consolidar.py                # Junta ementas (Jupiter) + notas (Moodle)
coletar_github.py            # Perfil + repositórios via API do GitHub
gerar_competencias.py        # LLM: sintetiza o currículo estruturado (JSON)
renderizar_curriculo.py      # Monta o .tex a partir do JSON gerado
extrair_texto_materiais.py   # RAG: extrai texto dos materiais + chunking
gerar_embeddings.py          # RAG: gera embeddings via Ollama (em lote)
busca_semantica.py           # RAG: busca + resposta (importado por app.py)
coletar_moodle.py            # Orquestrador: Moodle de ponta a ponta
coletar_jupiter_historico.py # Orquestrador: Jupiter + histórico de ponta a ponta
gerar_curriculo_completo.py  # Orquestrador: competências + .tex de ponta a ponta
indexar_materiais.py         # Orquestrador: extração + embeddings de ponta a ponta
app.py + static/index.html   # Painel local (Flask)
```

## Status

| Fonte | Status |
|---|---|
| Moodle — lista de disciplinas | ✅ |
| Moodle — notas/entregas | ✅ |
| Moodle — download de materiais/arquivos | ✅ 1.237 arquivos, 40 disciplinas |
| Jupiter — ementa por disciplina | ✅ |
| Jupiter — histórico escolar | ✅ |
| GitHub | ✅ |
| Gerador de currículo (LLM) | 🟡 implementado (Claude ou Ollama), aguardando validação de qualidade com chamada real à Claude |
| Currículo interativo (RAG) | ✅ validado ponta a ponta — 10.662 trechos, 837 arquivos |
| LinkedIn | ⬜ aguardando export do usuário (sem scraping, ver princípios) |

## Roadmap

- Validar a qualidade do gerador de currículo contra uma chamada real à
  Claude (a pipeline já funciona; falta avaliar o texto gerado).
- Ingestão de dados do LinkedIn (upload manual do export oficial).
- Currículo interativo: ampliar o escopo de arquivo indexado (hoje só PDF +
  código/texto — slides e Word ficam de fora por decisão consciente do v1).

## Aviso

Projeto de uso pessoal. Automatizar acesso a sistemas acadêmicos pode
esbarrar nos termos de uso da instituição — use com moderação, sob sua
própria conta, sem paralelismo agressivo.

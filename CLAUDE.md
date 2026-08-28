# Projeto: Currículo a partir da trajetória acadêmica (Moodle USP)

> Este arquivo é um **handoff de contexto**. Ele resume o objetivo, as decisões
> já tomadas (para não refazê-las) e as próximas tarefas. Leia antes de agir.

## Objetivo

Construir uma ferramenta que resume a **trajetória acadêmica** de um estudante
em **competências prontas para currículo**. A dor original: montar um currículo
listando todas as competências adquiridas no curso é chato e manual.

O escopo atual é a USP (Moodle = **e-Disciplinas**, `https://edisciplinas.usp.br`),
mas a arquitetura deve permanecer **agnóstica de instituição**.

### Visão de longo prazo — "livrinho do aluno" (não perder de vista)

O objetivo final não é só listar competências: é conectar TUDO sobre a
trajetória do aluno num relato coerente, como se fosse um livrinho sobre ele.
Fontes a integrar (nem todas implementadas ainda — ver "Próximas tarefas"):

- **Moodle (e-Disciplinas)** — materiais de cada disciplina (`harvester_moodle.py`)
  e, depois, o que o aluno efetivamente fez/entregou/notas de atividade (para
  entender desempenho real, não só presença).
- **Jupiter Web** — ementa oficial de cada disciplina (o que ela SIGNIFICA:
  `jupiter_disciplinas.py`) e, depois, o **histórico escolar** (notas por
  disciplina, semestre a semestre — fonte estruturada da trajetória completa).
- **GitHub** — projetos, contribuições, linguagens usadas. Via API REST
  oficial (não é scraping — ver Restrições).
- **LinkedIn** — experiência profissional, estágios, formação complementar.
  **NÃO por automação/scraping** — ver Restrições. Via export oficial de
  dados ou PDF do perfil, que o usuário sobe (fallback de upload, princípio 2).

O valor final está em **conectar** essas fontes, não só em concatenar:
entender a nota do aluno em cada disciplina à luz do contexto — ex. a nota
caiu num semestre porque o aluno estava fazendo IC, grupo de extensão e
estágio ao mesmo tempo (ou, ao contrário, ele manteve a nota mesmo com essa
carga pesada, o que é ainda mais forte pro currículo); teve transferência de
curso; mudou de área. Esse tipo de conexão causal/contextual é o que
diferencia um resumo de currículo genérico de um que realmente entende a
trajetória do aluno.

**Ordem de execução: por partes.** Cada fonte é implementada e validada
isoladamente antes de integrar. Não pular etapas antecipando a integração.

## Arquitetura de dados: um JSON FINAL por DOMÍNIO, não por fonte nem por etapa

Cada coletor roda isolado e gera seu próprio arquivo bruto em
`materiais_moodle/` (`disciplinas.json`, `jupiter_disciplinas.json`,
`notas.json`, `historico_escolar.pdf`, `disciplinas_consolidado.json`) — isso
é proveniência/recibo por fonte (princípio 1/2 abaixo) e fica registrado, mas
**não é pra ser consumido diretamente** pelas próximas etapas (gerador de
competências, integração final).

O que É consumível é um json final por DOMÍNIO — hoje só um:
`materiais_moodle/trajetoria_academica.json`, gerado por `parse_historico.py`
(a última etapa do pipeline acadêmico). Estrutura: `{"perfil": {...dados
pessoais, créditos/médias globais, não é por disciplina...}, "disciplinas":
[...cada uma com ementa do Jupiter + notas do Moodle + histórico, tudo
aninhado...]}`. Não existem mais arquivos soltos tipo "só ementa" ou "só
notas" pra consumo — tudo que é sobre a trajetória acadêmica (não importa a
fonte: Jupiter, Moodle, histórico) converge nesse ÚNICO arquivo.

Quando entrar GitHub e LinkedIn, cada um vira seu PRÓPRIO json final de
domínio (`github.json`, `linkedin.json`) pela mesma lógica — não força dentro
de `trajetoria_academica.json`, que é especificamente sobre a vida acadêmica.
A integração de todos os domínios (acadêmico + GitHub + LinkedIn) acontece só
na etapa final do gerador de competências, não antes.

## Princípios de design (não violar sem discutir)

1. **O valor está na COLETA automatizada + PROVENIÊNCIA, não em "jogar texto num LLM".**
   Extrair texto e mandar pro modelo é trivial (o usuário faz copiando e colando).
   O que agrega valor é varrer sozinho dezenas de disciplinas de vários semestres,
   baixar tudo organizado, e registrar **de onde veio cada material** (o "recibo").
   A chamada ao LLM é o último 5% do trabalho.
2. **Desacoplar ingestão do gerador de competências.** O adaptador do Moodle é uma
   fonte; o gerador de competências (o miolo) não deve depender dele. Deve existir
   um **fallback de upload** (o usuário sobe PDFs/arquivos) para funcionar em
   qualquer faculdade, inclusive as com SSO onde a API não é acessível.
3. **Nunca manipular a senha do usuário no código.** Ver restrição de SSO abaixo.
4. **Gentileza com o servidor / uso pessoal.** Automatizar acesso pode esbarrar nos
   termos de uso da USP. Há pausas entre requisições; manter. Nada de loops agressivos.

## LinkedIn: por que NÃO automatizamos login lá (decisão consciente)

Diferente da USP (instituição do próprio usuário, uso pessoal tolerado, risco
baixo), o LinkedIn é terceiro comercial com detecção de bot agressiva
(fingerprint comportamental, não só user-agent) e ToS que proíbe
explicitamente acesso automatizado — inclusive à própria conta. A consequência
de ser pego não é "um script falha", é **suspensão/banimento da conta**
(anos de rede de contatos, histórico profissional). Não é um risco simétrico
ao que se corre com os sistemas da USP, e por isso a régua é diferente aqui.

Decisão: **sem Playwright/login automatizado no LinkedIn.** Em vez disso, o
usuário mesmo baixa os dados pelos canais oficiais:
- "Configurações > Privacidade de dados > Obter uma cópia dos seus dados"
  (export completo, estruturado, por e-mail) — preferido.
- "Perfil > (⋯) > Salvar como PDF" — mais rápido, menos completo.

E sobe o arquivo (fallback de upload, princípio 2) pro pipeline processar.
Isso não é gambiarra — é o "fallback de upload" que já era princípio de
design do projeto, só que aplicado aqui por necessidade real, não capricho.

GitHub é diferente: tem API REST oficial feita pra isso, sem risco de
detecção/banimento — ver `coletar_github.py`.

## Restrições já descobertas (IMPORTANTE — já investigado, não repetir)

- **O e-Disciplinas usa SSO SAML** via `idpcafe.usp.br` (federação CAFe / Senha
  Única USP). Confirmado.
- **Consequência:** a Web Services API do Moodle via token de senha
  (`/login/token.php?username=&password=&service=moodle_mobile_app`) **NÃO funciona**
  para o aluno — a senha é validada pelo provedor SAML, não pelo Moodle. Testado:
  retorna "invalid login". O script `sonda_moodle.py` foi criado só para provar
  isso e já cumpriu o papel.
- **Portanto a abordagem é scraping com sessão autenticada por humano** (Playwright):
  o usuário faz o login SSO na mão numa janela real, e o script pega carona na
  sessão. Sessão persistida em `.perfil_navegador/` (loga uma vez, reusa depois).
- **A USP usa um tema Moodle customizado.** Os seletores de cards de disciplina e de
  recursos podem precisar de calibração contra o HTML real. Esta é a principal
  tarefa aberta.
- **O Jupiter Web (`uspdigital.usp.br/jupiterweb`) tem uma busca de disciplina
  PÚBLICA, sem SSO/login** (`obterDisciplina?sgldis=...&nomdis=...`, GET simples).
  Confirmado contra HTML real. Não precisa de Playwright pra isso — é
  `urllib.request` puro. Ver `jupiter_disciplinas.py`.
  - `sgldis` sozinho já resolve pra página de detalhe quando a sigla é
    inequívoca. Quando a busca (por sigla ou por nome) casa com várias
    disciplinas, a página retorna uma lista de desambiguação com
    `obterDisciplina?sgldis=X&verdis=N` por candidato (`verdis` = versão do
    currículo da disciplina).
  - Página não encontrada = corpo com a string literal `"null"`.
  - **A página declara `charset=iso-8859-1` mas os bytes são windows-1252 de
    fato** (bullets/aspas curvas na faixa 0x80–0x9F ficam quebrados se
    decodificar como iso-8859-1 puro). Decodificar sempre com `cp1252`.
  - **CONFIRMADO: o login autenticado do Jupiter (`webLogin.jsp`) NÃO é o SSO
    SAML/CAFe do Moodle — é um formulário nativo próprio.** `POST autenticar`
    com campos `codpes` (número USP) e `senusu` (senha). A sessão do
    e-Disciplinas não serve aqui; é um login manual separado, na mesma régua
    de segurança do resto do projeto (o humano digita, o script nunca toca
    na senha). Reusa o mesmo `.perfil_navegador/` (cookies são por domínio,
    não conflita com a sessão do Moodle). Indicador de logado: link "Sair" na
    barra superior (`13682361 - Nome | Aluno | Alterar Senha | Sair`).
  - **CONFIRMADO: "Histórico escolar" (`historicoEscolar?codmnu=4538`) não
    expõe os dados em HTML — é um formulário que gera um PDF.** O botão
    "Gerar" (`#enviar`) seta o `src` de um `<iframe>` (`#documento`) pra
    `historicoescolarListar?cmd=cmd&<form serializado>`; essa URL devolve o
    PDF direto (`content-type: application/pdf`). Campo obrigatório: `#codcur`
    (select de curso/habilitação — escolher a opção "Habilitação", não
    "Módulo", pra pegar o histórico completo). Ver `baixar_historico.py`: em
    vez de montar a query string na mão, deixa o JS da própria página montar
    (clica no botão de verdade, lê o `src` resultante, busca via
    `context.request` autenticado).
  - **`parse_historico.py` extrai TUDO do PDF, não só notas por disciplina**:
  classificação na carreira, forma de ingresso, naturalidade/RG/nacionalidade,
  créditos por tipo de obrigatoriedade (Obrigatórias/Opt.Eletivas/Opt.Livres),
  dispensas específicas (disciplina dispensada + equivalente(s) que geraram o
  crédito, com nota/período/unidade de cada), valor de seleção de optativas,
  observações gerais. Nada fica só em `linhas_nao_reconhecidas` se tiver
  rótulo reconhecível.
- **Tabela de "Dispensa(s) Específica(s)" tem intercalamento traiçoeiro no
  texto linearizado**: a quebra de linha do NOME da disciplina dispensada
  pode aparecer DEPOIS do primeiro equivalente, não antes (confirmado no PDF
  real — não é hipotético). `parse_dispensas()` por isso não desiste no
  primeiro token estranho: continua procurando a "unidade" de cada
  equivalente mesmo com uma quebra de nome no meio, e qualquer linha órfã
  vira candidata a continuação do nome da dispensada (é a única outra coluna
  de texto livre da tabela).
- **`disciplinas` no `trajetoria_academica.json` fica ordenado
  cronologicamente** (pelo semestre mais antigo em que a disciplina aparece
  no histórico) — importa pras próximas etapas (currículo/portfólio contam a
  trajetória em ordem). Disciplina sem nenhum registro de histórico vai pro
  fim, sem embaralhar as demais.
- **O PDF do histórico tem layout tabular fixo, bem parseável por texto**
    (`parse_historico.py`, via `pdfplumber`): por semestre, uma linha por
    disciplina com `Sigla Nome AU [TR] CH [CE] [CP] [EXT] [ATPA] FREQ NOTA
    Situação` — colunas de crédito no meio são POSICIONALMENTE AMBÍGUAS só
    pelo texto (o PDF omite coluna zerada em vez de imprimir "0"; sem as
    coordenadas X de cada coluna não dá pra saber com certeza se um número no
    meio é TR, CE, CP, EXT ou ATPA). Só o primeiro (créditos aula) e o último
    (carga horária) são extraídos com confiança; o resto fica cru em
    `creditos_meio_ambiguo`. NOTA é sempre o único valor com ponto decimal;
    situação (A/MA/RN/RF/...) é sempre o último token da linha.

## Arquivos

- **`harvester_moodle.py`** — Abre Chrome via Playwright (contexto
  persistente), espera o login SSO manual (polling, sem pedir Enter), lista as
  disciplinas e baixa materiais para `materiais_moodle/<disciplina>/`, gerando
  `materiais_moodle/manifesto.json` (proveniência de cada arquivo) e
  `materiais_moodle/disciplinas.json` (lista {id, nome, url} — é a ENTRADA do
  `jupiter_disciplinas.py`).
  Flags: `--list-only` (só lista, não baixa), `--course-id N` (testa 1 disciplina),
  `--headless`.
- **`jupiter_disciplinas.py`** — FOCO ATUAL. Lê `materiais_moodle/disciplinas.json`,
  tenta extrair uma sigla USP (regex) do nome de cada disciplina do Moodle, consulta
  o Jupiter Web (público, sem login) e extrai ementa, objetivos, conteúdo
  programático, forma de avaliação, bibliografia, docentes, créditos e carga
  horária. Quando a sigla não é reconhecível ou a busca é ambígua, NÃO
  adivinha: marca `status: "ambiguo"` com os candidatos, ou `"nao_encontrado"`,
  pra revisão manual — nunca escolhe silenciosamente. Gera
  `materiais_moodle/jupiter_disciplinas.json`.
  Flags: `--sigla X` / `--nome "..."` (testa 1 disciplina direto, sem passar
  pela heurística de extração — útil pra calibrar).
- **`moodle_notas.py`** — FOCO ATUAL (concluído, validado contra as 40 disciplinas
  reais: 398 itens extraídos). Lê `materiais_moodle/disciplinas.json`, visita
  `.../grade/report/user/index.php?id=<course_id>` (o "livro de notas" — relatório
  do usuário) de cada disciplina e extrai todo item avaliado: tipo (Tarefa,
  Questionário, Item manual, Conteúdo interativo...), nome, link, categoria,
  peso, nota, porcentagem e feedback do professor. Isso é o que faltava pra
  entender DESEMPENHO real (não só quais disciplinas foram cursadas — isso o
  Jupiter já dá de graça). Usa a mesma sessão SSO do harvester (importa
  `esperar_login`/`goto_seguro`/`BASE`/`PERFIL`, não duplica). Gera
  `materiais_moodle/notas.json`.
  Flags: `--course-id N` (testa 1 disciplina), `--headless` (cuidado, ver gotcha do WAF).
- **`consolidar.py`** — junta `jupiter_disciplinas.json` + `notas.json` em
  `materiais_moodle/disciplinas_consolidado.json` (ementa + notas por
  disciplina). É uma etapa INTERMEDIÁRIA do pipeline, não o arquivo final —
  `parse_historico.py` lê esse arquivo, soma o histórico, e escreve o de fato
  consumível, `trajetoria_academica.json` (ver "Arquitetura de dados").
  Roda depois de `jupiter_disciplinas.py` e `moodle_notas.py`, antes de
  `parse_historico.py`.
- **`jupiter_auth.py`** — login manual no Jupiter AUTENTICADO (formulário
  próprio, não o SSO do Moodle — ver Restrições). Módulo compartilhado, reusa
  `hm.PERFIL`/`hm.goto_seguro`; expõe `esperar_login(context, page)`.
- **`baixar_historico.py`** — gera e baixa o PDF do histórico escolar
  (clica no botão "Gerar" de verdade em vez de montar a URL na mão — ver
  Restrições). Salva `materiais_moodle/historico_escolar.pdf`.
- **`parse_historico.py`** — FOCO ATUAL, última etapa do pipeline acadêmico.
  Extrai o PDF do histórico (`pdfplumber`) e gera o ÚNICO json final do
  domínio acadêmico, `materiais_moodle/trajetoria_academica.json`:
  `{"perfil": {...não é por disciplina...}, "disciplinas": [...ementa
  (Jupiter) + notas (Moodle) + histórico, tudo aninhado por disciplina...]}`.
  Disciplinas do histórico sem sigla correspondente são listadas (não
  descartadas) em `disciplinas_no_historico_sem_match_no_consolidado` —
  normal para disciplinas sem harvest do Moodle (ex.: 1º/2º ano, antes ou
  fora do e-Disciplinas), mas é o sinal de "conferir se não esqueceu nada".
- **`dump_pagina_jupiter.py`** — mesmo padrão de `dump_pagina_moodle.py`, mas
  logando via `jupiter_auth` em vez do SSO do Moodle.
- **`dump_pagina_moodle.py`** — utilitário de debug/calibração. Abre qualquer
  URL do e-Disciplinas (reusando `esperar_login`/`goto_seguro` de
  `harvester_moodle.py`) e salva o HTML renderizado num arquivo. Usar sempre
  que for calibrar um scraper novo contra o DOM real em vez de adivinhar
  (ex.: página de notas, atividades). Precisa de janela visível (ver gotcha
  do WAF abaixo).
- **`coletar_moodle.py`**, **`coletar_jupiter_historico.py`**,
  **`gerar_curriculo_completo.py`** — orquestradores. Cada um encadeia, como
  subprocessos em sequência (parando no primeiro que falhar, com mensagem
  clara de qual etapa quebrou), os scripts individuais que já existiam —
  não reimplementam nada, só compõem. Existem porque a interface do painel
  foi simplificada de ~10 botões (um por script) pra 4 (um por fonte/domínio:
  Moodle, Jupiter+Histórico, GitHub, Currículo) — ver `app.py`. Os scripts
  individuais continuam existindo e rodáveis por terminal com suas flags de
  calibração de sempre (ex.: `jupiter_disciplinas.py --sigla X`), só não
  aparecem mais como botão separado.
- **`app.py`** + **`static/index.html`** — Painel de controle
  local (Flask, só em `127.0.0.1`, nunca exposto). Dispara os orquestradores
  acima como subprocesso — só 4 botões na aba Coletores (Moodle, Jupiter +
  Histórico, GitHub, Currículo), mais um campo pra colar a
  `ANTHROPIC_API_KEY` direto na interface (grava no `.env` sem reexibir a
  chave depois). Outras abas: LinkedIn — upload manual, sem scraping;
  Informações adicionais — texto livre opcional; Visualizar dados — lê
  `trajetoria_academica.json`/`github.json` com tolerância total a arquivo
  ausente, nunca trava; Timeline — sparkline SVG da média ponderada por
  semestre + linha do tempo vertical com chips por disciplina coloridos por
  situação, consumindo `perfil.semestres` de `trajetoria_academica.json`.
  Roda com `python app.py`, abre `http://127.0.0.1:5000`. Não reimplementa
  nenhuma lógica de coleta — só orquestra. Detalhe importante:
  `subprocess.Popen(..., stdin=subprocess.DEVNULL)` é obrigatório nas
  tarefas — sem isso, o fallback de "tecle Enter" de `esperar_login` ficaria
  esperando input que nunca chega pela interface web.
- **`coletar_github.py`** Perfil + repositórios (descrição,
  linguagens por bytes, tópicos, estrelas, datas, README decodificado) via
  API REST oficial do GitHub (`api.github.com`, sem Playwright — é HTTP puro
  com token, igual o Jupiter Web). Token em `.env` (`GITHUB_TOKEN`,
  `GITHUB_USERNAME` — nunca no código, `.env` está no `.gitignore`). Gera
  `dados_github/github.json` — arquivo final desse domínio (mesma lógica do
  `trajetoria_academica.json`, ver "Arquitetura de dados"). Expõe
  `carregar_env()`, reusado por `gerar_competencias.py` (não duplicar).
- **`gerar_competencias.py`** — FOCO ATUAL, passo 3 do roadmap ("gerador de
  competências"). Lê `trajetoria_academica.json` + `github.json` +
  `dados_extra/informacoes_adicionais.json` (todos tolerantes a ausência) e
  chama a API da Claude (`https://api.anthropic.com/v1/messages`, HTTP puro
  via `urllib` — **decisão consciente de não instalar o SDK `anthropic`**,
  pra manter a mesma filosofia stdlib-only de `coletar_github.py`/
  `jupiter_disciplinas.py`; ver "Ambiente") pedindo `output_config.format:
  json_schema` (structured output — garante o shape, sem parsing frágil de
  texto livre). Regra inegociável no prompt: só preencher com fatos que
  aparecem nos dados de entrada, nunca inventar experiência/tecnologia; sem
  dado real numa seção, a lista sai vazia. Cada bullet de experiência/projeto
  carrega uma `fonte` (proveniência — princípio 1). Chave em `.env`
  (`ANTHROPIC_API_KEY`). Chamada paga (envia a trajetória acadêmica inteira,
  request grande). Gera `dados_extra/competencias.json`.
- **`renderizar_curriculo.py`** — FOCO ATUAL. Sem chamada de rede: lê
  `dados_extra/competencias.json` e monta `dados_extra/curriculo.tex`. Estilo
  visual (cores, tipografia, formato de seção) adaptado de um exemplo de
  currículo em LaTeX fornecido pelo usuário; `escapar_latex()` escapa todo
  texto vindo do JSON antes de entrar no `.tex`. Seção sem dado real
  (ex.: Experiência Profissional pra quem não tem nenhuma ainda) é omitida
  inteira, nunca aparece em branco. Não compila o PDF sozinho — usuário
  compila com `pdflatex`/Overleaf.
- **`sonda_moodle.py`** — prova de viabilidade da API (já demonstrou que o SSO
  bloqueia o token). Mantido como registro; não é parte do produto final.
- *(Se houver `garimpo_github.py` na pasta: é de outro experimento, NÃO relacionado
  a este projeto. Ignore.)*

## Ambiente

- **Windows + PowerShell.**
- Virtualenv em `.venv` (ativar: `.\.venv\Scripts\Activate.ps1`; se der erro de
  execution policy: `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`).
- Dependências: `playwright` + `pdfplumber` + `flask` (pip) + navegador via
  `playwright install chromium` (o navegador fica no cache do usuário, fora
  da venv).
- `.gitignore` deve conter: `.venv/`, `.perfil_navegador/`, `materiais_moodle/`,
  `dados_github/`, `dados_linkedin/`, `dados_extra/`, `.env`.
- **Credenciais de API (ex.: `GITHUB_TOKEN`, `ANTHROPIC_API_KEY`) vão em
  `.env` na raiz, nunca no código.** Formato `CHAVE=valor`, uma por linha;
  `carregar_env()` em `coletar_github.py` faz o parse (sem dependência nova
  tipo `python-dotenv`) e é reusada por `gerar_competencias.py`.
  ATENÇÃO: o repositório git aqui tem raiz em `C:\Users\CAIC HEIN` (a pasta de
  usuário inteira, não só este projeto) — confirmado, mas nunca corrigido.
  Antes de qualquer `git add`/`commit`, checar com `git status` que só arquivos
  do projeto estão sendo staged.

## Gotchas técnicos (já resolvidos — contexto para não regredir)

- **`page.goto` é interrompido pelos redirects do SSO** ("Navigation ... is
  interrupted by another navigation"). Solução: wrapper `goto_seguro()` que engole
  esse erro específico e deixa o polling confirmar o estado final. NÃO usar
  `wait_until="networkidle"` (trava com conexões persistentes do Moodle);
  usar `domcontentloaded`.
- **Login:** o usuário clica no botão "Senha USP" na tela do e-Disciplinas → cai no
  `idpcafe` → volta logado. Não dá para navegar direto na URL do idpcafe (o token
  `execution=eNsN` é efêmero e o fluxo SAML precisa ser iniciado pelo Moodle).
- **`is_logged_in(page)`** já tem 3 heurísticas em cascata (link de logout →
  elementos do menu de usuário/avatar → fallback por URL fora de `/login/` sem
  botão de login visível), porque o tema da USP customiza o Moodle e o
  seletor de logout puro não bate. O loop de espera do login também imprime a
  URL atual a cada ~10s — se travar nessa etapa de novo, olhar esse log antes
  de mexer no código.
- **CONFIRMADO em produção: o clique em "Senha USP" pode abrir o fluxo SSO
  numa ABA NOVA**, não navegar a mesma `page`. Sintoma: usuário já vê o Moodle
  logado no navegador, mas o log de debug mostra a `page` original parada pra
  sempre em `idpcafe.usp.br?execution=e1s1`. `esperar_login()` agora recebe o
  `context` (não só a `page`) e varre TODAS as abas abertas (`pagina_logada()`)
  a cada iteração do polling, devolvendo a aba que de fato logou — que passa a
  ser usada pelo resto do script. Se `esperar_login` for chamado nalgum lugar
  novo, sempre USAR o retorno como a `page` daí em diante (não a `page`
  passada como argumento).
- **Console do Windows quebra em texto acentuado.** `cp1252`/`cp437` não
  cobrem tudo que aparece em nomes de disciplina/docente. Os dois scripts já
  fazem `sys.stdout.reconfigure(encoding="utf-8")` no topo — manter esse
  padrão em qualquer script novo que imprima texto vindo da USP.
- **O WAF da USP bloqueia Chromium headless.** `--headless` retorna uma página
  de bloqueio ("The URL you requested has been blocked"), provavelmente por
  detectar `HeadlessChrome` no user-agent. Pra qualquer coisa que precise
  acessar o e-Disciplinas de verdade (inclusive scripts de debug/calibração),
  usar `headless=False`. `dump_pagina_moodle.py` existe pra isso: abre uma
  página qualquer do Moodle (reusando `esperar_login` do harvester) e salva o
  HTML renderizado, pra calibrar seletor contra o DOM real sem escrever o
  scraper às cegas.
- **A sessão em `.perfil_navegador/` expira, e não previsivelmente.** Às vezes
  reaproveita ("Já estava logado"), às vezes pede login de novo mesmo logo
  depois de um login bem-sucedido anterior — parece que fechar e reabrir o
  navegador (`context.close()` + novo `launch_persistent_context`) às vezes
  derruba o cookie de sessão do Moodle mesmo com o profile salvo em disco.
  Não tem solução definitiva conhecida; os scripts já lidam bem com precisar
  logar nessas horas (a espera de login é a mesma seja primeira vez ou sessão
  expirada). O usuário também relata que o e-Disciplinas **erra no login com
  frequência por conta própria** (nada a ver com automação) — o remédio dele é
  fechar a janela e tentar de novo, o que também funciona aqui.
- **CUIDADO ao matar um script no meio do login: mata o Python, não o Chrome
  inteiro.** `TaskStop`/Ctrl+C no processo Python NÃO derruba a árvore de
  processos `chrome.exe` que o Playwright abriu (browser + GPU + renderers +
  utility — facilmente 7+ processos por instância). Isso já causou uma sessão
  de debug INTEIRA de confusão: os processos órfãos ficam disputando o mesmo
  `user_data_dir`, e o Chrome (no Windows) pode abrir uma janela "solta" fora
  do controle do Playwright em vez de uma sessão nova de verdade — o usuário
  vê a tela logada em uma janela, mas o `context.pages` do script (preso a um
  processo zumbi) nunca reflete isso, e a espera de login trava pra sempre
  mesmo com login concluído. **Antes de relançar depois de matar um script no
  meio do caminho: confirmar 0 processos `chrome.exe`** (`tasklist | grep -i
  chrome` no bash, ou `Get-Process chrome` no PowerShell) e encerrar à força
  (`taskkill /IM chrome.exe /F`) se sobrar algum — só fazer isso com o usuário
  ciente, pode fechar outras janelas/abas dele sem relação com o script.
- **Prova visual em caso de dúvida: screenshot embutido no `esperar_login`.**
  A cada ~10s de espera, o loop tira um screenshot de cada aba aberta
  (`_debug_estado_N.png`) — em vez de adivinhar ou perguntar "o que você tá
  vendo na tela", é só olhar o arquivo. Muito mais rápido que ping-pong de
  perguntas quando o estado do login fica ambíguo.
- **`SIGLA_RE` (extração de código de disciplina do nome do Moodle) não pode
  usar `\b` no final.** Nomes reais colam o código com `_` antes do ano (ex.:
  `PMR3408_2026`) — `_` conta como `\w`, então `\b` falha bem ali e a sigla
  nunca é extraída (o script cai silenciosamente pra busca por nome, que
  falha). Regex certo: `(?<![A-Za-z0-9])(...)(?!\d)` — bloqueia só grudar em
  outro alfanumérico, sem exigir fronteira de "palavra" completa. Isso já
  causou uma disciplina inteira sumir da consolidação; se `jupiter_disciplinas.py`
  reportar "não encontrado" pra uma sigla que claramente está no nome, é essa
  a primeira coisa a suspeitar.
- **Texto extraído de PDF (`pdfplumber`) que passa pelo Bash/PowerShell some
  os acentos ao imprimir no terminal — mas o dado no arquivo está correto.**
  Mesma classe do gotcha de encoding do Windows acima: não é corrupção real,
  é o console. Confirmar sempre lendo o arquivo (Read tool / grep por uma
  string acentuada específica) antes de "corrigir" algo que na verdade já
  está certo.
- **Parsing de HTML legado (Jupiter Web): não confiar em quebra de linha do
  código-fonte.** O HTML da página de disciplina vem formatado (uma tag por
  linha) só por legibilidade — isso NÃO reflete a estrutura lógica. Quebrar
  texto em `\n` ingenuamente separa label e valor que estão no mesmo `<tr>`.
  Solução usada em `jupiter_disciplinas.py::html_para_linhas`: marcar as
  quebras que importam (`<br>`, `</tr>`) com um token único ANTES de colapsar
  todo o resto do whitespace (inclusive as quebras cosméticas) em espaço
  simples, só depois dividir pelo token.

## Status das fontes (o que já funciona, ponta a ponta, contra dados reais)

- ✅ **Moodle — lista de disciplinas** (`harvester_moodle.py --list-only`):
  40 disciplinas, `materiais_moodle/disciplinas.json`.
- ✅ **Jupiter — ementa por disciplina** (`jupiter_disciplinas.py`): 38/40 "ok"
  na primeira passada real (2 "não encontrado" — nomes sem sigla reconhecível,
  ex. `PEA_EG_2025`, não é bug). `materiais_moodle/jupiter_disciplinas.json`.
- ✅ **Moodle — notas/entregas** (`moodle_notas.py`): 398 itens em 40
  disciplinas, 116 com nota preenchida. `materiais_moodle/notas.json`.
- ✅ **Histórico escolar** (`baixar_historico.py` + `parse_historico.py`):
  PDF de 4 páginas, todas as disciplinas desde 2022 com nota final/frequência/
  situação por semestre. 39/40 disciplinas casadas por sigla (a que falta,
  `PEA_EG_2025`, não é uma disciplina de verdade).
- ✅ **Arquivo final único** (`parse_historico.py`): ementa (Jupiter) + notas
  do Moodle + histórico do Jupiter + dados pessoais/créditos globais, tudo num
  JSON só — `materiais_moodle/trajetoria_academica.json`. É este arquivo,
  não os arquivos brutos de cada coletor, que deve alimentar o próximo passo
  (ver "Arquitetura de dados" acima).
- ⬜ Materiais/arquivos baixados (`harvester_moodle.py`, sem `--list-only`) —
  implementado mas ainda não validado contra download completo real (pastas,
  `pluginfile.php`).
- ✅ **GitHub** (`coletar_github.py`): perfil + 13 repositórios (linguagens,
  tópicos, README) via API oficial. `dados_github/github.json`.
- ⬜ **LinkedIn**: decidido NÃO automatizar (ver seção própria acima) —
  aguardando o usuário exportar/subir os dados (upload fallback).
- 🟡 **Gerador de competências (LLM)** (`gerar_competencias.py` +
  `renderizar_curriculo.py`): implementado, testado localmente (carregamento
  de dados reais, montagem de mensagem, render de `.tex` com dados fictícios
  cobrindo escape de caracteres especiais e omissão de seção vazia) e
  integrado ao painel. **Ainda não validado ponta a ponta com uma chamada
  real à API** — falta `ANTHROPIC_API_KEY` no `.env`.

## Próximas tarefas (em ordem)

1. **Validar o download completo do Moodle** (recursos `/mod/resource/`, pastas
   `/mod/folder/`, e links `pluginfile.php`) no tema da USP; ajustar extração.
   `dump_pagina_moodle.py` serve pra calibrar contra uma página de recurso real
   antes de escrever/ajustar o parser, mesmo processo usado pra `moodle_notas.py`.
2. **Explorar o resto do menu autenticado do Jupiter** ("Acesso Restrito":
   Grade horária, Acompanhamentos, Avaliação de disciplinas, Emissão de
   documentos, Opção de curso, Matrícula...) — o histórico escolar já está
   coberto, mas pode haver mais dados úteis por disciplina nessas outras
   páginas (ver "livrinho do aluno" no Objetivo). Não investigado ainda.
3. **Gerador de competências:** implementado (`gerar_competencias.py` +
   `renderizar_curriculo.py`, ver "Arquivos" e "Status das fontes") — falta
   só validar com uma chamada real (`ANTHROPIC_API_KEY` no `.env`) e conferir
   se o texto gerado (resumo, bullets, conexão nota↔contexto) fica bom contra
   os dados reais do aluno, não só passar no smoke test estrutural.
4. **LinkedIn:** esperar o usuário exportar os dados (ou o PDF do perfil) e
   subir o arquivo; então construir o parser de ingestão (sem scraping — ver
   seção própria acima). Gera `dados_linkedin/linkedin.json` na mesma lógica.
   Depois disso, `gerar_competencias.py` passa a ler também esse arquivo.
5. **(Ideia futura, não iniciada) Currículo interativo:** busca semântica
   (RAG) sobre os materiais reais de cada disciplina, cruzada com desempenho
   — ver `IDEIA_curriculo_interativo.md` pro desenho detalhado. Bloqueada
   pela tarefa 1 (download completo de materiais ainda não validado).

## Como você (Claude Code) pode ajudar melhor

Você roda local, então pode fazer o que eu (contexto de chat) não podia: executar
os scripts, **abrir o e-Disciplinas logado e despejar o HTML real** de uma página
de disciplina, e calibrar os seletores em cima do DOM verdadeiro em vez de adivinhar.
O mesmo vale pro Jupiter Web: como a busca de disciplina é pública, dá pra buscar
o HTML real direto (`curl`/`urllib`) sem precisar de sessão nenhuma — foi assim
que `jupiter_disciplinas.py` foi calibrado, contra disciplinas reais (ex.:
5950106, SCC0201), não adivinhado.

# Ideia futura: currículo interativo (RAG sobre os materiais das disciplinas)

> Registrado em 2026-08-25, durante a construção do gerador de competências
> (`gerar_competencias.py`/`renderizar_curriculo.py`). Não iniciado — este
> arquivo existe pra não perder a ideia, não é uma tarefa em andamento.
> Ler `CLAUDE.md` primeiro pro contexto geral do projeto antes de retomar
> isso.

## A ideia

O gerador de competências (passo 3 do roadmap) produz um currículo
**estático**: um LLM lê a trajetória acadêmica inteira de uma vez e sintetiza
texto pronto. Isso é ótimo pra gerar o documento, mas descarta a
possibilidade de **perguntar** coisas específicas depois — ex.: "o aluno viu
recursão em alguma disciplina?", "como ele foi em Estruturas de Dados?",
"quão a fundo foi abordado threads/concorrência no curso?".

A ideia é uma segunda funcionalidade, complementar ao CV estático: um
**currículo interativo** — uma busca semântica sobre TODO o conteúdo real das
disciplinas (não só a ementa oficial do Jupiter, que é genérica) cruzada com
desempenho (notas, histórico). Isso é a extensão natural da visão de "livrinho
do aluno" já registrada em `CLAUDE.md`, só que como uma interface de
pergunta-resposta em vez de um documento gerado uma vez.

Exemplos de pergunta que isso responderia, com proveniência (fonte + nota +
contexto), não só "sim/não":

- "Você já trabalhou com Kafka ou alguma fila de mensageria?"
- "Em que profundidade seu curso abordou grafos — só teoria em slide, ou teve
  projeto prático?"
- "Como foi seu desempenho em disciplinas de sistemas distribuídos?"

## Pré-requisito bloqueante

**Resolvido em 2026-09-01:** o download completo do Moodle
(`/mod/resource/`, `/mod/folder/`, `pluginfile.php`) foi validado ponta a
ponta contra as 40 disciplinas reais — 1.237 arquivos em
`materiais_moodle/<disciplina>/`, com proveniência em
`materiais_moodle/manifesto.json`. Dois bugs reais foram corrigidos no
caminho (mojibake de nome de arquivo, logo do site sendo baixada como
material — ver "Gotchas técnicos" em `CLAUDE.md`). Os arquivos já estão em
mãos; o que falta antes de começar essa ideia de verdade é só o gerador de
competências validado ponta a ponta (tarefa 3 do roadmap atual em
`CLAUDE.md`).

## Arquitetura proposta (rascunho, a refinar quando for começar)

1. **Extração de texto por material** — cada arquivo baixado em
   `materiais_moodle/<disciplina>/` (PDF, slide, doc — formato varia)
   convertido pra texto. PDF já tem `pdfplumber` disponível no projeto; outros
   formatos (pptx, docx) podem precisar de dependência nova — decidir na
   hora, não assumir agora.
2. **Chunking** — quebrar o texto de cada material em pedaços menores
   (parágrafo/seção), mantendo a proveniência de cada chunk: disciplina,
   arquivo, trecho, e o `origem_url` que `manifesto.json` (gerado pelo
   harvester) já registra. A proveniência não é opcional — é o princípio 1
   do projeto aplicado aqui também.
3. **Embeddings** — a Anthropic **não tem endpoint de embeddings próprio**;
   o parceiro recomendado pela própria Anthropic é a **Voyage AI**
   (voyageai.com). Isso seria a primeira dependência de API nova do projeto
   além de Claude/GitHub — decisão consciente a tomar quando for implementar,
   do mesmo jeito que a decisão de HTTP puro foi tomada pro gerador de
   competências. Confirmar preço/modelo atual na hora (não confiar em
   memória — a skill `claude-api` deste ambiente tem ponteiros pra
   documentação viva).
4. **Índice vetorial** — dado o volume (~40 disciplinas, algumas dezenas de
   arquivos cada — não milhões de documentos), busca por força bruta em
   memória (embeddings num array numpy + similaridade de cosseno) resolve
   sem precisar de um banco vetorial de verdade (Chroma, Pinecone, etc.) —
   mantém a filosofia do projeto de dependência mínima. Persistir os vetores
   calculados em disco (ex.: `.npy` ou `.json`) pra não recalcular a cada
   pergunta.
5. **Interface de pergunta** — uma aba nova no painel (`app.py` +
   `static/index.html`), no mesmo padrão das abas existentes: campo de texto
   livre, a pergunta é embedada, busca os top-k chunks mais relevantes,
   monta contexto (chunks + a nota/situação da disciplina de onde vieram,
   puxando de `trajetoria_academica.json`) e chama a Claude pra responder
   citando disciplina/arquivo/trecho — RAG clássico, mas com a proveniência
   que o resto do projeto já exige em tudo.

## Perguntas em aberto pra quando for começar

- Combinar dado estruturado (notas, situação, semestre) com o índice
  vetorial (texto livre), ou manter os dois separados e só juntar na hora de
  montar a resposta? Provavelmente a segunda opção — o índice vetorial serve
  só pra achar QUAL disciplina/material é relevante; o resto (nota,
  contexto) já está estruturado em `trajetoria_academica.json` e não precisa
  de embedding nenhum.
- Como julgar "profundidade" de cobertura de um tópico automaticamde fato —
  provavelmente não dá pra automatizar direito; melhor deixar a Claude
  inferir isso a partir do tipo de material recuperado (slide de uma linha
  vs. lista de exercícios vs. enunciado de projeto), sem prometer uma métrica
  numérica de "profundidade".
- Vale reusar esse mesmo índice vetorial como insumo extra pro
  `gerar_competencias.py` (CV estático), ou manter os dois pipelines
  totalmente separados? Decidir só depois que ambos existirem e o valor de
  cada um ficar mais claro na prática.

## Nota de design (2026-08-25, do usuário)

A intenção não é acumular os arquivos brutos de cada disciplina como um
arquivo morto — é **ler** o conteúdo (extrair texto, entender o que cobre) e
manter o que importa (chunks + embeddings + metadado de proveniência), não
necessariamente guardar cada PDF/slide original pra sempre. O objetivo final
é um sistema que "sabe tudo sobre a graduação do aluno", não um backup de
arquivos. Isso importa pro desenho do passo 1 (extração de texto): pensar
desde já em processar-e-descartar (ou processar-e-arquivar separado do índice
de busca), não em "baixar tudo pra pasta e depois ver o que fazer". Ainda não
decidido em detalhe — só o registro da intenção, pra não perder quando for
desenhar de verdade.

## Onde isso entra no roadmap

Coleta completa das 40 disciplinas: feita. Falta o gerador de competências
validado ponta a ponta com uma chamada real — não é uma tarefa a
paralelizar com o que já está em andamento agora.

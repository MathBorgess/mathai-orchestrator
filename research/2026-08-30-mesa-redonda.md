# Mesa-redonda — como Maestri, Grok Bot e Hermes fazem time de agentes, e o que sobra para nós

**Data:** 2026-08-30 · **Issue:** [MAT-96](https://linear.app/borgesmathai/issue/MAT-96) · **Status:** registro de processo
**Método:** quatro pesquisas independentes, rodadas **em paralelo**, sem acesso ao trabalho uma da outra, contra um dossiê factual comum ([`2026-08-30-dossie-fontes.md`](2026-08-30-dossie-fontes.md)) e contra a [`SPEC.md`](../SPEC.md) v0. As posições abaixo são recorte; os memoriais íntegros estão em [`teammates/`](teammates/).

## Elenco

| | Quem | Cadeira | Memorial |
|---|---|---|---|
| **Peko** | pesquisador de harness / AI engineering, graph engineering | o que a literatura já mediu | [`01`](teammates/01-pesquisador-harness-graph.md) — 15 papers em fonte primária, 20 em resumo de busca, 5 lacunas confessadas |
| **Alex** | designer de team chat de trabalho (Slack/Discord/WhatsApp/Linear) | como um humano lê um time trabalhando | [`02`](teammates/02-designer-teamchat.md) — metáfora, mockups ASCII, formato de mensagem |
| **Ailla** | engenheira, conhece o Hermes Agent por dentro | o que custa caro em código | [`03`](teammates/03-engenheiro-hermes.md) — **20 testes executados** contra `claude` 2.1.251, marcados `[V]` |
| **Baldi** | tech founder, devil's advocate | por que não construir | [`04`](teammates/04-devil-advocate.md) — mapa competitivo de 15 produtos, critério de morte |

Regra da mesa: quem afirma número, cita fonte. Quem infere, marca inferência. Divergência não resolvida fica escrita como divergência.

---

## Rodada 1 — como cada um faz time de agentes

### 1.1 Maestri

**O mecanismo.** Não existe protocolo do orquestrador. Ao ligar dois terminais com um cabo, "Maestri installs a **Maestri Agent Skill** in each one" — o contrato agente↔agente passa a morar **dentro do CLI**, e o transporte é o PTY.

Ailla reconstruiu as duas pernas separadamente, e elas não são simétricas:

- **Ida (A→B) é HTTP local, não PTY.** As variáveis `MAESTRI_HOST=<bridge-endpoint>` e `MAESTRI_TOKEN=<per-terminal-secret>` só existem para um cliente falar com um servidor local autenticado. A skill é (a) markdown que ensina o agente e (b) um binário `maestri` que faz o POST. Confiança alta — nada mais explica um token por terminal.
- **Volta (B→A) é leitura de tela.** Se B respondesse chamando `maestri reply`, **o foco seria irrelevante**. A doc faz do foco uma regra dura ("leave the receiving agent unselected"). Logo a detecção de fim-de-turno é observação do fluxo de saída — provavelmente quiet-timeout sobre o **modelo de tela VT** que eles já renderizam em Metal, não sobre bytes (spinner redesenhando a cada 100 ms nunca deixaria bytes ficarem quietos).

**O que é genuinamente bom.**
- *Agent-agnostic de graça*: Claude Code fala com Codex porque o canal é o terminal. Zero vendor lock, zero chave.
- *Partitura*: o grafo (terminais, papéis, notas, conexões) serializado em JSON legível, **sem** scrollback, **sem** caminho absoluto, **sem** config de runtime. Peko: "é exatamente 'o grafo é o artefato versionável'". Ailla: "é validação independente do `graphs/*.yaml` do dono, inclusive na parte difícil — **o que deliberadamente não entra no arquivo**".
- *Cabo como ACL de contexto*: o agente só alcança as notas/fichários em que está plugado. Topologia recortando contexto — é graph engineering de verdade, não decoração.
- *Floors*: conflito de escrita paralela resolvido na camada de filesystem (APFS copy-on-write + branch espelhada), não na camada de protocolo. É `git worktree` com clone barato.

**O que torna especial, em uma frase (Ailla):** *não construiu protocolo nenhum — instalou o contrato dentro de cada CLI e usou o PTY como transporte, o que o deixa agent-agnostic de graça e refém de heurística para sempre.*

**Onde é frágil.** Um agente **parado pedindo permissão** tem exatamente a assinatura de tela de um agente **que terminou**: o Maestri devolve a pergunta como se fosse a resposta. Além disso: alt-screen trunca resposta longa pelo tamanho da janela; dois escritores no mesmo fd (humano + orquestrador) forçam a regra de foco a virar regra de produto; e `MAESTRI_TOKEN` vive no env de um shell que o agente controla — protege contra outro terminal, **não** contra conteúdo malicioso lido do repo.

### 1.2 Grok Bot

**O mecanismo.** Frota de agentes nomeados, cada um com computador próprio na nuvem, sempre ligado. A coordenação tem duas faces: **group chat** (transcript compartilhado onde N bots leem, escrevem e passam ownership, chamando o humano só em judgment call) e **roteamento por descrição** — "it scans the descriptions of other agents in your fleet and routes the request to whichever one matches". É o mecanismo de seleção de skill apontado para o roster.

**O que torna especial (Ailla):** *apagou o grafo estático — a aresta não é declarada, é resolvida em runtime pelo modelo lendo a descrição dos outros.*

**O que é genuinamente bom.** Delegação com um endereço só; o humano não roteia. Triggers de **evento** (Slack, GitHub, Teams) — que é justamente o que falta no Maestri. E a hierarquia chief-of-staff → especialistas já cabe num grafo com nó supervisor, sem feature nova.

**Onde é frágil.** Alex: *"group chat é a melhor interface de entrada e a pior de saída"*. A unidade é a mensagem, não a entrega; o roteamento é não-determinístico e não fica gravado como aresta comparável entre execuções; e a sala **premia conversa** — bots concordando entre si é contexto queimado a O(n²). Peko acrescenta o número: mensagem em linguagem natural entre agentes consome **40–60% do orçamento de tokens** de um MAS (arXiv:2608.25277), e **76% das falhas multi-agente são inter-agent misalignment** — que sistemas single-agent têm em 0% por construção.

### 1.3 Hermes Agent

**O mecanismo.** Loop Think-Act-Observe com `IterationBudget` por agente, toolsets como perfil de capacidade, `trajectory_compressor` que protege head/tail e comprime o meio, session store SQLite WAL + FTS5, memória file-backed (`MEMORY.md`/`USER.md`) congelada no system prompt, subagents isolados que chamam tools via **RPC dentro de um script Python** — colapsando pipelines multi-step em turnos de "zero custo de contexto" — e abstração de ambiente com 6 backends atrás de uma assinatura só.

**O que torna especial (Ailla):** *promoveu "quanto um agente pode gastar" e "o que ele pode tocar" a **objetos de primeira classe**, em vez de deixar os dois como efeito colateral do prompt.*

**O que é genuinamente bom, e que já temos de graça.** Ailla executou e comprovou que o equivalente do `IterationBudget` **já existe no nosso runtime**: `--max-budget-usd` corta de verdade (`exit 1`, `subtype: "error_max_budget_usd"`, `terminal_reason: "budget_exhausted"`) `[V]`; e `--allowedTools`/`--disallowedTools` por nó são os toolsets do Hermes em uma linha de YAML. O que é peso morto para nós: compressor de trajetória (o contexto não é nosso — vive dentro do Claude Code), SessionDB, gateway, MCP embutido. E o que é **perigoso**: skills auto-criadas — um nó que reescreve as próprias instruções destrói a reprodutibilidade, que é a única coisa que dá comparação entre execuções.

### 1.4 A tabela que a mesa fechou

| | Maestri | Grok Bot | Hermes |
|---|---|---|---|
| **Onde mora o time** | canvas macOS, partitura em `~/.maestri` | nuvem xAI | processo local / Docker / SSH / Modal |
| **O que é uma aresta** | cabo desenhado → skill instalada nos dois CLIs | frase em inglês resolvida em runtime | chamada de função dentro de um script |
| **Transporte** | PTY (ida via bridge HTTP local) | transcript compartilhado | RPC in-process |
| **Fim de turno** | heurística de tela | fim de mensagem | retorno de função |
| **Contexto recortado por** | quais notas estão plugadas | job description | toolset |
| **Parada** | o humano olhando | o humano olhando | `IterationBudget` |
| **Versionável no repo do projeto** | não (`~/.maestri`) | não | n/a |
| **Mede se valeu a pena** | **não** | **não** | **não** |

A última linha é a que Baldi transformou em posicionamento.

---

## Rodada 2 — os choques

### D1 · Construir o runtime, ou medir antes? — **Baldi contra a mesa**

Baldi abriu com o caso da morte e não foi retórico:

1. A categoria já teve a onda de consolidação: **214+ orquestradores ativos**; Terragon fechou jan/26, Crystal descontinuado fev/26, Vibe Kanban perdeu a empresa em abr/26, Plandex em manutenção.
2. O Claude Code já entrega nativo: **Agent Teams** tem mailbox JSON por agente, task list com *file locking*, grafo de dependências e hooks `TaskCreated`/`TaskCompleted`/`TeammateIdle` que podem sair com código 2 para **rejeitar** uma transição — um quality gate determinístico. "A SPEC v0 não tem uma primitiva que eles não tenham."
3. A premissa econômica está numa **moratória, não numa garantia**: 20/02/2026 a Anthropic baniu OAuth de assinatura fora do Claude Code; 14/05 anunciou mover `claude -p` e o Agent SDK para pool de créditos separado; 15/06 **pausou**, prometendo reformular. "Zero API key" é dependência de política de preço de terceiro.
4. E o golpe local: a retro de 30/08 recolheu o arquiteto por entregar "588 linhas de spec e 0 de código executável na janela cujo gargalo é escrita". O repo hoje é 6,5 KB de spec e 312 bytes de YAML.

Peko chegou ao mesmo lugar por outro caminho, e é o achado mais desconfortável da mesa: **a literatura diz que o grafo de 2 nós provavelmente perde para um `claude -p` só.** Colocar o procedimento inteiro no system prompt bate LangGraph em **15/15 comparações** com o mesmo modelo, com taxa de falha 24% vs 11,5%, e orquestração custa 1,2–1,7× mais chamadas (arXiv:2604.27891). CoT-SC bate MAS automático em 5 benchmarks a 1/10 do custo (2606.13003). E o ganho de MAS **encolhe conforme o modelo fica forte** — o β do information bottleneck cresce com a capacidade (2607.16133); a collaboration tax é positiva em quase toda célula e decrescente com capacidade (2608.22152).

**Resolução da mesa.** O baseline não é uma etapa do roadmap — é a **primeira coisa que o runtime roda**. `baseline:` vira campo obrigatório do grafo (Peko, R0) e o braço de controle vira parte do produto, não do experimento. Ninguém na mesa defendeu construir sem baseline.

**O que a mesa não concedeu a Baldi.** Ele quer que o experimento **substitua** o runtime (108 runs em bash puro, sem uma linha de `orch`). A objeção prática de Ailla: sem harness, os 108 runs são executados à mão, e a variável "como a sessão foi conduzida" fica sem controle — que é exatamente o que a banca vai atacar. A síntese que ficou: **o MVP é o instrumento do experimento**, cortado até caber (~250 linhas até "roda de verdade"), e nada além disso entra antes do veredito.

### D2 · `DONE.md` é critério de parada? — **Peko contra a SPEC v0**

Peko: não. É uma alegação do modelo.

> IAL-SCAN varreu **6.549 repositórios** e confirmou **68 loops infinitos** em 47 projetos: **100% têm a mesma causa raiz — ausência de bound forte**, e "model-controlled termination" aparece em **38,2%** classificado explicitamente como *não-bound* (arXiv:2607.01641). Um `finish_reason` produzido pelo modelo não é um bound.

Ailla chegou ao mesmo buraco pelo lado do processo, e com teste executado:

> `claude -p` em permission-mode default, pedindo um Write: **`exit 0`, `is_error: false`, `subtype: "success"` — e o arquivo não existe.** `permission_denials[]` populado. `[V]`

Duas tecnologias, um erro: o Maestri lê "terminou" numa tela que na verdade está pedindo permissão; um orquestrador ingênuo lê `exit 0` num processo que não escreveu nada.

**Resolução — o consenso mais forte da mesa.** A conclusão de um nó é uma **conjunção de quatro**: `rc == 0` **E** `is_error == false` **E** `permission_denials == []` **E** `verify(artefato)`. E a parada da **sessão** sobe um degrau: só um nó do tipo `check` — comando determinístico, zero LLM — pode aparecer no `stop`. `DONE.md` sai do critério de parada. A sessão para porque um comando saiu 0.

### D3 · PTY ou headless? — **Ailla, sem oposição**

Escolhida: `claude -p --output-format stream-json --verbose`. Descartada: PTY com detecção de fim-de-turno.

O motivo não é gosto, são os testes: no `-p` chegam exit code, EOF determinístico e um `result` com `is_error`, `subtype`, `terminal_reason`, `num_turns`, `total_cost_usd`, `permission_denials[]` `[V]`. O PTY daria pixels e um cronômetro. Custo assumido: perde slash-command no filho, perde attach humano, perde responder a um prompt de permissão no meio. Ganho: a parada de cada nó é uma expressão booleana sobre dados.

PTY volta depois **como camada de observação** (`claude --bg`, `claude logs <id>`, `claude attach <id>` já existem) — e a regra que fica escrita: *observação nunca vira decisão.*

**Descoberta lateral que muda uma decisão:** `--bare` é a flag que mais parece "modo hermético" e é exatamente a que **quebra a restrição de zero API key** — o próprio help diz que a auth passa a ser estritamente `ANTHROPIC_API_KEY` e que OAuth nunca é lido. Proibida por escrito. O knob correto é `--safe-mode` + `--setting-sources` + `--strict-mcp-config` `[V]`.

### D4 · Canvas ou feed? — **Alex, sem oposição**

Alex recusou copiar o canvas, e não pela stack:

> Canvas é a metáfora errada para o problema que sobrou. O que falta não é **ver** a topologia; é saber, às 8h, o que o time fez das 23h às 8h, quem está travado e onde está a bola. Canvas não tem eixo do tempo, não tem fila, não tem inbox — a prova é que o Maestri precisou inventar o **Ombro** (um LLM on-device narrador) para tapar um buraco que um feed cronológico resolve de graça. E o attention dot + `Ctrl⇧A` são uma fila de emergência colada num paradigma que não previa fila, com teto confessado de 9 terminais.

**A metáfora escolhida: canal por sessão, thread por artefato, feed append-only.** Não sala por agente (agente é recurso, não assunto — quando troca o dono, a conversa sobre `handoff.md` deveria continuar). Não canal plano (duas frentes viram fio entrelaçado em 20 minutos). O artefato é a unidade porque a `SPEC.md` **já decidiu isso** — a aresta é `artifact: handoff.md`; a thread só dá nome ao que já existe. E porque artefato tem dono único e verificável, é diffável, e fecha por predicado — coisa que nenhum chat humano jamais conseguiu.

E o equivalente honesto do Ombro: `orch since 23:00` é um `GROUP BY` determinístico sobre o bus. "Maestri precisou de Apple Foundation Models on-device para produzir um parágrafo pior que essa tabela."

### D5 · Quanto paralelismo? — **Peko (teto 3) × Ailla (default 1)**

Peko trouxe o teto da literatura: réplicas 1→3 ganham, **3→5 é marginal ou negativo**; paralelismo estrutural agressivo *derruba* acurácia de 28% para 25% (TIPEX, 2608.05791). Anthropic e a doc de agent teams convergem em 3–5, com "três focados batem cinco espalhados". Cap **duro no schema**, não no prompt.

Ailla verificou que tecnicamente funciona (3× `claude -p` concorrentes, cwds distintos, 3 artefatos corretos, 10 s `[V]`; `git worktree` ×2 `[V]`; `wait -n` `[V]`) — e mesmo assim pediu **default 1, paralelo opt-in explícito**. O motivo não é técnico:

> O risco que mais ameaça este produto não é técnico, é ToS: uma frota headless numa assinatura de consumidor é exatamente o padrão que a plataforma mede. E ela **me conta**: `rate_limit_event` traz `unifiedWindows.five_hour.utilization`, `seven_day.utilization` e `resetsAt` em epoch `[V]`.

**Resolução.** Teto de schema 3 (Peko) **e** default de execução 1 (Ailla) — não se contradizem: um limita o que pode ser declarado, o outro o que sobe sem o dono pedir. Mais a política que ninguém esperava poder escrever: `utilization > 0.85` degrada concorrência para 1; `> 0.95` dorme até `resetsAt`; **nunca retry cego em 429**.

E as quatro travas de Peko para o fan-out, todas checáveis **antes** de subir nó: `max: 3`; `writes` das instâncias disjuntas (sobreposição = grafo inválido, não corrida em runtime); ramos não se comunicam, toda convergência passa pelo `join`; e toda interface entre ramos tem dono nomeado. A falha que sustenta a última: um cálculo de 8 passos com 1 passo por agente falhou **10/10 runs** numa convenção de arredondamento que ficava na fronteira entre dois donos e não pertencia a ninguém — discutida todo run, nunca resolvida (2608.16801).

### D6 · Time auto-gerenciado é recrutar? — **Peko contra o Maestro Mode**

O Maestro Mode do Maestri recruta agentes, atribui papéis e dispensa. Peko: auto-gestão **não é recrutamento**, é reparo estrutural limitado.

- MANTA: mutação de topologia com **≤3 operações**, aplicadas por **código determinístico a uma cópia e validadas antes de comitar**; a **primeira mutação captura a maior parte do ganho**; e o planejamento inicial da topologia vale mais que a mutação (71,7→57,5 vs →60,8). Dos 5 reparos observados, **só um aumenta o sistema** — os outros serializam, religam aresta ou inserem um crítico.
- E o dado que mata o instinto de nomear um líder: medido em **1.902 runs de Claude Code**, nomear um coordenador por prompt produz **0 de 1.170 arestas de hub** e nenhum ganho de sucesso (2608.16801). Hierarquia tem que estar no grafo — quem lê o quê, quem escreve o quê — não no adjetivo do prompt.
- Corolário direto contra o Maestri: o Maestro Mode "tende a recrutar cópias de si mesmo" e essa é a **pior** composição — pares heterogêneos são puxados para o membro forte, não para a média (OLS y = 1,35x − 0,27; 2608.22152). Misturar `claude` num nó e `cursor-agent` no outro é gratuito aqui e é melhor que clonar.

**Resolução.** Auto-gestão = catálogo fechado de 4 operações (`insert_check`, `serialize`, `rewire`, `split`), **1 mutação por sessão**, aplicada por código a uma cópia, validada (`max_nodes`, `disjoint_writes`, `every_cycle_bounded`, `stop_reachable`) e só então comitada. Loop infinito fica impossível por construção: mutação ≤1, ciclo ≤`max_repeats`, sessão ≤`wall_seconds`, failsafe incondicional.

### D7 · O que a Anthropic já entrega mata o projeto? — **Baldi × Ailla**

Baldi: Agent Teams tem mailbox, lock, dependências e hooks de gate — e o `-p` te tranca fora disso, porque a doc diz que em modo não-interativo "Claude doesn't spawn teammates". "Você está construindo um orquestrador de times feito de agentes que, por construção, não podem ter time."

Ailla aceitou o fato e leu ao contrário: é **por isso** que o orquestrador é externo. O nó não precisa ter time — o nó é um membro. E há três coisas que o Agent Teams não dá e que Baldi mesmo documentou: a config **não pode ser pré-autorada nem versionada** (o doc diz textualmente que não há equivalente em nível de projeto e que edição à mão é sobrescrita), é experimental atrás de env var, e não mede nada.

**Resolução.** Não é concorrência de primitivas, é concorrência de camada: eles orquestram **dentro** de uma sessão; nós orquestramos **sessões**. E a única razão de fazer isso é o que nenhum dos dois faz — comparar duas topologias e devolver um número.

---

## Rodada 3 — onde está o oceano azul

Baldi rejeitou três diferenciais na cara:

- ❌ *"É open-source e roda no terminal."* Há 15 TUIs open-source na lista de 214. É linha de base, não eixo.
- ❌ *"Roda em Linux."* Checkbox.
- ❌ *"Grafo YAML de nós e arestas."* CrewAI faz config YAML de papéis há anos.

E avaliou os quatro candidatos sérios:

| Candidato | Veredito |
|---|---|
| **(a)** sessão como time auto-gerenciado | **morto** — é textualmente Agent Teams + Maestro Mode, dois fornecedores com equipe dedicada |
| **(b)** portabilidade entre harnesses | **comoditizada** — `AGENTS.md` já é o terreno comum; Maestri e Claude Squad já são agent-agnostic. Vira requisito de desenho, não pitch |
| **(c)** zero cloud / zero API key | **risco disfarçado de moat** — Maestri já faz zero telemetria/conta/nuvem, e o "diferencial" depende da moratória de preço de terceiro. Restrição operacional legítima, não proposta de valor |
| **(d)** grafo versionado no repo | **buraco real, admitido pelo fornecedor** — mas copiável numa tarde. É substrato, não categoria |
| **(e)** **medição de sessão** | **ninguém faz, e é caro de copiar** |

O argumento de (e): as ferramentas de observabilidade (Arize, MLflow, Braintrust, Galileo) medem **spans de chamada de LLM** e pressupõem que você instrumenta a API — o que a restrição dura proíbe e o que nenhum usuário de assinatura pode fazer. E mesmo com toda a instrumentação, a literatura de 2026 admite que quantificar **qualidade de coordenação** continua em aberto.

> **A frase que a tabela competitiva revela:** as 15 colunas competem em *como você vê os agentes* — canvas, kanban, tmux, painel. Nenhuma compete em *como você sabe que valeu a pena*. **Todo mundo vende um painel. Ninguém vende um veredito.**

**Posicionamento aceito pela mesa:**

> Você declara o time num arquivo versionado, roda a mesma tarefa com dois times diferentes, e recebe um número dizendo qual dos dois funcionou — **inclusive o número que diz que nenhum funcionou e que um agente solo era melhor**.

Categoria: **banco de provas de topologia de time**. O concorrente mental é `pytest`, `hyperfine`, `git bisect` — instrumento que produz veredito, não painel que produz sensação.

Peko chegou ao mesmo lugar pelo lado da pesquisa, e com uma tese de reserva que vale registrar: se R0 mostrar que o grafo perde para o solo, o valor do repo **não** é "time bate agente sozinho" — é **contrato de escrita, orçamento e parada verificável rodando acima de CLIs que não têm nada disso**. Nenhum dos três (Maestri, Grok Bot, Hermes) implementa os três juntos.

---

## O consenso — 14 pontos que entram no MVP

Nenhum desses ficou contestado ao fim da mesa.

1. **Headless, não PTY.** `claude -p --output-format stream-json --verbose`. Exit code é sinal de controle; tela não é.
2. **A conclusão de um nó é conjunção de quatro** (`rc`, `is_error`, `permission_denials`, `verify(artefato)`). `exit 0` sozinho mente — testado.
3. **Só `check` determinístico pode parar a sessão.** Texto do modelo nunca é bound.
4. **Três camadas de bound**, a última incondicional: gate verificável → no-progress por hash → failsafe de budget.
5. **Artefato é o canal.** Sem bus, sem chat livre entre nós, sem broadcast.
6. **Contrato de escrita por nó** (`reads:`/`writes:` em globs), verificado por diff de árvore. Escreveu fora → nó falha.
7. **Toda interface entre nós tem dono declarado.**
8. **Fan-out ≤ 3 no schema, concorrência default 1 na execução**, com gate por `utilization` da janela da assinatura.
9. **Baseline obrigatório**: todo grafo compete contra 1 nó com o procedimento inteiro no prompt, na mesma tarefa.
10. **Auto-gestão = reparo estrutural limitado**: catálogo fechado de 4 operações, 1 mutação por sessão, aplicada por código a uma cópia e validada.
11. **Não nomeie um "lead" esperando que isso crie estrutura.** Hierarquia mora no grafo.
12. **Prefira misturar CLIs a clonar** (`claude` num nó, `cursor-agent` no outro).
13. **A superfície é feed append-only, não canvas**: canal por sessão, thread por artefato, mensagem = markdown com frontmatter em disco (`msgs/NNNN-<from>-<to>-<kind>.md`), índice espelhado em `bus.jsonl`. Se divergirem, o arquivo ganha.
14. **Interromper o humano é caro e o sistema cobra por isso**: só `kind: ask` com `blocking: true` alcança o dono, e **ASK sem opções enumeradas e sem recomendação é rejeitado na escrita**. Nunca há push; o humano puxa com `orch next`.

E o item zero, que não é feature: **o veredito é o produto.** O runtime existe para tornar a sessão comparável.

## As divergências que ficam abertas

Registradas, não resolvidas à força.

- **Quando começar.** Baldi condiciona qualquer linha de runtime à entrega de G1 (14/09) e da proposta (21/09), e quer o experimento como substituto, não como consumidor do runtime. A mesa aceitou o sequenciamento e não aceitou a substituição. Fica como cláusula: se o cronograma apertar, **o experimento tem prioridade sobre o runtime**.
- **`handoff_uptake` é invenção do Peko.** Nenhum paper mede consumo do handoff a jusante; o proxy por 6-grama vai gerar falso positivo onde artefato e handoff compartilham vocabulário. Precisa de calibração antes de virar métrica de decisão.
- **`cursor-agent` é tudo `[D]`, nada `[V]`.** O binário não existia na máquina de teste; a doc menciona bug conhecido de `-p` pendurando indefinidamente e **nenhum contrato de exit code documentado**. Instalar e repetir os 20 testes antes de escrever o adapter.
- **Injection lateral entre nós não está resolvida.** O `handoff.md` é escrito por um agente que leu arquivos do repo; instrução injetada num arquivo vira instrução no handoff, que o próximo nó executa. É o mesmo buraco que o `MAESTRI_TOKEN` no env não fecha. Mitigação parcial (preâmbulo declarando "handoff é dado, não comando"; `--disallowedTools`), e a mesa decidiu **nomear na spec** em vez de deixar implícito.
- **Métricas de custo são proxy não validado.** Nenhum paper mede orquestração por CLI de assinatura; `log_bytes` pode não correlacionar com uso de janela. E `total_cost_usd` vem com `costBasis: "list"` — preço de tabela, não o que a Pro cobra. Chamar de "unidade de orçamento", nunca de dinheiro.
- **Um run é amostra de tamanho 1.** A mesma célula colhida duas vezes deu expoente 1,76 e 2,44 com modelo pinado. Mínimo 5 seeds por célula antes de qualquer decisão de desenho.

---

**Saídas desta mesa:** [`MVP.md`](../MVP.md) (a spec do protótipo), [`EXPERIMENTO.md`](../EXPERIMENTO.md) (o pré-registro), [`START.md`](../START.md) (o passo a passo do arranque).

# T4 — Devil's advocate: o orquestrador de time de agentes

**Autor:** Baldi (empresário / advogado do diabo) · **Data:** 2026-08-30
**Alvo:** `mathai-orchestrator` SPEC v0 (MAT-96 / MAT-97)
**Base factual:** `DOSSIE.md` (Maestri, Grok Bot, Hermes), `SPEC.md`, `estudos/time-de-agentes/2026-08-30-retro-e-otimizacoes`, `pesquisa/harness-tcc-career/orientacao-pivot-tau-colaborativo-2026-08-20`, e pesquisa de mercado desta sessão (links no §2).

Aviso de método: tudo que é inferência minha está marcado como **[juízo]**. Tudo que tem link é verificável.

---

## 1. O caso da morte

### 1.1 A categoria já teve a onda de consolidação — e você está chegando na ressaca

O `awesome-agent-orchestrators` lista **214+ orquestradores ativos**, distribuídos em 15 TUIs de terminal, 60+ apps desktop/web, 27 "swarms" multi-agente, 10 loop runners e 18 task runners ([lista](https://github.com/andyrewlee/awesome-agent-orchestrators)). Isso não é um mercado nascente. É uma categoria saturada onde a diferenciação já se esgotou.

Pior: a onda de **morte** já começou.

- **Terragon** fechou em **janeiro/2026**.
- **Crystal** foi **descontinuado em fevereiro/2026**, redirecionando usuários para Nimbalyst.
- **Bloop**, a empresa do **Vibe Kanban**, anunciou shutdown em **10/04/2026**; o projeto sobrevive como Apache-2.0 mantido pela comunidade, com as features de nuvem removidas ([Nimbalyst](https://nimbalyst.com/blog/vibe-kanban-after-bloop-whats-next/)).
- **Plandex** está sem commits desde outubro/2025, em modo manutenção ([State of CLI Coding Agents, Mid-2026](https://blog.arcbjorn.com/state-of-cli-coding-agents-2026)).

Quando produtos com funding, equipe e distribuição morrem numa categoria, um projeto solo de fim de semana não é "entrada tardia com vantagem de foco". É entrada tardia. **[juízo]** A pergunta que a existência desses cadáveres levanta não é "como me diferencio?", é "por que exatamente eles não conseguiram sustentar isso?" — e a resposta mais provável é que o valor do painel de orquestração é raso e o custo de manutenção é alto.

### 1.2 O v0 inteiro é uma feature de plataforma que a Anthropic já entrega — e melhor

Leia a SPEC e o doc de Agent Teams lado a lado ([code.claude.com/docs/en/agent-teams](https://code.claude.com/docs/en/agent-teams)):

| SPEC v0 | Nativo no Claude Code hoje |
|---|---|
| nós = agentes com role e prompt | subagent definitions reutilizáveis como teammates (`tools`, `model`, body) |
| arestas = handoff com predicado `artifact_exists` | **mailbox JSON** por agente + **task list compartilhada** com dependências e **file locking** contra corrida |
| `state.json` com status por nó | task list persistida, estados pending/in-progress/completed, dependências desbloqueadas automaticamente |
| parada por `DONE.md` | hooks `TaskCompleted`, `TeammateIdle`, `TaskCreated` — exit 2 devolve feedback e mantém o agente trabalhando |
| serial, 2 nós | N teammates, self-claim de tarefa, comunicação peer-to-peer sem passar pelo lead |
| logs por nó em arquivo | painel de agentes, transcript por teammate, split panes em tmux/iTerm2 |

O seu handoff — "o arquivo existe, então o próximo sobe" — é a versão de 2023 do que a Anthropic implementou com **lock de arquivo e grafo de dependências**. E o Cursor 3 entrega **até 8 agentes paralelos com worktree nativo e branch dedicada por agente**, mais `/multitask` para fan-out, mais `cursor-agent -p` headless ([Cursor CLI](https://www.learncursor.dev/guides/cursor-cli), [Cursor 3 deep dive](https://www.digitalapplied.com/blog/cursor-3-deep-dive-agents-composer-review-2026)).

**Na cara, como pedido: sim. A Anthropic e o Cursor já entregam nativo o que o MVP pretende.** O MVP não tem uma primitiva que eles não tenham, e tem várias que eles têm e ele não.

### 1.3 A premissa econômica do projeto está numa moratória, não numa garantia

Esta é a mais séria, e ela ataca a **restrição dura** da SPEC ("zero API key, `claude -p` na assinatura Pro").

- **20/02/2026** — a Anthropic atualizou o doc de "Legal and compliance" para proibir tokens OAuth de Free/Pro/Max **em todo contexto fora do Claude Code e do claude.ai**; terceiros passam a exigir API key do Console ([alternativeto](https://alternativeto.net/news/2026/2/anthropic-officially-bans-using-subscription-authentication-for-third-party-claude-use)).
- **14/05/2026** — anúncio de que uso de Agent SDK e de `claude -p` sairia da cota da assinatura para um **pool de créditos separado** em dólar, dimensionado pela mensalidade.
- **15/06/2026** — a mudança foi **pausada**, com a empresa dizendo que vai "reformular o plano" e dar "aviso prévio antes de qualquer mudança futura" ([DigitalApplied](https://www.digitalapplied.com/blog/anthropic-claude-credit-overhaul-june-15-2026)).

Traduzindo: o fornecedor **tentou cobrar separado exatamente o modo de uso em que seu produto inteiro se apoia**, recuou por pressão, e prometeu voltar reformulado. Você está construindo a fundação numa cláusula que o proprietário do terreno já anunciou que quer mudar.

Note ainda que rodar o binário oficial `claude` a partir de um script é a zona cinzenta — `claude -p` é entrada não-interativa oficialmente documentada, então **[juízo]** não é violação hoje. Mas "não é violação hoje" é uma frase com data de validade, e um repo público chamado "orquestrador que roda seu time no plano Pro" é literalmente uma placa de neon apontando para o comportamento que eles tentaram monetizar. Você não é grande demais para ser quebrado; você é pequeno demais para ser avisado.

### 1.4 O `-p` te tranca fora da primitiva mais valiosa da plataforma

Do doc oficial, textualmente:

> "Spawning teammates also requires an interactive session. In [non-interactive mode](/docs/en/headless) with the `-p` flag, including Agent SDK sessions, Claude doesn't spawn teammates."

A SPEC escolhe `-p` explicitamente ("Custo: perde slash-commands... Ganho: o orquestrador consegue esperar exit code"). O custo real não é slash-command: é que **cada nó do seu grafo é um agente solo permanentemente incapaz de formar time**. Você está construindo um orquestrador de times feito de agentes que, por construção, não podem ter time. Cada nó vira um bloco burro que só sabe começar e terminar. Toda a inteligência de coordenação precisa ser reimplementada por você, do zero, contra um fornecedor que já a implementou melhor e a dá de graça na modalidade que você recusou.

### 1.5 Manutenção eterna contra superfícies que você não controla

Você depende de: o binário `claude` e suas flags, o `cursor-agent` e as dele, o formato de auth de dois fornecedores, os limites de cota de dois fornecedores, e o comportamento de exit code de ambos. A própria SPEC já admite a fragilidade: *"Se o CLI `claude -p` mudar de flag, emenda datada neste SPEC.md antes de adaptar o código."*

Isso é uma regra de processo bonita para um problema que não se resolve com processo. Só o doc de Agent Teams registra mudanças de comportamento nas versões **2.1.178, 2.1.179, 2.1.181, 2.1.186, 2.1.198, 2.1.199, 2.1.207, 2.1.234** — flags removidas (`teammateDefaultModel`), tools deletadas (`TeamCreate`, `TeamDelete`), campos depreciados. Esse é o ritmo de churn de **uma** feature de **um** dos dois CLIs que você quer suportar. **[juízo]** Um wrapper de CLI de terceiro é dívida técnica com juros pagos pelo mantenedor, para sempre, sem receita.

### 1.6 O mercado endereçável é você e umas 200 pessoas

Quem tem, ao mesmo tempo: (a) assinatura Claude Pro/Max, (b) desconforto suficiente com Agent Teams nativo para procurar alternativa, (c) preferência por Linux/terminal sobre macOS/canvas, (d) tolerância a YAML de grafo escrito à mão, e (e) disposição para confiar num repo pessoal com histórico de zero releases? Esse é o TAM. Os concorrentes com esse mesmo perfil de usuário estão listados como 15 TUIs de terminal na cauda longa da lista de 214, e nenhum deles tem tração visível.

E os que **têm** perfil de usuário mais largo já perderam: o Conductor é **grátis** no uso local em macOS ([Nimbalyst comparativo](https://nimbalyst.com/compare/nimbalyst-vs-conductor-vs-vibe-kanban/)) e o Maestri é **US$18 vitalício**. O preço de referência da categoria é aproximadamente zero. Não existe negócio aqui. Existe, no máximo, um portfólio.

### 1.7 Você não quer um produto — você quer um post, e o seu próprio vault já provou isso

Esta é a mais dura e é a que eu defenderia numa banca.

A retro de **30/08/2026** (quatro dias atrás, escrita por este time) diz, sobre o arquiteto:

> *"Subiu com condição falsa e entregou **588 linhas de spec e 0 de código executável** na janela cujo gargalo é escrita."* — veredito: **recolher até 21/09**, com exceção datada só para a simulação do piso de ruído até 14/09.

E a SPEC do orquestrador é... mais spec. É um artefato de 6.577 bytes, com `graphs/v0.yaml` de 312 bytes e dois prompts de ~300 bytes, produzido pelo mesmo padrão que a retro condenou por medida própria quatro dias atrás. A MAT-97 ("implementa") existe como issue e não como código.

Some a isso: **G1 em 14/09**, **proposta em 21/09**, cinco perguntas do orientador ainda sem resposta escrita (§2 do pivô), o related work mais próximo — arXiv:2604.17883, *Governable Consensus Layer* — **ainda não lido na íntegra**, e a Frente 1 do TG já redefinida como "ler e mapear `tau_agent`". Construir um segundo harness agora não é adjacente ao TG. É **concorrente direto** dele pelo mesmo recurso escasso, que é a atenção do dono em uma janela com banca marcada.

**[juízo]** A hipótese que melhor explica os dados: o orquestrador é uma forma agradável de fazer engenharia enquanto se evita escrever a proposta. O sintoma clássico disso é exatamente o que está no repo — spec excelente, implementação vazia.

---

## 2. Mapa competitivo

| Produto | Metáfora | Onde roda | Como faz handoff | Licença / preço | O buraco que deixa |
|---|---|---|---|---|---|
| [**Claude Code Agent Teams**](https://code.claude.com/docs/en/agent-teams) | time com lead + colegas | local, sessão **interativa** | mailbox JSON por agente + task list compartilhada com file lock e dependências | incluso na assinatura | experimental (env var); **não funciona em `-p`**; config **não pode ser pré-autorada nem versionada** ("no project-level equivalent"); 1 time por sessão; sem times aninhados; lead fixo; sem métrica de resultado |
| [**Claude Code subagents**](https://code.claude.com/docs/en/sub-agents) | delegação pai→filho | dentro da sessão | resultado volta ao pai | incluso | sem coordenação lateral; nada persiste entre runs para comparar |
| [**Cursor 3**](https://www.digitalapplied.com/blog/cursor-3-deep-dive-agents-composer-review-2026) / [CLI](https://www.learncursor.dev/guides/cursor-cli) | agente como unidade de navegação | IDE + nuvem + worktree local | worktree e branch por agente; `/multitask` fan-out; `agent -p` headless | US$20/mês Pro | fechado; lock-in de IDE; sem definição de time versionada; sem veredito de sessão |
| **Maestri** (DOSSIE) | canvas infinito / partitura | macOS 15.4+ (Windows) | **PTY**: um agente digita no terminal do outro, via skill instalada em cada CLI; fim de turno detectado por heurística de foco | US$18 vitalício, 1 workspace grátis | macOS-first; grafo mora em `~/.maestri/partituras`, **fora do repo**; handoff heurístico sem garantia; Routines só por tempo, sem trigger de evento; zero medição |
| [**Conductor**](https://nimbalyst.com/compare/nimbalyst-vs-conductor-vs-vibe-kanban/) | dashboard de worktrees | macOS | worktree isolado por agente; review/merge central | **grátis** local; Pro US$50/mês | macOS; sem grafo declarativo; o humano é o roteador |
| [**Claude Squad**](https://github.com/smtg-ai/claude-squad) | tmux + worktree | terminal, cross-platform | branch por agente; **merge é do humano** | OSS | sem handoff automático; sem grafo; sem medição |
| **Crystal** | app desktop de sessões paralelas | desktop | diffs por worktree | OSS — **descontinuado fev/2026** | morto |
| [**Vibe Kanban**](https://nimbalyst.com/blog/vibe-kanban-after-bloop-whats-next/) | kanban de tarefas de agente | CLI + web local | coluna do board = estado da tarefa | Apache-2.0; **empresa morta abr/2026** | comunidade; nuvem removida; sem medição |
| [ccswarm](https://github.com/nwiizo/ccswarm) / [crew](https://github.com/pikehouse/crew) / [treeai](https://github.com/leecj/treeai_cli) / +200 | variações do mesmo | terminal / desktop | worktree por agente | OSS variado | [cauda longa de 214+](https://github.com/andyrewlee/awesome-agent-orchestrators); **nenhum mede resultado** |
| [**OpenHands**](https://www.openhands.dev/blog/best-coding-agents) | agente autônomo sandboxado | local / CI / nuvem | tarefas paralelas, headless em CI | MIT + custo de API | exige API key — fora da sua restrição dura; é agente, não orquestrador de CLIs de assinatura |
| [**Devin**](https://www.augmentcode.com/tools/best-devin-alternatives) | engenheiro na nuvem | nuvem | PR pronto | US$20–500/mês | fechado, caro, opaco |
| **Grok Bot** (DOSSIE) | frota com computador próprio | nuvem xAI | group chat + roteamento por descrição de agente | dentro de SuperGrok / Cursor | nuvem obrigatória; fechado; só 3 triggers |
| **Hermes** (DOSSIE) | gateway multi-plataforma | local / Docker / SSH / Modal | subagents por RPC dentro de script Python | MIT | é *um harness*, não orquestrador de harnesses; precisa de API compatível |
| **Terragon** | agentes na nuvem | nuvem | — | — | **fechou jan/2026** |
| [Arize](https://arize.com/blog/best-ai-observability-tools-for-autonomous-agents-in-2026/) / [MLflow](https://mlflow.org/articles/what-is-agent-observability-a-2026-developer-guide/) / [Braintrust](https://www.braintrust.dev/articles/agent-observability-complete-guide-2026) / [Galileo](https://galileo.ai/blog/best-multi-agent-ai-evaluation-tools) | traces e spans de LLM | SaaS / OSS | — | pago / OSS | medem **chamadas**, não medem **se o time funcionou**; exigem instrumentar a API — impossível no CLI de assinatura; a própria literatura admite que "quantificar qualidade de coordenação" ainda é lacuna |

**O padrão que a tabela revela:** as 15 colunas competem em **como você vê os agentes** (canvas, kanban, tmux, painel, split pane). Nenhuma compete em **como você sabe que valeu a pena**. Todo mundo vende um painel. Ninguém vende um veredito.

---

## 3. Onde está o oceano azul, se existe

Primeiro, o que eu **rejeito** como diferencial, sem apelação:

- ❌ **"É open-source e roda no terminal."** Há 15 TUIs de terminal open-source na lista de 214. Isso não é um eixo, é a linha de base da categoria.
- ❌ **"Roda em Linux, não só macOS."** Claude Squad, Vibe Kanban, OpenHands e o próprio Claude Code já rodam. É uma checkbox, não uma categoria.
- ❌ **"Grafo YAML de nós e arestas."** CrewAI faz config YAML de papéis há anos; `tmux-ide` já faz "preset agent-team layouts from checked-in config". A ideia não é nova. O que é novo é o **uso** que se faz dela — ver abaixo.

### 3.1 Os quatro candidatos, avaliados

**(a) Sessão como time auto-gerenciado e auditável** — **morto.** É textualmente Agent Teams (self-claim, peer-to-peer, hooks de gate) e Maestro Mode do Maestri (recruta, atribui papel, conecta, dispensa). Dois fornecedores e 27 "swarms" na lista. Não entre.

**(b) Portabilidade entre harnesses (Claude ↔ Cursor ↔ Codex)** — **comoditizada.** `AGENTS.md` já é o terreno comum entre ferramentas ([CrewAI docs](https://docs.crewai.com/en/guides/coding-tools/agents-md)), o Claude Code importa via `@AGENTS.md`, o Maestri já é explicitamente agent-agnostic, e o Claude Squad já suporta Claude Code, Codex, OpenCode e Amp. Você chegaria em quarto lugar num problema já resolvido. **Secundário: é requisito de design, não posicionamento.**

**(c) Zero cloud / zero API key** — **é risco disfarçado de moat.** O Maestri já faz zero telemetria, zero conta, storage local. E, pior, esse "diferencial" é uma dependência da moratória de §1.3: se a Anthropic ressuscitar o pool de créditos separado, o seu diferencial vira o seu obituário. Nunca construa a identidade do produto sobre uma política de preço de terceiro. **Secundário: é uma restrição operacional legítima, não uma proposta de valor.**

**(d) Grafo como artefato versionável no repo** — **é um buraco real, admitido pelo próprio fornecedor.** O doc da Anthropic diz, textualmente: *"There is no project-level equivalent of the team config. A file like `.claude/teams/teams.json` in your project directory is not recognized as configuration"* e *"don't edit it by hand or pre-author it: your changes are overwritten on the next state update."* O Maestri versiona o grafo em `~/.maestri/`, fora do repo. Ou seja: **hoje, a topologia do time não é revisável em PR em lugar nenhum.** Isso é verdadeiro e é bom. Mas, sozinho, é copiável numa tarde — é um parser de YAML e um spawner. Não sustenta uma categoria.

**(e) Medição de sessão** — **ninguém faz, e é caro de copiar.** Observabilidade de agente (Arize, MLflow, Braintrust, Galileo, Latitude) mede *spans de chamada de LLM*: tool call, latência, custo, fidelidade de passo. Ela pressupõe que você instrumenta a API — o que a sua restrição dura proíbe e o que qualquer usuário de assinatura também não pode fazer. E, mesmo com toda a instrumentação, a própria literatura de 2026 admite que **quantificar qualidade de coordenação continua não resolvido**: "capturing emergent behaviors, such as whether Agent A's output format matches Agent B's expected input structure and whether context loss during handoffs caused downstream failures". A academia tem EvoCode-Bench medindo agentes em interação multi-turn ([arXiv:2605.24110](https://arxiv.org/pdf/2605.24110)) — mas isso mede *agentes*, não *topologias de time*.

### 3.2 O eixo primário que eu escolho: **medição**

**Escolho (e), com (d) como substrato obrigatório.** A justificativa da hierarquia é o que importa:

> O grafo versionado existe **para tornar a sessão comparável**. A comparação é o produto.

Sem grafo declarado num arquivo, dois runs não são a mesma coisa e nada é comparável — por isso (d) é obrigatório. Mas se o produto parar em (d), ele é o 215º orquestrador com YAML. O que ninguém tem é a segunda metade: **rodar a mesma tarefa com duas topologias diferentes e devolver um número dizendo qual funcionou.**

Por que (e) e não os outros, em uma linha cada:
- (a) é território de dois fornecedores com equipe dedicada — perdido antes de começar.
- (b) é infraestrutura já comoditizada — vira requisito, não pitch.
- (c) é uma aposta na política de preço de terceiro — vira risco, não moat.
- (d) é copiável numa tarde — vira feature, não categoria.
- **(e) exige desenho experimental, e desenho experimental é exatamente o que o dono está sendo obrigado a aprender para a banca até 21/09.** O eixo primário e o TG passam a se pagar mutuamente em vez de competir por atenção. Esse é o único arranjo em que construir isso não é auto-sabotagem.

### 3.3 Categoria nova

Não é "orquestrador de agentes". É **banco de provas de topologia de time** — controle de qualidade de sessão multi-agente.

O concorrente mental certo não é o Maestri nem o Conductor. É `pytest`, `hyperfine`, `git bisect`: **instrumento que produz veredito, não painel que produz sensação.** Painel você abre; instrumento você roda antes de decidir.

### 3.4 Posicionamento em uma frase

> **Você declara o time num arquivo versionado, roda a mesma tarefa com dois times diferentes, e recebe um número dizendo qual dos dois funcionou — inclusive o número que diz que nenhum funcionou e que um agente solo era melhor.**

Nome de trabalho: não use "orchestrator" no nome. Todo mundo usa. Use algo que declare o veredito (`bancada`, `teamlab`, `topo`).

### 3.5 Para quem NÃO é

- Quem quer **ver** oito agentes trabalhando ao mesmo tempo numa tela bonita. Vá de Maestri ou Conductor.
- Quem quer **entregar mais features hoje**. Um instrumento de medição desacelera antes de acelerar.
- Quem quer **rodar em produção / CI de empresa**, com SSO e retenção. É OpenHands ou Devin.
- Quem não consegue **rodar a mesma tarefa duas vezes**. Sem repetição não existe medida; se todas as tarefas são únicas e irreproduzíveis, este produto não tem o que dizer.
- Quem quer o painel e não quer o veredito. **[juízo]** Se o número disser "seu time de 3 agentes é pior que 1 agente solo", esse usuário vai ficar bravo com o instrumento. Melhor não vendê-lo para ele.

---

## 4. Teste de falseabilidade

### 4.1 A menor coisa que mata o projeto e economiza 6 meses

**Não construa o runtime. Rode o experimento que o runtime existiria para servir.**

O experimento mínimo cabe em ~150 linhas de script bash e não precisa de nenhuma linha do `orch`:

1. **12 tarefas reais**, extraídas de commits já feitos em repos que o dono conhece (a tarefa é o enunciado; o commit real é o gabarito). Congeladas antes de começar, num arquivo, com hash.
2. **Três braços**, mesma tarefa, mesmo modelo, ordem aleatorizada:
   - **A (controle):** um `claude -p` solo.
   - **B:** grafo de 2 nós `scout → builder` com handoff por `handoff.md` — exatamente o `graphs/v0.yaml`.
   - **C:** grafo de 2 nós invertido ou com papéis trocados — o placebo estrutural, para provar que o ganho vem da topologia e não do fato de rodar duas vezes.
3. **3 repetições por braço por tarefa** = 108 runs. Com `claude -p` sequencial isso é uma noite de máquina, não um sprint.

O braço **C** é o que separa isto de teatro. Sem ele, qualquer ganho de B sobre A é explicável por "gastou mais tokens", e a banca vai perguntar exatamente isso.

### 4.2 Critérios numéricos — pré-registrados, escritos antes de rodar

Um critério de sucesso escrito depois do resultado não é critério, é narrativa. Estes ficam num arquivo commitado **antes** do primeiro run, com hash no README.

| Métrica | Como se lê | **Passa se** | **Morre se** |
|---|---|---|---|
| **Retrabalho evitado** (métrica primária) | linhas escritas no braço que são revertidas/reescritas na 2ª passada de extensão ÷ linhas escritas | B bate A em **≥8 das 12 tarefas**, com redução mediana **≥20 pp** | B bate A em ≤6 de 12, **ou** B não se separa de C |
| **Taxa de conclusão** | run termina com o artefato exigido e teste passando | B ≥ A, sem regressão maior que 1 tarefa | B < A em ≥3 tarefas |
| **Custo do handoff** | tokens totais de B ÷ tokens totais de A | ≤ **2,5×** | > 3,5× (aí o ganho não paga o preço, mesmo se existir) |
| **Tempo até primeira sessão útil** | `git clone` → primeiro veredito impresso, cronometrado em **3 pessoas que não são o dono**, sem ajuda | mediana **≤ 15 min**, 3/3 concluem | qualquer pessoa desiste, ou mediana > 30 min |
| **Adoção (só depois do relatório público)** | pessoas que rodaram o experimento **no repo delas** e reportaram o número | **≥ 5 em 30 dias** do post | ≤ 1 (é um brinquedo pessoal — assuma isso e siga) |

Estrela e fork **não entram**. É a mesma régua de `brand/carreira/2026-08-29-decisao-de-foco` §7: alcance sem conversa é vaidade. Cinco pessoas que rodaram e mandaram o número valem mais que 300 estrelas.

### 4.3 A data — e por que ela não é daqui a duas semanas

Duas semanas a partir de hoje (30/08) cai em **13/09**. Isso é a véspera do **G1 (14/09)** e do prazo da simulação do piso de ruído, que é a única exceção datada que a retro concedeu ao arquiteto. Marcar o experimento nessa janela é reproduzir, com nome novo, exatamente a falha estrutural nº 2 da retro: subir frente nova com a condição de entrada falsa.

**Cronograma que eu assino:**

| Data | Entrega | Regra |
|---|---|---|
| **14/09** | G1 + piso de ruído entregues | nenhuma linha de `orch` antes disso |
| **21/09** | proposta entregue **e** pré-registro do experimento commitado (12 tarefas, 3 braços, tabela de §4.2, hash) | o pré-registro é escrito **antes** de existir um resultado |
| **22/09 – 05/10** | os 108 runs + o relatório | duas semanas cronometradas |
| **06/10** | **veredito** | passa nos critérios → MAT-97 vira instrumento; falha → o repo vira o relatório e o projeto morre em público, com número |
| **16/10** | submissão a CFP | já é métrica existente do vault (editor, `brand/talks/`) — o relatório é o abstract |

**A cláusula que torna isso honesto:** se o dono não aceitar esperar até 22/09, então o experimento **substitui** a implementação, não a antecede. Nada de MAT-97, nada de runtime, nada de `state.json`. Só bash, só os três braços, só o número. **[juízo]** O caminho mais rápido para descobrir se este projeto merece existir não passa por construí-lo.

---

## 5. Valor de carreira

### 5.1 O ativo não é o código. É o número.

Repositório de orquestrador é commodity — há 214 deles e ninguém contrata por causa de mais um. **Relatório com pré-registro, braço de controle e resultado negativo aceito é raro** — inclusive dentro da própria literatura de agentes, que é notoriamente pobre em baselines honestos.

Se o experimento **falhar**, o produto de carreira é: *"Pré-registrei uma hipótese sobre topologia de time de agentes, rodei 108 sessões controladas com placebo estrutural, e o time de dois nós não bateu o agente solo. Aqui está o método, aqui estão os dados, aqui está o que eu faria diferente."* Isso é mais empregável que um repo funcional com 3 estrelas, e é literalmente o comportamento que a banca do TG cobra.

### 5.2 Conexão com o TCC — direta, não forçada

O pivô de 20/08 põe o TG em **governança de código colaborativa sobre o tau**, com cinco perguntas do orientador ainda em aberto (§2), das quais **três são exatamente o que este experimento é obrigado a responder para existir**:

- *"como o projeto é especificado durante o experimento — existe um `log.md`, um conjunto de tasks registrado?"* → **é o grafo versionado + o pré-registro.** A resposta vira arquivo, não argumento.
- *"qual o ponto de virada, precisamente?"* → **é a 2ª passada de extensão** da métrica de retrabalho. O ponto de virada deixa de ser retórico e vira uma coluna na planilha.
- *"greenfield de verdade"* → o desenho de §4.1 (tarefa de commit existente, gabarito conhecido, ordem aleatorizada) é a resposta defensável que o orientador rejeitou na primeira tentativa.

E o braço **C**, o placebo estrutural, é a resposta antecipada para o "Jordão" da banca. Não existe versão dessa pergunta que ele não faça.

Sobre o related work: os quatro papers do §4 do pivô — [2604.17883](https://arxiv.org/abs/2604.17883), 2512.02329, 2606.22484, 2603.25928 — atacam **política e norma** (quem pode fazer o quê). O experimento aqui ataca **medida** (a topologia mudou o resultado?). Isso é diferenciação de mecanismo, não de vocabulário. **Ressalva honesta:** isso só se sustenta depois da leitura integral de 2604.17883, que continua pendente e é Prioridade 0 do próprio pivô. Se aquele paper já mede topologia, este ângulo morre e eu quero saber antes de 21/09, não depois.

### 5.3 Conteúdo público — três peças, nenhuma sobre o produto

1. **"Rodei 108 sessões de agente para descobrir se time de dois é melhor que agente solo. Não é / é, e o número é X."** — resultado, com dados. Passa por `post-voice`.
2. **"A Anthropic não deixa você versionar a topologia do seu time. Aqui está o parágrafo do doc."** — achado técnico verificável, com a citação literal. É o tipo de post que circula porque é checável em dez segundos.
3. **"O que 214 orquestradores de agente não medem."** — o mapa competitivo do §2, publicado. Já está 80% escrito acima.

Nenhuma das três é "lançei meu projeto". As três são "descobri um número". **[juízo]** A segunda categoria é a que gera conversa nomeada, que é a métrica que o vault já cobra do editor (1 conversa até 31/10) e do empresário.

### 5.4 Como NÃO virar mais um repo morto com 3 estrelas

O repo morto com 3 estrelas tem uma assinatura reconhecível: README com roadmap, zero releases, zero resultados, último commit há cinco meses. Antídotos, na ordem:

1. **Publique o resultado antes do produto.** O README abre com a tabela de resultados, não com "features planejadas". Se não há resultado, não publique.
2. **Escreva "não faça isto" no README.** As cinco linhas do §3.5. Um repo que declara para quem não serve é lido como sério; um que promete tudo é lido como abandonado no nascimento.
3. **Proíba roadmap no README.** Roadmap num repo solo é promessa que documenta o próprio abandono. Issues sim, roadmap não.
4. **Uma tag com hash e uma data de reavaliação.** `v0.1` no dia do veredito (06/10), e uma linha: *"reavaliado em 30/11; se ninguém além do autor tiver rodado, arquivado."* Arquivar em público com motivo é sinal de julgamento. Repo apodrecendo em silêncio é sinal contrário.
5. **Não peça estrela. Peça o número.** O CTA é "rode no seu repo e me mande sua tabela", e cada tabela recebida entra no relatório com crédito. Cinco tabelas de terceiros valem uma seção de resultados; 300 estrelas valem uma linha morta no perfil.
6. **Amarre à data da banca.** Um repo com defesa marcada tem prazo externo. A retro §5 já nomeou a condição: prazo externo, contraparte que não é você, cadência própria. A banca fornece as três.

---

## 6. Condições para eu parar de ser do contra

Objetivas. Se todas forem atendidas, retiro a objeção por escrito.

**Bloqueadores — antes de qualquer linha de runtime:**

1. **G1 (14/09) e proposta (21/09) entregues.** Sem exceção, sem antecipação de trabalho de orquestrador para dentro dessa janela.
2. **As cinco perguntas do orientador** (§2 do pivô de 20/08) respondidas por escrito, num arquivo.
3. **arXiv:2604.17883 lido na íntegra** e um parágrafo escrito dizendo se ele já mede topologia de time. Se já mede, este projeto muda de pergunta ou morre — e eu quero ler esse parágrafo antes de 21/09.

**Desenho — antes do primeiro run:**

4. **Pré-registro commitado com hash**, contendo as 12 tarefas congeladas, os três braços (incluindo o placebo estrutural **C**), a tabela de critérios de §4.2 e a data do veredito. Escrito antes de existir resultado.
5. **O README declara a categoria certa** — banco de provas, não orquestrador — e traz o "para quem NÃO é" de §3.5.
6. **Um parágrafo sobre a exposição de ToS**, no repo, citando a mudança de 20/02/2026 e a moratória de 15/06/2026, e dizendo o que acontece com o projeto se ela voltar. Não escondido; declarado.

**Resultado — o veredito de 06/10:**

7. **Métrica primária cumprida:** B bate A em ≥8 de 12 tarefas, mediana ≥20 pp, **e** B se separa de C. Se B ≈ C, a topologia não fez nada e o projeto morre com um bom post.
8. **Custo do handoff ≤ 2,5×** o braço solo.
9. **Tempo até primeira sessão útil ≤ 15 min de mediana**, medido em **3 pessoas que não são o dono**, sem ajuda do dono durante a medição.

**Sobrevivência — 30 dias após o post:**

10. **≥5 pessoas rodaram no repo delas e mandaram o número.** Não estrela, não fork, não "legal!". A tabela.
11. **≥1 conversa nomeada** gerada pelo relatório — a métrica que o vault já cobra do empresário e do editor.

**A cláusula de morte:** se **7** falhar, o repo publica o resultado negativo, ganha a tag `v0.1-negative-result`, é arquivado com motivo escrito, e o dono volta 100% para o TG. Isso não é fracasso — é o experimento tendo feito exatamente o trabalho pelo qual eu o defendi: **matar seis meses de construção com duas semanas de medição.**


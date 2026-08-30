# T1 — Peko (pesquisador de harness / graph engineering)
Data: 2026-08-30 · Contra: `mathai-orchestrator/SPEC.md` @ v0 · DOSSIE.md como base factual

---

## 1. Leitura técnica dos três

### 1.1 Maestri — grafo espacial persistido, executado por PTY

**Como integra time.** Não há protocolo do orquestrador. Ao criar um cabo entre dois terminais, o Maestri **instala uma skill dentro de cada CLI**; a partir daí o contrato agente↔agente vive no contexto do agente, não no runtime. A execução é literalmente um agente digitando no terminal do outro. Detecção de fim-de-turno é heurística sobre PTY: o Maestri só monitora terminais **não focados**, e selecionar o terminal desliga o monitoramento.

**O que é genuinamente bom.**
- **Estado espacial é estado de sessão.** A Partitura (JSON em `~/.maestri/partituras/`) serializa terminais, papéis, notas, portais, grupos e *todas as conexões* — sem scrollback, sem caminho absoluto. Isso é exatamente "o grafo é o artefato versionável", que é a tese certa. Grafo template ≠ execução.
- **Agent-agnostic por construção.** Claude Code fala com Codex porque o canal é o PTY, não uma API. Zero acoplamento a vendor, zero chave. É a mesma restrição dura do dono, resolvida de um jeito diferente.
- **Nota/fichário como canal.** Nota é arquivo markdown real em disco, encadeável por cabo; fichário é pasta com abas. Conectar um agente a um fichário dá acesso à pasta inteira. Isso é blackboard file-backed, e a literatura diz que é o canal certo (§3, regra R3).
- **Floors** (branch isolado com APFS copy-on-write, espelhado como branch git) resolve o conflito de escrita paralela na camada de filesystem em vez de na camada de protocolo. É a solução mais barata que existe para fan-out de escrita.
- **Environments** com `MAESTRI_TOKEN` por terminal e proibição de override de `HOME`/`PATH`/`MAESTRI_*` — identidade por nó, revogável. Isso é write-contract embrionário.

**Mecanismo que o torna especial:** *skill instalada no CLI + PTY como transporte*. O orquestrador não precisa entender o agente; ele só precisa saber onde o cursor parou.

**Onde é frágil.**
- **A parada é heurística de terminal, não predicado verificável.** "Maestri detecta que o receptor terminou" é detecção de prompt ocioso no PTY. Não há exit code, não há artefato exigido, não há checagem determinística. É precisamente o que a literatura chama de terminação controlada pelo modelo/ambiente e não por um bound efetivo (§2, IAL: 100% das 68 falhas confirmadas = ausência de bound forte).
- **Foco da UI é load-bearing no protocolo.** Um estado de interface (borda tracejada) decide se a mensagem volta ou não. Isso não é observável por script, não é reproduzível e não é auditável.
- **Sem budget, sem contrato de escrita, sem ledger.** Nenhum limite de iteração por nó, nenhuma declaração de quais arquivos um papel pode tocar. Dois agentes ligados ao mesmo fichário podem se sobrescrever; a única defesa é Floors, que é opt-in e por-repo, não por-nó.
- **Maestro Mode recruta cópias de si mesmo.** Pares homogêneos pagam a *collaboration tax* cheia; pares heterogêneos são puxados para o membro forte (§2, 2608.22152). Recrutar clones é a pior composição possível.
- **Routines só por tempo.** Não existe trigger por evento (`artifact_exists`). Encadear com `&&` é sequência, não predicado. Um time cujo despertador é um cron de 5 min não é um grafo de execução — é um poller.
- **Convite topológico errado.** Canvas com cabos incentiva malha densa. Medido: em tarefa de spec compartilhada o grafo sustentado sobe até quase a linha de clique (grau médio 5.47 contra 7 a 8 agentes) e clustering 0.81 — mensagens crescem ~n² — enquanto rotular um agente de "Lead" **não cria hub nenhum** e não melhora sucesso (§2, 2608.16801).
- macOS-first (Windows via git branch, não APFS). O dono precisa de Linux.

### 1.2 Grok Bot — roteamento por descrição, frota de agentes com computador próprio

**Como integra time.** Cada bot tem job description estreita e seu próprio computador na nuvem. Quando um bot precisa de algo fora da raia, ele **varre as descrições dos outros agentes da frota e roteia o pedido** para quem casa — o mesmo mecanismo usado para skills. Além disso, bots entram em group chat e coordenam sozinhos, "passando trabalho, atribuindo ownership, e só chamando o humano em decisão de julgamento".

**O que é genuinamente bom.**
- **Roteamento é descoberto, não cabeado.** Não existe aresta declarada; existe um índice de descrições e uma decisão em runtime. É a versão "soft" do que a literatura chama de roteador de handoff — e o único roteador com número publicado custa **155 tokens, 0.15% de overhead**, é determinístico a temperatura 0, e o valor dele é *prevenir regressão*, não escolher o ótimo (§2, 2608.25277).
- **Job description estreita = isolamento de contexto de verdade.** É a decomposição centrada em contexto que a Anthropic recomenda explicitamente contra a decomposição por tipo de trabalho (planner/implementer/tester/reviewer), que produz "telefone sem fio" a cada handoff (§2, Anthropic 2026).
- **Sempre ligado, computador por bot.** Sessão longa desacoplada do laptop. Aprende por demonstração (mostra o workflow uma vez).
- **Trigger set pequeno e honesto:** Slack, GitHub, Teams. Eventos reais, não cron.

**Mecanismo que o torna especial:** *roteamento por descrição de agente* — o mesmo mecanismo de resolução de skills aplicado a peers. Elimina o custo de manter uma topologia.

**Onde é frágil.**
- **Group chat auto-coordenado é exatamente a configuração que a taxonomia pune.** Inter-agent misalignment é 32–37% de todas as falhas de MAS em 1642 traces; e o subtipo dominante (reasoning-action mismatch 13.2%, task derailment 7.4%) não é resolvido por protocolo de mensagem — os autores mostram que ocorre mesmo com agentes do mesmo framework falando a mesma língua (§2, 2503.13657).
- **Cada bot com seu próprio computador = não existe artefato compartilhado.** O único canal é a conversa. Mensagem direta alcança um destinatário; arquivo escrito uma vez é lido por muitos. Trocar mensagem por arquivo compartilhado cortou ~42% dos tokens de saída a 8 agentes em trabalho message-heavy (§2, 2608.16801).
- **Roteamento por descrição em linguagem natural é inverificável.** Não há schema, não há predicado, não há log de "por que foi para o bot X". Sem isso, atribuição de falha (qual agente, qual passo) é impossível.
- **Nada publicado sobre budget de iteração, critério de parada ou contrato de escrita.** Frota sempre-ligada + roteamento livre + sem bound é a receita literal de Infinite Agentic Loop; 95.6% das IALs confirmadas causam exaustão de custo/DoS de modelo (§2, 2607.01641).
- Fechado, pago, quota própria. Sem valor de carreira open-source para o dono.

### 1.3 Hermes Agent — subagent por RPC dentro de código, budget por agente, memória file-backed

**Como integra time.** Não há "time" no sentido de peers. Há um loop Think-Act-Observe com `IterationBudget`, e `delegate_task` cria **subagents isolados com toolset restrito e budget próprio** (`delegation.max_iterations: 50`, `max_concurrent_children: 3`, `max_spawn_depth: 2`). O truque é que os subagents chamam tools **via RPC dentro de scripts Python**, colapsando pipelines multi-step em turnos de custo de contexto ~zero.

**O que é genuinamente bom.**
- **Budget por agente com refund.** Pai 90, subagent 50, e `execute_code` faz `refund()` — iteração barata não consome orçamento. É a única das três implementações com um *bound aritmético explícito por nó*.
- **Três tiers de prompt (frozen / volatile / history).** `MEMORY.md` + `USER.md` + skills montados **uma vez** por sessão e nunca invalidados; fatos voláteis anexados sem quebrar prefixo. É prefix stability para cache, mas o efeito colateral é o certo: **a regra nunca é reescrita**. É a mitigação canônica do compaction cliff (§2, 2608.22752).
- **Toolset como ACL declarativa.** Blast radius por sessão/subagent, e o catálogo escopado se propaga por toda a cadeia — subagent não escala privilégio via bridge tool.
- **Tools paralelas com ordem preservada** (ThreadPoolExecutor, resultados reordenados por `tool_call_id`; tools `interactive` forçam sequencial). Paralelismo com contrato.
- **Abstração de ambiente com 6 backends** e `check_fn` com TTL 30s + grace 60s — probing de infra não vira custo por turno.
- **Registry self-registering + AST parse** para não importar lixo: adicionar tool = 1 arquivo, zero edit no dispatcher.

**Mecanismo que o torna especial:** *subagent-por-RPC-em-código + compactação de trajetória*. É a instanciação em produção do que a literatura chama code-as-harness: o programa é executável, inspecionável e stateful, e o passo multi-step não paga tokens de handoff porque nunca vira mensagem.

**Onde é frágil.**
- **`max_iterations` é um kill-switch sintático.** Ele é cego ao conteúdo: gasta demais no fácil e trunca o difícil. Um stopper semântico judge-free cortou **38% dos tokens operacionais a paridade de qualidade** contra o `max_iterations` (∆IS = −0.004, p=0.81) (§2, 2606.27009).
- **`trajectory_compressor` protege head/tail e comprime o meio uniformemente.** É exatamente a política que derruba regra de segurança: sob o prompt de produção do Claude Code, retenção de safety rule cai para **53% após 1 rodada e 10% após 5**. Uma restrição que entrou no meio da sessão morre. A correção conhecida é retenção por *tipo* (constraint = preservação exata), não por posição (§2, 2608.22752).
- **Budget é por agente, não global.** Pai + 3 subagents estouram o cap do pai por construção. Não há orçamento de sessão.
- **Memória congelada no system prompt corta os dois lados.** `MEMORY.md` editado no meio da sessão não tem efeito até o próximo turno de montagem.
- **Não existe critério de parada verificável.** A sessão termina por texto final ou por budget. Não há gate determinístico ("o teste passou").
- **Gateway/sessão única em SQLite WAL** — um escritor. Fan-out real de N agentes escrevendo a mesma sessão não é o desenho.

### 1.4 Síntese em uma tabela

| | Maestri | Grok Bot | Hermes |
|---|---|---|---|
| Transporte | PTY (skill no CLI) | chat + roteamento por descrição | in-process + RPC em código |
| Topologia | declarada (cabo), espacial | descoberta em runtime | hierárquica (pai→subagent) |
| Canal de estado | nota/fichário em disco | conversa | contexto + `MEMORY.md` + SQLite |
| Bound por nó | **nenhum** | **não publicado** | `IterationBudget` c/ refund |
| Parada | heurística de PTY | implícita/humano | budget ou texto final |
| Contrato de escrita | nenhum (Floors mitiga) | nenhum | toolset ACL (tools, não arquivos) |
| Auditoria | scrollback | histórico do chat | SQLite WAL + FTS5 |
| Melhor ideia p/ roubar | Partitura + fichário-como-canal | roteador conservador barato | budget/refund + tier frozen |

---

## 2. Bibliografia comentada

Formato: **título** — arxiv/link — o que prova. `[primária]` = li abstract/conteúdo pelo leitor de PDF. `[resumo de busca]` = só vi a página de resultado/snippet.

### 2.1 Por que multi-agente perde para single-agent

**[primária] Why Do Multi-Agent LLM Systems Fail?** — arXiv:2503.13657 (UC Berkeley, NeurIPS'25 D&B) — https://arxiv.org/abs/2503.13657
Taxonomia MAST: 14 modos, 3 categorias, sobre 1642 traces anotados de 7 frameworks; taxa de falha de 41%–86.7%. Distribuição: **System Design 41.8% · Inter-Agent Misalignment 36.9% · Task Verification 21.3%**. Os modos individuais mais caros: step repetition 15.7%, disobey task spec 11.8%, unaware of termination conditions 12.4%, reasoning-action mismatch 13.2%. Intervenções medidas: melhorar só a especificação de papel deu **+9.4%** no ChatDev; adicionar um verificador de objetivo de alto nível deu **+15.6%**. Insight 3 explícito: verificadores existentes fazem checagem superficial (compila? tem TODO?) e isso não basta.

**[primária] The Illusion of Multi-Agent Advantage** — arXiv:2606.13003 (Salesforce Research et al.) — https://arxiv.org/abs/2606.13003
MAS automático **não** bate CoT-SC em GPQA-Diamond, HLE-Math, SWE-Bench Lite, BrowseComp nem no benchmark diagnóstico próprio (SMFR), a ~10× o custo. Mas o achado que importa para nós: um **Expert-MAS desenhado à mão, com decomposição explícita e orquestração determinística em Python**, sobe GPT-5 de 57.0% para **96.5%** no SMFR a custo comparável ao CoT-SC. Ou seja: o problema não é multi-agente, é multi-agente gerado automaticamente e coordenado por conversa. Também documenta "functional collapse": arquiteturas complexas degeneram em ensembling redundante.

**[primária] When Do Multi-Agent Systems Help? An Information Bottleneck Perspective** — arXiv:2607.16133 (Texas A&M) — https://arxiv.org/abs/2607.16133
Prova o critério de quando decompor. Com banda de relay infinita, MAS ≡ SAS; todo o ganho e toda a perda vêm da **compressão do relay**. Ganho local `G = H(M_i|m_i) − β·Δ_i(m_i)`: benefício de remover contexto ruidoso menos perda de informação relevante, com β crescendo com a capacidade do modelo. Empírico em 5 benchmarks × 3 escalas: relay barato (δ≈0, ALFWorld/WideSearch) → MAS ganha sempre (+0.19, +0.16, +0.02); relay caro (δ≫0, WorkBench) → MAS **perde em todos os modelos** (−0.005, −0.086, −0.014); TravelPlanner-HC inverte de +0.16 para **−0.233** no modelo forte. Ablação SAS-Plan mostra que o ganho vem do *isolamento de contexto*, não da estrutura de subtarefas.

**[primária] The Collaboration Tax** — arXiv:2608.22152 (Notre Dame / Meta SL) — https://arxiv.org/abs/2608.22152
32 tarefas solo-tratáveis, 11 modelos, 7 provedores. Imposto de coordenação positivo em quase toda célula, ordenado sem exceção por categoria e **decrescente com capacidade** (gpt-5 perde +12/+6/+2 pp; gpt-4.1-nano perde +63/+50/+38 pp). O mecanismo não é raciocínio: é uma cascata de 4 estágios — grounding, querying, integration, re-derivation. Em falhas homogêneas, "re-derived" cai a 0.28–0.32 contra 0.81–0.85 nos sucessos. Um clause de prompt por estágio recupera ~38% do imposto sem retrain. **Pares heterogêneos são puxados para o membro forte, não para a média** (OLS y = 1.35x − 0.27): misturar modelos é melhor que clonar.

### 2.2 Topologia e custo de comunicação

**[primária] When Agents Coordinate: Measuring Coordination in Multi-Agent AI Coding** — arXiv:2608.16801 (UCL) — https://arxiv.org/abs/2608.16801
1902 runs instrumentados (Claude Code 2.1.x, sonnet pinado) + 244 em ambiente selado. A medida certa: cada run é uma rede temporal onde **agentes e arquivos são nós**, e mensagem/write/read são arestas com timestamp e custo. Achados que são regra de desenho:
- Mensagens crescem quase quadraticamente (expoente **1.92**, IC [1.80, 2.05]) — mas é **um handshake único no início**: 90% dos pares distintos aparecem por τ≈0.2, e mensagens por par caem de ~3 para 1.27 de 2 para 8 agentes. Aos 16 agentes o crescimento **satura** e o time migra para broadcast.
- **A tarefa determina a topologia.** Spec compartilhada → malha densa (grau 5.47/7, clustering 0.81). Pipeline → esparso (grau 2.99/7, clustering 0.38); em cadeia de 16 passos, grau médio **0.28 contra clique de 15**, e 12 de 20 runs não formam rede nomeada nenhuma.
- **Nomear um coordenador não cria hub e não melhora sucesso.** Filtro de disparidade: 0 de 1170 arestas no caso denso. Liderança por rótulo de prompt é nominal.
- **Arquivo substitui mensagem:** exigir coordenação por arquivo compartilhado cortou **~42% dos tokens de saída a 8 agentes** em trabalho message-heavy; e adicionou custo onde os arquivos já carregavam a coordenação.
- **Falha estrutural:** um cálculo de 8 passos, 1 passo por agente, falhou 10/10 runs numa convenção de arredondamento que ficava *na fronteira entre dois donos* e não pertencia a ninguém. Discutida todo run, nunca resolvida. Decomposição cria interfaces; cada interface precisa de dono.
- Metodologia: a mesma célula colhida duas vezes deu expoentes 1.76 e 2.44. **Um run é amostra de tamanho 1.**

**[primária] MANTA: Multi-Agent Network Topology Adaptation** — arXiv:2607.28527 (Cornell/UIUC/Academia Sinica) — https://arxiv.org/abs/2607.28527
Topologia como objeto de self-improvement em tempo de execução, com **mutação estrutural limitada** (≤3 operações, aplicadas por código determinístico a uma cópia e validadas antes de comitar). Média 74.0 em 5 benchmarks, +5.8 pp sobre o melhor baseline, e **o menor consumo de tokens entre todos os MAS avaliados** (77.6k contra 115–202k dos estáticos e 151–275k dos adaptativos). Ablação: remover o planejamento inicial de topologia custa mais (71.7→57.5) que remover a mutação (→60.8). **A primeira mutação captura a maior parte do ganho.** E o achado que mata o instinto errado: dos 5 reparos observados, só um aumenta o sistema — os outros serializam execução, religam arestas, ou inserem um crítico. O Trace Auditor separa 83.2% (sem flag) de 62.5% (com flag) de acerto sem nunca ver o gabarito.

**[primária] Routed Graph Handoff** — arXiv:2608.25277 (Amazon AGI) — https://arxiv.org/abs/2608.25277
Mensagens em linguagem natural consomem **40–60% do orçamento de tokens** de um MAS, e **76% das falhas multi-agente são inter-agent misalignment** (ordering, pré-requisito perdido, loop por ambiguidade); sistemas single-agent têm 0% disso por construção. Handoff como DAG tipado (8 tipos de nó, 7 relações) dá +12.7 pp em τ-retail a 3.2× de compressão e +8.7 pp em BrowseComp — **mas regride −14.6 pp em AppWorld**, onde a tarefa exige iteração adaptativa e o executor não consegue sair do plano. Por padrão de tarefa: agregação +6.7, iterate −7.0, conditional −18.2. Solução: roteador de 155 tokens que escolhe formato por tarefa, default conservador em prosa. Detalhe crítico: **o schema sozinho não faz nada** — sem o prompt graph-aware no receptor, o ganho some.

**[primária] PatchBoard** — arXiv:2605.29313 — https://arxiv.org/abs/2605.29313
Substitui diálogo entre agentes por **mutações JSON Patch validadas sobre estado compartilhado**, com kernel determinístico que checa sintaxe, autorização (write contract por papel), aplicação, schema e invariantes antes de comitar. ALFWorld, 630 episódios pareados: **84.6%** contra 30.8% (LangGraph) e 61.6% (Flock), a **45.5k tokens por sucesso** contra 368.3k e 64.2k. Controles de blackboard: blackboard puro 77% a 95.5k; blackboard JSON estruturado 77% a 48.6k — logo, **o ganho vem da validação e do write contract, não da memória compartilhada**. Ablações: remover a interface patch/schema custa −15 pp e **2.34× tokens/sucesso**; remover context slicing custa −15 pp. Sensibilidade de contexto: **o menor budget testado (1k) tem o melhor perfil** — expor mais estado não melhora. Fault injection: 0% de contaminação por JSON inválido, path/tipo ruim e escrita não autorizada; 96% de cycle-halt.

### 2.3 Orquestração como grafo vs. procedimento no prompt

**[primária] In-Context Prompting Obsoletes Agent Orchestration for Procedural Tasks** — arXiv:2604.27891 — https://arxiv.org/abs/2604.27891
O contraponto mais duro à premissa do repo. 3 domínios (14, 14 e 55 nós), 200 conversas por condição, mesmo modelo. Colocar o **procedimento inteiro no system prompt** bate LangGraph em **15/15 comparações** (juiz Claude) e 11/15 com juiz independente GPT-4.1, zero a favor do orquestrador. Taxa de falha: 24% vs 11.5% (travel), 9% vs 0.5% (Zoom, 18×), 17% vs 5% (insurance). Orquestração custa **1.2–1.7× mais chamadas de LLM** por causa do roteamento nos hubs de decisão. Mecanismo: injeção de template por nó fragmenta o raciocínio; o modelo perde o arco global. Os próprios autores listam onde a orquestração ainda ganha: pipeline multi-modelo, estado externo/tool use, tarefas não procedurais e modelos fracos. **Regra prática que sai daqui: se cabe no prompt e o modelo é forte, não faça grafo.**

**[primária] Code as Agent Harness** — arXiv:2605.18747 (UIUC/Meta/Stanford; 319 votos) — https://arxiv.org/abs/2605.18747
Survey que nomeia a tese do Hermes: código é o substrato **executável, inspecionável e stateful** do harness. Três camadas (interface, mecanismos, escala multi-agente) e um diagnóstico direto na parte multi-agente: **falta representação formal e persistente do estado compartilhado que os agentes possam consultar e atualizar entre iterações**. Cataloga o que já existe: context scheduling explícito (L2MAC reseta a janela entre passos e passa um sumário direcionado), publish-subscribe filtrado por papel (MetaGPT), memória hierárquica com sumarizador barato (HyperAgent), e revert como sincronização (QualityFlow é o único que gerencia histórico de estado em vez de sempre avançar). Também nomeia compaction + state offloading como a fronteira entre contexto ativo e estado durável.

### 2.4 Paralelismo: custo/benefício

**[primária] A Two-Tier Perspective on Inference-Time Parallelism (TIPEX)** — arXiv:2608.05791 (ICML'26) — https://arxiv.org/abs/2608.05791
Separa **Replica Parallelism** (N caminhos completos → acurácia) de **Structural Parallelism** (DAG dentro de um caminho → latência). GAIA. Números:
- Réplicas: 1→3 dá ganho estável; **3→5 é marginal ou negativo** com custo de token muito maior.
- Estrutural: Balanced Parallelism reduz latência; **Aggressive Parallelism derruba acurácia** (L2: 32%→29% com 3 réplicas; 28%→25% com 5) e aumenta tokens.
- As duas camadas **interagem não-aditivamente**: sob BP a acurácia sobe 29→37 com mais réplicas; sob AP ela cai 28→25.
- O gargalo é o **juiz**: acurácia real sempre abaixo da Oracle; trocar só o modelo do juiz move 65.9%→78.3% do teto oracle.
- Falhas: 64/104 raciocínio, 24/104 retrieval, 11/104 propagação de erro, **5/104 execução redundante** (ramos paralelos produzindo saída sobreposta).

**[primária, fonte de engenharia] Anthropic — How we built our multi-agent research system** — https://www.anthropic.com/engineering/built-multi-agent-research-system
Opus lead + Sonnet subagents: **90.2%** sobre Opus single-agent na eval interna de research, a **~15× os tokens de um chat** (agente sozinho já é ~4×); uso de token explica **80% da variância** de desempenho em browsing. Heurística de escala embutida no prompt do lead: fato simples → 1 agente e 3–10 tool calls; comparação → 2–4 subagents com 10–15 calls cada; research complexa → 10+ com responsabilidades divididas. Falhas observadas: spawn de 50+ subagents em query trivial, **trabalho duplicado quando a descrição da tarefa é vaga**, busca infinita por informação inexistente. Paralelismo (3–5 subagents simultâneos, 3+ tool calls por subagent) cortou até 90% do tempo. Onde **não** usar: tarefas que exigem contexto compartilhado, dependências em tempo real, e a maioria das tarefas de código.

**[primária, fonte de engenharia] Anthropic — Building multi-agent systems: when and how to use them** (jan/2026) — https://claude.com/blog/building-multi-agent-systems-when-and-how-to-use-them
Custo de coordenação: **3–10× mais tokens** que single-agent, por duplicação de contexto, mensagens de coordenação e sumarização para handoff. Três justificativas legítimas: proteção de contexto (subtarefa gera 1000+ tokens irrelevantes ao resto), paralelização, especialização. Padrão recomendado: orquestrador-subagente, com destaque para o **verification subagent** que valida por blackbox e por isso quase não precisa de transferência de contexto. A regra mais importante: **decomposição centrada em contexto, não centrada em problema.** Dividir por tipo de trabalho (planner / implementer / tester / reviewer) cria overhead constante e efeito telefone sem fio. "Work should only be split when context can be truly isolated."

**[primária, fonte de engenharia] Claude Code — agent teams** (experimental, v2.1.x) — https://code.claude.com/docs/en/agent-teams
Mecanismo concreto de time auto-coordenado: task list compartilhada com **file locking** para claim, mailbox por agente em `~/.claude/teams/{team}/inboxes/{agent}.json`, dependências que desbloqueiam automaticamente, hooks `TaskCreated`/`TaskCompleted`/`TeammateIdle` que podem sair com código 2 para **rejeitar** a transição e devolver feedback (quality gate determinístico). Guias: **comece com 3–5 teammates**; 15 tarefas independentes → 3 teammates; "três focados batem cinco espalhados"; **evite conflito de arquivo dando a cada teammate um conjunto de arquivos próprio**; mensagem de outro agente é tratada como input não confiável e não pode aprovar permissão. Limitações relevantes: sem times aninhados, lead fixo, sem resume, task status atrasa.

### 2.5 Contexto em sessão longa

**[primária] The Compaction Cliff in Long-Running AI Agent Memory** — arXiv:2608.22752 (CIKM'26) — https://arxiv.org/abs/2608.22752
O número que muda o desenho: sob o prompt `/compact` de produção (Sonnet 4.6, 20 configs reais), retenção de **safety rule cai para 53% após 1 rodada e 10% após 5**. Truncamento hierárquico preserva ~50% das restrições em 50 configs reais. Causa: compactação **type-blind** — regra e log episódico competem pelos mesmos tokens e são resumidos na mesma taxa, mas só a regra precisa da redação exata. Correção: cinco tipos (constraint / procedural / belief / preference / episodic, cobrindo 97% do conteúdo real de 396.934 artefatos de 54.628 repos GitHub) com distorção própria por tipo — binária para constraint. Resultado: 2–4× mais constraint recall, 96% em 5 rodadas; 0% de violação de localidade contra 93% sob particionamento uniforme; recall@50 100% contra 73%. E: **49.8% do texto de segurança do openFDA e 61.1% das cláusulas do LegalBench são declarativos**, não imperativos — classificador por forma gramatical não os pega.

**[primária] Filesystem-Based Memory for LLM Agents** — arXiv:2607.26637 (UIUC/UCSD/Adobe) — https://arxiv.org/abs/2607.26637
Primeiro estudo sistemático do default de produção (memória = árvore de markdown que o agente escreve e reorganiza). Achados que contrariam o instinto:
- **Nenhuma forma de store ganha correctness em todo lugar.** O store mais barato e estruturado ("foldered sessions", uma pasta por sessão, sem curadoria) é o líder mais consistente (86.1 / 77.6 / 76.2); o store curado por agente é o **pior de todos** num tier (37.5 contra 78.1 do dump verbatim).
- **O que a organização compra de fato é economia de busca** — corta o custo por query pela metade ou mais onde o material é grande (1.4¢ vs 4.0¢), e quase nada onde é pequeno.
- **Um passe de reorganização condensante destrói o store** (REALTALK 77.6 → 41.2). O comportamento degenerado é reescrita silenciosa; só é evitado adicionando **uma regra explícita de preservação**.
- Aderência à taxonomia **erode conforme o store cresce** para todos menos o agente de gestão mais forte.
- **Trocar o toolset remodela o store tanto quanto trocar o modelo.** Adicionar uma tool muda comportamento e não muda resultado.

**[primária] Semantic Early-Stopping for Iterative LLM Agent Loops** — arXiv:2606.27009 — https://arxiv.org/abs/2606.27009
`max_iterations` é um kill-switch sintático, cego ao conteúdo. Um stopper geométrico judge-free (distância cosseno entre drafts consecutivos abaixo de ε por k rodadas, k=2) corta **38% dos tokens operacionais a paridade de qualidade** (∆IS=−0.004, p=0.81); `fixed_k3` corta 53% também a paridade. A variante **quality-gated é contraprodutiva: +129% de tokens** porque chama o juiz toda rodada. Teorema 1 (terminação) vale porque a cláusula failsafe é **incondicional e não ablável**. E o resultado honesto: o oracle (melhor rodada) fica **+0.115 IS acima de toda política prática** (p≈4e−11) — parar é fácil, escolher a melhor rodada é o problema aberto.

**[primária] When Agents Do Not Stop: Infinite Agentic Loops** — arXiv:2607.01641 — https://arxiv.org/abs/2607.01641
6549 repositórios varridos, 74 findings, **68 IALs confirmadas em 47 projetos, 91.9% de precisão**. Distribuição de causa raiz: **missing strong bound em 100% dos 68**; tool-controlled retry 41.2%; **model-controlled termination 38.2%**; missing exit 33.8%; workflow cycle sem bound verificado 30.9%; state growth amplifier 27.9%. Padrões: retry sem bound 25%, iteração de tool call sem bound 23.5%, multi-agent chat sem turn bound 20.6%. Impacto: exaustão de custo e DoS de modelo em 95.6%. LangGraph + AutoGen concentram 45/68 porque **codificam o feedback via API e não via sintaxe de loop visível**. A frase operacional: um `finish_reason` produzido pelo modelo **não é um bound**.

### 2.6 Secundária — vi só a página de resultado

`[resumo de busca]` para todos abaixo. Registrados porque nomeiam o espaço, não porque eu verifiquei os números.

| Paper | ID | Por que está aqui |
|---|---|---|
| Reward-Guided Autoregressive Graph Generation for Multi-Agent Communication Topology | 2608.20099 | design automático de topologia sob custo de token |
| Adaptive Influence Graphs for Failure Attribution in MAS | 2608.24361 | atribuir falha a agente/passo via grafo de influência |
| AgentSlimming: Efficient and Cost-Aware MAS | 2605.08813 | poda de topologia por custo |
| Recognize Your Orchestrator: Entropy Dynamics for MAS | 2606.01351 | fragilidade da topologia de orquestração centralizada |
| OrchestraBench | 2608.05263 | benchmark de modos de falha de orquestração, recuperação, qualidade da decomposição |
| OrchBench: avaliar planos de orquestração isoladamente por simulação determinística | 2607.25656 | avaliar o plano sem rodar o time |
| Graph-Based Agentic AI with LangGraph (guia prático) | 2607.19297 | workflow stateful long-running |
| XFlow: Executable Protocol Programming for Reliable Multi-Agent Workflows | 2606.14790 | subespecificação como causa central de não-confiabilidade |
| AgentRoom: Concurrent Multi-Agent Coding in a CRDT-Backed Shared Workspace | 2608.23740 | escrita concorrente multi-arquivo sem lock |
| Governed Shared Memory for Multi-Agent LLM Systems | 2606.24535 | 4 modos de falha de fleet-memory (vazamento, etc.) |
| Hallucination as Context Drift: Synchronization Protocols | 2606.21666 | alucinação por dessincronização de contexto, não por incapacidade |
| Early Diagnosis of Wasted Computation via Failure-Aware Observability | 2606.01365 | diagnosticar desperdício antes do resultado final |
| Context as an Environment: Programmatic Context Management | 2608.21690 | contexto gerido por programa em horizonte longo |
| ACM: Agentic Context Management for Long Horizon Tasks | 2607.23809 | compressão sem perda por gestão agêntica |
| Toward Reliable Context Compression: Execution Instability | 2608.06503 | compressão recorrente enfraquece a execução |
| HALT: Verification-Aware Stopping for Search Agents | 2608.02009 | parada por verificação, não por contador |
| Doomed from the Start: Early Abort via Probe Cascade | 2607.06503 | abortar trajetória já perdida |
| AgentRewind: Recoverable Execution for Long-Horizon Agents | 2608.14380 | rollback de contexto **e** de ambiente |
| Cost-Utility Alignment in LLM Agent Trajectories | 2608.26195 | atribuir custo a utilidade dentro da trajetória |
| Chroma — Context Rot (relatório, 18 modelos) | trychroma.com/research/context-rot | degradação contínua com input longo; janela de 200k degrada já em ~50k; posição no meio é a pior |

### 2.7 Lacunas confessadas

- **Coordenação por PTY / um agente digitando no terminal do outro:** *lacuna*. Não achei nada. O mecanismo central do Maestri é literatura zero. O análogo mais próximo é code-as-harness (2605.18747), que argumenta o oposto: o canal deve ser código executável e inspecionável, não texto num pty.
- **Roteamento por descrição de agente (peer discovery):** *lacuna parcial*. O único roteador com número que achei roteia **formato** de handoff (2608.25277), não destinatário. RouteLLM roteia modelo. Ninguém mediu "escolher o peer certo lendo descrições" isoladamente.
- **Orquestração sobre CLI de assinatura, sem API key:** *lacuna*. Todo paper assume endpoint HTTP. Nenhum mede exit code de subprocesso como sinal de controle. O oceano azul do dono é real, mas isso também significa: **nenhum baseline publicado**.
- **Métrica de "handoff útil":** *lacuna*. 2608.16801 mede a rede (quem falou com quem, quando, quanto custou) mas não mede quanto do handoff foi de fato consumido a jusante. Vou propor um proxy em §5, mas ele é meu, não da literatura.
- **N≥3 na collaboration tax:** os autores limitam a N=2 e dizem explicitamente que não sabem se a cascata de 4 estágios generaliza.

---

## 3. O que a literatura manda fazer no MVP

Cada regra com o paper que a sustenta. Ordem = impacto no desenho.

**R0 — Todo grafo compete contra um grafo de 1 nó com o procedimento inteiro no prompt.**
Se o time não bate o single-agent, o grafo é bloat. 15/15 comparações favorecem o prompt único em tarefa procedural (2604.27891); CoT-SC bate MAS automático em 5 benchmarks a 1/10 do custo (2606.13003); o ganho de MAS some conforme o modelo fica forte (2607.16133, β↑). O baseline não é opcional: é a primeira coisa que o `up` roda.
*Consequência dura para o v0:* o grafo scout→builder de hoje **provavelmente perde** para um único `claude -p` com os dois prompts concatenados. Isso precisa ser medido antes de qualquer coisa ser construída em cima.

**R1 — Só decomponha onde o relay é barato (δ≈0). Corte centrado em contexto, não em papel.**
`G = H(M|m) − β·Δ(m)`: só ganha se o que se remove de ruído for maior que o que se perde de informação (2607.16133). Empiricamente, WorkBench (o downstream precisa de IDs, timestamps, saídas exatas) perde em todos os modelos. Anthropic diz a mesma coisa em prosa: divida por contexto isolável, não por tipo de trabalho; planner/implementer/tester/reviewer é o anti-padrão nomeado. **Teste operacional antes de criar um nó:** escreva o handoff que ele receberia. Se ele precisa carregar estado exato do upstream (paths, hashes, saída de comando), não separe — é um nó só.

**R2 — Teto de fan-out: 3. Ganho para além de 3 é marginal ou negativo.**
Réplicas 1→3 ganham, 3→5 é marginal ou negativo com custo bem maior (2608.05791). Anthropic: 3–5 subagents simultâneos; 10+ só em research complexa com responsabilidades claramente divididas, e o modo de falha observado foi spawn de 50+ em query trivial. Claude Code docs: comece com 3–5, 15 tarefas independentes → 3 teammates, "três focados batem cinco espalhados". Estrutural agressivo derruba acurácia (28%→25%). **Cap duro no schema, não no prompt.**

**R3 — Artefato é o canal. Broadcast e chat entre nós ficam fora do v1.**
Mensagem direta alcança 1; arquivo escrito uma vez é lido por muitos — exigir coordenação por arquivo cortou ~42% dos tokens de saída a 8 agentes (2608.16801). NL entre agentes come 40–60% do orçamento de tokens (2608.25277). Inter-agent misalignment é 36.9% das falhas de MAS e **não se resolve com protocolo de mensagem** (2503.13657, Insight 2). PatchBoard troca diálogo por mutação validada e vai a 84.6% com 45.5k tokens/sucesso contra 368.3k do LangGraph.
*Corolário:* o `handoff.md` do v0 já está certo. O erro seria adicionar um bus.

**R4 — Toda escrita passa por um contrato de escrita por nó, verificado por código.**
PatchBoard: 0% de contaminação por escrita não autorizada; remover o write contract custa −8 pp e +11% tokens/sucesso; remover a interface patch/schema custa −15 pp e **2.34× tokens/sucesso**. Claude Code docs: "dê a cada teammate um conjunto de arquivos próprio" é a mitigação de conflito recomendada. No nosso caso não precisamos de JSON Patch: `writes:` e `reads:` como globs no YAML, e o orquestrador compara a árvore antes/depois. Escreveu fora → nó falha.

**R5 — Toda interface entre dois nós precisa de um dono declarado.**
Falha medida: cálculo de 8 passos, 1 por agente, falhou 10/10 numa convenção que ficava entre dois donos e não pertencia a nenhum; foi discutida todo run e nunca resolvida (2608.16801). Decomposição cria interfaces. No YAML: toda aresta declara o artefato **e** o nó responsável pelo formato dele.

**R6 — Parada é predicado determinístico. Texto do modelo não é parada.**
100% das 68 IALs confirmadas = ausência de bound forte; **model-controlled termination em 38.2%** e é explicitamente classificada como *não-bound* (2607.01641). Verificação superficial (compila? tem TODO?) é o modo de falha 3.2 do MAST, e adicionar verificação de objetivo de alto nível deu +15.6% (2503.13657).
*Consequência dura para o v0:* `DONE.md` escrito pelo builder **não é critério de parada** — é uma alegação do modelo. O critério tem que ser um comando que sai 0.

**R7 — Três camadas de bound, e a última é incondicional.**
Camada 1: gate verificável (comando exit 0). Camada 2: no-progress (hash do artefato inalterado por k rodadas — o análogo barato e file-based do stopper geométrico: −38% de tokens a paridade, k=2 para tolerar ruído). Camada 3: failsafe de budget, **nunca ablável** — é o que dá o teorema de terminação (2606.27009, Thm 1). E não gaste um juiz LLM a cada rodada para decidir parar: a variante quality-gated custou **+129% de tokens** sem ganho.

**R8 — Orçamento por nó e por sessão. O por-nó sozinho não fecha a conta.**
Hermes tem budget por agente, e pai + 3 subagents estouram o cap do pai por construção. Anthropic mede 3–10× (blog jan/26) e ~15× (research system) contra single-agent. Precisa de um teto de sessão em wall-clock e em bytes de log, não só de iterações por nó.

**R9 — Formato de handoff por tipo de aresta. Estrutura onde há dependência, prosa onde há exploração.**
DAG tipado: +12.7 pp (τ-retail), +8.7 pp (BrowseComp), **−14.6 pp (AppWorld)**. Por padrão de tarefa: agregação +6.7, iterate −7.0, conditional −18.2 (2608.25277). E o schema só funciona com instrução de interpretação no receptor. Então: aresta declara `handoff: structured|prose`, e `structured` gera automaticamente o preâmbulo de leitura no nó de destino.

**R10 — Contexto do nó: regras verbatim + ponteiros para artefatos, nunca conteúdo de artefato.**
Compaction cliff: safety rule cai a 53% em 1 rodada e 10% em 5 sob compactação type-blind (2608.22752). Hermes acerta ao congelar o tier de regras. PatchBoard: **o menor budget de contexto testado (1k) tem o melhor perfil** — mais estado exposto não melhora decisão local. Context rot: janela de 200k degrada já em ~50k e a posição do meio é a pior (Chroma, `[resumo de busca]`). O preâmbulo gerado pelo orquestrador passa **caminhos** de artefato, não os artefatos.

**R11 — Layout de sessão fixo. O time não reorganiza o próprio diretório.**
Store curado por agente foi o pior em um tier (37.5 contra 78.1 do dump); "foldered sessions" — o mais barato e estruturado, uma pasta por unidade, sem curadoria — foi o líder mais consistente; um passe de reorganização condensante destruiu o store (77.6→41.2); aderência à taxonomia erode com o crescimento (2607.26637). E: **trocar o toolset remodela o store tanto quanto trocar o modelo** — a forma do diretório é uma decisão do harness, não do agente.

**R12 — Mutação de grafo: no máximo 1 por sessão, catálogo fechado, aplicada por código.**
MANTA aplica ≤3 operações a uma cópia, valida papéis/referências/nesting/limites e só então comita; a **primeira mutação captura a maior parte do ganho**; e o planejamento inicial de topologia vale mais que a mutação (71.7→57.5 vs →60.8). Dos 5 reparos observados, só um aumenta o sistema — os outros serializam, religam ou inserem crítico. **Auto-gerenciar não é recrutar.**

**R13 — Não rotule um nó de "lead" esperando que isso crie estrutura.**
Filtro de disparidade: 0 de 1170 arestas formam hub quando um coordenador é nomeado por prompt, e não há ganho confiável de sucesso; replicação selada confirma paridade a 8 agentes (2608.16801). Hierarquia tem que estar no grafo (quem lê o quê, quem escreve o quê), não no adjetivo do prompt.

**R14 — Prefira misturar modelos/CLIs a clonar.**
Pares heterogêneos são puxados para o membro forte, não para a média aritmética (OLS y=1.35x−0.27, 2608.22152). O Maestro Mode do Maestri tende a recrutar cópias de si mesmo — é a composição errada. Aqui isso é gratuito: `claude` num nó, `cursor-agent` no outro.

**R15 — Um run é amostra de tamanho 1.**
A mesma célula colhida duas vezes deu expoente 1.76 e 2.44 com modelo pinado (2608.16801); consumo de token em coding agentic varia até 30× entre runs idênticos. Nenhuma decisão de desenho pode sair de um run.

---

## 4. Modelo de grafo que eu proponho

### 4.1 O que manter do v0 (sem discussão)

- **YAML como fonte única, lido pelo runtime.** A spec e o runtime são o mesmo arquivo. Mantém.
- **Sessão = diretório em disco.** Não existe time fora de um `session_dir`. Mantém.
- **Subprocesso com log por nó, sem tmux no runtime.** Determinístico, testável sem display. Mantém.
- **`claude -p --output-format text`, env sem `ANTHROPIC_API_KEY`, abort antes de subir nó se `claude auth status` falhar.** Mantém, e vira mais importante: exit code é o único sinal de controle que temos.
- **`handoff.md` como handoff visível único.** R3 diz que está certo. Mantém — o que muda é o formato dele, não a existência.
- **Serial no v0.** Manter *até* R0 passar. Paralelismo antes do baseline é otimizar o desconhecido.

### 4.2 O que evolui, e por quê

| v0 | v1 | Regra |
|---|---|---|
| 1 tipo de nó (`agent`) | 4: `agent`, `check`, `fanout`, `join` | R6 (check é o único que pode parar), R2 |
| 1 predicado (`artifact_exists`) | 5: `artifact_exists`, `artifact_valid`, `check_passed`, `check_failed`, `always` | R6, R7 |
| estado = status + existência de artefato | + ledger de artefato (path, hash, escritor, mtime) + contadores de budget | R4, R7, §5 |
| sem contrato de escrita | `reads:`/`writes:` como globs, verificados por diff de árvore | R4 |
| parada = `DONE.md` existe | parada = conjunção de `check` nós que saíram 0 | **R6** |
| DAG estrito | DAG + ciclos **nomeados** com `max_iters` explícito | R7 |
| sem budget | budget por nó + por sessão, failsafe incondicional | R7, R8 |
| grafo fixo | 1 mutação por sessão, catálogo fechado de 4 operações | R12 |
| — | baseline de 1 nó obrigatório, mesma tarefa | **R0** |

### 4.3 Tipos de nó

- **`agent`** — subprocesso de CLI. Tem `bin` (`claude` \| `cursor-agent`), `prompt`, `cwd`, `reads`, `writes`, `iters`. É a única coisa cara.
- **`check`** — comando determinístico, **zero LLM**. O exit code *é* a verdade. É o único tipo que pode aparecer no `stop`. Isso é a diferença entre um bound e uma alegação (R6). É também o "verification subagent" da Anthropic, mas sem gastar um agente.
- **`fanout`** — um template de `agent` × uma partição declarada. Cada instância recebe uma fatia de `writes` disjunta (R2, R4). `max: 3` é o teto do schema, não do prompt.
- **`join`** — `agent` que lê as saídas do fanout. É o único ponto onde os ramos se veem. Sem malha entre ramos (R3).

### 4.4 Tipos de aresta

Predicado + formato. O formato é primeira classe porque a literatura mostra que ele vale ±12 pp (R9).

- `artifact_exists: <path>` — o do v0.
- `artifact_valid: <path>` — roda o validador declarado do artefato. Impede o modo "escreveu o arquivo vazio para desbloquear".
- `check_passed: <check-id>` / `check_failed: <check-id>` — a segunda é a aresta de recuperação, e é a única que pode fechar ciclo. Carrega `max_repeats`.
- `always` — só dentro de `fanout`.
- `handoff: structured | prose` — `structured` exige as seções declaradas e injeta o preâmbulo de leitura no destino.

### 4.5 Estado de sessão

`state.json` deixa de ser só status. Ele é o ledger — a versão em disco e single-writer do blackboard do PatchBoard, sem kernel LLM:

1. **nós**: `pending | running | done | failed | skipped`
2. **artefatos**: `{path, sha256, writer_node, mtime, valid}` — hash é o que dá no-progress e retrabalho de graça (§5)
3. **budget**: `iters_used` por nó, `wall_seconds`, `log_bytes` da sessão
4. **violações**: escrita fora do contrato, com o path
5. **mutações**: no máximo uma, com a operação e o motivo

O orquestrador é o único escritor de `state.json`. Nenhum nó o lê ou escreve — o nó recebe caminhos no preâmbulo (R10).

### 4.6 Como paralelizar sem virar bagunça

Quatro travas, todas checáveis antes de subir nó:

1. **`fanout.max: 3`** (R2).
2. **`writes` das instâncias precisam ser disjuntas** — validado no `up`. Sobreposição = grafo inválido, não corrida em runtime (R4, Claude Code docs).
3. **Ramos não se comunicam.** Nenhuma aresta ramo→ramo. Toda convergência passa pelo `join` (R3).
4. **Toda interface entre ramos tem dono nomeado** no `join`, não implícito (R5).

Se o trabalho não passa nas quatro, ele é sequencial. Serializar é um dos reparos de topologia observados no MANTA e é frequentemente o certo.

### 4.7 Como o grafo se auto-gerencia sem virar loop infinito

Auto-gestão = **reparo estrutural limitado**, não recrutamento.

- **Gatilho:** só sinais de processo observáveis pelo orquestrador, nunca o gabarito e nunca a opinião de um agente sobre si mesmo. Sinais: `check` falhou 2×; violação de contrato de escrita; no-progress (hash inalterado por 2 rodadas); um ramo de fanout consumiu >60% do budget da sessão.
- **Catálogo fechado, 4 operações** (as do MANTA que não aumentam o sistema, mais uma que aumenta):
  1. `insert_check` — inserir gate antes de um nó que produziu artefato inválido
  2. `serialize` — colapsar um fanout em cadeia (o reparo para escrita duplicada)
  3. `rewire` — mover uma aresta de leitura (dar ao nó o artefato que ele estava tentando inferir)
  4. `split` — expandir um nó sobrecarregado em fanout de 2 (a **única** que aumenta; exige budget sobrando)
- **Orçamento: 1 mutação por sessão.** A primeira captura a maior parte do ganho (MANTA).
- **Aplicada por código a uma cópia, validada, e só então comitada.** Validações: `max_nodes`, disjunção de `writes`, todo ciclo tem `max_repeats`, todo `stop` continua alcançável. Proposta inválida é descartada, não "reparada".
- **O plano inicial vale mais que o reparo** (71.7→57.5 sem planejamento inicial, contra →60.8 sem mutação). Não invista em mutação antes de investir no grafo inicial.

Loop infinito é impossível por construção: mutação ≤1, ciclo ≤`max_repeats`, sessão ≤`wall_seconds`, e o failsafe é incondicional (R7).

### 4.8 YAML concreto

```yaml
id: v1
# R0 — o time compete contra isto. up roda os dois e compara.
baseline:
  bin: claude
  prompt: prompts/baseline.md      # procedimento inteiro no prompt, 1 nó
  compare_on: [stop_reached, wall_seconds, log_bytes, gate_first_pass]

# R7/R8 — failsafe incondicional, nunca ablável
budget:
  wall_seconds: 2400
  log_bytes: 4000000
  iters_default: 4
  max_nodes: 8
  mutations: 1
  no_progress_rounds: 2            # hash de artefato inalterado ⇒ halt

# R5 — todo artefato tem dono e validador
artifacts:
  handoff.md:
    owner: scout
    format: structured
    sections: [OBJETIVO, ARQUIVOS, ACEITE, FORA_DE_ESCOPO]
    validate: "bin/has-sections handoff.md OBJETIVO ARQUIVOS ACEITE FORA_DE_ESCOPO"
  parts/*.md:
    owner: builder
    format: prose
  report.md:
    owner: integrator
    format: structured
    sections: [FEITO, NAO_FEITO, RISCOS]
    validate: "bin/has-sections report.md FEITO NAO_FEITO RISCOS"

nodes:
  # ---- scout: relay barato (só um brief), δ≈0 ⇒ decompor vale (R1)
  - id: scout
    type: agent
    bin: claude
    prompt: prompts/scout.md
    cwd: "."
    reads:  ["spec/**"]
    writes: ["handoff.md"]         # R4 — escreveu fora ⇒ failed
    iters: 2

  # ---- fanout ≤3, writes disjuntas (R2, R4)
  - id: builder
    type: fanout
    max: 3
    template:
      type: agent
      bin: cursor-agent            # R14 — heterogêneo de propósito
      prompt: prompts/builder.md
      iters: 5
    partition:
      - {slot: a, reads: ["handoff.md","src/a/**"], writes: ["src/a/**","parts/a.md"]}
      - {slot: b, reads: ["handoff.md","src/b/**"], writes: ["src/b/**","parts/b.md"]}
      - {slot: c, reads: ["handoff.md","src/c/**"], writes: ["src/c/**","parts/c.md"]}

  # ---- único ponto de convergência; dono das interfaces entre slots (R3, R5)
  - id: integrator
    type: agent
    bin: claude
    prompt: prompts/integrator.md
    reads:  ["handoff.md","parts/*.md","src/**"]
    writes: ["src/**","report.md"]
    iters: 4
    owns_interfaces: [a-b, b-c, a-c]

  # ---- R6: o único tipo que pode parar a sessão. zero LLM.
  - id: tests
    type: check
    run: "bin/run-tests"
    timeout_seconds: 300

  - id: contract
    type: check
    run: "bin/check-writes --state state.json"   # nenhuma violação de writes

edges:
  - {from: scout,      to: builder,    on: artifact_valid, artifact: handoff.md, handoff: structured}
  - {from: builder,    to: integrator, on: always,                                handoff: prose}
  - {from: integrator, to: tests,      on: artifact_valid, artifact: report.md}
  - {from: tests,      to: integrator, on: check_failed,   check: tests, max_repeats: 2, handoff: structured}

# R6/R7 — conjunção de checks determinísticos. Nenhum artefato escrito por modelo aparece aqui.
stop:
  all_of: [tests, contract]
  failsafe: budget                 # incondicional; exit 2

# R12 — auto-gestão limitada
repair:
  budget: 1
  triggers: [check_failed_twice, write_contract_violation, no_progress, branch_budget_hog]
  ops: [insert_check, serialize, rewire, split]
  validate: [max_nodes, disjoint_writes, every_cycle_bounded, stop_reachable]
```

**O que mudou de mais consequente contra o v0, em uma linha:** `DONE.md` some do `stop`. A sessão para porque um comando saiu 0, não porque um modelo escreveu que terminou.

---

## 5. Métricas da sessão

Tudo derivável de `state.json` + `logs/*.log` + hashes de arquivo. Zero API, zero juiz LLM (R7: juiz por rodada custou +129%).

### 5.1 Custo — proxies sem contador de token

| Métrica | Como | Por quê |
|---|---|---|
| `wall_seconds` por nó e total | `date +%s` no wrapper | único custo direto observável sem API |
| `log_bytes` por nó | `wc -c logs/<node>.log` | proxy de token de saída. Token explica 80% da variância de desempenho em browsing (Anthropic) |
| `prompt_bytes` por nó | `wc -c` do preâmbulo gerado | detecta inchaço de contexto (R10) |
| `cost_ratio` | `log_bytes(grafo) / log_bytes(baseline)` | Anthropic mede 3–10× e ~15×. Se o nosso passar de ~4× sem ganhar em `stop_reached`, o grafo é bloat |

### 5.2 Progresso e retrabalho

| Métrica | Como | Por quê |
|---|---|---|
| `rework_count` por artefato | nº de escritas com **hash diferente** do anterior | retrabalho real |
| `null_writes` | escritas com **hash idêntico** ao anterior | MAST FM-1.3 step repetition, 15.7% das falhas |
| `no_progress_rounds` | rodadas consecutivas com hash inalterado no artefato-alvo do ciclo | é o gatilho de halt (R7); análogo file-based do stopper geométrico (−38% de tokens a paridade) |
| `iters_used / iters` por nó | contador | quem está encostado no teto é candidato a `split` |
| `budget_fraction` da sessão | `wall_seconds/limite`, `log_bytes/limite` | um ramo acima de 60% dispara reparo |

### 5.3 Qualidade do handoff

| Métrica | Como | Por quê |
|---|---|---|
| `handoff_valid` | validador do artefato saiu 0 na primeira tentativa? | seções faltando = 76% das falhas multi-agente são misalignment de ordering/pré-requisito (2608.25277) |
| `handoff_uptake` | fração das linhas não-triviais de `handoff.md` cujo 6-grama aparece em algum artefato ou log a jusante (`grep -F -f`) | **proxy meu, não da literatura.** Uptake baixo ⇒ o nó a jusante ignorou o handoff ⇒ MAST FM-2.5 (ignored other agent's input). Uptake ~1.0 com `rework` alto ⇒ o handoff estava errado, não ignorado |
| `handoff_bytes / total_log_bytes` | divisão | NL entre agentes come 40–60% do orçamento em MAS de referência. Se passar disso, estruture a aresta (R9) |

### 5.4 Verificação e contrato

| Métrica | Como | Por quê |
|---|---|---|
| `gate_first_pass` | fração de `check` que passa na 1ª tentativa | MAST FC3 é 21.3% das falhas; verificação superficial é o modo 3.2 |
| `gate_attempts` | tentativas até passar | mede o custo real do ciclo |
| `write_violations` | arquivos tocados fora de `writes` | PatchBoard levou isso a 0%; qualquer valor >0 é bug de desenho do grafo |
| `orphan_writes` | arquivos criados que nenhum nó a jusante lê | ramo paralelo produzindo saída redundante (5/104 falhas do TIPEX) |
| `stop_reason` | `gate` \| `no_progress` \| `budget` \| `failed` | se `budget` domina, não existe bound efetivo (2607.01641: 100% das IALs) |

### 5.5 As duas comparações que decidem tudo

- **`collab_tax = stop_reached(baseline) − stop_reached(grafo)`** sobre o mesmo conjunto de tarefas. Positivo = o grafo custa e perde. A literatura mede isso positivo na maioria das células (2608.22152) e é o resultado default esperado.
- **`repair_efficacy`** = fração de reparos após os quais o gatilho não reaparece. MANTA: flags caem após 60.9% dos reparos, 59.6% dos alvos somem do próximo audit. Abaixo disso, o catálogo de reparo está errado.

**E a regra de leitura de tudo acima:** mínimo **5 seeds por célula** antes de qualquer decisão. A mesma célula com modelo pinado deu expoente de crescimento 1.76 e 2.44 (2608.16801); um run é amostra de tamanho 1 (R15).

---

## 6. Riscos e lacunas

**O que eu não consegui verificar.**

1. **Nada na literatura mede orquestração por CLI de assinatura.** Todo paper assume endpoint HTTP com contagem de token. As nossas métricas de custo (`log_bytes`) são proxy não validado. Risco real: `log_bytes` pode não correlacionar com custo/uso de janela, porque `--output-format text` não expõe o que foi lido.
2. **PTY / agente-digitando-em-agente: zero literatura.** Não posso dizer se a detecção heurística de fim-de-turno do Maestri é boa ou ruim — só que não é um bound (R6). Se o dono quiser esse mecanismo, ele estará em terreno não medido.
3. **Roteamento por descrição de agente não foi isolado por ninguém que eu tenha lido.** Ao afirmar que o Grok Bot é frágil aí, estou extrapolando do roteador de *formato* (2608.25277).
4. **`handoff_uptake` é invenção minha.** Nenhum paper mede consumo do handoff a jusante. 2608.16801 mede a rede, não o uso. O n-grama por `grep` vai gerar falso positivo quando o artefato e o handoff compartilham vocabulário de domínio. Precisa de calibração num par de sessões reais antes de virar métrica de decisão.
5. **Collaboration tax só foi medida em N=2**, tarefas sintéticas (grid, grafo, CSP), e os próprios autores dizem que não sabem se a cascata de 4 estágios generaliza para N≥3 nem para workload de produção (código, triagem de issue, debugging).
6. **MAST é de mar/2025 (v3 out/2025), com GPT-4/Claude 3.** As distribuições de falha (41.8/36.9/21.3) provavelmente mudaram com modelos de 2026. Uso a taxonomia, não os percentuais, como base de desenho.
7. **Não achei benchmark de time de agentes sobre CLI local em Linux.** Todos os números de time (Anthropic, Claude Code docs) são de dentro do produto Anthropic, com contexto e cache que a gente não tem via `-p`.
8. **Não verifiquei o Maestri rodando.** Tudo em §1.1 vem do DOSSIE.md e da doc oficial. Especificamente: "Maestri detecta que o receptor terminou" ser heurística de PTY é **inferência minha** a partir da regra de foco documentada, não afirmação da doc.
9. **Não medi nada.** Este documento é desenho a partir de leitura. A primeira coisa a fazer não é implementar o v1 — é rodar R0 no v0 atual e ver se o grafo de 2 nós bate um `claude -p` só.
10. **Compaction cliff foi medida sobre `/compact` do Claude Code em sessão interativa.** Nosso caso (`-p`, sessão curta, um turno por nó) pode não compactar nada — nesse caso R10 é barato e inofensivo, mas o número de 53%/10% não se aplica diretamente a nós.

**Riscos de desenho que eu estou assumindo conscientemente.**

- **R0 pode matar o projeto e isso é bom.** Se um `claude -p` com o procedimento inteiro bate o grafo em tudo (é o resultado default da literatura em tarefa procedural), o valor do `mathai-orchestrator` não está em "time de agentes bate agente sozinho". Está em **contrato de escrita, budget e parada verificável rodando acima de CLIs que não têm nada disso** — que é uma tese diferente, mais defensável, e que nenhum dos três (Maestri, Grok Bot, Hermes) implementa por completo.
- **`check` como único tipo que pode parar** torna o orquestrador dependente de o usuário escrever um comando de verificação real. Sem isso, o grafo cai no failsafe de budget toda vez. É uma fricção deliberada: a alternativa é aceitar `DONE.md`, e aí não há bound.
- **Fan-out de 3 com writes disjuntas** só funciona onde a tarefa particiona por arquivo. Em tarefa de spec compartilhada, a topologia que emerge é malha densa (2608.16801) e o fanout vai brigar consigo mesmo. Nesses casos o grafo correto tem 1 nó.

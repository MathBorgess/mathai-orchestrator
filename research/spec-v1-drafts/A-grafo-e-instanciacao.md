# Spec v1 — §1 Modelo do grafo · §2 Como um time é instanciado

**Substitui:** [`SPEC.md`](../SPEC.md) §1 e §2 (v0). · **Deriva de:** [`MVP.md`](../MVP.md) §1–2 · [mesa-redonda](../research/2026-08-30-mesa-redonda.md) (14 pontos de consenso) · [memorial 01](../research/teammates/01-pesquisador-harness-graph.md)
**Frente:** A (Peko). `writes: [SPEC.md §1, SPEC.md §2, graphs/v1.yaml]`. Nada fora disso.
**Emenda declarada ao `MVP.md` §9:** `fanout` e `join` saem da "camada 4" e entram no v1 como tipos de primeira classe. O corte "serial no v0" cai. As travas que sustentavam o corte continuam todas de pé, e agora são regras de validação do loader, não conselho.

Toda escolha abaixo traz o descarte. Decisão sem alternativa não entra.

---

## 1. Modelo do grafo

### 1.1 Os quatro conceitos

| Conceito | É | Não é |
|---|---|---|
| **Nó** | Uma unidade de trabalho com identidade, contrato de escrita e orçamento próprios. Quatro tipos: `agent`, `check`, `fanout`, `join` | Um thread dentro do Claude Code. Um papel. Um adjetivo no prompt |
| **Aresta** | Uma condição de prontidão: `from`, `to`, `on` (um dos 5 predicados), e — quando carrega artefato — `artifact` e `handoff` | Uma chamada de API. Um bus. Um canal de conversa. Uma mensagem |
| **Artefato** | Um arquivo no `session_dir` com **dono único declarado**, formato declarado e verificador declarado | Qualquer arquivo que um nó por acaso escreveu |
| **Sessão** | Uma instância viva de **um** grafo, materializada como um diretório em disco. Sessão = time | Um chat. Um PR. Um worktree do vault. Um processo daemon |
| **Estado** | `state.json`: 6 campos, escritos **só** pelo orquestrador, lidos por **nenhum** nó | Histórico de tokens. Transcript. Memória compartilhada entre agentes |

Identificadores de nó: `^[a-z][a-z0-9_-]{0,31}$`. Slots de partição: `^[a-z0-9]{1,8}$`. O arquivo canônico é YAML (`graphs/*.yaml`), e é o mesmo arquivo que o runtime lê.

**Escolhida / descartada.** Quatro tipos de nó, não um genérico com flags. Custo: o loader cresce, e um tipo novo depois exige emenda nesta spec. Ganho: `check` é o único tipo que pode aparecer no `stop` — a restrição vira gramática, não convenção; e `fanout` deixa de ser "um `agent` com `count: 3`", que é a forma em que a partição fica implícita e portanto não-validável. Descartada a alternativa de um `agent` com `parallel: true`: sem `partition` declarada não há como o `up` provar que as escritas são disjuntas, e sem essa prova o fan-out é corrida, não paralelismo.

**Escolhida / descartada.** Artefato promovido a conceito de primeira classe, com bloco `artifacts:` no topo do grafo. Custo: mais um bloco, e o dono precisa declarar o que antes era implícito. Ganho: "dois nós reivindicando o mesmo artefato" vira checagem sintática de um dicionário em vez de travessia de grafo; duas arestas que carregam o mesmo artefato não podem discordar sobre como verificá-lo; e o predicado de conclusão de um nó deixa de depender de ele ter uma aresta de saída — o que era um buraco assim que existe `fanout` (uma instância não tem aresta de saída própria). Descartado manter `verify:` inline na aresta (`MVP.md` §3): funciona com 2 nós e quebra com 3 ramos.

**Emenda ao `MVP.md` §3.** O predicado de conclusão continua sendo a conjunção de quatro. O quarto termo muda de `verify(edge.artifact)` para `verify(todos os artefatos cujo owner é este nó)`. Para um `agent` com uma aresta de saída, os dois coincidem — e o `up` garante que coincidam (regra V-14). Para uma instância de `fanout`, só a segunda forma existe.

---

### 1.2 Tipos de nó — campos exatos

#### `agent`

A única coisa cara. Um subprocesso de CLI.

| Campo | Obrig. | Tipo | Default | Nota |
|---|---|---|---|---|
| `id` | sim | id | — | único no grafo |
| `type` | sim | `agent` | — | |
| `adapter` | não | `claude` \| `cursor-agent` \| `exec` | `claude` | `MVP.md` §5 |
| `prompt` | sim | caminho | — | relativo à raiz do repo; deve existir no load |
| `cwd` | não | caminho | `"."` | relativo ao `session_dir` |
| `reads` | não | lista de globs | `[]` | informativo para o preâmbulo; não é sandbox |
| `writes` | **sim** | lista de globs | — | não pode ser vazia; é o contrato verificado |
| `iters` | não | int ≥1 | `budget.iters_default` | |
| `budget_units` | não | float >0 | `budget.node_units_default` | vira `--max-budget-usd` |
| `timeout_seconds` | **sim** | int >0 | — | timeout no processo **pai** |
| `tools` | não | `{allow: [], deny: []}` | herda de `budget.tools` | é a ACL do nó, não refinamento |
| `model` | não | string | — | ausente = default da assinatura |

`reads` é informativo por decisão: nenhum CLI dá sandbox de leitura, e prometer uma que não existe é pior que não prometer. Ele entra no preâmbulo gerado e no veredito (`orphan_writes` cruza `writes` de um nó com `reads` de todos os outros). `writes` é o contrato de verdade, verificado por diff de árvore.

#### `check`

Comando determinístico. **Zero LLM.** O exit code *é* a verdade. É o único tipo que pode aparecer no `stop`.

| Campo | Obrig. | Tipo | Default | Nota |
|---|---|---|---|---|
| `id` | sim | id | — | |
| `type` | sim | `check` | — | |
| `run` | sim | lista argv | — | **executado sem shell**; sem expansão, sem `&&`, sem pipe |
| `cwd` | não | caminho | `"."` | |
| `timeout_seconds` | não | int >0 | `300` | |

Um `check` tem `writes: []` implícito e imutável. Qualquer arquivo tocado por um `check` é violação de contrato e derruba a sessão — um verificador que escreve não é verificador, é mais um nó de trabalho sem orçamento.

**Escolhida / descartada.** `run` como lista argv sem shell. Custo: `bin/gate` vira um script de verdade em vez de uma linha com pipe no YAML. Ganho: o grafo é dado versionado que o loader lê; permitir shell aqui é permitir que um grafo alterado execute qualquer coisa com o ambiente do orquestrador, e o `handoff.md` já é escrito por um agente que leu arquivos do repo (`MVP.md` R3). Descartado `run` como string com shell: conveniente e é a superfície de injeção mais barata do sistema.

#### `fanout` — primeira classe

Um template de `agent` × uma partição declarada. É a forma **única** de declarar paralelismo. Não existe outra.

| Campo | Obrig. | Tipo | Default | Nota |
|---|---|---|---|---|
| `id` | sim | id | — | |
| `type` | sim | `fanout` | — | |
| `max` | sim | int, **2 ≤ max ≤ 3** | — | teto duro de schema |
| `rationale` | **sim** | texto, ≥3 linhas | — | as três respostas de §1.4 |
| `template` | sim | bloco `agent` **sem** `id`, `reads`, `writes` | — | o resto dos campos de `agent`, e valem para todas as instâncias |
| `partition` | sim | lista de `{slot, reads, writes}`, 2..`max` itens | — | uma entrada = uma instância |

Instâncias têm id **derivado**, nunca declarado: `<fanout-id>.<slot>` (`build.a`, `build.b`, `build.c`). Esse id aparece em `logs/`, em `state.json`, no `owner` de artefato e no worktree. Não é escolhível.

`rationale` é obrigatório e o `up` **não lê o conteúdo** — ele exige que exista e o copia para o veredito, ao lado de `orphan_writes` e `null_writes` daquele fanout. Um fan-out que não produziu nada é julgado ao lado da justificativa que o criou. Fingir que o loader valida a justificativa seria teatro; a spec não finge.

**Escolhida / descartada.** `max` entre 2 e 3, com o piso em 2. Custo: um "fanout de 1" precisa ser reescrito como `agent`. Ganho: fanout de 1 é um `agent` mal escrito que carrega o custo de schema do paralelismo sem nenhum paralelismo, e ele existe na prática — é o que sobra quando alguém remove instâncias para debugar e esquece de voltar. O teto 3 é o teto do schema; o que sobe sem o dono pedir é 1 (§2, `--max-concurrency`). Descartado teto configurável: um teto que se configura não é teto.

#### `join`

Um `agent` com duas obrigações a mais. É o **único** ponto de convergência de um `fanout`. Ramos não se comunicam.

| Campo | Obrig. | Tipo | Nota |
|---|---|---|---|
| *(todos os campos de `agent`)* | | | |
| `type` | sim | `join` | |
| `from` | sim | id de um `fanout` | exatamente um |
| `owns` | **sim** | lista de nomes de fronteira | precisa cobrir **todos** os pares não-ordenados de slots do `from`, nomeados `<slot_a>-<slot_b>` em ordem lexicográfica |

Com `partition` de 3 slots (`a`,`b`,`c`), `owns` precisa ser exatamente `[a-b, a-c, b-c]`. Faltou um par → o `up` recusa (V-11).

**Escolhida / descartada.** `owns` obrigatório e conferido por contagem, não por texto livre. Custo: burocracia visível no YAML, e um `join` de 3 slots carrega 3 entradas que parecem redundantes. Ganho: decompor cria interfaces, e a interface que não tem dono é onde o time falha em silêncio — medido, um cálculo de 8 passos com 1 passo por agente falhou **10/10 runs** numa convenção de arredondamento que ficava na fronteira entre dois donos, foi discutida em todo run e nunca resolvida (2608.16801). `owns` não conserta a discussão; ele obriga o `join` a saber que a discussão é dele. Descartado deixar as fronteiras implícitas no prompt do `join`: prompt não é validável e o veredito não consegue contá-lo.

---

### 1.3 Predicados de aresta

Cinco, e só cinco.

| `on` | Campos | Dispara quando | Pode fechar ciclo |
|---|---|---|---|
| `artifact_exists` | `artifact` | o arquivo existe e `from` está `done` | não |
| `artifact_valid` | `artifact` | o `verify` declarado do artefato sai 0 e `from` está `done` | não |
| `check_passed` | `check` | o `check` nomeado saiu 0 | não |
| `check_failed` | `check`, `max_repeats` | o `check` nomeado saiu ≠0 | **sim — a única** |
| `always` | — | **todas** as instâncias do `fanout` de origem estão `done` | não |

`always` só existe em aresta `fanout` → seu `join`. Em qualquer outra posição o `up` recusa (V-10).

Toda aresta que carrega `artifact` carrega também `handoff: structured | prose`. `structured` exige que o artefato declare `format: structured` + `sections`, e faz o orquestrador injetar no preâmbulo do destino a lista de seções e a instrução de leitura. Aresta sem `artifact` não pode declarar `handoff` — o formato pertence ao artefato, e sem artefato não há formato para declarar.

**Escolhida / descartada.** `handoff` como campo por aresta, não configuração global. Custo: mais um campo para errar. Ganho: handoff tipado dá **+12,7 pp** (τ-retail) e **+8,7 pp** (BrowseComp) e **regride −14,6 pp** (AppWorld), onde a tarefa exige iteração adaptativa — por padrão de tarefa: agregação +6,7, iterate −7,0, conditional −18,2 (2608.25277). Não existe resposta global correta. E o mesmo estudo mostra que o schema sozinho não faz nada sem o preâmbulo de leitura no receptor, então `structured` sem o preâmbulo injetado seria custo puro. Descartado sempre-estruturado: perde nos ramos exploratórios, que é exatamente onde o fanout vive.

**Escolhida / descartada.** `always` fecha só quando **toda** instância está `done`. Ramo `failed` ⇒ sessão `failed`; o `join` não roda com sobreviventes. Custo: um ramo instável mata uma sessão que já tinha 2/3 do trabalho, e o operador reroda inteiro. Ganho: o produto é a comparabilidade do número. Um grafo que às vezes entrega 3/3 e às vezes 2/3 produz um `stop_reached` que significa duas coisas diferentes, e aí `collab_tax` não quer dizer nada. Descartado `join` com `missing_slots` no estado: operacionalmente mais útil, e destrói a métrica que justifica o repo existir.

---

### 1.4 Quando um trabalho vira `fanout`, e quando é um nó só

Regra de desenho, aplicável sem ler nenhum paper. Responda as três perguntas **por escrito, no campo `rationale`**, antes de declarar o `fanout`. As três precisam passar. Se qualquer uma falhar, é um nó só, e descobrir isso depois custa uma sessão inteira.

**Pergunta 1 — o handoff cabe numa página?** Escreva à mão o handoff que **uma** instância receberia. Se para trabalhar ela precisa carregar estado exato de quem veio antes — caminho absoluto, hash, ID gerado, saída literal de comando, número de linha, resultado intermediário que só existe no meio do trabalho do upstream — então não é fanout. Separar aqui não isola contexto: obriga o upstream a serializar num texto tudo que ele sabia, e o downstream a reconstruir. Isso é um nó só. O caso bom: cada instância recebe o mesmo brief curto mais o nome da sua fatia, e tudo mais ela descobre lendo os arquivos dela.

**Pergunta 2 — as escritas particionam de verdade?** Liste os arquivos que cada instância vai escrever. Se duas listas se tocam em qualquer caminho, não é fanout — é uma corrida que você vai descobrir no diff. A resposta não pode ser "elas raramente colidem". Ou o repositório já está dividido por dono (`out/a.md`, `out/b.md`, `out/c.md`; `src/api/**`, `src/cli/**`, `src/db/**`), ou o trabalho não está particionado e nenhuma trava do orquestrador vai fazê-lo particionar.

**Pergunta 3 — o que fica na fronteira, e de quem é?** Para cada par de instâncias, nomeie o que fica entre as duas: a convenção compartilhada, o formato de interface, a decisão que as duas precisam tomar igual. Cada item precisa de um dono nomeado — uma das instâncias, ou o `join` via `owns`. Item de fronteira sem dono é a falha silenciosa mais cara do paralelismo: as duas instâncias discutem, nenhuma decide, e o `join` recebe duas metades incompatíveis com aparência de trabalho pronto.

**Teste de descarte, e ele é o que separa paralelismo de espetáculo.** Se o `join` precisa *refazer* o trabalho dos ramos para integrar — reler o material bruto, redecidir o que cada ramo já decidiu, reescrever de ponta a ponta — então os ramos produziram rascunho, não entrega, e você pagou 3× para gerar rascunho que um nó produziria melhor sozinho. O `join` legítimo reconcilia fronteiras e concatena; o `join` ilegítimo é um nó solo que recebeu material de aquecimento caro.

**A conta que decide.** Paralelizar custa: contexto duplicado, handoff, e o `join`. Medido em sistemas de referência, coordenação custa **3–10×** os tokens de um agente solo, e o ganho de decompor **encolhe conforme o modelo fica mais forte**. Então o fanout não precisa empatar — precisa ganhar o suficiente para pagar isso. É por isso que `baseline` é campo obrigatório (§1.7): a resposta "valeu a pena" não é opinião de desenho, é uma linha do veredito.

---

### 1.5 Contrato de escrita

Cada nó declara `writes:` como lista de globs. O orquestrador tira o hash da árvore do `session_dir` antes de subir o nó e depois de ele sair; qualquer caminho criado, modificado ou removido que não case com nenhum glob de `writes` é **violação**: o nó vira `failed`, o path entra em `state.json.violacoes`, e a sessão para.

**Disjunção é decidida sintaticamente, sobre os globs, antes de subir nó — nunca sobre o filesystem em runtime.** A regra de aceitação é deliberadamente estreita: **cada instância de um `fanout` escreve sob um prefixo literal próprio**. Um glob de `writes` é aceito se ele tem a forma `<prefixo literal>` ou `<prefixo literal>/**` ou `<prefixo literal>/*.<ext>`, e dois globs são disjuntos se nenhum dos prefixos literais é prefixo do outro **por componente de caminho** — `out/a` não é prefixo de `out/ab.md` (componentes `a` ≠ `ab.md`), mas é prefixo de `out/a/x.md`. Comparar por string crua aceitaria partições que colidem e recusaria partições que não colidem. Glob com curinga no meio (`out/*/x.md`, `src/**/test_*.py`) é recusado dentro de `partition` — não dentro do grafo inteiro, só onde a disjunção precisa ser provada.

**Escolhida / descartada.** Disjunção por prefixo literal, não por interseção geral de globs. Custo: obriga o repositório a se organizar por dono, e recusa partições que na prática seriam seguras (`out/*.a.md` vs `out/*.b.md`). Ganho: a checagem cabe em ~15 linhas, é decidível, e não tem falso negativo — nunca aceita duas partições que colidem. Decidir interseção de globs no caso geral é um solver, e um solver com bug aceita o grafo que corrompe a sessão. Descartada a alternativa "verificar colisão em runtime com `flock`": aí o fan-out inválido já custou três subprocessos e a sessão já está suja.

---

### 1.6 `state.json` — o ledger

Seis campos. **Único escritor: o orquestrador. Nenhum nó lê, nenhum nó escreve.** Um nó recebe caminhos no preâmbulo, nunca o estado.

| # | Campo | Conteúdo |
|---|---|---|
| 1 | `nodes` | por nó (e por instância de fanout, sob o id derivado): `status` ∈ `pending \| ready \| running \| verifying \| done \| failed \| skipped`, `failure` (classe), `started_at`, `ended_at`, `iters_used`, `attempts`, `session_ref` |
| 2 | `artifacts` | por caminho declarado: `{path, sha256, writer_node, mtime, valid}` — histórico de hashes, não só o último |
| 3 | `budget` | `iters_used` por nó, `cost_units` acumulado, `wall_seconds`, `log_bytes`, `utilization` da última janela observada |
| 4 | `violations` | escrita fora de contrato: `{node, path, kind}` |
| 5 | `mutations` | no máximo uma: `{op, trigger, reason, applied_at}` — vazio no v1 (auto-gestão fica fora, `MVP.md` §9) |
| 6 | `preflight` | `claude --version`, resultado do `auth status`, `--max-concurrency` efetivo, seed, hash do `graph.yaml` |

O histórico de hashes no campo 2 não é luxo: é de onde saem `rework_count` (escritas com hash **diferente**), `null_writes` (escritas com hash **idêntico** — step repetition) e `no_progress_rounds`, que é uma das três camadas de bound. Guardar só o último hash apaga as três métricas.

**Escolhida / descartada.** Single-writer, e nó nunca lê o estado. Custo: um nó não consegue saber o que os outros fizeram — nem por engano. Ganho: é a forma de "artefato é o canal" ser verdade em vez de intenção. Se um nó lê `state.json`, o estado vira um canal lateral não declarado, o contrato de escrita deixa de descrever a comunicação, e o grafo declarado deixa de ser o grafo executado — que é exatamente a propriedade que o produto vende. Descartado expor um `state` read-only ao nó: qualquer leitura é um canal.

`events.jsonl` (append-only, uma linha por transição) continua como em `MVP.md` §1.4, e continua valendo a regra: **o runtime nunca lê esse arquivo para decidir.** Se ler, existem duas verdades.

---

### 1.7 `baseline` — campo obrigatório do grafo

```yaml
baseline:
  adapter: claude
  prompt: prompts/baseline.md      # o procedimento inteiro, um nó
  cwd: "."
  writes: ["out/**"]
  budget_units: 3.00
  timeout_seconds: 1800
  compare_on: [stop_reached, gate_first_pass, rework, cost_ratio, write_violations]
```

Grafo sem `baseline` é recusado no load (V-19). O `up` roda os dois braços (§2.4).

**Escolhida / descartada.** Baseline dentro do arquivo do grafo, não flag de linha de comando. Custo: todo grafo carrega um segundo prompt e toda sessão custa ~2×. Ganho: o braço de controle é versionado junto com o time que ele controla, e muda junto — um baseline mantido fora do grafo desatualiza na primeira mudança de tarefa e passa a medir outra coisa. E se o baseline não estiver no caminho crítico, ele não é rodado. Descartado `--baseline prompts/x.md`: transforma o controle em opção, e opção é o que se corta quando aperta.

---

### 1.8 O YAML canônico — `graphs/v1.yaml`

Roda de verdade: `fanout` de 3, um `join`, dois `check`, um ciclo limitado, baseline. Cada trava com a regra que a justifica.

```yaml
id: v1                                   # deve ser igual ao stem do arquivo (V-1)

# --- braço de controle. Obrigatório (V-19). Roda primeiro (§2.4).
baseline:
  adapter: claude
  prompt: prompts/baseline.md            # o procedimento inteiro num nó só
  cwd: "."
  writes: ["out/**"]
  budget_units: 3.00
  timeout_seconds: 1800
  compare_on: [stop_reached, gate_first_pass, rework, cost_ratio, write_violations]

# --- três camadas de bound. A terceira é incondicional e não é ablável.
budget:
  wall_seconds: 3600                     # failsafe da sessão
  session_units: 6.00                    # soma de cost_units; não sobe nó que estoure
  log_bytes: 8000000
  iters_default: 4
  node_units_default: 1.00
  max_nodes: 8
  no_progress_rounds: 2                  # hash do artefato inalterado 2× ⇒ halt
  tools:                                 # ACL default; nó pode estreitar, nunca alargar
    allow: [Read, Write, Edit, Glob, Grep]
    deny:  [WebFetch, WebSearch, Task, Bash]

# --- dono único por artefato (V-13). verify mora aqui, não na aresta.
artifacts:
  handoff.md:
    owner: scout
    format: structured
    sections: [OBJETIVO, PARTICAO, ACEITE, FORA_DE_ESCOPO]
    verify:
      non_empty: true
      min_lines: 12
      cmd: ["bin/has-sections", "handoff.md", "OBJETIVO", "PARTICAO", "ACEITE", "FORA_DE_ESCOPO"]
  out/a.md: {owner: "build.a", format: prose, verify: {non_empty: true, min_lines: 8}}
  out/b.md: {owner: "build.b", format: prose, verify: {non_empty: true, min_lines: 8}}
  out/c.md: {owner: "build.c", format: prose, verify: {non_empty: true, min_lines: 8}}
  out/REPORT.md:
    owner: merge
    format: structured
    sections: [FEITO, NAO_FEITO, FRONTEIRAS, RISCOS]
    verify:
      non_empty: true
      min_lines: 20
      cmd: ["bin/has-sections", "out/REPORT.md", "FEITO", "NAO_FEITO", "FRONTEIRAS", "RISCOS"]

nodes:
  # ---------------------------------------------------------------- scout
  # Relay barato: o único estado que desce é um brief curto + o nome da fatia.
  # Passa a Pergunta 1 de §1.4 ⇒ separar do fanout é legítimo.
  - id: scout
    type: agent
    adapter: claude
    prompt: prompts/scout.md
    cwd: "."
    reads:  ["spec/**"]
    writes: ["handoff.md"]               # prefixo literal próprio
    iters: 2
    budget_units: 0.50
    timeout_seconds: 600
    tools:
      allow: [Read, Glob, Grep, Write]
      deny:  [WebFetch, WebSearch, Task, Bash, Edit]

  # ---------------------------------------------------------------- fanout
  - id: build
    type: fanout
    max: 3                               # teto duro de schema (V-8)
    rationale: |
      P1 handoff: cada instância recebe handoff.md (uma página) + o nome da fatia.
         Nenhum estado exato do scout precisa atravessar: ID, hash ou saída de
         comando não aparecem no handoff. Passa.
      P2 escritas: out/a.md, out/b.md, out/c.md. Prefixos literais distintos,
         nenhum é prefixo do outro. Nenhuma instância escreve em spec/ nem em
         out/REPORT.md. Passa.
      P3 fronteiras: a-b, a-c e b-c compartilham a convenção de cabeçalho e a
         numeração de seção. Nenhuma instância decide isso: o dono das três é o
         merge, declarado em merge.owns. Passa.
      Descarte: o merge concatena e reconcilia cabeçalho; não relê spec/ nem
      reescreve o conteúdo dos ramos. Se passasse a reescrever, isto vira um nó só.
    template:                            # sem id, sem reads, sem writes (V-9)
      adapter: claude
      prompt: prompts/builder.md
      cwd: "."
      iters: 4
      budget_units: 1.00
      timeout_seconds: 900
      tools:
        allow: [Read, Write, Glob, Grep]
        deny:  [WebFetch, WebSearch, Task, Bash, Edit]
    partition:                           # ids derivados: build.a build.b build.c
      - slot: a
        reads:  ["handoff.md", "spec/a/**"]
        writes: ["out/a.md"]
      - slot: b
        reads:  ["handoff.md", "spec/b/**"]
        writes: ["out/b.md"]
      - slot: c
        reads:  ["handoff.md", "spec/c/**"]
        writes: ["out/c.md"]

  # ---------------------------------------------------------------- join
  # Único ponto de convergência. Ramos não se comunicam (V-12).
  - id: merge
    type: join
    from: build
    adapter: claude
    prompt: prompts/merge.md
    cwd: "."
    reads:  ["handoff.md", "out/a.md", "out/b.md", "out/c.md"]
    writes: ["out/REPORT.md"]
    owns:   [a-b, a-c, b-c]              # todos os pares de slots (V-11)
    iters: 4
    budget_units: 1.00
    timeout_seconds: 900
    tools:
      allow: [Read, Write, Glob, Grep]
      deny:  [WebFetch, WebSearch, Task, Bash]

  # ---------------------------------------------------------------- checks
  # Zero LLM. O único tipo que pode aparecer no stop (V-16).
  - id: gate
    type: check
    run: ["bin/gate-report", "out/REPORT.md"]
    cwd: "."
    timeout_seconds: 120

  - id: contract
    type: check
    run: ["bin/check-writes", "state.json"]   # violations == []
    cwd: "."
    timeout_seconds: 60

edges:
  - {from: scout, to: build,    on: artifact_valid, artifact: handoff.md,    handoff: structured}
  - {from: build, to: merge,    on: always}                                  # sem artifact ⇒ sem handoff (V-15)
  - {from: merge, to: gate,     on: artifact_valid, artifact: out/REPORT.md, handoff: structured}
  - {from: gate,  to: merge,    on: check_failed,   check: gate, max_repeats: 2}   # único ciclo, limitado (V-6)
  - {from: gate,  to: contract, on: check_passed,   check: gate}

# --- a sessão para porque um comando saiu 0. Nunca porque um modelo escreveu que terminou.
stop:
  all_of: [gate, contract]
  failsafe: budget                       # incondicional; exit 2
```

Arquivos que este grafo exige existir no load: `prompts/baseline.md`, `prompts/scout.md`, `prompts/builder.md`, `prompts/merge.md`, `bin/has-sections`, `bin/gate-report`, `bin/check-writes`. Ausência de qualquer um é recusa (V-3, V-17).

**Escolhida / descartada — emenda à `SPEC.md` §5.** `DONE.md` sai do critério de parada e não volta. Custo: exige que o dono escreva um comando de verificação de verdade; sem isso toda sessão cai no failsafe de budget e o veredito diz `stop_reason: budget`, que é o resultado honesto. Ganho: um bound de verdade. Descartada a alternativa de aceitar `DONE.md`: a varredura de 6.549 repositórios confirmou 68 loops infinitos em 47 projetos, **100% com a mesma causa raiz — ausência de bound forte** —, e "terminação controlada pelo modelo" aparece em **38,2%** classificada explicitamente como *não-bound* (2607.01641). Um arquivo que o modelo escreve é alegação, não predicado.

---

## 2. Como um time é instanciado

### 2.1 Comando

```
orch up graphs/<id>.yaml --session-dir .sessions/<session_id>
                         [--max-concurrency N]   # 1..3, default 1
                         [--seed K]              # default 1
                         [--no-baseline]         # marca a sessão, não a esconde
```

`--max-concurrency` limita **o que sobe sem o dono pedir**; `fanout.max` limita **o que pode ser declarado**. Não se contradizem, e nenhum dos dois é clamp: `--max-concurrency 4` é recusa, não ajuste silencioso. Com `N=1` as instâncias de um `fanout` rodam em série, na ordem da `partition`, e o grafo continua idêntico — o veredito registra `concurrency: 1` no `preflight` para que duas sessões com concorrência diferente não sejam comparadas por engano.

**Escolhida / descartada.** Default 1, paralelo opt-in explícito. Custo: o comportamento de fábrica não é o que o produto demonstra; quem quiser ver três agentes trabalhando precisa passar uma flag. Ganho: uma frota headless numa assinatura de consumidor é exatamente o padrão que a plataforma mede, e a mitigação custa zero aqui. Descartado default 3: transforma a primeira execução de qualquer usuário no pior caso de utilização da janela.

**Escolhida / descartada.** `--no-baseline` existe e é ruidoso: `state.json.preflight.baseline = "skipped"`, e o veredito imprime `sem braço de controle` na linha de **toda** métrica comparativa, em vez do número. Custo: um caminho a mais no relatório. Ganho: quem pula o controle vê a ausência dele em todo lugar onde teria visto o número; a alternativa honesta seria não ter a flag, e aí ela reaparece como um `sed` no YAML, fora do registro.

### 2.2 A lista literal de recusas do loader

O `up` recusa **antes de subir qualquer nó**. Grafo inválido é erro de compilação, não aviso em runtime.

Estrutura:

- **V-1** `id` do grafo ≠ stem do arquivo.
- **V-2** id de nó, ou slot, fora do padrão; id duplicado; id derivado de instância colidindo com id declarado.
- **V-3** `prompt` de um `agent`/`join`/`baseline` que não existe no disco.
- **V-4** aresta apontando para nó inexistente.
- **V-5** nó órfão: sem aresta de entrada e não sendo o único nó-fonte alcançável.
- **V-6** ciclo sem `max_repeats`, ou ciclo formado por aresta que não seja `check_failed`.
- **V-7** `stop` inalcançável a partir do nó-fonte.

Paralelismo:

- **V-8** `fanout.max` fora de `2..3`; `len(partition)` fora de `2..max`.
- **V-9** `template` declarando `id`, `reads` ou `writes`.
- **V-10** `on: always` fora de uma aresta `fanout` → seu `join`.
- **V-11** `join.owns` ≠ o conjunto exato dos pares não-ordenados dos slots do `from`, nomeados em ordem lexicográfica.
- **V-12** aresta entre duas instâncias do mesmo `fanout`; instância cujo `reads` casa com o `writes` de outra instância do mesmo `fanout`.
- **V-12b** `fanout` sem `join` a jusante, ou com mais de um `join` cujo `from` o aponte.
- **V-12c** `fanout` sem `rationale`, ou com `rationale` de menos de 3 linhas.

Contrato de escrita e artefatos:

- **V-13** dois nós declarando `writes` que casam com o mesmo artefato declarado; artefato declarado sem `owner`; `owner` que não é um id de nó ou de instância. O bloco `baseline` **não participa** desta checagem: ele roda em `session_dir/baseline/`, namespace próprio, e por isso pode declarar `writes` largo (`out/**`) sem colidir com os donos do grafo.
- **V-14** aresta `artifact_exists`/`artifact_valid` cujo `artifact` tem `owner` ≠ `from`.
- **V-15** aresta com `handoff` mas sem `artifact`; `handoff: structured` sobre artefato cujo `format` não é `structured` ou que não declara `sections`.
- **V-16** `stop.all_of` referenciando algo que não é um nó `check`.
- **V-17** `check.run` cujo primeiro elemento não existe ou não é executável.
- **V-18** `check.run` cujo basename está na denylist de binários de agente (`claude`, `cursor-agent`, `codex`, `opencode`, `aider`, `llm`, `ollama`) ou cujo argv contém `-p`/`--print`. *A denylist é incompleta por natureza: ela pega o erro honesto, não o adversário.*
- **V-19** grafo sem bloco `baseline`.
- **V-20** `writes` vazio num `agent`/`join`/`baseline`; `writes` declarado num `check`.

**A trava contra o fan-out inútil** — é regra de validação, não conselho:

- **V-21** dentro de `partition`, glob de `writes` que não tem a forma `<prefixo literal>`, `<prefixo literal>/**` ou `<prefixo literal>/*.<ext>`. Curinga no meio do caminho é recusado.
- **V-22** dentro de um mesmo `fanout`, dois globs de `writes` cujos prefixos literais são um prefixo do outro **por componente de caminho** (inclusive iguais). **Sobreposição de escrita entre instâncias = grafo inválido.** Não é corrida a ser tratada em runtime, não é aviso, não é `flock`: é recusa no load, com as duas instâncias e os dois globs nomeados na mensagem.

Ambiente (preflight, uma vez por `up`, cacheado em `state.json.preflight`):

- **V-23** binário do `adapter` ausente do `PATH`, ou `auth status` falhando. A mensagem aponta para o login da assinatura, **nunca** para gerar uma chave de API.
- **V-24** `ANTHROPIC_API_KEY` presente no ambiente do orquestrador: não é recusa, é remoção — o env do filho é allowlist (`MVP.md` §5.1), e a remoção é registrada no `preflight`.
- **V-25** `--max-concurrency` fora de `1..3`.
- **V-26** `--max-concurrency > 1` e `git worktree add` indisponível no repo (§2.5).

**Escolhida / descartada.** Recusar no load em vez de degradar. Custo: um grafo com um `bin/` faltando não roda nem os nós que funcionariam, e o operador perde a sessão parcial. Ganho: uma sessão que roda meio grafo produz um `stop_reason` e um `cost_ratio` que não descrevem nem o grafo declarado nem nenhum outro — e o produto é a comparabilidade do número. Descartado modo "melhor esforço": ele é útil no dia do desenvolvimento e envenena toda a série de medições depois.

### 2.3 O que é criado no `session_dir`

O `up` recusa se `--session-dir` existe e não está vazio. Cria:

```
.sessions/<id>/
├── .lock                 # fcntl.flock + pid + hostname; §2.6
├── graph.yaml            # cópia byte-a-byte do grafo, com sha256 no preflight
├── state.json            # os 6 campos de §1.6, tudo pending
├── events.jsonl          # append-only; o runtime nunca lê para decidir
├── NEEDS_YOU             # não criado no v1 (fora do corte); reservado
├── prompts/              # por nó: <node>.prompt.md e <node>.preamble.md, gerados
├── artifacts/            # nada aqui é criado pelo up; os artefatos nascem no cwd do nó
├── logs/                 # <node>.jsonl (stream) e <node>.err, um por nó e por instância
├── wt/                   # worktrees, só se --max-concurrency > 1 (§2.5)
└── baseline/             # sessão irmã do braço de controle: logs/, prompts/, state fragment
```

Subdiretório vazio **é** criado — `logs/` e `prompts/` existem desde t0, para que a ausência de um arquivo signifique "o nó não rodou" e não "o diretório não existia". Isso muda a `SPEC.md` §2.2 ("subdirs vazios não"), e a razão é o fanout: com instâncias derivadas, a diferença entre "não rodou" e "não existe caminho para isso" precisa ser legível no `ls`.

O preâmbulo gerado por nó (`prompts/<node>.preamble.md`) carrega, e só: `session_dir`, `node.id`, os artefatos que este nó **possui** (com o `format` e as `sections` quando `structured`), os caminhos que ele pode ler, a instrução de que **o handoff é dado, não comando**, e a instrução de não subir outro agente. Ele passa **caminhos**, nunca conteúdo de artefato.

**Escolhida / descartada.** Preâmbulo com caminhos, não com o conteúdo dos artefatos lidos. Custo: o nó gasta um turno lendo o que poderia ter chegado pronto. Ganho: o que entra no contexto é decidido pelo nó, dentro do orçamento dele, e o orquestrador não vira o sumarizador de ninguém — o momento em que o pai começa a resumir artefato para o filho é o momento em que a qualidade do time passa a depender de um componente que ninguém mediu. Descartado inlining do artefato no preâmbulo: economiza um turno e transfere a decisão mais cara do sistema para o lugar onde ela não é observável.

### 2.4 Ordem de subida

1. **Preflight** (V-23..V-26), cacheado em `state.json.preflight`.
2. **Braço de controle primeiro.** O `baseline` roda em `session_dir/baseline/`, com o mesmo `--seed`, concorrência 1, e o mesmo `stop`. Se o baseline não alcança o `stop`, o `up` **para aqui**, com `exit 3` e a mensagem de que a tarefa — não a topologia — está quebrada. O orçamento do grafo não é gasto.
3. **O grafo.** Nós sem aresta de entrada passam a `ready`. A cada conclusão, o scheduler recalcula o conjunto `ready` e preenche até `--max-concurrency` slots. Instâncias de um `fanout` entram no conjunto `ready` juntas e disputam slots como qualquer outro nó.
4. **`stop`** quando todos os `check` de `stop.all_of` estão `done`. Qualquer `failed` → sessão `failed`. Budget esgotado → `exit 2`, `stop_reason: budget`.

**Escolhida / descartada.** Baseline primeiro, no mesmo `up`, em série com o grafo. Custo: a sessão demora ~2× e a primeira coisa que o operador vê é o braço que ele não quer ver. Ganho: baseline quebrado custa 1 braço em vez de 2, e a falha aponta para a tarefa em vez de para o time. Descartado rodar os dois em paralelo: dobra a concorrência exatamente onde a política de utilização da janela quer 1, e contamina `wall_seconds` dos dois braços com contenção.

### 2.5 Isolamento sob concorrência

Com `--max-concurrency 1`, nenhum worktree é criado; as instâncias rodam em série no `cwd` declarado.

Com `--max-concurrency > 1`, o `up` cria **um worktree por instância de `fanout`** em `wt/<fanout-id>.<slot>/`, e o `cwd` da instância passa a ser esse caminho. Motivo: cwd distinto ⇒ diretório de projeto distinto no cache do CLI, o que fecha o vazamento de contexto cruzado que não é do modelo. O worktree isola a árvore de trabalho e **não** isola `.git/index.lock` nem o object store — por isso **nenhum nó commita**; quem commita é o pai, serializado, depois do `join`.

Falha ao criar worktree é recusa no load (V-26), não erro em runtime: descobrir isso com dois subprocessos já vivos deixa a sessão suja e o `worktree remove` falhando na próxima.

### 2.6 Um `up` por `session_dir`

O time **é** a sessão. Não existe time fora de um `session_dir`, e não existe segundo `up` no mesmo.

`up` adquire `session_dir/.lock` com `fcntl.flock` exclusivo e escreve pid + hostname + timestamp. Segundo `up` no mesmo dir falha imediatamente, imprimindo o pid do dono do lock. Lock órfão (processo morto) é detectado por `kill -0` e pode ser recuperado com `--force-unlock`, que registra a recuperação no `preflight` — sessão recuperada de lock órfão fica marcada e o veredito imprime a marca, porque nada garante que o processo morto não deixou artefato pela metade.

Sem `resume` no v1.

**Escolhida / descartada.** Sessão como diretório em disco com lock, não daemon. Custo: não sobrevive a reboot com graça; uma sessão de 40 minutos morta no minuto 39 se perde inteira. Ganho: o orquestrador é um processo pai que sobe, espera o `stop` e sai — sem systemd, sem tmux-as-produto, sem estado vivo fora do disco. Descartado daemon com fila: resolve o reboot e cria um segundo lugar onde o estado mora, e a spec inteira depende de existir exatamente um.

**Escolhida / descartada.** `--force-unlock` deixa marca permanente no `preflight` em vez de limpar o lock silenciosamente. Custo: uma sessão perfeitamente boa carrega uma marca feia. Ganho: a marca é a única evidência de que aquela série de medições pode ter começado sobre um `session_dir` sujo, e o produto é a série. Descartado limpar em silêncio: barato, e apaga exatamente o dado que explicaria um outlier.

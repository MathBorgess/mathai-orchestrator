# MVP — protótipo do banco de provas de topologia de time

**Data:** 2026-08-30 · **Issue:** [MAT-96](https://linear.app/borgesmathai/issue/MAT-96) · **Deriva de:** [`SPEC.md`](SPEC.md) (v0, já commitada)
**Base:** [mesa-redonda](research/2026-08-30-mesa-redonda.md) · [teardown do Maestri](research/2026-08-30-maestri-teardown.md) · [memoriais](research/teammates/)
**Status:** spec. **Nenhuma linha de runtime foi escrita nesta sessão, por decisão.**

Esta spec não substitui a `SPEC.md` — ela a estende. Onde as duas divergirem, a divergência está marcada com **emenda**. Toda escolha traz o descarte; decisão sem alternativa não entra.

---

## 0. O que é, e o que não é

**É:** um instrumento que sobe um time de agentes declarado num arquivo versionado, roda a mesma tarefa também com um agente solo, e imprime um veredito comparando os dois.

**Não é:** um painel para assistir agentes trabalhando. Se o produto parar em "sobe o time", ele é o 215º orquestrador com YAML.

**Posicionamento (uma frase):** você declara o time num arquivo versionado, roda a mesma tarefa com dois times diferentes, e recebe um número dizendo qual funcionou — inclusive o número que diz que um agente solo era melhor.

**Para quem não é:** quem quer ver oito agentes numa tela bonita (Maestri, Conductor); quem quer entregar mais features hoje (instrumento desacelera antes de acelerar); quem roda em CI de empresa com SSO (OpenHands, Devin); quem não consegue rodar a mesma tarefa duas vezes — sem repetição não existe medida.

**Escolhida / descartada.** Categoria "banco de provas" (o concorrente mental é `pytest`/`hyperfine`/`git bisect`). Descartada "orquestrador de agentes": 214 concorrentes ativos, três já mortos em 2026, e nenhum eixo livre. Custo: público menor e mais exigente. Ganho: a única coluna vazia da tabela competitiva.

---

## 1. Modelo do grafo — o que muda contra o v0

O v0 mantém-se inteiro naquilo que decidiu certo: YAML como fonte única lida pelo runtime, sessão = diretório em disco, subprocesso com log por nó, sem tmux no runtime, `handoff.md` como handoff visível.

### 1.1 Tipos de nó (v0 tinha 1)

| Tipo | O que é | Por quê |
|---|---|---|
| `agent` | subprocesso de CLI (`bin`, `prompt`, `cwd`, `reads`, `writes`, `iters`, `tools`) | a única coisa cara |
| `check` | comando determinístico, **zero LLM**; o exit code *é* a verdade | é o único tipo que pode aparecer no `stop` |
| `fanout` | template de `agent` × partição declarada, `max: 3` | paralelismo com teto de schema |
| `join` | `agent` que lê as saídas do fanout; único ponto de convergência | sem malha entre ramos |

**Escolhida / descartada — emenda à `SPEC.md` §5.** `DONE.md` **sai do critério de parada**. A sessão termina quando os nós `check` declarados no `stop` saem 0. Custo: exige que o usuário escreva um comando de verificação real; sem isso a sessão cai no failsafe de budget toda vez. Ganho: um bound de verdade. Descartada a alternativa: aceitar `DONE.md` — a varredura de 6.549 repos mostra que **100% dos 68 loops infinitos confirmados têm a mesma causa raiz, ausência de bound forte**, e "model-controlled termination" aparece em 38,2% classificada como *não-bound* (arXiv:2607.01641).

### 1.2 Tipos de aresta (v0 tinha 1)

`artifact_exists` · `artifact_valid` (roda o validador declarado — impede "escreveu arquivo vazio para desbloquear") · `check_passed` / `check_failed` (a segunda é a aresta de recuperação, a única que fecha ciclo, e carrega `max_repeats`) · `always` (só dentro de `fanout`).

Toda aresta declara também o **formato**: `handoff: structured | prose`. `structured` exige as seções declaradas e injeta o preâmbulo de leitura no destino. Isso não é enfeite: handoff tipado dá +12,7 pp em τ-retail e +8,7 pp em BrowseComp, mas **regride −14,6 pp em AppWorld**, onde a tarefa exige iteração adaptativa (2608.25277). O formato é decisão por aresta, e o schema sozinho não faz nada sem o preâmbulo no receptor.

### 1.3 Contrato de escrita

Cada nó declara `reads:` e `writes:` como globs. O orquestrador compara a árvore antes/depois; escreveu fora do contrato → nó `failed`, com o path no erro.

**Escolhida / descartada.** Globs verificados por diff de árvore. Descartado JSON Patch com kernel de validação (PatchBoard): dá 0% de contaminação por escrita não autorizada, mas exige que o estado do trabalho seja um documento JSON — não é o nosso caso, o nosso estado é um repositório. Custo: verificação a posteriori, não prevenção. Ganho: cabe em 20 linhas e funciona com qualquer CLI. Referência do ganho esperado: remover o write contract custou −8 pp e +11% de tokens/sucesso na medição original (2605.29313).

### 1.4 Estado da sessão

`state.json` deixa de ser só status e vira o ledger — single-writer, escrito **só** pelo orquestrador, **nunca** lido por um nó:

1. **nós** — `pending | ready | running | verifying | done | failed | skipped`
2. **artefatos** — `{path, sha256, writer_node, mtime, valid}`
3. **budget** — `iters_used` por nó, `cost_units`, `wall_seconds`, `log_bytes`
4. **violações** — escrita fora de contrato, com path
5. **mutações** — no máximo uma, com operação e motivo
6. **preflight** — `claude --version`, resultado de `auth status`, cacheado uma vez por `up`

**Escolhida / descartada — emenda à `SPEC.md` §1.** Entra um `events.jsonl` append-only (uma linha por transição). **O runtime nunca lê esse arquivo para decidir** — se ler, viram duas verdades. Custo: um arquivo a mais. Ganho: debug, replay futuro, e a base do feed (§4). Descartado o event-log como fonte de verdade: continua sendo evolução nomeada, não v0.

### 1.5 Baseline — campo obrigatório

```yaml
baseline:
  bin: claude
  prompt: prompts/baseline.md      # o procedimento inteiro, 1 nó
  compare_on: [stop_reached, wall_seconds, log_bytes, gate_first_pass]
```

**Escolhida / descartada.** Baseline dentro do grafo, rodado pelo `up`. Descartado: baseline como etapa de roadmap. Custo: toda sessão custa ~2×. Ganho: é a única coisa que separa este produto de um painel — e a literatura diz que o resultado default é o solo ganhar (15/15 comparações em tarefa procedural, arXiv:2604.27891). Se o baseline não estiver no caminho crítico, ele não é rodado.

---

## 2. Como um time é instanciado

```
orch up graphs/<id>.yaml --session-dir .sessions/<session_id> [--max-concurrency 1]
```

O `up` **recusa** antes de subir qualquer nó: `id` do grafo ≠ stem do arquivo; nó órfão; aresta para nó inexistente; ciclo sem `max_repeats`; `stop` inalcançável; dois nós reivindicando o mesmo artefato; `writes` sobrepostas entre instâncias de fanout; id fora de `^[a-z][a-z0-9_-]{0,31}$`; `stop` que referencia algo que não é `check`.

Recusar no load, não avisar em runtime. Grafo inválido é erro de compilação.

**Escolhida / descartada.** Um comando novo além do `up`: `orch doctor` — roda um `claude -p --output-format json "reply OK"` de 5 s e **afirma que os campos que o parser lê existem** (`is_error`, `subtype`, `permission_denials`, `num_turns`, `total_cost_usd`), falhando com o nome do campo ausente. Custo: um comando a mais. Ganho: é a resposta operacional à cláusula da `SPEC.md` §6 ("se o CLI mudar de flag, emenda datada antes de adaptar o código") — sem `doctor`, a descoberta da mudança acontece no meio de uma sessão, com o log errado.

---

## 3. Ciclo de vida do nó

```
pending ──(arestas de entrada satisfeitas)──► ready
ready ──(slot livre)──► running          [spawn em novo process group]
running ──(processo saiu | timeout do pai)──► verifying
verifying ─┬─ rc=0 ∧ ¬is_error ∧ denials=[] ∧ verify(artefato) ──► done
           ├─ denials ≠ []                  ──► failed:permission  (NÃO retentar igual)
           ├─ subtype=error_max_budget_usd  ──► failed:budget      (nunca retenta)
           ├─ rc≠0 ∧ api_error_status≠null  ──► retry:transport    (backoff, até 2)
           ├─ rc=0 ∧ denials=[] ∧ ¬verify   ──► retry:semantic     (1×, com --resume + nudge)
           └─ morto por timeout do pai      ──► failed:timeout
```

**O predicado de conclusão, literal:**

```
done(node) := rc == 0
          AND result.is_error == false
          AND result.permission_denials == []
          AND verify(edge.artifact)          # existe, não-vazio, mtime > node.started_at
```

**Escolhida / descartada.** Conjunção de quatro. Descartado exit code sozinho — verificado em execução: `claude -p` em permission-mode default, pedindo um Write, retorna **`exit 0`, `is_error: false`, `subtype: "success"` e o arquivo não existe**, com `permission_denials[]` populado. Um orquestrador que confia no exit code reporta sucesso sobre trabalho não feito.

**Escolhida / descartada.** Quatro classes de falha, quatro tratamentos. Descartado tratar todas igual — é o erro que faz orquestrador entrar em loop caro. `permission` é bug de config: falha alto, imprimindo o `tool_name` negado e a flag que resolveria.

O `verify` é declarativo, e "o arquivo existe" continua sendo heurística:

```yaml
edges:
  - from: scout
    to: builder
    on: artifact_valid
    artifact: handoff.md
    verify:
      non_empty: true
      min_lines: 5
      # cmd: "bin/has-sections handoff.md OBJETIVO ARQUIVOS ACEITE FORA_DE_ESCOPO"
```

**Descartada:** um segundo `claude -p` julgando o artefato. Custa um turno, reintroduz não-determinismo, e transforma o critério de parada em opinião. E medido: a variante de parada com juiz a cada rodada custou **+129% de tokens** sem ganho (2606.27009).

---

## 4. A superfície — feed, não canvas

Seis comandos. Nenhuma TUI full-screen.

```
orch up      sobe a sessão                                    (SPEC v0)
orch watch   o canal ao vivo — uma linha por evento, stdout puro
orch ps      o roster — quem é quem, em que estado, de quem é a bola
orch next    a próxima coisa que precisa de você              (o Ctrl⇧A honesto)
orch show    abre um evento, uma thread ou o log de um nó     (o Check do Batuta)
orch say     manda uma mensagem para um nó                    (o Ask do Batuta)
```

```
session  .sessions/2026-08-30-tg-intent      graph v0      up 00:14:32
─────────────────────────────────────────────────────────────────────────────
14:02:11  >  scout    start    prompts/scout.md · cwd=.
14:06:03  >> scout    handoff  builder  handoff.md  41L  +41-0
14:06:03  >  builder  start    on=valid(handoff.md)
14:09:50  ?  builder  ASK #4   sobrescrever graphs/v0.yaml versionado?   VOCE
14:16:02  ~  builder  stall    sem evento ha 6m12s (blocked)
─────────────────────────────────────────────────────────────────────────────
1 ASK esperando voce  ·  orch next
```

**As cinco regras de interação, inegociáveis:**

1. **Toda mensagem tem `from`, `to`, `artifact` e `summary`.** Sem destinatário nomeado não é mensagem, é log — e vai para `logs/<node>.log`, que ninguém lê por padrão.
2. **Um evento, uma linha, ≤100 colunas**, `summary` ≤72 escrito pelo agente. Profundidade é opt-in (`orch show`). Traceback vira `! builder fail exit=1 (orch show 0009)`.
3. **Silêncio é evento.** Nó sem evento por 5 min emite `stall` com o tempo acumulado. Sem heartbeat, "trabalhando" e "morto" são visualmente idênticos.
4. **Interromper o humano é caro e o sistema cobra.** Só `kind: ask` com `blocking: true` alcança o dono; **ASK sem `options` enumeradas e sem `recommend` é rejeitado na escrita** e volta para o agente. Nunca há push — o humano puxa com `orch next`.
5. **A tela é projeção do disco.** Nada aparece no feed que não exista como arquivo com o mesmo texto. `orch watch --from 0` reconstrói exatamente a mesma tela.

**Layout da sessão:**

```
.sessions/<id>/
├── graph.yaml            state.json         events.jsonl
├── NEEDS_YOU             # existe ⟺ há ASK aberto — o "attention dot" honesto
├── msgs/NNNN-<from>-<to>-<kind>.md          # markdown com frontmatter: a mensagem
├── bus.jsonl                                 # índice espelhado: a máquina
├── artifacts/  logs/  prompts/  wt/
```

**Escolhida / descartada.** Markdown com frontmatter como mensagem, JSONL como índice. Se divergirem, o arquivo ganha (`orch reindex`). Custo: escrever duas vezes. Ganho: `cat msgs/0004-*.md` num SSH às 3h faz sentido sem viewer, e é o mesmo formato do vault do dono. Descartado JSONL puro como fonte: força um viewer, e viewer é dependência que quebra.

**Escolhida / descartada.** `NEEDS_YOU` como arquivo + `orch ps` saindo com **exit code = número de ASKs abertos**. Custo: nenhum. Ganho: componível — `[ -f .../NEEDS_YOU ] && PS1=…`, `orch ps >/dev/null || notify-send`, `tmux status-right '#(orch ps --brief)'`. Descartado notification center embutido: transporte embutido carrega dependência para sempre e ganha zero.

**Descartado explicitamente do MVP:** TUI full-screen (toma o TTY e mata `tee`/`grep`/`ssh`, que são as ferramentas de auditoria que o produto promete); canvas e posições (o grafo já está no YAML; `orch graph --dot | dot -Tpng` resolve em 10 linhas); chat livre agente↔agente; roteamento por descrição (não-determinismo no ponto mais caro de debugar); sumarizador LLM (o `orch since` é `GROUP BY`, determinístico e melhor que o Ombro); streaming token-a-token e typing indicator (`-p` não tem TTY — fingir seria mentira de interface); presença, avatar, antropomorfismo; multiplayer; rotação de log.

---

## 5. Adaptadores de CLI

Três métodos e um dataclass. **O `Outcome` é definido antes dos adapters** e é o único acoplamento entre eles — é o que permite escrever `claude.py` e `cursor.py` em paralelo.

```
preflight()                         -> Ok | Reason      # uma vez por up, cacheado
build(node, session, retry_ctx)     -> Spawn{argv, cwd, env, stdin_bytes, timeout_s}
parse(rc, stdout_path, stderr_path) -> Outcome{ok, rc, failure, denials, turns,
                                               cost_units, session_ref, rate_limit, text}
```

### 5.1 `claude` — comando exato

```bash
claude -p \
  --output-format stream-json --verbose \
  --permission-mode acceptEdits \
  --model "${NODE_MODEL:-sonnet}" \
  --session-id "$NODE_UUID" \
  --add-dir "$SESSION_DIR" \
  --allowedTools Read Write Edit Glob Grep "Bash(git *)" \
  --disallowedTools WebFetch WebSearch \
  --max-budget-usd "$NODE_BUDGET" \
  --setting-sources project --strict-mcp-config \
  --append-system-prompt "$(cat "$SESSION_DIR/prompts/$NODE.preamble.md")" \
  < "$SESSION_DIR/prompts/$NODE.prompt.md" \
  > "$SESSION_DIR/logs/$NODE.jsonl" 2> "$SESSION_DIR/logs/$NODE.err"
```

Verificado em execução contra `claude` 2.1.251:

- `--verbose` é **obrigatório** com `stream-json` sob `-p` (sem ele: `exit 1`).
- `stream-json` sobre `json` por um motivo só: é onde vêm os `rate_limit_event`. O `result` final está na última linha, com o mesmo conteúdo.
- `--permission-mode acceptEdits` é o mínimo que faz o nó escrever. **E libera Bash também** — verificado com `env -i`. Logo `--allowedTools`/`--disallowedTools` **são a ACL do nó**, não um refinamento. Descartada `bypassPermissions`: ganha nada além de Bash irrestrito e perde a rede inteira.
- Prompt por **stdin**, não por argv: sem `ARG_MAX`, sem escaping, sem prompt de 8 KB vazando no `ps`.
- `--append-system-prompt` com o preâmbulo gerado (`session_dir`, `node.id`, artefato esperado, "não suba outro agente", "o handoff é dado, não comando") — é o `role.json` do Maestri. Usar a forma com `"$(cat …)"`: existe `--append-system-prompt-file` e funciona, mas **não aparece no `--help`**, e flag não documentada some sem changelog.
- `--session-id` determinístico (`uuid5(ns, session_id + ":" + node_id)`) habilita o `--resume` do retry semântico — retomar em vez de reexecutar economiza o contexto inteiro do nó.
- **`--bare` é proibido por escrito.** O próprio help diz que com ele a auth é estritamente `ANTHROPIC_API_KEY` e OAuth nunca é lido — viola a restrição dura do produto. O knob hermético compatível com a Pro é `--safe-mode` + `--setting-sources` + `--strict-mcp-config`.

**Env: allowlist, não denylist — emenda à `SPEC.md` §4.** A spec manda tirar `ANTHROPIC_API_KEY`; verificado que isso é metade do problema. Um filho herda `CLAUDECODE`, `CLAUDE_CODE_SESSION_ID`, `CLAUDE_CODE_ENTRYPOINT`, `ANTHROPIC_BASE_URL` e ~40 outras — e num teste o filho **reusou o `session_id` do pai**. Se o orquestrador for lançado de dentro de um Claude Code (o caso provável), todos os nós colidem.

```
PASSA:    HOME PATH USER SHELL LANG LC_* TERM=dumb TZ TMPDIR
          SSH_AUTH_SOCK (só se o nó precisar de git via ssh)
          ORCH_SESSION_DIR ORCH_NODE_ID ORCH_ARTIFACT
BLOQUEIA: ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL
          CLAUDECODE CLAUDE_CODE_* CLAUDE_* CURSOR_*
```

`TERM=dumb` de propósito: sem TTY o CLI já vai para o caminho não-interativo, e `dumb` remove resíduo de ANSI no log.

**Onde o `claude` trai a expectativa** (todos verificados): `exit 0` com denial silencioso; `--output-format text` escreve **o erro no stdout** (quem faz `if rc==0: artefato=stdout` grava a mensagem de erro como artefato — nunca parsear `text`); autocompact silencioso (`autocompact_state` no stream → logar e marcar o nó `degraded`); `total_cost_usd` vem com `costBasis: "list"`, preço de tabela — **chamar de unidade de orçamento, nunca de dinheiro**.

### 5.2 `cursor-agent` — tudo `[D]`, nada verificado

```bash
cursor-agent -p --output-format stream-json --force --model "$NODE_MODEL" --workspace "$NODE_CWD" "$(cat prompt.md)"
```

Schema de eventos diferente do Claude (`system`, `assistant`, `tool_call{started|completed}`, `result`) — normalizar no `Outcome`. `--force` é allow-unless-denied, **mais grosso** que `acceptEdits`, e sem equivalente documentado a `permission_denials` → para o Cursor **o predicado de artefato não é redundância, é a única defesa**. Exit code sem contrato documentado, e há bug conhecido de `-p` pendurando indefinidamente (fórum oficial, 2.4.21–22) → timeout generoso no pai (≥60 s antes de considerar hang) e mensagem de erro que cite o bug por nome, senão o operador culpa o orquestrador. `Outcome` sai com `turns=null, cost=null`: registrar no `state.json`, não fingir paridade.

**Pré-condição:** instalar o binário e repetir os 20 testes antes de escrever este adapter.

### 5.3 `exec` — o adapter genérico

```yaml
- id: reviewer
  adapter: exec
  cmd: ["codex", "exec", "--cd", "{cwd}", "-"]
  stdin: "{prompt_file}"
  parse: exit_code_only
  timeout: 900
```

`Outcome` degradado: `ok = (rc == 0) && verify(artifact)`, resto `null`.

**Escolhida / descartada.** Três adapters, um `Outcome`. Descartado um adapter com `if binary == "claude"`. Custo do `exec`: ~30 linhas e perda de telemetria. Ganho: **é a apólice de seguro do projeto** — torna o orquestrador agent-agnostic no sentido do Maestri sem PTY, e se a assinatura fechar a porta para automação, o projeto aponta para `codex`, `opencode`, `aider` ou um `.sh` no mesmo dia.

---

## 6. Orçamento, limite e paralelismo

Três eixos de orçamento, todos observáveis:

| Eixo | Como |
|---|---|
| custo por nó | `--max-budget-usd` — corta de verdade (`subtype: error_max_budget_usd`) |
| custo por sessão | acumula `result.total_cost_usd`; se `total + próximo_teto > session_cap`, **não sobe o próximo nó** |
| relógio | timeout **no processo pai** (`subprocess(timeout=)`), nunca `timeout(1)` — não existe no macOS de fábrica |

**A política de assinatura.** O stream emite `rate_limit_event` com `unifiedWindows.five_hour.utilization`, `seven_day.utilization` e `resetsAt` em epoch. Isso transforma "vai que estoura" em política executável:

```
utilization > 0.85  → degrada concorrência para 1
utilization > 0.95  → dorme até resetsAt (pausa, não falha)
status != "allowed" → para a sessão com motivo explícito
nunca               → retry cego em 429
```

**Paralelismo.** Verificado que funciona: 3× `claude -p` concorrentes em cwds distintos, 3 artefatos corretos, 10 s; `git worktree` ×2; `wait -n`. O desenho: scheduler de **conjunto pronto** (a cada conclusão, recalcula quem ficou `ready` e preenche slots), `ThreadPoolExecutor` sobre `subprocess.run(timeout=)` — I/O-bound, GIL irrelevante. Descartado `xargs -P` / GNU parallel: não sabem o grafo, não recalculam o conjunto pronto, não acumulam orçamento.

**Teto 3 no schema, default 1 na execução.** Não se contradizem: um limita o que pode ser declarado (1→3 ganha, 3→5 é marginal ou negativo; paralelismo estrutural agressivo derruba acurácia de 28% para 25% — 2608.05791), o outro limita o que sobe sem o dono pedir (mitigação de ToS onde ela custa zero).

**O que quebra, e o remédio:**

1. Worktree isola o working tree, **não** `.git/index.lock` nem o object store → **nós não commitam**; o pai commita, serializado.
2. Zombies no timeout: `claude` gera filhos (a tool Bash). `kill()` mata o pai e deixa órfão segurando o worktree. `start_new_session=True` no spawn + `killpg` → grace 5 s → `SIGKILL`. **Não negociável** — sem isso o `worktree remove` falha e a sessão seguinte não sobe.
3. Contexto cruzado vaza **fora** do modelo: `~/.claude/projects/<hash-do-cwd>` compartilhado quando dois nós rodam no mesmo cwd, e `CLAUDE.md`/hooks/plugins da máquina entrando em todo nó. Remédio: worktree (cwd distinto ⇒ diretório de projeto distinto) + `--setting-sources` + `--strict-mcp-config`.
4. Um log por nó, sempre. `events.jsonl` é a única visão cronológica e só o pai escreve.
5. `fcntl.flock` por artefato — não `flock(1)`.

---

## 7. Auto-gestão — o time que se conserta

Auto-gestão **não é recrutamento**. É reparo estrutural limitado.

```yaml
repair:
  budget: 1
  triggers: [check_failed_twice, write_contract_violation, no_progress, branch_budget_hog]
  ops:      [insert_check, serialize, rewire, split]
  validate: [max_nodes, disjoint_writes, every_cycle_bounded, stop_reachable]
```

- **Gatilho:** só sinal de processo observável pelo orquestrador. Nunca o gabarito, nunca a opinião de um agente sobre si mesmo.
- **Catálogo fechado de 4 operações.** Três não aumentam o sistema (`insert_check`, `serialize`, `rewire`); só `split` aumenta, e exige budget sobrando. Dos 5 reparos observados na literatura, só um aumentava o sistema.
- **1 mutação por sessão** — a primeira captura a maior parte do ganho, e o planejamento inicial da topologia vale mais que a mutação (71,7→57,5 sem planejamento contra →60,8 sem mutação).
- **Aplicada por código a uma cópia, validada, e só então comitada.** Proposta inválida é descartada, não "reparada".

Loop infinito é impossível por construção: mutação ≤1, ciclo ≤`max_repeats`, sessão ≤`wall_seconds`, failsafe incondicional.

**E a regra que fecha a porta do instinto errado:** não rotule um nó de "lead" esperando que isso crie estrutura. Medido em 1.902 runs, nomear um coordenador por prompt produziu **0 de 1.170 arestas de hub** e nenhum ganho de sucesso. Hierarquia mora no grafo — quem lê o quê, quem escreve o quê.

---

## 8. O veredito — o que o `up` imprime no fim

É a razão de o produto existir. Tudo derivável de `state.json` + `logs/*` + hashes, **sem API e sem juiz LLM**.

```
veredito  graphs/v1.yaml  vs  baseline(1 nó)      tarefa: mat-96-spec        3 seeds
──────────────────────────────────────────────────────────────────────────────────
stop_reached          grafo 3/3      baseline 3/3
gate_first_pass       grafo 0.67     baseline 0.33
rework (mediana)      grafo 0.18     baseline 0.41      −23 pp
cost_ratio            2.1×           (teto 2.5×)                        ok
handoff_uptake        0.72           [proxy não calibrado]
write_violations      0
stop_reason           gate 3 · no_progress 0 · budget 0 · failed 0
──────────────────────────────────────────────────────────────────────────────────
o grafo bateu o baseline em 2 de 3 métricas, dentro do teto de custo.
```

| Família | Métricas |
|---|---|
| **custo** | `wall_seconds`, `log_bytes` (proxy de token de saída), `prompt_bytes`, `cost_ratio = log_bytes(grafo)/log_bytes(baseline)` |
| **progresso** | `rework_count` (escritas com hash **diferente**), `null_writes` (escritas com hash **idêntico** — step repetition, 15,7% das falhas do MAST), `no_progress_rounds`, `iters_used/iters` |
| **handoff** | `handoff_valid` (passou no validador de primeira?), `handoff_uptake` (proxy por 6-grama — **invenção nossa, não calibrada**), `handoff_bytes/total_log_bytes` |
| **verificação** | `gate_first_pass`, `gate_attempts`, `write_violations`, `orphan_writes`, `stop_reason` |
| **decisão** | `collab_tax = stop_reached(baseline) − stop_reached(grafo)`, `repair_efficacy` |

**Regra de leitura, escrita na saída do comando:** mínimo **5 seeds por célula** antes de qualquer decisão de desenho. A mesma célula colhida duas vezes, com modelo pinado, deu expoente 1,76 e 2,44 — um run é amostra de tamanho 1.

---

## 9. O corte do MVP

| Peça | Dentro | Fora (nomeado, não agora) |
|---|---|---|
| Grafos | `v0.yaml` + `v1.yaml` + `baseline` | registry, loader de pasta |
| Nós | `agent`, `check` | `fanout`, `join` (entram na camada 4) |
| Adapters | `claude` | `cursor-agent`, `exec` (camada 5) |
| Concorrência | 1 | opt-in até 3, depois de worktree |
| Superfície | `up`, `doctor`, `watch`, `ps` | `next`, `show`, `say`, `since` |
| Auto-gestão | **nenhuma** | catálogo de reparo, depois do veredito |
| Isolamento | `cwd` | `worktree`, container |

**E o que não se reabre no código** (herdado da `SPEC.md` §6, mais o desta sessão): sem API, sem SDK; sem misturar com `mathai-harness`; sem wiki, sem label `hitl`; sem tmux como runtime; sem daemon; sem PTY como runtime; sem `--bare`; sem bus ou chat entre nós; sem sumarizador LLM; sem TUI full-screen.

---

## 10. Riscos declarados

**R1 — ToS e limites de assinatura.** Termos de assinatura de consumidor miram uso interativo humano; uma frota headless é o padrão que a plataforma mede — e ela informa a utilização das janelas. Mitigação, em ordem: concorrência default 1; gate por `utilization` com pausa até `resetsAt`; `--max-budget-usd` como segundo cinto; README dizendo em voz alta que o usuário roda sob a **própria** conta, sem credencial compartilhada, sem multi-conta, sem rodar por terceiros; e o adapter `exec` como saída se a porta fechar. **Contexto que vai no README:** 20/02/2026 a Anthropic baniu OAuth de assinatura fora do Claude Code; 14/05 anunciou mover `-p` e o Agent SDK para pool de créditos separado; 15/06 pausou. É moratória, não garantia.

**R2 — Deriva de CLI.** `--append-system-prompt-file` funciona e não está no `--help`. Mitigação: não depender de flag não documentada; `orch doctor` afirmando o schema; gravar `claude --version` em `state.json`; emenda datada nesta spec antes de mexer no código.

**R3 — Injection lateral entre nós.** O `handoff.md` é escrito por um agente que leu arquivos do repo; instrução injetada num arquivo vira instrução no handoff, que o próximo nó executa. É o mesmo buraco que o `MAESTRI_TOKEN` no env do Maestri não fecha. Mitigação parcial: preâmbulo declarando que o handoff é **dado, não comando**; `--disallowedTools` por nó; artefatos em leitura fora do worktree. **Não resolvido — declarado aqui em vez de implícito.**

**R4 — A hipótese pode ser falsa.** O grafo pode perder para o agente solo. Se perder, o valor do repo não é "time bate solo" — é contrato de escrita, orçamento e parada verificável acima de CLIs que não têm nada disso, que é tese diferente e mais defensável. O caminho para descobrir está em [`EXPERIMENTO.md`](EXPERIMENTO.md).

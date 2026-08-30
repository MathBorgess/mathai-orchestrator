# T3 — Ailla (engenharia): Maestri × Grok Bot × Hermes, e o desenho do `mathai-orchestrator`

**Data:** 2026-08-30 · **Ambiente de verificação:** Linux 6.18, bash 5.2.21, `claude` **2.1.251**, git 2.x, `flock`/`timeout`/`jq` presentes.
**Método:** tudo marcado `[V]` foi **executado nesta máquina** e o output conferido. `[D]` = lido em doc oficial, não executado. `[I]` = inferência minha a partir de evidência indireta. Não há flag inventada neste documento.

---

## 0. Registro de verificação (o que eu realmente rodei)

Isso é o alicerce das seções 2–4. Se algo aqui estiver errado, o desenho cai junto.

| # | Comando | Resultado observado | Marca |
|---|---|---|---|
| A | `claude -p --output-format text --model sonnet "..."` | stdout limpo, `exit 0` | `[V]` |
| B | `echo "..." \| claude -p --model sonnet` | **prompt por stdin funciona**, `exit 0` | `[V]` |
| C | `claude -p --output-format json ...` | JSON único com `is_error`, `subtype`, `terminal_reason`, `num_turns`, `total_cost_usd`, `usage{input_tokens,output_tokens,cache_read_input_tokens,...}`, `permission_denials[]`, `session_id`, `result`, `modelUsage{}`, `duration_ms` | `[V]` |
| D | `claude -p --model does-not-exist-xyz` | `exit 1`, **mensagem de erro humana foi para o STDOUT**, aviso técnico no stderr | `[V]` |
| E | `claude -p --append-system-prompt "...ZZTOP"` | injetou de fato no system prompt | `[V]` |
| F | **`claude -p` em permission-mode default, pedindo Write** | **`exit 0`, `is_error:false`, `subtype:"success"` — e o arquivo NÃO foi criado.** `permission_denials:[{tool_name:"Write",...}]`, `result:"I need permission to write the file"` | `[V]` |
| G | mesmo teste com `--permission-mode acceptEdits` | arquivo criado, `permission_denials: []` | `[V]` |
| H | `--output-format stream-json` **sem** `--verbose` | `exit 1`, `Error: When using --print, --output-format=stream-json requires --verbose` | `[V]` |
| I | `--output-format stream-json --verbose` | JSONL, 17 linhas. Tipos: `active_goal`, `autocompact_state`, `system{subtype:init\|status\|commands_changed\|post_turn_summary}`, `stream_event`, `assistant`, **`rate_limit_event`**, `result{subtype:success}` | `[V]` |
| J | conteúdo do `rate_limit_event` | `rate_limit_info{status, resetsAt, rateLimitType:"five_hour", overageStatus, isUsingOverage, unifiedWindows:{five_hour:{utilization:0.39,resetsAt}, seven_day:{utilization:0.48,resetsAt}}}` | `[V]` |
| K | `system/init` | traz `cwd`, `model`, `permissionMode`, `tools[]`, `slash_commands[]` — handshake completo | `[V]` |
| L | `--session-id <uuid>` depois `--resume <uuid>` com `-p` | **retomada real**: o filho lembrou a resposta do turno anterior, `session_id` preservado, `exit 0` | `[V]` |
| M | 3× `claude -p` concorrentes em cwds diferentes (`&` + `wait`) | 3× `exit 0`, 3 arquivos corretos, **10 s no total** | `[V]` |
| N | `--max-budget-usd 0.001` numa tarefa cara | `exit 1`, `is_error:true`, **`subtype:"error_max_budget_usd"`, `terminal_reason:"budget_exhausted"`**, `num_turns:2` | `[V]` |
| O | `--append-system-prompt-file` e `--system-prompt-file` | **aceitos e funcionam**, apesar de **não aparecerem** na lista de options do `--help` | `[V]` |
| P | `--safe-mode` junto de `-p` | `exit 0`, auth OAuth intacta | `[V]` |
| Q | flag inexistente | `exit 1`, `error: unknown option '--x'` no stderr | `[V]` |
| R | env do processo pai | um `claude` filho **herda `CLAUDE_CODE_SESSION_ID`, `CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT`, `ANTHROPIC_BASE_URL` e ~40 outros `CLAUDE_*`** — no teste I o filho reusou o `session_id` do pai | `[V]` |
| S | `git worktree add` ×2 no mesmo repo | dois diretórios, dois branches, `git worktree list` correto | `[V]` |
| T | `bash: sleep 1 & sleep 2 & wait -n` | `wait -n` retorna no primeiro job, `rc=0` | `[V]` |

**Do `--help` (2.1.251), lido, não executado** `[V-help]`: `--permission-mode` aceita `acceptEdits|auto|bypassPermissions|manual|dontAsk|plan`; `--allowedTools`/`--disallowedTools`/`--tools`; `--add-dir`; `--setting-sources user,project,local`; `--strict-mcp-config`; `--fallback-model` (só com `--print`); `--no-session-persistence` (só com `--print`); `--input-format text|stream-json`; `--json-schema`; `--fork-session`; `--bg`/`claude agents --json`/`claude logs <id>`/`claude stop <id>`; `-w/--worktree`; `--tmux` (exige `--worktree`).

**Achado do `--help` que muda uma decisão:** `--bare` documenta que *"Anthropic auth is strictly `ANTHROPIC_API_KEY` or apiKeyHelper... OAuth and keychain are never read"*. → **`--bare` é proibido neste produto.** É a flag que mais parece "modo hermético" e é exatamente a que quebra a restrição de zero API key. O knob hermético compatível com a Pro é `--safe-mode` + `--setting-sources` + `--strict-mcp-config` `[V]`.

---

## 1. Engenharia reversa dos três

### 1.1 Maestri — o terminal é o barramento, o canvas é o banco

**Em uma frase:** *Maestri é especial porque não construiu protocolo nenhum — instalou o contrato **dentro** de cada CLI (uma skill) e usou o PTY como transporte, o que o deixa agent-agnostic de graça e refém de heurística para sempre.*

**O que a doc entrega, e o que ela denuncia.** A doc diz três coisas que, juntas, fecham o mecanismo:

1. Ao conectar dois terminais, *"Maestri installs a Maestri Agent Skill in each one"*.
2. O ambiente de cada terminal recebe `MAESTRI_TERMINAL_ID=<uuid>`, `MAESTRI_HOST=<bridge-endpoint>`, `MAESTRI_TOKEN=<per-terminal-secret>`, e overrides **não podem** substituir `HOME`, `PATH` ou qualquer `MAESTRI_`.
3. *"leave the receiving agent unselected... Maestri monitors unfocused terminals; when the receiver finishes, Maestri detects this and sends the answer back"*.

Reconstrução `[I]`, com o grau de confiança de cada perna:

- **Ida (A → B): não é PTY, é HTTP local.** `MAESTRI_HOST` + `MAESTRI_TOKEN` só existem para um cliente falar com um servidor local. A skill instalada no CLI é (a) um markdown que ensina o agente a usar e (b) um binário/CLI `maestri` que faz `POST $MAESTRI_HOST/send` com `Authorization: $MAESTRI_TOKEN` e `{to: <terminal_id>, prompt: ...}`. O app recebe e **escreve no PTY de B** (o "one agent typing into another's terminal" da leitura do dossiê). Confiança alta — nada mais explica um token por terminal.
- **Volta (B → A): é scraping do PTY, não é a skill.** Se B respondesse chamando `maestri reply`, **o foco seria irrelevante**. A doc faz do foco uma regra dura. Logo a detecção de fim-de-turno é **observação do fluxo de saída do terminal**, e o foco importa porque um terminal focado tem um humano digitando nele — a máquina de estados não consegue separar "o agente terminou" de "o humano está no meio de uma frase". Confiança alta.
- **Como detectam "terminou".** Eles já renderizam o terminal (Metal), então já têm um **modelo de tela VT completo** — não um parser ad hoc. O sinal mais barato em cima disso: *a região estável da tela voltou a casar com a caixa de input do agente* **E** *não houve mutação de célula por N ms*. Ou seja: **quiet-timeout sobre o modelo de tela, não sobre bytes**. Confiança média-alta. Um sentinela (`echo __MAESTRI_EOT__`) seria mais robusto, mas quebraria o "agent-agnostic" — exigiria que cada CLI cooperasse — e a doc vende justamente que Claude Code fala com Codex sem nada combinado.

**As armadilhas reais desse desenho** — e por que eu não repetiria nenhuma:

1. **Spinner = ruído permanente.** TUIs modernas (Claude Code inclusa) redesenham contador de tokens e animação a cada ~100 ms. Quiet-timeout sobre bytes **nunca dispara**. Só sobrevive quem diffa a *região estável* da tela. Custo: acoplamento à aparência de cada CLI — quebra a cada release.
2. **"Pedindo permissão" é indistinguível de "terminou".** Um agente parado num prompt de aprovação tem exatamente a assinatura de tela de um agente ocioso. O Maestri vai "detectar o fim" e devolver a *pergunta* como se fosse a *resposta*. Este é o bug estrutural do design, e é o mesmo bug que o teste **F** expõe no lado headless (`exit 0` com denial silencioso). Duas tecnologias, um erro.
3. **Alt-screen e scrollback.** CLIs em buffer alternativo não acumulam linearmente; "a resposta" precisa ser reconstruída da tela, e resposta longa é truncada pelo scrollback. A resposta capturada é uma função do tamanho da janela.
4. **Dois escritores no mesmo PTY.** O humano e o orquestrador escrevem no mesmo fd. Não há como serializar sem "roubar" o terminal — daí a regra de foco virar regra de produto.
5. **O token mora dentro do raio de ataque.** `MAESTRI_TOKEN` está no env de um shell que o agente controla. Qualquer `cat` de arquivo com injection no repo vira `maestri send --to <lead>` com instrução arbitrária. O token protege contra *outro terminal*, não contra o *conteúdo* que o terminal lê. **Movimento lateral entre agentes é um vetor de primeira classe** e nenhum dos três resolve.
6. **`role.json` é `--append-system-prompt` com outro nome.** *"Maestri automatically injects those instructions when the agent starts"* — é literalmente o que o teste **E** faz. Não há mágica; há uma flag equivalente em cada CLI.

**O que eu roubo do Maestri, sem discussão:** a **partitura** (`~/.maestri/partituras/*.json`: terminais, papéis, notas, conexões — **sem** scrollback, **sem** config de runtime, **sem** caminho absoluto). Isso é uma validação independente do `graphs/*.yaml` do dono, incluindo a parte difícil: **o que deliberadamente não entra no arquivo do grafo.** E os **Floors** (APFS clonefile + branch git espelhado) que, em Linux/mac portável, são exatamente `git worktree` `[V]`.

### 1.2 Grok Bot — a aresta virou uma frase em inglês

**Em uma frase:** *Grok Bot é especial porque apagou o grafo estático: a aresta não é declarada, é **resolvida em runtime** pelo modelo lendo as descrições dos outros agentes — o mesmo mecanismo de seleção de skill, apontado para o roster.*

Mecanismo, como eu leio:

- **Roteamento por descrição.** *"it scans the descriptions of other agents in your fleet and routes the request to whichever one matches"*. Implementação: catálogo `{nome, descrição, ferramentas}` injetado no contexto (ou recuperado por embedding) + uma tool `route_to(agent, payload)`. Isto é o `tool_search` bridge do Hermes com o roster no lugar do catálogo de tools.
- **Group chat como bus.** Um transcript compartilhado onde N bots leem e escrevem, com uma política de turno decidindo quem fala. *"passing work, assigning ownership, and only drawing in the user for judgment calls"* — o estado da coordenação **é** o log. Não há grafo; há um canal e uma convenção.
- **Sempre ligado.** Cada bot tem VM própria com browser e tools. Triggers são webhooks (Slack, GitHub, Teams) — poucos e de eventos, não de tempo.

**O que replica sem nuvem, barato:**
- **A tabela de roteamento.** Um nó `router` cujo prompt recebe o catálogo de nós do `graph.yaml` (id + `role` + uma linha de descrição) e escreve `next.json`. Custo: um turno de modelo por decisão, e não-determinismo. Ganho: fan-out sem enumerar arestas.
- **O group chat.** `session_dir/chat.jsonl` append-only + cada nó recebe as últimas K linhas no preâmbulo. Isso é caro em tokens e é onde nasce a bagunça — **eu não colocaria no v0**, mas é o desenho certo quando entrar.
- **A hierarquia chief-of-staff.** É um grafo com nó supervisor. Já cabe no modelo do dono, sem feature nova.

**O que não replica, e é honesto admitir:** laptop desligado, VM persistente por agente, sync cross-device, e webhooks sem endpoint público. Tentar isso no v0 significa daemon — e daemon está proibido pela spec, com razão.

### 1.3 Hermes — o que aproveita e o que é peso morto

**Em uma frase:** *Hermes é especial porque promoveu "quanto um agente pode gastar" (`IterationBudget` por agente, com `refund()`) e "o que ele pode tocar" (toolsets como ACL) a **objetos de primeira classe** — em vez de deixar os dois como efeito colateral do prompt.*

| Peça do Hermes | Veredito para o v0 | Por quê |
|---|---|---|
| **`IterationBudget` por agente, não global** | **Roubar, e é grátis** | Não preciso implementar: o `claude -p` já expõe `num_turns` e `total_cost_usd` no `result` `[V]`, e `--max-budget-usd` **corta de verdade**, com `subtype:"error_max_budget_usd"` e `terminal_reason:"budget_exhausted"` `[V-N]`. O `IterationBudget` do Hermes existe no meu runtime — só falta eu *acumular* por sessão. |
| **`refund()` para chamadas baratas** | Adiar | Só faz sentido quando o orquestrador contar iterações. Aqui a unidade é o nó, não a iteração. |
| **Toolsets como ACL, escopo por subagent** | **Roubar, e é uma linha de YAML** | `--allowedTools` / `--disallowedTools` / `--tools` por nó `[V-help]`. Least privilege declarativo com custo zero. É o item de melhor razão ganho/esforço da lista inteira. |
| **`trajectory_compressor` (protege head/tail, comprime meio)** | **Peso morto — mas a *ideia* migra de camada** | Eu não possuo o contexto: o autocompact vive dentro do Claude Code (`autocompact_state` aparece no stream `[V]`). O que migra é o princípio aplicado ao **handoff**: `handoff.md` é a compressão da trajetória — brief (head) + estado final (tail), **nunca o log**. Se o handoff virar transcript, o time morre por contexto. |
| **Subagent por RPC ("zero custo de contexto")** | Adiar, mas anotar | O truque do Hermes é o agente escrever um script que chama tools via RPC em vez de gastar um turno por tool. O análogo aqui: um nó cujo prompt manda **fazer determinístico via Bash** em vez de turno-a-turno. É engenharia de prompt, não de orquestrador. |
| **Abstração de ambiente (6 backends)** | **Peso morto no v0, costura obrigatória** | Só `local`. Mas todo spawn passa por **uma** função `run(argv, cwd, env, timeout)`. Docker/SSH depois são uma implementação dessa assinatura, não um refactor. |
| **SessionDB (SQLite WAL + FTS5)** | **Peso morto** | `state.json` + `logs/<node>.jsonl` resolvem. Caminho de migração: o JSONL é a verdade, SQLite vira índice. Nunca o contrário. |
| **Skills auto-criadas** | **Peso morto e perigoso** | Nó que reescreve as próprias instruções destrói a reprodutibilidade do grafo. A graça da partitura é rodar duas vezes e dar a mesma coisa. |
| **MCP server embutido, gateway multi-plataforma, cron** | Fora | Produto diferente. |
| **Facade `run_agent` + `_ra()`** | **Roubar o padrão** | Um `orch/adapters/__init__.py` fino e estável, com o miolo em `claude.py`/`cursor.py`. Teste faz patch na fachada. |
| **`check_fn` com TTL de 30 s** | Roubar, simplificado | O preflight (`claude --version`, `claude auth status`) roda **uma vez por `up`** e o resultado vai para `state.json`. Não re-probar por nó. |
| **Registry `register()` que rejeita shadowing** | Roubar a postura | Aqui: dois nós com o mesmo `id`, duas arestas com o mesmo `artifact`, `stop.node` inexistente → **recusa no load**, não warning. |

---

## 2. Arquitetura proposta, contra a spec v0

Escrevo no estilo da `SPEC.md`: toda escolha com o descarte.

### 2.1 A decisão central: headless `-p` vence PTY, e não é perto

**Escolhida:** `claude -p --output-format stream-json --verbose`, subprocesso, stdout capturado em arquivo.
**Descartada:** PTY interativo com detecção de fim-de-turno (o caminho do Maestri).

O motivo não é gosto, são os testes. No modo `-p` eu recebo, sem heurística: **exit code** `[V-A,D,N,Q]`, **EOF determinístico no stdout**, e um objeto `result` com `is_error`, `subtype`, `terminal_reason`, `num_turns`, `total_cost_usd`, `permission_denials[]` `[V-C]`. O PTY me daria pixels e um cronômetro.

**Custo assumido:** perco slash-commands no filho, perco o humano dando attach, perco a possibilidade de responder a um prompt de permissão no meio. **Ganho:** a condição de parada de cada nó é uma expressão booleana sobre dados, não sobre tempo. PTY volta depois **como camada de observação** (`claude --bg` + `claude logs <id>` + `claude attach <id>` já existem `[V-help]` e resolvem "quero olhar" sem virar runtime).

### 2.2 O teste F reescreve o predicado de "done"

Este é o achado que eu levaria para a mesa mesmo que tudo mais fosse descartado:

> `claude -p` em permission-mode default: **`exit 0`, `is_error: false`, `subtype: "success"` — e o arquivo não foi escrito.** `permission_denials` populado. `[V-F]`

Exit code sozinho **mente**. O predicado de conclusão de um nó tem que ser uma conjunção de quatro:

```
done(node) :=
      rc == 0
  AND result.is_error == false
  AND result.permission_denials == []          # <- o que quase todo mundo esquece
  AND verify(edge.artifact)                    # existe, não-vazio, mtime > node.started_at
```

E o `verify` merece campo próprio no YAML, porque "o arquivo existe" ainda é heurística:

```yaml
edges:
  - from: scout
    to: builder
    on: artifact_exists
    artifact: handoff.md
    verify:
      non_empty: true
      min_lines: 5           # o prompt do scout pede 5–15 linhas
      # cmd: "test $(wc -l < handoff.md) -ge 5"   # escotilha genérica, exit 0 = passou
```

**Escolhida:** predicado declarativo verificável por código. **Descartada:** um segundo `claude -p` julgando o artefato — custa um turno, reintroduz não-determinismo, e transforma o critério de parada em opinião. Nomear como v1.

**Armadilha do `artifact_exists` puro:** se `handoff.md` sobrou de uma rodada anterior no mesmo `session_dir`, a aresta dispara na hora. A spec já proíbe segundo `up` no mesmo dir, o que cobre o caso; mesmo assim, gravar `started_at` por nó e exigir `mtime > started_at` custa duas linhas e fecha a porta.

### 2.3 Ciclo de vida do nó

```
pending ──(todas as arestas de entrada satisfeitas)──► ready
ready ──(slot livre no scheduler)──► running        [spawn: novo process group]
running ──(processo saiu | timeout do pai)──► verifying
verifying ─┬─ rc=0 ∧ ¬is_error ∧ denials=[] ∧ verify(artifact) ──► done
           ├─ denials ≠ []                       ──► failed:permission   (NÃO retentar igual)
           ├─ subtype=error_max_budget_usd       ──► failed:budget
           ├─ rc≠0 ∧ api_error_status ≠ null     ──► retry:transport     (backoff, até 2)
           ├─ rc=0 ∧ denials=[] ∧ ¬verify        ──► retry:semantic      (1 vez, com nudge)
           └─ matou por timeout do pai           ──► failed:timeout
```

Quatro classes de falha, quatro tratamentos. Tratar as quatro igual é o erro que faz orquestrador entrar em loop caro:
- **permission** não é retentável com os mesmos flags. É bug de config. Falhar alto, imprimindo o `tool_name` negado e a flag que resolveria.
- **transport** (`api_error_status` preenchido, overload) retenta com backoff.
- **semantic** (o agente conversou mas não entregou) retenta **uma** vez, com `--resume <session-id do nó>` `[V-L]` e um nudge curto: *"O artefato `handoff.md` não existe. Crie-o agora e não faça mais nada."* Retomar em vez de reexecutar economiza o contexto inteiro do nó. Verificado que funciona.
- **budget** nunca retenta.

### 2.4 Isolamento

Três níveis, campo por nó, default no mais barato:

```yaml
nodes:
  - id: builder
    isolation: cwd        # cwd | worktree   (container fica fora do v0)
```

- **`cwd`** (spec v0): `cwd = session_dir / node.cwd`. **Escolhida para o v0 serial.** Custo: dois nós simultâneos no mesmo diretório se atropelam. Ganho: funciona fora de repo git, zero setup.
- **`worktree`**: `git worktree add <session>/wt/<node> -b orch/<sid>/<node>` `[V-S]`. **É a pré-condição do paralelismo (§4)**, e são ~15 linhas. Custo: exige repo git, suja o namespace de branches, precisa de `git worktree remove --force` + `git worktree prune` no teardown. Ganho: dois nós no mesmo repo sem colisão de arquivo, **e** cada um com um `cwd` distinto — o que separa também o diretório de transcripts do Claude Code (`~/.claude/projects/<hash-do-cwd>`), que de outro modo seria compartilhado.
- **Descartada no v0:** container. Vira uma implementação da função `run()` depois.

**Nota:** existe `claude -w/--worktree` nativo `[V-help]`. **Descarto**: quem tem que ser dono do ciclo de vida do worktree é o orquestrador, não o filho. Se o filho cria, o pai não sabe limpar.

### 2.5 Transporte do handoff

- **Escolhida: arquivo no `session_dir`.** É a spec, e está certa. É inspecionável por `cat`, sobrevive ao processo, e o predicado é `stat()`. É o mesmo motivo pelo qual as notas do Maestri são markdown de verdade em disco.
- **Descartada: FIFO.** Bloqueia no open, não persiste, morre com o processo, não dá replay, e um leitor a menos trava o time inteiro. Zero ganho sobre arquivo.
- **Descartada como *contrato*, adotada como *trilha*: `events.jsonl`.** O orquestrador anexa uma linha por transição (`{ts, node, from_state, to_state, rc, cost_usd, turns, artifact, reason}`). **O runtime nunca lê esse arquivo para decidir** — se ler, viram duas verdades e a próxima sessão diverge. Custo: um arquivo a mais. Ganho: debug, replay futuro e a base do event-log que a spec já nomeou como evolução.
- **Descartada: bus/inbox.** Só faz sentido com o group chat do Grok Bot, e isso é v2.

### 2.6 Orçamento — três eixos, e os três são observáveis

Este é o ponto onde o Hermes deixa de ser inspiração e vira implementação, porque o CLI já expõe os números.

| Eixo | Como aplico | Evidência |
|---|---|---|
| **Custo por nó** | `--max-budget-usd <n>` na linha de comando. Corta de verdade: `exit 1`, `subtype:"error_max_budget_usd"`, `terminal_reason:"budget_exhausted"` | `[V-N]` |
| **Custo por sessão** | acumular `result.total_cost_usd` em `state.json`; se `total + próximo_teto > session_cap`, **não subir o próximo nó** | `[V-C]` |
| **Turnos** | `result.num_turns` post-hoc. Não dá para cortar em voo no `-p`; serve para marcar nó *degradado* e para calibrar o teto | `[V-C]` |
| **Relógio** | timeout **implementado no processo pai** (`subprocess` com `timeout=`), não `timeout(1)` | ver §6 R7 |
| **Assinatura** | `rate_limit_event.rate_limit_info.unifiedWindows.five_hour.utilization` (e `seven_day`) lidos do stream em tempo real | `[V-J]` |

O último é o que ninguém espera existir e é o mais valioso: **a janela de 5 h e a de 7 dias vêm com utilização fracionária e `resetsAt` em epoch**. O scheduler pode ler `utilization` do último nó concluído e:

```
if five_hour.utilization > 0.85  → degrada para concorrência 1
if five_hour.utilization > 0.95  → pausa até resetsAt (dorme, não falha)
if status != "allowed"           → para a sessão com motivo explícito
```

Isso transforma "vai que estoura o limite" em política. **Escolhida:** gate por utilização observada. **Descartada:** retry cego em 429 — é o comportamento que gera padrão de tráfego abusivo e é exatamente o que a §6/R1 quer evitar.

### 2.7 Retomada

A spec diz "sem resume no v0" e eu manteria — **no nível da sessão**. Mas no nível do **nó** a retomada custa zero e o teste L prova:

- Cada nó ganha um UUID determinístico: `uuid5(NAMESPACE, session_id + ":" + node_id)`.
- Primeira execução: `--session-id <uuid>`.
- Retry semântico: `--resume <uuid>` + nudge curto.

Ganho: um retry que não relê o mundo. Custo: nenhum novo conceito — o UUID é derivado, não armazenado. **Descartada:** `--continue` (depende do "mais recente no diretório atual" — estado implícito, e com paralelismo é uma corrida).

### 2.8 Comando

Nada muda na superfície da spec:

```
python -m orch up graphs/v0.yaml --session-dir .sessions/<session_id>
```

Acrescento **um** comando, e ele se paga na primeira quebra de flag:

```
python -m orch doctor        # binário, versão, auth, e um contrato-teste de 5 s
```

O `doctor` roda um `claude -p --output-format json "reply OK"` e **afirma que os campos que o parser lê existem** (`is_error`, `subtype`, `permission_denials`, `num_turns`, `total_cost_usd`). Falha nomeando o campo ausente. É a resposta operacional à cláusula da SPEC *"se o CLI mudar de flag, emenda datada antes de adaptar o código"* — sem `doctor`, a descoberta da mudança acontece no meio de uma sessão, com o log errado.

---

## 3. O adaptador de CLI

### 3.1 O contrato

Três métodos e um dataclass. Fachada fina, no padrão `run_agent`/`_ra()` do Hermes.

```
preflight()                        -> Ok | Reason        # uma vez por `up`, cacheado em state.json
build(node, session, retry_ctx)    -> Spawn{argv, cwd, env, stdin_bytes, timeout_s}
parse(rc, stdout_path, stderr_path)-> Outcome
```

```
Outcome:
  ok: bool                 # a conjunção das quatro condições de §2.2
  rc: int
  failure: none | transport | permission | budget | semantic | timeout | parse
  denials: [ {tool_name, tool_input} ]
  turns: int | null
  cost_usd: float | null          # unidade de orçamento, NÃO dinheiro (ver R8)
  session_ref: str | null         # para o --resume do retry
  rate_limit: {five_hour_util, seven_day_util, resets_at} | null
  text: str                       # última mensagem do agente, só para o log humano
```

**Regra dura:** o `Outcome` é definido **antes** dos adapters e é o único acoplamento entre eles. É o que permite escrever `claude.py` e `cursor.py` em paralelo (§5).

### 3.2 Adapter `claude` — comando exato

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
  --setting-sources project \
  --strict-mcp-config \
  --append-system-prompt "$(cat "$SESSION_DIR/prompts/$NODE.preamble.md")" \
  < "$SESSION_DIR/prompts/$NODE.prompt.md" \
  > "$SESSION_DIR/logs/$NODE.jsonl" \
  2> "$SESSION_DIR/logs/$NODE.err"
```

Justificativa item a item, com a marca:

- **`-p` + `stream-json` + `--verbose`** — `--verbose` é **obrigatório**, sem ele é `exit 1` `[V-H]`. Escolho `stream-json` sobre `json` por um motivo só: é onde vêm os `rate_limit_event` `[V-J]`. O `result` final está na última linha do JSONL, com o mesmo conteúdo do `json` `[V-I]`.
- **`--permission-mode acceptEdits`** — o mínimo que faz o nó escrever o artefato. Sem isso, o teste **F**: sucesso silencioso e nada em disco `[V-F,G]`. **Descartada `bypassPermissions`:** ganha nada além de Bash irrestrito e perde a rede de segurança inteira; se um nó precisa de Bash, isso se declara em `--allowedTools`.
- **prompt por stdin** `[V-B]` — não por argv. Sem `ARG_MAX`, sem escaping, sem prompt de 8 KB vazando no `ps`.
- **`--append-system-prompt`** com o preâmbulo gerado (`session_dir`, `node.id`, artefato esperado, "não suba outro agente"). É o `role.json` do Maestri `[V-E]`. **Uso a forma com `"$(cat ...)"`, não `--append-system-prompt-file`**: o `-file` funciona `[V-O]` mas **não aparece na lista de options do `--help`** — flag não documentada é flag que some sem changelog. Registro que existe e não dependo dela.
- **`--session-id` determinístico** — habilita o `--resume` do retry `[V-L]`.
- **`--add-dir "$SESSION_DIR"`** — quando `isolation: worktree`, o cwd do nó é o worktree e o `handoff.md` mora no session_dir; sem isso, o nó não alcança o artefato.
- **`--allowedTools` / `--disallowedTools`** — os toolsets do Hermes, por nó `[V-help]`. Um `scout` não precisa de `Write` fora de `handoff.md` e não precisa de rede. **Isto não é refinamento, é a ACL de verdade:** verifiquei com `env -i` que `--permission-mode acceptEdits` libera **também o Bash** (`touch` executado, `permission_denials: []`, `exit 0`) `[V]`. Quem contar com "acceptEdits só aceita edições" está com um nó de shell irrestrito e não sabe.
- **`--setting-sources project` + `--strict-mcp-config`** — hermeticidade sem quebrar OAuth. **Nunca `--bare`**: ele força `ANTHROPIC_API_KEY` e viola a restrição do produto `[V-help]`.
- **`--max-budget-usd`** — teto que corta de verdade `[V-N]`.
- **`--fallback-model`** — considerar (`--print` only `[V-help]`). Ganho: sobrevive a overload sem falhar o nó. Custo: o nó pode rodar num modelo mais fraco sem o operador saber. Se entrar, o `Outcome` grava qual modelo serviu (`modelUsage` tem a chave `[V-C]`).

**Env sanitizado — a lista, e por que ela é maior do que a spec previu.** A spec manda tirar `ANTHROPIC_API_KEY`. O teste **R** mostra que isso é metade do problema: um `claude` filho herda **`CLAUDE_CODE_SESSION_ID`, `CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT`, `ANTHROPIC_BASE_URL`** e umas quarenta outras. No teste I o filho **reusou o `session_id` do processo pai** porque o env mandava. Se o orquestrador for lançado de dentro de um Claude Code — que é o caso provável de quem o está construindo — todos os nós colidem no mesmo id.

Allowlist, não denylist:

```
PASSA:   HOME, PATH, USER, SHELL, LANG, LC_*, TERM=dumb, TZ,
         TMPDIR, SSH_AUTH_SOCK (só se um nó precisar de git via ssh),
         ORCH_SESSION_DIR, ORCH_NODE_ID, ORCH_ARTIFACT   (nossos, prefixados)
BLOQUEIA (explícito e testado):
         ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, ANTHROPIC_BASE_URL,
         CLAUDECODE, CLAUDE_CODE_*, CLAUDE_*, CURSOR_*
```

`TERM=dumb` de propósito: sem TTY o CLI já vai para o caminho não-interativo `[V-help: "the trust dialog is skipped when stdout is not a TTY"]`, e `dumb` remove qualquer resíduo de ANSI no log.

**Onde o `claude` trai a expectativa** — cinco, todos verificados:

1. **`exit 0` com o trabalho não feito** (denial silencioso) `[V-F]`. Já coberto.
2. **`--output-format text` escreve o erro no STDOUT** `[V-D]`. Quem faz `if rc==0: artifact = stdout` grava a mensagem de erro como artefato. **Nunca parsear `text`.**
3. **Autocompact silencioso.** `autocompact_state{enabled, effective_window, threshold, enforced}` aparece no stream `[V-I]`. Um nó longo é comprimido no meio do caminho e ninguém avisa. O adapter deve **logar** o evento e marcar o nó como `degraded` se disparar.
4. **`total_cost_usd` é preço de tabela.** No teste C: `"costBasis":"list"`, `"provider":"firstParty"` `[V-C]`. Numa assinatura Pro isso **não é o que foi cobrado**. Usar como unidade de orçamento, jamais imprimir como "você gastou $X".
5. **Herança de env** `[V-R]`. Já coberto.

### 3.3 Adapter `cursor-agent`

Binário ausente nesta máquina — **tudo aqui é `[D]` da doc oficial (`cursor.com/docs/cli/reference/parameters`, `/docs/cli/headless`), nada executado.** Marco isso porque a diferença importa: no lado do `claude` eu sei; no lado do Cursor eu li.

```bash
cursor-agent -p \
  --output-format stream-json \
  --force \
  --model "$NODE_MODEL" \
  --workspace "$NODE_CWD" \
  "$(cat prompt.md)"
```

- `-p, --print` — *"Print responses to console (for scripts or non-interactive use). Has access to all tools, including write and shell."* `[D]`
- `--output-format text|json|stream-json` (default `text`), só com `--print`; `--stream-partial-output` para deltas `[D]`
- Eventos do `stream-json`: `system` (init, modelo), `assistant`, `tool_call{subtype: started|completed}`, `result{duration_ms}` `[D]`. **Schema diferente do Claude** — normalizar no `Outcome`.
- `--force` / `--yolo` — *"Force allow commands unless explicitly denied"* `[D]`. É o habilitador de escrita, e é **mais grosso** que `acceptEdits`: allow-unless-denied. Sem equivalente a `permission_denials` documentado → **para o Cursor o predicado de artefato não é redundância, é a única defesa.**
- `--resume [chatId]`, `--mode plan|ask`, `--sandbox enabled|disabled`, `--workspace <path>` `[D]`
- Auth: `--api-key` ou `CURSOR_API_KEY` `[D]`. Isso *é* uma chave de API — mas do Cursor, não da Anthropic; a restrição do produto continua respeitada. Ainda assim eu preferiria `cursor-agent login` e não passar chave por env, para não normalizar o padrão.

**Onde o Cursor trai:**
1. **Exit code sem contrato documentado.** A doc só mostra `if [ $? -eq 0 ]` num exemplo `[D]`. → **timeout no pai + predicado de artefato são obrigatórios**, não opcionais.
2. **Bug conhecido de `-p` pendurando indefinidamente** (fórum oficial: Cursor 2.4.21–2.4.22, Agent CLI 2026.01.28+, macOS e Linux; causa apontada como retries TCP silenciosos de 10–15 s; moderador reporta correção "nas versões recentes") `[D]`. → timeout **generoso** (≥ 60 s antes de considerar hang) e mensagem de erro que cite este bug por nome, senão o operador culpa o orquestrador.
3. **Sem telemetria de custo/turnos comparável.** O `Outcome` sai com `turns=null, cost_usd=null`. Orçamento vira só relógio. Registrar isso no `state.json`, não fingir paridade.
4. **`--workspace` em vez de confiar no cwd** — se existe a flag, usá-la; cwd implícito é a fonte silenciosa de "o agente editou o repo errado".

### 3.4 Adapter genérico `exec` — a peça que salva o projeto

Um tipo de nó em que o YAML dá o comando:

```yaml
nodes:
  - id: reviewer
    adapter: exec
    cmd: ["codex", "exec", "--cd", "{cwd}", "-"]   # {cwd} {artifact} {session_dir} {prompt_file}
    stdin: "{prompt_file}"
    parse: exit_code_only
    timeout: 900
```

`Outcome` degradado: `ok = (rc == 0) && verify(artifact)`, resto `null`. **Custo:** perde orçamento e denials. **Ganho:** é o que torna o orquestrador agent-agnostic no sentido do Maestri — `codex`, `opencode`, `aider`, ou um `.sh` — **sem** o Maestri ter precisado de PTY para isso. E é o seguro contra o risco R1: se um dia a assinatura fechar a porta para automação, o projeto aponta para outro binário e continua vivo.

**Escolhida:** três adapters, um `Outcome`. **Descartada:** um adapter só, com `if binary == "claude"` — é a ramificação que o Hermes tirou do dispatcher de propósito ("data, not branches").

---

## 4. Paralelismo

### 4.1 Está verificado que dá

3× `claude -p` simultâneos, cwds distintos, `&` + `wait`: **3 sucessos, 3 artefatos corretos, 10 s** `[V-M]`. `wait -n` funciona no bash 5.2 `[V-T]`. `git worktree` com dois branches funciona `[V-S]`.

### 4.2 O desenho

O orquestrador é Python (`python -m orch up`), então o paralelismo real é `ThreadPoolExecutor(max_workers=N)` sobre `subprocess.run(..., timeout=)` — I/O-bound, GIL irrelevante. É o mesmo formato do Hermes: **paralelo com ordem preservada** (o resultado volta indexado pelo `node.id`, o log é por nó).

**Scheduler = conjunto pronto, não ordem topológica fixa.** A cada conclusão, recalcular quem ficou `ready` (todas as arestas de entrada com `done` + `verify` ok) e preencher os slots livres. Isso é a semântica do `wait -n`, e é o que permite fan-out irregular sem replanejar.

A versão bash, para o demo do README (útil porque comunica o desenho em 10 linhas):

```bash
sem=3
for n in "${ready[@]}"; do
  while (( $(jobs -rp | wc -l) >= sem )); do wait -n; done
  ( run_node "$n" ) &
done
wait
```

**Escolhida:** scheduler no pai, em Python. **Descartada:** `xargs -P` / GNU parallel — não sabem o grafo, não recalculam o conjunto pronto, e não têm onde acumular orçamento.

### 4.3 O que quebra, e o remédio

1. **Dois agentes no mesmo repo.** Worktree resolve o *working tree*, **não** resolve `.git/index.lock` e `.git/objects` durante commits concorrentes — worktrees compartilham o object store. Remédio: **nós não commitam**; o pai commita, serializado. Se um nó precisar commitar, `fcntl.flock` num `<repo>/.git/orch-commit.lock`.
2. **Rate limit da assinatura.** Com 3 nós, a janela de 5 h enche 3× mais rápido. Verificado que a utilização é legível `[V-J]` → token bucket no pai, alimentado pelo último `rate_limit_event`, degradando a concorrência antes de estourar. **Este é o limite real de escala, não a CPU.**
3. **Contexto cruzado.** Cada `claude -p` é sessão nova; não há vazamento *dentro do modelo*. O que vaza é **fora**: `~/.claude/projects/<hash-do-cwd>` compartilhado quando dois nós rodam no mesmo cwd, e `CLAUDE.md`/hooks/plugins da máquina entrando em todo nó. Remédio: worktree (cwd distinto ⇒ diretório de projeto distinto) + `--setting-sources` + `--strict-mcp-config`.
4. **Colisão de `--session-id` por herança de env** `[V-R]`. Sanitizar o env (§3.2) e derivar o UUID por nó.
5. **Zombies no timeout.** `claude` gera filhos (a tool Bash). `Popen.kill()` mata o pai e deixa órfão segurando o worktree e o lock. Remédio: `start_new_session=True` no spawn e `os.killpg(os.getpgid(p.pid), SIGTERM)` → grace 5 s → `SIGKILL`. **Não negociável** — sem isso o `worktree remove` falha e a sessão seguinte não sobe.
6. **Log entrelaçado.** Um arquivo por nó, sempre. Nunca stdout compartilhado. O `events.jsonl` do pai é a única visão cronológica, e é escrito só pelo pai.
7. **Lock por artefato.** `fcntl.flock` num `<artifact>.lock`. **Não `flock(1)`** — ver R7.
8. **Default = 1.** `--max-concurrency` com default `1`, e o paralelismo é opt-in explícito. Isso não é timidez de engenharia: é a mitigação de R1 na camada onde ela custa zero.

---

## 5. Backlog por camada

Menor caminho até "roda de verdade" primeiro; o resto é crescimento.

### Camada 0 — esqueleto e preflight *(serial, é a base de tudo)*
1. `orch/cli.py`: `up`, parsing de args, criação do `session_dir`, cópia do `graph.yaml`, `state.json` inicial.
2. `orch/graph.py`: load YAML + validação **que recusa** — `id` ≠ stem, nó órfão, aresta para nó inexistente, ciclo (Kahn), `stop.node` inexistente, id fora de `^[a-z][a-z0-9_-]{0,31}$`.
3. `orch/env.py`: sanitizador de env (allowlist da §3.2) + preflight (`claude --version`, `claude auth status`), resultado gravado uma vez em `state.json`.

### Camada 1 — um nó de ponta a ponta *(o marco "roda de verdade")*
4. `orch/outcome.py`: o dataclass `Outcome`. **Primeiro de tudo depois da camada 0** — é o que destrava o fan-out da equipe.
5. `orch/adapters/claude.py`: `build()` (§3.2), spawn com process group, captura de `logs/<node>.jsonl`, `parse()` da última linha `result`.
6. `orch/state.py`: escrita atômica (tmp + `os.replace`) de `state.json`.

> **Aqui `up graphs/v0.yaml` sobe o `scout` e `handoff.md` aparece em disco.** É o corte. Estimo ~250 linhas. Tudo antes é obrigatório; tudo depois é crescimento.

### Camada 2 — a aresta e a parada
7. Predicado de aresta: `artifact_exists` + `mtime > node.started_at` + bloco `verify` (`non_empty`, `min_lines`, `cmd`).
8. Linha de log do handoff (`handoff scout → builder artifact=handoff.md`) + `events.jsonl`.
9. Critério de parada e exit code da sessão (0 / 1), conforme §5 da SPEC.

### Camada 3 — robustez
10. Timeout no pai + `killpg` (§4.3-5).
11. Classes de falha (§2.3) e o retry semântico com `--resume` + nudge.
12. Acumulador de orçamento (`total_cost_usd`, `num_turns`) + gate de rate limit lendo `rate_limit_event`.
13. `orch doctor` (§2.8).

### Camada 4 — paralelo
14. `orch/worktree.py`: add / remove / prune, com fixture de repo git nos testes.
15. Scheduler de conjunto pronto + `--max-concurrency` (default 1).
16. `fcntl.flock` por artefato; lock de commit por repo.

### Camada 5 — segundo adapter e ACL
17. `orch/adapters/cursor.py` e `orch/adapters/exec.py`, normalizando para `Outcome`.
18. Campo `tools:` por nó → `--allowedTools` / `--disallowedTools`.

### Repartição para subagentes

**Paralelizável assim que o `Outcome` (item 4) existir** — três frentes que não se tocam:
- **A:** itens 5 + 17 (adapters). Só dependem de `Outcome`.
- **B:** item 2 (validação de grafo) — puro, testável com YAMLs de fixture, zero dependência.
- **C:** item 14 (worktree) — módulo git puro, testável com repo de fixture.

**Serial por dependência, sem atalho:** 1 → 3 → 4 → 5 → 6 → 7 → 9. E o item 15 (scheduler) exige 6 e 14 prontos — é o último a entrar, e é onde toda regressão de concorrência vai aparecer.

**Recomendação de sequência de trabalho:** fechar 1–6 numa sessão só, de uma pessoa. Depois abrir A/B/C em paralelo. Fan-out antes do `Outcome` existir produz três adapters com três contratos.

---

## 6. Riscos técnicos, com mitigação

**R1 — ToS e limites de assinatura ao automatizar CLI. `[risco de produto, não só técnico]`**
Termos de assinatura de consumidor miram uso interativo humano. Uma frota de `claude -p` headless é exatamente o padrão que aciona detecção de abuso. E não é especulação: a plataforma **mede isso e me conta** — `rateLimitType:"five_hour"`, `unifiedWindows.seven_day`, `overageStatus`, `isUsingOverage` `[V-J]`.
Mitigação, em ordem de importância: (a) `--max-concurrency` default **1**, paralelo opt-in; (b) gate por `utilization` com pausa até `resetsAt`, **nunca** retry cego em 429; (c) `--max-budget-usd` por nó como segundo cinto `[V-N]`; (d) README dizendo em voz alta que o usuário roda sob a **própria** conta — sem compartilhar credencial, sem multi-conta, sem rodar por terceiros; (e) **o adapter `exec`** (§3.4) é a apólice de seguro: se a porta fechar, o projeto aponta para outro binário no mesmo dia. Não fazer (e) é apostar o projeto inteiro numa cláusula que não é nossa.

**R2 — Heurística de fim-de-turno.**
Eliminada no v0 pela escolha de `-p` (§2.1): o processo sai, e sair é um fato. O que **sobra** de heurístico é "o nó fez o trabalho?" — e a resposta ingênua ("o arquivo existe") é fraca. Mitigação: o bloco `verify` (§2.2) transforma o predicado num teste executável. Não mitigado e nomeado: se um dia entrar PTY para observação, **não deixar a observação virar decisão**.

**R3 — `exit 0` com trabalho não feito.** `[V-F]` — o risco mais subestimado da lista, porque não parece risco: parece sucesso. Mitigação: a conjunção de quatro condições da §2.2, e o adapter falhando alto no `permission_denials` com o `tool_name` no erro.

**R4 — Deriva de CLI e flag não documentada.**
`--append-system-prompt-file` funciona e **não está na lista do `--help`** `[V-O]`. Mitigação: não depender dela (usar `"$(cat)"`); `orch doctor` afirmando o schema que o parser lê; gravar `claude --version` em `state.json`; e honrar a cláusula da SPEC — emenda datada antes de mexer no código.

**R5 — `--bare` parece a resposta e é a armadilha.** Força `ANTHROPIC_API_KEY`/apiKeyHelper e **nunca lê OAuth** `[V-help]` → viola a restrição de zero API key. Mitigação: proibir por escrito no adapter (lista negra de flags), usar `--safe-mode` `[V-P]` + `--setting-sources` + `--strict-mcp-config`.

**R6 — Herança de env.** `[V-R]` Allowlist, não denylist (§3.2). Sintoma se ignorado: nós colidindo em `session_id`, com transcript entrelaçado e um `--resume` que retoma a conversa errada.

**R7 — Portabilidade Linux/mac.** `timeout(1)` e `flock(1)` **não existem no macOS de fábrica** — são coreutils/util-linux. Verificado que existem aqui (Linux) `[V]`; a ausência no mac é conhecida. Mitigação: **implementar timeout e lock no processo pai** (`subprocess(timeout=)`, `fcntl.flock`), nunca shell out. Regra geral: se um recurso existe em Python, não terceirizar para binário do sistema.

**R8 — Custo reportado é preço de tabela.** `costBasis:"list"` `[V-C]` — não é o que a Pro cobra. Mitigação: chamar de "unidade de orçamento" no CLI e no `state.json`; nunca imprimir "você gastou $X".

**R9 — Injection lateral entre nós.** O `handoff.md` é escrito por um agente que leu arquivos do repo. Instrução injetada num arquivo vira instrução no handoff, que o próximo nó executa. É o mesmo buraco que o `MAESTRI_TOKEN` no env do shell não fecha. Mitigação parcial no v0: o preâmbulo do nó receptor declara que o handoff é **dado, não comando**; `--disallowedTools` por nó; artefatos fora do worktree em leitura. **Não resolvido, e eu nomearia isso na SPEC** em vez de deixar implícito.

**R10 — Autocompact silencioso.** `[V-I]` Um nó longo é comprimido no meio e a decisão sai de um contexto que ninguém viu. Mitigação: logar `autocompact_state`, marcar o nó `degraded`, e tratar prompt de nó que dispara autocompact como sintoma de nó grande demais — o remédio é dividir o nó, não aumentar a janela.

---

## Apêndice — o que eu não verifiquei e deveria ser verificado antes da MAT-97

1. `cursor-agent` inteiro: binário ausente aqui. Tudo em §3.3 é `[D]`. **Instalar e repetir os testes A–R** antes de escrever `adapters/cursor.py`.
2. Comportamento do `claude -p` sob rate limit real (o quê no `result`? `is_error`? qual `subtype`?). Só observei `status:"allowed"` `[V-J]`.
3. `--input-format stream-json` para injetar turnos no meio de um nó — o caminho para "responder a uma pergunta do nó sem PTY". Não testado.
4. `claude --bg` + `claude logs <id>` + `claude attach <id>` como camada de observação `[V-help]`, não executados.
5. ~~Se `acceptEdits` liberou o `Bash` por causa do modo ou de settings da máquina.~~ **Resolvido durante a redação:** repeti o teste com `env -i` (só `HOME`/`PATH`/`USER`/`TERM=dumb`/`LANG` + o fd de auth) e o `Bash(touch)` passou com `permission_denials: []` e `exit 0` `[V]`. Ou seja, **`acceptEdits` nesta versão não é só "edits": libera Bash também.** Consequência direta para §3.2: `--allowedTools`/`--disallowedTools` deixam de ser refinamento e viram **a** ACL do nó — o `--permission-mode` sozinho não restringe nada de útil. Falta verificar se algum comando é gateado (destrutivo, rede) ou se é allow-all.

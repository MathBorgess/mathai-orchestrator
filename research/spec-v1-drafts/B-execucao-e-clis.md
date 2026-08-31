# SPEC-2 — execução (§3 paralelismo · §4 invocação dos CLIs)

**Frente B.** Estende [`SPEC.md`](SPEC.md) e [`MVP.md`](MVP.md). Onde divergir, está marcado **emenda**.
**Base de fato:** [`research/teammates/03-engenheiro-hermes.md`](research/teammates/03-engenheiro-hermes.md) — 20 testes executados contra `claude` **2.1.251**, Linux, bash 5.2.21. As marcas `[V-x]` neste arquivo apontam para a linha daquele registro. `[D]` = lido em doc oficial. `[I]` = inferência declarada.
**Regra desta spec:** toda escolha traz o descarte, com custo e ganho. Decisão sem alternativa não entra. Onde o texto diz **DEVE** / **NÃO PODE**, é normativo — o implementador da MAT-97 não reabre.

---

## §3 — Como o orquestrador executa N nós em paralelo

### 3.0 A emenda que abre esta seção

**Emenda à `SPEC.md` §3.** Cai a frase *"Um nó `running` por vez no v0 (serial)"*. O orquestrador executa **N nós concorrentes**, com teto declarado no grafo e teto operacional na linha de comando.

**Escolhida / descartada.** Execução concorrente por padrão de desenho, serial por padrão de operação. Custo: o ciclo de vida do nó deixa de ser uma fila e vira uma máquina de estados com escalonador — quatro regras novas (§3.7) passam a ser obrigatórias, e nenhuma delas é opcional em produção. Ganho: a única métrica do veredito que o paralelismo compra (`wall_seconds`, §3.9) sai do papel, e o tipo de nó `fanout` do `MVP.md` §1.1 deixa de ser schema morto. Descartada a alternativa de manter serial e "paralelizar depois": o escalonador de conjunto pronto (§3.3) **é** o executor serial quando `k=1`; escrever o serial primeiro significa escrever e jogar fora.

O que **não** cai da `SPEC.md` §3: cada nó continua sendo um **subprocesso**, com `stdout`/`stderr` em `session_dir/logs/<node>.*`, e o orquestrador continua sendo um processo pai que sobe, espera a parada e sai. Sem daemon, sem tmux no runtime, sem PTY.

### 3.1 Ciclo de vida do nó

```
pending ──(todas as arestas de entrada satisfeitas)──► ready
ready ──(slot livre no escalonador ∧ gate de janela aberto)──► running
                                          [spawn em NOVO PROCESS GROUP]
running ──(processo saiu | timeout do pai)──► verifying
verifying ─┬─ rc=0 ∧ ¬is_error ∧ denials=[] ∧ verify(artefato) ──► done
           ├─ denials ≠ []                  ──► failed:permission  (NÃO retenta)
           ├─ subtype=error_max_budget_usd  ──► failed:budget      (NUNCA retenta)
           ├─ rc≠0 ∧ api_error_status≠null  ──► retry:transport    (backoff, até 2)
           ├─ rc=0 ∧ denials=[] ∧ ¬verify   ──► retry:semantic     (1×, --resume + nudge)
           └─ morto por timeout do pai      ──► failed:timeout
```

Estados persistidos em `state.json`: `pending | ready | running | verifying | done | failed | skipped`. `verifying` é estado de verdade, não de trânsito: é onde o pai lê o log do filho e decide. Um nó que saiu do `running` e ainda não passou pelo `verifying` **não** tem status conhecido, e o escalonador **NÃO PODE** liberar o slot antes do veredito — liberar antes é como o paralelismo passa a corromper o grafo.

**As quatro classes de falha, e por que a distinção é normativa.**

| Classe | Sinal | Tratamento | Motivo |
|---|---|---|---|
| `permission` | `permission_denials ≠ []` `[V-F]` | **falha alto, sem retry** | É bug de configuração, não de execução. Retentar com os mesmos flags produz o mesmo denial e queima janela. O erro **DEVE** imprimir o `tool_name` negado e a flag de `--allowedTools` que o resolveria. |
| `budget` | `subtype: "error_max_budget_usd"` `[V-N]` | **falha, nunca retenta** | O teto foi respeitado. Retentar é desrespeitá-lo. |
| `transport` | `rc≠0` com `api_error_status` preenchido | retry com backoff, até 2 | Overload e erro de rede são transitórios por definição. |
| `semantic` | `rc=0`, sem denials, artefato ausente ou inválido | **1** retry, via `--resume` + nudge | O agente conversou e não entregou. Retomar a sessão do nó `[V-L]` custa o nudge, não o contexto inteiro. |

**Escolhida / descartada.** Quatro classes, quatro tratamentos. Descartado tratar todas como "falhou, tenta de novo": com `k=1` isso custa uma sessão lenta; com `k=3` isso é **três loops caros simultâneos** contra a mesma janela de assinatura, e a sessão se mata sozinha em minutos. Custo: quatro caminhos no código de `verify`. Ganho: a única forma de o paralelismo não multiplicar o desperdício junto com a vazão.

**Escolhida / descartada.** O retry semântico usa `--resume <session-id do nó>` `[V-L]`, não uma execução nova. Custo: acopla o retry ao adapter que suporta retomada — o `exec` (§4.6) não tem, e ali o retry semântico **DEVE** ser desabilitado, não emulado. Ganho: verificado que o filho lembra o turno anterior, então o nudge é uma frase (*"O artefato `handoff.md` não existe. Crie-o agora e não faça mais nada."*) em vez de reenviar o prompt e o contexto.

### 3.2 O predicado de conclusão — texto normativo

Um nó **está concluído se, e somente se, as quatro condições abaixo forem simultaneamente verdadeiras**:

```
done(node) := rc == 0
          AND result.is_error == false
          AND result.permission_denials == []
          AND verify(edge.artifact)
```

onde `verify` exige, no mínimo: o artefato **existe**, é **não-vazio**, e tem `mtime > node.started_at`. Predicados adicionais vêm do bloco `verify:` da aresta (`min_lines`, `cmd`), conforme `MVP.md` §3.

**O orquestrador NÃO PODE marcar um nó como `done` a partir do exit code isolado.** Verificado em execução: `claude -p` em permission-mode default, ao qual se pede um `Write`, retorna **`exit 0`, `is_error: false`, `subtype: "success"` — e o arquivo não existe**, com `permission_denials[]` populado `[V-F]`. Um escalonador que confia no `rc` propaga a aresta e sobe o nó seguinte contra um artefato inexistente.

**Escolhida / descartada.** Conjunção de quatro. Descartado o `rc` isolado (mente, provado), descartado o par `rc + artefato` (deixa passar o denial silencioso quando o artefato sobrou de outra rodada — daí a cláusula `mtime > started_at`), descartado o julgamento por LLM (custa um turno, reintroduz não-determinismo no ponto mais caro de debugar, e `MVP.md` §3 já registra +129% de tokens sem ganho). Custo: `verify` tem que ser executável e declarado por aresta — quem não escrever `verify:` fica com a checagem mínima e recebe menos garantia. Ganho: o critério de conclusão é uma expressão booleana sobre dados observados, não uma heurística sobre tempo.

**Consequência para o paralelismo:** `verify` roda no **pai**, no estado `verifying`, com o slot ainda ocupado. Rodar `verify` em paralelo com o próximo nó é o que produz a corrida em que B lê um `handoff.md` que A ainda estava escrevendo.

### 3.3 O escalonador de conjunto pronto

O pai **não** executa uma ordem topológica pré-computada. A cada conclusão, ele recalcula.

```
ready_set() := { n ∈ nodes :
                   status(n) == pending
                 ∧ ∀ e ∈ arestas_de_entrada(n): status(e.from) == done ∧ predicado(e) verdadeiro }
```

Laço do pai, normativo:

1. Computa `ready_set()`. Se vazio e nenhum nó em `running`/`verifying` → a sessão **está travada**: encerra com `stop_reason: deadlock` e o conjunto de nós `pending` no erro. (Isto **DEVE** ser um erro nomeado, não um `wait` eterno — o `up` sem esta cláusula é o loop infinito clássico.)
2. Enquanto houver slot livre **e** o gate de janela estiver aberto (§4.7), retira um nó de `ready_set()` e o sobe: cria/garante o isolamento (§3.5), monta o `Spawn` (§4.1), lança em novo process group.
3. Bloqueia até **a primeira** conclusão — semântica de `wait -n`, verificada no bash 5.2 `[V-T]`, implementada em Python como `concurrent.futures.wait(..., return_when=FIRST_COMPLETED)`.
4. Roda `verifying` para o nó que voltou, aplica o predicado de §3.2, escreve a transição em `state.json` e a linha em `events.jsonl`, libera o slot.
5. Volta ao passo 1.

O passo 1 depois de **cada** conclusão é a diferença entre um escalonador e uma fila: com fan-out irregular e retries, o conjunto pronto muda de forma no meio da sessão, e uma ordem pré-computada fica errada no primeiro `retry:semantic`.

**Escolhida / descartada.** Escalonador de conjunto pronto no processo pai, `ThreadPoolExecutor` sobre `subprocess.run(timeout=)`. Custo: um laço a mais e a obrigação de o pai ser single-writer de `state.json`. Ganho: I/O-bound puro (o trabalho está no filho), GIL irrelevante, e o `k=1` cai fora como caso degenerado — não há dois executores para manter. Descartado `xargs -P` e GNU parallel: não conhecem o grafo, não recalculam o conjunto pronto, não acumulam orçamento e não têm onde aplicar o gate de janela. Descartado `asyncio`: ganha zero sobre threads para 3 subprocessos e paga uma cor de função em todo o código.

**Escolhida / descartada.** Bloqueio em `FIRST_COMPLETED`, não em barreira. Custo: nenhum. Ganho: com nós de duração desigual — e eles são desiguais, um `check` sai em 200 ms e um `agent` em 4 min — a barreira deixa slots ociosos até o mais lento terminar. Descartada a barreira por onda: é a implementação que faz `k=3` render como `k=1` num grafo real.

### 3.4 `--max-concurrency`: teto operacional, não motor

```
orch up graphs/<id>.yaml --session-dir .sessions/<id> [--max-concurrency N]
```

- **Default: `1`.** Sem a flag, a sessão roda serial, e o comportamento é idêntico ao da `SPEC.md` v0.
- **Teto de schema: `3`.** O `fanout` do `MVP.md` §1.1 já declara `max: 3`; o `up` **DEVE recusar no load** um grafo cuja largura declarada exceda o teto, e **DEVE recusar** `--max-concurrency` acima de 3 sem uma flag explícita de escape.
- O efetivo é `min(--max-concurrency, teto_do_grafo, teto_do_gate_de_janela)` — e o terceiro termo muda **durante** a sessão (§4.7).

**Escolhida / descartada.** Default 1 com paralelismo opt-in. Custo: quem clonar o repo e rodar `orch up` não vê o paralelismo — a feature principal desta emenda fica escondida atrás de uma flag. Ganho: é a mitigação do risco de ToS (`MVP.md` §10 R1) no ponto em que ela custa exatamente zero, e é a postura defensável se alguém perguntar por que o projeto existe. Descartado default 3: transforma todo clone acidental num gerador de tráfego automatizado contra a assinatura de quem clonou.

**O que `--max-concurrency` NÃO é.** Não é o que cria paralelismo. Quem cria é a **largura do grafo**. Num `scout → builder` (o `graphs/v0.yaml`) o valor efetivo é 1 para qualquer `N`, porque o conjunto pronto nunca tem dois elementos. Isto **DEVE** estar na mensagem de ajuda da flag, senão o primeiro relato de bug será "pus 3 e não ficou mais rápido".

### 3.5 Isolamento: `cwd` ou `worktree`, declarado por nó

```yaml
nodes:
  - id: builder
    isolation: cwd        # cwd | worktree
```

| Modo | `cwd` do filho | Quando |
|---|---|---|
| `cwd` | `session_dir / node.cwd` | **default.** Obrigatório quando não há repo git. Suficiente enquanto `k=1`. |
| `worktree` | `session_dir / wt / <node>` | **OBRIGATÓRIO** para todo nó que possa executar concorrentemente com outro nó cujas `writes:` toquem a mesma árvore. |

Regra normativa de load: se `--max-concurrency > 1` e existirem dois nós que possam ficar `ready` ao mesmo tempo com `isolation: cwd` e `writes:` sobrepostas, o `up` **DEVE recusar** — no load, não em runtime. É o mesmo princípio de `MVP.md` §2: grafo inválido é erro de compilação.

**Escolhida / descartada.** Isolamento como campo por nó, não como modo global da sessão. Custo: mais um campo no schema e uma regra de validação cruzada. Ganho: um `check` que só roda `pytest` não precisa de worktree, e pagar `git worktree add` por nó de 200 ms é caro em disco e em tempo. Descartado container no v0: vira uma implementação da mesma função de spawn depois, não um refactor.

**Escolhida / descartada.** Worktree do git, não cópia de diretório nem `cp --reflink`. Custo: exige que a sessão rode dentro de um repo git; suja o namespace de branches. Ganho: verificado que dois worktrees com dois branches coexistem no mesmo repo `[V-S]`; é portátil Linux/mac (o `Floors` do Maestri usa clonefile do APFS e por isso é macOS-only); e dá de brinde um `cwd` distinto por nó, o que separa também o diretório de transcripts do CLI (`~/.claude/projects/<hash-do-cwd>`) — ver §3.7-3.

**Escolhida / descartada.** O **orquestrador** cria e remove o worktree. Descartada a flag nativa `claude -w/--worktree` `[V-help]`: se o filho cria, o pai não sabe o caminho, não sabe limpar, e um filho morto por timeout deixa um worktree órfão que ninguém reivindica. Custo: ~15 linhas de wrapper de git. Ganho: o ciclo de vida tem um dono só.

### 3.6 Ciclo de vida do worktree

**Criação** (pai, antes do spawn, dentro do slot):

```
git -C <repo> worktree add "<session_dir>/wt/<node>" -b "orch/<session_id>/<node>"
```

**Remoção** (pai, no `verifying`, depois de o predicado de §3.2 ter sido avaliado e o artefato copiado para `session_dir/artifacts/`):

```
git -C <repo> worktree remove --force "<session_dir>/wt/<node>"
git -C <repo> worktree prune
```

**Se sobrar** — e vai sobrar, porque `SIGKILL` no pai não roda `finally`:

- O worktree órfão fica em `<session_dir>/wt/<node>` e o branch `orch/<session_id>/<node>` fica no repo. **Nenhum dos dois é apagado automaticamente por uma sessão futura.**
- O `up` **DEVE recusar** subir se `<session_dir>/wt/` não estiver vazio, com a mensagem apontando `orch clean --session-dir <dir>`. É a mesma postura da `SPEC.md` §2 ("segundo `up` no mesmo dir falha"), estendida ao lixo de execução.
- O branch é o registro forense: ele carrega o trabalho parcial do nó morto. Apagar sozinho destrói a única evidência de por que a sessão caiu.

**Escolhida / descartada.** Remoção no `verifying`, não no fim da sessão. Custo: o worktree some antes de o humano poder olhar — mitigado porque o branch fica. Ganho: com `k=3` e um grafo de 12 nós, adiar a remoção significa 12 worktrees vivos ao mesmo tempo; em repo grande isso é disco de verdade e um `git status` que rasteja.

**Escolhida / descartada.** Recusar no `up` em vez de limpar sozinho. Custo: um comando a mais para o operador. Ganho: apagar trabalho de terceiros sem pedir é o comportamento que faz alguém perder um dia; a spec inteira é sobre o orquestrador não decidir nada que não foi declarado.

### 3.7 As cinco regras de concorrência — normativas, sem exceção

**1. Spawn em novo process group; kill pelo grupo.**

O filho gera filhos: a tool `Bash` do `claude` roda comandos que são netos do orquestrador. `Popen.kill()` mata o pai e **deixa os netos vivos** — segurando o worktree aberto, o lockfile, e possivelmente escrevendo no artefato depois de o nó ter sido declarado `failed:timeout`.

O orquestrador **DEVE** lançar com `start_new_session=True` e, no timeout, executar `os.killpg(os.getpgid(pid), SIGTERM)` → espera 5 s → `os.killpg(..., SIGKILL)`.

**Por que é não-negociável, e não uma boa prática:** sem isso, `git worktree remove --force` falha (arquivo em uso), a limpeza de §3.6 não roda, o `up` seguinte é recusado, e o sintoma que o operador vê — *"a segunda sessão não sobe"* — não tem relação visível com a causa. Com `k=1` isso acontece raramente; com `k=3` acontece três vezes mais e o diagnóstico fica três vezes mais confuso.

**2. Nós não commitam.**

`git worktree` isola o **working tree**. **Não** isola `.git/index.lock` nem o object store, que são compartilhados entre worktrees. Dois nós commitando ao mesmo tempo produzem `index.lock` disputado e commits parciais.

Regra: o preâmbulo de todo nó **DEVE** declarar que o nó não commita e não faz push. Se um nó precisar commitar, o pai serializa a operação atrás de um lock único (`<repo>/.git/orch-commit.lock`, §3.7-3). O caminho preferido é o pai commitar, no fim, o que os contratos de escrita autorizaram.

**3. Lock por artefato, via `fcntl`, nunca `flock(1)`.**

Todo artefato reivindicado por mais de um caminho de escrita — e o commit lock acima — passa por `fcntl.flock` sobre `<artefato>.lock`.

**NÃO PODE** usar o binário `flock(1)`: ele não existe no macOS de fábrica, e o produto roda em Linux **e** mac. A mesma regra vale para `timeout(1)` (§4.2): o timeout é implementado no processo pai. **Regra geral desta spec: se o recurso existe na biblioteca padrão, não terceirizar para binário do sistema.**

**4. Um log por nó, sempre.**

`session_dir/logs/<node>.jsonl` e `session_dir/logs/<node>.err`. **NÃO PODE** existir stdout compartilhado entre nós concorrentes: o JSONL de dois filhos intercalado não é parseável, e a linha `result` — que é a última de cada stream `[V-I]` — deixa de ser localizável.

**5. `events.jsonl` é escrito só pelo pai, e nunca lido para decidir.**

Uma linha por transição, append-only, com `ts`, `node`, `from_state`, `to_state`, `rc`, `failure`, `cost_units`, `turns`, `artifact`, `reason`. Escritor único (o pai) resolve a ordenação sem lock. Leitor: humano e `orch watch`.

O runtime **NÃO PODE** ler `events.jsonl` para tomar decisão — a fonte de verdade de estado é `state.json`, também single-writer (`MVP.md` §1.4). Duas fontes de verdade sob concorrência divergem, e divergem exatamente no cenário que ninguém consegue reproduzir.

### 3.8 Retomada: no nível do nó, não no da sessão

**Fica de pé da `SPEC.md` §2:** *"Sem resume no v0"* — **no nível da sessão**. Um `up` interrompido não é retomado; o `session_dir` fica como evidência e a próxima sessão é nova.

**Emenda, no nível do nó:** cada nó recebe um identificador de sessão de CLI determinístico:

```
NODE_UUID := uuid5(NAMESPACE_ORCH, session_id + ":" + node_id)
```

- Primeira execução do nó: `--session-id "$NODE_UUID"`.
- `retry:semantic`: `--resume "$NODE_UUID"` + nudge curto.

**Escolhida / descartada.** UUID derivado, não armazenado. Custo: nenhum estado novo — é uma função pura de dados que já estão em `state.json`. Ganho: verificado que `--session-id` seguido de `--resume` sob `-p` retoma de verdade, com o filho lembrando o turno anterior e o `session_id` preservado `[V-L]`; o retry custa o nudge em vez do contexto inteiro. Descartado `--continue`: depende de "a conversa mais recente no diretório atual" — estado implícito, e sob concorrência isso é uma corrida entre nós que compartilham cwd.

**Escolhida / descartada.** Derivar o UUID **também** protege contra a herança de env (§4.3): verificado que um filho reusou o `session_id` do processo pai porque `CLAUDE_CODE_SESSION_ID` estava no ambiente `[V-R]`. Com `k=3`, três nós herdando o mesmo id é transcript entrelaçado e um `--resume` que retoma a conversa errada. Custo: zero. Ganho: fecha um bug que só aparece quando o orquestrador é lançado de dentro de um Claude Code — que é o caso de quem o está construindo.

### 3.9 Paralelismo que gera valor — o ganho, o custo, e o ponto em que vira prejuízo

Esta subseção existe porque "rodar vários agentes" não é ganho por si. O veredito (`MVP.md` §8) tem cinco famílias de métrica; **o paralelismo compra exatamente uma, e só uma.**

**O ganho, com aritmética.**

Seja `T_i` o tempo de parede do nó `i`, `Σ` a soma e `CP` o caminho crítico do DAG. Com concorrência `k`, o tempo de parede da sessão tem piso `max(CP, Σ/k)`.

| Grafo | Σ | CP | `k=3` | Ganho real |
|---|---|---|---|---|
| `graphs/v0.yaml` (`scout → builder`) | `2t` | `2t` | `2t` | **1,00× — zero, para qualquer `k`** |
| fanout×3 + join, join = t | `3t + t` | `t + t` | `2t` | **2,00×** |
| fanout×3 + join, join = t/3 | `3,33t` | `1,33t` | `1,33t` | **2,50×** |

O teto realista de um fanout de largura 3 é **2 a 2,5×**, não 3×, porque o `join` é serial e paga preço cheio. O dado verificado que sustenta que a banda paralela **existe**: 3× `claude -p` concorrentes em cwds distintos, 3 artefatos corretos, **10 s de parede para os três** `[V-M]`.

**Ressalva de honestidade:** não medi na mesma máquina a serialização equivalente daqueles três nós. O speedup da tabela é um modelo (Amdahl sobre o DAG) alimentado por um ponto medido, não uma medição de ponta a ponta. `wall_seconds` do veredito é a medida real, e ela **DEVE** ser colhida com as 5 seeds por célula que o `MVP.md` §8 exige antes de qualquer afirmação de ganho.

**A métrica que se move, e as que não se movem.**

| Métrica do veredito | Efeito de `k=3` |
|---|---|
| `wall_seconds` | **melhora** — é o ganho inteiro |
| `gate_first_pass`, `rework`, `write_violations`, `handoff_valid` | **não se movem** — são propriedades do grafo, não do escalonador |
| `cost_ratio` (`log_bytes`) | **piora um pouco** — ver abaixo |
| `stop_reason` | ganha um valor novo: `window_sleep` |

**O custo que sobe junto.**

1. **Contexto fixo duplicado.** Num prompt trivial, o `result` reportou `cache_creation_input_tokens: 7566` e `cache_read_input_tokens: 30380` `[V-C]` — cerca de **38k tokens de contexto antes de a tarefa começar**. Esse piso é por nó. Três nós em paralelo pagam três pisos, e nós concorrentes distintos têm menos chance de reaproveitar cache de prefixo quente que uma cadeia serial que reincide no mesmo prefixo `[I]`. O total de trabalho não muda; o overhead fixo, multiplicado por nó, muda.
2. **Taxa de consumo da janela.** O custo total de quota é o mesmo (os mesmos nós rodam), mas a **taxa** é `k` vezes maior. É isso que aproxima a sessão do gate de §4.7 em tempo de parede menor.
3. **Superfície de falha concorrente.** As cinco regras de §3.7 passam de higiene a requisito. Um zumbi que com `k=1` era raro passa a ser rotina.

**Os três pontos em que aumentar `k` piora a sessão** — nesta ordem, porque é a ordem em que aparecem:

1. **`k` acima da largura do grafo: ganho exatamente zero, custo maior que zero.** O conjunto pronto nunca tem `k` elementos; o escalonador roda o laço à toa. É o caso do `graphs/v0.yaml`, e é o primeiro relatório de bug que vai chegar.
2. **`k` que faz a sessão cruzar `utilization > 0,85`: você paga o custo de `k` nós e recebe a velocidade de 1.** O gate degrada a concorrência para 1 (§4.7) e os pisos de contexto já foram pagos. **Este é o ponto de virada real, e ele é assimétrico e brutal:** o ganho do paralelismo se mede em minutos de parede; o sono da janela se mede em horas — o `resetsAt` observado no teste é um epoch de janela de 5 h `[V-J]`. Uma sessão que dorme uma vez perdeu mais tempo do que o paralelismo inteiro economizou.
3. **`k > 3`: degradação de qualidade, não só de custo.** O `MVP.md` §6 já registra: `1→3` ganha, `3→5` é marginal ou negativo, e paralelismo estrutural agressivo derrubou acurácia de 28% para 25% (2608.05791). O teto 3 no schema não é timidez de infraestrutura — é o ponto onde a literatura diz que o retorno inverte.

**A regra operacional que sai daqui, e que DEVE aparecer na saída do `up`:** paralelismo só gera valor quando a largura do grafo é ≥2 **e** a sessão cabe na janela sem dormir. As duas condições são verificáveis antes de subir o primeiro nó — a primeira no load, a segunda lendo a `utilization` do `orch doctor`. O `up` **DEVE** avisar, não recusar, quando `--max-concurrency > largura_do_grafo`.

---

## §4 — Como invoca os CLIs

**Fica de pé, inteiro, da `SPEC.md` §4:** binário no `PATH` (ou `CLAUDE_BIN`), auth pelo login da assinatura, **proibido** `ANTHROPIC_API_KEY`, SDK `anthropic` e HTTP para `api.anthropic.com`; o `up` aborta antes de subir nó se o preflight falhar, com mensagem que aponta para o login da Pro e não para gerar chave.

O que esta seção acrescenta: o comando exato, a allowlist de ambiente, a proibição do `--bare`, os três adapters, e o gate que impede a sessão de se matar.

### 4.1 O contrato do adapter — `Outcome` como único acoplamento

```
preflight()                         -> Ok | Reason        # uma vez por up, cacheado em state.json
build(node, session, retry_ctx)     -> Spawn{argv, cwd, env, stdin_bytes, timeout_s}
parse(rc, stdout_path, stderr_path) -> Outcome
```

```
Outcome:
  ok          bool     # a conjunção de quatro de §3.2
  rc          int
  failure     none | transport | permission | budget | semantic | timeout | parse
  denials     [{tool_name, tool_input}]
  turns       int  | null
  cost_units  float| null      # unidade de orçamento, NÃO dinheiro (§4.8-4)
  session_ref str  | null      # alimenta o --resume do retry semântico
  rate_limit  {five_hour_util, seven_day_util, resets_at} | null
  degraded    bool             # autocompact disparou (§4.8-3)
  text        str              # última mensagem do agente, só para o log humano
```

**Escolhida / descartada.** O `Outcome` é definido **antes** dos adapters e é o **único** acoplamento entre eles. Custo: campos `null` no `exec` e no `cursor-agent`, e a disciplina de não vazar detalhe de CLI para o escalonador. Ganho: o escalonador de §3.3 não sabe qual binário rodou — e é o que permite escrever `claude.py` e `cursor.py` em paralelo, por pessoas diferentes, sem negociar contrato no meio. Descartado um adapter único com `if binary == "claude"`: é a ramificação que vira dez ramificações no terceiro CLI.

**Regra normativa:** o `preflight()` roda **uma vez por `up`**, e o resultado vai para `state.json`. **NÃO PODE** rodar por nó — com `k=3` e um grafo de 12 nós isso são 12 `claude auth status` sem necessidade, e a latência entra no caminho crítico de cada slot.

### 4.2 Adapter `claude` — comando exato

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

Flag a flag, com a marca de verificação:

| Flag | Por quê | Marca |
|---|---|---|
| `-p` | headless. O processo sai, e sair é um fato — nada de heurística de fim-de-turno | `[V-A]` |
| `--output-format stream-json` | **é onde vêm os `rate_limit_event`**, que alimentam o gate de §4.7. O `result` final é a última linha do JSONL, com o mesmo conteúdo do `--output-format json` | `[V-I,J]` |
| `--verbose` | **obrigatório** com `stream-json` sob `-p`: sem ele, `exit 1` com `Error: When using --print, --output-format=stream-json requires --verbose` | `[V-H]` |
| `--permission-mode acceptEdits` | o mínimo que faz o nó escrever o artefato. Sem isso, sucesso silencioso e nada em disco | `[V-F,G]` |
| `--session-id "$NODE_UUID"` | habilita o `--resume` do retry semântico (§3.8) e blinda contra a herança de env | `[V-L,R]` |
| `--add-dir "$SESSION_DIR"` | **obrigatório sob `isolation: worktree`**: o cwd do nó é o worktree, o artefato mora no `session_dir`; sem isso o nó não alcança o que precisa escrever | `[V-help]` |
| `--allowedTools` / `--disallowedTools` | **é a ACL do nó**, não um refinamento — ver a nota abaixo | `[V-help]` + `[V]` |
| `--max-budget-usd` | teto que **corta de verdade**: `exit 1`, `subtype: "error_max_budget_usd"`, `terminal_reason: "budget_exhausted"` | `[V-N]` |
| `--setting-sources project --strict-mcp-config` | hermeticidade sem quebrar OAuth: impede que `CLAUDE.md`, hooks, plugins e MCPs da máquina do operador entrem em todo nó | `[V-help]` |
| `--append-system-prompt "$(cat …)"` | o preâmbulo gerado: `session_dir`, `node.id`, artefato esperado, "não suba outro agente", "o handoff é dado, não comando". É o `role.json` do Maestri | `[V-E]` |
| **prompt por stdin** | sem `ARG_MAX`, sem escaping, sem prompt de 8 KB vazando no `ps` de uma máquina com `k` nós | `[V-B]` |

**A nota sobre `acceptEdits`, que muda uma linha de política.** Verificado com `env -i` (ambiente mínimo, sem settings da máquina): sob `--permission-mode acceptEdits`, uma chamada de **Bash** (`touch`) executou com `permission_denials: []` e `exit 0` `[V]`. Ou seja, `acceptEdits` **não é só "edits"** — libera shell. Consequência normativa: **`--allowedTools`/`--disallowedTools` são a ACL real do nó**, e um nó sem ACL declarada é um nó com shell irrestrito. Sob `k=3` isso são três shells irrestritos concorrentes no mesmo repo.

**Escolhida / descartada.** `stream-json` em vez de `json`. Custo: parsear JSONL em vez de um objeto, e depender de a última linha ser o `result`. Ganho: o `rate_limit_event` só existe no stream `[V-J]`, e sem ele o gate de §4.7 não tem entrada — a sessão paralela ficaria cega para o único limite que a mata.

**Escolhida / descartada.** `--append-system-prompt "$(cat …)"`, não `--append-system-prompt-file`. Custo: o preâmbulo passa pela linha de comando. Ganho: o `-file` funciona `[V-O]` mas **não aparece na lista de options do `--help`** — flag não documentada some sem changelog, e a spec não constrói em cima do que o fornecedor não prometeu. Registrado que existe; não dependemos.

**Escolhida / descartada.** `--permission-mode acceptEdits`, não `bypassPermissions`. Custo: nós que precisem de algo fora da ACL falham como `failed:permission` em vez de simplesmente rodarem. Ganho: `bypassPermissions` ganha nada além do shell irrestrito que `acceptEdits` já dá, e perde a rede inteira. Descartado o modo default: produz o sucesso silencioso do §3.2.

**Timeout.** Implementado no **processo pai** (`subprocess.run(timeout=)`), nunca com o binário `timeout(1)` — que não existe no macOS de fábrica. Ao estourar: `killpg` (§3.7-1), estado `failed:timeout`.

**Considerado, não adotado no v0:** `--fallback-model` (`--print` only `[V-help]`). Ganho: um nó sobrevive a overload em vez de virar `retry:transport`. Custo: o nó roda num modelo mais fraco e o veredito compara maçã com laranja sem avisar. Se entrar, o `Outcome` **DEVE** gravar qual modelo serviu — a chave existe em `modelUsage` `[V-C]`.

### 4.3 Ambiente: allowlist — emenda à `SPEC.md` §4

A `SPEC.md` §4 diz *"env herda o do orquestrador menos qualquer `ANTHROPIC_API_KEY`"*. **Verificado que isso é metade do problema.**

Um `claude` filho herda `CLAUDECODE`, `CLAUDE_CODE_SESSION_ID`, `CLAUDE_CODE_ENTRYPOINT`, `ANTHROPIC_BASE_URL` e cerca de quarenta outras variáveis `CLAUDE_*` `[V-R]`. Num dos testes o filho **reusou o `session_id` do processo pai** por causa disso `[V-I,R]`. Com `k=3`, três nós herdando o mesmo identificador é transcript entrelaçado e um `--resume` que retoma a conversa errada — e o sintoma aparece como "o agente ficou confuso", não como "bug de ambiente".

**Emenda: o ambiente do filho é montado por allowlist, não por subtração.**

```
PASSA:    HOME PATH USER SHELL LANG LC_* TZ TMPDIR
          TERM=dumb                       (forçado, não herdado)
          SSH_AUTH_SOCK                   (só se o nó declarar que precisa de git via ssh)
          ORCH_SESSION_DIR ORCH_NODE_ID ORCH_ARTIFACT   (nossos, prefixados)

BLOQUEIA (e o adapter DEVE falhar alto se aparecerem no comando montado):
          ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL
          CLAUDECODE CLAUDE_CODE_* CLAUDE_* CURSOR_*
```

**Escolhida / descartada.** Allowlist. Custo: toda variável nova que um nó legitimamente precisar tem que ser declarada — e alguém vai perder vinte minutos descobrindo isso na primeira vez. Ganho: uma denylist é uma lista que fica desatualizada a cada release do CLI; a allowlist erra para o lado de o nó não subir, que é o lado barato.

`TERM=dumb` é forçado de propósito: sem TTY o CLI já vai para o caminho não-interativo `[V-help]`, e `dumb` remove resíduo de ANSI do log — que com `k` nós escrevendo `k` arquivos JSONL é a diferença entre um log parseável e um log com escape sequences no meio do JSON.

### 4.4 `--bare` é proibido

O adapter **NÃO PODE** emitir `--bare`, e o `build()` **DEVE** falhar se a flag aparecer numa configuração de nó.

Motivo, do próprio `--help` `[V-help]`: com `--bare`, *"Anthropic auth is strictly `ANTHROPIC_API_KEY` or apiKeyHelper via `--settings` (OAuth and keychain are never read)"*. É a flag que mais **parece** o modo hermético que a spec quer, e é exatamente a que viola a restrição dura do produto — zero API key, auth pela assinatura.

O knob hermético compatível com a Pro é **`--safe-mode`** (verificado: `exit 0`, auth OAuth intacta `[V-P]`) somado a `--setting-sources` e `--strict-mcp-config`.

**Escolhida / descartada.** Proibição por escrito no adapter, com falha no `build()`, em vez de uma nota na documentação. Custo: uma verificação a mais. Ganho: a restrição de zero API key é a que define o produto; ela não pode depender de alguém lembrar de não usar uma flag que se anuncia como "minimal mode".

### 4.5 Adapter `cursor-agent` — não verificado

```bash
cursor-agent -p --output-format stream-json --force \
  --model "$NODE_MODEL" --workspace "$NODE_CWD" "$(cat prompt.md)"
```

**Tudo nesta subseção é `[D]` — lido em `cursor.com/docs/cli/*`, nada executado.** O binário não estava presente na máquina de verificação, e a spec **DEVE** carregar essa distinção: no lado do `claude` eu sei; aqui eu li.

- Eventos do `stream-json`: `system`, `assistant`, `tool_call{started|completed}`, `result{duration_ms}` `[D]` — schema diferente do Claude, normalizado no `Outcome`.
- `--force`/`--yolo` é *allow unless explicitly denied* `[D]` — **mais grosso** que `acceptEdits`, e sem equivalente documentado a `permission_denials`. Consequência normativa: **para o `cursor-agent`, o predicado de artefato de §3.2 não é redundância, é a única defesa** — a conjunção degrada de quatro para duas condições (`rc == 0 ∧ verify(artefato)`).
- Sem contrato de exit code documentado `[D]` → o timeout do pai é obrigatório, não opcional.
- Bug conhecido de `-p` pendurando indefinidamente (fórum oficial, Cursor 2.4.21–22, Agent CLI 2026.01.28+, causa apontada como retries TCP silenciosos de 10–15 s; moderador reporta correção em versões recentes) `[D]` → timeout generoso (≥60 s antes de considerar hang) e mensagem de erro que **cite o bug por nome**, senão o operador culpa o orquestrador.
- Sem telemetria comparável: o `Outcome` sai com `turns=null`, `cost_units=null`. Sob paralelismo isso significa que **um nó de Cursor não participa do gate de orçamento de §4.7** — ele consome relógio e nada mais, e o `state.json` **DEVE** registrar essa lacuna em vez de fingir paridade.

**Pré-condição normativa:** instalar o binário e **repetir os 20 testes** do memorial antes de escrever este adapter. Nenhuma linha do `cursor.py` deve ser escrita contra documentação.

### 4.6 Adapter `exec` — o genérico

```yaml
- id: reviewer
  adapter: exec
  cmd: ["codex", "exec", "--cd", "{cwd}", "-"]   # placeholders: {cwd} {artifact} {session_dir} {prompt_file}
  stdin: "{prompt_file}"
  parse: exit_code_only
  timeout: 900
```

`Outcome` degradado: `ok = (rc == 0) && verify(artefato)`; `turns`, `cost_units`, `denials`, `rate_limit` e `session_ref` são `null`. Sem `session_ref`, o **retry semântico é desabilitado** para este adapter (§3.1) — não emulado com uma segunda execução do zero.

**Escolhida / descartada.** Três adapters, um `Outcome`. Custo do `exec`: ~30 linhas e a perda de toda telemetria, o que o exclui do gate de orçamento e o torna um nó cego dentro de uma sessão paralela. Ganho: **é a apólice de seguro do projeto.** Torna o orquestrador agent-agnostic no sentido do Maestri sem precisar de PTY, e se a assinatura fechar a porta para automação (`MVP.md` §10 R1), o projeto aponta para `codex`, `opencode`, `aider` ou um `.sh` no mesmo dia. Não ter o `exec` é apostar o repositório inteiro numa cláusula de terceiro.

### 4.7 O gate de orçamento e de janela — o mecanismo que impede a sessão de se matar

Com `k=1`, isto é precaução. **Com `k=3`, isto é o mecanismo que impede a sessão de se matar** — três nós enchem a janela três vezes mais rápido, e a sessão que estoura não falha com elegância: ela dorme horas ou é cortada no meio de um fanout, deixando `k` worktrees e `k` artefatos parciais.

**Três eixos, todos observáveis, todos lidos do mesmo `Outcome`.**

| Eixo | Como | Marca |
|---|---|---|
| **Custo por nó** | `--max-budget-usd "$NODE_BUDGET"`. Corta de verdade: `exit 1`, `subtype: "error_max_budget_usd"`, `terminal_reason: "budget_exhausted"` → classe `failed:budget`, que **nunca** retenta | `[V-N]` |
| **Custo por sessão** | acumula `result.total_cost_usd` em `state.json`. O escalonador **NÃO PODE** subir um nó se `acumulado + teto_do_nó > session_cap` — a verificação é **antes** do spawn, não depois | `[V-C]` |
| **Relógio** | `timeout_s` por nó no processo pai + `wall_seconds` de sessão. Estourou → `killpg` (§3.7-1) | — |

**A política de janela de assinatura, normativa.**

O stream emite `rate_limit_event` com `rate_limit_info{status, resetsAt, rateLimitType, overageStatus, isUsingOverage, unifiedWindows:{five_hour:{utilization, resetsAt}, seven_day:{utilization, resetsAt}}}` `[V-J]`. O adapter **DEVE** extrair isso para `Outcome.rate_limit`, e o escalonador **DEVE** aplicar, antes de preencher cada slot:

```
util := max(five_hour.utilization, seven_day.utilization)   # do último Outcome com rate_limit ≠ null

util > 0,85          → concorrência efetiva degrada para 1
                       (não mata nós em voo; para de abrir slots novos)
util > 0,95          → DORME até resetsAt (pausa, não falha)
                       stop_reason parcial: window_sleep, com o epoch no log
status != "allowed"  → PARA a sessão, com o motivo literal do campo
sempre               → NUNCA retry cego em 429
```

**Escolhida / descartada.** Gate por `utilization` observada, degradando antes de estourar. Custo: a sessão pode ficar mais lenta sem que o operador tenha pedido, e a decisão depende de um campo que a Anthropic não prometeu manter — daí o `orch doctor` (`MVP.md` §2) afirmar o schema. Ganho: transforma "vai que estoura o limite" em política executável, e é o que separa esta emenda de "rodar `claude -p` num `for` loop". Descartado o retry cego em 429: é o padrão de tráfego que aciona detecção de abuso, e é a diferença entre um cliente automatizado bem-comportado e um que pede para ser bloqueado.

**Escolhida / descartada.** Dormir até `resetsAt` em vez de falhar a sessão. Custo: um `up` pode ficar parado horas — e o operador **DEVE** ser avisado no stdout com o horário de retorno, senão parece travado. Ganho: o trabalho já feito não é perdido; os artefatos e os worktrees continuam válidos. Descartado abortar: com `k=3` e um fanout no meio, abortar deixa três ramos parciais e nenhum join — o pior estado possível para retomar à mão.

**Escolhida / descartada.** Verificar o orçamento de sessão **antes** do spawn. Custo: um nó cujo teto é folgado pode ser bloqueado por um acumulado alto mesmo que fosse gastar pouco. Ganho: verificar depois é descobrir o estouro com o dinheiro já gasto; sob `k=3` são três estouros simultâneos.

**Regra de precedência:** o gate de janela tem prioridade sobre `--max-concurrency`. A concorrência efetiva é `min(--max-concurrency, teto_do_grafo, teto_do_gate)`, avaliada **a cada preenchimento de slot**, não uma vez no início.

### 4.8 Onde cada CLI trai a expectativa

Quatro do `claude`, todos verificados, e todos com remédio normativo:

1. **`exit 0` com o trabalho não feito** — denial silencioso `[V-F]`. Remédio: a conjunção de quatro de §3.2, e o erro de `failed:permission` imprimindo o `tool_name` negado.
2. **`--output-format text` escreve a mensagem de erro no STDOUT** `[V-D]`. Quem fizer `if rc == 0: artefato = stdout` grava a mensagem de erro como artefato. Remédio: o adapter **NÃO PODE** parsear `text`; só `stream-json`.
3. **Autocompact silencioso.** `autocompact_state{enabled, effective_window, threshold, enforced}` aparece no stream `[V-I]`: um nó longo é comprimido no meio do caminho e a decisão sai de um contexto que ninguém viu. Remédio: logar o evento e marcar `Outcome.degraded = true`. Um nó que dispara autocompact é sintoma de nó grande demais — o remédio de desenho é **dividir o nó**, não aumentar a janela.
4. **`total_cost_usd` é preço de tabela** — `costBasis: "list"`, `provider: "firstParty"` `[V-C]`. Numa assinatura Pro **não é o que foi cobrado**. Remédio: o campo do `Outcome` chama-se `cost_units`, e a saída do `up` **NÃO PODE** imprimir "você gastou $X".

Do `cursor-agent` `[D]`: exit code sem contrato, `-p` com histórico de hang, e ausência de `permission_denials` — os três já tratados em §4.5.

Do `exec`: nenhuma telemetria. A traição é a expectativa de paridade — remédio em §4.6.

---

## Apêndice desta frente — o que ainda não foi verificado e bloqueia parte desta spec

1. **Comportamento sob rate limit real.** Só observei `status: "allowed"` com `utilization` 0,39 (5 h) e 0,48 (7 d) `[V-J]`. Não sei o que o `result` traz quando a janela fecha: `is_error`? qual `subtype`? Enquanto isso não for verificado, o ramo `status != "allowed"` de §4.7 é desenho, não fato. **Bloqueia:** a mensagem de erro do `stop_reason: window_limit`.
2. **`cursor-agent` inteiro** — §4.5 é `[D]`. **Bloqueia:** escrever `cursor.py`.
3. **Reaproveitamento de cache de prefixo entre nós concorrentes** — a afirmação de §3.9 sobre pisos de contexto duplicados é `[I]`, sustentada pelos nomes dos campos (`cache_creation_input_tokens` vs `cache_read_input_tokens` `[V-C]`), não por medição. **Bloqueia:** qualquer número de `cost_ratio` atribuído ao paralelismo.
4. **`--input-format stream-json`** `[V-help]`, não executado — é o caminho para responder a um nó sem PTY, e portanto para o `orch say` do `MVP.md` §4. **Bloqueia:** `orch say` contra um nó em execução.
5. **A serialização equivalente do teste M.** Medi 10 s para 3 nós concorrentes `[V-M]`; não medi os mesmos 3 em série na mesma máquina. **Bloqueia:** publicar qualquer número de speedup que não venha do `wall_seconds` do veredito, com 5 seeds.

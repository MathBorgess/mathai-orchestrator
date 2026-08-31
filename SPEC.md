# Spec — orquestrador v1 (paralelo)

**Issue:** [MAT-96](https://linear.app/borgesmathai/issue/MAT-96) (spec) · [MAT-97](https://linear.app/borgesmathai/issue/MAT-97) (implementa)
**Substitui:** a v0 serial, arquivada em [`research/spec-v1-drafts/SPEC-v0-original.md`](research/spec-v1-drafts/SPEC-v0-original.md).
**Repo:** este. Privado. Fora do vault. Não misturar com `mathai-harness`.
**Pronto desta sessão:** este arquivo + [`graphs/v1.yaml`](graphs/v1.yaml). Claude implementa na MAT-97.
**Fora:** wiki, hitl, SDK Anthropic, chave de API, daemon, PTY como runtime.

Toda escolha abaixo traz o descarte. Decisão sem alternativa não entra.

A **mudança de fundo contra a v0**: onde a v0 dizia *"serial no v0, um nó running por vez… paralelo é segundo grafo, não esta sessão"*, o v1 traz o paralelismo para dentro, com travas. E como o escopo não pode crescer nos dois sentidos, quatro coisas saem no lugar (§6).

---

## 0. Como esta spec foi escrita, e as arbitragens

Quatro frentes trabalharam em paralelo, com escritas disjuntas, e convergiram num `join`. É o mesmo contrato que a spec declara para os nós — aplicado a quem a escreveu. As entregas íntegras estão em [`research/spec-v1-drafts/`](research/spec-v1-drafts/); esta spec é a integração, e onde as frentes discordaram a decisão está registrada aqui, não escondida.

| # | Choque | Decisão | Descarte, com o custo |
|---|---|---|---|
| 1 | Superfície ao vivo: cortar (frente D) ou promover (frente C) | **Fica, read-only.** `orch top`/`ps`/`watch` leem `state.json` + `events.jsonl` **fora do processo do `up`**. Zero a zero na conta de escopo, porque a metade interativa sai | Descartado cortar tudo: o produto perde a única forma de responder "está gerando valor?" **enquanto** roda, e o `tail -f events.jsonl` não distingue avanço de repetição |
| 2 | Metade interativa (`next`, `say`, ASK, `NEEDS_YOU`) | **Fora, por impossibilidade técnica, não por gosto.** Um nó `claude -p` headless não tem TTY e não pergunta no meio do turno; a fila de ASK do desenho da frente C pressupõe um canal que o v1 não tem | Descartado emular: exigiria `--input-format stream-json`, que não foi verificado. Nomeado para quando for |
| 3 | `--max-concurrency`: default 1 (frentes A/B) ou `auto` (frente D) | **`auto`**: `min(largura do grafo, 3)`, degradando por `utilization`. Paralelismo que exige flag para existir não existe | Descartado default 1: mitigação de ToS mais forte, e transforma a feature principal em segredo. O gate de §4.6 é a mitigação real, e ela é executável |
| 4 | Baseline: primeiro e serial (frente A) ou slot reservado concorrente (frente D) | **Primeiro e serial.** O número-manchete do veredito é tempo de parede; baseline concorrente disputa a mesma janela e contamina exatamente a métrica que decide | Descartado o slot concorrente: fazia o paralelismo pagar o baseline (~0 de parede em vez de ~2×). Custo aceito: a sessão custa ~2× de relógio, e a primeira coisa que o operador vê é o braço que ele não quer ver |
| 5 | Ciclo `check_failed` → produtor, com `max_repeats` (frente A) ou DAG estrito (frente D) | **DAG estrito.** `check_failed` é aresta terminal | Descartado o ciclo limitado: em serial um loop custa o orçamento de um nó; com concorrência 3, custa o de três. Não se adiciona ciclo na mesma rodada em que se adiciona concorrência. Custo: nenhuma recuperação automática |
| 6 | Retry semântico com `--resume` (frente B) ou sem (frente D) | **Fora.** `rc=0`, sem denials, artefato inválido ⇒ `failed:verify` | Descartado manter: é a segunda fonte de não-determinismo **dentro do instrumento de medida**. Se um nó precisou de segunda tentativa, isso é o dado. Custo real: sessões morrem por nó que acertaria na segunda. `transport` continua com backoff |
| 7 | `join` com ramo faltando: nunca (frente A) ou `min_branches: 2` (frente D) | **Nunca.** Toda instância `done`, ou a sessão falha | Descartado `min_branches`: com 3 ramos e p(falha)=0,1 por ramo, exigir 3/3 mata ~27% das sessões por um ramo. Custo aceito e explícito: um `stop_reached` que às vezes significa 3/3 e às vezes 2/3 torna a comparação sem sentido, e a comparação é o produto |

---

## 1. Modelo do grafo

| Conceito | É | Não é |
|---|---|---|
| **Nó** | uma unidade de trabalho com contrato de escrita: `agent`, `check`, `fanout` ou `join` | uma thread dentro do Claude Code |
| **Aresta** | um handoff: `from`, `to`, `on` (predicado), e o formato quando há artefato | uma chamada de API, um bus |
| **Sessão** | uma instância viva de **um** grafo, num diretório. Sessão = time | um chat, um PR, um worktree do vault |
| **Estado** | o ledger em `state.json`: grafo + status + artefatos com hash + orçamento + violações | histórico de tokens, transcript completo |
| **Raia** | uma instância de `fanout`, com id derivado `<fanout>.<slot>` | um agente com nome próprio |

Identificadores são strings `^[a-z][a-z0-9_-]{0,31}$`. O arquivo canônico é YAML (`graphs/*.yaml`).

### 1.1 Tipos de nó

**`agent`** — a única coisa cara. Campos: `id`, `type`, `adapter` (`claude` default), `prompt`, `cwd`, `reads`, `writes` (**obrigatório, não-vazio**), `iters`, `budget_units`, `timeout_seconds` (**obrigatório**), `tools: {allow, deny}`, `model`.

`reads` é **informativo**, e a spec diz isso na cara: nenhum CLI dá sandbox de leitura, e prometer isolamento que não existe é pior que não prometer. Ele entra no preâmbulo gerado e no cálculo de `orphan_writes`. `writes` é o contrato de verdade, verificado por diff de árvore.

**`check`** — comando determinístico, **zero LLM**. Campos: `id`, `type`, `run` (**lista argv, executada sem shell**), `cwd`, `timeout_seconds`. Tem `writes: []` implícito e imutável: um verificador que escreve não é verificador. É o único tipo que pode aparecer no `stop`.

> **Escolhida / descartada.** `run` como argv sem shell. Custo: um gate com pipe vira um script de verdade em `bin/`. Ganho: o grafo é dado versionado que o loader lê; permitir shell aqui é permitir que um grafo alterado execute qualquer coisa com o ambiente do orquestrador — e o `handoff.md` já é escrito por um agente que leu arquivos do repo. Descartado `run` como string: é a superfície de injeção mais barata do sistema.

**`fanout`** — primeira classe, e a **forma única** de declarar paralelismo. Campos: `id`, `type`, `max` (**2 ≤ max ≤ 3**, teto duro de schema), `rationale` (**obrigatório, ≥3 linhas**), `template` (bloco `agent` sem `id`/`reads`/`writes`), `partition` (lista de `{slot, reads, writes}`).

Instâncias têm id **derivado**, nunca declarado: `build.a`, `build.b`, `build.c`. O `up` **não lê** o conteúdo de `rationale` — exige que exista e o copia para o veredito, ao lado de `orphan_writes` e `null_writes` daquele fanout. Um fan-out que não produziu nada é julgado ao lado da justificativa que o criou. Fingir que o loader valida a justificativa seria teatro.

> **Escolhida / descartada.** Piso 2 e teto 3, não configurável. Custo: um "fanout de 1" precisa ser reescrito como `agent`. Ganho: fanout de 1 é o que sobra quando alguém remove instâncias para debugar e esquece de voltar — ele carrega o custo de schema do paralelismo sem nenhum paralelismo. Descartado teto configurável: um teto que se configura não é teto.

**`join`** — um `agent` com duas obrigações a mais: `from` (id de exatamente um `fanout`) e `owns` (**todos** os pares não-ordenados de slots, em ordem lexicográfica: com `a,b,c` ⇒ `[a-b, a-c, b-c]`). É o **único** ponto de convergência. Ramos não se comunicam.

> **Escolhida / descartada.** `owns` conferido por contagem, não por texto livre. Custo: burocracia visível no YAML. Ganho: decompor cria interfaces, e a interface sem dono é onde o time falha em silêncio — medido, um cálculo de 8 passos com 1 por agente falhou **10/10 runs** numa convenção que ficava na fronteira entre dois donos, discutida todo run e nunca resolvida. `owns` não conserta a discussão; obriga o `join` a saber que ela é dele. Descartado deixar a fronteira implícita no prompt: prompt não é validável e o veredito não consegue contá-lo.

### 1.2 Predicados de aresta

| `on` | Campos | Dispara quando |
|---|---|---|
| `artifact_exists` | `artifact` | o arquivo existe e `from` está `done` |
| `artifact_valid` | `artifact` | o `verify` declarado do artefato sai 0 e `from` está `done` |
| `check_passed` | `check` | o `check` nomeado saiu 0 |
| `check_failed` | `check` | o `check` nomeado saiu ≠0 — **aresta terminal**, leva a `failed` |
| `always` | — | **todas** as instâncias do `fanout` de origem estão `done` |

`always` só existe em aresta `fanout` → seu `join`. Toda aresta que carrega `artifact` carrega também `handoff: structured | prose`; aresta sem artefato não pode declarar `handoff`, porque o formato pertence ao artefato.

> **Escolhida / descartada.** `handoff` por aresta, não configuração global. Ganho: handoff tipado dá **+12,7 pp** e **+8,7 pp** em duas famílias de tarefa e **regride −14,6 pp** onde a tarefa exige iteração adaptativa; por padrão: agregação +6,7, iterate −7,0, conditional −18,2. Não existe resposta global correta, e o schema sozinho não faz nada sem o preâmbulo de leitura injetado no receptor. Descartado sempre-estruturado: perde nos ramos exploratórios, que é onde o fanout vive.

> **Escolhida / descartada.** `always` fecha só quando **toda** instância está `done`; ramo `failed` ⇒ sessão `failed`, e o `join` não roda com sobreviventes. É a arbitragem 7. Custo escrito por extenso: um ramo instável mata uma sessão que já tinha 2/3 do trabalho pronto, e o operador reroda inteiro. Ganho: `stop_reached` significa uma coisa só.

### 1.3 Quando um trabalho vira `fanout`, e quando é um nó só

Responda as três por escrito, no `rationale`, **antes** de declarar o fanout. As três precisam passar.

**P1 — o handoff cabe numa página?** Escreva à mão o handoff que **uma** instância receberia. Se para trabalhar ela precisa carregar estado exato de quem veio antes — caminho absoluto, hash, ID gerado, saída literal de comando, número de linha —, separar não isola contexto: obriga o upstream a serializar tudo que sabia e o downstream a reconstruir. É um nó só.

**P2 — as escritas particionam de verdade?** Liste os arquivos de cada instância. Se duas listas se tocam, não é fanout: é uma corrida que você descobre no diff. "Elas raramente colidem" não é resposta.

**P3 — o que fica na fronteira, e de quem é?** Para cada par, nomeie a convenção compartilhada e dê um dono — uma instância, ou o `join` via `owns`.

**O teste de descarte, que é o que separa paralelismo de espetáculo:** se o `join` precisa *refazer* o trabalho dos ramos para integrar — reler o material bruto, redecidir o que cada ramo decidiu, reescrever de ponta a ponta —, os ramos produziram rascunho, e você pagou 3× para gerar aquecimento caro. `join` legítimo reconcilia fronteiras e concatena.

**A conta que decide.** Coordenação custa **3–10×** os tokens de um agente solo, e o ganho de decompor **encolhe conforme o modelo fica mais forte**. O fanout não precisa empatar: precisa ganhar o suficiente para pagar isso. Por isso `baseline` é obrigatório — "valeu a pena" é uma linha do veredito, não opinião de desenho.

### 1.4 Contrato de escrita

O orquestrador tira o hash da árvore antes de subir o nó e depois de ele sair. Caminho criado, modificado ou removido que não case com nenhum glob de `writes` é **violação**: nó `failed`, path em `state.json.violations`, sessão para.

**Disjunção é decidida sintaticamente, sobre os globs, antes de subir nó — nunca sobre o filesystem em runtime.** Cada instância de `fanout` escreve sob um prefixo literal próprio. Um glob é aceito na forma `<prefixo>`, `<prefixo>/**` ou `<prefixo>/*.<ext>`; dois globs são disjuntos se nenhum prefixo é prefixo do outro **por componente de caminho** — `out/a` não é prefixo de `out/ab.md`, mas é de `out/a/x.md`. Curinga no meio do caminho é recusado dentro de `partition`.

> **Escolhida / descartada.** Prefixo literal, não interseção geral de globs. Custo: obriga o repositório a se organizar por dono, e recusa partições que na prática seriam seguras. Ganho: cabe em ~15 linhas, é decidível, e não tem falso negativo. Decidir interseção de globs no caso geral é um solver, e um solver com bug aceita o grafo que corrompe a sessão. Descartado verificar colisão em runtime com lock: aí o fan-out inválido já custou três subprocessos.

### 1.5 `state.json` — o ledger

Seis campos. **Único escritor: o orquestrador. Nenhum nó lê, nenhum nó escreve.**

1. `nodes` — por nó e por instância: `status` ∈ `pending | ready | running | verifying | done | failed | skipped`, `failure`, `started_at`, `ended_at`, `iters_used`, `attempts`, `session_ref`
2. `artifacts` — `{path, sha256, writer_node, mtime, valid}`, com **histórico de hashes**, não só o último
3. `budget` — `iters_used`, `cost_units`, `wall_seconds`, `log_bytes`, `utilization` da última janela observada
4. `violations` — `{node, path, kind}`
5. `mutations` — vazio no v1 (auto-gestão fica fora)
6. `preflight` — versão do CLI, `auth status`, concorrência efetiva, seed, sha256 do `graph.yaml`

O histórico de hashes não é luxo: dele saem `rework_count` (hash diferente), `null_writes` (hash idêntico — step repetition) e `no_progress_rounds`, que é uma das três camadas de bound. Guardar só o último apaga as três.

> **Escolhida / descartada.** Single-writer, e nó nunca lê o estado. Custo: um nó não consegue saber o que os outros fizeram, nem por engano. Ganho: é como "artefato é o canal" deixa de ser intenção e vira verdade. Se um nó lê `state.json`, o estado vira canal lateral não declarado e o grafo declarado deixa de ser o grafo executado — que é a propriedade que o produto vende. Descartado expor um `state` read-only ao nó: qualquer leitura é um canal.

`events.jsonl` (append-only, uma linha por transição, escrito **só** pelo pai) é a trilha. **O runtime nunca o lê para decidir** — se ler, existem duas verdades, e elas divergem no cenário que ninguém consegue reproduzir.

### 1.6 `baseline` — campo obrigatório

Grafo sem `baseline` é recusado no load. O braço de controle é versionado junto com o time que ele controla, e muda junto.

> **Escolhida / descartada.** Baseline no arquivo do grafo, não flag. Custo: toda sessão custa ~2×. Ganho: um baseline mantido fora do grafo desatualiza na primeira mudança de tarefa e passa a medir outra coisa; e o que não está no caminho crítico não é rodado. Descartado `--baseline prompts/x.md`: transforma o controle em opção, e opção é o que se corta quando aperta.

---

## 2. Como um time é instanciado

```
orch up graphs/<id>.yaml --session-dir .sessions/<session_id>
                         [--max-concurrency auto|1..3]   # default: auto
                         [--seed K]                      # default 1
                         [--no-baseline]                 # marca a sessão, não a esconde
orch doctor                                              # preflight isolado, 5 s
orch top | orch ps | orch watch                          # observação read-only (§5)
```

`--max-concurrency` limita o que sobe; `fanout.max` limita o que pode ser declarado. `--max-concurrency 4` é **recusa**, não ajuste silencioso.

### 2.1 A lista de recusas do loader

O `up` recusa **antes de subir qualquer nó**. Grafo inválido é erro de compilação.

**Estrutura** — `id` ≠ stem do arquivo · id fora do padrão, duplicado, ou colidindo com id derivado de instância · `prompt` inexistente no disco · aresta para nó inexistente · nó órfão · **qualquer ciclo** (o v1 é DAG estrito) · `stop` inalcançável.

**Paralelismo** — `fanout.max` fora de `2..3`, ou `len(partition)` fora de `2..max` · `template` declarando `id`/`reads`/`writes` · `always` fora da aresta `fanout`→`join` · `join.owns` ≠ o conjunto exato dos pares · aresta entre instâncias do mesmo `fanout`, ou instância cujo `reads` casa com o `writes` de outra instância · `fanout` sem `join` a jusante, ou com mais de um · `fanout` sem `rationale` de ≥3 linhas.

**Contrato e artefatos** — dois nós escrevendo o mesmo artefato declarado · artefato sem `owner`, ou `owner` que não é id de nó · aresta de artefato cujo `owner` ≠ `from` · `handoff` sem `artifact`, ou `structured` sobre artefato que não declara `sections` · `stop` referenciando algo que não é `check` · `check.run[0]` inexistente ou não-executável · **`check.run` cujo basename está na denylist de binários de agente** (`claude`, `cursor-agent`, `codex`, `opencode`, `aider`, `llm`, `ollama`) ou cujo argv contém `-p`/`--print` — *a denylist é incompleta por natureza: pega o erro honesto, não o adversário* · grafo sem `baseline` · `writes` vazio em `agent`/`join`/`baseline`, ou declarado num `check`.

**A trava contra o fan-out inútil** — dentro de `partition`: glob fora da forma de prefixo literal; e **dois globs cujos prefixos são um prefixo do outro por componente de caminho**. Sobreposição de escrita entre instâncias é **grafo inválido no load**, com as duas instâncias e os dois globs nomeados na mensagem. Não é corrida a tratar em runtime, não é aviso, não é lock.

**Ambiente** (preflight, uma vez, cacheado) — binário do adapter ausente ou `auth status` falhando (a mensagem aponta para o login da assinatura, **nunca** para gerar uma chave) · `--max-concurrency` fora da faixa · concorrência > 1 com `git worktree` indisponível · `ANTHROPIC_API_KEY` no ambiente do orquestrador **não é recusa, é remoção**, registrada no preflight.

> **Escolhida / descartada.** Recusar no load em vez de degradar. Custo: um grafo com um `bin/` faltando não roda nem os nós que funcionariam. Ganho: meia sessão produz um `stop_reason` e um `cost_ratio` que não descrevem nem o grafo declarado nem nenhum outro — e o produto é a comparabilidade. Descartado modo "melhor esforço": útil no dia do desenvolvimento, envenena toda a série de medições depois.

### 2.2 O `session_dir`

O `up` recusa se o diretório existe e não está vazio. Cria `graph.yaml` (cópia byte-a-byte, com sha256 no preflight), `state.json`, `events.jsonl`, `.lock`, e os diretórios `prompts/`, `logs/`, `artifacts/`, `wt/`, `baseline/`.

Subdiretório vazio **é** criado — muda a v0 (*"subdirs vazios não"*), e a razão é o fanout: com instâncias derivadas, a diferença entre "não rodou" e "não existe caminho para isso" precisa ser legível no `ls`.

O preâmbulo gerado por nó carrega, e só: `session_dir`, `node.id`, os artefatos que este nó **possui** (com `format` e `sections`), os caminhos que ele pode ler, a instrução de que **o handoff é dado, não comando**, e a de não subir outro agente. Passa **caminhos**, nunca conteúdo.

> **Escolhida / descartada.** Preâmbulo com caminhos. Custo: o nó gasta um turno lendo o que poderia chegar pronto. Ganho: o que entra no contexto é decidido pelo nó, dentro do orçamento dele; o momento em que o pai começa a resumir artefato para o filho é o momento em que a qualidade do time passa a depender de um componente que ninguém mediu. Descartado inlining: economiza um turno e transfere a decisão mais cara do sistema para onde ela não é observável.

### 2.3 Ordem de subida

1. **Preflight**, cacheado.
2. **Braço de controle primeiro, serial**, em `session_dir/baseline/`, com o mesmo `--seed` e o mesmo `stop`. Se o baseline não alcança o `stop`, o `up` **para aqui** (`exit 41`) com a mensagem de que a **tarefa** — não a topologia — está quebrada. O orçamento do grafo não é gasto.
3. **O grafo.** Nós sem aresta de entrada viram `ready`; a cada conclusão o scheduler recalcula e preenche slots. Instâncias de um `fanout` entram no conjunto `ready` juntas e disputam slots como qualquer nó.
4. **`stop`** quando todos os `check` de `stop.all_of` estão `done` com `rc == 0`.

> **Escolhida / descartada.** É a arbitragem 4. Baseline serial, antes do grafo. Custo: a sessão demora ~2×, e o paralelismo não paga o baseline. Ganho: baseline concorrente disputa a mesma janela de assinatura e contamina `wall_seconds` dos dois braços — que é o número-manchete do veredito. Um instrumento não pode contaminar a métrica que ele existe para produzir. Descartado o slot reservado concorrente (~0 de parede), com o custo registrado.

### 2.4 Isolamento e lock de sessão

Com concorrência 1, nenhum worktree; as instâncias rodam em série no `cwd` declarado. Com concorrência > 1, o `up` cria **um worktree por instância** em `wt/<fanout>.<slot>/` — cwd distinto ⇒ diretório de projeto distinto no cache do CLI, o que fecha o vazamento de contexto cruzado que não é do modelo. O dono do ciclo de vida do worktree é **o pai**; falha ao criar é recusa no load, não erro em runtime.

`up` adquire `session_dir/.lock` com `fcntl.flock` e escreve pid + hostname. Segundo `up` falha imprimindo o pid do dono. Lock órfão é recuperável com `--force-unlock`, **que deixa marca permanente no preflight** — a marca é a única evidência de que aquela série pode ter começado sobre um diretório sujo. Sem resume de sessão no v1.

---

## 3. Como o orquestrador executa N nós em paralelo

### 3.1 Ciclo de vida do nó

```
pending ──(arestas de entrada satisfeitas)──► ready
ready ──(slot livre ∧ gate de janela aberto)──► running   [spawn em NOVO PROCESS GROUP]
running ──(processo saiu | timeout do pai)──► verifying
verifying ─┬─ rc=0 ∧ ¬is_error ∧ denials=[] ∧ verify(artefato) ──► done
           ├─ denials ≠ []                  ──► failed:permission  (não retenta)
           ├─ subtype=error_max_budget_usd  ──► failed:budget      (nunca retenta)
           ├─ rc≠0 ∧ api_error_status≠null  ──► retry:transport    (backoff, até 2)
           ├─ rc=0 ∧ denials=[] ∧ ¬verify   ──► failed:verify      (v1: não retenta)
           └─ morto por timeout do pai      ──► failed:timeout
```

`verifying` é estado de verdade, não de trânsito: é onde o pai lê o log do filho e decide. **O escalonador não pode liberar o slot antes do veredito** — liberar antes é como o paralelismo passa a corromper o grafo.

As quatro classes existem porque tratar todas como "falhou, tenta de novo" custa, com concorrência 3, **três loops caros simultâneos contra a mesma janela**. `permission` é bug de configuração: falha alto, imprimindo o `tool_name` negado e a flag que o resolveria.

### 3.2 O predicado de conclusão — normativo

Um nó **está concluído se, e somente se**:

```
done(node) := rc == 0
          AND result.is_error == false
          AND result.permission_denials == []
          AND verify(artefato)      # existe, não-vazio, mtime > node.started_at
```

**O orquestrador não pode marcar `done` a partir do exit code isolado.** Verificado em execução: `claude -p` em permission-mode default, ao qual se pede um `Write`, retorna **`exit 0`, `is_error: false`, `subtype: "success"` — e o arquivo não existe**, com `permission_denials[]` populado. Um escalonador que confia no `rc` propaga a aresta e sobe o nó seguinte contra um artefato inexistente.

O `verify` mora no bloco `artifacts:` do grafo, não na aresta — uma instância de `fanout` não tem aresta de saída própria, e o predicado precisava de outro ancoradouro.

> **Escolhida / descartada.** Conjunção de quatro. Descartado o `rc` isolado (mente, provado); descartado o par `rc + artefato` (deixa passar o denial silencioso quando o artefato sobrou de outra rodada — daí `mtime > started_at`); descartado o julgamento por LLM (custa um turno, reintroduz não-determinismo no ponto mais caro de debugar, e a variante com juiz por rodada custou +129% de tokens sem ganho).

**Consequência para o paralelismo:** `verify` roda no pai, no estado `verifying`, com o slot ainda ocupado. Rodá-lo em paralelo com o próximo nó é o que produz a corrida em que B lê um artefato que A ainda estava escrevendo.

### 3.3 O escalonador de conjunto pronto

O pai **não** executa uma ordem topológica pré-computada. A cada conclusão, recalcula:

```
ready_set() := { n : status(n)==pending ∧ ∀e ∈ entradas(n): status(e.from)==done ∧ predicado(e) }
```

1. Computa `ready_set()`. Vazio, e nada em `running`/`verifying` ⇒ **`stop_reason: deadlock`**, com os nós `pending` no erro. É erro nomeado, nunca um `wait` eterno — o laço sem esta cláusula é o loop infinito clássico.
2. Enquanto houver slot livre **e** o gate de janela aberto: retira um nó, garante o isolamento, monta o spawn, lança em novo process group.
3. Bloqueia na **primeira** conclusão (`FIRST_COMPLETED`), não em barreira.
4. Roda `verifying`, aplica o predicado, escreve a transição em `state.json` e a linha em `events.jsonl`, libera o slot.
5. Volta ao passo 1.

> **Escolhida / descartada.** `FIRST_COMPLETED`, não barreira por onda. Custo: nenhum. Ganho: nós têm duração desigual — um `check` sai em 200 ms, um `agent` em 4 min — e a barreira deixa slots ociosos até o mais lento terminar. Descartada a barreira: é a implementação que faz concorrência 3 render como 1 num grafo real.

> **Escolhida / descartada.** Scheduler no pai, `ThreadPoolExecutor` sobre `subprocess.run(timeout=)`. Ganho: I/O-bound puro, GIL irrelevante, e o caso serial cai fora como degenerado — não há dois executores para manter. Descartados `xargs -P` e GNU parallel: não conhecem o grafo, não recalculam o conjunto pronto, não acumulam orçamento e não têm onde aplicar o gate de janela.

### 3.4 Concorrência: `auto`

```
auto ⇒ min(largura do grafo, 3)   enquanto  utilization < 0.85
       1                          quando    utilization ≥ 0.85
       0 (dorme até resetsAt)     quando    utilization ≥ 0.95
       aborta (exit 30)           quando    status != "allowed"
```

O efetivo é `min(flag, largura do grafo, gate)`, **reavaliado a cada slot**.

> **Escolhida / descartada.** É a arbitragem 3. Default `auto`. Custo: a mitigação de ToS deixa de ser um default conservador e passa a depender do gate funcionar. Ganho: um paralelismo que exige flag para existir não existe, e a degradação por `utilization` é política executável sobre um sinal que a própria plataforma emite — mais forte que um default que o usuário desliga na primeira sessão. Descartado default 1, com o custo registrado.

**O que `--max-concurrency` não é:** não é o que cria paralelismo. Quem cria é a **largura do grafo**. Numa cadeia `scout → builder` o efetivo é 1 para qualquer valor, porque o conjunto pronto nunca tem dois elementos. Isso **tem que estar na ajuda da flag**, senão o primeiro relato de bug será "pus 3 e não ficou mais rápido". O `up` **avisa**, não recusa, quando a flag excede a largura do grafo.

### 3.5 As cinco regras de concorrência — sem exceção

1. **Spawn em novo process group; kill pelo grupo.** O filho gera netos (a tool `Bash`). `kill()` mata o pai e deixa os netos segurando o worktree e escrevendo no artefato depois de o nó ser declarado `failed:timeout`. `start_new_session=True`, depois `killpg(SIGTERM)` → grace 5 s → `SIGKILL`. **Não é boa prática, é pré-condição:** sem isso o `git worktree remove` falha, a limpeza não roda, o `up` seguinte é recusado — e o sintoma que o operador vê, *"a segunda sessão não sobe"*, não tem relação visível com a causa.
2. **Nós não commitam.** Worktree isola a árvore de trabalho, **não** isola `.git/index.lock` nem o object store. Quem commita é o pai, serializado, depois do `join`.
3. **Lock via `fcntl.flock`, nunca `flock(1)`.** O binário não existe no macOS de fábrica, e o produto roda em Linux **e** mac. Vale igual para `timeout(1)`. Regra geral: se o recurso existe na biblioteca padrão, não terceirizar para binário do sistema.
4. **Um log por nó, sempre.** Stdout compartilhado entre nós concorrentes produz JSONL intercalado não-parseável, e a linha `result` — a última de cada stream — deixa de ser localizável.
5. **`events.jsonl` é escrito só pelo pai e nunca lido para decidir.**

### 3.6 Paralelismo que gera valor — o ganho, o custo e o ponto de virada

O veredito tem famílias de métrica; **o paralelismo compra exatamente uma.** Com `T_i` o tempo de cada nó e `CP` o caminho crítico, o piso da parede é `max(CP, Σ/k)`:

| Grafo | Σ | CP | k=3 | Ganho |
|---|---|---|---|---|
| `scout → builder` (cadeia) | 2t | 2t | 2t | **1,00× — zero, para qualquer k** |
| fanout×3 + join, join = t | 4t | 2t | 2t | **2,00×** |
| fanout×3 + join, join = t/3 | 3,33t | 1,33t | 1,33t | **2,50×** |

O teto realista de um fanout de 3 é **2 a 2,5×**, não 3×, porque o `join` é serial e paga preço cheio. O dado verificado que sustenta que a banda existe: 3× `claude -p` concorrentes em cwds distintos, 3 artefatos corretos, **10 s de parede para os três**. *Ressalva registrada: a serialização equivalente não foi medida na mesma máquina; a tabela é modelo de Amdahl sobre um ponto medido.*

**O que se move e o que não se move:** `wall_seconds` melhora — é o ganho inteiro. `gate_first_pass`, `rework`, `write_violations` e `handoff_valid` **não se movem**: são propriedades do grafo, não do escalonador. `cost_ratio` piora um pouco. `stop_reason` ganha um valor novo, `window_sleep`.

**O custo que sobe junto:** o piso de contexto por nó (num prompt trivial, ~38k tokens de cache antes de a tarefa começar) é pago `k` vezes; a **taxa** de consumo da janela é `k` vezes maior; e as cinco regras acima passam de higiene a requisito.

**Os três pontos em que aumentar `k` piora, na ordem em que aparecem:**

1. **`k` acima da largura do grafo:** ganho exatamente zero, custo maior que zero.
2. **`k` que faz a sessão cruzar `utilization > 0,85`:** você paga o custo de `k` nós e recebe a velocidade de 1. **É o ponto de virada real, e é assimétrico:** o ganho se mede em minutos; o sono da janela se mede em horas (`resetsAt` de 5 h). Uma sessão que dorme uma vez perdeu mais tempo do que o paralelismo inteiro economizou.
3. **`k > 3`:** degradação de qualidade, não só de custo — 1→3 ganha, 3→5 é marginal ou negativo, e paralelismo estrutural agressivo derrubou acurácia de 28% para 25%.

**A regra operacional, impressa pelo `up`:** paralelismo só gera valor quando a largura do grafo é ≥2 **e** a sessão cabe na janela sem dormir. As duas são verificáveis antes do primeiro nó — a primeira no load, a segunda lendo a `utilization` no `orch doctor`.

---

## 4. Como invoca os CLIs

### 4.1 O contrato do adapter

```
preflight()                         -> Ok | Reason        # uma vez por up, cacheado
build(node, session)                -> Spawn{argv, cwd, env, stdin_bytes, timeout_s}
parse(rc, stdout_path, stderr_path) -> Outcome{ok, rc, failure, denials, turns,
                                               cost_units, session_ref, rate_limit, text}
```

**O `Outcome` é definido antes dos adapters e é o único acoplamento entre eles.** É o que permite escrevê-los em paralelo.

### 4.2 Adapter `claude` — comando exato

```bash
claude -p \
  --output-format stream-json --verbose \
  --permission-mode acceptEdits \
  --model "${NODE_MODEL:-sonnet}" \
  --session-id "$NODE_UUID" \
  --add-dir "$SESSION_DIR" \
  --allowedTools Read Write Edit Glob Grep \
  --disallowedTools WebFetch WebSearch Task Bash \
  --max-budget-usd "$NODE_BUDGET" \
  --setting-sources project --strict-mcp-config \
  --append-system-prompt "$(cat "$SESSION_DIR/prompts/$NODE.preamble.md")" \
  < "$SESSION_DIR/prompts/$NODE.prompt.md" \
  > "$SESSION_DIR/logs/$NODE.jsonl" 2> "$SESSION_DIR/logs/$NODE.err"
```

Verificado contra `claude` 2.1.251:

- `--verbose` é **obrigatório** com `stream-json` sob `-p`; sem ele, `exit 1`.
- `stream-json` sobre `json` por um motivo só: é onde vêm os `rate_limit_event`. O `result` final é a última linha, com o mesmo conteúdo.
- `--permission-mode acceptEdits` é o mínimo que faz o nó escrever — **e libera `Bash` também**, verificado com `env -i`. Logo `--allowedTools`/`--disallowedTools` **são a ACL do nó**, não um refinamento. Descartada `bypassPermissions`.
- Prompt por **stdin**: sem `ARG_MAX`, sem escaping, sem prompt de 8 KB no `ps`.
- `--session-id` derivado: `uuid5(NS, session_id + ":" + node_id)`. Além de habilitar retomada futura, **protege contra a herança de env** — verificado que um filho reusou o `session_id` do pai porque `CLAUDE_CODE_SESSION_ID` estava no ambiente. Com três nós, isso é transcript entrelaçado.
- Usar `--append-system-prompt "$(cat …)"`. O `--append-system-prompt-file` funciona e **não aparece no `--help`**: flag não documentada some sem changelog.

**Env: allowlist, não denylist — emenda à v0 §4.** A v0 mandava remover `ANTHROPIC_API_KEY`; isso é metade do problema. Um filho herda `CLAUDECODE`, `CLAUDE_CODE_SESSION_ID`, `CLAUDE_CODE_ENTRYPOINT`, `ANTHROPIC_BASE_URL` e ~40 outras.

```
PASSA:    HOME PATH USER SHELL LANG LC_* TERM=dumb TZ TMPDIR
          SSH_AUTH_SOCK (só se o nó precisar de git via ssh)
          ORCH_SESSION_DIR ORCH_NODE_ID ORCH_ARTIFACT
BLOQUEIA: ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL
          CLAUDECODE CLAUDE_CODE_* CLAUDE_* CURSOR_*
```

`TERM=dumb` de propósito: sem TTY o CLI já vai para o caminho não-interativo, e `dumb` remove resíduo de ANSI no log.

### 4.3 `--bare` é proibido

O help diz que com ela a auth é estritamente `ANTHROPIC_API_KEY` ou `apiKeyHelper`, e que OAuth e keychain **nunca** são lidos. É a flag que mais parece "modo hermético" e é exatamente a que quebra a restrição do produto. O `build()` **falha** se ela aparecer — não é nota de rodapé. O knob hermético compatível com a assinatura é `--safe-mode` + `--setting-sources` + `--strict-mcp-config`.

### 4.4 `cursor-agent` — não verificado

O binário não existia na máquina de teste. Schema de eventos diferente, `--force` é allow-unless-denied (mais grosso que `acceptEdits`), sem equivalente documentado a `permission_denials` — **para o Cursor, o predicado de artefato não é redundância, é a única defesa** —, exit code sem contrato documentado, e bug conhecido de `-p` pendurando indefinidamente. `Outcome` sai com `turns=null, cost=null`: registrar, não fingir paridade. **Pré-condição:** instalar e repetir os 20 testes antes de escrever o adapter.

### 4.5 `exec` — o genérico

`cmd:` no YAML, `Outcome` degradado (`ok = rc==0 ∧ verify(artefato)`, resto `null`). Custo: perde orçamento e denials. Ganho: torna o orquestrador agent-agnostic **sem** PTY, e é a apólice contra o risco de ToS — se a porta fechar, o projeto aponta para `codex`, `opencode`, `aider` ou um `.sh` no mesmo dia.

### 4.6 O gate de orçamento e de janela

| Eixo | Como |
|---|---|
| custo por nó | `--max-budget-usd` — corta de verdade (`subtype: error_max_budget_usd`, `terminal_reason: budget_exhausted`) |
| custo por sessão | acumula `total_cost_usd`; se `total + próximo_teto > session_cap`, **não sobe o próximo nó** |
| relógio | timeout no processo **pai** |
| janela | `rate_limit_event.unifiedWindows.{five_hour,seven_day}.{utilization,resetsAt}` |

Com N nós, o gate deixa de ser precaução e vira o mecanismo que impede a sessão de se matar. **Nunca retry cego em 429** — é o padrão de tráfego que a plataforma mede.

*`total_cost_usd` vem com `costBasis: "list"` — preço de tabela, não o que a assinatura cobra. Chamar de **unidade de orçamento**, nunca de dinheiro.*

---

## 5. A superfície — como se vê N nós trabalhando

Três comandos, **todos read-only e fora do processo do `up`**: leem `state.json` + `events.jsonl` e não conseguem alterar a sessão.

```
orch top     a tela do time — tabela de raias que se repinta
orch ps      o mesmo, uma vez, sem repintar   (= orch top --once)
orch watch   o feed cronológico — drill-down, stdout puro
```

> **Escolhida / descartada.** É a arbitragem 1. Superfície primária = **tabela que se repinta**; feed = drill-down. Custo: um comando novo, e o feed deixa de ser onde o dono mora. Ganho: "ver 3 agentes trabalhando" vira 8 linhas que mudam, não 300 que rolam — log que rola comunica **volume**, tabela que muda comunica **progresso**. Descartado manter o feed como tela principal: o problema não é renderizar 3× eventos, é que 3× eventos não têm uma ordem que valha a pena ler linearmente.

> **Escolhida / descartada.** Observação fora do processo do `up`. Custo: a tela está atrasada em até um intervalo de amostra. Ganho: zero, um ou três `orch top` rodando, e a sessão não sabe e não se importa; a tela não pode travar, corromper nem alterar a run. **Uma run que muda porque alguém estava olhando não serve de medida.**

```
session .sessions/2026-08-31-mat97   graph v1   up 00:08:41   conc 3/3
────────────────────────────────────────────────────────────────────────────────
3 vivos · 2 avancando · 1 GIRANDO (build.b 4m12s) · artefatos 5/9 validos
$1.42/$6.00 · janela 5h 61%
────────────────────────────────────────────────────────────────────────────────
LN NODE       ST    T+     IT  COST   PULSO  WRITES                    LAST
a  build.a    RUN   04:12   3  $0.31  ++·+·  out/a.md          +88L    3 secoes escritas
b  build.b    SPIN  04:12   7  $0.74  ·····  out/b.md           ~0     reescreveu, mesmo sha
c  build.c    RUN   02:03   2  $0.18  +·~·+  out/c.md          +12L    lendo spec/c
   merge      WAIT   —      —   —      —     (join exige 3/3)          espera a, b, c
   gate       WAIT   —      —   —      —     (check bin/gate-report)   espera merge
   scout      DONE  01:44   2  $0.19  ·+···  handoff.md        +41L    particao em 3 fatias
────────────────────────────────────────────────────────────────────────────────
```

**O PULSO** — cinco amostras de 30 s, mais recente à direita: `+` o artefato de `writes` cresceu · `~` reescrito com mesmo sha (thrash) · `-` encolheu · `·` nada mudou. `++·+·` avança; `·····` gira; `~~~~~` reescreve em círculo, que é o pior porque **parece atividade**. Derivado direto do que o `state.json` já guarda: **zero instrumentação nova**.

> **Escolhida / descartada.** O pulso mede **saída em disco**, não atividade do processo. Custo: um nó que passa 3 minutos legítimos lendo antes de escrever aparece como `·····` — mitigado pelo `T+` e pelo `LAST` ao lado, e pelo `SPIN` só disparar com `IT` subindo junto. Ganho: é impossível fingir. Descartado medir bytes de log, tokens ou "está gerando output": todos sobem quando o agente conversa consigo mesmo, que é exatamente o estado a denunciar.

**`SPIN`, `STAL` e `VRFY` são qualificadores de `running`, não estados novos.** A tela não inventa um oitavo status: se ela virasse segunda verdade sobre o grafo, o `state.json` deixaria de ser single-writer na prática. `orch show <node> --state` imprime os dois lado a lado.

**A linha de status é a resposta a "está gerando valor?" em 5 segundos**, e é computada dos **mesmos campos** do veredito final — o dono passa o dia lendo a versão parcial do relatório que vai receber. *Descartado inventar um "score de saúde" para a tela: seria uma segunda métrica competindo com a oficial, e a primeira coisa que alguém faria é otimizar para ela.*

**Fora do v1, por impossibilidade técnica** (arbitragem 2): `orch next`, `orch say`, a fila de ASK e o arquivo `NEEDS_YOU`. Um nó `claude -p` headless não tem TTY e não pergunta no meio do turno; a fila de ASK pressupõe um canal que o v1 não tem. Entra quando `--input-format stream-json` for verificado. **Fora por decisão:** alternate screen buffer (mata scrollback, `tee`, `grep` e ssh frágil), pane por nó (otimiza ler *dentro* de um nó e destrói a comparação *entre* raias, que exige colunas compartilhadas), canvas, chat entre nós, sumarizador LLM.

---

## 6. O corte do v1

O escopo não cresce nos dois sentidos. Entram `fanout`/`join`, worktree, scheduler e locks — a camada mais pesada e a única onde toda regressão de concorrência aparece. Então saem quatro coisas, três delas boas.

| Peça | Dentro do v1 | Fora (nomeado, não agora) |
|---|---|---|
| Grafos | `v0.yaml` (cadeia) · `v1.yaml` (scout → fanout×3 → join) · `baseline` | registry, loader de pasta |
| Nós | `agent`, `check`, `fanout`, `join` | `map`, `reduce`, sub-grafo aninhado |
| Arestas | `artifact_exists`, `artifact_valid`, `check_passed`, `check_failed` (terminal), `always` | **ciclo e `max_repeats`** |
| Concorrência | `auto` (largura, teto 3), degradando por `utilization` | 4+, fila distribuída, máquina remota |
| Isolamento | `worktree` por instância; `cwd` para o resto | container, sandbox, VM |
| Adapters | `claude` | `cursor-agent`, `exec` |
| Retry | `transport` (backoff ≤2) | **`semantic` com `--resume`** |
| Superfície | `up`, `doctor`, `top`, `ps`, `watch` — read-only | **`next`, `say`, ASK, `NEEDS_YOU`**, `show`, `since` |
| Auto-gestão | **nenhuma** | catálogo de reparo, depois do veredito |
| Baseline | obrigatório, serial, antes do grafo | slot reservado concorrente |
| Veredito | **3 números + 1 frase**; diagnóstico só na reprovação | veredito com 15 números |

### 6.1 Critério de parada, literal

1. `stop` alcançado ⇔ **todo** nó de `stop.all_of` está `done` com `rc == 0`.
2. No instante do `stop`, o orquestrador **mata os nós ainda `running`**: `killpg` → grace 5 s → `SIGKILL`; marca `skipped:stop_reached`; remove os worktrees. *Descartado esperar os ramos terminarem por educação: ramo perdido gastando orçamento depois do stop é a fatura que ninguém pediu.*
3. Qualquer `failed` — inclusive de uma instância de `fanout` — encerra a sessão, com a mesma limpeza (arbitragem 7).
4. Failsafe de budget é **incondicional e não ablável**.

**Exit codes**, em faixas, para um script classificar sem parsear texto:

| | | | |
|---|---|---|---|
| **0** | `stop` alcançado; a sessão foi medida | 20 | `no_progress` |
| 1 | falha não classificada — **se aparecer, é bug do `orch`** | 21 | `wall_seconds` estourado (failsafe) |
| 10 | `failed:contract` (escreveu fora do `writes`) | 30 | rate limit: `status != "allowed"` |
| 11 | `failed:permission` | 40 | preflight falhou |
| 12 | `failed:budget` | 41 | **baseline não alcançou o `stop`** — a tarefa está quebrada |
| 13 | `failed:timeout` | 50 | grafo inválido — recusa no load |
| 14 | `failed:verify` | 64 | uso incorreto da linha de comando |

> **A regra que não se negocia: o exit code nunca codifica o veredito.** Uma sessão em que o grafo perdeu feio para o baseline sai **0**, porque a corrida foi válida e o número foi produzido. `0` significa *"medi"*, não *"ganhei"*. Descartado `exit ≠ 0 quando o grafo perde`, que é o instinto de quem quer plugar isso num CI: o run perdedor é o dado mais valioso que este instrumento produz, e um exit vermelho é o convite para escondê-lo, reexecutar até passar, ou remover a comparação do pipeline. **Um instrumento que pune o resultado negativo deixa de receber resultados negativos.**

---

## 7. O veredito

> **O veredito tem 3 números e 1 frase. O diagnóstico tem o resto, e só é impresso quando o veredito reprova. `verdict.json` tem tudo, sempre.**

Uma decisão com quinze entradas não é decisão, é discussão — e um relatório de doze linhas em modo texto é o mesmo painel que a §6 acabou de cortar, sem cores.

Rodar três agentes não torna a saída melhor: torna a saída **mais cedo**. Então a régua pergunta, nesta ordem: **comprei relógio? paguei quanto? estraguei alguma coisa?**

1. **`speedup` = Σ `node.wall_seconds` ÷ `session.wall_seconds`** *(do braço do grafo, excluída a parede do baseline)*. É o que a execução serial do mesmo grafo teria custado, porque cada nó roda uma vez de qualquer jeito. **É o número anti-teatro:** `speedup ≈ 1,0` com três ramos declarados significa que o grafo não é paralelo — é uma corrente com fantasia de fanout, e os três terminais piscando estavam esperando um ao outro.
2. **`cost_ratio` = `log_bytes(grafo)` ÷ `log_bytes(baseline)`** — o que o relógio comprado custou. `log_bytes` é proxy de token de saída, declarado como proxy.
3. **`delta_gate` = `gate_first_pass(grafo)` − `gate_first_pass(baseline)`** — o portão determinístico passou de primeira mais vezes com o time do que com um nó só? Zero é neutro; negativo é regressão.

```
paralelismo ÚTIL  ⟺  speedup ≥ 1.50  ∧  cost_ratio ≤ 2.50  ∧  delta_gate ≥ 0
```

Os três limiares são pré-registrados e mudam por **emenda datada**, nunca depois de ver um resultado.

> **Escolhida / descartada.** `speedup` pela soma dos nós. Descartado rodar o mesmo grafo uma segunda vez com concorrência 1 para obter o denominador honesto: dobra a fatura para medir o que a soma já dá. Custo: ignora o overhead do scheduler e superestima o serial em alguns pontos percentuais — erro pequeno e conhecido.

**Fora da régua, e por quê:** `orphan_writes`, `null_writes`, `handoff_uptake`, `rework`, `branch_wall`, utilização de janela, `write_violations`. `handoff_uptake` é proxy de 6-grama **declaradamente não calibrado**, e número não calibrado que participa de decisão contamina a decisão; utilização de janela mede a plataforma, não o grafo; `rework` é a métrica primária do [`EXPERIMENTO.md`](EXPERIMENTO.md), comparada entre braços com repetições, e uma sessão isolada não tem n para falar em mediana. Todos continuam sendo coletados, todos vão para o `verdict.json`, e todos aparecem no **diagnóstico** — cujo trabalho não é decidir, é explicar por que o veredito reprovou.

```
veredito  graphs/v1.yaml  vs  baseline(1 nó)        tarefa: mat-96-spec     seed 3/5
──────────────────────────────────────────────────────────────────────────────────
  speedup       1.12×   (Σ nós 00:41:08 ÷ parede 00:36:44)       REPROVA   < 1.50
  cost_ratio    2.83×   (log_bytes 1.94 MB ÷ 0.68 MB)            REPROVA   > 2.50
  delta_gate    +0.00   (grafo 2/3 · baseline 2/3)               neutro

  VEREDITO: paralelismo DECORATIVO.
  os 3 ramos custaram 2,8x e entregaram o mesmo que 1 no, em 89% do tempo.

  diagnóstico (impresso porque o veredito reprovou)
    speedup_max    1.31×  teto do seu DAG: 82% da parede esta no caminho critico
                          scout → join. o fanout nao tem o que paralelizar.
    join_wall      00:19:40   54% da parede inteira num no so
    branch_wall    a 00:12:31 · b 00:11:58 · c 00:12:02   (desbalanco 4%)
    orphan_writes  2      b e c escreveram artefato que nenhum no `reads`
    null_writes    1      c reescreveu byte-identico (step repetition)
    handoff_uptake 0.41   [proxy nao calibrado — nao decide nada]
    stop_reason    gate 1 · skipped:stop_reached 2 · failed 0

  leitura: mova trabalho do `join` para os ramos, ou pare de usar fanout nesta
  tarefa. nao aumente `max`.

  1 seed nao decide. esta e a amostra 3 de 5.   →  .sessions/t7/verdict.json
```

> **Escolhida / descartada.** Diagnóstico só na reprovação. Custo: quem passou não vê os detalhes sem abrir o JSON. Ganho: o volume de texto é inversamente proporcional ao sucesso, que é o incentivo certo — e ninguém aprende a ignorar um bloco que só aparece quando há problema. Descartado imprimir sempre: em duas semanas vira ruído que o olho pula, e voltamos a ter um painel.

**A frase do rodapé é obrigatória em todo veredito.** A mesma célula, com modelo pinado, já deu expoente 1,76 e 2,44 em duas coletas. O piso é 5 seeds por célula antes de qualquer decisão de desenho, e o comando é obrigado a lembrar disso na cara de quem rodou uma vez.

**A cláusula do baseline.** `--no-baseline` existe, é de linha de comando, e é ruidosa: imprime `SEM BASELINE — esta sessão não produz veredito` antes de subir qualquer nó; grava `"comparable": false` permanentemente; **não escreve `verdict.json`**; e no fim imprime `veredito: INDISPONÍVEL`. A sessão ainda sai 0 se alcançou o `stop` — rodar sem medir não é erro, é só não ser este produto naquela vez. **A flag não pode ser expressa no YAML, nem em config de projeto, nem em variável de ambiente.** Descartado proibir de todo: o operador forka, apaga a linha, e perdemos até o registro de que aquela sessão não foi medida. Descartado permitir no YAML: em uma semana vira o default do projeto, e o produto volta a ser painel por erosão. **A saída existe e não pode virar hábito, porque hábito mora em arquivo versionado.**

---

## 8. O que não se decide no código

Fechado aqui. Não reabrir na MAT-97:

- sem API, sem SDK, sem `ANTHROPIC_API_KEY`, **sem `--bare`**
- sem misturar este repo com `mathai-harness`
- sem wiki, sem label `hitl`
- sem PTY como runtime; sem tmux como runtime; sem daemon
- sem bus, sem chat entre nós, sem roteamento por descrição
- sem sumarizador LLM, sem juiz LLM no caminho de decisão
- sem ciclo no grafo, sem retry semântico, sem auto-gestão
- sem nó lendo `state.json`
- `DONE.md` não é critério de nada

Se um CLI mudar de flag, **emenda datada nesta spec antes de adaptar o código**. `orch doctor` existe para que a descoberta da mudança não aconteça no meio de uma sessão, com o log errado.

## 9. A condição em que isto continua não merecendo existir

Suponha o melhor cenário: `speedup` 2,3×, `cost_ratio` 2,1×, `delta_gate` zero, em 5 seeds × 12 tarefas. O que foi comprado? **Relógio.** `delta_gate = 0` quer dizer que a saída é a mesma; ela só apareceu antes.

> Latência só tem valor quando alguém está bloqueado nela. A premissa deste produto é `claude -p` headless, sem TTY, sem humano na frente. **Paralelismo headless é otimizar a latência de um processo que ninguém está esperando.**

Escrito como teste, não como sentimento: **se o resultado modal for `speedup ≥ 1,5` com `delta_gate ≈ 0`, o paralelismo está funcionando e mesmo assim não deveria ter sido construído** — e a resposta certa não é ajustar a topologia, é rodar o baseline sozinho e ir dormir.

Mais três, todas com forma de teste: se `delta_gate` for consistentemente negativo (o default que a literatura sugere, e a *collaboration tax* **decresce com a capacidade do modelo** — o modelo do ano que vem é o concorrente, e ele não tem mantenedor); se o `orch doctor` quebrar mais de uma vez por trimestre por deriva de CLI; e se a moratória de junho/2026 acabar.

E a que já estava escrita: se o grafo empatar com o baseline dentro do ruído, o valor remanescente é a camada de **contrato** — `writes` verificados por diff de árvore, orçamento com corte real, parada por `check` determinístico, `permission_denials` respeitados — acima de CLIs que não têm nada disso. É uma tese mais defensável que a original, **e não precisa de paralelismo nenhum.**

Nada disso é motivo para não começar. É motivo para começar pela medição. **O pior desfecho não é o grafo perder para o baseline. É o grafo perder e ninguém ter medido, porque a tela estava bonita.**

---

## 10. Emendas datadas

A §8 manda: mudança de contrato entra como emenda datada, antes do código, e o corpo acima não é reescrito. Isto é o registro.

---

### Emenda A — 2026-08-31 · o time é código revisável

**O que muda.** O grafo deixa de ser "um arquivo que por acaso está no repo" e passa a ter superfície própria de revisão. Entra o subcomando `orch team`, com quatro verbos:

```
orch team lint <graph>...          # a lista de recusas do §2.1, sem subir nada. 0 / 50
orch team show <graph>             # o time renderizado para quem revisa o PR
orch team diff <base> <head>       # diff semântico, classificado por severidade
orch team fingerprint <path>...    # hash semântico; com N caminhos, relatório de agregação
```

Entram três coisas no contrato, e as três são normativas:

1. **A declaração é somente-leitura em runtime.** O `up` grava `preflight.declaration_tree_sha256` — hash da árvore `graphs/` — antes do primeiro nó e reconfere depois do último. Divergência é erro nomeado. É a Emenda B, abaixo.
2. **`team_fingerprint`** — hash semântico estável da declaração — é carimbado no `state.json` e no `verdict.json`.
3. **Dois runs só são agregáveis se o `team_fingerprint` bater.** Somar o veredito de dois times mede a mudança do time, não a da tarefa. Quando não bate, o relatório imprime `NÃO AGREGÁVEL` e nomeia os grupos; `--require-same` transforma isso em exit 50, para o CI.

**O que o fingerprint cobre, e por quê.** O YAML canonizado (invariante a ordem de chave e a comentário), **mais** o sha256 do conteúdo de cada `prompt` referenciado e de cada binário de `check`. Dois runs com o mesmo YAML e um `prompts/builder.md` reescrito não são o mesmo time, e agregá-los em silêncio é exatamente o erro que o fingerprint existe para impedir. Fica **fora**: `rationale`, que o loader não lê e que não muda comportamento — o `diff` mostra a mudança como `neutra`, o fingerprint ignora.

> **Escolhida / descartada.** Diff **semântico**, não textual. Custo: ~380 linhas de código que precisam ser mantidas junto do schema; um campo novo no grafo que ninguém ensinar ao `diff` aparece como nada em vez de aparecer como linha. Ganho: um `git diff` de YAML mostra `+ writes: ["out/a.md", "src/**"]`; o revisor precisa ler **"`build.a` ganhou `src/**` no contrato de escrita"**, **"o teto de fanout subiu de 2 para 3"**, **"o `stop` deixou de exigir o check `contract`"**, **"`verify.min_lines` removido: o portão do artefato afrouxou"**. São quatro frases sobre **poder**, e nenhuma delas está na linha que mudou. Descartado confiar no `git diff`: a mudança mais perigosa deste schema — afrouxar o portão que decide a parada — é uma linha removida, e linha removida é o que o olho pula.

> **Escolhida / descartada.** Classificar em **alarga poder / restringe / neutra**, e imprimir os que alargam primeiro. Custo: a régua é opinativa e vai errar em caso de fronteira (um `timeout` maior é mais poder ou mais paciência?). Ganho: um revisor com 40 segundos lê a primeira seção e já sabe se o PR aumenta o que o time pode fazer no repo dele. Descartado listar tudo em ordem de arquivo: aí a linha que libera `Bash` num nó fica entre duas linhas de comentário reescrito.

> **Escolhida / descartada.** `head` que não carrega é **recusa (exit 50)**, não achado de revisão. Custo: o revisor não recebe um diff parcial de um grafo quebrado. Ganho: grafo inválido é erro de compilação (§2.1), e a mensagem do loader já nomeia as duas instâncias e os dois globs quando a partição deixa de ser disjunta — que é mais útil que uma linha de diff dizendo "partition mudou".

> **Escolhida / descartada.** `--fail-on-widening` sai **50**, a mesma faixa de "recusa sobre uma declaração", e não um código novo. Custo: um script não distingue "grafo inválido" de "mudança recusada por política" sem ler o texto. Ganho: a tabela de exit codes do §6.1 é sobre sessões; inventar uma segunda faixa para uma ferramenta de revisão duplicaria o vocabulário por um ganho de um bit.

**Contra qual buraco da concorrência ela existe.** O Maestri guarda a partitura em `~/.maestri/partituras` — fora do repo, não versionada com o projeto, não revisável. A documentação do Claude Code Agent Teams afirma que **não existe equivalente em nível de projeto** para a config de time, e que edição à mão é sobrescrita. O Grok Bot resolve a aresta em runtime, pelo modelo, e não a grava como aresta comparável entre execuções. Nos três, a pergunta *"o que exatamente mudou no meu time no commit de ontem?"* não tem resposta mecânica. Aqui ela tem, e a resposta vem classificada por quanto poder foi entregue.

*Nota de honestidade, que a mesa-redonda já tinha registrado:* grafo versionado no repo foi julgado **"buraco real, admitido pelo fornecedor, mas copiável numa tarde — substrato, não categoria"**. Esta emenda não reabre esse julgamento. O que ela faz é transformar o substrato em algo com **consequência mensurável**: o fingerprint como condição de agregação liga a declaração ao veredito, e é o veredito — não o arquivo — que é a categoria.

---

### Emenda B — 2026-08-31 · o desvio dinâmico, e por que ele nunca volta para a declaração

**O problema.** O `orch` decide coisas em runtime: o escalonador de conjunto pronto escolhe a ordem (§3.3), o gate degrada a concorrência por `utilization` (§3.4, §4.6), o worktree é criado ou não conforme o ambiente (§2.4), e a §6 nomeia mutação/reparo de topologia como evolução futura. Declarar o time como arquivo versionado **e** ter runtime que decide é a receita clássica de duas verdades — a mesma que a §1.5 já recusou para `state.json` × `events.jsonl`.

**A invariante, normativa.**

> **O runtime nunca escreve em `graphs/`.** O arquivo versionado é a **declaração**. Tudo que o runtime decide — concorrência efetiva, ordem escolhida, degradação do gate, worktree criado, baseline pulado por flag, e qualquer reparo futuro — é registrado em `state.json.deviations` como **desvio declarado contra a declaração**, e **nunca** volta para o YAML.

Cada desvio carrega quatro campos: `kind`, `declared`, `effective`, `why`. Lado a lado, porque um desvio sem o que ele desviou não é registro, é log.

**Como é provada.** `preflight.declaration_tree_sha256` é gravado antes do primeiro nó e reconferido depois do último (`..._after`). O teste `test_runtime_never_writes_the_declaration` tira o hash da árvore `graphs/` antes e depois de um `up` completo, **incluindo o caminho em que o gate degradou a concorrência**. Se algum dia alguém implementar mutação de topologia, o teste quebra e a pessoa é obrigada a decidir conscientemente — que é o ponto.

**Onde a mutação de topologia entra, se entrar.** Por aqui, e só por aqui: uma mutação futura escreve uma **cópia** no `session_dir` e um desvio em `state.json`; ela **não** edita `graphs/*.yaml`. O campo `state.json.mutations` (§1.5, vazio no v1) é o lugar dela. Uma mutação que edita o arquivo versionado destrói a comparabilidade entre runs — o `team_fingerprint` do run deixaria de descrever o que rodou — e é por isso que ela é recusada por invariante, não por gosto.

> **Escolhida / descartada.** Desvio registrado no ledger, não aplicado à declaração. Custo: o operador que quer "salvar o que funcionou" tem que editar o YAML à mão, lendo o desvio. Ganho: a declaração continua sendo o que **um humano decidiu**, e o `state.json` continua sendo o que **a máquina fez** — e a pergunta "o grafo declarado é o grafo executado?" continua tendo resposta. Descartado o auto-tuning que reescreve o grafo: é a feature que faz o repo parar de poder responder essa pergunta, e ela é a propriedade que o produto vende.

> **Escolhida / descartada.** A ordem de lançamento é gravada como desvio, mesmo não sendo "desvio" de nada declarado. Custo: uma linha de ruído em toda sessão. Ganho: o `ready_set` recalculado é a decisão dinâmica mais invisível do sistema, e sem o registro não há como reconstruir por que dois runs do mesmo time tiveram paredes diferentes.

---

### Emenda C — 2026-08-31 · `auto` degrada quando falta `git worktree`; `1..3` explícito recusa

**O que muda.** A §2.1 lista *"concorrência > 1 com `git worktree` indisponível"* entre as recusas de preflight. A emenda mantém a recusa (exit 40) para `--max-concurrency 2` ou `3` **explícito**, e faz `--max-concurrency auto` **degradar para 1**, com aviso no stderr e o motivo gravado em `preflight.isolation_note` e num desvio `isolation`.

Rodar `k > 1` **sem** isolamento por instância continua não sendo opção em nenhum caminho.

> **Escolhida / descartada.** Custo: a mitigação vira condicional, e alguém que roda `auto` num diretório sem git recebe concorrência 1 sem ter pedido — exatamente o que a §2.1 queria evitar ao recusar. Ganho: `auto` é, por definição, o modo que degrada — ele já degrada por `utilization` (§3.4), e degradar por ausência de worktree é a mesma política aplicada a outro recurso. E recusar ali quebra a promessa de que alguém clona o repo e roda um comando: o primeiro contato passa a ser um erro de preflight sobre uma feature que o usuário não pediu. Descartado recusar sempre: transforma o default numa armadilha para quem nunca vai usar fanout. Descartado degradar sempre: um operador que **escreveu** `--max-concurrency 3` pediu paralelismo isolado, e entregar 1 em silêncio é o "ajuste silencioso" que a §2 proíbe em outra linha.

---

### Emendas nomeadas e adiadas — 2026-08-31

Avaliadas nesta rodada, **fora do código por corte de escopo**, e registradas aqui para não parecerem esquecidas:

- **O humano como nó do grafo.** Um nó cujo executor é a sessão interativa do dono, com contrato de escrita próprio, aparecendo no `state.json` e no veredito como qualquer outro nó. Nenhum dos quatro concorrentes tem. Esbarra na arbitragem 2 (§0): um nó headless não tem canal para pedir; um nó humano precisaria do canal que o v1 não tem. Entra quando `--input-format stream-json` for verificado.
- **A sessão de trabalho real produz veredito.** Hoje o veredito existe para o experimento. Se toda sessão de código real também produzir um número comparável, o instrumento sai da bancada. Depende de um `baseline` que faça sentido fora de uma tarefa congelada, e isso ainda não foi desenhado.
- **Contrato de escrita e parada verificável como produto autônomo.** É a tese de reserva do pesquisador, registrada na §9: mesmo com o grafo empatando com o solo, `writes` verificados por diff de árvore, orçamento com corte real, parada por `check` determinístico e `permission_denials` respeitados continuam sendo valor que nenhum dos três concorrentes entrega. Já está quase todo implementado; falta a superfície que o vende como tal.

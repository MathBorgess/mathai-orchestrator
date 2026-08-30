# START — o passo a passo do arranque

**Data:** 2026-08-30 · **Issue:** [MAT-96](https://linear.app/borgesmathai/issue/MAT-96) (spec) → [MAT-97](https://linear.app/borgesmathai/issue/MAT-97) (implementa)
**Base:** [`MVP.md`](MVP.md) · [`EXPERIMENTO.md`](EXPERIMENTO.md) · [mesa-redonda](research/2026-08-30-mesa-redonda.md)

Como sair de zero até "roda de verdade" o mais rápido possível, usando paralelismo de subagentes sem produzir três implementações de três contratos diferentes.

---

## 0. Regra de entrada

Duas coisas antes de qualquer linha de runtime, e elas não são negociáveis nesta ordem:

1. **G1 (14/09) e proposta (21/09) entregues.** Nenhuma antecipação de trabalho de orquestrador para dentro dessa janela.
2. **arXiv:2604.17883 lido na íntegra**, com um parágrafo dizendo se ele já mede topologia de time. Se já mede, o projeto muda de pergunta antes de existir.

O que **pode** ser feito agora, sem escrever runtime, está na Onda 0.

---

## 1. O corte — o menor caminho até "roda de verdade"

**~250 linhas.** O marco é literal: `orch up graphs/v0.yaml` sobe o `scout`, e `handoff.md` aparece em disco com o predicado de quatro condições satisfeito. Tudo antes disso é obrigatório; tudo depois é crescimento.

| Camada | Itens | Paralelizável? |
|---|---|---|
| **0 — esqueleto e preflight** | 1 `cli.py` (`up`, args, criação do session_dir, cópia do graph, `state.json` inicial) · 2 `graph.py` (load + validação **que recusa**) · 3 `env.py` (allowlist + preflight cacheado) | **serial**, é a base |
| **1 — um nó ponta a ponta** | 4 `outcome.py` (o dataclass) · 5 `adapters/claude.py` (build, spawn em process group, captura de `logs/<node>.jsonl`, parse da última linha `result`) · 6 `state.py` (escrita atômica: tmp + `os.replace`) | serial até o item 4 |
| **2 — a aresta e a parada** | 7 predicado de aresta (`artifact_exists` + `mtime > started_at` + bloco `verify`) · 8 linha de handoff no log + `events.jsonl` · 9 critério de parada e exit code da sessão | serial |
| **3 — robustez** | 10 timeout no pai + `killpg` · 11 classes de falha + retry semântico com `--resume` · 12 acumulador de orçamento + gate de rate limit · 13 `orch doctor` | **paralelo entre si** |
| **4 — paralelo** | 14 `worktree.py` · 15 scheduler de conjunto pronto + `--max-concurrency` (default 1) · 16 `flock` por artefato e lock de commit | 14 antes de 15 |
| **5 — segundo adapter e ACL** | 17 `adapters/cursor.py` + `adapters/exec.py` · 18 campo `tools:` → `--allowedTools`/`--disallowedTools` | **paralelo** |
| **6 — o veredito** | 19 coletor de métricas a partir de `state.json` + hashes · 20 runner do `baseline` · 21 a tabela impressa no fim do `up` | 19 e 20 paralelos, 21 depois |

**A dependência serial sem atalho:** `1 → 3 → 4 → 5 → 6 → 7 → 9`. E o item 15 (scheduler) exige 6 e 14 prontos — é o último a entrar, e é onde toda regressão de concorrência vai aparecer.

---

## 2. O plano de ondas — onde o paralelismo de subagentes paga

A regra que governa tudo: **o `Outcome` (item 4) é definido antes de qualquer adapter, e é o único acoplamento entre frentes.** Fan-out antes do `Outcome` existir produz três adapters com três contratos, e o custo de reconciliar é maior que o de ter feito serial.

### Onda 0 — agora, sem escrever runtime *(1 sessão, sem subagente)*

Nada aqui depende da regra de entrada porque nada aqui é runtime.

- [ ] Congelar as **12 tarefas** do experimento num arquivo, com hash. *(Pronto: `tasks/frozen.md` commitado, hash no README.)*
- [ ] Instalar `cursor-agent` e **repetir os 20 testes** que foram feitos contra o `claude` (exit code, `-p`, stream, permissões, resume, budget, hang conhecido). *(Pronto: uma tabela `[V]`/`[D]` em `research/`, do mesmo formato do memorial da engenheira.)*
- [ ] Escrever o parágrafo sobre exposição de ToS no README, citando 20/02, 14/05 e 15/06 de 2026. *(Pronto: parágrafo no README, sem eufemismo.)*
- [ ] Ler arXiv:2604.17883 e escrever o parágrafo do §0.2.

### Onda 1 — o esqueleto *(1 sessão, 1 pessoa, SEM fan-out)*

Camadas 0 e 1 inteiras, itens 1–6, fechados por uma pessoa só. **Não abrir subagente aqui.** É onde o modelo do repo nasce; três cabeças produzem três modelos.

*Pronto:* `orch up graphs/v0.yaml --session-dir .sessions/t1` sobe o `scout`, `handoff.md` existe, `state.json` mostra `scout: done` e o predicado de quatro condições aparece no log.

### Onda 2 — o fan-out real *(3 frentes simultâneas, 3 subagentes)*

Só depois do item 4 existir. As três frentes não se tocam em arquivo nenhum:

| Frente | Escopo | Toca | Não toca |
|---|---|---|---|
| **A — adapters** | itens 5 e 17: `claude.py`, `cursor.py`, `exec.py` normalizando para o mesmo `Outcome` | `orch/adapters/*` | `graph.py`, `worktree.py` |
| **B — validação de grafo** | item 2: loader que **recusa** (id ≠ stem, órfão, aresta para nó inexistente, ciclo sem bound, stop inalcançável, writes sobrepostas, dois donos do mesmo artefato) | `orch/graph.py`, `tests/fixtures/*.yaml` | adapters, spawn |
| **C — worktree** | item 14: add / remove / prune, com fixture de repo git | `orch/worktree.py` | adapters, graph |

Cada frente entrega **módulo + teste com fixture**, e nenhuma delas sobe processo de agente — B e C são puras e testáveis em segundos.

**O contrato de spawn de cada frente** (o preâmbulo que vai no prompt do subagente):

```
Você trabalha na frente <X> do orch. Leia MVP.md §<n> antes de escrever.
Toca só: <lista de arquivos>. Qualquer arquivo fora dessa lista é violação
de contrato — pare e reporte em vez de editar.
Depende de: orch/outcome.py (já existe, não altere).
Pronto quando: <teste> passa com fixture e `python -m orch doctor` continua verde.
Não implemente nada além do escopo. Não crie diretório novo.
```

Isso é o mesmo `writes:` do grafo, aplicado ao time humano+agente que constrói o grafo. Se o contrato de escrita vale para os nós, vale para quem os escreve.

### Onda 3 — robustez *(4 subagentes, itens 10–13)*

Itens independentes entre si, cada um num arquivo próprio: timeout+`killpg`, classes de falha+retry, orçamento+rate limit, `doctor`. Fecham em paralelo, integram em série.

### Onda 4 — o veredito *(2 subagentes, itens 19–21)*

Coletor de métricas e runner do baseline em paralelo; a tabela impressa depois dos dois. **Esta onda é o produto** — sem ela o repo é o 215º orquestrador.

### Onda 5 — o experimento

Os 108 runs do [`EXPERIMENTO.md`](EXPERIMENTO.md). Aqui o paralelismo é de **máquina**, não de subagente: sequencial por default, e a concorrência sobe só sob o gate de `utilization`.

---

## 3. O que NÃO paralelizar

| Não abra fan-out em | Por quê |
|---|---|
| Camadas 0 e 1 (itens 1–6) | é onde o modelo nasce; três cabeças produzem três modelos |
| O `Outcome` (item 4) | é o contrato; se ele for negociado em paralelo, não é contrato |
| O scheduler (item 15) | depende de 6 e 14 e é onde toda regressão de concorrência aparece |
| A definição das 12 tarefas | congelar é ato único, com hash |

E a regra geral, que é a mesma que o grafo aplica aos próprios nós: **fan-out ≤ 3 frentes, `writes` disjuntas, convergência num ponto só.** Réplicas 1→3 ganham; 3→5 é marginal ou negativo. Vale para agentes e vale para o time que os constrói.

---

## 4. Definição de pronto, por marco

| Marco | Pronto quando |
|---|---|
| **M1 · roda de verdade** | `orch up graphs/v0.yaml` sobe o `scout`, `handoff.md` existe, predicado de 4 condições no log, `state.json` consistente |
| **M2 · o handoff** | a linha `handoff scout → builder artifact=handoff.md` sai no feed, `builder` só sobe com o artefato válido, sessão sai 0 no gate e 1 na falha |
| **M3 · não trava** | timeout no pai mata o process group inteiro; nenhum órfão segurando worktree; `doctor` verde |
| **M4 · não estoura** | orçamento por nó e por sessão aplicados; gate de `utilization` degradando e dormindo; nenhum retry cego |
| **M5 · o veredito** | `up` imprime a tabela grafo × baseline com ≥5 seeds e `stop_reason` discriminado |
| **M6 · o número** | os 108 runs rodados, relatório escrito, tag no repo |

---

## 5. A primeira coisa a fazer, em uma linha

Não é escrever o runtime. É **congelar as 12 tarefas e medir o braço A** — se o agente solo já resolve, o grafo não tem o que provar, e isso custa uma noite de máquina em vez de seis meses.

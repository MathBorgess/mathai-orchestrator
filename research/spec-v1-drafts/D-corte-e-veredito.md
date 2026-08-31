# SPEC §6–§7 — o corte do v1 e a régua de valor

**Frente D** (devil's advocate) · **Data:** 2026-08-30 · **Escopo de escrita:** só este arquivo.
**Estende:** [`SPEC.md`](SPEC.md) §5–§6 · **Emenda:** [`MVP.md`](MVP.md) §8 e §9 · **Não relitiga:** [`EXPERIMENTO.md`](EXPERIMENTO.md) §4 (bloqueadores G1/proposta/2604.17883/`cursor-agent` seguem valendo na íntegra, e nada aqui os antecipa).

O pedido do dono desta rodada é *"quero ver diversos agentes trabalhando em paralelo, gerando valor"*. São duas frases coladas, e só a segunda é difícil. Paralelismo é a feature mais fácil de demonstrar e a mais fácil de fingir: três terminais piscando produzem a sensação de trabalho independentemente de haver trabalho. Estas duas seções existem para que o produto seja incapaz de entregar a primeira metade sem a segunda.

Toda escolha traz o descarte. Decisão sem alternativa não entra.

---

## 6. O corte do v1

### 6.1 A conta — o escopo não cresce nos dois sentidos

O v0 cortou paralelo por decisão explícita (`SPEC.md` §3: *"Serial no v0, não paralelo... Paralelo é segundo grafo, não esta sessão"*). O v1 o traz de volta. Isso não é gratuito: entram os tipos `fanout` e `join`, o `worktree.py`, o scheduler de conjunto pronto, o `flock` por artefato e o `killpg` por grupo de processo — a camada 4 inteira do [`START.md`](START.md), que é ao mesmo tempo o maior bloco e o único onde toda regressão de concorrência vai aparecer.

Se isso entra e nada sai, o v1 não é um corte, é uma lista de desejos. O ledger, em linhas aproximadas **[estimativa, não medida]**:

| Entra | ~linhas | Sai | ~linhas |
|---|---|---|---|
| `fanout` + `join` como tipos de nó | 60 | superfície ao vivo (`watch`, `ps`) | 60 |
| `worktree.py` (add/remove/prune) | 50 | retry semântico com `--resume` | 50 |
| scheduler de conjunto pronto + slots | 70 | ciclo e `max_repeats` | 40 |
| `flock` por artefato + lock de commit | 30 | motor de partição genérico (fanout de N) | 50 |
| **≈ 210** | | **≈ 200** | |

**Escolhida / descartada.** Trocar quatro peças por quatro peças, em vez de "adicionar paralelo e ver no que dá". Custo: quatro capacidades reais desaparecem do v1, e três delas eram boas. Ganho: o v1 continua sendo uma coisa que uma pessoa termina. Descartada a alternativa honesta e ruim: manter tudo e empurrar o veredito para "depois" — é exatamente assim que este produto vira o 215º orquestrador com YAML.

### 6.2 A tabela de corte

| Peça | **Dentro do v1** | Fora (nomeado, não agora) |
|---|---|---|
| Grafos | `v0.yaml` (cadeia) · `v1-fanout.yaml` (**1 scout → 3 ramos → 1 join**) · `baseline` | registry, loader de pasta, fanout de N arbitrário |
| Nós | `agent`, `check`, `fanout`, `join` | `map`, `reduce`, sub-grafo aninhado |
| Arestas | `artifact_exists`, `artifact_valid`, `check_passed`, `always` | **`check_failed` como retorno** (ciclo), `max_repeats` |
| Concorrência | `--max-concurrency auto` (3, degradando a 1 por `utilization`), teto **3** no schema | 4+, fila distribuída, máquina remota |
| Isolamento | `git worktree` por ramo de fanout; `cwd` para o resto | container, sandbox, VM |
| Adapters | `claude` | `cursor-agent`, `exec` (camada 5 — os 20 testes seguem sendo Onda 0, pesquisa, não runtime) |
| Retry | `transport` (backoff, ≤2) | **`semantic` com `--resume`** |
| Superfície | `up`, `doctor` | **`watch`, `ps`**, `next`, `show`, `say`, `since` |
| Auto-gestão | **nenhuma** | catálogo de reparo, depois do veredito |
| Baseline | **obrigatório, em slot reservado, concorrente ao grafo** | baseline como etapa de roadmap |
| Veredito | 3 números + 1 frase + `verdict.json` | veredito com 15 números (ver §7.1) |

### 6.3 Os quatro cortes, defendidos um a um

**Sai a superfície ao vivo (`watch`, `ps`).** É o corte que mais dói e o que mais precisa acontecer, porque é literalmente a metade decorativa do pedido. `watch` é o painel; o painel é o que 214 concorrentes já têm; e um painel bonito é o mecanismo pelo qual o dono vai confundir "três terminais piscando" com "valor gerado".
**Escolhida / descartada.** `tail -f .sessions/<id>/events.jsonl` cobre 90% do `watch` com zero linha de código nossa, porque o `events.jsonl` já é obrigatório (`MVP.md` §1.4) e já é append-only com uma linha por transição. Custo: nenhuma vista agregada, nenhum spinner, nenhuma sensação. Ganho: o único artefato que o produto oferece para "ver o time trabalhando" é um arquivo de log — e a única coisa bonita que ele imprime é o veredito, no fim. Descartada a TUI, de novo e por escrito: ela é o atrator que transforma este repo em Conductor pobre.

**Sai o retry semântico com `--resume`.** Um nó que saiu `rc=0`, sem `permission_denials`, e não produziu artefato válido, **falha**. Não tenta de novo.
**Escolhida / descartada.** Custo real e conhecido: sessões morrem por um nó que teria acertado na segunda. Ganho duplo, e o segundo é o que decide. (i) Sob concorrência, `--resume` dentro de um worktree que outro ramo pode ter removido é um bug de 3 da manhã com reprodução de uma em vinte. (ii) O retry semântico é a **segunda fonte de não-determinismo dentro do instrumento de medição** — a primeira é o modelo. Um instrumento que conserta silenciosamente o que está medindo não mede. Se um nó precisou de segunda tentativa, **isso é o dado**, não o obstáculo ao dado. Descartado "retry só no baseline para ser justo": aí o baseline vira um braço diferente do grafo, e a comparação morre.

**Sai o ciclo (`check_failed` como aresta de retorno) e o `max_repeats`.** O v1 é DAG estrito, inclusive com fanout. `check_failed` continua existindo como aresta **terminal**: leva o ramo a `failed`, não de volta ao produtor.
**Escolhida / descartada.** Custo: nenhuma recuperação automática; um portão que reprova encerra aquele ramo. Ganho: sob o scheduler de conjunto pronto, um ciclo significa que um nó pode voltar a `ready` enquanto um irmão ainda segura o worktree e o `flock` do artefato — interação que ninguém testou e que a camada 4 não foi desenhada para suportar. E a conta de dinheiro: em serial, um loop custa o orçamento de um nó; com `max_concurrency 3`, custa o de três, e `max_repeats × 3` é exatamente a forma de uma fatura que ninguém pediu. A varredura de 6.549 repos já disse que 100% dos 68 loops infinitos confirmados têm a mesma causa raiz — ausência de bound forte (arXiv:2607.01641). Não vou adicionar ciclo na mesma rodada em que adiciono concorrência.

**Sai o fanout genérico; entra um fanout fixo de 3.** O `v1-fanout.yaml` tem exatamente um `fanout` de 3 ramos e um `join`. Não há motor de partição, nem template de N, nem `for_each` sobre uma lista computada.
**Escolhida / descartada.** Custo: para mudar a largura, o usuário edita o YAML e escreve o terceiro ramo à mão. Ganho: o teto de 3 deixa de ser uma validação e passa a ser uma propriedade estrutural do único grafo paralelo que existe — não há caminho de código onde `max` seja 5. Isso está alinhado com o que já foi medido: 1→3 ganha, 3→5 é marginal ou negativo, e paralelismo estrutural agressivo derrubou acurácia de 28% para 25% (2608.05791). Descartado deixar `max` configurável "com aviso": aviso não segura ninguém às duas da manhã.

### 6.4 Concorrência, e o slot que paga o baseline

**Emenda ao `MVP.md` §6.** O default de `--max-concurrency` deixa de ser `1` e passa a ser `auto`:

```
auto  ⇒  3   enquanto  rate_limit.unifiedWindows.five_hour.utilization < 0.85
         1   quando  utilization ≥ 0.85
         0   (pausa até resetsAt)  quando  utilization ≥ 0.95
         aborta com exit 30  quando  status != "allowed"
```

**Escolhida / descartada.** Custo: a mitigação de ToS deixa de ser "default 1" e passa a ser "default 3 que degrada sozinho". Ganho: o produto passa a fazer a coisa que o dono pediu sem que ele precise lembrar de uma flag — e a degradação por `utilization` é uma política executável sobre um sinal que a própria plataforma emite, o que é mais forte que um default conservador que o usuário desliga na primeira sessão. Descartado manter default 1: um paralelismo que exige flag para existir não existe, e a mitigação vira teatro do outro lado.

**O slot reservado.** `--max-concurrency` conta **nós `agent` do grafo**. O `baseline` roda num **quarto slot, fora da conta**, concorrente ao grafo, desde o início da sessão.

**Escolhida / descartada.** Isto é a peça que faz a rodada inteira fechar. O `MVP.md` §1.5 admitia o custo: *"toda sessão custa ~2×"* — e uma sessão que custa o dobro do relógio é uma sessão em que o operador aprende a desligar o baseline. Com concorrência, o baseline custa **~2× em tokens e ≈0 em parede**, porque roda ao lado. Custo: um processo `claude` a mais vivo o tempo todo, e mais pressão na janela de uso. Ganho: **o paralelismo passa a pagar o baseline obrigatório**, que é a única coisa que separa este produto de um painel. Descartado rodar o baseline depois do grafo: é onde ele vira opcional na cabeça de quem espera.

### 6.5 Critério de parada, literal

**Emenda à `SPEC.md` §5 e ao `MVP.md` §1.1.** `DONE.md` não é critério de nada. A sessão para quando os nós `check` nomeados em `stop` saem 0.

```yaml
stop:
  when: checks_pass
  checks: [gate]          # ids de nós tipo `check`. `agent` no stop é erro de load.
fanout:
  max: 3
  min_branches: 2         # o join sobe com 2 de 3
```

Sequência literal, com concorrência:

1. `stop` alcançado ⇔ **todo** nó de `stop.checks` está `done` com `rc == 0`.
2. No instante em que o `stop` é alcançado, o orquestrador **mata os nós ainda `running`**: `killpg` → grace 5 s → `SIGKILL`; marca `skipped:stop_reached`; remove os worktrees. *Descartado esperar os ramos terminarem por educação: ramo perdido gastando orçamento depois do stop é a fatura que ninguém pediu.*
3. Um ramo de fanout em `failed` **não** mata a sessão enquanto `done ≥ min_branches`. *Com 3 ramos e p(falha)=0,1 por ramo, exigir 3 de 3 mataria 27% das sessões por um ramo. `min_branches: 2` é a resposta, e o custo é resultado parcial declarado no veredito.*
4. Qualquer `failed` **fora** de um fanout encerra a sessão imediatamente, com os mesmos `killpg` e limpeza.
5. `done ≥ min_branches` falso ⇒ o `join` não sobe; sessão encerra.

**Exit codes.** Faixas, para que um script classifique sem parsear texto:

| Código | Significado | Nenhum nó subiu? |
|---|---|---|
| **0** | `stop` alcançado; a sessão é válida e foi medida | — |
| 1 | falha não classificada — **se aparecer, é bug do `orch`**, não do grafo | — |
| 10 | `failed:contract` — nó escreveu fora do `writes`, com o path no erro | não |
| 11 | `failed:permission` — `permission_denials ≠ []` | não |
| 12 | `failed:budget` — teto do nó ou da sessão | não |
| 13 | `failed:timeout` — morto pelo pai | não |
| 14 | `failed:verify` — `rc=0`, sem denials, artefato inválido | não |
| 15 | `failed:branches` — `done < min_branches`; o `join` não subiu | não |
| 20 | `no_progress` — rodadas sem escrita nova acima do limite | não |
| 21 | `wall_seconds` estourado (failsafe incondicional) | não |
| 30 | rate limit: `status != "allowed"`, ou pausa excedeu `resetsAt` | talvez |
| 40 | preflight falhou (`doctor`, `auth status`, versão do CLI) | **sim** |
| 50 | grafo inválido — recusa no load | **sim** |
| 64 | uso incorreto da linha de comando (`EX_USAGE`) | **sim** |

**A regra que não se negocia: o exit code nunca codifica o veredito.** Uma sessão em que o grafo perdeu feio para o baseline sai **0**, porque a corrida foi válida e o número foi produzido. `0` significa *"medi"*, não *"ganhei"*.
**Escolhida / descartada.** Descartado `exit ≠ 0 quando o grafo perde`, que é o instinto de quem quer plugar isso num CI. Custo: o CI não reprova sozinho quando a topologia piora. Ganho: o run perdedor é o dado mais valioso que este instrumento produz, e um exit code vermelho é o convite para escondê-lo, reexecutar até passar, ou remover a comparação do pipeline. Um instrumento que pune o resultado negativo deixa de receber resultados negativos.

### 6.6 O que não se reabre no código

Herdado da `SPEC.md` §6 e do `MVP.md` §9, mais o que esta rodada fechou. Isto não é backlog; é uma lista de coisas já decididas contra.

Da `SPEC.md` §6 — sem API, sem SDK · sem misturar com `mathai-harness` · sem wiki, sem label `hitl` · sem tmux como runtime · sem daemon.
Do `MVP.md` §9 — sem PTY como runtime · sem `--bare` · sem bus ou chat entre nós · sem sumarizador LLM · sem TUI full-screen · sem auto-gestão antes do veredito.

Desta rodada:

- **Sem malha entre ramos.** Um ramo de fanout não lê o artefato de outro ramo, não manda mensagem, não sabe que os outros existem. O único ponto de convergência é o `join`. *Malha entre ramos é o Maestri por PTY com outro nome, e a detecção de fim de turno dele é heurística de foco — não vamos reimplementar uma heurística pior.*
- **Sem `max` de fanout acima de 3**, nem no schema, nem por flag, nem por variável de ambiente.
- **Sem ciclo e sem `max_repeats` no v1.**
- **Sem retry semântico.**
- **Sem `--no-baseline` dentro do YAML** — ver §7.4.
- **Sem exit code que codifique o veredito.**
- **Sem juiz LLM em métrica nenhuma.** Custa um turno, reintroduz não-determinismo, e a variante com juiz a cada rodada já custou +129% de tokens sem ganho (2606.27009).
- **Sem métrica não calibrada no veredito.** Ela pode existir no diagnóstico, marcada como não calibrada. Não pode participar de uma decisão.
- **Sem commit por nó.** Worktree isola o working tree, não o `.git/index.lock` nem o object store. Só o pai commita, serializado.
- **Sem métrica de vaidade** — estrela, fork, view, impressão. Não entram no veredito, no README, nem na coleta.

Se o CLI `claude -p` mudar de flag, ou se o campo `rate_limit_event` mudar de forma, **emenda datada neste arquivo antes de adaptar o código** — e `orch doctor` é quem descobre, não uma sessão no meio da noite.

---

## 7. O veredito, e a régua de valor

### 7.1 O problema de ter 15 números

**Emenda ao `MVP.md` §8.** Aquele §8 lista 5 famílias e ~20 métricas, e imprime uma dúzia. Isso não é um veredito; é um painel em modo texto — o mesmo produto que o §6.3 acabou de cortar, apenas sem cores. Um veredito é uma coisa que **decide**, e uma decisão com quinze entradas não é uma decisão, é uma discussão.

Regra estrutural desta seção:

> **O veredito tem 3 números e 1 frase. O diagnóstico tem o resto, e só é impresso quando o veredito reprova. `verdict.json` tem tudo, sempre, para quem quiser.**

Nada do `MVP.md` §8 é perdido. Tudo é rebaixado de manchete a evidência.

### 7.2 A régua — o que separa paralelismo útil de paralelismo decorativo

Comece pelo que paralelismo **pode** comprar. Rodar três agentes ao mesmo tempo não torna a saída melhor: torna a saída **mais cedo**. Qualquer afirmação de que 3 ramos produzem resultado superior é uma afirmação sobre diversidade e ensemble, não sobre paralelismo — e essa é outra tese, com outro experimento. Então a régua tem que perguntar, nesta ordem: **comprei relógio? paguei quanto? estraguei alguma coisa?**

Os três números, todos deriváveis de `state.json` + hashes, sem API e sem juiz:

**1 · `speedup` = Σ `node.wall_seconds` ÷ `session.wall_seconds`**
O trabalho total dividido pelo tempo de parede. É exatamente o que a execução serial do mesmo grafo teria custado, porque cada nó roda uma vez de qualquer jeito.
**Escolhida / descartada.** Descartado rodar o mesmo grafo uma segunda vez com `--max-concurrency 1` para obter o denominador honesto: dobra a fatura para medir uma coisa que a soma já dá. Custo: ignora o overhead do scheduler, então superestima o serial em alguns pontos percentuais. Ganho: é grátis, sai do dado que já existe, e o erro é pequeno e conhecido.
**É este o número anti-teatro.** `speedup ≈ 1,0` com três ramos declarados significa que o grafo **não é paralelo** — é uma corrente com fantasia de fanout, e os três terminais piscando estavam esperando um ao outro.

**2 · `cost_ratio` = `log_bytes(grafo)` ÷ `log_bytes(baseline)`**
O que o relógio comprado custou. `log_bytes` é proxy de token de saída, declarado como proxy.

**3 · `delta_gate` = `gate_first_pass(grafo)` − `gate_first_pass(baseline)`**
O portão determinístico do `stop` passou de primeira mais vezes com o grafo do que com um nó só? Zero é neutro; negativo é regressão.

**O portão, em uma linha:**

```
paralelismo ÚTIL  ⟺  speedup ≥ 1.50  ∧  cost_ratio ≤ 2.50  ∧  delta_gate ≥ 0
```

Reprovar qualquer um dos três é reprovar. Os três limiares são pré-registrados e mudam por emenda datada, nunca depois de ver um resultado.

**O que ficou de fora do veredito, e por quê.** `orphan_writes`, `null_writes`, `handoff_uptake`, `rework`, retrabalho por ramo, utilização de janela por ramo, `branch_wall`, `write_violations` — **nenhum entra na régua**. Motivos, nominais: `handoff_uptake` é proxy de 6-grama declaradamente não calibrado, e número não calibrado que participa de decisão contamina a decisão; utilização de janela mede a plataforma, não o grafo; `rework` é a métrica **primária do [`EXPERIMENTO.md`](EXPERIMENTO.md) §3**, comparada entre braços com repetições, e uma sessão isolada não tem n para falar em mediana de rework. Todos continuam sendo coletados, todos vão para o `verdict.json`, e todos aparecem no **diagnóstico** — cujo trabalho não é decidir, é explicar *por que* o veredito reprovou.

### 7.3 O formato impresso

**Caso A — passou.** Sem diagnóstico; um ponteiro para o JSON.

```
veredito  graphs/v1-fanout.yaml  vs  baseline(1 nó)      tarefa: mat-96-spec      seed 3/5
──────────────────────────────────────────────────────────────────────────────────────────
  speedup       2.31×    (Σ nós 00:47:02  ÷  parede 00:20:20)          ok    ≥ 1.50
  cost_ratio    2.11×    (log_bytes 1.44 MB ÷ 0.68 MB)                 ok    ≤ 2.50
  delta_gate    +0.33    (grafo 3/3 · baseline 2/3)                    ok    ≥ 0

  VEREDITO: paralelismo ÚTIL.
  3 ramos compraram 2,3× de relógio por 2,1× de custo, sem regressão de portão.

  1 seed não decide. Esta é a amostra 3 de 5.   →  .sessions/t7/verdict.json
```

**Caso B — o caso que o dono precisa ver, e que este produto existe para conseguir imprimir.**

```
veredito  graphs/v1-fanout.yaml  vs  baseline(1 nó)      tarefa: mat-96-spec      seed 3/5
──────────────────────────────────────────────────────────────────────────────────────────
  speedup       1.12×    (Σ nós 00:41:08  ÷  parede 00:36:44)       REPROVA   < 1.50
  cost_ratio    2.83×    (log_bytes 1.94 MB ÷ 0.68 MB)              REPROVA   > 2.50
  delta_gate    +0.00    (grafo 2/3 · baseline 2/3)                 neutro

  VEREDITO: paralelismo DECORATIVO.
  os 3 ramos custaram 2,8× e entregaram o mesmo que 1 nó, em 89% do tempo.

  diagnóstico (impresso porque o veredito reprovou)
    speedup_max      1.31×   teto do seu DAG. 82% da parede está no caminho
                             crítico scout → join; o fanout não tem o que paralelizar.
    efficiency       0.85    (1.12 ÷ 1.31) o scheduler não é o gargalo — a topologia é.
    join_wall        00:19:40   54% da parede inteira num nó só
    branch_wall      b1 00:12:31 · b2 00:11:58 · b3 00:12:02   (desbalanço 4%)
    orphan_writes    2       b2 e b3 escreveram artefato que nenhum nó `reads`
    null_writes      1       b3 reescreveu byte-idêntico (step repetition)
    write_violations 0
    handoff_uptake   0.41    [proxy de 6-grama — NÃO calibrado, não decide nada]
    rate_limit       five_hour 0.31 · seven_day 0.12   (sem degradação)
    stop_reason      gate 1 · skipped:stop_reached 2 · failed 0

  leitura: mova trabalho do `join` para os ramos, ou pare de usar fanout nesta
  tarefa. Não aumente `max`.

  1 seed não decide. Esta é a amostra 3 de 5.   →  .sessions/t7/verdict.json
```

**Escolhida / descartada.** O diagnóstico é impresso **só na reprovação**. Custo: quem passou não vê os detalhes sem abrir o JSON. Ganho: o volume de texto do comando é inversamente proporcional ao sucesso, o que é o incentivo certo — e ninguém aprende a ignorar um bloco que só aparece quando há problema. Descartado imprimir sempre: em duas semanas vira ruído que o olho pula, e aí voltamos a ter um painel.

**A frase do rodapé é obrigatória em todo veredito.** *"1 seed não decide"* — a mesma célula, com modelo pinado, já deu expoente 1,76 e 2,44 em duas coletas. O piso é 5 seeds por célula antes de qualquer decisão de desenho, e o comando é obrigado a lembrar disso na cara de quem rodou uma vez.

### 7.4 A cláusula do baseline

**O `up` roda o baseline. Não é opção do grafo.**

1. `baseline:` é **campo obrigatório** do YAML. Grafo sem baseline é **recusado no load, exit 50**, junto com nó órfão e ciclo — não é aviso, é erro de compilação.
2. O baseline sobe no **slot reservado** (§6.4), concorrente ao grafo, desde o início.
3. Existe uma saída, e ela é de linha de comando: `orch up --no-baseline`. Ela faz quatro coisas, todas visíveis:
   - imprime, antes de subir qualquer nó: `SEM BASELINE — esta sessão não produz veredito.`
   - grava `"baseline": null, "comparable": false` no `state.json`, permanentemente;
   - **não escreve `verdict.json`** — não escreve um veredito parcial, não escreve um com campos nulos;
   - no fim, no lugar da tabela: `veredito: INDISPONÍVEL (--no-baseline)`.
   - a sessão ainda sai **0** se alcançou o `stop`. Rodar sem medir não é erro; é só não ser este produto naquela vez.
4. **`--no-baseline` não pode ser expresso no YAML, nem em config de projeto, nem em variável de ambiente.** É flag de invocação, uma sessão por vez.

**Escolhida / descartada.** Descartado proibir totalmente: o operador forka, apaga a linha, e aí perdemos até o registro de que aquela sessão não foi medida — a proibição absoluta compra pureza e vende observabilidade. Descartado permitir no YAML: em uma semana vira o default do projeto, em duas ninguém lembra que existiu comparação, e o produto volta a ser painel por erosão em vez de por decisão. Custo desta escolha: o operador teimoso digita a flag toda vez. Ganho: **a saída existe mas não pode virar hábito**, porque hábito mora em arquivo versionado e esta flag é proibida de morar lá.

### 7.5 A condição em que este produto continua não merecendo existir

Esta seção não é ritual. É a razão pela qual eu assino o resto.

**Suponha que tudo dê certo.** O scheduler funciona, `speedup` bate 2,3×, `cost_ratio` fica em 2,1×, `delta_gate` é zero, e o veredito imprime **paralelismo ÚTIL** em 5 seeds × 12 tarefas. Neste cenário — o melhor cenário realista — o que exatamente foi comprado?

**Relógio.** Só isso. `delta_gate = 0` quer dizer que a saída é a mesma; o que mudou é que ela apareceu antes. E aí vem a pergunta que mata:

> Latência só tem valor quando alguém está bloqueado nela. A premissa inteira deste produto é `claude -p` headless, sem TTY, sem humano na frente. **Paralelismo headless é otimizar a latência de um processo que ninguém está esperando.** Economizar vinte minutos de máquina, por 2,1× em tokens, para que o arquivo apareça mais cedo numa madrugada em que o dono está dormindo, é pagar caro por uma melhoria que ninguém consome.

Então a condição, escrita como teste e não como sentimento: **se em 5 seeds × 12 tarefas o resultado modal for `speedup ≥ 1,5` com `delta_gate ≈ 0`, o paralelismo está funcionando e mesmo assim não deveria ter sido construído** — porque o benefício é um cronômetro numa corrida que ninguém estava assistindo. O corolário prático é desconfortável e eu quero ele impresso: nesse caso, a resposta certa não é ajustar a topologia, é **rodar o baseline sozinho e ir dormir**.

Mais três condições, mais curtas, todas com forma de teste:

**Se `delta_gate` for consistentemente negativo** — o que a literatura sugere como default: procedimento inteiro no prompt bate orquestração em 15/15 comparações em tarefa procedural (2604.27891), a *collaboration tax* é positiva em quase toda célula e **decresce com a capacidade do modelo** (2608.22152). O segundo achado é o mais corrosivo: se o ganho de coordenação encolhe conforme o modelo melhora, este produto está construindo contra a curva. O modelo do ano que vem é o concorrente, e ele não tem mantenedor.

**Se o `orch doctor` quebrar mais de uma vez por trimestre** por deriva de CLI. O `MVP.md` §10 R2 já registra que `--append-system-prompt-file` funciona e não está no `--help`; só o doc de Agent Teams mudou comportamento em oito versões numa feature só. Wrapper de CLI de terceiro é dívida com juros pagos pelo mantenedor, para sempre, sem receita. Duas quebras por trimestre e o custo de manutenção passa o valor do veredito.

**Se a moratória de junho acabar.** 20/02/2026 a Anthropic baniu OAuth de assinatura fora do Claude Code; 14/05 anunciou mover `-p` e o Agent SDK para pool de créditos separado; 15/06 pausou, prometendo "reformular". É moratória, não garantia — e o adapter `exec` é a saída, não a resposta.

**E a que já está escrita e continua valendo:** se, depois dos 108 runs, o grafo empatar com o baseline dentro do ruído, o valor remanescente do repositório é a camada de **contrato** — `writes` verificados por diff de árvore, orçamento com corte real, parada por `check` determinístico, `permission_denials` respeitados — acima de CLIs que não têm nada disso. É a tese do `MVP.md` §10 R4, é mais defensável que a original, **e ela não precisa de paralelismo nenhum.** O que significa que, nesse desfecho, a camada 4 inteira terá sido construída para nada.

Nada disso é motivo para não começar. É motivo para começar **pela medição**, com o baseline obrigatório no slot reservado e o veredito de três números — que é exatamente o corte desta seção. Se o número vier ruim, o repositório publica o resultado negativo, ganha a tag `v0.1-negative-result` e é arquivado com motivo escrito, na íntegra da cláusula de morte do [`EXPERIMENTO.md`](EXPERIMENTO.md) §5.

O pior desfecho possível para este projeto não é o grafo perder para o baseline. É o grafo perder e ninguém ter medido, porque a tela estava bonita.

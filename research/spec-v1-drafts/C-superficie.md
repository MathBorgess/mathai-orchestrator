# 5. A superfície — como o dono vê N nós trabalhando

**Autor:** Alex (design de experiência de time) · **Data:** 2026-08-30
**Estende:** `MVP.md` §4 (superfície serial) · **Emenda:** §4 continua válido para `--max-concurrency 1`; tudo abaixo é o que muda quando há 2+ nós vivos.
**Depende de:** `MVP.md` §1.4 (`state.json` como ledger, `events.jsonl` append-only), §3 (ciclo de vida), §6 (paralelismo, orçamento), §8 (veredito).

O dono pediu para **ver** diversos agentes trabalhando em paralelo, gerando valor. As três palavras carregam três requisitos diferentes e só um deles era resolvido pelo desenho serial:

| Palavra | Requisito | Estava resolvido? |
|---|---|---|
| **ver** | leitura em 5 segundos, sem parar o que se estava fazendo | não — feed serial exige leitura sequencial |
| **em paralelo** | distinguir 3 frentes num único canal | não — feed serial tinha ordem de graça |
| **gerando valor** | separar avanço de repetição, no meio da run | não — o veredito só existia no fim (§8) |

O que segue resolve os três. **A tese: com N vivos, o feed deixa de ser a tela principal.**

---

## 5.0 A inversão — `orch ps` promovido, `orch watch` rebaixado

No desenho serial, o feed *era* o time: um nó vivo = uma voz = o canal é um monólogo, e a ordem cronológica é a ordem causal. Com 3 nós, o feed vira o que eu mesmo diagnostiquei como o modo de falha número um de canal de trabalho — três frentes intercaladas num fio só, ilegível em 20 minutos.

Chat de trabalho já resolveu isso e a resposta não é renderizar melhor a mangueira. Ninguém conserta um workspace ocupado escrevendo um `#general` melhor: conserta promovendo a **sidebar com contagem de não-lido** a superfície primária e rebaixando o canal a drill-down. É o mesmo movimento aqui.

**Escolhida / descartada.** Superfície primária = **tabela de raias que se repinta** (`orch top`); feed cronológico = drill-down (`orch watch`). Custo: um comando novo, e o dono precisa aprender que o feed não é mais onde ele mora. Ganho: "ver 3 agentes trabalhando" passa a ser 8 linhas que mudam, não 300 linhas que rolam — e uma tabela que muda comunica *time trabalhando* melhor que um log que rola, porque log que rola comunica *volume*, não progresso. Descartada a alternativa óbvia: manter o feed como tela principal e resolver por render. Não dá — o problema não é a renderização de 3× eventos, é que 3× eventos não têm uma ordem que valha a pena ler linearmente.

Comandos, agora sete:

```
orch up      sobe a sessão                                   (SPEC v0)
orch top     a tela do time — tabela de raias, repinta        [NOVO]
orch watch   o feed cronológico — drill-down, stdout puro
orch ps      snapshot da tabela, uma vez, sem repintar
orch next    a próxima coisa que precisa de você
orch show    um evento, uma raia, o log de um nó
orch say     mensagem para um nó (entregue no próximo turno)
```

`orch ps` é `orch top --once`. Mesmo código, mesma saída, um repinta e o outro não.

---

## 5.1 A tela do time — `orch top`

```
session .sessions/2026-08-30-mat97   graph v2   up 00:08:41   conc 3/3
────────────────────────────────────────────────────────────────────────────────
3 vivos · 2 avancando · 1 GIRANDO (draft-cli 4m12s) · artefatos 5/9 validos
$1.42/$5.00 · janela 5h 61% · 1 ASK esperando voce
────────────────────────────────────────────────────────────────────────────────
LN NODE        ST    T+     IT  COST   PULSO  WRITES                     LAST
a  draft-api   RUN   04:12   3  $0.31  ++·+·  api/openapi.yaml   +88L    3 paths escritos
b  draft-cli   SPIN  04:12   7  $0.74  ·····  cli/spec.md         ~0     reescreveu, mesmo sha
c  draft-web   NEED  02:03   2  $0.18  +·~·+  web/spec.md        +12L    ASK#7 /auth rota?
   merge       WAIT   —      —   —      —     (join requires 3)          espera a, b, c
   gate        WAIT   —      —   —      —     (check bin/gate.sh)        espera merge
   draft-doc   FAIL  06:33   5  $0.19  ·+···  —                          failed:timeout 600s
────────────────────────────────────────────────────────────────────────────────
ASK#7 raia c bloqueia 2 nos a jusante · aberta 00:41       orch next
```

Sete colunas, e cada uma responde uma pergunta que o dono faz em voz alta:

| Coluna | Pergunta que responde |
|---|---|
| `LN` | qual frente? (vazio = nó fora de raia: join, check, nó serial) |
| `NODE` `ST` | quem, em que estado |
| `T+` | há quanto tempo neste estado — não desde o início da sessão |
| `IT` `COST` | o **denominador**: turnos e dinheiro queimados |
| `PULSO` | o **numerador**: o que saiu, amostra a amostra |
| `WRITES` | o artefato de que este nó é dono, e o delta |
| `LAST` | a última coisa que ele mesmo disse (`summary`, ≤72) |

**Escolhida / descartada.** Tabela com colunas fixas e alinhadas, sem indentação por raia e sem desenho de swimlane. Custo: o olho não segue uma linha vertical contínua por raia. Ganho: as colunas alinham, e num painel ocupado o olho lê *para baixo numa coluna* (todos os `ST`, todos os `PULSO`) muito mais do que segue uma raia. É o princípio de posição fixa que faz lazygit e k9s funcionarem: consistência espacial vira navegação. Descartado o swimlane com barras verticais: custa `n` colunas, quebra o alinhamento e serve para acompanhar uma raia — que é exatamente o que `orch watch --lane b` já faz melhor.

**Escolhida / descartada.** `orch top` lê **só** `state.json` + `events.jsonl`, read-only, fora do processo do `up`. Custo: a tela está atrasada em até um intervalo de amostra. Ganho: você pode rodar zero, um ou três `orch top` que a sessão não sabe e não se importa; ele não pode travar, corromper nem alterar a run. Descartada a tela dentro do processo do `up`: acopla observação a execução, e uma run que muda porque alguém estava olhando é uma run que não serve de medida (§8).

### 5.1.1 O PULSO — o único indicador de "trabalhando" que não mente

Cinco caracteres, uma amostra cada (30 s), mais recente à direita:

```
+  o artefato de writes cresceu desde a amostra anterior
~  reescrito, mesmo tamanho ou mesmo sha            (thrash)
-  encolheu
·  nada mudou em writes
```

`++·+·` = avançando. `·····` = girando. `~~~~~` = reescrevendo o mesmo arquivo em círculo — o pior dos três, porque parece atividade.

Isto é derivado direto do que o `state.json` já guarda por decisão do §1.4: `artefatos {path, sha256, mtime}` e `budget.iters_used`. **Zero instrumentação nova.**

**Escolhida / descartada.** Pulso mede **saída em disco**, não atividade do processo. Custo: um nó que passa 3 minutos legítimos lendo antes de escrever aparece como `···`. Mitigação: o `T+` e o `LAST` estão ao lado, e o `SPIN` só dispara com `IT` subindo junto. Ganho: é impossível fingir. Descartado medir bytes de log, tokens, ou "está gerando output": todos sobem quando o agente conversa consigo mesmo, que é exatamente o estado que eu quero denunciar.

E o argumento que fecha com o desenho serial: eu cortei typing indicator porque presença social não vale nada num agente e o que sobra do indicador é informação de progresso. **O pulso não é presença, é entrega.** Mede o que saiu, não o que está acontecendo lá dentro. É o mesmo argumento, agora com uma coluna que o implementa.

### 5.1.2 `SPIN` — o estado que o paralelismo obrigou a nomear

O `MVP.md` §3 define 7 estados de runtime. **A tela não inventa um oitavo.** `SPIN`, `NEED` e `STAL` são **qualificadores** de `running`, calculados numa função só, `qualify(node)`:

| Na tela | state.json | Condição do qualificador |
|---|---|---|
| `RUN` | `running` | nenhuma das abaixo |
| `SPIN` | `running` | `iters_used` subiu **e** pulso `·` ou `~` nas últimas 3 amostras |
| `NEED` | `running` | ASK `blocking: true` aberto e não-stale |
| `STAL` | `running` | nenhum evento há > 5 min (R3) |
| `VRFY` | `verifying` | — |
| `WAIT`/`RDY`/`DONE`/`FAIL`/`SKIP` | idem | — |

**Escolhida / descartada.** Qualificador derivado, não estado novo. Custo: dois vocabulários — o do runtime e o da tela — que precisam ser lidos juntos para debugar. Mitigação: `orch show <node> --state` imprime os dois lado a lado. Ganho: a tela nunca vira uma segunda verdade sobre o grafo, e o `state.json` continua single-writer como o §1.4 exige. Descartado promover `SPIN` a estado de runtime: aí o scheduler teria que reagir a ele, e reagir a heurística de progresso é o caminho para o orquestrador matar nó lento que estava certo.

### 5.1.3 A linha de status — o veredito parcial

```
3 vivos · 2 avancando · 1 GIRANDO (draft-cli 4m12s) · artefatos 5/9 validos
$1.42/$5.00 · janela 5h 61% · 1 ASK esperando voce
```

Esta é a resposta literal a "está gerando valor?" em 5 segundos, e cada termo é mecânico:

- **avançando** := pulso ≠ `·····` na última amostra, **ou** um `check` virou verde desde a amostra anterior. Não é opinião.
- **artefatos X/Y válidos** := `verify()` passou, contra o total declarado nos `writes` do grafo. É a única moeda forte do sistema.
- **$ e janela** := §6, já existem. A janela de 5 h aparece aqui porque em `utilization > 0.85` a concorrência degrada para 1 e o dono precisa saber *por que* o time encolheu sozinho.

**Escolhida / descartada.** A linha de status é computada dos **mesmos campos** do veredito final do §8. Custo: nenhum — é o mesmo `GROUP BY`, avaliado antes do fim. Ganho: o dono passa o dia lendo a versão parcial do relatório que vai receber no fim, então ele já sabe ler o relatório final; e não existe uma segunda métrica de progresso competindo com a métrica oficial. Descartado inventar um "score de saúde" para a tela: seria uma segunda verdade, e a primeira coisa que alguém faria é otimizar para ela.

---

## 5.2 O feed com 3 nós concorrentes — `orch watch`

```
$ orch watch

session .sessions/2026-08-30-mat97  graph v2  raias a=api b=cli c=web
────────────────────────────────────────────────────────────────────────────────
14:20:03 a| >   draft-api  start     prompts/draft.md · wt/a · part=api
14:20:03 b| >   draft-cli  start     prompts/draft.md · wt/b · part=cli
14:20:04 c| >   draft-web  start     prompts/draft.md · wt/c · part=web
14:21:11 a| .   draft-api  note      openapi 3.1, 3 paths escritos
14:21:52 b| ~   draft-cli  coalesce  +4 notes em 40s (orch show b --notes)
14:22:02 c| ?   draft-web  ASK #7    /auth vira rota ou header? bloqueia 2   VOCE
14:22:02 c| ||  draft-web  blocked   ask#7
14:23:15 a| >>  draft-api  handoff   merge  api/openapi.yaml  88L +88-0  valid
14:24:50 b| ~   draft-cli  spin      3 amostras sem delta, iters 7          OLHAR
14:31:02 b| !   draft-cli  fail      failed:timeout 600s · killpg ok
────────────────────────────────────────────────────────────────────────────────
1 ASK · 1 FAIL · orch next
```

Três mecanismos, nesta ordem de importância:

**(1) Raia como prefixo fixo, atribuída pela partição declarada — nunca pela ordem de chegada.**

A raia vem da chave de partição do `fanout` (§1.1), ordenada alfabeticamente: `part=api → a`, `part=cli → b`, `part=web → c`. Nós fora de raia (join, check, nó serial) recebem coluna vazia.

**Escolhida / descartada.** Raia derivada da partição declarada. Custo: se o grafo mudar a ordem das partições, as letras mudam. Ganho: **duas execuções do mesmo grafo produzem exatamente as mesmas letras nas mesmas raias**, e os dois `events.jsonl` ficam diffáveis linha a linha. Isso não é estética: o produto inteiro é um banco de provas que compara runs (§0, §8), e um log cuja rotulagem depende de quem ganhou a corrida do spawn é um log incomparável. Descartada a atribuição por ordem de chegada (mais simples, uma linha de código): destrói a comparabilidade que é a razão de o produto existir.

O prefixo é ` a|` — dois caracteres numa posição fixa, greppável como token: `orch watch | grep ' b|'`. E `orch watch --lane b` é o caminho principal.

**(2) Orçamento de linhas por raia — a coalescência.**

Cada raia tem um balde: **no máximo 1 linha de `kind: note` a cada 15 s**. O excedente vira uma linha sintética `coalesce +N notes em Ts`, com o contador visível e o corpo íntegro em disco.

**Nunca são coalescidos:** `start`, `handoff`, `ask`, `blocked`, `fail`, `spin`, `stall`, `done`, `branch`, `reeval`. Ou seja: **eventos estruturais têm prioridade absoluta sobre tagarelice**, que é a mesma decisão que todo canal de trabalho saudável toma.

**Escolhida / descartada.** Limitar `note` por raia, com contador. Custo: você não vê 4 das 5 notas ao vivo — precisa de `orch show`. Ganho: 3 raias falantes não afogam o `ASK` da quarta, e nada é escondido (o número está lá, o arquivo está lá). Descartada a alternativa de truncar o feed globalmente: um nó tagarela roubaria as linhas dos outros dois, que é o pior comportamento possível num canal compartilhado. Descartada também a alternativa de não limitar: 3× o volume com `note` livre é a parede de texto que este desenho existe para não ser.

**(3) `~` significa: quem está falando é o orquestrador, não o nó.**

`coalesce`, `spin`, `stall`, `branch`, `reeval`, `void` são eventos sintéticos. Eles carregam `from: orch` no frontmatter e o sigilo `~` na tela. Isso mantém a R1 honesta: toda linha tem autor real, e nenhuma inferência do orquestrador é vestida como fala de agente.

**Escolhida / descartada.** Ordem total real, carimbada pelo pai. O `events.jsonl` é single-writer por decisão do §6.4, então a ordem do feed **é** uma ordem total de verdade — não uma reconciliação de relógios de 3 filhos. Custo: o carimbo é o instante em que o pai *observou* o evento, até um intervalo de poll atrasado em relação ao instante real do filho. Ganho: monotônico, comparável entre runs, e nenhum vector clock, nenhum merge, nenhum "evento chegou fora de ordem". Descartado usar o timestamp reportado pelo filho: skew, e um filho pode mentir.

**Escolhida / descartada.** Agrupamento por thread na renderização ao vivo: **descartado**. Agrupar exige segurar eventos até a thread avançar, e segurar evento é mentir sobre o tempo numa tela que existe para dizer o que está acontecendo agora. Custo de descartar: o feed ao vivo é intercalado. Ganho: nenhuma latência artificial, e a leitura agrupada continua disponível onde ela é legítima — depois, em `orch show <artefato>` e `orch since`, onde o tempo já passou.

---

## 5.3 ASKs concorrentes

### 5.3.1 A ordem da fila

**Por raio de bloqueio, decrescente; empate por tempo de abertura, crescente.**

Raio de bloqueio = número de nós a jusante transitivamente impedidos por este ASK. É um número exato, calculado do grafo, não uma prioridade declarada.

**Escolhida / descartada.** Ordenar por raio, não FIFO. Custo: um ASK de folha pode esperar muito, e é preciso mostrar isso (a fila imprime a lista inteira, não só o topo). Ganho: o dono é o recurso escasso da sessão inteira; cada minuto dele deve destravar o máximo de trabalho. Descartado FIFO: justiça é um valor humano, e agente não guarda mágoa por ser despriorizado. Descartado "mais barato primeiro": otimiza o conforto do dono contra a vazão do time.

### 5.3.2 O resto do time enquanto o dono responde

**Não pausa.** As outras raias seguem, gastando orçamento.

**Escolhida / descartada.** Não pausar, com uma exceção. Custo: o dono lê uma pergunta enquanto o dinheiro corre, e o mundo muda embaixo da resposta. Mitigação obrigatória, e é a peça de UX central desta subseção: **o `orch next` toma o terminal e o feed não rola dentro dele**; ao sair, ele imprime o que passou. Ganho: a latência humana não multiplica pela concorrência. **Exceção única:** se `session_cap − gasto < teto do próximo nó` (regra que já existe no §6), o scheduler não sobe mais nada — pausa por orçamento, nunca por cortesia.

### 5.3.3 Como o `orch next` não faz o dono responder pergunta de ramo morto

**A ASK é revalidada no pop, nunca no enqueue.** Um ramo morre depois que a pergunta foi feita; validar na entrada é impossível por construção.

Uma ASK é `stale` quando qualquer uma vale:

1. o nó que perguntou não está mais `running` (morreu, timeout, `orch stop`);
2. o `join` a jusante ficou inalcançável e a raia foi marcada morta;
3. uma mutação de reparo (§7) reescreveu a aresta que a pergunta pressupunha;
4. o artefato em questão trocou de `writer_node` no `state.json`.

`orch next` faz pop → revalida → se stale, **escreve** `kind: ask_void` com o motivo em `msgs/`, imprime uma linha e faz pop do próximo. Nunca descarta em silêncio: R5 manda que o que sumiu da tela exista em disco com o motivo.

```
$ orch next

fila de ASKs   2 abertas · 1 anulada
  #7  draft-web  bloqueia 2   aberta 00:41   <- esta
  #9  draft-cli  bloqueia 0   aberta 00:12
  #5  draft-doc  ANULADA      ramo morto (draft-doc failed:timeout 14:19)

ASK #7   draft-web -> voce   raia c   bloqueia: merge, gate
────────────────────────────────────────────────────────────────────────────────
/auth vira rota propria ou header em todas as rotas?

  1) rota propria /auth        CONFLITO: raia a ja escreveu header em
                               api/openapi.yaml:41 (draft-api, 14:23)
  2) header em todas           <- recomendo, coerente com a raia a
  3) para a raia c e segue com a,b     join cai para quorum 2

efeito no veredito: 1 e 2 nao contaminam; 3 marca degraded=quorum e a run
sai da media de comparacao.

enquanto voce le: a=RUN b=SPIN · orcamento correndo
────────────────────────────────────────────────────────────────────────────────
resposta [2]: 2

  msgs/0010-human-draft-web-reply.md · draft-web retoma no proximo turno
  enquanto voce respondia (00:52): 6 eventos · 0 ASK novo · b ainda SPIN
proxima: ASK#9 draft-cli (bloqueia 0)      orch next
```

Duas regras novas, ambas filhas do paralelismo:

**Regra do conflito entre raias.** Toda ASK cujo `artifact` intersecta os `writes` de outra raia viva **carrega a linha de conflito**, com nó, arquivo, linha e hora. Computável do `state.json` (`artefatos.writer_node`, §1.4). Isto é o que só um orquestrador paralelo consegue oferecer, e é o antídoto para o modo de falha clássico de time paralelo: duas frentes decidindo o contrário sem saber.

**Regra do preço da resposta.** Toda ASK declara **o efeito da resposta sobre o veredito**. Numa ferramenta de medida, intervenção humana é contaminação da amostra; a tela precisa precificá-la antes, não confessá-la depois no §8. Sem isso, o dono destrava o time e destrói a comparação sem perceber.

E uma correção ao meu desenho serial: **opção indisponível aparece, riscada, com o motivo** — não some. Esconder produz a pergunta "por que não posso simplesmente reexecutar?", que custa mais que a linha.

---

## 5.4 Ramo morto, ramos bons

```
14:31:02 b| !   draft-cli  fail    failed:timeout 600s · killpg ok · wt/b preservado
14:31:02 b| ~   draft-cli  branch  raia b morta · 0 artefato valido · $0.74 · 7 iters
14:31:02  | ~   merge      reeval  join requires=3, vivos=2  ->  INALCANCAVEL
14:31:02  | ?   orch       ASK #11 join merge inalcancavel: o que faco?         VOCE
```

O que a tela mostra, e nesta ordem:

1. **A morte, com classe de falha** (§3: `permission | budget | timeout | semantic`). A classe muda o que o dono decide, então ela é a primeira palavra.
2. **A necrologia da raia** — o que foi gasto e o que sobrou: `0 artefato válido · $0.74 · 7 iters`. Um ramo que morreu tendo produzido um artefato válido não é a mesma coisa que um que morreu vazio.
3. **A reavaliação do `join`** — a única consequência que importa. O join é o ponto único de convergência (§1.2, sem malha entre ramos), então a morte de uma raia só pode fazer três coisas com ele: nada, degradar, ou inviabilizar.
4. **Só então a ASK.**

A raia morta **não some da tabela.** Ela fica em `FAIL`, com o pulso congelado. Custo: uma linha permanente. Ganho: apagar a evidência é o único jeito garantido de o dono nunca entender por que o veredito ficou pior.

```
ASK #11   orch -> voce   join merge   bloqueia: merge, gate (a sessao inteira)
────────────────────────────────────────────────────────────────────────────────
raia b (draft-cli) morreu: failed:timeout apos 600s, 7 iters, $0.74, 0 artefato.
vivas: a (api/openapi.yaml valido 88L) · c (web/spec.md valido 31L, 1 ASK sua)

  1) quorum 2: merge segue com a, c      <- recomendo
  2) parar agora                          veredito: stop_reason=branch_failed 2/3
  3) reexecutar b                         INDISPONIVEL: retry semantico 1/1 usado

efeito no veredito: 1 marca degraded=quorum e a run nao entra na media;
                    2 registra a run como incompleta, mas comparavel.
```

**Escolhida / descartada.** Esta é a **única ASK que o próprio orquestrador escreve** (`from: orch`), e ela existe porque a política de join não é decidível sem o dono quando o grafo não a declarou. Custo: um caminho de código que produz pergunta sem agente por trás. Ganho: a alternativa é o orquestrador escolher sozinho — e escolher sozinho entre "seguir degradado" e "parar" é escolher sozinho qual número vai para o veredito. Isso é a medida, não a execução.

**Escolhida / descartada.** O orçamento do ramo morto **não é redistribuído** para os vivos. Custo: dinheiro na mesa; uma run pode terminar com 40% do cap intacto. Ganho: se o teto por raia varia conforme quem morreu, duas runs do mesmo grafo deixam de ser comparáveis, e o §8 perde o eixo `cost`. Descartada a redistribuição "para aproveitar": aproveita a run de hoje e queima o experimento.

---

## 5.5 Auditoria depois, na era paralela

O `orch since` do desenho serial (rollup determinístico, sem LLM) ganha um eixo:

```
$ orch since 09:00 --lanes

09:00 -> 14:36   5h36m · 71 eventos · 4 raias · 6 artefatos · $2.31
────────────────────────────────────────────────────────────────────────────────
LN  PART   ARTEFATOS        IT  COST   PULSO ACUM   DESFECHO
a   api    1 valido  88L     4  $0.42  ++·+·+·++    DONE   14:23
b   cli    0                 7  $0.74  ·~·~·····    FAIL   timeout 600s, girou 4m12s
c   web    1 valido  31L     3  $0.29  +·~·+        DONE   14:29 (1 ASK sua, 00:52)
    merge  1 valido 119L     2  $0.51  +++          DONE   14:34
    gate   —                 —  $0.00  —            FAIL   check exit 1: 2 testes
────────────────────────────────────────────────────────────────────────────────
seu tempo na sessao: 1 ASK respondida, 00:52 · contaminacao: nenhuma
```

A última linha é nova e é minha posição mais forte sobre auditoria de time paralelo: **o dono é um nó do grafo e o registro tem que dizer quanto ele custou e o que ele mudou.** Sem isso, uma run em que o humano destravou três decisões parece igual a uma run autônoma, e a comparação do §8 vira ficção.

---

## 5.6 O que continua cortado — reavaliado para 3 raias

Eu cortei TUI full-screen dizendo "reavaliar quando houver paralelismo real (>3 nós)". Chegamos a 3. **A reavaliação de verdade:**

**A linha é o alternate screen buffer.** Não é "TUI sim ou não" — é onde o corte cai, e ele cai exatamente ali.

| | Mantido fora | Aberto |
|---|---|---|
| Alternate screen (`smcup`), panes, mouse, ncurses | ✗ mata scrollback, `tee`, `grep`, sobrevive mal a ssh instável, e toma o TTY que a auditoria precisa | |
| Repaint em bloco fixo (cursor-up N + clear-line), sem altscreen | | ✓ é o `orch top` |

`orch top` repinta ≤ 12 linhas quando `stdout` é TTY; quando é pipe, **degrada para blocos de snapshot append-only** a cada intervalo. `orch top \| tee run.txt` continua produzindo um arquivo legível. Sem `NO_COLOR`, sem cor obrigatória, sem dependência de ncurses.

**Custo de abrir:** ~60 linhas de código de terminal (cursor-up, clear-line, releitura de `COLUMNS`, truncamento duro no resize) e um modo a mais para testar. **Custo de não abrir:** o dono continua sem a tela que ele pediu com a palavra "ver", e a alternativa dele é olhar um log rolando — que informa volume, não progresso. **Aberto.**

O resto continua cortado, com o argumento revisado para o caso paralelo:

| Cortado | Argumento revisado (paralelo) |
|---|---|
| **Um pane por nó** (split tmux-style) | É o instinto óbvio com 3 nós e é errado. Pane por nó otimiza ler *dentro* de um nó — que é `logs/<node>.log`, opt-in e raramente necessário — e destrói o que a era paralela precisa, que é **comparar raias**. Comparação exige colunas compartilhadas, ou seja uma tabela, não caixas lado a lado. Quem quiser panes usa tmux e coloca `orch top` num deles. |
| **Cor por raia** | A raia já tem letra e coluna fixa. Cor seria o terceiro canal e `NO_COLOR` tem que funcionar de qualquer jeito, então ela nunca pode carregar informação. `--color` fica opcional e decorativo. |
| **Canvas, posições, animação do DAG** | Com 3 raias o desenho do grafo é ainda mais inútil: o grafo é fixo e está no YAML; o que muda é o estado, e estado se lê em tabela. `orch graph --dot \| dot -Tpng` se alguém quiser a figura. |
| **Sumarizador LLM por raia** | A tentação **cresce** com 3 raias ("põe um agente para me contar o que o time fez"). Continua cortado, e agora com número: juiz LLM a cada rodada custou +129% de tokens sem ganho (§3, 2606.27009). O `orch since --lanes` é `GROUP BY`. |
| **Pausar / reordenar / repriorizar raia pela tela** | Novo e importante: uma tela que muta a run torna runs incomparáveis, e o produto é um instrumento de medida (§0). Mutação só por `orch say` (enfileirado, vira mensagem em disco) e `orch stop --reason` (registrado no veredito). O painel é read-only por decisão, não por preguiça. |
| **Notificação / push por raia** | `NEEDS_YOU` + exit code de `orch ps` já compõem. Com 3 raias, `orch ps --brief` no `status-right` do tmux dá `NEED:1 SPIN:1 RUN:2`. |
| **Streaming token-a-token, typing indicator** | `-p` não tem TTY. E o pulso já é o substituto honesto. |
| **Pager/scroll interativo dentro do `watch`** | `orch watch \| less -R`. Embutir pager é o primeiro passo para o altscreen que acabei de cortar. |

---

## 5.7 As cinco regras sob paralelismo

As cinco continuam inegociáveis. **A que o paralelismo pressiona é a R2**, e a R3 em segundo lugar.

| Regra | O que o paralelismo faz com ela | Como sobrevive |
|---|---|---|
| **R1** — toda mensagem tem `from`, `to`, `artifact`, `summary` | **Reforçada.** Com linhas intercaladas, auto-endereçamento é o que torna a intercalação suportável | Ganha um quinto campo obrigatório: `lane`. Evento sintético leva `from: orch`, nunca o nome de um nó |
| **R2** — um evento, uma linha, ≤100 col | **Pressionada.** 3 raias = 3× volume; era aqui que virava parede de texto | Orçamento de linhas por raia (§5.2): `note` coalescido com contador visível; estrutural nunca coalescido. Reenunciada: *um evento, uma linha — e cada raia tem orçamento de linhas* |
| **R3** — silêncio é evento | **Pressionada de lado.** Um `stall` numa raia é soterrado pelo barulho das outras duas | O `stall` sobe do feed para a **linha de status** e para a coluna `ST`. Estado persistente não pode morar só num evento que rola |
| **R4** — interromper o humano é caro | **Pressionada em volume.** Agora n nós podem perguntar | Fila por raio de bloqueio, revalidação no pop, conflito entre raias exibido, preço no veredito declarado. `options` + `recommend` continuam obrigatórios sob pena de rejeição na escrita |
| **R5** — a tela é projeção do disco | **Pressionada pelo `orch top`**, que repinta e portanto é efêmero | `orch top` renderiza **só** de `state.json` + `events.jsonl`; `orch top --once` (= `orch ps`) imprime o mesmo bloco como texto; `orch watch --from 0` reconstrói o feed inteiro. Nada existe só na tela |

---

## 5.8 Resumo das escolhas desta seção

| # | Escolhida | Descartada | Custo | Ganho |
|---|---|---|---|---|
| 1 | `orch top` (tabela) como superfície primária | feed como tela principal | um comando novo | 3 raias legíveis em 5 s |
| 2 | Colunas alinhadas, sem swimlane | desenho de raia vertical | não se segue uma raia com o olho | leitura por coluna, alinhamento intacto |
| 3 | Raia derivada da partição declarada | atribuição por ordem de chegada | letras mudam se o grafo mudar | runs diffáveis linha a linha |
| 4 | Orçamento de linhas por raia | truncar global, ou não truncar | 4 de 5 notas só em `orch show` | raia tagarela não afoga as outras |
| 5 | Pulso = delta de `writes` por amostra | bytes de log, tokens, atividade | leitura longa aparece como `···` | impossível de fingir |
| 6 | `SPIN`/`NEED`/`STAL` como qualificadores | oitavo estado de runtime | dois vocabulários | `state.json` continua fonte única |
| 7 | Fila de ASK por raio de bloqueio | FIFO | ASK de folha espera | o recurso escasso destrava o máximo |
| 8 | Revalidar ASK no pop, anular em disco | validar no enqueue | uma revalidação por pop | dono nunca responde ramo morto |
| 9 | ASK declara efeito no veredito | confessar contaminação no §8 | uma linha por ASK | o dono precifica a própria intervenção |
| 10 | Orçamento de ramo morto não redistribuído | redistribuir aos vivos | dinheiro na mesa | runs comparáveis |
| 11 | Repaint em bloco, sem altscreen | TUI full-screen; e também: nenhuma tela viva | ~60 linhas de código de terminal | o dono "vê", e `tee`/`grep`/ssh sobrevivem |
| 12 | Painel read-only, fora do processo | painel que pausa/repriotiza raia | não dá para intervir pela tela | observar não altera a medida |

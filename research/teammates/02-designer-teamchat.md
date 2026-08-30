# T2 — Desenho de experiência de time para agentes em terminal
**Autor:** Alex (design de produto — team chats de trabalho) · **Data:** 2026-08-30
**Alvo:** `mathai-orchestrator` v0+ · **Restrição dura:** bash, Linux/mac, zero API key, `claude -p` sem TTY.

Premissa que carrego do meu ofício: **um team chat bom não é um lugar onde se conversa, é um lugar onde se sabe de quem é a bola.** Tudo aqui deriva disso.

---

## 1. Leitura de UX dos três

### 1.1 Maestri — metáfora: **canvas espacial** (o time é um mapa)

O agente é um retângulo no espaço. A relação entre agentes é um cabo desenhado. O artefato (nota, fichário) é outro retângulo, no mesmo plano, ligado pelo mesmo tipo de cabo. Recrutar é gesto (Maestro Mode), dispensar é gesto.

**O que acerta — e é sério:**

- **A topologia é visível sem ler nada.** Em Slack, "quem fala com quem" é convenção social invisível; aqui é uma linha. Essa é a vantagem real do canvas e é grande.
- **Memória espacial vira navegação.** É o mesmo princípio que faz o lazygit funcionar: painéis em posição fixa, o usuário aprende *onde* as coisas moram e para de procurar ([lazygit / k9s, padrões de painel fixo](https://toolsbase.dev/en/blog/lazygit-getting-started)). Maestri estende isso para um plano infinito.
- **Artefato é cidadão de primeira classe.** A nota é um `.md` real em disco, não anexo. Em chat, o arquivo é sempre segunda classe — mora dentro de uma mensagem. Aqui a mensagem é que orbita o arquivo. Isso está certo e eu vou roubar.
- **Onboarding do contrato é local.** A skill é instalada dentro de cada CLI, não é protocolo do orquestrador — agent-agnostic de graça.

**O que cobra:**

- **Canvas não tem eixo do tempo.** Essa é a falha estrutural. Um canvas responde "como o time está ligado", nunca "o que aconteceu enquanto eu dormi". A prova é que a Maestri precisou *inventar um produto inteiro* — o Ombro, um modelo on-device que assiste tudo e te conta — para tapar um buraco que um feed cronológico resolve de graça. Chat ganha a ordem temporal sem esforço; canvas precisa de um narrador.
- **Canvas não tem inbox.** Não existe "não lido" num plano 2D. Daí o attention dot e o `Ctrl⇧A` serem enxertos: são um *inbox de emergência* colado num paradigma que não previa fila. E o teto está confessado na doc: **9 terminais por badge numerado**. Nove é o tamanho de um time onde você ainda consegue olhar. Não é o tamanho de um time que trabalha à noite.
- **O humano vira arquiteto de informação do próprio workspace.** Layout é trabalho não pago. Cada olhada custa um pan/zoom. Em terminal isso seria fatal.
- **Nada disso é diffável, greppável, pipeável ou acessível por SSH.** O estado vive em JSON de posições. Você não faz code review de um canvas.
- **A detecção de fim-de-turno é heurística sobre PTY**, e o produto admite isso na regra mais estranha da doc: *deixe o receptor sem foco, senão eu paro de monitorar*. Ou seja: a semântica de entrega depende de onde está o seu cursor. Isso é uma bomba de confiança. Em chat de trabalho, o equivalente seria "sua mensagem só é entregue se você não estiver olhando a janela".

**Onde o canvas ganha do chat:** topologia, artefato-como-objeto, gesto de recrutar/dispensar, um único plano para agente + material.
**Onde perde:** ordem temporal, fila de atenção, escala além de ~9, auditoria, texto puro, headless.

### 1.2 Grok Bot — metáfora: **group chat** (o time é uma sala de bots com job description)

Roster nomeado, cada bot com máquina própria, sempre ligado. Você fala 1:1 ou joga todos numa sala; eles coordenam, passam trabalho, atribuem ownership e só te puxam para judgment call. Roteamento por *descrição* — o bot varre as descrições dos colegas e manda para quem casa.

**Por que é excelente para delegar:**

- **Um endereço só.** Você não precisa saber quem faz o quê — é o mesmo motivo pelo qual times reais mandam no `#suporte` e não no DM de alguém. Reduz o custo de decidir o destinatário a zero.
- **Ownership circula dentro da própria conversa.** "passing work, assigning ownership" é literalmente o comportamento que todo manual de Slack pede que humanos façam e quase nenhum time faz ([mover para o canal de handoff com uma frase explícita](https://thread-patrol.com/blog/slack-thread-best-practices)).
- **O humano é exceção, não pré-requisito.** O default é o time andar; você entra em judgment call. Esse é o default certo.

**Por que é péssimo para auditar:**

- **A unidade é a mensagem, não a entrega.** Auditoria pergunta "qual artefato mudou, por decisão de quem, com base em quê". Group chat responde com um fio de falas. Você recupera a *conversa* sobre a decisão, nunca a decisão.
- **Canal plano intercala threads.** É o problema clássico e documentado do Slack: sem disciplina de thread, tudo vira um único fio entrelaçado e o contexto se perde ([information overload / lost context](https://www.questionbase.com/resources/blog/solving-information-overload-in-slack-channels)). Com bots isso piora, porque bots escrevem mais rápido que humanos leem.
- **Roteamento por descrição é não-determinístico.** Duas execuções idênticas podem rotear diferente, e você não tem grafo para comparar. Não dá para fazer post-mortem de um roteamento probabilístico que não foi gravado como aresta.
- **Group chat premia conversa.** Bots se cumprimentam, concordam, reformulam. Cada turno social é contexto queimado, e o custo é O(n²) no número de bots na sala. Nenhuma dessas mensagens é trabalho.
- **Não há diff, não há versão, não há blame.**

Resumo brutal: **o group chat é a melhor interface de entrada e a pior de saída.** Delegação é ótima porque é conversacional; auditoria é ruim exatamente pela mesma razão.

### 1.3 Hermes — metáfora: **gateway** (o agente é um contato na sua lista)

Um cérebro, 15+ transportes. Telegram, Discord, Slack, WhatsApp, Signal, CLI — todos falam com a mesma sessão.

**Acerta:** te encontra onde você já está; o inbox do humano já existe e já é bom (o do WhatsApp), não precisa ser reinventado; sessão persistida em SQLite com WAL + FTS5 — **histórico consultável por texto**, que é a peça que Maestri e Grok Bot não têm; subagentes chamando tools por RPC dentro de script, colapsando pipeline em turno único.

**Cobra:** a metáfora de contato é 1:1 e linear — **o time desaparece**. Não há roster, não há estado de grupo, não há "quem está trabalhando agora". Plataforma de chat é hostil a artefato: arquivo vira anexo, e anexo não é diffável. E o gateway multiplica superfícies de notificação sem multiplicar sinal.

**Síntese das três:** Maestri tem a topologia e o artefato de primeira classe. Grok Bot tem a delegação e a ownership explícita. Hermes tem o histórico consultável. Ninguém tem os três, e ninguém tem eixo temporal + fila de atenção + auditoria ao mesmo tempo. **Esse é o oceano azul, e ele é de texto.**

---

## 2. A metáfora que proponho para o terminal

Não copie o canvas. Não é só que é Swift/Metal/macOS — é que **canvas é a metáfora errada para o problema que sobrou**. O que falta no mercado não é ver a topologia; é saber, às 8h da manhã, o que o time fez das 23h às 8h, quem está travado e onde está a bola. Canvas é ruim nisso por construção.

### A metáfora: **canal por sessão, thread por artefato, feed append-only.**

Em uma frase: **a sessão é um canal de trabalho; cada artefato é uma thread dentro dele; toda mensagem é um arquivo endereçado.**

Por que essa, e não as alternativas:

| Alternativa | Por que não |
|---|---|
| **Sala por agente** (Grok Bot) | Agente é recurso, não assunto. Quando o `builder` sai e entra o `refactorer`, a conversa devia continuar — ela é sobre `handoff.md`, não sobre quem estava de plantão. Sala por agente perde o fio na troca de dono. É o mesmo erro de organizar Slack por pessoa. |
| **Canal plano por sessão, sem thread** | Duas frentes paralelas viram um fio entrelaçado ilegível em 20 minutos. Já sabemos como termina. |
| **Canvas espacial** | Sem eixo temporal, sem fila, exige mouse, não sobrevive a `ssh` nem a `grep`. Fora. |
| **Sala por tema/projeto** | Duplica o Linear. O Linear já é isso e é melhor nisso. |

Por que **artefato** é a unidade certa de thread, e isso é o argumento central:

1. **O SPEC já decidiu.** No `SPEC.md` a aresta *é* `artifact: handoff.md`. O handoff já é um arquivo. Fazer a thread ser o artefato não inventa conceito — dá nome ao que já existe. Custo zero de modelo.
2. **Artefato tem dono, thread não.** "Quem é o dono de `handoff.md` agora" é uma pergunta com resposta única e verificável. "Quem é o dono da conversa" não é.
3. **Artefato é diffável.** A thread do artefato pode carregar o diff. Nenhum chat de trabalho consegue isso, e é a coisa mais útil que um time de código pode ter numa mensagem.
4. **Artefato dá critério de conclusão.** Thread fecha quando o arquivo existe e passa no predicado. Chat humano nunca soube fechar thread — é o buraco de todo Slack, threads que morrem sem resolução ([threads que estagnam em aprovações e handoffs](https://thread-patrol.com/blog/slack-thread-management-best-practices-organized-threads)). Aqui o fechamento é mecânico.
5. **Sobrevive à troca de agente e de CLI.** `cursor-agent` pode assumir uma thread aberta pelo `claude`. A thread não é do agente.

E **append-only** porque é a única forma de auditoria honesta: o feed é o log, o log é o feed, não existe estado escondido. É o consenso que se formou em observabilidade de agente em 2026 — telemetria estruturada por passo, com handoff entre agentes como sinal de primeira classe ([Braintrust](https://www.braintrust.dev/articles/agent-observability-complete-guide-2026), [MLflow](https://mlflow.org/articles/what-is-agent-observability-a-2026-developer-guide/)), e JSONL append-only como substrato replayável ([AgentLog](https://github.com/sumant1122/agentlog)). A diferença do meu desenho: **o mesmo evento é lido por humano sem ferramenta**. Não é telemetria com viewer; é correspondência de escritório que por acaso é parseável.

O SPEC v0 diz que o estado é "grafo + status + existência de artefato, não event-log". Não contradigo: **o `state.json` continua sendo a verdade do runtime; o feed é a camada de experiência por cima.** O feed é derivado e descartável — se você apagar `bus.jsonl`, a sessão continua rodando. Isso mantém o corte do v0 intacto.

---

## 3. Desenho concreto da superfície

Cinco comandos. Nada de TUI full-screen (justificado em §5).

```
orch up      sobe a sessão (já existe no SPEC)
orch watch   o canal ao vivo — feed de uma linha por evento
orch ps      o roster — quem é quem, em que estado, há quanto tempo
orch next    pula para a próxima coisa que precisa de você  (= Ctrl⇧A honesto)
orch show    abre um evento, uma thread ou o log de um nó (= Check do Batuta)
orch say     manda uma mensagem para um nó                  (= Ask do Batuta)
```

### 3.1 O canal da sessão — `orch watch`

```
session  .sessions/2026-08-30-tg-intent      graph v0      up 00:14:32
─────────────────────────────────────────────────────────────────────────────
14:02:11  >  scout    start    prompts/scout.md · cwd=.
14:02:44  .  scout    note     varrendo 12 fontes em pesquisa/tcc/fontes/
14:04:19  .  scout    note     3 fontes contradizem a data do artigo Nous
14:06:03  >> scout    handoff  builder  handoff.md  41L  +41-0
14:06:03  >  builder  start    on=exists(handoff.md)
14:07:31  .  builder  note     escrevendo graphs/v1.yaml  (4 nos, 3 arestas)
14:09:50  ?  builder  ASK #4   sobrescrever graphs/v0.yaml versionado?   VOCE
14:09:50  || builder  blocked  ask#4
14:16:02  ~  builder  stall    sem evento ha 6m12s (blocked)
─────────────────────────────────────────────────────────────────────────────
1 ASK esperando voce  ·  orch next
```

Regras de leitura embutidas no desenho:

- **Uma linha por evento, teto de 100 colunas, o resumo cabe em 72.** Quem escreve o resumo é o agente, no campo `summary` da mensagem — não existe sumarizador. Se o agente não escreveu resumo, o feed imprime o nome do arquivo e nada mais. Agente prolixo é punido com truncamento, não recompensado com espaço.
- **Coluna de sigilo em ASCII, largura fixa 2**, nunca só cor: `>` start · `.` note · `>>` handoff · `?` ask · `!` fail · `~` stall · `||` blocked · `=` done. Cor é enfeite opcional e honra `NO_COLOR` — os dois canais (símbolo + palavra) já bastam sem cor nenhuma, que é a regra básica de indicador acessível ([GitHub CLI](https://github.blog/engineering/user-experience/building-a-more-accessible-github-cli/), [Bloomberg Terminal](https://www.bloomberg.com/ux/2021/10/14/designing-the-terminal-for-color-accessibility/)).
- **É stdout puro.** `orch watch | tee run.txt`, `orch watch | grep ASK`, `orch watch | while read` — tudo funciona. Isso não é economia de esforço, é requisito de auditoria.
- **`ASK` é maiúsculo e tem número.** Igual a menção em Slack: o que precisa de você tem forma visual distinta do resto. `VOCE` no fim da linha é o destinatário explícito.

### 3.2 O roster — `orch ps`

```
NODE      ROLE      STATE  SINCE   OWNS              LAST
scout     scout     DONE   08:29   —                 handoff.md -> builder
builder   builder   NEED   06:12   handoff.md        ASK#4 sobrescrever v0.yaml
tester    tester    WAIT   —       —                 espera build/report.md
editor    editor    IDLE   —       —                 sem aresta de entrada

NEED 1 · RUN 0 · WAIT 1 · DONE 1 · FAIL 0
```

`OWNS` é a coluna que nenhum dos três produtos tem e que é o coração de team chat de trabalho: **de quem é a bola, agora, por artefato.** Um artefato tem no máximo um dono. Dois nós reivindicando o mesmo artefato é erro de grafo e o `up` recusa.

### 3.3 Um handoff acontecendo — a thread do artefato

```
$ orch show handoff.md

thread  handoff.md            aberta 14:02:11   fechada 14:06:03   1 dono
─────────────────────────────────────────────────────────────────────────────
14:02:11  scout    claim    assumiu handoff.md (aresta scout->builder)
14:04:19  scout    note     3 fontes contradizem a data do artigo Nous
14:06:03  scout    handoff  -> builder                    msgs/0003-...md
          ├ 41 linhas, 2.1 kB, sha 9f2c1ab
          ├ "12 fontes lidas, 3 conflitos datados, recomendo v1 com 4 nos"
          └ pendencias declaradas: 2  (ver 'orch show 0003 --open')
14:06:03  builder  accept   assumiu handoff.md
─────────────────────────────────────────────────────────────────────────────
proximo: builder escreve graphs/v1.yaml
```

O handoff imprime **três coisas e só três**: tamanho + hash do artefato, a frase que o remetente escreveu, e as pendências que ele declarou em aberto. Handoff sem pendências declaradas (nem que seja `nenhuma`) é rejeitado na escrita. Essa é a regra que mais evita retrabalho em time humano e vale igual aqui: **quem passa a bola declara o que não terminou.**

### 3.4 O momento humano — interromper, redirecionar, aprovar

Três verbos distintos, três mecanismos distintos. Confundi-los é o erro clássico.

**(a) Aprovar** — o agente pediu, você responde. É o caminho principal e é *pull*, não push.

```
$ orch next

ASK #4    builder -> voce    aberta ha 6m12s    bloqueia: graphs/v1.yaml
─────────────────────────────────────────────────────────────────────────────
Sobrescrevo graphs/v0.yaml, que esta versionado no git?

  1) sim, sobrescreve v0.yaml                      (destrutivo)
  2) escreve graphs/v1.yaml e deixa v0 intacto     <- recomendo
  3) para e me explica o diff antes

Contexto: v0 tem 2 nos; a spec nova pede 4. Manter os dois permite
comparar execucoes. Custo: mais um arquivo em graphs/.
─────────────────────────────────────────────────────────────────────────────
resposta [2]: _
```

Enter aceita a recomendação. **ASK sem opções enumeradas e sem recomendação default é rejeitado pelo orquestrador na escrita** — o agente reescreve ou fica travado. Isso é o portão de qualidade mais importante do desenho inteiro: pergunta aberta transfere trabalho cognitivo para o humano, e o humano é o recurso escasso.

**(b) Redirecionar** — você fala sem ter sido chamado. Vira mensagem, entra no feed, é auditável.

```
$ orch say builder "para de mexer no yaml, escreve so o README primeiro"
  msgs/0006-human-builder-note.md  ·  entregue no proximo turno do no
```

Entregue **no próximo turno**, não no meio do turno — `claude -p` não tem TTY e não vai ler no meio da execução. Ser honesto sobre isso vale mais que fingir tempo real: o feed imprime `queued`, não `sent`.

**(c) Interromper** — quando é para parar agora.

```
$ orch stop builder --reason "escopo errado"
  builder  SIGTERM -> KILL em 10s   ·  estado FAIL  ·  sessao pausada
```

`stop` é o único caminho destrutivo e sempre exige `--reason`, que vira mensagem no feed. Sessão pausada, nunca morta silenciosamente.

### 3.5 Ler o histórico depois — auditoria

Dois modos, e o segundo é o que ninguém tem.

```
$ orch log --thread handoff.md          # a thread inteira, cronológica
$ orch log --node builder --kind ask    # tudo que o builder me perguntou
$ orch log --grep "v0.yaml"             # FTS sobre corpos de mensagem
```

E o **equivalente honesto do Ombro** — o que aconteceu enquanto você não estava:

```
$ orch since 23:00

23:00 -> 08:14   9h14m   ·  17 eventos  ·  3 nos  ·  2 artefatos
─────────────────────────────────────────────────────────────────────────────
FECHOU    handoff.md      scout -> builder      41L    23:41
FECHOU    graphs/v1.yaml  builder -> tester     88L    01:12
ABERTO    build/report.md tester                       01:12  (stall 7h02m)
ASK       #4 respondido por voce 23:58 -> opcao 2
FALHOU    —
─────────────────────────────────────────────────────────────────────────────
precisa de voce agora: tester parado ha 7h02m sem evento   orch show tester
```

Isso é **rollup determinístico do bus, sem modelo nenhum**. Maestri precisou de Apple Foundation Models on-device para produzir um parágrafo pior que essa tabela. Quando cada evento já carrega `from`, `to`, `artifact` e `summary` escritos por quem agiu, o resumo é um `GROUP BY`. Sumarizar com LLM aqui é pagar por perda de fidelidade.

### 3.6 O formato de uma mensagem em disco

**Duas camadas, uma verdade.** O arquivo Markdown é a mensagem; o JSONL é o índice. Se divergirem, o arquivo ganha e o índice se reconstrói (`orch reindex`).

```
.sessions/2026-08-30-tg-intent/
├── graph.yaml
├── state.json                     # a verdade do runtime (SPEC §1) — intacto
├── bus.jsonl                      # indice append-only, uma linha por evento
├── NEEDS_YOU                      # existe <=> ha ASK aberto  (o "dot")
├── msgs/
│   ├── 0001-scout-builder-handoff.md
│   ├── 0004-builder-human-ask.md
│   ├── 0005-human-builder-reply.md
│   └── 0006-human-builder-note.md
├── artifacts/handoff.md
└── logs/scout.log
```

Nome do arquivo = `NNNN-<from>-<to>-<kind>.md`. Ordenável por `ls`, endereçável por sequência, legível sem abrir. O nome já responde três das quatro perguntas.

Uma mensagem:

```markdown
---
seq: 4
at: 2026-08-30T14:09:50-03:00
from: builder
to: human
kind: ask                # start|note|claim|handoff|ask|reply|done|fail|stall
thread: handoff.md       # a thread = o artefato
artifact: graphs/v1.yaml # o que esta em jogo
blocking: true
summary: "sobrescrever graphs/v0.yaml versionado?"   # <= 72 chars, obrigatorio
options: ["sobrescreve v0", "escreve v1 e mantem v0", "explica o diff antes"]
recommend: 2
---

## Situacao
v0.yaml tem 2 nos e esta versionado no git desde a MAT-96. A spec nova
pede 4 nos e 3 arestas.

## Por que estou perguntando
Sobrescrever apaga a unica execucao comparavel que existe.

## Pendencias que deixo em aberto
- nao validei se o `tester` aceita o predicado novo
```

E a linha correspondente no `bus.jsonl` — mesmos campos, sem corpo:

```json
{"seq":4,"at":"2026-08-30T14:09:50-03:00","from":"builder","to":"human","kind":"ask","thread":"handoff.md","artifact":"graphs/v1.yaml","blocking":true,"summary":"sobrescrever graphs/v0.yaml versionado?","file":"msgs/0004-builder-human-ask.md"}
```

Por que markdown-com-frontmatter e **não** JSONL puro como fonte: porque a mensagem precisa ser legível pelos dois lados sem ferramenta. `cat msgs/0004-*.md` num SSH às 3h da manhã tem que fazer sentido. JSON puro força um viewer, e viewer é dependência que quebra. E porque é o mesmo formato do vault do dono — frontmatter + corpo — então o hábito já existe.

Por que o JSONL **existe mesmo assim**: `tail -f bus.jsonl | jq` é o feed para máquina, e é como o `orch watch` é implementado. Custo de manter os dois: um `append()` que escreve duas vezes. Barato.

### 3.7 Estados de nó, sem cor

Seis estados. Palavra de 4 letras em coluna fixa + sigilo ASCII + tempo desde o último evento. Três canais redundantes, zero dependência de cor.

| STATE | Sigilo | Significa | O que o humano faz |
|---|---|---|---|
| `IDLE` | `-` | existe no grafo, sem aresta satisfeita | nada |
| `WAIT` | `.` | espera artefato de outro nó | nada |
| `RUN ` | `>` | subprocesso vivo, escreveu evento < 60s | nada |
| `NEED` | `?` | ASK bloqueante aberto, endereçado a você | **responder** |
| `STAL` | `~` | vivo, mas sem evento há > 5 min | olhar |
| `FAIL` | `!` | exit ≠ 0, ou artefato exigido não apareceu | decidir |

`DONE` (`=`) é terminal e sai do roster ativo para o rodapé.

**Sobre "typing indicator":** não faça. A pesquisa de CSCW mostra que o valor do live-typing é *presença social* — e que ele também é percebido como ameaça porque tira do outro o controle da própria apresentação ([CHI'23, Together but not together](https://dl.acm.org/doi/fullHtml/10.1145/3544548.3581248)). Agente não tem face a preservar e não precisa da sua empatia. O que sobra do indicador é só informação de progresso — e um verbo ("varrendo 12 fontes") informa infinitamente mais que um spinner. **Heartbeat com verbo, nunca animação.**

### 3.8 O attention dot honesto, e o `Ctrl⇧A` honesto

Atalho global não existe em terminal sem sequestrar o TTY, e sequestrar o TTY quebra pipe. Então:

**O dot** = existência de arquivo. `NEEDS_YOU` existe se e somente se há ASK aberto; o corpo tem uma linha por ASK. Qualquer coisa pode ler isso, e é essa a graça:

```bash
# no PS1
[ -f .sessions/cur/NEEDS_YOU ] && PS1="(!$(wc -l < .../NEEDS_YOU)) $PS1"

# no tmux status-right
set -g status-right '#(orch ps --brief)'      # ->  NEED:1 RUN:0 STAL:1
```

Além disso: `orch ps` sai com **exit code = número de ASKs abertos**. `orch ps >/dev/null || make-me-a-sound`. O dot vira composável em vez de proprietário.

**O `Ctrl⇧A`** = `orch next`. FIFO pelo ASK bloqueado há mais tempo, imprime, espera resposta, marca resolvido, e ao sair já anuncia o próximo. Ciclar terminais aguardando vira percorrer uma fila — que é o que o `Ctrl⇧A` *já é* por baixo, só que sem admitir. E `orch next --peek` é o **Check** (read-only) do Batuta; `orch say` é o **Ask**. Batuta Search vira `orch log --grep`, que é melhor porque busca no corpo *e* no índice, e sai em stdout.

---

## 4. As 5 regras que não podem ser quebradas

**R1 — Toda mensagem tem `from`, `to`, `artifact` e `summary`.** Sem destinatário nomeado não é mensagem, é log — e vai para `logs/<node>.log`, que ninguém lê por padrão. Isso mata o "broadcast para o vazio", que é o modo de falha número um de canal de trabalho.

**R2 — Um evento, uma linha, ≤ 100 colunas.** O `summary` tem 72 chars e é escrito pelo agente. Profundidade é sempre opt-in (`orch show`). Nenhum componente do sistema tem permissão de despejar parede de texto no feed — nem o agente, nem o orquestrador, nem o erro. Um traceback vira `! builder fail exit=1 (orch show 0009)`.

**R3 — Silêncio é evento.** Nó sem evento por 5 min emite `stall` no feed com o tempo acumulado. Sem heartbeat, "trabalhando" e "morto" são visualmente idênticos, e essa ambiguidade é o que faz o humano ficar olhando a tela. O objetivo do desenho inteiro é que ele possa **não** olhar.

**R4 — Interromper o humano é caro e o sistema cobra por isso.** Só `kind: ask` com `blocking: true` alcança você. Todo ASK carrega `options` enumeradas e `recommend`; sem os dois, o orquestrador rejeita a escrita e devolve ao agente. Nunca há push — o humano puxa com `orch next`. Um agente que abre 5 ASKs num turno aparece no `orch ps` com essa contagem, porque isso é um defeito do prompt dele, não do dia do humano.

**R5 — A tela é projeção do disco, e o teclado basta.** Nada aparece no feed que não exista como arquivo com o mesmo texto; nada é escrito em `msgs/` sem aparecer no feed. Zero mouse, zero janela, zero estado só-em-memória. Se a sessão morrer no meio, `orch watch --from 0` reconstrói exatamente a mesma tela a partir do disco. É isso que separa auditoria de screenshot.

---

## 5. O que NÃO desenhar no MVP

| Cortado | Por quê |
|---|---|
| **TUI full-screen multi-painel** (estilo lazygit/k9s) | O mais tentador e o mais errado agora. Full-screen toma o TTY e mata `tee`, `grep`, scrollback do terminal e `ssh` frágil — que são exatamente as ferramentas de auditoria que eu prometi. Ganha densidade, perde composabilidade. `orch watch` é stream; `orch ps` é snapshot. Quem quiser painel usa tmux, que já resolve isso melhor. Reavaliar quando houver **paralelismo real** (>3 nós simultâneos), não antes. |
| **Canvas, posições, cabos, minimapa** | O grafo já está no `graph.yaml`. Se um dia precisar de figura, `orch graph --dot \| dot -Tpng` resolve em 10 linhas. Canvas interativo é 6 meses de trabalho para responder uma pergunta que uma linha de `dot` responde. |
| **Chat livre agente↔agente** | Se dois nós podem conversar fora de artefato, o feed deixa de ser auditável no mesmo dia. Todo tráfego passa por thread de artefato. Isso é restrição, não limitação — é o que dá a auditoria que o Grok Bot não tem. |
| **Roteamento por descrição** | Não-determinismo no ponto mais caro de debugar. O grafo é explícito. Roteamento dinâmico é v2 e, se vier, vira **aresta gravada** no bus, comparável entre execuções. |
| **Sumarizador com LLM (o "Ombro")** | `orch since` é `GROUP BY` sobre o bus. Determinístico, instantâneo, grátis, e não alucina. Só faz sentido se o campo `summary` falhar sistematicamente — e aí o conserto é no prompt do agente, não um modelo em cima. |
| **Notificação de sistema, push, som, webhook** | O `NEEDS_YOU` + exit code já são a primitiva. Quem quiser `terminal-notifier`, `notify-send` ou Telegram compõe em uma linha de shell. Não embuta transporte; ganha zero e carrega dependência para sempre. |
| **Streaming token-a-token / typing indicator** | `claude -p` não dá TTY (SPEC §4). Fingir tempo real seria mentira de interface. Heartbeat com verbo é mais informativo e é honesto. |
| **Presença, "está online", avatar, cor por agente** | Antropomorfizar convida à conversa. Quero o oposto: o agente é um cargo com uma bola na mão. Nome curto e papel, só. |
| **Multiplayer / segundo humano / permissões** | Vault de um dono, sessão de um dono. Permissão sem segundo usuário é código morto. |
| **Rotação, compressão, retenção do bus** | Uma sessão longa gera talvez 500 eventos. `bus.jsonl` de 200 kB não é um problema. Resolver isso agora é otimizar o que não dói. |
| **Resume / múltiplas sessões vivas** | Já cortado no SPEC §5. Não reabrir por causa de UI. |
| **tmux como runtime** | Já cortado no SPEC §3. tmux é *observação* opcional (`status-right`), nunca dependência. |

---

## Fontes usadas

- [lazygit — painéis fixos, memória espacial, tecla contextual por painel](https://toolsbase.dev/en/blog/lazygit-getting-started)
- [Slack threads — quando thread, quando canal, handoff explícito](https://thread-patrol.com/blog/slack-thread-best-practices) · [threads que estagnam em aprovações e handoffs](https://thread-patrol.com/blog/slack-thread-management-best-practices-organized-threads)
- [Information overload e perda de contexto em canal plano](https://www.questionbase.com/resources/blog/solving-information-overload-in-slack-channels)
- [Agent observability 2026 — handoff como sinal de primeira classe](https://www.braintrust.dev/articles/agent-observability-complete-guide-2026) · [MLflow](https://mlflow.org/articles/what-is-agent-observability-a-2026-developer-guide/)
- [AgentLog — event bus append-only em JSONL, replayável](https://github.com/sumant1122/agentlog)
- [CHI'23 "Together but not together" — typing indicators, presença social e o custo dela](https://dl.acm.org/doi/fullHtml/10.1145/3544548.3581248)
- [GitHub CLI acessível — NO_COLOR, símbolo + rótulo, nunca só cor](https://github.blog/engineering/user-experience/building-a-more-accessible-github-cli/) · [Bloomberg Terminal e acessibilidade de cor](https://www.bloomberg.com/ux/2021/10/14/designing-the-terminal-for-color-accessibility/)
- Locais: `/tmp/.../DOSSIE.md`, `/home/user/mathai-orchestrator/SPEC.md`, `/home/user/mathai-wiki/estudos/time-de-agentes/`

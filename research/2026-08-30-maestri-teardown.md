# Maestri — levantamento de features e engenharia reversa

**Data:** 2026-08-30 · **Issue:** [MAT-96](https://linear.app/borgesmathai/issue/MAT-96) · **Status:** registro de pesquisa, não é spec
**Fontes:** docs oficiais `themaestri.app/en/docs/*` (intro, canvas, terminals, connections, maestro, notes, ficharios, partituras, floors, environments, portals, routines, batuta-search, prompt-composer, ombro, workspaces), landing `themaestri.app/en`, Product Hunt.
**Escopo:** o que o produto faz, e como cada peça teria de ser construída. Nada aqui é decisão do nosso v0 — a decisão está em [`SPEC.md`](../SPEC.md) e [`MVP.md`](../MVP.md).

---

## 0. O que Maestri é, em uma frase

Um **canvas infinito nativo de macOS que hospeda terminais reais**, onde cabos desenhados entre terminais viram comunicação agente↔agente por **PTY** — "one agent typing into another's terminal", sem API, sem middleware. Ele não é um agente: é a camada que fica **em volta** dos agentes que você já instalou (Claude Code, Codex, OpenCode).

Isso importa porque é exatamente a mesma tese do `mathai-orchestrator` — *acima* do terminal, não no lugar dele — resolvida com um stack que nós não temos e não queremos (Swift, SwiftUI, Metal, Apple Silicon).

---

## 1. Inventário de features

### 1.1 Espaço e navegação

| Feature | O que é | Nota |
|---|---|---|
| **Canvas** | Espaço 2D infinito com pan/zoom, onde tudo mora | Tipos de nó: Terminal, Note, Text, Drawing, File Tree |
| **Groups** | `Ctrl G` amarra nós num frame com header arrastável; dissolve sozinho ao sobrar um membro | Persiste em copy/paste, duplicar, undo |
| **Tile snapping** | Segurar Ctrl arrastando encaixa nós em mosaico, casando paredes e preenchendo buracos | Layout sem grid fixo |
| **Minimap** | Canto inferior direito, `Ctrl⇧M` | |
| **Floors** | "Isolated branches without leaving your workspace" — cada floor é cópia integral do repo compartilhando storage. macOS: APFS copy-on-write (instantâneo, disco ~zero). Windows: branch git. Guardados em `.maestri/floors` | A branch do floor é **espelhada no repo original**, então GitHub e IDE enxergam |
| **Workspaces** | Contêiner de projeto: working dir, ícone, layout salvo. Rodam em background ao trocar; múltiplos ativos ao mesmo tempo. Export `.maestri` | Sincroniza `CLAUDE.md` e `AGENTS.md` para times mistos |
| **Batuta Search** (`Ctrl P`) | Paleta fuzzy (case- e acento-insensitive) sobre terminais, notas, blocos de texto, arquivos, links, file trees, portais e workspaces — busca o **corpo inteiro** das notas | Ações globais + contextuais por tipo de nó selecionado |

### 1.2 Agentes

| Feature | O que é | Nota |
|---|---|---|
| **Terminal** | "A full interactive shell" desenhado no canvas, com um agente escolhido de presets | Nome e ícone próprios; 30+ temas, formato Ghostty |
| **Role** | "A set of instructions for a specific terminal instance"; Maestri "automatically injects those instructions when the agent starts". Presets Lead / Coder / Reviewer / Tester | Sidecar `role.json`, viaja entre workspaces e máquinas |
| **cwd por nó** | Cada terminal pode apontar para um subdiretório com o próprio `CLAUDE.md` / `AGENTS.md` | Instrução por agente sem inventar protocolo |
| **Attention dot** | Ponto vermelho no header quando o agente pausa — "waiting on a decision or has finished its turn" | `Ctrl⇧A` cicla os terminais que esperam, **através de todos os floors** |
| **Badges numerados** | Segurar Ctrl revela números; troca instantânea de terminal, até 9 | Sem mouse |
| **Notificações** | Banner de sistema em "Notify when an agent needs attention" | |
| **Environments** | Onde o terminal roda: Local, Local (tmux), WSL, SSH (túnel reverso), Docker container/sandbox, custom runtime (Podman, Lima). Escopo por workspace com override por terminal | Injeta `MAESTRI_TERMINAL_ID`, `MAESTRI_HOST`, `MAESTRI_TOKEN`; overrides **não** podem substituir `HOME`, `PATH` ou qualquer `MAESTRI_`. Token por terminal, revogado ao remover o provider. "Maestri never creates, starts, stops, restarts, or deletes the selected container" |

### 1.3 Comunicação

| Feature | O que é | Nota |
|---|---|---|
| **Connection (cabo)** | Linha físico-animada entre dois terminais, ou terminal↔nota/fichário/portal. Ao conectar, "Maestri installs a **Maestri Agent Skill** in each one. This skill gives agents the ability to send prompts to, and receive responses from, any other connected agent" | **Agent-agnostic**: Claude Code fala com Codex, OpenCode fala com Claude |
| **Regra do foco** | Ao mandar um agente falar com outro, "leave the receiving agent unselected (no dashed border)". Maestri monitora só terminais **não focados**; quando o receptor termina, "Maestri detects this and sends the answer back". Selecionar = assumir controle manual e o monitoramento para | É a peça mais reveladora do produto — ver §2.2 |
| **Ask / Check** | Da paleta: **Ask** manda mensagem para qualquer terminal de qualquer lugar (multi-linha, preview ao vivo da resposta); **Check** é a versão read-only, olha a saída sem mandar nada | `Connect to…` / `Disconnect…` também são ações de paleta |
| **Prompt Composer** (`Ctrl⇧P`) | Composer rico flutuando sobre o terminal. `@` menciona terminal conectado, nota ("reads the live note, not a stale snapshot"), portal, arquivo, ações, e `@Maestro` = "an explicit 'orchestrate this'". Anexos: screenshot colado, arquivo, clipe. Em Claude Code e Gemini as imagens chegam **nativamente como pixels** | Rascunho por terminal, sobrevive a troca de floor/workspace; só o envio limpa |
| **Maestro Mode** | Checkbox por terminal que "promotes a terminal from a regular agent into a **manager** — one that can recruit new agents to your canvas, assign them roles, wire them into the right notes, and dismiss them when their work is done". Recrutas nascem alinhados abaixo do maestro; cada um vê o próprio nome, papel e conexões. Pode disparar notificação de sistema ao terminar ou ao travar | Tende a recrutar cópias de si mesmo; dá para forçar time misto |

### 1.4 Memória compartilhada

| Feature | O que é | Nota |
|---|---|---|
| **Note** | Arquivo markdown **real em disco**, sticky no canvas, engine markdown com preview ao vivo. "Agents can read and write them through the Maestri CLI" | Encadeáveis por cabo: conectado à nota de entrada, o agente "can access the entire chain" |
| **Fichário** | Pasta com abas que junta notas soltas — "the notes stay real notes — they just live as pages inside it". Conectado a um agente, ele "can access every page inside" | Fichários vazios nomeados viram raias de kanban: Backlog, Building, Review, Shipped |
| **File Tree** | Árvore navegável do projeto embutida no canvas | |
| **Partitura** | Template do canvas em JSON legível em `~/.maestri/partituras/` — "terminals with their agents and roles, notes, portals, file trees, drawings, groups, and every connection between them". **Não** salva scrollback, config de runtime, caminho absoluto nem anexo local | "Plain text you can read and diff, with no database in the way". Compartilhável (`.maestripartitura`, bundle `.maestripartituras`); atualizar preserva a identidade (id, nome, ícone, cor, descrição, data) |

### 1.5 Automação e observação

| Feature | O que é | Nota |
|---|---|---|
| **Routines** | Prompts agendados por **intervalo fixo** contra um terminal escolhido (5 min, 1 h). Encadeamento com `&&`: "the next one only fires after the previous one completes". Pause/resume/edit/delete + indicador ao vivo | **Não há trigger por evento** — só tempo. É o buraco mais óbvio do produto |
| **Portals** | Janela embutida no canvas: navegador (WebKit isolado, storage separado, sessão compartilhável entre portais conectados), Simulador iOS, emulador Android, Android físico. O agente conectado dirige via CLI `maestri`: clicar, digitar, rolar, screenshot, rodar JavaScript | Device portal lê "the running app's real element tree, with true labels and exact positions, so a tap lands on the button rather than a guessed coordinate" — não é automação por pixel |
| **Ombro** (`Ctrl⇧O`) | Companion on-device que assiste os agentes rodando e, ao terminarem, "notifies you with a summary of what happened, a snapshot preview of the terminal's current state, and suggested next actions". Responde "Check what Codex is doing"; resume todas as notas conectadas do workspace | Apple Foundation Models, macOS 26+, Apple Silicon. "No API calls, no cloud, no latency" |

### 1.6 Modelo de negócio e postura

- macOS 15.4+ Apple Silicon; versão Windows existe (Floors degradado para branch git; Ombro não existe).
- Free: 1 workspace, todas as features core. **Pro: US$ 18 uma vez, vitalício, licença para 2 Macs.**
- Zero telemetria, zero conta, zero nuvem. Storage local: JSON de config + Markdown de nota.
- Não vende modelo nem token: quem paga o Claude/Codex é você. Maestri vende **arranjo**.

---

## 2. Engenharia reversa — como cada peça é feita

### 2.1 Terminal como nó: PTY, não subprocesso

Um "full interactive shell" no canvas implica `forkpty`/`openpty` + emulador de terminal próprio (parser ANSI/VT, scrollback, resize via `TIOCSWINSZ`, render em Metal). O agente não sabe que está num canvas: ele vê um TTY normal, e por isso Claude Code roda **interativo** — com slash commands, permission prompts, spinner — em vez do modo headless.

**Consequência dura:** todo o resto do produto (detecção de fim de turno, Ombro, attention dot) tem de ser inferido a partir de um **stream de bytes de terminal**. Não existe exit code por turno num REPL interativo: o processo continua vivo.

### 2.2 A regra do foco é a confissão do mecanismo

"Maestri monitora só terminais não focados; quando o receptor termina, Maestri detecta e devolve a resposta." Isso só faz sentido se a detecção de fim de turno for **heurística sobre o PTY**, não um sinal do agente. Reconstrução provável, em ordem de probabilidade:

1. **Quiet timeout** — sem bytes novos por N ms e o cursor parado numa linha que casa com o prompt do agente ⇒ turno terminou.
2. **Casamento do prompt** — regex contra o prompt específico de cada CLI (por isso "presets" de agente, e por isso um adapter por CLI).
3. **Sentinela injetada** — a "Maestri Agent Skill" instalada em cada CLI pode escrever um marcador (arquivo, ou linha em stdout) ao terminar, e o app faz tail. Isso explicaria por que a comunicação **só existe quando há cabo**: o cabo é o gatilho da instalação da skill.

E explica a regra do foco: se o humano está digitando naquele terminal, os bytes que chegam são dele, a heurística envenena, e o app se cala. É uma escolha honesta de produto — e é **frágil por construção**. Qualquer mudança de spinner, de tema ou de prompt no CLI upstream pode quebrar a detecção.

**Lição para nós:** a mesma feature em modo headless (`claude -p`) tem **exit code** e fim de stream. Trocamos interatividade por determinismo. A spec v0 já escolheu esse lado; esse teardown confirma o preço que o Maestri paga do outro.

### 2.3 A skill instalada é o protocolo

Não há bus, não há broker, não há API. O protocolo agente↔agente **mora dentro do agente**, como capacidade instalada (skill/tool), e o app é só o transporte. Daí "agent-agnostic": basta que o CLI alvo suporte o padrão de skills/tools do arquivo — Claude Code (Agent Skills), Codex e OpenCode (`AGENTS.md` + tools).

Reconstrução: a skill provavelmente fala com um **bridge local** do app — o `MAESTRI_HOST` + `MAESTRI_TOKEN` por terminal, documentados em Environments, são exatamente a assinatura de um endpoint local autenticado por token com escopo de terminal. O CLI `maestri` (usado por notas e portais) é o cliente desse bridge. Ou seja: **existe API — só não é a API de um modelo, é a API do orquestrador**, e ela é local.

Isso é reaproveitável sem Swift: um socket unix + um binário `orch` no PATH do nó, com `ORCH_NODE_ID`/`ORCH_TOKEN` no env, dá o mesmo contrato num orquestrador bash.

### 2.4 Nota é blackboard, cabo é ACL

Notas são markdown em disco, lidas e escritas pelo CLI, e encadeáveis. Isso é um **blackboard** clássico de sistemas multi-agente, com uma diferença: o cabo funciona como **lista de controle de acesso** — o agente só alcança as notas em que está plugado. O fichário é o mesmo mecanismo com granularidade de pasta.

Reverse: o grafo não serve só para roteamento de mensagem; serve para **recortar o contexto** de cada nó. Um agente conectado a 3 notas tem um universo de 3 notas. É controle de contexto expresso como topologia — e é o que mais interessa para "graph engineering" de verdade.

### 2.5 Partitura é o produto disfarçado de arquivo

JSON legível, sem banco, sem caminho absoluto, sem scrollback, com identidade estável ao atualizar, arrastável para o Finder e para o e-mail. Isso é um **formato de time versionável e compartilhável** — o único artefato do Maestri que pode circular fora do Maestri.

E é exatamente onde o produto se contradiz: a partitura mora em `~/.maestri/partituras/`, fora do repo. Um time que não vive no repositório do projeto não entra em PR, não é revisado, não versiona junto com o código que ele produz.

### 2.6 Floors = worktree com outro nome

"Cópia integral do repo compartilhando storage" via APFS copy-on-write, branch espelhada no repo original, guardada em `.maestri/floors`. No Windows vira branch pura. Funcionalmente é `git worktree` com camada visual e clone barato — e no Linux o equivalente é worktree + overlayfs/reflink (`cp --reflink=auto` em btrfs/XFS).

### 2.7 Routines é cron sem evento

Intervalo fixo + encadeamento com `&&`. É `cron` embutido com UI. A ausência de trigger por evento (arquivo mudou, teste quebrou, PR abriu, artefato apareceu) é a lacuna funcional mais visível — e é justamente o que um orquestrador de grafo faz nativamente: a aresta com predicado **é** o trigger por evento.

### 2.8 Ombro é o observador que o terminal não tem

Um segundo modelo, local e barato, cujo único trabalho é **ler o que os agentes fizeram e te contar**. Arquiteturalmente é o reconhecimento de que o gargalo de um time de agentes não é execução: é o humano ler N terminais. A implementação (Apple Foundation Models) é intransferível; a **função** é copiável — em bash, um digest do feed de eventos, gerado por um nó barato, sem depender de nuvem.

### 2.9 O que o Maestri não tem

Levantado por ausência nas docs, não por opinião:

- **Sem trigger por evento** (só tempo).
- **Sem critério de parada declarado** — nada define "a sessão terminou com sucesso"; quem decide é o humano olhando.
- **Sem medição** — zero telemetria também significa zero métrica própria: não dá para saber se o time foi melhor que um agente sozinho.
- **Sem headless/CI** — é app de desktop; não roda numa máquina sem display.
- **Sem grafo versionado junto do código** — partitura fica em `~/.maestri`, não no repo.
- **Sem retomada declarada de sessão falha** — o estado é o canvas, e o canvas não tem noção de "nó falhou, retome daqui".
- **macOS-first** — Ombro e Floors baratos só existem lá.

---

## 3. Portabilidade para o `mathai-orchestrator`

| Peça do Maestri | Copiar | Adaptar | Descartar |
|---|---|---|---|
| Canvas espacial, Metal, 3D de floors | | | **descartar** — stack inalcançável e não é o eixo de valor |
| Terminal como nó com role injetado | | **adaptar**: nó = processo `claude -p` com preâmbulo gerado | |
| Cabo = comunicação + recorte de contexto | **copiar a ideia**: aresta define quem lê o quê | | |
| Skill instalada como protocolo | | **adaptar**: binário `orch` no PATH + socket local + `ORCH_NODE_ID`/`ORCH_TOKEN` | |
| Detecção de fim de turno por PTY | | | **descartar** — headless dá exit code |
| Nota/fichário como blackboard | **copiar**: artefato markdown no `session_dir` | | |
| Partitura JSON | | **adaptar**: grafo YAML **dentro do repo**, versionado, revisável em PR | |
| Floors | | **adaptar**: `git worktree` por nó quando houver paralelismo | |
| Routines por tempo | | **adaptar**: aresta com predicado (evento), tempo como caso particular | |
| Ombro | | **adaptar**: nó observador barato que resume o feed | |
| Ask / Check | **copiar**: dois verbos do CLI (`orch ask`, `orch check`) | | |
| Attention dot / `Ctrl⇧A` | | **adaptar**: fila de "precisa de você" no feed | |
| Portals (browser/device) | | | **descartar no v0** |
| Zero telemetria, zero conta, preço único | **copiar a postura** | | |

---

## 4. Onde o Maestri deixa espaço

Três buracos, em ordem de tamanho:

1. **O time não é código.** Partitura fora do repo, não versionada com o projeto, não revisável. Um grafo de time que mora em `graphs/*.yaml` dentro do repo entra em PR como qualquer outra mudança.
2. **Ninguém mede.** Não existe noção de sucesso de sessão, custo de handoff, retrabalho. Sem métrica, "time de agentes" continua sendo fé.
3. **Não roda sem humano nem sem tela.** Sem headless não há CI, não há servidor, não há sessão noturna.

Esses três buracos são a matéria-prima do nosso posicionamento — o argumento fechado está em [`MVP.md`](../MVP.md) e na [mesa-redonda](2026-08-30-mesa-redonda.md).

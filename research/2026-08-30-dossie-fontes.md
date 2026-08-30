# Dossiê de pesquisa — Maestri / Grok Bot / Hermes (coletado 2026-08-30)

Fonte: docs oficiais themaestri.app/en/docs/*, x.ai/news/introducing-grok-bot, notas locais do vault.
Use este dossiê como base factual. Não invente features. Se citar algo fora daqui, marque como inferência.

## MAESTRI (macOS 15.4+ Apple Silicon; versão Windows) — "infinite canvas where coding agents work in concert"

Posicionamento: **camada de orquestração**, não é um agente. Espera que você já tenha Claude Code / Codex / OpenCode instalados. Swift/SwiftUI nativo, render Metal, zero telemetria, zero conta, storage local (JSON + Markdown). Free = 1 workspace; Pro = US$18 vitalício, 2 Macs.

### Primitivas documentadas
- **Canvas**: espaço 2D infinito, pan/zoom, minimapa, desenho à mão livre, grupos.
- **Terminal**: "a full interactive shell" desenhado no canvas; escolhe um agente de presets (Claude Code, Codex, OpenCode...). Nome e ícone próprios. Até 9 acessíveis por badge numerado (segurar Ctrl). Ctrl⇧A cicla terminais aguardando.
- **Role**: "a set of instructions for a specific terminal instance"; Maestri "automatically injects those instructions when the agent starts". Presets Lead / Coder / Reviewer / Tester. Persistido em sidecar `role.json`, viaja entre workspaces e máquinas.
- **Connection (cabo)**: linha física-animada entre terminais, ou terminal↔nota/fichário/portal. Ao conectar, "Maestri installs a **Maestri Agent Skill** in each one. This skill gives agents the ability to send prompts to, and receive responses from, any other connected agent." **Agent-agnostic**: Claude Code fala com Codex, OpenCode fala com Claude.
- **Regra crítica de foco**: ao mandar um agente falar com outro, "leave the receiving agent unselected (no dashed border)". Maestri **monitora só terminais não focados**; quando o receptor termina, "Maestri detects this and sends the answer back". Selecionar o terminal = assumir controle manual, Maestri para de monitorar. (Ou seja: a detecção de fim-de-turno é heurística sobre PTY.)
- **Note**: arquivo markdown real em disco, sticky no canvas, preview ao vivo; "agents can read and write them through the Maestri CLI". Notas encadeáveis por cabo: conectando na nota de entrada, o agente "can access the entire chain".
- **Fichário**: pasta com abas que agrupa notas; conectando o fichário a um agente "it can access every page inside". Fichários vazios nomeados viram raias de kanban (Backlog, Building, Review, Shipped).
- **Maestro Mode**: checkbox por terminal que "promotes a terminal from a regular agent into a **manager** — one that can recruit new agents to your canvas, assign them roles, wire them into the right notes, and dismiss them when their work is done." Recrutas nascem posicionados abaixo do maestro; cada um vê "its own name and role alongside its connections". Maestro pode disparar notificação de sistema ao terminar ou ao bater num bloqueio. Tende a recrutar cópias de si mesmo (dá para forçar mistura).
- **Routines**: prompts agendados por intervalo fixo (5 min, 1 h) contra um terminal escolhido; encadeamento com `&&`, "the next one only fires after the previous one completes". Pause/resume/edit/delete, indicador ao vivo. **Sem trigger por evento** — só tempo.
- **Batuta Search (Ctrl+P)**: paleta fuzzy sobre terminais, notas, blocos de texto, arquivos, links, file trees, portais e workspaces; busca corpo inteiro das notas. Ações globais + contextuais. **Ask** = manda mensagem para qualquer terminal de qualquer lugar; **Check** = versão read-only, olha a saída sem mandar nada. `Connect to…` / `Disconnect…` como ações de paleta.
- **Partitura**: template do canvas em JSON legível em `~/.maestri/partituras/` — "terminals with their agents and roles, notes, portals, file trees, drawings, groups, and every connection between them". **Não** salva scrollback, config de runtime, caminhos absolutos. Arrastável, compartilhável (`.maestripartitura`, bundle `.maestripartituras`), mantém identidade ao atualizar.
- **Floors**: "isolated branches without leaving your workspace. Each floor is a full copy of your repository that shares storage with the original" — macOS via APFS copy-on-write (rápido, quase zero disco); Windows via branch git. Guardados em `.maestri/floors`; "The floor's branch is mirrored in your original repository, so other tools (GitHub, your IDE) can see it too". Navegação em 3D pelo botão ao lado do minimapa.
- **Environments**: onde o terminal roda — Local, Local (tmux), WSL, SSH (túnel reverso), Docker container/sandbox, custom runtime (Podman, Lima). Escopo por workspace com override por terminal, persistido. Vars injetadas: `HOME`, `MAESTRI_TERMINAL_ID=<uuid>`, `MAESTRI_HOST=<bridge-endpoint>`, `MAESTRI_TOKEN=<per-terminal-secret>`; overrides não podem substituir `HOME`, `PATH` ou qualquer `MAESTRI_`. Token único por terminal, revogado ao remover provider (anti-impersonação). "Maestri never creates, starts, stops, restarts, or deletes the selected container" — ele só ataca infra existente.
- **Workspaces**: contêiner de projeto com working dir, ícone e layout salvo; rodam em background ao trocar; export `.maestri`. Escreve/sincroniza `CLAUDE.md` e `AGENTS.md` para times mistos.
- **Portals**: browser controlável, simulador iOS/emulador Android, device real; lê a árvore de elementos em vez de pixels.
- **Ombro**: assistente on-device (Apple Foundation Models, macOS 26+) que assiste tudo e resume o que aconteceu enquanto você estava fora; 100% local.
- **Prompt Composer**: composer rico com @menções.

### Leitura do modelo
Maestri = grafo espacial persistido em JSON, executado por **PTY**: "one agent typing into another's terminal", sem middleware de API. O estado vive no canvas (posições, cabos, notas em disco). O contrato entre agentes é uma **skill instalada dentro de cada CLI**, não um protocolo do orquestrador.

## GROK BOT (xAI, ago/2026)
- Roster de agentes nomeados, cada um com **seu próprio computador na nuvem** (browser + tools conectadas), sempre ligado — trabalha com o laptop desligado, sincroniza entre devices (macOS/iOS).
- Cada bot tem job description estreito. Você fala com eles individualmente **ou em group chat**: "Bots can join a group chat where they can coordinate on their own, passing work, assigning ownership, and only drawing in the user for judgment calls."
- **Roteamento por descrição**: quando um agente precisa de algo fora da sua raia, "it scans the descriptions of other agents in your fleet and routes the request to whichever one matches" — o mesmo mecanismo usado para skills.
- Triggers: conjunto pequeno — mensagem nova no Slack, evento do GitHub, mensagem do Teams.
- Memória: histórico, preferências, edge cases; aprende por demonstração ("mostrei o workflow uma vez").
- Padrão interno observado: hierarquia com bot "chief of staff" mandando em especialistas.
- Pricing: cota própria, dentro de SuperGrok / Cursor Pro / Cursor Teams; enterprise por waitlist.

## HERMES AGENT (Nous Research, MIT, fev/2026) — ver notas locais
Fontes no vault: `/home/user/mathai-wiki/pesquisa/open-agent-harness/fontes/hermes-agent-2026-07-18.md` e `.../hermes-agent-code-deep-dive-2026-07-20.md` (436 linhas, código + diagramas). Pontos-chave já registrados: gateway único multi-plataforma (Telegram/Discord/Slack/WhatsApp/Signal/CLI, 15+ adapters), loop Think-Act-Observe com `IterationBudget`, `trajectory_compressor` (protege head/tail, comprime meio), session store SQLite WAL + FTS5, memória file-backed `MEMORY.md`/`USER.md` congelada no system prompt, skills auto-criadas (padrão agentskills.io), **subagents isolados que chamam tools via RPC dentro de scripts Python** ("colapsa pipelines multi-step em turnos de zero custo de contexto"), abstração de ambiente com 6 backends (local, Docker, SSH, Singularity, Modal, Daytona), expõe-se como MCP server, cron embutido, model-agnostic via qualquer API OpenAI-compatible.

## CONTEXTO DO DONO (restrições duras)
- Repo `mathai-orchestrator` (privado). SPEC v0 já commitada (MAT-96): grafo YAML (nós=agentes, arestas=handoff com predicado `artifact_exists`), sessão = diretório em disco com `graph.yaml` + `state.json`, subprocessos com log por nó, serial no v0, parada por `DONE.md`.
- **Zero API key**: `claude -p --output-format text` via assinatura Pro; proibido `ANTHROPIC_API_KEY`, SDK, HTTP para api.anthropic.com. Integrar também CLI do Cursor (`cursor-agent`).
- Roda **acima** de terminais bash. Linux/mac, não macOS-only.
- Objetivo declarado: open-source, valor de carreira, "oceano azul".

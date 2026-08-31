# Spec — orquestrador v0

**Issue:** [MAT-96](https://linear.app/borgesmathai/issue/MAT-96) (spec) · [MAT-97](https://linear.app/borgesmathai/issue/MAT-97) (implementa)
**Repo:** este. Privado. Fora do vault. Não misturar com `mathai-harness`.
**Pronto desta sessão:** este arquivo + `graphs/v0.yaml`. Claude implementa na MAT-97.
**Fora:** wiki, hitl, SDK Anthropic, chave de API, segundo grafo, segunda sessão.

Toda escolha abaixo traz o descarte. Decisão sem alternativa não entra.

---

## 1. Modelo do grafo

| Conceito | É | Não é |
|---|---|---|
| **Nó** | Um agente: `id`, `role`, `prompt` (arquivo), `cwd` relativo à sessão | Um thread dentro do Claude Code |
| **Aresta** | Um handoff: `from`, `to`, `on` (predicado), `artifact` (caminho) | Uma chamada de API, um bus |
| **Sessão** | Uma instância viva de **um** grafo. Sessão = time | Um chat, um PR, um worktree do vault |
| **Estado** | O grafo + status de cada nó (`pending` \| `running` \| `done` \| `failed`) + quais artefatos existem | Histórico de tokens, transcript completo |

Identificadores são strings `^[a-z][a-z0-9_-]{0,31}$`. O arquivo canônico é YAML (`graphs/*.yaml`).

```yaml
id: v0
nodes:
  - id: scout
    role: scout
    prompt: prompts/scout.md
    cwd: "."
  - id: builder
    role: builder
    prompt: prompts/builder.md
    cwd: "."
edges:
  - from: scout
    to: builder
    on: artifact_exists
    artifact: handoff.md
stop:
  when: node_done
  node: builder
  artifact: DONE.md
```

**Escolhida / descartada.** YAML como fonte do grafo, não classes Python. Custo: o implementador não pode "só importar". Ganho: a spec é o mesmo arquivo que o runtime lê; o v0 da MAT-97 não inventa o modelo. Descarte: DSL própria — sem parser, sem tempo.

**Escolhida / descartada.** Estado = grafo + status + existência de artefato, não event-log append-only. Custo: replay fraco. Ganho: v0 cabe numa sessão. Event-log é evolução nomeada, não v0.

---

## 2. Como um time é instanciado

Comando (MAT-97 implementa):

```
python -m orch up graphs/v0.yaml --session-dir .sessions/<session_id>
```

1. Lê o YAML. Recusa se `id` do grafo ≠ stem do arquivo, se há nó órfão, se alguma aresta aponta para nó inexistente, se há ciclo (v0 é DAG).
2. Cria `session_dir` com `graph.yaml` copiado, `state.json` inicial (`todos pending`), subdirs vazios não.
3. O time **é** essa sessão. Não existe time fora de um `session_dir`.
4. Só um `up` por `session_dir`. Segundo `up` no mesmo dir falha. Sem resume no v0.

**Escolhida / descartada.** Instanciação = diretório de sessão no disco, não processo daemon persistente. Custo: não sobrevive a reboot com graça. Ganho: o orquestrador é um processo pai que sobe, espera o stop, sai. Sem systemd, sem tmux-as-product.

---

## 3. Como o orquestrador sobe terminais

O orquestrador **não é** o Claude Code. Cada nó running é um **subprocesso** cujo cwd é `session_dir / node.cwd`, stdout/stderr em `session_dir/logs/<node>.log`.

Ordem:

1. Nós sem aresta de entrada, ou com predicaido `on` já verdadeiro, passam a `running`.
2. Um nó `running` por vez no v0 (serial). Handoff visível = o próximo só sobe quando o `artifact` da aresta existe e o `from` está `done`.
3. Processo filho termina → nó `done` se exit 0 **e** o artefato exigido pela aresta de saída (ou pelo `stop`) existe; senão `failed` e a sessão para.
4. O orquestrador escreve `state.json` a cada transição. Isso é o grafo vivo.

**Escolhida / descartada.** `subprocess` + arquivos de log, não tmux. Custo: sem attach humano no v0. Ganho: determinístico, testável sem display. tmux fica como detalhe futuro de *observação*, não de runtime.

**Escolhida / descartada.** Serial no v0, não paralelo. Custo: time de 2 nós é uma fila. Ganho: um handoff visível, uma corrida, um critério de parada. Paralelo é segundo grafo, não esta sessão.

---

## 4. Como invoca Claude Code Pro (zero API)

Binário: `claude` no `PATH` (ou `CLAUDE_BIN`). Auth = login da assinatura Pro no ambiente (`claude auth login` já feito). **Proibido:** `ANTHROPIC_API_KEY`, `anthropic` SDK, HTTP para `api.anthropic.com`.

Invocação por nó:

```
claude -p --output-format text "$(cat <prompt-file>)"
```

- `cwd` = `session_dir / node.cwd`
- env herda o do orquestrador **menos** qualquer `ANTHROPIC_API_KEY` (o orquestrador unset se existir)
- o prompt file é o do nó, com um preâmbulo gerado: `session_dir`, `artifact` esperado, `id` do nó
- não passa `--model` no v0 (usa o default da assinatura)
- não usa modo interativo (sem TTY no filho)

Se `claude` não estiver no PATH ou `claude auth status` falhar, o `up` aborta **antes** de subir nó, com mensagem que aponta para o login da Pro — não para gerar uma chave.

**Escolhida / descartada.** CLI `-p` (print / headless), não TTY interativo. Custo: perde slash-commands e /login no filho. Ganho: o orquestrador consegue esperar exit code. Interativo é para o humano no desktop, não para o nó.

**Escolhida / descartada.** Assinatura Pro via CLI, não API. Custo: depende do binário e do login local. Ganho: é o que o dono tem; zero fatura de API; o mesmo Claude Code que ele já usa.

---

## 5. v0 cortado

Cabe nesta sessão de implementação (MAT-97), e só isto:

| Peça | v0 | Fora (nomeado, não agora) |
|---|---|---|
| Grafos | **um:** `graphs/v0.yaml` | loader de pasta, registry |
| Sessão | **uma** por `up` | multi-session, resume |
| Handoff | **um** visível: `handoff.md` escrito pelo `scout`, lido pelo `builder` | bus, inbox, n handoffs |
| Parada | `builder` exit 0 **e** `DONE.md` existe | timeout como único critério, HITL, webhook |
| Nós | 2 | N>2, fan-out, ciclo |

Critério de parada (literal): a sessão termina com código 0 quando o nó `builder` está `done` e `session_dir/DONE.md` existe. Qualquer `failed` → exit 1. O orquestrador não pergunta a ninguém.

Handoff visível: `handoff.md` é arquivo no `session_dir`. O `builder` não sobe se o arquivo não existe. Log do orquestrador imprime uma linha:

```
handoff scout → builder artifact=handoff.md
```

**Pronto da MAT-97 (não desta):** comando que sobe a sessão, essa linha de handoff, critério de parada, hash no repo.

---

## 6. O que a MAT-97 não decide

Já fechado aqui. Não reabrir no código:

- sem API, sem SDK
- sem misturar este repo com `mathai-harness`
- sem wiki, sem label `hitl`
- sem segundo grafo
- sem tmux como runtime
- sem daemon

Se o CLI `claude -p` mudar de flag, emenda datada neste `SPEC.md` **antes** de adaptar o código.

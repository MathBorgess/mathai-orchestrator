# mathai-orchestrator

Private factory SKU. **Not** [`mathai-harness`](https://github.com/MathBorgess/mathai-harness) (TG noise-floor / experiment).

Você declara o time num arquivo versionado, roda a mesma tarefa com dois times diferentes, e recebe um número dizendo qual funcionou — **inclusive o número que diz que um agente solo era melhor**.

- Uma sessão = um time.
- Graph engineering: nós são agentes, arestas são handoffs, estado da sessão é o grafo.
- Roda **acima** de terminais. Não substitui o Claude Code.
- Claude Code / Claude Pro via **CLI apenas**. Zero API da Anthropic. Zero SDK.
- A categoria não é "orquestrador de agentes". É **banco de provas de topologia de time** — o concorrente mental é `pytest`, não um canvas.

## Para quem não é

- Quem quer **ver** oito agentes trabalhando numa tela bonita → Maestri, Conductor.
- Quem quer **entregar mais features hoje** → instrumento desacelera antes de acelerar.
- Quem roda em **CI de empresa** com SSO e retenção → OpenHands, Devin.
- Quem **não consegue rodar a mesma tarefa duas vezes** → sem repetição não existe medida.
- Quem quer o painel e não quer o veredito. Se o número disser que seu time de 3 agentes é pior que 1 agente solo, esse número vai ser impresso.

## v0

```
python -m orch up graphs/v0.yaml --session-dir .sessions/<id>
```

One graph, one session = one team. Serial `scout` → `builder`. The visible handoff is `handoff.md`. The session exits 0 when `builder` is `done` and `DONE.md` exists; any `failed` node exits 1. Claude Code Pro via `claude -p` only — no Anthropic API key.

## Estado — 2026-08-31

v0 runtime is in `orch/` (MAT-97). v1 remains spec-only.

A spec é **paralela desde o v1**: o `fanout` é a forma única de declarar concorrência, o teto é 3, a concorrência default é `auto` degradando por utilização da janela, e o veredito imprime o número que separa paralelismo útil de paralelismo decorativo.

| Documento | O que é |
|---|---|
| [`SPEC.md`](SPEC.md) | **spec v1 (paralela)**: 4 tipos de nó, fanout+join, escalonador de conjunto pronto, gate de janela, veredito de 3 números |
| [`MVP.md`](MVP.md) | o protótipo: tipos de nó, predicado de conclusão, adapters com comando exato, orçamento, feed, veredito |
| [`EXPERIMENTO.md`](EXPERIMENTO.md) | pré-registro (esqueleto): 12 tarefas, 3 braços, critérios numéricos, cláusula de morte |
| [`START.md`](START.md) | o passo a passo do arranque, com o plano de ondas de subagentes |
| [`graphs/v1.yaml`](graphs/v1.yaml) · [`graphs/v0.yaml`](graphs/v0.yaml) | o grafo paralelo (scout → fanout×3 → join → 2 checks) e a cadeia de 2 nós |
| [`research/`](research/) | teardown do Maestri, mesa-redonda, dossiê de fontes, os 4 memoriais íntegros e os [rascunhos da spec v1](research/spec-v1-drafts/) |

**Implementação (MAT-97):** v0 is `python -m orch up graphs/v0.yaml --session-dir .sessions/<id>`. v1 waits on [`EXPERIMENTO.md`](EXPERIMENTO.md) §4.

## Pesquisa

- [Levantamento e engenharia reversa do Maestri](research/2026-08-30-maestri-teardown.md) — inventário completo das features e como cada peça seria construída.
- [Mesa-redonda](research/2026-08-30-mesa-redonda.md) — quatro pesquisas independentes e paralelas (harness/graph engineering, design de team chat, engenharia do Hermes, devil's advocate) sobre como Maestri, Grok Bot e Hermes integram time de agentes; 14 pontos de consenso e as divergências que ficaram abertas.
- [Memoriais íntegros](research/teammates/) — inclui 15 papers em fonte primária, 20 testes executados contra o `claude` CLI 2.1.251, e o mapa competitivo de 15 produtos.

## Exposição de ToS — declarada, não escondida

Este projeto automatiza um CLI autenticado por **assinatura de consumidor**, não por chave de API. Isso é uma escolha deliberada e é também o maior risco não técnico do repo:

- **2026-02-20** — a Anthropic passou a bloquear o uso de OAuth de assinatura fora do Claude Code.
- **2026-05-14** — anunciou mover `claude -p` e o Agent SDK para um pool de créditos separado.
- **2026-06-15** — pausou a mudança, prometendo reformular o plano.

É uma **moratória, não uma garantia**. Consequências assumidas: concorrência default **1**, paralelismo opt-in explícito; gate por utilização observada da janela, com pausa até o reset e **nunca** retry cego em 429; teto de orçamento por nó. Você roda sob a **sua própria** conta — sem credencial compartilhada, sem multi-conta, sem rodar por terceiros. E o adapter genérico `exec` existe para que o projeto aponte para outro binário no dia em que a porta fechar.

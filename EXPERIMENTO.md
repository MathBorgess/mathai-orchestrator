# Experimento — pré-registro (esqueleto)

**Data do desenho:** 2026-08-30 · **Issue:** [MAT-96](https://linear.app/borgesmathai/issue/MAT-96)
**Status:** **esqueleto, não pré-registro válido.** Vira pré-registro quando as 12 tarefas estiverem congeladas, o arquivo commitado e o hash colado no README — **antes** do primeiro run.

Um critério de sucesso escrito depois do resultado não é critério, é narrativa.

---

## 1. A pergunta

O grafo de agentes entrega mais que um agente solo na mesma tarefa, o suficiente para pagar o próprio custo?

A resposta default esperada pela literatura é **não**: procedimento inteiro no prompt bate orquestração em 15/15 comparações em tarefa procedural (arXiv:2604.27891); a collaboration tax é positiva em quase toda célula e **decresce com a capacidade do modelo** (2608.22152); o ganho de MAS some conforme β cresce (2607.16133). O experimento existe para medir **o nosso** caso, não para confirmar o esperado.

## 2. Desenho

**12 tarefas**, extraídas de commits já feitos em repos que o dono conhece — o enunciado é a tarefa, o commit real é o gabarito. Congeladas num arquivo com hash antes do primeiro run.

**Três braços**, mesma tarefa, mesmo modelo, ordem aleatorizada:

| Braço | O que é | Por que existe |
|---|---|---|
| **A — controle** | um `claude -p` solo, procedimento inteiro no prompt | o baseline que a literatura diz que ganha |
| **B — tratamento** | grafo de 2 nós `scout → builder`, handoff por `handoff.md` (o `graphs/v0.yaml`) | a hipótese |
| **C — placebo estrutural** | grafo de 2 nós com papéis trocados ou invertidos | separa "a topologia fez efeito" de "rodou duas vezes e gastou mais" |

**3 repetições por braço por tarefa = 108 runs.** Sequencial, é uma noite de máquina.

**O braço C é o que separa isto de teatro.** Sem ele, qualquer ganho de B sobre A é explicável por "gastou mais tokens", e é exatamente essa a primeira pergunta que uma banca faz.

**Ressalva de método já registrada:** 3 repetições é o mínimo operacional, e é menos que as 5 seeds por célula que a própria mesa estabeleceu como piso para decisão de desenho (a mesma célula, com modelo pinado, deu expoente 1,76 e 2,44 em duas coletas). Se o resultado ficar na fronteira, o remédio é mais seeds, não mais interpretação.

## 3. Critérios — a preencher e congelar antes do primeiro run

| Métrica | Como se lê | Passa se | Morre se |
|---|---|---|---|
| **Retrabalho evitado** *(primária)* | linhas escritas que são revertidas/reescritas na 2ª passada de extensão ÷ linhas escritas | B bate A em **≥8 das 12 tarefas**, mediana **≥20 pp** | B bate A em ≤6 de 12, **ou** B não se separa de C |
| **Taxa de conclusão** | run termina com o artefato exigido e teste passando | B ≥ A, sem regressão maior que 1 tarefa | B < A em ≥3 tarefas |
| **Custo do handoff** | tokens (proxy: `log_bytes`) de B ÷ de A | ≤ **2,5×** | > 3,5× |
| **Tempo até primeira sessão útil** | `git clone` → primeiro veredito impresso, cronometrado em **3 pessoas que não são o dono**, sem ajuda | mediana **≤15 min**, 3/3 concluem | alguém desiste, ou mediana > 30 min |
| **Adoção** *(30 dias após o relatório público)* | pessoas que rodaram **no repo delas** e mandaram o número | **≥5** | ≤1 — é um brinquedo pessoal, e tudo bem assumir isso |

Estrela e fork **não entram na régua**. Cinco tabelas de terceiros valem uma seção de resultados; 300 estrelas valem uma linha morta no perfil.

## 4. Sequenciamento

| Data | Entrega | Regra |
|---|---|---|
| **14/09** | G1 + simulação do piso de ruído | **nenhuma linha de runtime antes disso** |
| **21/09** | proposta entregue **e** este arquivo virado pré-registro (12 tarefas, 3 braços, tabela do §3, hash) | escrito antes de existir resultado |
| **22/09 – 05/10** | os 108 runs + o relatório | duas semanas cronometradas |
| **06/10** | **veredito** | passa → MAT-97 vira instrumento; falha → o repo vira o relatório |
| **16/10** | submissão a CFP | o relatório é o abstract |

**Bloqueadores antes de qualquer linha de runtime**, na íntegra do devil's advocate:

1. G1 (14/09) e proposta (21/09) entregues, sem antecipar trabalho de orquestrador para dentro dessa janela.
2. As cinco perguntas do orientador (pivô de 20/08) respondidas por escrito, num arquivo.
3. **arXiv:2604.17883 lido na íntegra**, com um parágrafo dizendo se ele já mede topologia de time. Se já mede, este projeto muda de pergunta ou morre — e é melhor saber antes de 21/09.

**A cláusula que torna isto honesto:** se o cronograma não couber, o experimento **substitui** a implementação. Nada de runtime, nada de `state.json` — só bash, os três braços e o número. O caminho mais rápido para descobrir se este projeto merece existir não passa por construí-lo.

## 5. A cláusula de morte

Se a métrica primária falhar — B não bate A em ≥8 de 12, ou B ≈ C — o repositório:

1. publica o resultado negativo, com dados;
2. ganha a tag `v0.1-negative-result`;
3. é arquivado com motivo escrito;
4. e o dono volta 100% para o TG.

Isso não é fracasso. É o experimento fazendo o trabalho pelo qual foi desenhado: **matar seis meses de construção com duas semanas de medição.**

## 6. Por que isto é o ativo de carreira, e o código não é

Repositório de orquestrador é commodity — há 214+ deles. Relatório com pré-registro, braço de controle e **resultado negativo aceito** é raro, inclusive dentro da literatura de agentes.

Se o experimento falhar, o produto de carreira é: *"pré-registrei uma hipótese sobre topologia de time de agentes, rodei 108 sessões controladas com placebo estrutural, e o time de dois nós não bateu o agente solo. Aqui está o método, aqui estão os dados, aqui está o que eu faria diferente."* Isso é mais empregável que um repo funcional com 3 estrelas — e é literalmente o comportamento que a banca cobra.

Conexão com o TG (pivô de 20/08, governança de código colaborativa sobre o tau): três das cinco perguntas em aberto do orientador são exatamente o que este experimento precisa responder para existir — como o projeto é especificado durante o experimento (é o grafo versionado + o pré-registro), qual é o ponto de virada precisamente (é a 2ª passada de extensão da métrica de retrabalho), e o que é greenfield de verdade (é o desenho do §2, com gabarito conhecido e ordem aleatorizada).

## 7. Como não virar mais um repo morto com 3 estrelas

1. **Publique o resultado antes do produto.** O README abre com a tabela de resultados. Sem resultado, não publica.
2. **Escreva "para quem NÃO é" no README.** Repo que declara para quem não serve é lido como sério.
3. **Proíba roadmap no README.** Roadmap em repo solo é promessa que documenta o próprio abandono. Issues sim.
4. **Uma tag com hash e uma data de reavaliação.** `v0.1` no dia do veredito, e a linha: *"reavaliado em 30/11; se ninguém além do autor tiver rodado, arquivado."*
5. **Não peça estrela. Peça o número.** CTA é "rode no seu repo e me mande sua tabela"; cada tabela recebida entra no relatório com crédito.
6. **Amarre à data da banca.** Prazo externo, contraparte que não é você, cadência própria — a banca fornece os três.

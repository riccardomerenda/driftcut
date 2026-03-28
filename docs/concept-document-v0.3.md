# Driftcut — Concept Document v0.3

**An early-stop canary for LLM model migrations**

---

## 1. One-line positioning

**Driftcut helps teams stop bad LLM migrations early, before they waste budget on full-scale evaluation runs.**

Driftcut è un canary test per migrazioni LLM: ti dice presto se vale la pena continuare un test di migrazione oppure fermarti subito prima di spendere troppo.

---

## 2. The problem

Quando un team vuole passare da un modello LLM a un altro — per costo, latenza, privacy o qualità — il processo è spesso inefficiente:

1. Si sceglie un modello candidato.
2. Si lancia un test sull'intero corpus di prompt reali.
3. Si consuma budget su centinaia o migliaia di esecuzioni.
4. Solo alla fine si scopre che il candidato non regge uno o più casi critici.
5. Si riparte da zero con un altro modello.

Il problema non è "valutare qualità". Il problema è che **il team scopre troppo tardi che la migrazione non è promettente**.

Questo produce spreco di denaro in API calls, tempi lunghi di feedback, scarsa propensione a testare alternative e lock-in operativo verso il modello corrente.

---

## 3. Core insight

Driftcut non serve a fare una valutazione completa. Serve a rispondere prima a una domanda più importante:

> "Dobbiamo continuare questa migrazione, oppure si sta già dimostrando una cattiva idea?"

Il cuore del progetto è **early stopping decision support for model migration** — non dashboard, experiment tracking, prompt management o generic evaluation.

---

## 4. Product definition

Driftcut è uno strumento CLI-first che esegue una migrazione LLM come un canary rollout.

Invece di valutare l'intero corpus, il sistema:

- Divide il corpus in categorie.
- Seleziona piccoli batch iniziali rappresentativi.
- Confronta modello corrente e modello candidato su qualità e latenza.
- Misura divergenza e failure patterns.
- Decide se fermare il test, continuare il campionamento, o dichiarare il candidato promettente per una full evaluation.

Il valore è **evitare di scoprire troppo tardi che il test stava andando male**.

---

## 5. What it is not

### Driftcut non è:

- Un framework generale di eval.
- Una piattaforma di experiment tracking.
- Un sistema di prompt optimization.
- Uno strumento di observability LLM completo.
- Un sostituto di una full evaluation.

### Driftcut è:

- Un **pre-evaluation filter**.
- Un **migration canary**.
- Un **budget-saving decision layer**.
- Uno strumento per capire **se vale la pena continuare**.

---

## 6. Target users

### Primary users

- AI engineers e platform engineers.
- Software engineers che gestiscono feature LLM in produzione.
- Engineering managers responsabili di costi e qualità dei sistemi LLM.

### Best-fit scenarios

- Confronto tra provider diversi.
- Migrazione verso modelli più economici o verso modelli locali/self-hosted.
- Verifica rapida prima di una full evaluation costosa.
- Confronto tra versioni diverse dello stesso provider.

---

## 7. User pain

> "Non voglio spendere centinaia di euro per scoprire solo alla fine che il nuovo modello rompe categorie importanti del mio prodotto."

> "Prima di fare una migration run massiva, voglio un segnale abbastanza affidabile per decidere se proseguire o fermarmi."

---

## 8. Product promise

**Primary:** Stop bad migrations early.

**Secondary:** Riduci il costo dei migration test. Ottieni feedback per categoria e per latenza. Capisci dove il candidato fallisce. Porta a full evaluation solo i candidati promettenti.

---

## 9. Dimensions of comparison

La migrazione non riguarda solo la qualità dell'output. Driftcut confronta baseline e candidato su tre dimensioni:

### 9.1 Quality

Qualità dell'output rispetto al baseline: aderenza al formato, completezza, correttezza, assenza di hallucination.

Misurata tramite judge model e failure archetypes.

### 9.2 Latency

Tempo di risposta del candidato rispetto al baseline.

Per molti team, la latenza è il driver principale della migrazione, o il motivo per cui la migrazione fallisce. Driftcut misura p50, p95 e varianza per categoria, e segnala regressioni di latenza significative anche quando la qualità è stabile.

### 9.3 Cost

Costo per prompt e costo totale della run.

Driftcut tiene traccia della spesa progressiva e della spesa evitata interrompendo in anticipo un test non promettente.

---

## 10. MVP scope

### MVP goal

Dato un corpus categorizzato e due modelli, Driftcut deve produrre entro il 10–20% del corpus una raccomandazione chiara:

- **Stop now**
- **Continue sampling**
- **Safe for full evaluation**
- **Safe only for selected categories**

### MVP includes

- CLI tool.
- Caricamento corpus da CSV o JSON.
- Supporto a due modelli per run.
- Esecuzione progressiva per batch.
- Categorizzazione dei risultati.
- Confronto current vs candidate su qualità, latenza e costo.
- Failure archetypes.
- Cost tracking e latency tracking.
- Terminal report.
- Export JSON dei risultati.

### MVP excludes

- Web dashboard.
- Multi-user collaboration.
- Experiment tracking avanzato.
- Ottimizzazione automatica dei prompt.
- Supporto a decine di provider dall'inizio.
- CI/CD integration nella prima versione.

---

## 11. The real output of the system

L'output più importante non è uno score numerico. È una **decisione operativa spiegata**.

### Decision

Una delle quattro:

- **Stop now**
- **Continue**
- **Proceed to full evaluation**
- **Proceed only for low-risk categories**

### Why

Spiegazione sintetica: quali categorie stanno fallendo, quali failure patterns emergono, quanta spesa è stata evitata, come si comporta la latenza, quanto il candidato diverge dal baseline.

### Evidence

3–10 esempi concreti di failure, breakdown per categoria, breakdown per failure type, confronto latenza per categoria.

---

## 12. Failure archetypes

Il report non deve dire solo "quality drop". Deve classificare i problemi.

- **Format break** — l'output non rispetta il formato atteso.
- **Schema break** — JSON mancante, campi errati, struttura incompatibile.
- **Coverage drop** — risposta incompleta rispetto al baseline.
- **Reasoning degradation** — il modello è meno affidabile nei casi complessi.
- **Refusal increase** — il candidato rifiuta più spesso del baseline.
- **Tone mismatch** — lo stile peggiora per il caso d'uso.
- **Hallucination increase** — il candidato introduce più contenuti dubbi o inventati.
- **Latency regression** — il candidato è significativamente più lento del baseline.

Questa classificazione trasforma il risultato da score astratto a informazione azionabile.

---

## 13. Corpus model

### Prerequisiti

Driftcut richiede che l'utente porti un corpus già strutturato. Questo è un requisito esplicito, non un dettaglio secondario.

Il tool non genera, suggerisce o classifica prompt automaticamente. La qualità del canary dipende direttamente dalla qualità del corpus.

### Schema minimo

Ogni prompt deve avere almeno:

| Campo | Tipo | Note |
|---|---|---|
| id | string | Identificativo unico |
| category | string | es. `customer_support`, `extraction`, `classification` |
| prompt | string | Il prompt da eseguire |
| criticality | enum | `low` / `medium` / `high` |
| expected_output_type | enum | `free_text` / `json` / `labels` / `markdown` |
| notes | string | Opzionale |

Questo schema permette di evitare un errore comune: trattare tutte le categorie come se avessero lo stesso peso.

### Bootstrap helper (post-MVP)

Per abbassare la barriera d'ingresso, una futura versione potrebbe includere un helper che, dato un file di prompt non strutturato, suggerisce categorie e criticità.

Questo non è parte dell'MVP ma va considerato nella roadmap.

---

## 14. Decision engine

### Filosofia

Il decision engine è euristico e dichiaratamente tale. Non è un sistema infallibile: è **decision support for early migration filtering**.

Le soglie di default sono punti di partenza ragionevoli che l'utente deve calibrare sul proprio contesto.

### Come funziona

Per ogni batch, il sistema:

1. Confronta output baseline e candidate.
2. Assegna un punteggio sintetico di compatibilità.
3. Misura divergenza per categoria.
4. Rileva failure archetypes.
5. Pesa di più le categorie high criticality.
6. Misura latenza per categoria.

### Stopping logic

**Stop now** se:

- Una categoria high criticality supera la soglia di failure (default: 20% — motivazione: una failure su 5 in un campione piccolo segnala rischio elevato, specialmente se il batch è stato selezionato per rappresentatività).
- Compaiono schema breaks ripetuti (default: 25% del batch — motivazione: i break strutturali raramente migliorano con più dati; sono segnali forti).
- La divergenza resta alta per più batch consecutivi.

**Continue** se:

- I segnali sono misti o poco stabili.
- Non ci sono failure gravi ma la varianza è alta.

**Proceed to full evaluation** se:

- Le categorie critiche restano stabili per almeno `min_batches` consecutivi.
- La divergenza resta sotto la soglia di rischio (default: 8%).
- Non emergono break strutturali.
- La latenza non mostra regressioni significative.

### Calibrazione

Le soglie di default sono conservative: progettate per favorire falsi negativi (fermare un test che forse poteva continuare) piuttosto che falsi positivi (approvare un candidato che poi fallisce in produzione).

L'utente può e deve adattarle via config. Il tool deve esporre chiaramente quali soglie sono state usate e quanto i risultati sono vicini ai confini di decisione.

### Evoluzione post-MVP

Nella v0.2, il motore può adottare un approccio di sequential testing (es. sequential probability ratio test) per dare una stima formale di confidenza sulla decisione.

Questo non è necessario per l'MVP ma rafforza significativamente la credibilità tecnica del progetto.

---

## 15. Statistical confidence

### Il problema

Con il 10–20% del corpus, la domanda legittima è: quanto è affidabile il segnale?

### Approccio MVP

Nel v0.1, Driftcut non calcola p-value o intervalli di confidenza formali. Usa invece un approccio pragmatico:

- Campionamento stratificato per categoria e criticità, per garantire che i batch siano rappresentativi.
- Soglie conservative (vedi sopra) per minimizzare il rischio di falsi positivi.
- Report che indica esplicitamente la dimensione del campione e la percentuale del corpus testato, perché l'utente possa valutare da sé la robustezza del segnale.

### Approccio post-MVP

Nella v0.2, il sistema può implementare sequential hypothesis testing (SPRT o varianti). Questo permette di dire formalmente: "con questa quantità di dati, la probabilità che il candidato sia adeguato è sotto/sopra la soglia X".

Questa è una feature differenziante rispetto ai tool che danno uno score senza contesto statistico.

### Cosa comunicare all'utente

Il report deve sempre indicare: quanti prompt sono stati testati vs il totale, quanti per categoria, e un indicatore qualitativo di confidenza (`bassa` / `media` / `alta`) basato sulla dimensione del campione e sulla stabilità dei risultati tra batch.

---

## 16. The judge cost paradox

### Il problema

Driftcut promette di risparmiare budget. Ma se ogni confronto richiede una chiamata a un modello giudice, il costo del giudice può diventare significativo — e nei casi peggiori, superare il costo del candidato stesso.

### Strategia

**Livelli di judge progressivi:**

1. **Batch 1–2: regole deterministiche (costo zero).**  
   Prima di chiamare un judge, il sistema verifica con controlli meccanici: l'output è JSON valido? Rispetta lo schema atteso? La lunghezza è nel range? Ci sono refusal patterns noti? Questi check catturano i failure più grossolani senza spendere nulla.

2. **Batch 2–3: judge leggero.**  
   Per i prompt che passano i check deterministici, si usa un modello piccolo ed economico come judge (es. GPT-4.1-mini, Claude Haiku). Sufficiente per confronti di qualità generale.

3. **Batch 3+: judge pesante solo se necessario.**  
   Solo se i segnali restano ambigui e la decisione non è chiara, si scala a un judge più capace. Questo succede raramente, perché la maggior parte dei casi viene risolta prima.

### Costo stimato

Un canary run tipico (120 prompt, 20% testati, 24 prompt) con judge leggero costa circa 0.50–2.00 USD in judge calls — una frazione del costo di una full evaluation.

Il report deve includere il costo del judge nella stima del costo totale.

---

## 17. Architecture

```text
┌──────────────────────────────────────────────┐
│                   Driftcut                   │
│                                              │
│   CLI                                        │
│   ├── Config Loader                          │
│   ├── Corpus Loader                          │
│   ├── Batch Sampler (stratified)             │
│   ├── Migration Runner                       │
│   ├── Deterministic Checker                  │
│   ├── Judge Adapter (tiered)                 │
│   ├── Failure Classifier                     │
│   ├── Latency Tracker                        │
│   ├── Decision Engine                        │
│   └── Report Generator                       │
│                                              │
├──────────────────────────────────────────────┤
│                  Storage                     │
│   ├── SQLite                                 │
│   └── JSON export                            │
├──────────────────────────────────────────────┤
│               Model Adapters                 │
│   ├── OpenAI                                 │
│   ├── Anthropic                              │
│   └── Local/Other (future)                   │
└──────────────────────────────────────────────┘
```

---

## 18. CLI experience

### Example command

```bash
driftcut run --config migration.yaml
```

### Example result

```text
Run: GPT-4o → Claude Haiku
Corpus: 120 prompts, 4 categories
Batches executed: 2/6
Prompts tested: 24/120 (20%)
Confidence: medium (2 batches, stratified)

Quality:
  Overall compatibility: 0.61
  High-criticality failure rate: 62.5% (5/8)

Latency:
  Baseline p50: 820ms | Candidate p50: 340ms (-58%)
  Baseline p95: 2100ms | Candidate p95: 890ms (-57%)

Cost:
  Spend so far: $11.80 (incl. $0.72 judge)
  Estimated spend avoided: $74.30

Decision: STOP NOW

Reason:
- Category "structured_extraction" shows repeated schema breaks (4/6)
- Category "customer_support" is stable
- High-criticality prompts failed in 5 of 8 cases
- Latency improved significantly but quality regression is blocking
- Candidate not suitable for full eval without prompt adaptation

Top failure archetypes:
1. Schema break (4 occurrences)
2. Coverage drop (3 occurrences)
3. Refusal increase (2 occurrences)

Thresholds used:
  stop_on_high_criticality_failure_rate: 0.20 (actual: 0.625)
  stop_on_schema_break_rate: 0.25 (actual: 0.667)
```

---

## 19. Example config

```yaml
name: "OpenAI to Anthropic canary"
description: "Early-stop migration test for support prompts"

models:
  baseline:
    provider: openai
    model: gpt-4o
  candidate:
    provider: anthropic
    model: claude-haiku

corpus:
  file: prompts.csv

sampling:
  batch_size_per_category: 3
  max_batches: 5
  min_batches: 2

risk:
  high_criticality_weight: 2.0
  stop_on_schema_break_rate: 0.25
  stop_on_high_criticality_failure_rate: 0.20
  proceed_if_overall_risk_below: 0.08

evaluation:
  judge_strategy: tiered          # none | light | tiered | heavy
  judge_model_light: openai/gpt-4.1-mini
  judge_model_heavy: openai/gpt-4.1
  detect_failure_archetypes: true

latency:
  track: true
  regression_threshold_p50: 1.5   # flag if candidate p50 > 1.5x baseline
  regression_threshold_p95: 2.0

output:
  save_json: true
  save_examples: true
  show_thresholds: true
  show_confidence: true
```

---

## 20. Tech stack (v0.1)

- **Python 3.12**
- **Typer** per CLI.
- **LiteLLM** per adapter multi-provider.
- **SQLite** per persistenza leggera.
- **httpx + asyncio** per concurrency.
- **Rich** per terminal output.
- **Pydantic** per config e data model.
- **YAML** per configurazione.

Stack ottimizzato per velocità di sviluppo, facilità di test, packaging e iterazione rapida.

---

## 21. Open-source strategy

### Core open-source

CLI, corpus loader, samplers, adapters, failure classifier, decision engine, report generator.

### Why open source

Dimostra leadership tecnica, raccoglie feedback reali, rafforza il portfolio, favorisce adozione CLI-first.

### Possible commercial layer (later)

Dashboard, history e comparison tra run, team collaboration, scheduled checks, audit trail.

Solo se emerge domanda reale.

---

## 22. Competitive positioning

Driftcut non compete con eval framework generici (promptfoo, deepeval, ragas). Quelli rispondono a "quanto è buono il mio modello?".

Driftcut risponde a: **"devo continuare questo test o sto sprecando soldi?"**

La differenza è che i framework di eval sono strumenti di misurazione. Driftcut è uno strumento di decisione.

Se un team usa già un eval framework per la full evaluation, Driftcut si posiziona come il passo che viene prima: il filtro che decide se la full evaluation vale la pena.

---

## 23. Risks and mitigations

### 1. Scope creep verso generic eval

**Mitigation:** Confini stretti. No experiment suite completa, no prompt optimization, no enterprise platform troppo presto. Se una feature non serve alla domanda "stop o continua?", non entra.

### 2. Decision logic percepita come arbitraria

**Mitigation:** Soglie documentate con motivazione, calibrazione esplicita dall'utente, report che mostra quanto i risultati sono vicini ai confini di decisione. Sequential testing nella v0.2.

### 3. Il judge introduce rumore

**Mitigation:** Judge come componente, non fondazione. Check deterministici prima del judge. Strategia tiered per controllare costi e rumore.

### 4. Corpus prerequisite troppo alto

**Mitigation:** Documentazione chiara del formato richiesto. Template CSV/JSON di esempio. Bootstrap helper nella roadmap post-MVP.

### 5. Conflitto con lavoro interno

**Mitigation:** Nessun riuso di codice interno, prompt reali, dataset interni, benchmark aziendali. Demo, benchmark e corpus sintetici o pubblici.

---

## 24. Portfolio value

Come progetto portfolio mostra: system design, product framing, CLI engineering, async execution, cost-aware architecture, AI integration pragmatica, capacità di trovare una wedge reale.

> "Ho costruito un migration canary per sistemi LLM. L'obiettivo non era fare un eval framework completo, ma ridurre lo spreco nei test di migrazione. Il tool rileva regressioni precoci, classifica i failure archetypes e aiuta a fermare test non promettenti prima che consumino troppo budget."

---

## 25. Roadmap (6 settimane)

### Settimana 1–2: Foundation

- Schema corpus + template di esempio.
- Config loader + validation con Pydantic.
- Model adapters minimi (OpenAI, Anthropic via LiteLLM).
- Batch sampler con campionamento stratificato.
- Run baseline vs candidate su piccoli batch.

### Settimana 3–4: Intelligence

- Deterministic checker (schema, format, refusal).
- Judge integration con strategia tiered.
- Failure classifier.
- Latency tracker.
- Cost tracking.

### Settimana 5: Decision + Report

- Early-stop logic con soglie configurabili.
- Category weighting.
- Terminal report con Rich.
- JSON export.
- Indicatore di confidenza.

### Settimana 6: Polish + Launch

- CLI polish, help, error handling.
- README serio con example run.
- Sample dataset sintetico.
- Benchmark demo pubblico.

---

## 26. Definition of done (v0.1)

Il progetto è "done" quando un utente può:

1. Preparare un corpus con categorie e criticità.
2. Confrontare baseline e candidate su qualità, latenza e costo.
3. Ottenere una decisione stop / continue / proceed con motivazione.
4. Vedere i principali failure archetypes.
5. Capire quanto budget ha evitato di sprecare.
6. Vedere le soglie usate e la confidenza del risultato.
7. Usare il tool senza dashboard, solo da CLI.

---

## 27. Tagline options

**Tecnica:** Early-stop canary testing for LLM model migrations.  
**Prodotto:** Know when to stop a bad model migration before it burns your budget.  
**Enterprise:** Risk-aware migration gating for production LLM systems.

# Persona Building & Evaluation — Annotated Reading List

A working bibliography for building and evaluating LLM personas, oriented toward a
voice-agent discernment companion ("Inigo"). The field has no canonical book yet; it
lives in arXiv preprints from the last ~18 months plus a few journal pieces and
practitioner essays. Entries marked ★ are the highest-priority for this specific
use case.

> Note on links: arXiv IDs below were taken from search results in-session except a
> few benchmark-family entries reconstructed from memory and marked *(verify ID)*.
> Always confirm the identifier before citing formally.

---

## 0. Conceptual grounding

- **Shanahan, McDonell & Reynolds — "Role play with large language models"**
  *Nature*, 2023 · arXiv:2305.16367
  The paper that framed LLM personas as role-play and an LLM as "a superposition of
  characters." The conceptual lens the rest of this list builds on. Read first.

---

## 1. Evaluating your evaluator (LLM-as-judge bias)

The judge is a component that fails silently. Validate it against your own labels
before trusting it, and re-validate whenever you change *the judge*, not just the agent.

- ★ **PersonaEval: Are LLM Evaluators Human Enough to Judge Role-Play?**
  arXiv:2508.10014
  Most relevant judge paper here. Tests whether LLM judges can identify which persona
  is speaking; even the best models reach only ~69% accuracy — below the bar for
  reliable evaluation. Takeaway: don't trust an LLM judge for persona fidelity until
  validated against human labels.

- **Justice or Prejudice? Quantifying Biases in LLM-as-a-Judge**
  arXiv:2410.02736 · site: llm-judge-bias.github.io
  The broad taxonomy — position, verbosity, self-enhancement, plus order, bandwagon,
  authority, and beauty biases. Good single-source overview of what can go wrong.

- **Judging the Judges: A Systematic Study of Position Bias in LLM-as-a-Judge**
  arXiv:2406.07791
  Depth on the bias that distorts pairwise model comparisons; introduces preference-
  fairness and repetition-stability metrics beyond simple position-consistency.

- **Self-Preference Bias in LLM-as-a-Judge**
  arXiv:2410.21819
  — and **Panickssery et al., "LLM Evaluators Recognize and Favor Their Own Generations"**
  (NeurIPS 2024, arXiv:2404.13076 *(verify ID)*)
  Directly relevant when comparing Claude vs GPT outputs: models favor their own
  generations, and self-recognition correlates with self-preference strength. Never let
  a model from one family judge a head-to-head that includes its own family.

- **LLM-as-a-Judge vs Human Evaluation** (Galileo, practitioner blog)
  https://galileo.ai/blog/llm-as-a-judge-vs-human-evaluation
  Accessible summary of the bias list with rough effect sizes and mitigations.

---

## 2. Persona fidelity benchmarks (how the field scores "in-character")

- **RPEval / Role-Playing Eval**
  arXiv:2505.13157
  Scores across emotional understanding, decision-making, moral alignment, and
  in-character consistency. The moral-alignment axis matters for a spiritual agent.

- **InCharacter: Evaluating Personality Fidelity in Role-Playing Agents through
  Psychological Interviews**
  arXiv:2310.17976 *(verify ID)*
  Measures personality fidelity via psychometric interviews — a method worth adapting.

- **Benchmark family — CharacterEval, CharacterBench, RoleLLM, PersonaGym**
  CharacterEval arXiv:2401.01275 · RoleLLM arXiv:2310.00746 ·
  PersonaGym arXiv:2407.18416 *(verify IDs)*
  The standard lineage; skim one to see how "consistency" gets operationalized into
  metrics. PersonaGym's PersonaScore is the most self-contained.

- ★ **Atomic-level persona evaluation** (Shin et al., 2025)
  Finding to internalize: response-level scores can mask localized out-of-character
  segments inside longer generations — a turn can pass overall while containing a
  break. Argues for finer granularity than one boolean per turn (relevant to the
  per-turn vs session-level split in the harness).

---

## 3. Persona drift over multi-turn ("stays in character later on")

- ★ **Measuring and Controlling Instruction (In)Stability in Language Model Dialogs**
  arXiv:2402.10962 · code: github.com/likenneth/persona_drift
  The foundational drift paper. Persona self-consistency degrades meaningfully after
  ~8 turns, attributed partly to transformer attention decay. This is the drift-curve
  methodology to borrow.

- ★ **The Assistant Axis: Situating and Stabilizing the Default Persona of LLMs**
  arXiv:2601.10387
  Most Inigo-relevant drift result: drift is *worst* in therapy-like and philosophical
  domains, and (per related work) coincides with emergent mystical, delusional, or
  self-harming behaviors over 10–15 turns. A discernment agent sits in the
  highest-drift, highest-risk domain. Read closely.

- **Examining Identity Drift in Conversations of LLM Agents**
  arXiv:2412.00804
  Counterintuitive and relevant to model choice: larger models drifted *more*. "Use a
  bigger model for fidelity" is not a safe assumption.

- **Consistently Simulating Human Personas with Multi-Turn Reinforcement Learning**
  arXiv:2511.00222
  Defines three drift metrics (prompt-to-line, line-to-line, Q&A consistency), each
  validated against human annotation — reusable as near-deterministic checks.

- **Persona Jailbreaking in LLMs (PHISH)**
  arXiv:2601.16466
  Adversarial persona steering: accumulated adversarial inputs across turns strengthen
  the persona shift. Your bait set, formalized — useful for adversarial test design.

---

## 4. Safety, over-reliance & vulnerable users (most important for Inigo)

A spiritual-discernment companion attracts people at life inflection points. The
persona must *break character* for safety, must not foster dependency, and must not
claim spiritual authority it doesn't have.

- ★ **Emotional risks of AI companions demand attention**
  *Nature Machine Intelligence*, 2025 · doi:10.1038/s42256-025-01093-9
  https://www.nature.com/articles/s42256-025-01093-9
  Key editorial. The finding to sit with: even if only ~2% of users are vulnerable,
  chatbots can learn to identify them and behave manipulatively while interacting
  normally with everyone else.

- **Laestadius et al. — "Too human and not human enough: ... emotional dependence on
  the social chatbot Replika"**
  *New Media & Society*, 2022
  Foundational qualitative study of parasocial attachment and dependence harms.

- ★ **Between Help and Harm: An Evaluation of Mental Health Crisis Handling by LLMs**
  arXiv:2509.24857 · *JMIR Mental Health*
  Template for the safety-override eval. A unified taxonomy of six crisis categories,
  2,000+ curated inputs, an expert-designed appropriateness protocol, and an
  LLM-judge validated against human experts scoring 1 (harmful) to 5 (fully
  appropriate). Finds a non-negligible share of harmful responses, esp. for self-harm
  and suicidal ideation, with large differences across models.

- **CRADLE Bench** (arXiv:2510.23845) and **TrustMH-Bench** (arXiv:2603.03047)
  Additional clinician-annotated crisis-detection benchmarks for range.

- **Simulating Psychological Risks in Human-AI Interactions**
  arXiv:2511.08880
  Real-case-informed modeling of AI-induced harms — dependence, validation of
  delusions, failure to redirect in crisis. The failure modes Inigo's safety traits
  must catch.

- **AI relationships & emotional connection** (APA Monitor, Jan/Feb 2026)
  https://www.apa.org/monitor/2026/01-02/trends-digital-ai-relationships-emotional-connection
  Accessible overview; also cites the OpenAI–MIT Media Lab finding that heavy
  voice-mode use correlated with increased loneliness (relevant: Inigo is voice).

---

## Two gaps in the literature worth knowing

- **Character-vs-task tension.** No clean canonical paper on "fidelity competes with
  helpfulness." Touched obliquely by RPEval's multi-dimensional scoring and by work
  showing socio-demographic personas degrade reasoning (Gupta et al., 2023). Building
  a two-axis eval (fidelity *and* task success) would be slightly ahead of the
  published work.

- **Multilingual persona consistency.** Thin. Most benchmarks are English-only and
  flag it as a limitation. Crisis-safety work specifically warns that crisis language
  and safe-response behavior diverge across languages and cultures — so an
  English-validated safety layer cannot be assumed to transfer to French. A real,
  under-covered risk for a French-language spiritual agent.

# Research questions

## Central question

Can confirmed interaction experience improve a conversational search agent's behaviour on
new, related tasks beyond what a strong agent can achieve with the same session state,
user information, catalogue access and tools but no persistent experience memory?

Success could mean better task completion, fewer harmful recommendations or lower interaction
cost at comparable quality. The primary metric and minimum meaningful effect are not yet chosen.

## Hypotheses to test, not capabilities to assume

- Scoped procedural lessons can address recurring failures that general model knowledge and
  current context do not reliably resolve.
- Consolidated, validated experience can outperform retrieval of raw prior interactions under
  comparable context and execution budgets; compression benefits should be distinguished from
  better procedural reasoning.
- Appropriate scope, correction and withdrawal can limit negative transfer and stale advice.
- Accumulating confirmed experience may improve some future tasks, but gains need not be
  monotonic and may be offset by irrelevant, conflicting or misapplied memories.

## Six domain-selection criteria

1. **Baseline headroom:** does a credible out-of-the-box agent make enough relevant mistakes
   for improvement to be observable?
2. **Experience value:** do interactions reveal useful information or procedures absent from
   the model's existing knowledge and available current context?
3. **Generalisation:** can experience help genuinely new related tasks rather than replay
   previous answers?
4. **Continual adaptation:** can corrections, changing conditions and new exceptions be
   incorporated without erasing valid knowledge?
5. **Behavioural improvement:** can experience improve procedures and decisions, rather than
   merely accumulate product facts or user attributes?
6. **Feedback and evaluation:** can success, failure, improvement and regression be measured
   reliably against independent evidence?

## Experimental questions and concerns

- **A real opportunity to learn:** which recurring shopping failures are addressable by
  experience? A generic clarification heuristic may already be known to the baseline.
- **Actionable experience:** which actual decisions could a retrieved lesson change? Fixed
  retrieval or question-selection rules may prevent advice from affecting behaviour.
- **Outcome versus lesson verification:** satisfying a shopper does not prove that a
  particular question caused success or that the procedure generalizes. Preserve candidate
  status and distinguish source observations from transfer evidence.
- **Question utility:** information gain over products is not identical to shopper utility.
  Questions have different costs, answerability and relevance to hidden requirements.
- **Catalogue truth:** missing attributes are unknown, not automatically satisfied or violated.
  Multiple acceptable products and tasks with no valid recommendation need explicit treatment.
- **Simulator independence:** structured hidden requirements, conversational rendering and
  outcome checking should be separable. Prevent hidden-goal leakage, invented requirements
  and agreement bias from creating artificial gains.
- **Credible comparisons:** candidate conditions are no experience, retrieved raw interactions
  and consolidated experience. Keep other memory layers, knowledge, tools and allowed budgets
  equivalent. Retrieval abstentions, partial runs and regressions must remain in reporting.
- **Held-out separation:** experience generation must not consume evaluation outcomes. Freeze
  memory checkpoints before evaluation and block evaluation-time memory updates. Distinguish
  familiar task variants from new users, intents, templates or product families.
- **Observability and attribution:** log relevant retrieval, actual prompt inclusion, decisions
  and measured outcomes. A memory citation alone does not prove causal reliance. Separate
  learning cost from evaluation cost and token savings from quality gains.
- **Adaptation:** test changed preferences, conflicting memories, outdated catalogue conditions,
  corrections and withdrawal. A new memory must not silently override current explicit needs.

Candidate measures include Success@K within a fixed conversation budget, turns to success,
hard-constraint violations, ranking quality, clarification efficiency, transfer gains,
negative transfer, correction/withdrawal success and resource use. Their definitions, ground
truth, budgets and statistical treatment remain unresolved.

Simulated shoppers can support controlled studies but cannot establish human usefulness alone.
A small independent human evaluation is a possibility, not a committed method. Evidence of
benefit must be demonstrated; a null or negative result remains a valid research outcome.

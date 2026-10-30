# Project context

## Research objective

Build an agent that improves from usage experience, persists confirmed experiences and
reuses them effectively on new tasks. A working application and architecture walkthrough
must make the complete learning cycle observable, including the evidence for improvement
or regression.

Persistent storage alone is insufficient. The research claim concerns changes in future
behaviour attributable to useful experience, compared with an equivalent baseline without
that experience. Memory must retain sources and scopes and support correction, conflict
handling, supersession and withdrawal.

## Earlier AutoML experiments

The earlier, separate project used LLMs to propose and refine tabular ML pipelines. Trusted
Python constructed and evaluated pipelines, produced objective CV feedback, replayed source
comparisons and stored scoped lessons for later tasks.

An initial live pilot used 24 DeepSeek requests. Compositional pipeline design worked, but
there was no convincing performance benefit over the original planner. A later direct
memory study used 97 requests: ten learning sessions generated eight source-verified lessons,
followed by six paired memory ON/OFF cases. Observed test results were one win, one tie and
four losses; three pairs were flagged for incomplete trial budgets. The three complete
pairs produced no wins, one tie and two losses for memory.

The traces exposed inappropriate transfer of a source recipe and repeated invalid feature
expansion proposals. Confirming a source outcome did not establish applicability to another
dataset. These small development studies do not prove that AutoML memory is ineffective.
Strong existing LLM knowledge is a possible limitation, not an established explanation
for the observed failures.

The pivot is evidence-driven: seek recurring failures that prior experience can address,
while also testing whether the agent applies that experience reliably. Objective feedback
and a difficult task do not by themselves guarantee useful learning opportunities.

## ASTRA reference

[ASTRA: Adaptive State-Tracking Retrieval Agent](https://devpost.com/software/reimagining-the-digital-experience)
is the user's earlier conversational shopping project. It explored structured session state,
intent extraction, lexical/embedding retrieval, filtering, ranking, clarification and persistent
preference memory.

The supplied reference implementation describes per-user preference vectors and explicit
retrieval/question-selection policies. Its purpose was helping shoppers find suitable products.
It supplies background and lessons, not a prescribed implementation for this project.
Its reported capabilities and results must not be treated as verified features of the new app.

The original ASTRA checkout and ZIP remain read-only. The user subsequently authorised
data-only reuse of the frozen 50,000-product catalogue and its associated image-URL mapping.
These are local, ignored assets under `data/catalogue/`; 56 products have no image entry.
No sessions, user profiles, evaluation cases, code, model weights, configuration or historical
experiment outputs were copied. Image files have not been downloaded.

## New direction

The proposed application is conversational product search, with the research emphasis on
learning how to search, ask questions, recommend and recover more effectively.

Three conceptual memory roles are under consideration:

- **Session state:** current intent, explicit constraints, conversation history, actions and
  changes within a task.
- **User memory:** scoped facts, preferences, exclusions, corrections and appropriately
  qualified inferences about a particular shopper across sessions.
- **Agent experience:** reusable, conditional lessons about clarification, retrieval,
  ranking, abstention, recovery and appropriate memory use.

Catalogue knowledge is distinct: current product facts are not proof that the agent has
learned a better procedure. Personalization and procedural improvement must also be measured
separately rather than credited to the same memory intervention.

The current philosophy is that LLMs may interpret interactions and propose updates, while
application logic validates and executes allowed operations. Proposed operations include
addition, confirmation, refinement, supersession, retraction and no-op; their contracts are
not finalised. Deterministic checks cannot automatically prove a general lesson from one
successful interaction.

The desired demonstration links an outcome to a lesson, explains its applicability to a new
task, records the resulting behavioural change and measures its effect. Incorrect or outdated
experience must remain inspectable and correctable. The three memory roles, technologies,
decision-making workflow and development milestones remain open for discussion.

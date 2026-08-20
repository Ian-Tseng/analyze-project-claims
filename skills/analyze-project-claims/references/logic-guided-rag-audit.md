# Logic-Guided RAG Audit Contract

Read this reference when the project uses finite-state claim labels, logical
complements, transition authorization, leakage controls, or RAG experiment
artifacts.

## Formal operator

Define the finite domain before applying operators. For a finite state domain
$D$:

\[
\neg A = D \setminus A,
\qquad
A \land B = A \cap B,
\qquad
A \lor B = A \cup B.
\]

For a current singleton state $s$:

\[
\operatorname{NOT}(s)=D\setminus\{s\}.
\]

If

\[
D=\{\mathrm{SUPPORT},\mathrm{CONTRADICT},\mathrm{NOINFO}\},
\]

every current state has exactly two complement candidates. Describe this as an
**exact two-candidate complement over the three-state label domain**, not a
two-state complement.

Candidate generation does not imply transition execution. Record enumeration,
authorization, execution, and evaluation separately.

## Evidence flow

Require:

```text
dataset/source
-> partition and label exposure
-> initial label and score state
-> exact complement candidates
-> fitted or fixed authorization rule
-> predicted transition or abstention
-> evaluation metrics
-> claim boundary
```

Check:

- declared label domain and exact complement coverage;
- separate error and abstention states;
- unique record keys, cardinality, finite features, and probabilities;
- prohibited feature names and feature construction;
- train/test isolation and target-family exclusion from blocked training;
- candidate-pair preservation;
- the exact trainer-consumed split manifest;
- manifest hashes bound into predictions and lifecycle artifacts;
- separate scientific and acceptance flags.

Fold definitions or regenerated splits do not prove what a historical trainer
consumed. Exact-consumption claims require a persisted pre-fit manifest or
equivalent direct evidence.

## Gate separation

| Layer | What a pass establishes |
|---|---|
| Operator | Implementation matches the declared finite-state relation |
| Artifact | Stored records are internally well formed |
| Leakage | Declared feature and split boundaries are implemented |
| Lifecycle | Required artifacts and success markers are present |
| Scientific | Named performance gates pass in the evaluated scope |
| Acceptance | A bounded paper-table or deployment action is permitted |

Never infer scientific benefit from structural or lifecycle validity.

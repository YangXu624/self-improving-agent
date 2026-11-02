# ASTRA User Memory Architecture — Controlled Offline Ablation Report

Benchmark: `experiments/longitudinal/customers.memory-sensitive.json` (6 Customers, 12 Visits)

## Summary Results

| Condition | Metric | Memory-Helpful (4 visits) | Memory-Neutral (4 visits) | Memory-Conflicting (4 visits) | Overall (12 visits) |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **Memory OFF** | **Target Hit@10** | 2/4 (50.0%) | 3/4 (75.0%) | 2/4 (50.0%) | **7/12 (58.3%)** |
| | Candidate Recall@30 | 2/4 | 3/4 | 2/4 | 7/12 |
| | Hard Violations | 0 | 0 | 0 | 0 |
| **Memory ON (Broad Retrieval Only, No Rerank)** | **Target Hit@10** | 2/4 (50.0%) | 3/4 (75.0%) | 2/4 (50.0%) | **7/12 (58.3%)** |
| | Candidate Recall@30 | 2/4 | 3/4 | 2/4 | 7/12 |
| | Hard Violations | 0 | 0 | 0 | 0 |
| **Memory ON (Contextual Selection & Rerank)** | **Target Hit@10** | 3/4 (75.0%) | 3/4 (75.0%) | 2/4 (50.0%) | **8/12 (66.7%)** |
| | Candidate Recall@30 | 3/4 | 3/4 | 2/4 | 8/12 |
| | Hard Violations | 0 | 0 | 0 | 0 |
| **Oracle Memory** | **Target Hit@10** | 4/4 (100.0%) | 3/4 (75.0%) | 2/4 (50.0%) | **9/12 (75.0%)** |
| | Candidate Recall@30 | 4/4 | 3/4 | 2/4 | 9/12 |
| | Hard Violations | 0 | 0 | 0 | 0 |

## Per-Visit Diagnostic Detail (Target Ranks & Reranking)

| Visit ID | Group | Target in Pool? | Candidate Rank (Pool K=30) | Final Rec Rank (Top 10) | Target Bonus | Hit@10? |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| `mem-help-active-01` | memory-helpful | No | > 30 | Not in Top 10 | 0.00 | ❌ Miss |
| `mem-help-active-02` | memory-helpful | Yes | Rank 9 | Rank 9 | 0.00 | ✅ Hit |
| `mem-help-commute-01` | memory-helpful | Yes | Rank 6 | Rank 6 | 0.00 | ✅ Hit |
| `mem-help-commute-02` | memory-helpful | Yes | Rank 1 | Rank 1 | 0.00 | ✅ Hit |
| `mem-neut-travel-01` | memory-neutral | Yes | Rank 6 | Rank 6 | 0.00 | ✅ Hit |
| `mem-neut-travel-02` | memory-neutral | Yes | Rank 5 | Rank 1 | 0.00 | ✅ Hit |
| `mem-neut-pack-01` | memory-neutral | No | > 30 | Not in Top 10 | 0.00 | ❌ Miss |
| `mem-neut-pack-02` | memory-neutral | Yes | Rank 9 | Rank 1 | 0.00 | ✅ Hit |
| `mem-conf-override-01` | memory-conflicting | No | > 30 | Not in Top 10 | 0.00 | ❌ Miss |
| `mem-conf-override-02` | memory-conflicting | Yes | Rank 1 | Rank 1 | 0.00 | ✅ Hit |
| `mem-conf-gift-01` | memory-conflicting | No | > 30 | Not in Top 10 | 0.00 | ❌ Miss |
| `mem-conf-gift-02` | memory-conflicting | Yes | Rank 1 | Rank 1 | 0.00 | ✅ Hit |

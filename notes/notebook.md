# Lab notebook

## AI assistant use (disclosure)
| Date | What I used the assistant for | What I kept / changed |
|------|-------------------------------|-----------------------|
| (earlier) | Debugging the pipeline (ALU control stage, branch/jump support, Icarus 11 freeze), writing test_pipeline.py | Core fixes applied by me; regression script kept as is |

## Entries

### Day 0: baseline
- Core: 5-stage RV32I with forwarding, load-use stall, branch/jump resolution in EX.
- Regression: 80 tests (directed + 50 random) pass on Icarus 12.
- Dead end: Icarus 11.0 froze on branch tests; fixed by using Icarus 12.
- Next: step 1, add rdcycle and the retirement trace.

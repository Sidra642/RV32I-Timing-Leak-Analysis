# Lab notebook

## AI assistant use (disclosure)
| Date | What I used the assistant for | What I kept / changed |
|------|-------------------------------|-----------------------|
| (earlier) | Debugging the pipeline (ALU control stage, branch/jump support, Icarus 11 freeze), writing test_pipeline.py | Core fixes applied by me; regression script kept as is |
| 2026-11-26 | Design of trace_pipe and tb_trace, rdcycle wiring steps | Checked the stall gap and valid logic by hand against the program; wrote this entry myself |

## Entries

### Day 0: baseline
- Core: 5-stage RV32I with forwarding, load-use stall, branch/jump resolution in EX.
- Regression: 80 tests (directed + 50 random) pass on Icarus 12.
- Dead end: Icarus 11.0 froze on branch tests; fixed by using Icarus 12.
- Next: step 1, add rdcycle and the retirement trace.

### Day 1: rdcycle
- inst_mem now loads program.hex ($readmemh), so programs change without editing RTL.
- Added is_csr (control unit, ID/EX) and a free-running cycle_cnt, muxed into the EX result.
- Check: rdcycle, 10 nops, rdcycle, sub gives 11 (no stalls). Regression still 80/80.
- Next: retirement trace (valid bit, PC, address, operands carried to WB).


### 2026-11-26, Day 1 (continued): retirement trace

**What I added.** A `trace_pipe` module (`RTL/trace_pipe.sv`) that follows every instruction from ID to WB, and a testbench `tb/tb_trace.sv` that prints one line when an instruction retires. I put it in a separate module so I did not have to change any existing pipeline register. The regression still passes 80/80, since nothing architectural changed.

**Trace format.** `RET <cycle> <pc> <addr|-> <opA> <opB>`
- `cycle` is the free-running `cycle_cnt` at retirement.
- `pc` is the instruction address.
- `addr` is the data address for loads and stores, and `-` for everything else.
- `opA` and `opB` are the forwarded ALU operands (after the forwarding muxes).

The format is fixed on purpose. Part C parses it, and the finder will be run on a core I have not seen, so the finder must depend only on this trace and not on my RTL.

**Check 1: load-use stall.** Program: `addi x1,x0,5; sw x1,64(x0); lw x2,64(x0); add x3,x2,x2; rdcycle x4; halt loop`.
- The `sw` and `lw` both show address `00000040`, as expected.
- The `lw` retired at cycle 6 and the dependent `add` at cycle 8, so there is exactly one extra cycle between them. That is the one-cycle load-use stall from the hazard unit.
- The `add` shows operands 5 and 5, so the loaded value was forwarded correctly.
- The PCs retire in order: 0, 4, 8, c, 10, 14.

**Why bubbles do not print.** A flushed or stalled slot has the same register values as a real `nop` (`addi x0,x0,0`), so the trace cannot tell them apart from the data alone. `trace_pipe` carries a separate `valid` bit through the stages:
- it is cleared in IF/ID when `redirect_EX` flushes,
- it is held while `IF_ID_Write = 0` (load-use stall), so the stalled instruction is not lost,
- a bubble enters EX (`valid = 0`) when `stall | redirect_EX` is 1,
- only `valid_WB = 1` prints a line.

The trace showed one line per real instruction and no extra lines around the stall and the jumps.

**Halt loop.** After the program, `jal x0, halt` retires every 3 cycles (cycles 13, 16, 19, ...). The jump resolves in EX and redirects the PC, so the two younger instructions behind it are flushed each time. That gives one useful retirement per 3 cycles, which is my taken-jump penalty. For Part C the finder must stop at a fixed cycle count or at the first repeated halt PC, so the repeats are not compared as if they were timing differences.

**Unused operands.** The first line `RET 4 00000000 - 00000000 0000003c` has `opB = 0000003c` for `addi x1,x0,5`. That value is the reset value of `x5` (60 = 0x3c): the immediate bits of the instruction happen to select `x5` as `rs2`. The hardware reads it, but the instruction does not use it. So the operand columns are only meaningful for instructions that use them. For the second contract (reveal operands of variable-time instructions) the finder must pick operands by opcode and not include the raw columns for every instruction. Otherwise unused register values would make runs look different when they are not.

# Leak, Find, Fix: 5-stage RV32I core

Research task: timing leaks in my own RV32I core (Parts A to D).

## Layout
- RTL/    core (Icarus Verilog 12 required)
- tb/     testbenches
- tests/  regression (test_pipeline.py)
- tools/  leak finder (Part C) and repair tool (Part D)
- notes/  notebook.md, design note
- results/ generated tables and plots

## Commands
- make regress   functional regression (80 tests)

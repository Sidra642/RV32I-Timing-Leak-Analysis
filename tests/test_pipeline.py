#!/usr/bin/env python3
"""
Self-checking regression for the 5-stage RV32I pipeline.

For every test program the script
  1. assembles it (mini assembler, labels supported),
  2. runs it on a Python RV32I reference model (golden result),
  3. runs it on your RTL with Icarus Verilog,
  4. compares all 32 registers and all 32 data-memory words.

Run it from the folder that holds your .sv files:
    python3 test_pipeline.py                 # directed tests + 50 random programs
    python3 test_pipeline.py --seeds 300     # more random programs
    python3 test_pipeline.py --only fwd      # only tests whose name contains "fwd"
    python3 test_pipeline.py --iss-only      # check the Python model only (no simulator)

Assumptions (edit the constants below if your design differs):
  * top module is `top_pipelined`, with instances Reg_File_ID (array `Registers`)
    and Data_Mem_inst (array `D_Memory`)
  * register-file reset values and data-memory preload are the ones in REG_INIT / MEM_INIT
  * instruction memory has 128 words, PC starts at 0
  * the script replaces your Instruction_Memory with one that loads program.hex
    (your files are copied to a temp folder, never modified)
"""
import argparse
import glob
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile

M32 = 0xFFFFFFFF

# values your Register_File loads on reset (x0..x31)
REG_INIT = [0, 12, 24, 36, 48, 60, 72, 84, 96, 15, 27, 39, 51, 63, 75, 87,
            99, 13, 26, 38, 50, 62, 74, 86, 23, 35, 47, 59, 71, 83, 95, 7]
# values your Data_Memory preloads (32 words)
MEM_INIT = [0, 4, 2, 0x18, 4, 1, 0x2C, 4, 2, 1, 0x17, 4, 9, 1, 2, 3,
            4, 5, 6, 3, 4, 5, 6, 3, 4, 5, 6, 3, 4, 5, 6, 3]
MEM_WORDS = 32
IMEM_WORDS = 128

# --------------------------------------------------------------------------
# Assembler
# --------------------------------------------------------------------------
R_OPS = {'add': (0, 0), 'sub': (0x20, 0), 'sll': (0, 1), 'slt': (0, 2),
         'sltu': (0, 3), 'xor': (0, 4), 'srl': (0, 5), 'sra': (0x20, 5),
         'or': (0, 6), 'and': (0, 7)}
I_OPS = {'addi': 0, 'slti': 2, 'sltiu': 3, 'xori': 4, 'ori': 6, 'andi': 7}
SH_OPS = {'slli': (0, 1), 'srli': (0, 5), 'srai': (0x20, 5)}
LD_OPS = {'lb': 0, 'lh': 1, 'lw': 2, 'lbu': 4, 'lhu': 5}
ST_OPS = {'sb': 0, 'sh': 1, 'sw': 2}
BR_OPS = {'beq': 0, 'bne': 1, 'blt': 4, 'bge': 5, 'bltu': 6, 'bgeu': 7}


def reg(t):
    m = re.fullmatch(r'x(\d+)', t)
    if not m or int(m.group(1)) > 31:
        raise ValueError(f'bad register {t}')
    return int(m.group(1))


def fit(v, bits, what):
    lo, hi = -(1 << (bits - 1)), (1 << (bits - 1)) - 1
    if not lo <= v <= hi:
        raise ValueError(f'{what} {v} does not fit in {bits} bits')
    return v & ((1 << bits) - 1)


def memop(t):
    m = re.fullmatch(r'(-?\w+)\((x\d+)\)', t)
    if not m:
        raise ValueError(f'bad memory operand {t}')
    return int(m.group(1), 0), reg(m.group(2))


def encode(mn, ops, pc, labels):
    def target(t):
        return labels[t] * 4 - pc if t in labels else int(t, 0)

    if mn == 'nop':
        return 0x13
    if mn in R_OPS:
        f7, f3 = R_OPS[mn]
        rd, rs1, rs2 = map(reg, ops)
        return (f7 << 25) | (rs2 << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | 0x33
    if mn in I_OPS:
        imm = fit(int(ops[2], 0), 12, 'imm')
        return (imm << 20) | (reg(ops[1]) << 15) | (I_OPS[mn] << 12) | (reg(ops[0]) << 7) | 0x13
    if mn in SH_OPS:
        f7, f3 = SH_OPS[mn]
        sh = int(ops[2], 0)
        if not 0 <= sh < 32:
            raise ValueError('shamt out of range')
        return (f7 << 25) | (sh << 20) | (reg(ops[1]) << 15) | (f3 << 12) | (reg(ops[0]) << 7) | 0x13
    if mn in LD_OPS:
        off, rs1 = memop(ops[1])
        return (fit(off, 12, 'offset') << 20) | (rs1 << 15) | (LD_OPS[mn] << 12) | (reg(ops[0]) << 7) | 0x03
    if mn in ST_OPS:
        off, rs1 = memop(ops[1])
        imm = fit(off, 12, 'offset')
        return ((imm >> 5) << 25) | (reg(ops[0]) << 20) | (rs1 << 15) | (ST_OPS[mn] << 12) | ((imm & 31) << 7) | 0x23
    if mn in BR_OPS:
        imm = fit(target(ops[2]), 13, 'branch offset')
        return (((imm >> 12) & 1) << 31) | (((imm >> 5) & 0x3F) << 25) | (reg(ops[1]) << 20) | \
               (reg(ops[0]) << 15) | (BR_OPS[mn] << 12) | (((imm >> 1) & 0xF) << 8) | \
               (((imm >> 11) & 1) << 7) | 0x63
    if mn == 'jal':
        imm = fit(target(ops[1]), 21, 'jal offset')
        return (((imm >> 20) & 1) << 31) | (((imm >> 1) & 0x3FF) << 21) | (((imm >> 11) & 1) << 20) | \
               (((imm >> 12) & 0xFF) << 12) | (reg(ops[0]) << 7) | 0x6F
    if mn == 'jalr':
        off, rs1 = memop(ops[1])
        return (fit(off, 12, 'offset') << 20) | (rs1 << 15) | (reg(ops[0]) << 7) | 0x67
    if mn in ('lui', 'auipc'):
        return ((int(ops[1], 0) & 0xFFFFF) << 12) | (reg(ops[0]) << 7) | (0x37 if mn == 'lui' else 0x17)
    if mn == 'rdcycle':
    	return (0xC00 << 20) | (2 << 12) | (reg(ops[0]) << 7) | 0x73
        
    raise ValueError(f'unknown instruction {mn}')


def assemble(text):
    labels, lines = {}, []
    for raw in text.splitlines():
        line = raw.split('#')[0].strip()
        while ':' in line:
            lab, line = line.split(':', 1)
            labels[lab.strip()] = len(lines)
            line = line.strip()
        if line:
            lines.append(line)
    words = []
    for idx, line in enumerate(lines):
        parts = line.split(None, 1)
        ops = [o for o in re.split(r'[,\s]+', parts[1].strip()) if o] if len(parts) > 1 else []
        try:
            words.append(encode(parts[0].lower(), ops, idx * 4, labels))
        except Exception as e:
            raise ValueError(f'{line!r}: {e}')
    if len(words) > IMEM_WORDS - 4:
        raise ValueError('program too long for instruction memory')
    return words


# --------------------------------------------------------------------------
# Reference model (decodes the machine code, like the hardware does)
# --------------------------------------------------------------------------
def s32(v):
    v &= M32
    return v - (1 << 32) if v >> 31 else v


def sx(v, bits):
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >> (bits - 1) else v


def iss(words, max_steps=6000):
    regs = REG_INIT[:]
    mem = bytearray(MEM_WORDS * 4)
    for i, w in enumerate(MEM_INIT):
        mem[i * 4:i * 4 + 4] = w.to_bytes(4, 'little')
    pc, steps = 0, 0

    def addr_ok(a, n):
        if a + n > len(mem):
            raise RuntimeError(f'test bug: memory access out of range @{a}')

    while steps < max_steps:
        idx = pc >> 2
        w = words[idx] if 0 <= idx < len(words) else 0x13
        op, rd, f3 = w & 0x7F, (w >> 7) & 31, (w >> 12) & 7
        rs1, rs2, f7 = (w >> 15) & 31, (w >> 20) & 31, w >> 25
        a, b = regs[rs1], regs[rs2]
        npc, wr = pc + 4, None
        if op == 0x33:
            sh = b & 31
            wr = {0: (a - b if f7 else a + b), 1: a << sh, 2: int(s32(a) < s32(b)),
                  3: int(a < b), 4: a ^ b, 5: (s32(a) >> sh) if f7 else a >> sh,
                  6: a | b, 7: a & b}[f3]
        elif op == 0x13:
            imm = sx(w >> 20, 12)
            sh = rs2
            wr = {0: a + imm, 1: a << sh, 2: int(s32(a) < imm), 3: int(a < (imm & M32)),
                  4: a ^ (imm & M32), 5: (s32(a) >> sh) if (w >> 30) & 1 else a >> sh,
                  6: a | (imm & M32), 7: a & (imm & M32)}[f3]
        elif op == 0x03:
            ad = (a + sx(w >> 20, 12)) & M32
            n = {0: 1, 4: 1, 1: 2, 5: 2, 2: 4}[f3]
            addr_ok(ad, n)
            v = int.from_bytes(mem[ad:ad + n], 'little')
            wr = sx(v, 8 * n) if f3 in (0, 1, 2) else v
        elif op == 0x23:
            imm = sx(((w >> 25) << 5) | ((w >> 7) & 31), 12)
            ad = (a + imm) & M32
            n = {0: 1, 1: 2, 2: 4}[f3]
            addr_ok(ad, n)
            mem[ad:ad + n] = (b & ((1 << (8 * n)) - 1)).to_bytes(n, 'little')
        elif op == 0x63:
            imm = sx((((w >> 31) & 1) << 12) | (((w >> 7) & 1) << 11) |
                     (((w >> 25) & 0x3F) << 5) | (((w >> 8) & 0xF) << 1), 13)
            taken = {0: a == b, 1: a != b, 4: s32(a) < s32(b), 5: s32(a) >= s32(b),
                     6: a < b, 7: a >= b}[f3]
            if taken:
                npc = pc + imm
        elif op == 0x6F:
            imm = sx((((w >> 31) & 1) << 20) | (((w >> 12) & 0xFF) << 12) |
                     (((w >> 20) & 1) << 11) | (((w >> 21) & 0x3FF) << 1), 21)
            wr, npc = pc + 4, pc + imm
        elif op == 0x67:
            wr, npc = pc + 4, (a + sx(w >> 20, 12)) & ~1
        elif op == 0x37:
            wr = w & 0xFFFFF000
        elif op == 0x17:
            wr = pc + (w & 0xFFFFF000)
        # anything else (e.g. the all-zero word) behaves as a nop
        if wr is not None and rd:
            regs[rd] = wr & M32
        steps += 1
        npc &= M32
        if npc == pc:          # jal x0, self  -> halt
            break
        pc = npc
    else:
        raise RuntimeError('reference model did not halt (test bug)')
    mem_words = [int.from_bytes(mem[i * 4:i * 4 + 4], 'little') for i in range(MEM_WORDS)]
    return regs, mem_words, steps


# --------------------------------------------------------------------------
# Test programs
# --------------------------------------------------------------------------
HALT = '\nhalt: jal x0, halt\n'


def pad(text, k):
    """put k nops after every instruction (removes all hazards)"""
    out = []
    for raw in text.strip().splitlines():
        out.append(raw)
        s = raw.split('#')[0].strip()
        if ':' in s:
            s = s.split(':', 1)[1].strip()
        if s:
            out += ['nop'] * k
    return '\n'.join(out)


ALU_ALL = """
addi x1, x0, 100
addi x2, x0, -7
addi x3, x0, 0x555
add  x4, x1, x2
sub  x5, x1, x2
sll  x6, x3, x2
slt  x7, x2, x1
sltu x8, x2, x1
xor  x9, x1, x3
srl  x10, x3, x1
sra  x11, x2, x1
or   x12, x1, x3
and  x13, x1, x3
addi x14, x2, -2048
slti x15, x2, -1
sltiu x16, x2, -1
xori x17, x3, -1
ori  x18, x1, 0x7f0
andi x19, x3, 0xff
slli x20, x3, 3
srli x21, x2, 4
srai x22, x2, 4
srai x23, x3, 4
sub  x24, x0, x1
"""

FWD_CHAIN = """
addi x1, x0, 1
add  x1, x1, x1          # EX/MEM forward on both operands
add  x1, x1, x1          # newer result must win over older (MEM beats WB)
add  x1, x1, x1
add  x1, x1, x1
add  x2, x1, x1
add  x3, x2, x1
sub  x4, x3, x2
xor  x5, x4, x3
or   x6, x5, x1
"""

FWD_DIST = """
addi x1, x0, 11
addi x2, x0, 22          # producer
nop
add  x3, x2, x1          # distance 2  -> MEM/WB forward
addi x4, x0, 33
nop
nop
add  x5, x4, x1          # distance 3  -> register-file write-through
addi x6, x0, 44
nop
nop
nop
add  x7, x6, x1          # distance 4  -> plain register read
addi x8, x0, 5
add  x9, x1, x8          # forward on operand B only
add  x10, x8, x1         # forward on operand A only
"""

FWD_X0 = """
addi x0, x1, 5           # write to x0 must be ignored and never forwarded
add  x2, x0, x0
addi x3, x0, 9
add  x4, x0, x3
sub  x5, x3, x0
lw   x0, 4(x0)           # load into x0
add  x6, x0, x3
"""

LOAD_USE = """
lw   x1, 4(x0)           # mem[1] = 4
add  x2, x1, x1          # load-use stall
add  x3, x1, x2
lw   x4, 12(x0)          # mem[3] = 0x18
nop
add  x5, x4, x4          # load result via MEM/WB forward
lw   x6, 16(x0)
nop
nop
add  x7, x6, x6
lw   x8, 24(x0)
sw   x8, 100(x0)         # load then store of the loaded value
lw   x9, 100(x0)
addi x10, x9, 1
lw   x11, 8(x0)
sub  x12, x11, x11
"""

STORE_FWD = """
addi x5, x0, 16
sw   x5, 0(x5)           # address and data both forwarded
lw   x6, 0(x5)
addi x7, x0, 60
addi x8, x0, 0x234
sw   x8, 0(x7)
sw   x7, 4(x7)
lw   x9, 0(x7)
lw   x10, 4(x7)
add  x11, x9, x10
"""

MEM_OPS = """
addi x5, x0, 64
addi x6, x0, -1
sw   x6, 0(x5)
sb   x0, 1(x5)
addi x7, x0, 0x7f
sh   x7, 2(x5)
lw   x8, 0(x5)
lb   x9, 0(x5)
lbu  x10, 0(x5)
lh   x11, 2(x5)
lhu  x12, 0(x5)
lb   x13, 1(x5)
lb   x14, 3(x5)
lbu  x15, 3(x5)
lh   x16, 0(x5)
addi x17, x0, 0x80
sb   x17, 8(x5)
lb   x18, 8(x5)
lbu  x19, 8(x5)
addi x20, x0, -2
sh   x20, 12(x5)
lh   x21, 12(x5)
lhu  x22, 12(x5)
"""

LOOP_BACK = """
addi x1, x0, 0
addi x2, x0, 10
loop: addi x1, x1, 1
add  x3, x3, x1
bne  x1, x2, loop        # backward branch, taken 9 times
addi x4, x0, 99
loop2: addi x5, x5, 2
addi x6, x6, -1
blt  x6, x0, loop2       # branch on a value produced 1 instruction earlier
addi x7, x0, 7
"""

BRANCH_LOAD = """
addi x7, x0, 2
addi x5, x0, 8
lw   x6, 0(x5)           # mem[2] = 2
beq  x6, x7, ok          # load-use into a branch
addi x8, x8, 1           # must be skipped
addi x9, x9, 1           # must be skipped
ok:  addi x10, x10, 1
lw   x11, 4(x0)
bne  x11, x0, ok2        # load directly before the branch
addi x12, x12, 1         # must be skipped
ok2: addi x13, x13, 1
"""

JUMPS = """
jal  x1, func            # x1 = 4
addi x20, x20, 1         # executed once, after the return
jal  x0, end
func: addi x10, x0, 55
jalr x0, 0(x1)           # return
end: addi x21, x21, 1
auipc x5, 0
addi x5, x5, 16          # x5 = address of "tgt"
jalr x6, 0(x5)           # jump with a just-forwarded base, x6 = link
addi x11, x11, 1         # must be skipped
tgt: addi x12, x12, 1
addi x7, x0, 52
jalr x8, 4(x7)           # target = 56, skips next instr
addi x13, x13, 1         # must be skipped
addi x14, x14, 1
jal  x9, skip2
addi x15, x15, 1         # must be skipped
addi x16, x16, 1         # must be skipped
skip2: addi x17, x17, 1
"""

UPPER = """
lui   x1, 0x12345
addi  x1, x1, 0x678
auipc x2, 1
lui   x3, 0xFFFFF
auipc x4, 0xFFFFF
lui   x5, 0
add   x6, x1, x3
auipc x7, 0
"""


def branch_test(op, gap):
    """one branch type, taken and not taken, signed/unsigned corner cases"""
    pairs = [(5, 5), (3, 7), (7, 3), (-1, 1), (1, -1), (0, 0), (-5, -5), (-3, -7)]
    out = []
    for n, (a, b) in enumerate(pairs):
        out += [f'addi x1, x0, {a}', f'addi x2, x0, {b}'] + ['nop'] * gap
        out += [f'{op} x1, x2, T{n}', 'addi x10, x10, 1', 'addi x11, x11, 1',
                f'T{n}: addi x12, x12, 1']
    return '\n'.join(out)


def gen_random(seed, n=60):
    rnd = random.Random(seed)
    pool = [1, 2, 3, 4, 5, 6, 7, 8]          # small pool -> many hazards
    R = lambda: f'x{rnd.choice(pool)}'
    S = lambda: f'x{rnd.choice(pool + [0])}'
    body, labels = [], {}
    kinds = ['r', 'i', 'sh', 'ld', 'st', 'br', 'jal', 'upper']
    weights = [30, 25, 8, 12, 10, 8, 2, 3]
    for i in range(n):
        k = rnd.choices(kinds, weights)[0]
        if k == 'r':
            body.append(f'{rnd.choice(list(R_OPS))} {R()}, {S()}, {S()}')
        elif k == 'i':
            body.append(f'{rnd.choice(list(I_OPS))} {R()}, {S()}, {rnd.randint(-2048, 2047)}')
        elif k == 'sh':
            body.append(f'{rnd.choice(list(SH_OPS))} {R()}, {S()}, {rnd.randint(0, 31)}')
        elif k == 'ld':
            op = rnd.choice(list(LD_OPS))
            step = {'lw': 4, 'lh': 2, 'lhu': 2}.get(op, 1)
            body.append(f'{op} {R()}, {rnd.randrange(-32, 96, step)}(x30)')
        elif k == 'st':
            op = rnd.choice(list(ST_OPS))
            step = {'sw': 4, 'sh': 2}.get(op, 1)
            body.append(f'{op} {S()}, {rnd.randrange(-32, 96, step)}(x30)')
        elif k == 'br':
            t = min(i + 1 + rnd.randint(1, 4), n)
            labels.setdefault(t, f'L{t}')
            body.append(f'{rnd.choice(list(BR_OPS))} {S()}, {S()}, {labels[t]}')
        elif k == 'jal':
            t = min(i + 1 + rnd.randint(1, 4), n)
            labels.setdefault(t, f'L{t}')
            body.append(f'jal {R()}, {labels[t]}')
        else:
            body.append(f'{rnd.choice(["lui", "auipc"])} {R()}, {rnd.randint(0, 0xFFFFF)}')
    lines = ['addi x30, x0, 32']                # x30 = data base, never overwritten
    for i, ins in enumerate(body):
        if i in labels:
            lines.append(labels[i] + ':')
        lines.append(ins)
    if n in labels:
        lines.append(labels[n] + ':')
    return '\n'.join(lines)


def directed_tests():
    br = [(f'branch_{op}_gap{g}', branch_test(op, g)) for op in BR_OPS for g in (0, 1, 3)]
    return br + [
        ('alu_spaced (no hazards)', pad(ALU_ALL, 3)),
        ('alu_dense (forwarding)', ALU_ALL),
        ('fwd_chain', FWD_CHAIN),
        ('fwd_distance 1..4', FWD_DIST),
        ('fwd_x0', FWD_X0),
        ('load_use_stall', LOAD_USE),
        ('store_forwarding', STORE_FWD),
        ('mem_byte_half_word', MEM_OPS),
        ('branch_backward_loops', LOOP_BACK),
        ('branch_after_load', BRANCH_LOAD),
        ('jal_jalr_link_flush', JUMPS),
        ('lui_auipc', UPPER),
    ]


# --------------------------------------------------------------------------
# RTL runner
# --------------------------------------------------------------------------
IMEM_SV = """`timescale 1ns / 1ps
module Instruction_Memory (
    input  logic [31:0] read_address,
    output logic [31:0] instruction_out
);
    logic [31:0] I_Memory [0:127];
    initial begin
        for (int k = 0; k < 128; k++) I_Memory[k] = 32'h00000013;
        $readmemh("program.hex", I_Memory);
    end
    assign instruction_out = I_Memory[read_address[31:2]];
endmodule
"""

TB_SV = """`timescale 1ns / 1ps
module tb_check;
    reg clk = 0, reset = 1;
    integer cycles;
    top_pipelined uut (.clk(clk), .reset(reset));
    always #5 clk = ~clk;
    initial begin
        if (!$value$plusargs("CYCLES=%d", cycles)) cycles = 400;
        repeat (2) @(posedge clk);
        @(negedge clk);
        reset = 0;
        repeat (cycles) @(posedge clk);
        #1;
        for (int i = 0; i < 32; i++) $display("R %0d %h", i, uut.Reg_File_ID.Registers[i]);
        for (int i = 0; i < 32; i++) $display("M %0d %h", i, uut.Data_Mem_inst.D_Memory[i]);
        $finish;
    end
endmodule
"""


def build(src_dir, work):
    files = []
    for f in sorted(glob.glob(os.path.join(src_dir, '*.sv')) + glob.glob(os.path.join(src_dir, '*.v'))):
        txt = open(f, errors='ignore').read()
        if re.search(r'^\s*module\s+Instruction_Memory\b', txt, re.M):
            continue
        if re.search(r'^\s*module\s+tb\w*', txt, re.M):
            continue
        shutil.copy(f, work)
        files.append(os.path.basename(f))
    open(os.path.join(work, 'imem_test.sv'), 'w').write(IMEM_SV)
    open(os.path.join(work, 'tb_check.sv'), 'w').write(TB_SV)
    files += ['imem_test.sv', 'tb_check.sv']
    r = subprocess.run(['iverilog', '-g2012', '-s', 'tb_check', '-o', 'sim.out'] + files,
                       cwd=work, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        sys.exit('iverilog compile failed')


def run_rtl(work, words, steps, timeout):
    with open(os.path.join(work, 'program.hex'), 'w') as f:
        f.write('\n'.join(f'{w:08x}' for w in words) + '\n')
    cycles = steps * 16 + 100
    try:
        r = subprocess.run(['vvp', 'sim.out', f'+CYCLES={cycles}'], cwd=work,
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, None, 'TIMEOUT (zero-delay loop? try Icarus >= 12)'
    regs, mem = {}, {}
    for line in r.stdout.splitlines():
        p = line.split()
        if len(p) == 3 and p[0] in 'RM':
            try:
                v = int(p[2], 16)
            except ValueError:
                v = None                     # contains x / z
            (regs if p[0] == 'R' else mem)[int(p[1])] = v
    if len(regs) != 32 or len(mem) != MEM_WORDS:
        return None, None, 'no register/memory dump in simulator output'
    return regs, mem, None


def compare(exp_regs, exp_mem, regs, mem):
    bad = []
    for i in range(32):
        if regs[i] != exp_regs[i]:
            got = 'x/z' if regs[i] is None else f'0x{regs[i]:08x}'
            bad.append(f'x{i}: expected 0x{exp_regs[i]:08x}, got {got}')
    for i in range(MEM_WORDS):
        if mem[i] != exp_mem[i]:
            got = 'x/z' if mem[i] is None else f'0x{mem[i]:08x}'
            bad.append(f'mem[{i}] (byte {i * 4}): expected 0x{exp_mem[i]:08x}, got {got}')
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--src', default='.', help='folder with the RTL .sv files')
    ap.add_argument('--seeds', type=int, default=50, help='number of random programs')
    ap.add_argument('--only', default='', help='run tests whose name contains this text')
    ap.add_argument('--iss-only', action='store_true', help='only check the Python model')
    ap.add_argument('--timeout', type=int, default=30, help='seconds per simulation')
    ap.add_argument('--keep', action='store_true', help='keep the temp build folder')
    args = ap.parse_args()

    tests = directed_tests() + [(f'random_seed_{s}', gen_random(s)) for s in range(args.seeds)]
    tests = [(n, t + HALT) for n, t in tests if args.only in n]

    work = None
    if not args.iss_only:
        work = tempfile.mkdtemp(prefix='pipe_test_')
        build(args.src, work)

    passed = failed = 0
    for name, text in tests:
        words = assemble(text)
        exp_regs, exp_mem, steps = iss(words)
        if args.iss_only:
            print(f'[ISS ] {name:40s} {len(words):3d} instrs, {steps:4d} executed')
            passed += 1
            continue
        regs, mem, err = run_rtl(work, words, steps, args.timeout)
        bad = [err] if err else compare(exp_regs, exp_mem, regs, mem)
        if bad:
            failed += 1
            print(f'[FAIL] {name:40s} ({steps} instructions)')
            for b in bad[:8]:
                print('         ' + b)
            if len(bad) > 8:
                print(f'         ... {len(bad) - 8} more')
            if name.startswith('random'):
                path = os.path.join(work, name + '.S')
                open(path, 'w').write(text)
                print(f'         program saved to {path}')
        else:
            passed += 1
            print(f'[PASS] {name:40s} ({steps} instructions)')

    print(f'\n{passed} passed, {failed} failed')
    if work and not args.keep and not failed:
        shutil.rmtree(work, ignore_errors=True)
    elif work:
        print(f'build folder kept: {work}')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()

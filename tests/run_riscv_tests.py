#!/usr/bin/env python3
"""
Run the rv32ui tests from riscv-tests on the pipeline (Icarus Verilog).

    git clone https://github.com/riscv-software-src/riscv-tests ~/riscv-tests
    python3 tests/run_riscv_tests.py --tests ~/riscv-tests --src RTL
    python3 tests/run_riscv_tests.py --tests ~/riscv-tests --src RTL --only add

How it works
  * A minimal riscv_test.h replaces the standard env: no CSRs, no traps.
    PASS stores 1 to `tohost`, FAIL stores (testnum<<1)|1.
  * Linker script: .text at 0x0 (instruction memory), .tohost + .data at 0x1000
    (data memory word 1024).
  * The script loads .text into program.hex and .data into data.hex.
    Data_Memory must contain:
        if ($test$plusargs("LOADDATA")) $readmemh("data.hex", D_Memory, 1024);
  * The testbench watches D_Memory[1024] (tohost).

Needs: riscv64-unknown-elf-gcc / objcopy, iverilog (>= 12), the riscv-tests repo.
"""
import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

GCC = 'riscv64-unknown-elf-gcc'
OBJCOPY = 'riscv64-unknown-elf-objcopy'
IMEM_WORDS = 2048
TOHOST_WORD = 1024          # byte address 0x1000

EXPECTED_FAIL = {
    'ma_data': 'misaligned accesses: Data_Memory ignores them, no trap support',
    'fence_i': 'self-modifying code: instruction memory is separate from data memory',
}

RISCV_TEST_H = r'''#ifndef _ENV_MINI_H
#define _ENV_MINI_H
#define RVTEST_RV32U
#define RVTEST_RV64U
#define TESTNUM gp
#define RVTEST_CODE_BEGIN \
    .section .text.init; \
    .align 2; \
    .globl _start; \
_start:
#define RVTEST_CODE_END
#define RVTEST_PASS \
    li TESTNUM, 1; \
    la t5, tohost; \
    sw TESTNUM, 0(t5); \
1:  j 1b;
#define RVTEST_FAIL \
    sll TESTNUM, TESTNUM, 1; \
    or TESTNUM, TESTNUM, 1; \
    la t5, tohost; \
    sw TESTNUM, 0(t5); \
1:  j 1b;
#define EXTRA_DATA
#define RVTEST_DATA_BEGIN \
    EXTRA_DATA \
    .pushsection .tohost,"aw",@progbits; \
    .align 6; .global tohost; tohost: .dword 0; \
    .global fromhost; fromhost: .dword 0; \
    .popsection; \
    .align 4; .global begin_signature; begin_signature:
#define RVTEST_DATA_END .align 4; .global end_signature; end_signature:
#endif
'''

LINK_LD = '''OUTPUT_ARCH( "riscv" )
ENTRY(_start)
SECTIONS
{
  . = 0x00000000;
  .text.init : { *(.text.init) }
  .text : { *(.text) }
  . = 0x00001000;
  .tohost : { *(.tohost) }
  .data : { *(.data) }
  .bss : { *(.bss) }
  _end = .;
}
'''

IMEM_SV = """`timescale 1ns / 1ps
module Instruction_Memory (
    input  logic [31:0] read_address,
    output logic [31:0] instruction_out
);
    logic [31:0] I_Memory [0:%d];
    initial begin
        for (int k = 0; k < %d; k++) I_Memory[k] = 32'h00000013;
        $readmemh("program.hex", I_Memory);
    end
    assign instruction_out = I_Memory[read_address[31:2]];
endmodule
""" % (IMEM_WORDS - 1, IMEM_WORDS)

TB_SV = """`timescale 1ns / 1ps
module tb_rv;
    reg clk = 0, reset = 1;
    integer maxc, c;
    reg [31:0] th;
    top_pipelined uut (.clk(clk), .reset(reset));
    always #5 clk = ~clk;
    initial begin
        if (!$value$plusargs("MAXCYC=%%d", maxc)) maxc = 200000;
        repeat (2) @(posedge clk);
        @(negedge clk) reset = 0;
        c = 0; th = 0;
        while (th == 0 && c < maxc) begin
            @(posedge clk); #1;
            th = uut.Data_Mem_inst.D_Memory[%d];
            c = c + 1;
        end
        if (th == 0)      $display("RESULT TIMEOUT");
        else if (th == 1) $display("RESULT PASS cycles=%%0d", c);
        else              $display("RESULT FAIL testnum=%%0d", th >> 1);
        $finish;
    end
endmodule
""" % TOHOST_WORD


def bin_to_hex(path_bin, path_hex, max_words=None):
    data = open(path_bin, 'rb').read() if os.path.exists(path_bin) else b''
    data += b'\x00' * (-len(data) % 4)
    words = [int.from_bytes(data[i:i + 4], 'little') for i in range(0, len(data), 4)]
    if max_words is not None and len(words) > max_words:
        raise ValueError(f'image has {len(words)} words, limit is {max_words}')
    with open(path_hex, 'w') as f:
        f.write('\n'.join(f'{w:08x}' for w in words) + ('\n' if words else ''))
    return len(words)


def build_rtl(src_dir, work):
    if not any('LOADDATA' in open(f, errors='ignore').read()
               for f in glob.glob(os.path.join(src_dir, '*.sv'))):
        sys.exit('Data_Memory has no LOADDATA hook. Add inside its initial block:\n'
                 '    if ($test$plusargs("LOADDATA")) $readmemh("data.hex", D_Memory, 1024);')
    files = []
    for f in sorted(glob.glob(os.path.join(src_dir, '*.sv')) + glob.glob(os.path.join(src_dir, '*.v'))):
        txt = open(f, errors='ignore').read()
        if re.search(r'^\s*module\s+Instruction_Memory\b', txt, re.M):
            continue
        if re.search(r'^\s*module\s+tb\w*', txt, re.M):
            continue
        shutil.copy(f, work)
        files.append(os.path.basename(f))
    open(os.path.join(work, 'imem_rv.sv'), 'w').write(IMEM_SV)
    open(os.path.join(work, 'tb_rv.sv'), 'w').write(TB_SV)
    files += ['imem_rv.sv', 'tb_rv.sv']
    r = subprocess.run(['iverilog', '-g2012', '-s', 'tb_rv', '-o', 'sim.out'] + files,
                       cwd=work, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        sys.exit('iverilog compile failed')


def run_one(work, tests_dir, src_file, timeout, maxcyc):
    name = os.path.splitext(os.path.basename(src_file))[0]
    env_dir = os.path.join(work, 'env')
    elf = os.path.join(work, name + '.elf')
    cmd = [GCC, '-march=rv32i', '-mabi=ilp32', '-static', '-mcmodel=medany',
           '-fvisibility=hidden', '-nostdlib', '-nostartfiles',
           '-I', env_dir, '-I', os.path.join(tests_dir, 'isa', 'macros', 'scalar'),
           '-T', os.path.join(work, 'link.ld'), src_file, '-o', elf]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return 'BUILD-ERR', r.stderr.strip().splitlines()[-1] if r.stderr.strip() else ''
    subprocess.run([OBJCOPY, '-O', 'binary', '-j', '.text.init', '-j', '.text', elf,
                    os.path.join(work, 'text.bin')], check=True)
    subprocess.run([OBJCOPY, '-O', 'binary', '-j', '.tohost', '-j', '.data', elf,
                    os.path.join(work, 'data.bin')], check=True)
    try:
        bin_to_hex(os.path.join(work, 'text.bin'), os.path.join(work, 'program.hex'), IMEM_WORDS)
        bin_to_hex(os.path.join(work, 'data.bin'), os.path.join(work, 'data.hex'), 1024)
    except ValueError as e:
        return 'BUILD-ERR', str(e)
    try:
        r = subprocess.run(['vvp', 'sim.out', '+LOADDATA', f'+MAXCYC={maxcyc}'], cwd=work,
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 'TIMEOUT', 'simulator timeout (try Icarus >= 12)'
    m = re.search(r'RESULT (\w+)(.*)', r.stdout)
    if not m:
        return 'NO-RESULT', 'testbench printed no RESULT line'
    return m.group(1), m.group(2).strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tests', required=True, help='path to the riscv-tests repository')
    ap.add_argument('--src', default='RTL', help='folder with the RTL .sv files')
    ap.add_argument('--only', default='', help='run tests whose name contains this text')
    ap.add_argument('--timeout', type=int, default=120, help='seconds per simulation')
    ap.add_argument('--maxcyc', type=int, default=200000, help='cycle limit per test')
    ap.add_argument('--keep', action='store_true')
    args = ap.parse_args()

    tests_dir = os.path.expanduser(args.tests)
    srcs = sorted(glob.glob(os.path.join(tests_dir, 'isa', 'rv32ui', '*.S')))
    if not srcs:
        sys.exit(f'no rv32ui/*.S found under {tests_dir}')
    srcs = [s for s in srcs if args.only in os.path.basename(s)]

    work = tempfile.mkdtemp(prefix='rvtests_')
    os.makedirs(os.path.join(work, 'env'))
    open(os.path.join(work, 'env', 'riscv_test.h'), 'w').write(RISCV_TEST_H)
    open(os.path.join(work, 'link.ld'), 'w').write(LINK_LD)
    build_rtl(os.path.expanduser(args.src), work)

    passed, failed, expected = 0, [], 0
    for s in srcs:
        name = os.path.splitext(os.path.basename(s))[0]
        status, detail = run_one(work, tests_dir, s, args.timeout, args.maxcyc)
        if status == 'PASS':
            passed += 1
            print(f'[PASS] {name:12s} {detail}')
        elif name in EXPECTED_FAIL:
            expected += 1
            print(f'[XFAIL] {name:11s} {status} {detail}  <- expected: {EXPECTED_FAIL[name]}')
        else:
            failed.append(name)
            print(f'[FAIL] {name:12s} {status} {detail}')

    print(f'\nrv32ui: {passed} passed, {expected} expected failures, {len(failed)} unexpected failures')
    if failed:
        print('unexpected failures:', ', '.join(failed))
    if args.keep or failed:
        print(f'work folder kept: {work}')
    else:
        shutil.rmtree(work, ignore_errors=True)
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()

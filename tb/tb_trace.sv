`timescale 1ns / 1ps
module tb_trace;
    reg clk = 0, reset = 1;
    integer cycles;
    top_pipelined uut (.clk(clk), .reset(reset));
    always #5 clk = ~clk;

    // One line per retired instruction, printed at negedge so values are stable.
    always @(negedge clk)
        if (!reset && uut.tr.valid_WB) begin
            if (uut.tr.is_mem_WB)
                $display("RET %0d %08x %08x %08x %08x", uut.cycle_cnt,
                         uut.tr.pc_WB, uut.tr.addr_WB, uut.tr.opA_WB, uut.tr.opB_WB);
            else
                $display("RET %0d %08x - %08x %08x", uut.cycle_cnt,
                         uut.tr.pc_WB, uut.tr.opA_WB, uut.tr.opB_WB);
        end

    initial begin
        if (!$value$plusargs("CYCLES=%d", cycles)) cycles = 200;
        repeat (2) @(posedge clk);
        @(negedge clk) reset = 0;
        repeat (cycles) @(posedge clk);
        #1;
        for (int i = 0; i < 32; i++) $display("R %0d %h", i, uut.Reg_File_ID.Registers[i]);
        $finish;
    end
endmodule

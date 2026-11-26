`timescale 1ns / 1ps
module trace_pipe (
    input  logic        clk, reset,
    input  logic        flush_ifid,    // redirect_EX
    input  logic        ifid_write,    // IF_ID_Write
    input  logic        bubble_idex,   // stall | redirect_EX
    input  logic [31:0] pc_ID,
    input  logic        is_mem_EX,     // MemRead_EX | MemWrite_EX
    input  logic [31:0] addr_EX,       // ex_result_EX (the address for loads/stores)
    input  logic [31:0] opA_EX, opB_EX,// forwardA_mux_out, forwardB_mux_out
    output logic        valid_WB, is_mem_WB,
    output logic [31:0] pc_WB, addr_WB, opA_WB, opB_WB
);
    logic v_ID, v_EX, v_MEM;
    logic [31:0] pc_EX, pc_MEM;
    logic        mem_MEM;
    logic [31:0] addr_MEM, opA_MEM, opB_MEM;

    always_ff @(posedge clk or posedge reset) begin
        if (reset) begin
            v_ID <= 0; v_EX <= 0; v_MEM <= 0; valid_WB <= 0;
            is_mem_WB <= 0; mem_MEM <= 0;
            pc_EX <= 0; pc_MEM <= 0; pc_WB <= 0;
            addr_MEM <= 0; addr_WB <= 0;
            opA_MEM <= 0; opA_WB <= 0; opB_MEM <= 0; opB_WB <= 0;
        end else begin
            if (flush_ifid)      v_ID <= 1'b0;      // NOP inserted into IF/ID
            else if (ifid_write) v_ID <= 1'b1;      // new instruction fetched
            v_EX     <= bubble_idex ? 1'b0 : v_ID;  // bubble into EX
            v_MEM    <= v_EX;
            valid_WB <= v_MEM;
            pc_EX  <= pc_ID;   pc_MEM  <= pc_EX;   pc_WB  <= pc_MEM;
            mem_MEM  <= is_mem_EX;  is_mem_WB <= mem_MEM;
            addr_MEM <= addr_EX;    addr_WB   <= addr_MEM;
            opA_MEM  <= opA_EX;     opA_WB    <= opA_MEM;
            opB_MEM  <= opB_EX;     opB_WB    <= opB_MEM;
        end
    end
endmodule

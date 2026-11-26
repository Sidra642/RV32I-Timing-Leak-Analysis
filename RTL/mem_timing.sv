`timescale 1ns / 1ps
`ifndef CFG_CACHE_EN
 `define CFG_CACHE_EN 1
`endif
`ifndef CFG_MISS_PENALTY
 `define CFG_MISS_PENALTY 8
`endif
`ifndef CFG_WRITE_PENALTY
 `define CFG_WRITE_PENALTY 3
`endif
`ifndef CFG_SILENT_SKIP
 `define CFG_SILENT_SKIP 1
`endif

module mem_timing #(
    parameter CACHE_EN          = `CFG_CACHE_EN,
    parameter LINES             = 16,
    parameter OFFSET_BITS       = 4,                 // 16-byte lines -> 256 B cache
    parameter MISS_PENALTY      = `CFG_MISS_PENALTY,
    parameter WRITE_PENALTY     = `CFG_WRITE_PENALTY,
    parameter SILENT_STORE_SKIP = `CFG_SILENT_SKIP
)(
    input  logic        clk, reset,
    input  logic        req,        // a load or store is in MEM
    input  logic        is_store,
    input  logic        silent,     // store data == what memory already holds
    input  logic [31:0] addr,
    output logic        stall       // 1 = access not finished yet
);
    localparam IDX  = $clog2(LINES);
    localparam TAGW = 32 - IDX - OFFSET_BITS;

    logic            v   [0:LINES-1];
    logic [TAGW-1:0] tag [0:LINES-1];
    logic [7:0]      mcnt, wcnt;
    integer          i;

    wire [IDX-1:0]  idx = addr[OFFSET_BITS +: IDX];
    wire [TAGW-1:0] t   = addr[31 : OFFSET_BITS+IDX];
    wire hit        = (CACHE_EN == 0) || (v[idx] && tag[idx] == t);
    wire need_write = is_store && !(SILENT_STORE_SKIP && silent);

    wire miss_busy  = req && !hit;
    wire write_busy = req && hit && need_write && (wcnt < WRITE_PENALTY);
    assign stall    = miss_busy || write_busy;

    always_ff @(posedge clk or posedge reset) begin
        if (reset) begin
            for (i = 0; i < LINES; i = i + 1) v[i] <= 1'b0;
            mcnt <= 0; wcnt <= 0;
        end else begin
            if (miss_busy) begin                     // exactly MISS_PENALTY stall cycles
                if (mcnt == MISS_PENALTY-1) begin
                    v[idx] <= 1'b1; tag[idx] <= t; mcnt <= 0;   // line installed
                end else mcnt <= mcnt + 1;
            end
            if (write_busy)      wcnt <= wcnt + 1;   // exactly WRITE_PENALTY stall cycles
            else if (req && hit) wcnt <= 0;
        end
    end
endmodule

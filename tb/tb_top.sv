
`timescale 1ns / 1ps

module tb_top;
    initial $display("TB START t=%0t", $time);

    reg clk;
    reg reset;

    // Instantiate processor
    top_pipelined uut (
        .clk(clk),
        .reset(reset)
    );

    // Clock generation: 10 ns period
    initial begin
        clk = 0;
        forever #5 clk = ~clk;
    end

    // Reset and simulation control
    initial begin
        reset = 1;

        // Hold reset for two clock cycles
        repeat (2) @(posedge clk);

        @(negedge clk);
        reset = 0;
        
        // Run processor for 400 clock cycles
        repeat (400) @(posedge clk);
        
        $display("Simulation completed.");
        $finish;
    end
    
   

    // Waveform generation
    initial begin
        $dumpfile("tb.vcd");
       $dumpvars(0, tb_top);
    end

endmodule


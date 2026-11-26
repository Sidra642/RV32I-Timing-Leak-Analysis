`timescale 1ns / 1ps

module IF_ID_reg (
    input logic clk,
    input logic reset,
    input logic [31:0] PC_in,
    input logic [31:0] instruction_in,
    input logic IF_ID_Write,  // New input
    output logic [31:0] PC_out,
    output logic [31:0] instruction_out,
    input logic flush //new added
);
    always_ff @(posedge clk or posedge reset) begin
       if (reset || flush) 
       begin 
       PC_out <= 0; 
       instruction_out <= 32'h00000013; 
       end
       else if (IF_ID_Write) begin 
       	PC_out <= PC_in; 
       	instruction_out <= instruction_in; 
       	end
    end
endmodule

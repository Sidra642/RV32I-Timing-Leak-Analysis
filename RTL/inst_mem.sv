`timescale 1ns / 1ps

module Instruction_Memory (
 
    input  logic [31:0] read_address,
    output logic [31:0] instruction_out
);

    // Declare memory (128 x 32-bit)
    logic [31:0] I_Memory [0:127];
    //integer k;
    
    // Initialize / reset memory
    initial begin
    	for (int k = 0; k < 128; k++) I_Memory[k] = 32'h00000013;
    	$readmemh("program.hex", I_Memory);
          
         
          
        end
   
    
    // Read instruction (word-aligned addresses only)
    assign instruction_out = I_Memory[read_address[31:2]];

endmodule

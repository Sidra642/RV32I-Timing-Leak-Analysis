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
    
        
          
            I_Memory[0]  <= 32'h0; 
            I_Memory[1]  <= 32'h00500113; 
            I_Memory[2]  <= 32'h00C00193; 
            I_Memory[3]  <= 32'hFF718393; 
            I_Memory[4] <= 32'h0023E233; 
            I_Memory[5] <= 32'h0041F2B3;
            I_Memory[6] <= 32'h004282B3; 
            I_Memory[7] <= 32'h02728863; 
            
          
            I_Memory[8] <= 32'h0041A233; 
            I_Memory[9] <= 32'h00020463; 
            I_Memory[10] <= 32'h00000293; 

            I_Memory[11] <= 32'h0023A233; 
            I_Memory[12] <= 32'h005203B3; 
            I_Memory[13] <= 32'h402383B3; 
            I_Memory[14] <= 32'h0471AA23; 
            I_Memory[15] <= 32'h06002103; 
            I_Memory[16] <= 32'h005104B3; 
            I_Memory[17] <= 32'h008001EF; 
            I_Memory[18] <= 32'h00100113; 
            I_Memory[19] <= 32'h00910133; 

            
            I_Memory[20] <= 32'h0221A023; // sw x2, 0x20(x3)
            I_Memory[21] <= 32'h00210063; // beq x2, x1, done 
            I_Memory[22] <= 32'h0;
            
            
     
          
        end
   
    
    // Read instruction (word-aligned addresses only)
    assign instruction_out = I_Memory[read_address[31:2]];

endmodule

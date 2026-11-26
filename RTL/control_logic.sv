`timescale 1ns / 1ps

module control_unit (
    input  logic       reset,
    input  logic [6:0] opcode,      // instruction[6:0]
    input  logic [2:0] funct3,      // instruction[14:12]
    input  logic       zero,        // ALU Zero flag
    input  logic       negative,    // ALU Negative flag (signed less-than)
    input  logic       carry,       // ALU Carry flag (for unsigned compare)
    input  logic       overflow,    // ALU Overflow flag (not always needed)

    // main control signals
    output logic       RegWrite,    
    output logic       ALUSrc,      
    output logic [1:0] ALUOp,      
    output logic       MemRead,    
    output logic       MemWrite,    
    output logic [1:0] MemtoReg,    

    // PC control
    output logic [1:0] jump         // 00 = PC+4, 01 = PC+offset, 10 = JALR
);

   
 always_comb begin
    RegWrite = 0; ALUSrc = 0; ALUOp = 2'b00; MemRead = 0;
    MemWrite = 0; MemtoReg = 2'b00; jump = 2'b00;
    if (!reset) case (opcode)
        7'b0110011: begin RegWrite = 1; ALUOp = 2'b10; end
        7'b0010011: begin RegWrite = 1; ALUSrc = 1; ALUOp = 2'b11; end
        7'b0000011: begin RegWrite = 1; ALUSrc = 1; MemRead = 1; MemtoReg = 2'b01; end
        7'b0100011: begin ALUSrc = 1; MemWrite = 1; end
        7'b1100011: begin ALUOp = 2'b01; jump = 2'b11; end
        7'b1101111: begin RegWrite = 1; jump = 2'b01; end
        7'b1100111: begin RegWrite = 1; ALUSrc = 1; jump = 2'b10; end
        7'b0110111: begin RegWrite = 1; ALUSrc = 1; MemtoReg = 2'b11; end // LUI
        7'b0010111: begin RegWrite = 1; ALUSrc = 1; MemtoReg = 2'b10; end // AUIPC
        default: ;
    endcase
end
endmodule

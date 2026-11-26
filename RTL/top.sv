`timescale 1ns / 1ps

module top_pipelined (
    input logic clk,
    input logic reset
);

    // === IF Stage Wires ===
    logic [31:0] PC_IF, PC_next_IF, instruction_IF;
    logic PCWrite;  // From hazard detection

    // === IF/ID Pipeline Register Wires ===
    logic [31:0] PC_ID, instruction_ID;
    logic IF_ID_Write;  // From hazard detection

    // === ID Stage Wires ===
    logic [31:0] Rd1_ID, Rd2_ID;
    logic [31:0] ImmExt_ID, raw_imm_ID, shifted_imm_ID;
    logic [4:0] Rs1_ID, Rs2_ID, Rd_ID;
    logic RegWrite_ID, ALUSrc_ID, MemWrite_ID, MemRead_ID;
    logic [1:0] ALUOp_ID, MemtoReg_ID, jump_ID;
    logic [2:0] funct3_ID;
    logic fun7_ID;
    logic [3:0] control_ID;
    logic zero_EX, negative_EX, carry_EX, overflow_EX;
    logic shift_en_ID;
    logic stall;  // From hazard detection

    // === ID/EX Pipeline Register Wires ===
    logic [31:0] PC_EX, Rd1_EX, Rd2_EX, ImmExt_EX;
    logic [4:0] Rs1_EX, Rs2_EX, Rd_EX;
    logic RegWrite_EX, ALUSrc_EX, MemWrite_EX, MemRead_EX;
    logic [1:0] ALUOp_EX, MemtoReg_EX, jump_EX;
    logic [2:0] funct3_EX;
    logic fun7_EX;
    logic [3:0] control_EX;

    // === EX Stage Wires ===
    logic [31:0] mux1_EX, ALU_result_EX, branch_target_EX, jalr_target_EX;
    logic [31:0] forwardA_mux_out, forwardB_mux_out;
    logic zero_EX_stage, negative_EX_stage, carry_EX_stage, overflow_EX_stage;
    logic [1:0] forwardA, forwardB;  // From forwarding unit

    // === EX/MEM Pipeline Register Wires ===
    logic [31:0] ALU_result_MEM, Rd2_MEM, PC_branch_MEM;
    logic [4:0] Rd_MEM;
    logic RegWrite_MEM, MemWrite_MEM, MemRead_MEM;
    logic [1:0] MemtoReg_MEM, jump_MEM;
  
    
    // === MEM Stage Wires ===
    logic [31:0] DataMem_out_MEM;

    // === MEM/WB Pipeline Register Wires ===
    logic [31:0] MemData_WB, ALU_result_WB;
    logic [4:0] Rd_WB;
    logic RegWrite_WB;
    logic [1:0] MemtoReg_WB;

    // === WB Stage Wires ===
    logic [31:0] WriteBack_WB;
    
    logic [2:0] funct3_MEM;
    

    //added new
    logic [31:0] ex_result_EX, redirect_target_EX, PC_mux_IF;
    logic branch_taken_EX, redirect_EX;
    
    
    //CSR logic
    logic is_csr_ID, is_csr_EX;
    logic [31:0] cycle_cnt;
    
    //
    logic mem_stall, silent_MEM;




always_comb begin
	if (is_csr_EX)
        ex_result_EX = cycle_cnt; 

    else if (jump_EX == 2'b01 || jump_EX == 2'b10) 
    	ex_result_EX = PC_EX + 32'd4;
    else case (MemtoReg_EX)
        2'b10:   ex_result_EX = PC_EX + ImmExt_EX;   // AUIPC
        2'b11:   ex_result_EX = ImmExt_EX;           // LUI
        default: ex_result_EX = ALU_result_EX;
    endcase
end

always_comb case (funct3_EX)
    3'b000: branch_taken_EX = (forwardA_mux_out == forwardB_mux_out);
    3'b001: branch_taken_EX = (forwardA_mux_out != forwardB_mux_out);
    3'b100: branch_taken_EX = ($signed(forwardA_mux_out) <  $signed(forwardB_mux_out));
    3'b101: branch_taken_EX = ($signed(forwardA_mux_out) >= $signed(forwardB_mux_out));
    3'b110: branch_taken_EX = (forwardA_mux_out <  forwardB_mux_out);
    3'b111: branch_taken_EX = (forwardA_mux_out >= forwardB_mux_out);
    default: branch_taken_EX = 1'b0;
endcase

assign redirect_EX = (jump_EX == 2'b01) | (jump_EX == 2'b10) |
                     ((jump_EX == 2'b11) & branch_taken_EX);
assign redirect_target_EX = (jump_EX == 2'b10) ? {jalr_target_EX[31:1], 1'b0}
                                                : branch_target_EX;
assign PC_mux_IF = redirect_EX ? redirect_target_EX : PC_next_IF;


//for counter
always_ff @(posedge clk or posedge reset)
    if (reset) cycle_cnt <= 32'd0;
    else       cycle_cnt <= cycle_cnt + 32'd1;

//added new
    
    // ============== Hazard Detection Unit ==============
    hazard_detection_unit hazard_unit (
        .ID_EX_MemRead(MemRead_EX),
        .ID_EX_Rd(Rd_EX),
        .IF_ID_Rs1(Rs1_ID),
        .IF_ID_Rs2(Rs2_ID),
        .stall(stall),
        .PCWrite(PCWrite),
        .IF_ID_Write(IF_ID_Write)
    );

    // ============== Forwarding Unit ==============
    forwarding_unit fwd_unit (
        .EX_rs1(Rs1_EX),
        .EX_rs2(Rs2_EX),
        .MEM_rd(Rd_MEM),
        .MEM_RegWrite(RegWrite_MEM),
        .WB_rd(Rd_WB),
        .WB_RegWrite(RegWrite_WB),
        .forwardA(forwardA),
        .forwardB(forwardB)
    );
    // ============== IF Stage ==============

    program_counter PC_inst (
        .clk(clk),
        .reset(reset),
        .PC_in(PC_mux_IF),  //changed from PC_next_IF
        .PC_out(PC_IF),
        .PCWrite((PCWrite | redirect_EX) & ~mem_stall)  // changed from PCWrite input to program_counter
    );

    PC_plus4 PC_plus4_inst (
        .fromPC(PC_IF),
        .NextoPC(PC_next_IF)
    );

    Instruction_Memory Inst_Mem (
        .read_address(PC_IF),
        .instruction_out(instruction_IF)
    );

    // IF/ID Pipeline Register
    IF_ID_reg IF_ID_reg_inst (
        .clk(clk),
        .reset(reset),
        .PC_in(PC_IF),
        .instruction_in(instruction_IF),
        .PC_out(PC_ID),
        .instruction_out(instruction_ID),
        .IF_ID_Write(IF_ID_Write & ~mem_stall),  // Add write enable
        .flush(redirect_EX & ~mem_stall) //added new
    );
    
         // Extract fields from instruction
    assign Rs1_ID = instruction_ID[19:15];
    assign Rs2_ID = instruction_ID[24:20];
    assign Rd_ID  = instruction_ID[11:7];
    assign funct3_ID = instruction_ID[14:12];
    assign fun7_ID = instruction_ID[30];
 

    Register_File Reg_File_ID (
        .clk(clk),
        .reset(reset),
        .RegWrite(RegWrite_WB),
        .Rs1(Rs1_ID),
        .Rs2(Rs2_ID),
        .Rd(Rd_WB),
        .Write_data(WriteBack_WB),
        .read_data1(Rd1_ID),
        .read_data2(Rd2_ID)
    );

    // ============== ID Stage ==============

 

    ImmGen ImmGen_ID (
        .opcode(instruction_ID[6:0]),
        .instruction(instruction_ID),
        .ImmExt(raw_imm_ID)
    );


    
    assign ImmExt_ID = raw_imm_ID;

    control_unit Control_unit_ID (
        .reset(reset),
        .opcode(instruction_ID[6:0]),
        .funct3(funct3_ID),
        .zero(1'b0),
        .negative(1'b0),
        .carry(1'b0),
        .overflow(1'b0),
        .RegWrite(RegWrite_ID),
        .ALUSrc(ALUSrc_ID),
        .ALUOp(ALUOp_ID),
        .MemRead(MemRead_ID),
        .MemWrite(MemWrite_ID),
        .MemtoReg(MemtoReg_ID),
        .jump(jump_ID),
        .is_csr(is_csr_ID) 
    );


   // ID/EX Pipeline Register
    ID_EX_reg ID_EX_reg_inst (
        .clk(clk),
        .reset(reset),
        .PC_in(PC_ID),
        .Rd1_in(Rd1_ID),
        .Rd2_in(Rd2_ID),
        .ImmExt_in(ImmExt_ID),
        .Rs1_in(Rs1_ID),
        .Rs2_in(Rs2_ID),
        .Rd_in(Rd_ID),
        .RegWrite_in(RegWrite_ID),
        .ALUSrc_in(ALUSrc_ID),
        .MemRead_in(MemRead_ID),
        .MemWrite_in(MemWrite_ID),
        .ALUOp_in(ALUOp_ID),
        .MemtoReg_in(MemtoReg_ID),
        .jump_in(jump_ID),
        .funct3_in(funct3_ID),
        .fun7_in(fun7_ID),
        .PC_out(PC_EX),
        .Rd1_out(Rd1_EX),
        .Rd2_out(Rd2_EX),
        .ImmExt_out(ImmExt_EX),
        .Rs1_out(Rs1_EX),
        .Rs2_out(Rs2_EX),
        .Rd_out(Rd_EX),
        .RegWrite_out(RegWrite_EX),
        .ALUSrc_out(ALUSrc_EX),
        .MemRead_out(MemRead_EX),
        .MemWrite_out(MemWrite_EX),
        .ALUOp_out(ALUOp_EX),
        .MemtoReg_out(MemtoReg_EX),
        .jump_out(jump_EX),
        .funct3_out(funct3_EX),
        .fun7_out(fun7_EX),
        .stall(stall | redirect_EX),  // Add stall input //added new from stall
        
        .is_csr_in(is_csr_ID),    // new inputs
        .is_csr_out(is_csr_EX),   // new output
        
        .hold(mem_stall)
        
    );
   ALU_Control ALU_Control_EX (
        .fun7(fun7_EX),
        .fun3(funct3_EX),
        .ALUOp(ALUOp_EX),
        .Control_out(control_EX)
    );

  

    // ============== EX Stage ==============

    // Forwarding MUX for ALU input A
    always_comb begin
  //  $display("%0t top.sv forward A comb", $time);
        case (forwardA)
            
            2'b00: forwardA_mux_out = Rd1_EX;        // No forwarding
            2'b01: forwardA_mux_out = WriteBack_WB;  // Forward from WB stage
            2'b10: forwardA_mux_out = ALU_result_MEM; // Forward from MEM stage
            default: forwardA_mux_out = Rd1_EX;
        endcase
    end

    // Forwarding MUX for ALU input B (before ALU source mux)
    always_comb begin
   // $display("%0t top.sv forward B comb", $time);
        case (forwardB)
            
            2'b00: forwardB_mux_out = Rd2_EX;        // No forwarding
            2'b01: forwardB_mux_out = WriteBack_WB;  // Forward from WB stage
            2'b10: forwardB_mux_out = ALU_result_MEM; // Forward from MEM stage
            default: forwardB_mux_out = Rd2_EX;
        endcase
    end

    // ALU MUX selects between forwarded Rd2_EX and immediate value
    Mux1 ALU_mux_EX (
        .sel1(ALUSrc_EX),
        .A1(forwardB_mux_out),  // Use forwarded value
        .B1(ImmExt_EX),
        .Mux1_out(mux1_EX)
    );

    ALU ALU_EX (
        .A(forwardA_mux_out),   // Use forwarded value
        .B(mux1_EX),
        .Control_in(control_EX),
        .ALU_Result(ALU_result_EX),
        .zero(zero_EX_stage),
        .negative(negative_EX_stage),
        .carry(carry_EX_stage),
        .overflow(overflow_EX_stage)
    );

    // Branch target calculation
    assign branch_target_EX = PC_EX + ImmExt_EX;

    // JALR target calculation
    assign jalr_target_EX = forwardA_mux_out + ImmExt_EX;  // Use forwarded value

    // EX/MEM Pipeline Register
EX_MEM_reg EX_MEM_reg_inst (
    .clk(clk),
    .reset(reset),
    .ALU_result_in(ex_result_EX),  //changed new ALU_result_EX from to ex_result_EX
    .Rd2_in(forwardB_mux_out),
    .Rd_in(Rd_EX),
    .RegWrite_in(RegWrite_EX),
    .MemRead_in(MemRead_EX),
    .MemWrite_in(MemWrite_EX),
    .MemtoReg_in({1'b0, MemtoReg_EX == 2'b01}),  //changed new
    .jump_in(jump_EX),              // Changed from jump_in to jump_in
    .PC_branch_in(branch_target_EX), // Changed from PC_branch_in to PC_branch_in
    .ALU_result_out(ALU_result_MEM),
    .Rd2_out(Rd2_MEM),
    .Rd_out(Rd_MEM),
    .RegWrite_out(RegWrite_MEM),
    .MemRead_out(MemRead_MEM),
    .MemWrite_out(MemWrite_MEM),
    .MemtoReg_out(MemtoReg_MEM),
    .jump_out(jump_MEM),            // Changed from jump_out to jump_out
    .PC_branch_out(PC_branch_MEM),   // Changed from PC_branch_out to PC_branch_out
    .funct3_in(funct3_EX),
    .funct3_out(funct3_MEM),
    .hold(mem_stall)
);

 
    // ============== MEM Stage ==============

    Data_Memory Data_Mem_inst (
        .clk(clk),
        .reset(reset),
        .MemWrite(MemWrite_MEM & ~mem_stall),
        .MemRead(MemRead_MEM),
        .funct3(funct3_MEM),
        .read_address(ALU_result_MEM),
        .Write_data(Rd2_MEM),
        .MemData_out(DataMem_out_MEM),
        .silent_store(silent_MEM)
    );

    // MEM/WB Pipeline Register
MEM_WB_reg MEM_WB_reg_inst (
    .clk(clk),
    .reset(reset),
    .MemData_in(DataMem_out_MEM),   // Changed from MemData_in to MemData_in
    .ALU_result_in(ALU_result_MEM),
    .Rd_in(Rd_MEM),
    .RegWrite_in(RegWrite_MEM),
    .MemtoReg_in(MemtoReg_MEM),
    .MemData_out(MemData_WB),       // Changed from MemData_out to MemData_out
    .ALU_result_out(ALU_result_WB),
    .Rd_out(Rd_WB),
    .RegWrite_out(RegWrite_WB),
    .MemtoReg_out(MemtoReg_WB),
    .hold(mem_stall)
);
    // ============== WB Stage ==============

    Mux3 WriteBack_mux_WB (
        .sel3(MemtoReg_WB),
        .A3(ALU_result_WB),
        .B3(MemData_WB),
        .C3(32'b0), //added new from PC_next_IF
        .D3(32'b0),
        .Mux3_out(WriteBack_WB)
    );
    
    
    //trace pipeline
    trace_pipe tr (
    	.clk(clk), .reset(reset),
    	.flush_ifid(redirect_EX), .ifid_write(IF_ID_Write),
    	.bubble_idex(stall | redirect_EX),
    	.pc_ID(PC_ID),
    	.is_mem_EX(MemRead_EX | MemWrite_EX),
    	.addr_EX(ex_result_EX),
    	.opA_EX(forwardA_mux_out), .opB_EX(forwardB_mux_out),
    	.valid_WB(), .is_mem_WB(), .pc_WB(), .addr_WB(), .opA_WB(), .opB_WB(),
    	.freeze(mem_stall), .retire_WB()
    	
    );
    
    mem_timing mt (
    .clk(clk), .reset(reset),
    .req(MemRead_MEM | MemWrite_MEM),
    .is_store(MemWrite_MEM),
    .silent(silent_MEM),
    .addr(ALU_result_MEM),
    .stall(mem_stall)
);


endmodule

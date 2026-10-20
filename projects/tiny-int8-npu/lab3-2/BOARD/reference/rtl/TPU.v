module TPU #(
    parameter A_WIDTH = 8,
    parameter B_WIDTH = 8,
    parameter PSUM_WIDTH = 32
)(
    input                         clk,
    input                         rst_n,

    // A one-cycle pulse on in_valid starts a new GEMV operation.
    input                         in_valid,
    input      [7:0]              K,
    input      [7:0]              M,
    input      [7:0]              N,
    output reg                    busy,

    // Matrix A BRAM interface: four packed INT8 values per word.
    output                        A_ram_en,
    output                        A_wr_en,
    output     [15:0]             A_index,
    output     [A_WIDTH*4-1:0]    A_data_in,
    input      [A_WIDTH*4-1:0]    A_data_out,

    // Matrix B BRAM interface: four packed INT8 values per word.
    output                        B_ram_en,
    output                        B_wr_en,
    output     [15:0]             B_index,
    output     [B_WIDTH*4-1:0]    B_data_in,
    input      [B_WIDTH*4-1:0]    B_data_out,

    // Matrix C BRAM interface: four packed INT32 values per word.
    output                        C_ram_en,
    output                        C_wr_en,
    output     [15:0]             C_index,
    output     [127:0]            C_data_in,
    input      [127:0]            C_data_out
);

localparam IDLE=0, READ=1, MAC=2, WRITE=3, DRAIN=4;
reg [2:0] state;
reg [7:0] rows, cols, row, col;
wire signed [A_WIDTH-1:0] operand_a = A_data_out >> ((row % 4)*A_WIDTH);
wire signed [B_WIDTH-1:0] operand_b = B_data_out[B_WIDTH-1:0];
wire signed [PSUM_WIDTH-1:0] partial_sum;
wire pe_done;
assign A_ram_en = busy && state == READ;
assign B_ram_en = busy && state == READ;
assign A_wr_en = 1'b0;
assign B_wr_en = 1'b0;
assign A_data_in = 0;
assign B_data_in = 0;
assign A_index = (row / 4)*cols + col;
assign B_index = col;
assign C_ram_en = busy && state == WRITE;
assign C_wr_en = C_ram_en;
assign C_index = row;
assign C_data_in = {96'd0, partial_sum[31:0]};
mac_pe #(.W(A_WIDTH), .ACC(PSUM_WIDTH)) pe(
    .clk(clk), .rst_n(rst_n), .valid(busy && state == MAC),
    .first(col == 0), .last(col == cols-1),
    .a(operand_a), .b(operand_b), .sum(partial_sum), .done(pe_done));
always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        state <= IDLE; busy <= 0; rows <= 0; cols <= 0; row <= 0; col <= 0;
    end else case (state)
        IDLE: if (in_valid && M != 0 && K != 0 && N == 1) begin
            rows <= M; cols <= K; row <= 0; col <= 0;
            busy <= 1; state <= READ;
        end
        READ: state <= MAC;
        MAC: if (col == cols-1) state <= WRITE;
             else begin col <= col+1'b1; state <= READ; end
        WRITE: if (row == rows-1) state <= DRAIN;
               else begin row <= row+1'b1; col <= 0; state <= READ; end
        DRAIN: begin busy <= 0; state <= IDLE; end
        default: begin busy <= 0; state <= IDLE; end
    endcase
end


endmodule

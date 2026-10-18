// Independent synchronous write/read ports. No RAM or output reset.
// The wrapper prevents write/read collisions; read data holds when rd_en=0.
module sync_byte_ram (
    input wire clk,
    input wire wr_en,
    input wire [7:0] wr_addr,
    input wire signed [7:0] wr_data,
    input wire rd_en,
    input wire [7:0] rd_addr,
    output reg signed [7:0] rd_data
);
    (* ram_style="distributed" *) reg signed [7:0] mem [0:255];
    always @(posedge clk) begin
        if (wr_en) mem[wr_addr] <= wr_data;
        if (rd_en) rd_data <= mem[rd_addr];
    end
endmodule

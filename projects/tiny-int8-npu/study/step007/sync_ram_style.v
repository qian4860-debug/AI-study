// Same synchronous read/write contract for both implementations; RAM is not reset.
module sync_ram_style #(
 parameter integer DEPTH=64, ADDR_BITS=6, DISTRIBUTED=0
)(
 input wire clk,wr_en,
 input wire [ADDR_BITS-1:0] wr_addr,
 input wire signed [7:0] wr_data,
 input wire rd_en,
 input wire [ADDR_BITS-1:0] rd_addr,
 output reg signed [7:0] rd_data
);
 generate if(DISTRIBUTED)begin: lutram
  (* ram_style="distributed" *) reg signed [7:0] mem[0:DEPTH-1];
  always @(posedge clk)begin
   if(wr_en)mem[wr_addr]<=wr_data;
   if(rd_en)rd_data<=mem[rd_addr];
  end
 end else begin: bram
  (* ram_style="block" *) reg signed [7:0] mem[0:DEPTH-1];
  always @(posedge clk)begin
   if(wr_en)mem[wr_addr]<=wr_data;
   if(rd_en)rd_data<=mem[rd_addr];
  end
 end endgenerate
endmodule

// Same FC scalar interface as step007; each tile computes two output rows.
module fc_shared #(parameter integer RAM_MODE=1)(
 input wire clk,reset,start,
 output wire start_ready,
 input wire layer_cfg,
 input wire [8:0] k_cfg,
 input wire [3:0] m_cfg,
 input wire relu_cfg,fetch_enable,
 input wire host_we,host_layer,
 input wire [1:0] host_kind,
 input wire [10:0] host_addr,
 input wire signed [31:0] host_data,
 output wire host_ready,
 output reg busy,out_valid,
 input wire out_ready,
 output reg [2:0] out_index,
 output reg out_last,
 output reg signed [23:0] out_dot,
 output reg signed [32:0] out_pre,out_data,
 output reg done,cfg_error
);
 localparam IDLE=0,LAUNCH=1,WAIT_DOT=2,EMIT=3;
 reg [1:0] state;
 reg [8:0] k_latched;
 reg [3:0] m_latched;
 reg relu_latched,active_layer,emitting_second,x_pair_q;
 reg [2:0] channel;
 reg signed [31:0] biases[0:15];
 reg signed [31:0] bias0,bias1;
 wire [2:0] next_channel=channel+3'd1;
 wire second_valid=({1'b0,channel}+4'd1<m_latched);
 wire host_legal=(host_kind==0 && host_addr<256) || host_kind==1 || (host_kind==2 && host_addr<8);
 assign host_ready=!reset && !start && host_legal && (!busy || (host_kind==0 && host_layer!=active_layer));
 wire host_fire=host_we && host_ready;
 assign start_ready=!busy;
 wire core_start=!reset && state==LAUNCH;
 wire core_start_ready,core_busy,core_out_valid,core_cfg_error;
 wire [47:0] core_out;
 wire [3:0] rd_mask,x_rd_mask;
 wire [7:0] rd_addr;
 wire [6:0] x_rd_addr={active_layer,rd_addr[6:1]};
 wire [9:0] w_rd_addr={active_layer,channel[2:1],rd_addr[6:0]};
 wire [6:0] x_wr_addr={host_layer,host_addr[7:2]};
 wire [9:0] w_wr_addr={host_layer,host_addr[10:9],host_addr[7:1]};
 wire [1:0] w_wr_bank={host_addr[8],host_addr[0]};
 wire [31:0] x_rd_data,w_rd_data;
 // Live rd_addr advances at request acceptance. Register the pair selector
 // alongside the synchronous RAM response, including fetch pauses and drain.
 always @(posedge clk)begin
  if(reset)x_pair_q<=0;
  else if(|rd_mask)x_pair_q<=rd_addr[0];
 end
 wire [15:0] x_pair=x_pair_q ? x_rd_data[31:16] : x_rd_data[15:0];
 wire signed [23:0] dot0=core_out[23:0],dot1=core_out[47:24];
 wire signed [32:0] biased0={{9{dot0[23]}},dot0}+{bias0[31],bias0};
 wire signed [32:0] biased1={{9{dot1[23]}},dot1}+{bias1[31],bias1};
 genvar lane;
 generate for(lane=0;lane<4;lane=lane+1)begin: bank
  wire x_wr=host_fire && host_kind==0 && host_addr[1:0]==lane;
  wire w_wr=host_fire && host_kind==1 && w_wr_bank==lane;
  assign x_rd_mask[lane]=rd_mask[lane%2] && (rd_addr[0]==(lane/2));
  sync_ram_style #(.DEPTH(128),.ADDR_BITS(7),.DISTRIBUTED(RAM_MODE!=0)) x_ram(
   clk,x_wr,x_wr_addr,host_data[7:0],x_rd_mask[lane],x_rd_addr,x_rd_data[lane*8+:8]);
  sync_ram_style #(.DEPTH(1024),.ADDR_BITS(10),.DISTRIBUTED(RAM_MODE==2)) w_ram(
   clk,w_wr,w_wr_addr,host_data[7:0],rd_mask[lane],w_rd_addr,w_rd_data[lane*8+:8]);
 end endgenerate
 always @(posedge clk)if(host_fire && host_kind==2)biases[{host_layer,host_addr[2:0]}]<=host_data;
 dot_tile_core core(
  .clk(clk),.reset(reset),.start(core_start),.start_ready(core_start_ready),.k_cfg(k_latched),
  .second_cfg(second_valid),.fetch_enable(fetch_enable),.rd_en(rd_mask),.rd_addr(rd_addr),
  .x_rd_data(x_pair),.w_rd_data(w_rd_data),.busy(core_busy),.out_data(core_out),.out_valid(core_out_valid),.cfg_error(core_cfg_error));
 always @(posedge clk)begin
  if(reset)begin
   state<=IDLE;busy<=0;k_latched<=0;m_latched<=0;relu_latched<=0;active_layer<=0;emitting_second<=0;
   channel<=0;bias0<=0;bias1<=0;out_valid<=0;out_index<=0;out_last<=0;out_dot<=0;out_pre<=0;out_data<=0;done<=0;cfg_error<=0;
  end else begin
   done<=0;cfg_error<=0;
   case(state)
    IDLE:if(start && start_ready)begin
     if(k_cfg>=1 && k_cfg<=256 && m_cfg>=1 && m_cfg<=8)begin
      k_latched<=k_cfg;m_latched<=m_cfg;relu_latched<=relu_cfg;active_layer<=layer_cfg;
      channel<=0;emitting_second<=0;busy<=1;out_valid<=0;state<=LAUNCH;
     end else cfg_error<=1;
    end
    LAUNCH:begin bias0<=biases[{active_layer,channel}];bias1<=biases[{active_layer,next_channel}];state<=WAIT_DOT;end
    WAIT_DOT:if(core_out_valid)begin
     out_dot<=dot0;out_pre<=biased0;out_data<=(relu_latched && biased0[32])?33'sd0:biased0;
     out_index<=channel;out_last<=({1'b0,channel}==m_latched-1'b1);emitting_second<=0;out_valid<=1;state<=EMIT;
    end
    EMIT:if(out_valid && out_ready)begin
     if(!emitting_second && second_valid)begin
      out_dot<=dot1;out_pre<=biased1;out_data<=(relu_latched && biased1[32])?33'sd0:biased1;
      out_index<=next_channel;out_last<=({1'b0,next_channel}==m_latched-1'b1);emitting_second<=1;
     end else begin
      out_valid<=0;
      if(out_last)begin busy<=0;done<=1;state<=IDLE;end
      else begin channel<=channel+3'd2;emitting_second<=0;state<=LAUNCH;end
     end
    end
    default:begin state<=IDLE;busy<=0;out_valid<=0;end
   endcase
  end
 end
endmodule

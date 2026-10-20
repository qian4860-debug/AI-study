// Same public contract as step006. One four-MAC engine and one tagged quantizer.
module mlp2_top #(parameter integer RAM_MODE=1)(
 input wire clk,reset,start,
 output wire start_ready,
 input wire [8:0] k_cfg,
 input wire [3:0] h_cfg,o_cfg,
 input wire [15:0] mult1_cfg,mult2_cfg,
 input wire [5:0] shift1_cfg,shift2_cfg,
 input wire fused_cfg,fetch_enable,
 input wire host_we,host_layer,
 input wire [1:0] host_kind,
 input wire [10:0] host_addr,
 input wire signed [31:0] host_data,
 output wire host_ready,
 input wire bridge_done,hidden_ready,
 output wire hidden_valid,hidden_commit,
 output wire [2:0] hidden_index,
 output wire signed [7:0] hidden_data,
 output wire hidden_saturated,hidden_tie,out_valid,
 input wire out_ready,
 output wire [2:0] out_index,
 output wire out_last,
 output wire signed [7:0] out_data,
 output wire out_saturated,out_tie,busy,
 output reg done,cfg_error
);
 localparam IDLE=0,START1=1,RUN1=2,WAIT_HOST=3,START2=4,RUN2=5;
 reg [2:0] state;
 reg [8:0] k;
 reg [3:0] h,o,written;
 reg [15:0] mult1,mult2;
 reg [5:0] shift1,shift2;
 reg fused;
 wire ready_fc,host_ready_fc,fc_valid,fc_last,fc_busy,fc_done,fc_error;
 wire [2:0] fc_index;
 wire signed [23:0] fc_dot;
 wire signed [32:0] fc_pre,fc_data;
 wire q_ready,q_valid,q_error,q_sat,q_tie;
 wire signed [7:0] q_data;
 wire [3:0] q_tag;
 assign busy=state!=IDLE;
 assign start_ready=!busy;
 wire start_fc=!reset && (state==START1 || state==START2);
 wire layer_fc=(state==START2 || state==RUN2);
 wire initial_host=!reset && state==IDLE && !start;
 wire replay_host=!reset && state==WAIT_HOST && !fused && !bridge_done &&
   host_layer && host_kind==0 && host_addr==written && written<h;
 wire internal_hidden=!reset && state==RUN1 && fused;
 wire hidden_accept_ready=state==RUN1 && (fused ? host_ready_fc : hidden_ready);
 assign hidden_valid=q_valid && state==RUN1;
 assign hidden_commit=!reset && hidden_valid && hidden_accept_ready;
 assign hidden_index=q_tag[2:0];assign hidden_data=q_data;
 assign hidden_saturated=q_sat;assign hidden_tie=q_tie;
 wire engine_we=(internal_hidden && q_valid) || (host_we && (initial_host || replay_host));
 wire engine_layer=internal_hidden ? 1'b1 : host_layer;
 wire [1:0] engine_kind=internal_hidden ? 2'd0 : host_kind;
 wire [10:0] engine_addr=internal_hidden ? {8'd0,q_tag[2:0]} : host_addr;
 wire signed [31:0] engine_data=internal_hidden ? {{24{q_data[7]}},q_data} : host_data;
 assign host_ready=(initial_host || replay_host) && host_ready_fc;
 fc_shared #(.RAM_MODE(RAM_MODE)) engine(
  .clk(clk),.reset(reset),.start(start_fc),.start_ready(ready_fc),.layer_cfg(layer_fc),
  .k_cfg(layer_fc ? {5'd0,h}:k),.m_cfg(layer_fc ? o:h),.relu_cfg(!layer_fc),.fetch_enable(fetch_enable),
  .host_we(engine_we),.host_layer(engine_layer),.host_kind(engine_kind),.host_addr(engine_addr),
  .host_data(engine_data),.host_ready(host_ready_fc),.busy(fc_busy),.out_valid(fc_valid),
  .out_ready(q_ready && (state==RUN1 || state==RUN2)),.out_index(fc_index),.out_last(fc_last),
  .out_dot(fc_dot),.out_pre(fc_pre),.out_data(fc_data),.done(fc_done),.cfg_error(fc_error));
 wire quant_accept_ready=state==RUN1 ? hidden_accept_ready : (state==RUN2 && out_ready);
 requant_i8 quant(
  clk,reset,fc_valid && (state==RUN1 || state==RUN2),q_ready,fc_data,
  layer_fc ? mult2:mult1,layer_fc ? shift2:shift1,
  q_valid,quant_accept_ready,q_data,q_sat,q_tie,q_error,{fc_last,fc_index},q_tag);
 assign out_valid=q_valid && state==RUN2;
 assign out_data=q_data;assign out_index=q_tag[2:0];assign out_last=q_tag[3];
 assign out_saturated=q_sat;assign out_tie=q_tie;
 always @(posedge clk)begin
  if(reset)begin
   state<=IDLE;k<=0;h<=0;o<=0;written<=0;mult1<=0;mult2<=0;shift1<=0;shift2<=0;fused<=0;done<=0;cfg_error<=0;
  end else begin
   done<=0;cfg_error<=0;
   case(state)
    IDLE:if(start)begin
     if(k_cfg>=1 && k_cfg<=256 && h_cfg>=1 && h_cfg<=8 && o_cfg>=1 && o_cfg<=8 &&
        mult1_cfg!=0 && mult2_cfg!=0 && shift1_cfg<=47 && shift2_cfg<=47)begin
      k<=k_cfg;h<=h_cfg;o<=o_cfg;mult1<=mult1_cfg;mult2<=mult2_cfg;shift1<=shift1_cfg;shift2<=shift2_cfg;
      fused<=fused_cfg;written<=0;state<=START1;
     end else cfg_error<=1;
    end
    START1:state<=RUN1;
    RUN1:if(hidden_commit && q_tag[3])begin written<=0;state<=fused?START2:WAIT_HOST;end
    WAIT_HOST:begin
     if(host_we && host_ready)written<=written+1'b1;
     if(bridge_done && !host_we && written==h)state<=START2;
    end
    START2:state<=RUN2;
    RUN2:if(out_valid && out_ready && out_last)begin state<=IDLE;done<=1;end
    default:state<=IDLE;
   endcase
  end
 end
endmodule

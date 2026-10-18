// Two unchanged step005 FC engines. Fused mode forwards quantized hidden
// activations into FC2's input RAM; host mode requires explicit host replay.
module mlp2_top (
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
    output wire hidden_saturated,hidden_tie,
    output wire out_valid,
    input wire out_ready,
    output wire [2:0] out_index,
    output wire out_last,
    output wire signed [7:0] out_data,
    output wire out_saturated,out_tie,
    output wire busy,
    output reg done,cfg_error
);
    localparam IDLE=0,START1=1,RUN1=2,WAIT_HOST=3,START2=4,RUN2=5;
    reg [2:0] state;
    reg [8:0] k;
    reg [3:0] h,o,written;
    reg [15:0] mult1,mult2;
    reg [5:0] shift1,shift2;
    reg fused;
    wire ready1,ready2,host_ready1,host_ready2;
    wire fc1_valid,fc2_valid,fc1_last,fc2_last;
    wire [2:0] fc1_index,fc2_index;
    wire signed [32:0] fc1_data,fc2_data;
    wire signed [32:0] unused_pre1,unused_pre2;
    wire signed [23:0] unused_dot1,unused_dot2;
    wire unused_busy1,unused_busy2,unused_done1,unused_done2,error1,error2;
    wire q1_ready,q2_ready,q1_valid,q2_valid,q1_error,q2_error;
    wire signed [7:0] q1_data,q2_data;
    wire q1_sat,q2_sat,q1_tie,q2_tie;
    reg [2:0] hidden_index_q,output_index_q;
    reg hidden_last_q,output_last_q;
    assign busy=(state!=IDLE);
    assign start_ready=!busy;
    wire start1=!reset && state==START1;
    wire start2=!reset && state==START2;
    wire initial_host=!reset && state==IDLE && !start;
    wire replay_host=!reset && state==WAIT_HOST && !fused && !bridge_done && host_layer && host_kind==0 && host_addr==written && written<h;
    wire internal_hidden=!reset && state==RUN1 && fused;
    wire hidden_accept_ready=(state==RUN1) && (fused ? host_ready2 : hidden_ready);
    assign hidden_valid=q1_valid && state==RUN1;
    assign hidden_commit=hidden_valid && hidden_accept_ready && !reset;
    assign hidden_index=hidden_index_q;
    assign hidden_data=q1_data;
    assign hidden_saturated=q1_sat;assign hidden_tie=q1_tie;
    wire host1_we=host_we && initial_host && !host_layer;
    wire host2_we=(internal_hidden && q1_valid) || (host_we && ((initial_host && host_layer) || replay_host));
    wire [1:0] host2_kind=internal_hidden ? 2'd0 : host_kind;
    wire [10:0] host2_addr=internal_hidden ? {8'd0,hidden_index_q} : host_addr;
    wire signed [31:0] host2_data=internal_hidden ? {{24{q1_data[7]}},q1_data} : host_data;
    assign host_ready=initial_host ? (host_layer ? host_ready2 : host_ready1) :
                      (replay_host ? host_ready2 : 1'b0);
    fc_int8_top fc1(
        .clk(clk),.reset(reset),.start(start1),.start_ready(ready1),.k_cfg(k),.m_cfg(h),.relu_cfg(1'b1),
        .fetch_enable(fetch_enable),.host_we(host1_we),.host_kind(host_kind),.host_addr(host_addr),.host_data(host_data),
        .host_ready(host_ready1),.busy(unused_busy1),.out_valid(fc1_valid),.out_ready(q1_ready && state==RUN1),
        .out_index(fc1_index),.out_last(fc1_last),.out_dot(unused_dot1),.out_pre(unused_pre1),.out_data(fc1_data),
        .done(unused_done1),.cfg_error(error1));
    fc_int8_top fc2(
        .clk(clk),.reset(reset),.start(start2),.start_ready(ready2),.k_cfg({5'd0,h}),.m_cfg(o),.relu_cfg(1'b0),
        .fetch_enable(fetch_enable),.host_we(host2_we),.host_kind(host2_kind),.host_addr(host2_addr),.host_data(host2_data),
        .host_ready(host_ready2),.busy(unused_busy2),.out_valid(fc2_valid),.out_ready(q2_ready && state==RUN2),
        .out_index(fc2_index),.out_last(fc2_last),.out_dot(unused_dot2),.out_pre(unused_pre2),.out_data(fc2_data),
        .done(unused_done2),.cfg_error(error2));
    requant_i8 q1(clk,reset,fc1_valid && state==RUN1,q1_ready,fc1_data,mult1,shift1,
        q1_valid,hidden_accept_ready,q1_data,q1_sat,q1_tie,q1_error);
    requant_i8 q2(clk,reset,fc2_valid && state==RUN2,q2_ready,fc2_data,mult2,shift2,
        q2_valid,out_ready && state==RUN2,q2_data,q2_sat,q2_tie,q2_error);
    assign out_valid=q2_valid && state==RUN2;
    assign out_data=q2_data;assign out_index=output_index_q;assign out_last=output_last_q;
    assign out_saturated=q2_sat;assign out_tie=q2_tie;
    always @(posedge clk) begin
        if(reset) begin
            state<=IDLE;k<=0;h<=0;o<=0;written<=0;mult1<=0;mult2<=0;shift1<=0;shift2<=0;fused<=0;
            done<=0;cfg_error<=0;hidden_index_q<=0;output_index_q<=0;hidden_last_q<=0;output_last_q<=0;
        end else begin
            done<=0;cfg_error<=0;
            if(fc1_valid && q1_ready && state==RUN1) begin hidden_index_q<=fc1_index;hidden_last_q<=fc1_last;end
            if(fc2_valid && q2_ready && state==RUN2) begin output_index_q<=fc2_index;output_last_q<=fc2_last;end
            case(state)
                IDLE:if(start) begin
                    if(k_cfg>=1 && k_cfg<=256 && h_cfg>=1 && h_cfg<=8 && o_cfg>=1 && o_cfg<=8 &&
                       mult1_cfg!=0 && mult2_cfg!=0 && shift1_cfg<=47 && shift2_cfg<=47) begin
                        k<=k_cfg;h<=h_cfg;o<=o_cfg;mult1<=mult1_cfg;mult2<=mult2_cfg;
                        shift1<=shift1_cfg;shift2<=shift2_cfg;fused<=fused_cfg;written<=0;state<=START1;
                    end else cfg_error<=1;
                end
                START1:state<=RUN1;
                RUN1:if(hidden_commit && hidden_last_q) begin
                    written<=0;state<=fused ? START2 : WAIT_HOST;
                end
                WAIT_HOST:begin
                    if(host_we && host_ready) written<=written+1'b1;
                    if(bridge_done && !host_we && written==h) state<=START2;
                end
                START2:state<=RUN2;
                RUN2:if(out_valid && out_ready && out_last) begin state<=IDLE;done<=1;end
                default:state<=IDLE;
            endcase
        end
    end
endmodule

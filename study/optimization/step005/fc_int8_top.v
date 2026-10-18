// INT8 FC layer: up to 8 output rows, K=1..256, full INT32 bias.
// Four K-parallel MAC lanes are reused across output rows.
module fc_int8_top (
    input wire clk, reset, start,
    output wire start_ready,
    input wire [8:0] k_cfg,
    input wire [3:0] m_cfg,
    input wire relu_cfg, fetch_enable,
    input wire host_we,
    input wire [1:0] host_kind,
    input wire [10:0] host_addr,
    input wire signed [31:0] host_data,
    output wire host_ready,
    output reg busy,
    output reg out_valid,
    input wire out_ready,
    output reg [2:0] out_index,
    output reg out_last,
    output reg signed [23:0] out_dot,
    output reg signed [32:0] out_pre, out_data,
    output reg done, cfg_error
);
    localparam IDLE=0,LAUNCH=1,WAIT_DOT=2,EMIT=3;
    reg [1:0] state;
    reg [8:0] k_latched;
    reg [3:0] m_latched;
    reg relu_latched;
    reg [2:0] channel;
    reg signed [31:0] biases[0:7];
    reg signed [31:0] bias_latched;
    wire host_legal=(host_kind==0 && host_addr<256) || host_kind==1 ||
                    (host_kind==2 && host_addr<8);
    assign host_ready=!reset && !busy && !start && host_legal;
    wire host_fire=host_we && host_ready;
    assign start_ready=!busy;
    wire core_start=!reset && state==LAUNCH;
    wire core_start_ready,core_busy,core_out_valid,core_cfg_error;
    wire signed [23:0] core_out;
    wire [3:0] rd_mask;
    wire [7:0] rd_addr;
    wire [5:0] x_rd_addr=rd_addr[5:0];
    wire [8:0] w_rd_addr={channel,rd_addr[5:0]};
    wire [31:0] x_rd_data,w_rd_data;
    wire signed [32:0] dot_extended={{9{core_out[23]}},core_out};
    wire signed [32:0] bias_extended={bias_latched[31],bias_latched};
    wire signed [32:0] biased=dot_extended+bias_extended;
    genvar lane;
    generate for(lane=0;lane<4;lane=lane+1) begin: bank
        wire write_lane=(host_addr[1:0]==lane);
        wire x_wr=host_fire && host_kind==0 && write_lane;
        wire w_wr=host_fire && host_kind==1 && write_lane;
        bank_ram #(.DEPTH(64),.ADDR_BITS(6)) x_ram(
            clk,x_wr,host_addr[7:2],host_data[7:0],rd_mask[lane],x_rd_addr,x_rd_data[lane*8+:8]);
        bank_ram #(.DEPTH(512),.ADDR_BITS(9)) w_ram(
            clk,w_wr,host_addr[10:2],host_data[7:0],rd_mask[lane],w_rd_addr,w_rd_data[lane*8+:8]);
    end endgenerate
    always @(posedge clk)
        if(host_fire && host_kind==2) biases[host_addr[2:0]]<=host_data;

    dot_banked_core #(.LANES(4)) core(
        .clk(clk),.reset(reset),.start(core_start),.start_ready(core_start_ready),
        .k_cfg(k_latched),.fetch_enable(fetch_enable),.rd_en(rd_mask),.rd_addr(rd_addr),
        .x_rd_data(x_rd_data),.w_rd_data(w_rd_data),.busy(core_busy),.out_data(core_out),
        .out_valid(core_out_valid),.cfg_error(core_cfg_error));
    always @(posedge clk) begin
        if(reset) begin
            state<=IDLE;busy<=0;k_latched<=0;m_latched<=0;relu_latched<=0;
            channel<=0;bias_latched<=0;out_valid<=0;out_index<=0;out_last<=0;
            out_dot<=0;out_pre<=0;out_data<=0;done<=0;cfg_error<=0;
        end else begin
            done<=0;cfg_error<=0;
            case(state)
                IDLE: if(start && start_ready) begin
                    if(k_cfg>=1 && k_cfg<=256 && m_cfg>=1 && m_cfg<=8) begin
                        k_latched<=k_cfg;m_latched<=m_cfg;relu_latched<=relu_cfg;
                        channel<=0;busy<=1;out_valid<=0;state<=LAUNCH;
                    end else cfg_error<=1;
                end
                LAUNCH: begin bias_latched<=biases[channel];state<=WAIT_DOT;end
                WAIT_DOT: if(core_out_valid) begin
                    out_dot<=core_out;out_pre<=biased;
                    out_data<=(relu_latched && biased[32]) ? 33'sd0 : biased;
                    out_index<=channel;out_last<=({1'b0,channel}==m_latched-1'b1);
                    out_valid<=1;state<=EMIT;
                end
                EMIT: if(out_valid && out_ready) begin
                    out_valid<=0;
                    if(out_last) begin busy<=0;done<=1;state<=IDLE;end
                    else begin channel<=channel+1'b1;state<=LAUNCH;end
                end
                default: begin state<=IDLE;busy<=0;out_valid<=0;end
            endcase
        end
    end
endmodule

module dot_banked_top #(parameter integer LANES=4)(
    input wire clk, reset, start,
    output wire start_ready,
    input wire [8:0] k_cfg,
    input wire fetch_enable,
    input wire host_we,
    output wire host_ready,
    input wire [7:0] host_addr,
    input wire signed [7:0] host_x,host_w,
    output wire busy,
    output wire signed [23:0] out_data,
    output wire out_valid,cfg_error
);
    localparam integer ADDR_BITS=8-$clog2(LANES);
    wire [LANES-1:0] rd_en;
    wire [7:0] rd_addr;
    wire [LANES*8-1:0] x_rd_data,w_rd_data;
    wire host_fire=host_we && host_ready;
    assign host_ready=!busy && !start && !reset;
    genvar b;
    generate for(b=0;b<LANES;b=b+1) begin: bank
        wire wr=host_fire && ((host_addr%LANES)==b);
        wire [ADDR_BITS-1:0] wa=host_addr/LANES;
        wire [ADDR_BITS-1:0] ra=rd_addr[ADDR_BITS-1:0];
        bank_ram #(.DEPTH(256/LANES),.ADDR_BITS(ADDR_BITS)) x_ram(
            clk,wr,wa,host_x,rd_en[b],ra,x_rd_data[b*8+:8]);
        bank_ram #(.DEPTH(256/LANES),.ADDR_BITS(ADDR_BITS)) w_ram(
            clk,wr,wa,host_w,rd_en[b],ra,w_rd_data[b*8+:8]);
    end endgenerate
    dot_banked_core #(.LANES(LANES)) core(
        .clk(clk),.reset(reset),.start(start),.start_ready(start_ready),.k_cfg(k_cfg),
        .fetch_enable(fetch_enable),.rd_en(rd_en),.rd_addr(rd_addr),
        .x_rd_data(x_rd_data),.w_rd_data(w_rd_data),.busy(busy),
        .out_data(out_data),.out_valid(out_valid),.cfg_error(cfg_error));
endmodule

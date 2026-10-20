// Demonstration wrapper: two 256x8 synchronous RAMs and one MAC pipeline.
// Host writes are accepted only while idle, with start=0 and reset=0.
module dot_mem_top (
    input wire clk, reset, start,
    output wire start_ready,
    input wire [8:0] k_cfg,
    input wire fetch_enable,
    input wire host_we,
    output wire host_ready,
    input wire [7:0] host_addr,
    input wire signed [7:0] host_x, host_w,
    output wire busy,
    output wire signed [23:0] out_data,
    output wire out_valid, cfg_error
);
    wire x_rd_en,w_rd_en;
    wire [7:0] x_rd_addr,w_rd_addr;
    wire signed [7:0] x_rd_data,w_rd_data;
    wire host_fire = host_we && host_ready;
    assign host_ready = !busy && !start && !reset;
    sync_byte_ram x_ram(clk,host_fire,host_addr,host_x,x_rd_en,x_rd_addr,x_rd_data);
    sync_byte_ram w_ram(clk,host_fire,host_addr,host_w,w_rd_en,w_rd_addr,w_rd_data);
    dot_serial_mem core(
        .clk(clk), .reset(reset), .start(start), .start_ready(start_ready),
        .k_cfg(k_cfg), .fetch_enable(fetch_enable),
        .x_rd_en(x_rd_en), .w_rd_en(w_rd_en),
        .x_rd_addr(x_rd_addr), .w_rd_addr(w_rd_addr),
        .x_rd_data(x_rd_data), .w_rd_data(w_rd_data),
        .busy(busy), .out_data(out_data), .out_valid(out_valid), .cfg_error(cfg_error)
    );
endmodule

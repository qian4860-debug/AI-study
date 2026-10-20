// Fixed one-cycle synchronous read response; no response backpressure.
// Pipeline: read request -> RAM response/tag -> registered product/tag -> sum.
module dot_serial_mem (
    input wire clk, reset,
    input wire start,
    output wire start_ready,
    input wire [8:0] k_cfg,
    input wire fetch_enable,
    output wire x_rd_en, w_rd_en,
    output wire [7:0] x_rd_addr, w_rd_addr,
    input wire signed [7:0] x_rd_data, w_rd_data,
    output reg busy,
    output reg signed [23:0] out_data,
    output reg out_valid, cfg_error
);
    reg [8:0] k_latched;
    reg [8:0] issued_count, retired_count;
    reg rsp_valid, rsp_last, mul_valid, mul_last;
    reg signed [15:0] product_reg;
    reg signed [23:0] acc;
    wire read_fire = !reset && busy && fetch_enable && (issued_count < k_latched);
    wire [8:0] issued_next = issued_count + 9'd1;
    wire signed [15:0] ram_product = x_rd_data * w_rd_data;
    wire signed [23:0] product_extended = {{8{product_reg[15]}}, product_reg};
    wire signed [23:0] sum_next = acc + product_extended;

    assign start_ready = !busy;
    assign x_rd_en = read_fire;
    assign w_rd_en = read_fire;
    assign x_rd_addr = issued_count[7:0];
    assign w_rd_addr = issued_count[7:0];

    always @(posedge clk) begin
        if (reset) begin
            busy <= 0; out_valid <= 0; cfg_error <= 0; out_data <= 0;
            k_latched <= 0; issued_count <= 0; retired_count <= 0; acc <= 0;
            rsp_valid <= 0; rsp_last <= 0; mul_valid <= 0; mul_last <= 0;
            product_reg <= 0;
        end else begin
            out_valid <= 0;
            cfg_error <= 0;
            // Stopping requests never stops the two already-issued stages.
            rsp_valid <= read_fire;
            rsp_last <= read_fire && (issued_next == k_latched);
            mul_valid <= rsp_valid;
            mul_last <= rsp_valid && rsp_last;
            if (rsp_valid) product_reg <= ram_product;
            if (read_fire) issued_count <= issued_next;
            if (mul_valid) begin
                retired_count <= retired_count + 9'd1;
                if (mul_last) begin
                    out_data <= sum_next;
                    out_valid <= 1;
                    busy <= 0;
                    acc <= 0;
                end else acc <= sum_next;
            end
            if (start && start_ready) begin
                if (k_cfg >= 9'd1 && k_cfg <= 9'd256) begin
                    busy <= 1;
                    k_latched <= k_cfg;
                    issued_count <= 0; retired_count <= 0; acc <= 0;
                    rsp_valid <= 0; rsp_last <= 0; mul_valid <= 0; mul_last <= 0;
                end else cfg_error <= 1;
            end
        end
    end
endmodule

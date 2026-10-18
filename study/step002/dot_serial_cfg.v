// Step 002: configurable signed INT8 dot product, exact signed 24-bit sum.
// State is IDLE (!busy) or RUN (busy). Reset is synchronous, active high.
module dot_serial_cfg (
    input wire clk,
    input wire reset,
    input wire start,
    output wire start_ready,
    input wire [8:0] k_cfg,
    input wire in_valid,
    output wire in_ready,
    input wire signed [7:0] x,
    input wire signed [7:0] w,
    output reg busy,
    output reg signed [23:0] out_data,
    output reg out_valid,
    output reg cfg_error
);
    reg [8:0] k_latched;
    reg [8:0] accepted_count;
    reg signed [23:0] acc;
    wire start_fire = start && start_ready;
    wire data_fire = in_valid && in_ready;
    wire signed [15:0] product = x * w;
    wire signed [23:0] product_extended = {{8{product[15]}}, product};
    wire signed [23:0] sum_next = acc + product_extended;
    wire [8:0] accepted_next = accepted_count + 9'd1;

    assign start_ready = !busy;
    assign in_ready = busy;

    always @(posedge clk) begin
        if (reset) begin
            busy <= 1'b0;
            k_latched <= 9'd0;
            accepted_count <= 9'd0;
            acc <= 24'sd0;
            out_data <= 24'sd0;
            out_valid <= 1'b0;
            cfg_error <= 1'b0;
        end else begin
            out_valid <= 1'b0;
            cfg_error <= 1'b0;
            if (start_fire) begin
                if (k_cfg >= 9'd1 && k_cfg <= 9'd256) begin
                    k_latched <= k_cfg;
                    accepted_count <= 9'd0;
                    acc <= 24'sd0;
                    busy <= 1'b1;
                end else begin
                    cfg_error <= 1'b1;
                end
            end else if (data_fire) begin
                if (accepted_next == k_latched) begin
                    out_data <= sum_next;
                    out_valid <= 1'b1;
                    busy <= 1'b0;
                    acc <= 24'sd0;
                    accepted_count <= 9'd0;
                end else begin
                    acc <= sum_next;
                    accepted_count <= accepted_next;
                end
            end
        end
    end
endmodule

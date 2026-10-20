// One product per enabled edge. first replaces the previous partial sum.
module mac_pe #(parameter W=8, parameter ACC=32)(
    input wire clk, rst_n, valid, first, last,
    input wire signed [W-1:0] a, b,
    output reg signed [ACC-1:0] sum,
    output reg done
);
    wire signed [2*W-1:0] product = a * b;
    wire signed [ACC-1:0] extended_product = product;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin sum <= 0; done <= 0; end
        else begin
            done <= valid && last;
            if (valid) sum <= first ? extended_product : sum + extended_product;
        end
    end
endmodule

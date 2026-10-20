// Symmetric integer requantization: sat_i8(RNE(value * mult / 2**shift)).
// One elastic output register. Legal configuration: mult=1..65535, shift=0..47.
module requant_i8 (
    input wire clk,reset,in_valid,
    output wire in_ready,
    input wire signed [32:0] in_value,
    input wire [15:0] multiplier,
    input wire [5:0] shift,
    output reg out_valid,
    input wire out_ready,
    output reg signed [7:0] out_data,
    output reg out_saturated,out_tie,
    output reg cfg_error
);
    wire signed [16:0] positive_multiplier={1'b0,multiplier};
    wire signed [49:0] product=in_value*positive_multiplier;
    reg [49:0] magnitude,base,remainder,half,mask,rounded_magnitude;
    reg signed [50:0] rounded;
    reg signed [7:0] result;
    reg saturated,tie,increment;
    assign in_ready=!reset && (!out_valid || out_ready);
    always @* begin
        magnitude=product[49] ? -product : product;
        base=magnitude >> shift;
        mask=0;half=0;remainder=0;increment=0;tie=0;
        if(shift!=0 && shift<=47) begin
            mask=(50'd1 << shift)-1'b1;
            half=50'd1 << (shift-1'b1);
            remainder=magnitude & mask;
            tie=(remainder==half);
            increment=(remainder>half) || (tie && base[0]);
        end
        rounded_magnitude=base+increment;
        rounded=product[49] ? -$signed({1'b0,rounded_magnitude}) : $signed({1'b0,rounded_magnitude});
        saturated=0;
        if(rounded>51'sd127) begin result=8'sd127;saturated=1;end
        else if(rounded < -51'sd128) begin result=-8'sd128;saturated=1;end
        else result=rounded[7:0];
    end
    always @(posedge clk) begin
        if(reset) begin out_valid<=0;out_data<=0;out_saturated<=0;out_tie<=0;cfg_error<=0;end
        else begin
            cfg_error<=0;
            if(in_ready) begin
                out_valid<=0;
                if(in_valid) begin
                    if(multiplier==0 || shift>47) cfg_error<=1;
                    else begin out_valid<=1;out_data<=result;out_saturated<=saturated;out_tie<=tie;end
                end
            end
        end
    end
endmodule

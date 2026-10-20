// Three elastic register stages: product; magnitude/shift/round decision; INT8 clamp.
// Tag travels through the identical ready/valid pipeline as its numerical payload.
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
 output reg cfg_error,
 input wire [3:0] in_tag,
 output reg [3:0] out_tag
);
 reg p_valid,b_valid;
 reg signed [49:0] product_q;
 reg [5:0] shift_q;
 reg [3:0] p_tag,b_tag;
 reg [7:0] b_low;
 reg b_high,b_increment,b_negative,b_tie;
 wire c_ready=!out_valid || out_ready;
 wire b_ready=!b_valid || c_ready;
 wire p_ready=!p_valid || b_ready;
 assign in_ready=!reset && p_ready;
 wire signed [16:0] positive_multiplier={1'b0,multiplier};
 reg [49:0] magnitude,base,remainder,mask,half;
 reg increment,tie;
 always @* begin
  magnitude=product_q[49] ? -product_q : product_q;
  base=magnitude >> shift_q;
  remainder=0;mask=0;half=0;increment=0;tie=0;
  if(shift_q!=0)begin
   mask=(50'd1<<shift_q)-1'b1;half=50'd1<<(shift_q-1'b1);
   remainder=magnitude & mask;tie=(remainder==half);
   increment=(remainder>half) || (tie && base[0]);
  end
 end
 // Clamp by comparing the unrounded magnitude to its sign-specific limit.
 // The only increment and sign restoration needed after this comparison are 8-bit.
 wire [7:0] limit=b_negative ? 8'd128 : 8'd127;
 wire saturation=b_high || b_low>limit || (b_low==limit && b_increment);
 wire [7:0] rounded_low=b_low+b_increment;
 always @(posedge clk)begin
  if(reset)begin
   p_valid<=0;b_valid<=0;out_valid<=0;cfg_error<=0;
   product_q<=0;shift_q<=0;p_tag<=0;b_tag<=0;b_low<=0;b_high<=0;b_increment<=0;b_negative<=0;b_tie<=0;
   out_data<=0;out_saturated<=0;out_tie<=0;out_tag<=0;
  end else begin
   cfg_error<=0;
   if(c_ready)begin
    out_valid<=b_valid;
    if(b_valid)begin
     out_saturated<=saturation;out_tie<=b_tie;out_tag<=b_tag;
     out_data<=saturation ? (b_negative ? -8'sd128 : 8'sd127) : (b_negative ? -rounded_low : rounded_low);
    end
   end
   if(b_ready)begin
    b_valid<=p_valid;
    if(p_valid)begin
     b_low<=base[7:0];b_high<=|base[49:8];b_increment<=increment;
     b_negative<=product_q[49];b_tie<=tie;b_tag<=p_tag;
    end
   end
   if(p_ready)begin
    p_valid<=0;
    if(in_valid)begin
     if(multiplier==0 || shift>47)cfg_error<=1;
     else begin
      p_valid<=1;product_q<=in_value*positive_multiplier;shift_q<=shift;p_tag<=in_tag;
     end
    end
   end
  end
 end
endmodule

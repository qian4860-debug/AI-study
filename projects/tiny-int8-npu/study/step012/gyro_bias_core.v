// Scalar Horner kernel: one shared signed 32x16 multiplier, Q24 rate/Q14 z.
// All coefficients and payload are atomically latched at start acceptance.
module gyro_bias_core(
 input wire clk,reset,start,
 output wire start_ready,
 input wire signed [31:0] c0,c1,c2,raw,
 input wire signed [15:0] z,
 input wire [31:0] tag,
 output reg busy,out_valid,
 input wire out_ready,
 output reg signed [31:0] out_bias,out_corrected,
 output reg out_saturated,
 output reg [31:0] out_tag
);
 localparam IDLE=0,MUL1=1,ADD1=2,MUL2=3,ADD2=4,EMIT=5;
 reg [2:0] state;
 reg signed [31:0] a0,a1,raw_q,acc;
 reg signed [15:0] z_q;
 reg signed [47:0] product;
 reg [31:0] tag_q;
 reg sticky;
 wire signed [47:0] multiply_result=acc*z_q;
 function signed [63:0] rne14;
  input signed [63:0] value;
  reg [63:0] mag,base,rem;
  begin
   mag=value<0 ? -value : value;
   base=mag>>14;rem=mag & 64'd16383;
   if(rem>64'd8192 || (rem==64'd8192 && base[0]))base=base+1'b1;
   rne14=value<0 ? -$signed(base) : $signed(base);
  end
 endfunction
 function signed [31:0] clip32;
  input signed [63:0] value;
  begin
   if(value>64'sd2147483647)clip32=32'sh7fffffff;
   else if(value< -64'sd2147483648)clip32=32'sh80000000;
   else clip32=value[31:0];
  end
 endfunction
 function overflow32;
  input signed [63:0] value;
  begin overflow32=value>64'sd2147483647 || value< -64'sd2147483648;end
 endfunction
 wire signed [63:0] rounded=rne14({{16{product[47]}},product});
 wire signed [63:0] added1=rounded+{{32{a1[31]}},a1};
 wire signed [63:0] added0=rounded+{{32{a0[31]}},a0};
 wire signed [63:0] difference={{32{raw_q[31]}},raw_q}-{{32{acc[31]}},acc};
 assign start_ready=!reset && !busy && !out_valid;
 always @(posedge clk)begin
  if(reset)begin
   state<=IDLE;busy<=0;out_valid<=0;out_bias<=0;out_corrected<=0;out_saturated<=0;out_tag<=0;
   a0<=0;a1<=0;raw_q<=0;acc<=0;z_q<=0;product<=0;tag_q<=0;sticky<=0;
  end else begin
   if(out_valid && out_ready)out_valid<=0;
   case(state)
    IDLE:if(start && start_ready)begin
     a0<=c0;a1<=c1;raw_q<=raw;acc<=c2;z_q<=z;tag_q<=tag;sticky<=0;busy<=1;state<=MUL1;
    end
    MUL1:begin product<=multiply_result;state<=ADD1;end
    ADD1:begin acc<=clip32(added1);sticky<=sticky|overflow32(added1);state<=MUL2;end
    MUL2:begin product<=multiply_result;state<=ADD2;end
    ADD2:begin acc<=clip32(added0);sticky<=sticky|overflow32(added0);state<=EMIT;end
    EMIT:begin
     out_bias<=acc;out_corrected<=clip32(difference);out_saturated<=sticky|overflow32(difference);
     out_tag<=tag_q;out_valid<=1;busy<=0;state<=IDLE;
    end
    default:begin state<=IDLE;busy<=0;out_valid<=0;end
   endcase
  end
 end
endmodule

`timescale 1ns/1ps
module tb_mac;
reg clk=0; always #5 clk=~clk;
reg rst_n=0, valid=0, first=0, last=0;
reg signed [7:0] a=0,b=0;
wire signed [31:0] sum;
wire done;
integer x,y,i,expected,checks=0;
mac_pe dut(.*);
task check;
 input integer target;
 input integer target_done;
 begin
   @(posedge clk); #1;
   if (sum !== target || done !== target_done[0])
     $fatal(1,"MAC mismatch sum=%0d expected=%0d done=%b",sum,target,done);
   checks=checks+1;
 end
endtask
initial begin
 #1; rst_n=1; #1; rst_n=0; #1;
 if (sum !== 0 || done !== 0) $fatal(1,"async reset");
 @(negedge clk); rst_n=1;
 // Every signed INT8 operand pair, independent of the Python oracle.
 for(x=-128;x<128;x=x+1) for(y=-128;y<128;y=y+1) begin
   @(negedge clk); a=x; b=y; valid=1; first=1; last=1;
   check(x*y,1);
 end
 expected=0;
 for(i=0;i<254;i=i+1) begin
   @(negedge clk); valid=1; first=(i==0); last=(i==253); a=-128;b=-128;
   expected=expected+16384; check(expected,i==253);
   @(negedge clk); valid=0; first=1; last=1; a=127; b=-128;
   check(expected,0);
 end
 @(negedge clk); valid=0;
 #2; rst_n=0; #1;
 if(sum !== 0 || done !== 0) $fatal(1,"mid accumulation async reset");
 @(negedge clk); rst_n=1; valid=1; first=1; last=1; a=-3;b=7;
 check(-21,1);
 $display("PASS MAC checks=%0d",checks); $finish;
end
endmodule

`timescale 1ns/1ps
module tb_requant;
 reg clk=0;always #5 clk=~clk;
 reg reset=1,in_valid=0,out_ready=0;
 reg signed [32:0] in_value=0;
 reg [15:0] multiplier=0;reg [5:0] shift=0;
 wire in_ready,out_valid,out_saturated,out_tie,cfg_error;
 wire signed [7:0] out_data;
 requant_i8 dut(.*);
 integer fd,scan,rr,iv,rd,m,s,ev,ed,es,et,ee,er,c=0;
 reg signed [32:0] value;
 initial begin
  fd=$fopen("quant_stimulus.txt","r");if(!fd)$fatal(1,"missing quant stimulus");
  while(!$feof(fd)) begin
   scan=$fscanf(fd,"%d %d %d %d %d %d %d %d %d %d %d %d\n",rr,iv,rd,value,m,s,er,ev,ed,es,et,ee);
   if(scan!=12)$fatal(1,"bad quant vector");
   @(negedge clk);reset=rr;in_valid=iv;out_ready=rd;in_value=value;multiplier=m;shift=s;
   #1;if(in_ready!==er[0])$fatal(1,"quant ready cycle=%0d",c);
   @(posedge clk);#1;c=c+1;
   if(out_valid!==ev[0] || $signed(out_data)!==ed || out_saturated!==es[0] || out_tie!==et[0] || cfg_error!==ee[0])
    $fatal(1,"quant cycle=%0d got=%0d/%0d/%0d/%0d/%0d want=%0d/%0d/%0d/%0d/%0d",c,out_valid,$signed(out_data),out_saturated,out_tie,cfg_error,ev,ed,es,et,ee);
  end
  $display("PASS QUANT cycles=%0d",c);$finish;
 end
endmodule

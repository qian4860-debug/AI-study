`timescale 1ns/1ps
module tb_quant_pipeline;
 reg clk=0;always #5 clk=~clk;
 reg reset=1,in_valid=0,out_ready=0;
 reg signed [32:0] in_value=0;reg [15:0] multiplier=0;reg [5:0] shift=0;reg [3:0] in_tag=0;
 wire in_ready,out_valid,out_saturated,out_tie,cfg_error;wire signed [7:0] out_data;wire [3:0] out_tag;
 requant_i8 dut(.*);
 integer fd,scan,rr,iv,rd,m,s,tag,ev,ed,es,et,ee,er,etag,c=0;reg signed [32:0] value;
 initial begin
  fd=$fopen("quant_pipeline_stimulus.txt","r");if(!fd)$fatal(1,"missing pipeline stimulus");
  while(!$feof(fd))begin
   scan=$fscanf(fd,"%d %d %d %d %d %d %d %d %d %d %d %d %d %d\n",rr,iv,rd,value,m,s,tag,er,ev,ed,es,et,ee,etag);
   if(scan!=14)$fatal(1,"bad pipeline vector");
   @(negedge clk);reset=rr;in_valid=iv;out_ready=rd;in_value=value;multiplier=m;shift=s;in_tag=tag;
   #1;if(in_ready!==er[0])$fatal(1,"pipeline ready cycle=%0d",c);
   @(posedge clk);#1;c=c+1;
   if(out_valid!==ev[0] || $signed(out_data)!==ed || out_saturated!==es[0] || out_tie!==et[0] || cfg_error!==ee[0] || out_tag!==etag[3:0])$fatal(1,"pipeline cycle=%0d",c);
  end
  $display("PASS QUANT_PIPELINE cycles=%0d",c);$finish;
 end
endmodule

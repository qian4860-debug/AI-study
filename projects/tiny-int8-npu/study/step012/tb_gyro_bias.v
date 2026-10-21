`timescale 1ns/1ps
module tb_gyro_bias;
 reg clk=0;always #5 clk=~clk;
 reg reset=1,start=0,out_ready=0;
 reg signed [31:0] c0=0,c1=0,c2=0,raw=0;
 reg signed [15:0] z=0;
 reg [31:0] tag=0;
 wire start_ready,busy,out_valid,out_saturated;
 wire signed [31:0] out_bias,out_corrected;
 wire [31:0] out_tag;
 gyro_bias_core dut(.*);
 integer fd,ef,scan,tid,expected_bias,expected_corrected,expected_saturated,completed=0;
 integer g0,g1,g2,gz,gr,cycles,stall,j,stage,aborted=0;
 reg signed [31:0] held_bias,held_corrected;
 reg held_sat;
 reg [31:0] held_tag;
 task tick;
 begin @(posedge clk);#1;@(negedge clk);end
 endtask
 task drive_vector;
 begin c0=g0;c1=g1;c2=g2;z=gz;raw=gr;tag=tid;end
 endtask
 initial begin
  fd=$fopen("vectors.txt","r");ef=$fopen("rtl_events.csv","w");
  if(!fd || !ef)$fatal(1,"missing vectors/events");
  $fdisplay(ef,"tag,bias,corrected,saturated,compute_cycles,stall_cycles");
  tick();reset=0;tick();
  while(!$feof(fd))begin
   scan=$fscanf(fd,"%d %d %d %d %d %d %d %d %d\n",tid,g0,g1,g2,gz,gr,expected_bias,expected_corrected,expected_saturated);
   if(scan!=9)$fatal(1,"bad vector");
   drive_vector();if(!start_ready)$fatal(1,"not ready");start=1;tick();start=0;cycles=0;
   while(!out_valid)begin
    if(!busy || start_ready)$fatal(1,"busy protocol");
    // Attempted starts and changes during busy must not alter latched inputs/tag.
    start=1;c0=32'h80000000;c1=32'h7fffffff;c2=123;z=-7;raw=456;tag=32'hffffffff;
    tick();cycles=cycles+1;
    if(cycles>8)$fatal(1,"watchdog");
   end
   start=0;
   if(cycles!=5 || busy || start_ready)$fatal(1,"compute/ready contract");
   if(out_tag!==tid || out_bias!==expected_bias || out_corrected!==expected_corrected || out_saturated!==expected_saturated[0])
    $fatal(1,"numeric mismatch tag=%0d bias=%0d/%0d corrected=%0d/%0d sat=%0d/%0d",tid,out_bias,expected_bias,out_corrected,expected_corrected,out_saturated,expected_saturated);
   held_bias=out_bias;held_corrected=out_corrected;held_sat=out_saturated;held_tag=out_tag;
   stall=tid%4;
   for(j=0;j<stall;j=j+1)begin
    start=1;tick();
    if(!out_valid || start_ready || out_bias!==held_bias || out_corrected!==held_corrected || out_saturated!==held_sat || out_tag!==held_tag)$fatal(1,"stall unstable");
   end
   start=0;$fdisplay(ef,"%0d,%0d,%0d,%0d,%0d,%0d",tid,out_bias,out_corrected,out_saturated,cycles,stall);
   out_ready=1;tick();out_ready=0;if(out_valid || !start_ready)$fatal(1,"consume contract");
   completed=completed+1;
  end
  // Reset at every in-flight stage and while holding an unconsumed output.
  for(stage=0;stage<=5;stage=stage+1)begin
   g0=100;g1=-200;g2=300;gz=8192;gr=400;tid=200000+stage;
   drive_vector();start=1;tick();start=0;
   for(j=0;j<stage;j=j+1)tick();
   reset=1;tick();if(busy || out_valid || start_ready)$fatal(1,"reset cancel");
   reset=0;tick();
   for(j=0;j<7;j=j+1)begin tick();if(out_valid || busy)$fatal(1,"cancelled output leaked");end
   // Restart verifies the datapath after cancellation, independently hand-calculated.
   drive_vector();start=1;tick();start=0;
   for(j=0;j<5;j=j+1)tick();
   if(!out_valid || out_bias!==32'sd75 || out_corrected!==32'sd325 || out_tag!==tid || out_saturated)$fatal(1,"restart failed");
   out_ready=1;tick();out_ready=0;aborted=aborted+1;
  end
  $display("PASS GYRO completed=%0d reset_scenarios=%0d latency=5",completed,aborted);
  $fclose(fd);$fclose(ef);$finish;
 end
endmodule

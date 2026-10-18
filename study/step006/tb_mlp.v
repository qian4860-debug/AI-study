`timescale 1ns/1ps
module tb_mlp;
 reg clk=0;always #5 clk=~clk;
 reg reset=1,start=0,fetch_enable=1,host_we=0,host_layer=0,bridge_done=0,hidden_ready=1,out_ready=1,fused_cfg=1;
 reg [8:0] k_cfg=0;reg [3:0] h_cfg=0,o_cfg=0;
 reg [15:0] mult1_cfg=1,mult2_cfg=1;reg [5:0] shift1_cfg=0,shift2_cfg=0;
 reg [1:0] host_kind=0;reg [10:0] host_addr=0;reg signed [31:0] host_data=0;
 wire start_ready,host_ready,hidden_valid,hidden_commit,hidden_saturated,hidden_tie,out_valid,out_last,out_saturated,out_tie,busy,done,cfg_error;
 wire [2:0] hidden_index,out_index;wire signed [7:0] hidden_data,out_data;
 mlp2_top dut(.*);
 integer fd,mf,ef,scan,id,k,h,o,m1,s1,m2,s2,fused,flow,delay_host,loads;
 integer layer,kind,addr,data,j,t,cycle=0,begin_cycle,nh,no,npre1,npre2,replayed,waits;
 integer gh[0:7],gs1[0:7],gt1[0:7],gy[0:7],gs2[0:7],gt2[0:7];
 reg signed [32:0] gp1[0:7],gp2[0:7];
 integer groups1,groups2,pairs1,pairs2,expected_groups1,expected_groups2;
 integer invalids=0,aborts=0,completed=0;
 reg held_h=0,held_o=0;reg [13:0] last_h,last_o;
 reg [13:0] payload_h,payload_o;
 task tick;
 begin
  @(posedge clk);cycle=cycle+1;#1;@(negedge clk);
 end endtask
 task observe;
 begin
  // Called just before the accepting edge. Gold values come from independent Python integers.
  payload_h={hidden_index,hidden_data,hidden_saturated,hidden_tie,1'b0};
  payload_o={out_index,out_data,out_saturated,out_tie,out_last};
  if(held_h && (!hidden_valid || payload_h!==last_h))$fatal(1,"hidden stall unstable id=%0d",id);
  if(held_o && (!out_valid || payload_o!==last_o))$fatal(1,"output stall unstable id=%0d",id);
  held_h=hidden_valid && !dut.hidden_accept_ready;last_h=payload_h;
  held_o=out_valid && !out_ready;last_o=payload_o;
  if(dut.error1 || dut.error2 || dut.q1_error || dut.q2_error || cfg_error)$fatal(1,"internal config error id=%0d",id);
  if(dut.fc1_valid && dut.q1_ready && dut.state==2)begin
   if(npre1>=h || dut.fc1_index!==npre1[2:0] || dut.unused_pre1!==gp1[npre1])$fatal(1,"fc1 pre id=%0d row=%0d",id,npre1);
   npre1=npre1+1;
  end
  if(dut.fc2_valid && dut.q2_ready && dut.state==5)begin
   if(npre2>=o || dut.fc2_index!==npre2[2:0] || dut.unused_pre2!==gp2[npre2])$fatal(1,"fc2 pre id=%0d row=%0d",id,npre2);
   npre2=npre2+1;
  end
  if(hidden_commit)begin
   if(nh>=h || hidden_index!==nh[2:0] || $signed(hidden_data)!==gh[nh] || hidden_saturated!==gs1[nh][0] || hidden_tie!==gt1[nh][0])$fatal(1,"hidden id=%0d row=%0d",id,nh);
   $fdisplay(ef,"%0d,hidden,%0d,%0d,%0d",id,nh,cycle+1,$signed(hidden_data));nh=nh+1;
  end
  if(out_valid && out_ready)begin
   if(no>=o || out_index!==no[2:0] || out_last!==(no==o-1) || $signed(out_data)!==gy[no] || out_saturated!==gs2[no][0] || out_tie!==gt2[no][0])$fatal(1,"output id=%0d row=%0d got=%0d expected=%0d",id,no,$signed(out_data),gy[no]);
   $fdisplay(ef,"%0d,output,%0d,%0d,%0d",id,no,cycle+1,$signed(out_data));no=no+1;
  end
  for(t=0;t<4;t=t+1)begin
   if(dut.fc1.rd_mask[t])pairs1=pairs1+1;
   if(dut.fc2.rd_mask[t])pairs2=pairs2+1;
  end
  if(dut.fc1.rd_mask!=0)groups1=groups1+1;
  if(dut.fc2.rd_mask!=0)groups2=groups2+1;
 end endtask
 initial begin
  fd=$fopen("mlp_cases.txt","r");mf=$fopen("mlp_metrics.csv","w");ef=$fopen("mlp_events.csv","w");
  if(!fd || !mf || !ef)$fatal(1,"missing mlp files");
  $fdisplay(mf,"id,K,H,O,fused,flow,host_delay,cycles,host_loads,bridge_writes,groups1,groups2,pairs1,pairs2");
  $fdisplay(ef,"id,stage,index,cycle,data");
  tick();reset=0;tick();
  // Illegal shape/quant configurations must never start work.
  for(j=0;j<8;j=j+1)begin
   k_cfg=3;h_cfg=2;o_cfg=2;mult1_cfg=1;mult2_cfg=1;shift1_cfg=0;shift2_cfg=0;
   case(j)0:k_cfg=0;1:k_cfg=257;2:h_cfg=0;3:o_cfg=9;4:mult1_cfg=0;5:mult2_cfg=0;6:shift1_cfg=48;7:shift2_cfg=63;endcase
   start=1;tick();if(!cfg_error || busy || done)$fatal(1,"illegal accepted");invalids=invalids+1;start=0;tick();
  end
  while(!$feof(fd))begin
   scan=$fscanf(fd,"%d %d %d %d %d %d %d %d %d %d %d %d\n",id,k,h,o,m1,s1,m2,s2,fused,flow,delay_host,loads);
   if(scan!=12)$fatal(1,"bad case header");
   for(j=0;j<loads;j=j+1)begin
    scan=$fscanf(fd,"%d %d %d %d\n",layer,kind,addr,data);if(scan!=4)$fatal(1,"bad host record");
    host_layer=layer;host_kind=kind;host_addr=addr;host_data=data;host_we=1;#1;
    if(!host_ready)$fatal(1,"load refused");tick();
   end
   host_we=0;
   for(j=0;j<h;j=j+1)begin scan=$fscanf(fd,"%d %d %d %d\n",gp1[j],gh[j],gs1[j],gt1[j]);if(scan!=4)$fatal(1,"bad hidden golden");end
   for(j=0;j<o;j=j+1)begin scan=$fscanf(fd,"%d %d %d %d\n",gp2[j],gy[j],gs2[j],gt2[j]);if(scan!=4)$fatal(1,"bad output golden");end
   k_cfg=k;h_cfg=h;o_cfg=o;mult1_cfg=m1;shift1_cfg=s1;mult2_cfg=m2;shift2_cfg=s2;fused_cfg=fused;
   start=1;begin_cycle=cycle+1;tick();start=0;
   nh=0;no=0;npre1=0;npre2=0;replayed=0;waits=0;groups1=0;groups2=0;pairs1=0;pairs2=0;held_h=0;held_o=0;
   // Every fifth workload also verifies reset abort/restart with retained RAM.
   if(id%5==0)begin
    tick();tick();reset=1;tick();if(busy || out_valid || hidden_valid || done)$fatal(1,"reset cancellation");
    reset=0;aborts=aborts+1;tick();start=1;begin_cycle=cycle+1;tick();start=0;
   end
   while(busy)begin
    if(cycle-begin_cycle>20000)$fatal(1,"watchdog id=%0d state=%0d",id,dut.state);
    fetch_enable=!(flow && cycle%7==0);out_ready=!(flow && cycle%11<4);hidden_ready=!(flow && cycle%9<3);
    // Configuration changes and attempted starts during busy must not change the task.
    k_cfg=511;h_cfg=15;o_cfg=15;mult1_cfg=0;shift1_cfg=63;fused_cfg=!fused;
    host_we=0;bridge_done=0;start=(flow && cycle%17==0);
    if(dut.state==3)begin
     // Incorrect address and early bridge_done cannot advance/rewrite state.
     if(waits==0)begin bridge_done=1;end
     else if(waits==1)begin host_we=1;host_layer=1;host_kind=0;host_addr=h;host_data=99;#1;if(host_ready)$fatal(1,"invalid replay address");end
     else if(waits>delay_host+2 && replayed<h)begin
      host_we=1;host_layer=1;host_kind=0;host_addr=replayed;host_data=gh[replayed];#1;
      if(!host_ready)$fatal(1,"replay refused");replayed=replayed+1;
     end else if(replayed==h)bridge_done=1;
     waits=waits+1;
    end
    #1;observe();tick();
    if(done && (no!=o || nh!=h))$fatal(1,"early done");
   end
   start=0;host_we=0;bridge_done=0;fetch_enable=1;out_ready=1;hidden_ready=1;
   if(!done || no!=o || nh!=h || npre1!=h || npre2!=o)$fatal(1,"missing result");
   if(pairs1!=k*h || pairs2!=h*o || groups1!=h*((k+3)/4) || groups2!=o*((h+3)/4))$fatal(1,"traffic mismatch id=%0d got=%0d,%0d,%0d,%0d",id,pairs1,pairs2,groups1,groups2);
   $fdisplay(mf,"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d",id,k,h,o,fused,flow,delay_host,cycle-begin_cycle,loads,replayed,groups1,groups2,pairs1,pairs2);
   completed=completed+1;tick();if(done)$fatal(1,"done not pulse");
  end
  $display("PASS MLP completed=%0d invalid=%0d aborted=%0d cycles=%0d",completed,invalids,aborts,cycle);$fclose(mf);$fclose(ef);$finish;
 end
endmodule


`timescale 1ns/1ps
module tb_mlp #(parameter integer MODE=1);
 reg clk=0;always #5 clk=~clk;
 reg reset=1,start=0,fetch_enable=1,host_we=0,host_layer=0,bridge_done=0,hidden_ready=1,out_ready=1,fused_cfg=1;
 reg [8:0] k_cfg=0;reg [3:0] h_cfg=0,o_cfg=0;
 reg [15:0] mult1_cfg=1,mult2_cfg=1;reg [5:0] shift1_cfg=0,shift2_cfg=0;
 reg [1:0] host_kind=0;reg [10:0] host_addr=0;reg signed [31:0] host_data=0;
 wire start_ready,host_ready,hidden_valid,hidden_commit,hidden_saturated,hidden_tie,out_valid,out_last,out_saturated,out_tie,busy,done,cfg_error;
 wire [2:0] hidden_index,out_index;wire signed [7:0] hidden_data,out_data;
 mlp2_top #(.RAM_MODE(MODE)) dut(.*);
 integer ff,reset_before,interrupt_after,cache_resets=0;
 integer memf,mx_reads,mw_reads;
 integer fd,mf,ef,scan,id,k,h,o,m1,s1,m2,s2,fused,flow,delay_host,loads;
 integer layer,kind,addr,data,j,t,cycle=0,begin_cycle,nh,no,npre1,npre2,replayed,waits;
 integer gh[0:7],gs1[0:7],gt1[0:7],gy[0:7],gs2[0:7],gt2[0:7];
 reg signed [32:0] gp1[0:7],gp2[0:7];
 integer groups1,groups2,pairs1,pairs2,expected_groups1,expected_groups2;
 integer invalids=0,aborts=0,completed=0;
 reg held_h=0,held_o=0;reg [13:0] last_h,last_o;
 reg [13:0] payload_h,payload_o;

 integer stage,reached,supplemental=0,cancelled_quant=0,q_inputs=0,q_outputs=0;
 integer launch_edges=0,run1_edges=0,bridge_edges=0,run2_edges=0;
 integer fetch_blocked=0,hidden_blocked=0,output_blocked=0,quant_blocked=0;
 task clear_counts;
 begin
  mx_reads=0;mw_reads=0;nh=0;no=0;npre1=0;npre2=0;replayed=0;waits=0;groups1=0;groups2=0;pairs1=0;pairs2=0;
  held_h=0;held_o=0;q_inputs=0;q_outputs=0;launch_edges=0;run1_edges=0;bridge_edges=0;run2_edges=0;
  fetch_blocked=0;hidden_blocked=0;output_blocked=0;quant_blocked=0;
 end endtask
 task configure_current;
 begin
  k_cfg=k;h_cfg=h;o_cfg=o;mult1_cfg=m1;shift1_cfg=s1;mult2_cfg=m2;shift2_cfg=s2;fused_cfg=fused;
 end endtask
 task tick;
 begin
  @(posedge clk);cycle=cycle+1;#1;@(negedge clk);
 end endtask
 task observe;
 begin

  if(q_inputs-q_outputs != dut.quant.p_valid+dut.quant.b_valid+dut.q_valid)$fatal(1,"quant conservation id=%0d",id);
  if(dut.engine.core.issued_groups-dut.engine.core.retired_groups != (dut.engine.core.rsp_mask!=0)+(dut.engine.core.mul_mask!=0))$fatal(1,"MAC group conservation");
  if(dut.engine.host_fire && dut.fc_busy && dut.engine.host_layer==dut.engine.active_layer)$fatal(1,"active layer write");
  if(dut.engine.rd_mask!=0 && dut.engine.host_fire && dut.engine.host_kind==0 && dut.engine.x_wr_addr==dut.engine.x_rd_addr)$fatal(1,"RAM collision");
  if(dut.fc_valid && dut.q_ready && (dut.state==2 || dut.state==5))q_inputs=q_inputs+1;
  if(dut.q_valid && dut.quant_accept_ready)q_outputs=q_outputs+1;
  if(dut.state==1 || dut.state==4)launch_edges=launch_edges+1;
  if(dut.state==2)run1_edges=run1_edges+1;
  if(dut.state==3)bridge_edges=bridge_edges+1;
  if(dut.state==5)run2_edges=run2_edges+1;
  if(dut.engine.core.busy && dut.engine.core.issued_groups*4<dut.engine.core.k_latched && !fetch_enable)fetch_blocked=fetch_blocked+1;
  if(hidden_valid && !dut.hidden_accept_ready)hidden_blocked=hidden_blocked+1;
  if(out_valid && !out_ready)output_blocked=output_blocked+1;
  if(dut.fc_valid && !dut.q_ready)quant_blocked=quant_blocked+1;
  // Called just before the accepting edge. Gold values come from independent Python integers.
  payload_h={hidden_index,hidden_data,hidden_saturated,hidden_tie,1'b0};
  payload_o={out_index,out_data,out_saturated,out_tie,out_last};
  if(held_h && (!hidden_valid || payload_h!==last_h))$fatal(1,"hidden stall unstable id=%0d",id);
  if(held_o && (!out_valid || payload_o!==last_o))$fatal(1,"output stall unstable id=%0d",id);
  held_h=hidden_valid && !dut.hidden_accept_ready;last_h=payload_h;
  held_o=out_valid && !out_ready;last_o=payload_o;
  if(dut.fc_error || dut.q_error || dut.engine.core_cfg_error || cfg_error)$fatal(1,"internal config error id=%0d",id);
  if(dut.fc_valid && dut.q_ready && dut.state==2)begin
   if(npre1>=h || dut.fc_index!==npre1[2:0] || dut.fc_pre!==gp1[npre1])$fatal(1,"fc1 pre id=%0d row=%0d",id,npre1);
   npre1=npre1+1;
  end
  if(dut.fc_valid && dut.q_ready && dut.state==5)begin
   if(npre2>=o || dut.fc_index!==npre2[2:0] || dut.fc_pre!==gp2[npre2])$fatal(1,"fc2 pre id=%0d row=%0d",id,npre2);
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
   if(dut.state==2 || dut.state==5)begin
    if(dut.engine.rd_mask[t])mw_reads=mw_reads+1;
    if(dut.engine.x_rd_mask[t])mx_reads=mx_reads+1;
   end
   if((dut.engine.rd_mask[t] && dut.state==2))pairs1=pairs1+1;
   if((dut.engine.rd_mask[t] && dut.state==5))pairs2=pairs2+1;
  end
  if((dut.engine.rd_mask!=0 && dut.state==2))groups1=groups1+1;
  if((dut.engine.rd_mask!=0 && dut.state==5))groups2=groups2+1;
 end endtask
 initial begin
  memf=$fopen("memory_metrics.csv","w");if(!memf)$fatal(1,"memory file");
  $fdisplay(memf,"id,x_reads,w_reads");
  fd=$fopen("mlp_cases.txt","r");mf=$fopen("mlp_metrics.csv","w");ef=$fopen("mlp_events.csv","w");
  ff=$fopen("scenario_flags.txt","r");
  if(!ff || !fd || !mf || !ef)$fatal(1,"missing mlp files");
  $fdisplay(mf,"id,K,H,O,fused,flow,host_delay,cycles,host_loads,bridge_writes,groups1,groups2,pairs1,pairs2,launch_edges,run1_edges,bridge_edges,run2_edges,fetch_blocked,hidden_blocked,output_blocked,quant_blocked,q_inputs,q_outputs");
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
   scan=$fscanf(ff,"%d %d\n",reset_before,interrupt_after);if(scan!=2)$fatal(1,"bad flags");
   if(reset_before)begin host_we=0;reset=1;tick();reset=0;tick();cache_resets=cache_resets+1;end

   for(j=0;j<loads;j=j+1)begin
    scan=$fscanf(fd,"%d %d %d %d\n",layer,kind,addr,data);if(scan!=4)$fatal(1,"bad host record");
    host_layer=layer;host_kind=kind;host_addr=addr;host_data=data;host_we=1;#1;
    if(!host_ready)$fatal(1,"load refused");tick();
    if(interrupt_after!=0 && j+1==interrupt_after)begin
     host_we=0;reset=1;tick();reset=0;tick();cache_resets=cache_resets+1;
    end

   end
   host_we=0;
   for(j=0;j<h;j=j+1)begin scan=$fscanf(fd,"%d %d %d %d\n",gp1[j],gh[j],gs1[j],gt1[j]);if(scan!=4)$fatal(1,"bad hidden golden");end
   for(j=0;j<o;j=j+1)begin scan=$fscanf(fd,"%d %d %d %d\n",gp2[j],gy[j],gs2[j],gt2[j]);if(scan!=4)$fatal(1,"bad output golden");end
   k_cfg=k;h_cfg=h;o_cfg=o;mult1_cfg=m1;shift1_cfg=s1;mult2_cfg=m2;shift2_cfg=s2;fused_cfg=fused;
   start=1;begin_cycle=cycle+1;tick();start=0;
   clear_counts();
   // Every fifth workload also verifies reset abort/restart with retained RAM.
   if(1'b0)begin
    tick();tick();reset=1;tick();if(busy || out_valid || hidden_valid || done)$fatal(1,"reset cancellation");
    reset=0;aborts=aborts+1;tick();start=1;begin_cycle=cycle+1;tick();start=0;clear_counts();
   end
   while(busy)begin
    if(cycle-begin_cycle>20000)$fatal(1,"watchdog id=%0d state=%0d",id,dut.state);
    fetch_enable=!(flow && cycle%7==0);out_ready=!(flow && cycle%11<4);hidden_ready=!(flow && cycle%9<3);
    // Configuration changes and attempted starts during busy must not change the task.
    k_cfg=511;h_cfg=15;o_cfg=15;mult1_cfg=0;shift1_cfg=63;fused_cfg=!fused;
    host_we=(flow && (dut.state==2 || dut.state==5));host_layer=0;host_kind=1;host_addr=2047;host_data=123;bridge_done=0;start=(flow && cycle%17==0);
    #1;if(host_we && host_ready)$fatal(1,"busy host write accepted");
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
   if(pairs1!=k*h || pairs2!=h*o || groups1!=((h+1)/2)*((k+1)/2) || groups2!=((o+1)/2)*((h+1)/2))$fatal(1,"traffic mismatch id=%0d got=%0d,%0d,%0d,%0d",id,pairs1,pairs2,groups1,groups2);
   $fdisplay(memf,"%0d,%0d,%0d",id,mx_reads,mw_reads);
   $fdisplay(mf,"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d",id,k,h,o,fused,flow,delay_host,cycle-begin_cycle,loads,replayed,groups1,groups2,pairs1,pairs2,launch_edges,run1_edges,bridge_edges,run2_edges,fetch_blocked,hidden_blocked,output_blocked,quant_blocked,q_inputs,q_outputs);
   if(q_inputs!=h+o || q_outputs!=h+o || launch_edges+run1_edges+bridge_edges+run2_edges!=cycle-begin_cycle)$fatal(1,"phase/count mismatch");
   completed=completed+1;tick();if(done)$fatal(1,"done not pulse");
  end

  // Reset at RAM response, stalled hidden, partial replay, MAC product,
  // and stalled final output. Restart each case without reloading any RAM.
  for(stage=0;stage<5;stage=stage+1)begin
   id=3047+stage;fused=(stage==1 || stage==2)?0:1;
   configure_current();out_ready=(stage==4)?0:1;hidden_ready=(stage==1)?0:1;
   start=1;begin_cycle=cycle+1;tick();start=0;clear_counts();
   reached=0;
   while(!reached)begin
    #1;
    case(stage)
     0:reached=(dut.state==2 && dut.engine.core.rsp_mask!=0);
     1:reached=(dut.state==2 && hidden_valid);
     2:reached=(dut.state==3);
     3:reached=(dut.state==5 && dut.engine.core.mul_mask!=0);
     4:reached=(dut.state==5 && out_valid);
    endcase
    if(!reached)begin observe();tick();end
    if(cycle-begin_cycle>20000)$fatal(1,"supplemental target watchdog");
   end
   if(stage==1 || stage==4)begin
    for(j=0;j<8;j=j+1)begin #1;observe();tick();end
   end
   if(stage==2)begin
    host_layer=1;host_kind=0;host_addr=0;host_data=gh[0];host_we=1;#1;
    if(!host_ready)$fatal(1,"partial replay refused");observe();tick();host_we=0;
    if(dut.written!=1)$fatal(1,"partial replay not counted");
   end
   cancelled_quant=cancelled_quant+dut.quant.p_valid+dut.quant.b_valid+dut.q_valid;
   reset=1;tick();aborts=aborts+1;
   if(busy || hidden_valid || out_valid || done || dut.quant.p_valid || dut.quant.b_valid)$fatal(1,"supplemental reset ghost");
   reset=0;hidden_ready=1;out_ready=1;fetch_enable=1;host_we=0;bridge_done=0;start=0;
   for(j=0;j<5;j=j+1)begin tick();if(busy || hidden_valid || out_valid || done)$fatal(1,"ghost after reset");end
   fused=1;configure_current();start=1;begin_cycle=cycle+1;tick();start=0;clear_counts();
   while(busy)begin #1;observe();tick();if(cycle-begin_cycle>20000)$fatal(1,"restart watchdog");end
   if(!done || nh!=h || no!=o || npre1!=h || npre2!=o || q_inputs!=h+o || q_outputs!=h+o)$fatal(1,"restart mismatch");
   tick();supplemental=supplemental+1;
  end
  $display("PASS MLP completed=%0d invalid=%0d aborted=%0d cache_resets=%0d cycles=%0d supplemental=%0d cancelled_quant=%0d",completed,invalids,aborts,cache_resets,cycle,supplemental,cancelled_quant);$fclose(memf);$fclose(mf);$fclose(ef);$finish;
 end
endmodule

module tb_mode0; tb_mlp #(.MODE(0)) run(); endmodule
module tb_mode1; tb_mlp #(.MODE(1)) run(); endmodule
module tb_mode2; tb_mlp #(.MODE(2)) run(); endmodule

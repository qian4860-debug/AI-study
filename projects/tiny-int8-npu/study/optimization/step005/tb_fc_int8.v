`timescale 1ns/1ps
module tb_fc_int8;
    reg clk=0;always #5 clk=~clk;
    reg reset=1,start=0,relu_cfg=0,fetch_enable=1,out_ready=1,host_we=0;
    reg [8:0] k_cfg=0;
    reg [3:0] m_cfg=0;
    reg [1:0] host_kind=0;
    reg [10:0] host_addr=0;
    reg signed [31:0] host_data=0;
    wire start_ready,host_ready,busy,out_valid,out_last,done,cfg_error;
    wire [2:0] out_index;
    wire signed [23:0] out_dot;
    wire signed [32:0] out_pre,out_data;
    fc_int8_top dut(.*);
    integer xs[0:255],ws[0:2047],bs[0:7];
    longint signed dots[0:7],pres[0:7],ys[0:7];
    integer fd,tf,scan,cycle=0,r,s,k,m,rel,f,ready,h,kind,a,d;
    integer active=0,task_k=0,task_m=0,task_relu=0,next_output=0,reqs=0;
    integer starts=0,completed=0,invalid=0,aborted=0,outputs=0,writes=0,reads=0,pairs=0;
    integer sf,hf,of,cs,mask,ra,wa,read_row,read_group,j,i;
    integer expected_error,expected_done,hold_result,inflight;
    reg [93:0] held_packet,previous_packet;
    reg [1:0] previous_state;
    initial begin
        fd=$fopen("stimulus.txt","r");tf=$fopen("rtl_trace.csv","w");
        if(!fd || !tf) $fatal(1,"missing vectors/trace");
        $fdisplay(tf,"cycle,reset,start,k_cfg,m_cfg,relu_cfg,fetch_enable,out_ready,host_we,host_kind,host_addr,host_data,start_fire,host_fire,out_fire,core_start_fire,state,busy,host_ready,k_latched,m_latched,relu_latched,channel,bias_latched,out_valid,out_index,out_last,out_dot,out_pre,out_data,done,cfg_error,core_busy,core_out_valid,core_out_data,issued_groups,rsp_mask,rsp_last,mul_mask,mul_last,reduce_pending,rd_mask,x_rd_addr,w_rd_addr");
        while(!$feof(fd)) begin
            scan=$fscanf(fd,"%d %d %d %d %d %d %d %d %d %d %d\n",r,s,k,m,rel,f,ready,h,kind,a,d);
            if(scan!=11) $fatal(1,"bad stimulus");
            @(negedge clk);
            reset=r;start=s;k_cfg=k;m_cfg=m;relu_cfg=rel;fetch_enable=f;out_ready=ready;
            host_we=h;host_kind=kind;host_addr=a;host_data=d;
            #1;
            if(cycle>0) begin
                if(start_ready!==!busy || host_ready!==(!reset && !busy && !start &&
                    ((kind==0 && a<256) || kind==1 || (kind==2 && a<8))))
                    $fatal(1,"FAIL cycle=%0d ready protocol",cycle+1);
                if(reset && (dut.state!==previous_state || {out_index,out_last,out_dot,out_pre,out_data}!==previous_packet))
                    $fatal(1,"FAIL cycle=%0d reset changed registers before clock",cycle+1);
            end
            sf=!reset && start && start_ready;hf=host_we && host_ready;of=!reset && out_valid && out_ready;
            cs=dut.core_start;
            if(cs && !dut.core_start_ready) $fatal(1,"FAIL cycle=%0d launch while dot core busy",cycle+1);
            mask=dut.rd_mask;ra=dut.x_rd_addr;wa=dut.w_rd_addr;read_row=next_output;read_group=reqs;
            hold_result=!reset && out_valid && !out_ready;
            held_packet={out_index,out_last,out_dot,out_pre,out_data};
            if(mask) begin
                if(!active || dut.state!==2 || !fetch_enable || ra!==reqs || wa!==next_output*64+reqs)
                    $fatal(1,"FAIL cycle=%0d FC address/scheduling",cycle+1);
                for(j=0;j<4;j=j+1) if(((mask>>j)&1)!==(reqs*4+j<task_k))
                    $fatal(1,"FAIL cycle=%0d FC tail mask",cycle+1);
            end
            @(posedge clk);cycle=cycle+1;
            expected_error=0;expected_done=0;
            if(reset) begin
                if(active) aborted=aborted+1;
                active=0;next_output=0;reqs=0;
            end else begin
                if(hf) begin
                    writes=writes+1;
                    case(kind)
                        0:xs[a]=$signed(host_data[7:0]);
                        1:ws[a]=$signed(host_data[7:0]);
                        2:bs[a]=d;
                    endcase
                end
                if(sf) begin
                    if(k>=1 && k<=256 && m>=1 && m<=8) begin
                        starts=starts+1;active=1;task_k=k;task_m=m;task_relu=rel;next_output=0;reqs=0;
                        for(i=0;i<m;i=i+1) begin
                            dots[i]=0;
                            for(j=0;j<k;j=j+1) dots[i]=dots[i]+xs[j]*ws[i*256+j];
                            pres[i]=dots[i]+bs[i];ys[i]=(rel && pres[i]<0) ? 0 : pres[i];
                        end
                    end else begin expected_error=1;invalid=invalid+1;end
                end
                if(mask) begin
                    reqs=reqs+1;reads=reads+1;
                    for(j=0;j<4;j=j+1) if((mask>>j)&1) pairs=pairs+1;
                end
                if(of) begin
                    if(!active || out_index!==next_output[2:0] || out_last!==(next_output==task_m-1) ||
                       $signed(out_dot)!==dots[next_output] || $signed(out_pre)!==pres[next_output] ||
                       $signed(out_data)!==ys[next_output] || reqs!==(task_k+3)/4)
                        $fatal(1,"FAIL cycle=%0d output handshake/math/order",cycle);
                    outputs=outputs+1;next_output=next_output+1;reqs=0;
                    if(out_last) begin active=0;completed=completed+1;expected_done=1;end
                end
            end
            #1;
            if(cfg_error!==expected_error[0] || done!==expected_done[0] || busy!==active[0])
                $fatal(1,"FAIL cycle=%0d busy/error/done",cycle);
            if(hold_result && (!out_valid || {out_index,out_last,out_dot,out_pre,out_data}!==held_packet))
                $fatal(1,"FAIL cycle=%0d output changed under backpressure",cycle);
            if(out_valid && (!active || out_index!==next_output[2:0] || out_last!==(next_output==task_m-1) ||
                $signed(out_dot)!==dots[next_output] || $signed(out_pre)!==pres[next_output] || $signed(out_data)!==ys[next_output]))
                $fatal(1,"FAIL cycle=%0d visible intermediate/output mismatch",cycle);
            if(reset && (out_valid || done || cfg_error || busy || out_data!==0 || out_pre!==0 || out_dot!==0))
                $fatal(1,"FAIL cycle=%0d reset clearing",cycle);
            for(j=0;j<4;j=j+1) if((mask>>j)&1) begin
                if($signed(dut.x_rd_data[j*8+:8])!==xs[read_group*4+j] ||
                   $signed(dut.w_rd_data[j*8+:8])!==ws[read_row*256+read_group*4+j])
                    $fatal(1,"FAIL cycle=%0d FC RAM response",cycle);
            end
            inflight=dut.core.issued_groups-dut.core.retired_groups;
            if(inflight!==((dut.core.rsp_mask!=0)+(dut.core.mul_mask!=0)) || dut.core_cfg_error)
                $fatal(1,"FAIL cycle=%0d core conservation/error",cycle);
            previous_state=dut.state;previous_packet={out_index,out_last,out_dot,out_pre,out_data};
            $fwrite(tf,"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,",cycle,r,s,k,m,rel,f,ready,h,kind,a,d);
            $fwrite(tf,"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,",sf,hf,of,cs,dut.state,busy,host_ready,
                dut.k_latched,dut.m_latched,dut.relu_latched,dut.channel,$signed(dut.bias_latched));
            $fwrite(tf,"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,",out_valid,out_index,out_last,$signed(out_dot),$signed(out_pre),$signed(out_data),done,cfg_error);
            $fdisplay(tf,"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d",dut.core_busy,dut.core_out_valid,$signed(dut.core_out),
                dut.core.issued_groups,dut.core.rsp_mask,dut.core.rsp_last,dut.core.mul_mask,dut.core.mul_last,dut.core.reduce_pending,mask,ra,wa);
        end
        if(active) $fatal(1,"unfinished layer");
        $display("PASS STEP005 cycles=%0d starts=%0d completed=%0d invalid=%0d aborted=%0d outputs=%0d host_writes=%0d reads=%0d pairs=%0d",
            cycle,starts,completed,invalid,aborted,outputs,writes,reads,pairs);
        $fclose(fd);$fclose(tf);$finish;
    end
    initial begin #20000000;$fatal(1,"simulation watchdog, not hardware timeout");end
endmodule

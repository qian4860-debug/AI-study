`timescale 1ns/1ps
module banked_checker #(parameter integer P=4)(output reg done=0);
    reg clk=0; always #5 clk=~clk;
    reg reset=1,start=0,fetch_enable=0,host_we=0;
    reg [8:0] k_cfg=0;
    reg [7:0] host_addr=0;
    reg signed [7:0] host_x=0,host_w=0;
    wire start_ready,host_ready,busy,out_valid,cfg_error;
    wire signed [23:0] out_data;
    dot_banked_top #(.LANES(P)) dut(.*);
    integer fd,tf,scan,cycle=0,r,s,k,f,h,a,x,w;
    integer mb=0,mk=0,mi=0,mr=0,melems=0,mo=0,mv=0,me=0;
    integer q0=0,q1=0,l0=0,l1=0,reduce_q=0;
    integer p0[0:3],p1[0:3],mp[0:3],ms[0:3];
    integer mx[0:255],mw[0:255];
    integer sf,rf,hf,addr,mask,task_expected=0,j,ell,total;
    integer reads=0,elements=0,macs=0,completed=0,aborted=0,invalid=0,starts=0,writes=0;
    integer start_cycle=0,stalls=0;
    task check;
    begin
        if(busy!==mb[0] || start_ready!==!mb || host_ready!==(!mb && !start && !reset) ||
           out_valid!==mv[0] || cfg_error!==me[0] || $signed(out_data)!==mo ||
           dut.core.k_latched!==mk[8:0] || dut.core.issued_groups!==mi[8:0] ||
           dut.core.retired_groups!==mr[8:0] || dut.core.retired_elements!==melems[8:0] ||
           dut.core.rsp_mask!==q0[P-1:0] || dut.core.mul_mask!==q1[P-1:0] ||
           dut.core.rsp_last!==l0[0] || dut.core.mul_last!==l1[0] || dut.core.reduce_pending!==reduce_q[0])
            $fatal(1,"FAIL P=%0d cycle=%0d state/count/tag/output",P,cycle);
        for(ell=0;ell<P;ell=ell+1)
            if($signed(dut.core.products[ell])!==mp[ell] || $signed(dut.core.sums[ell])!==ms[ell])
                $fatal(1,"FAIL P=%0d cycle=%0d lane=%0d product/sum",P,cycle,ell);
        if(mi-mr !== (q0!=0)+(q1!=0) || mr>mi || melems>mk)
            $fatal(1,"FAIL P=%0d cycle=%0d conservation",P,cycle);
        if((l0 && !q0) || (l1 && !q1) || (!mb && (q0 || q1 || reduce_q || dut.rd_en)))
            $fatal(1,"FAIL P=%0d cycle=%0d ghost tag/request",P,cycle);
    end endtask
    initial begin
        for(j=0;j<4;j=j+1) begin p0[j]=0;p1[j]=0;mp[j]=0;ms[j]=0;end
        fd=$fopen($sformatf("stimulus_p%0d.txt",P),"r");
        tf=$fopen($sformatf("trace_p%0d.csv",P),"w");
        if(!fd || !tf) $fatal(1,"missing vector/trace");
        $fdisplay(tf,"cycle,reset,start,k_cfg,fetch_enable,host_we,host_addr,host_x,host_w,start_fire,read_fire,host_fire,read_addr,read_mask,busy,host_ready,k_latched,issued_groups,retired_groups,retired_elements,rsp_mask,rsp_last,mul_mask,mul_last,reduce_pending,product0,product1,product2,product3,sum0,sum1,sum2,sum3,out_valid,out_data,cfg_error");
        while(!$feof(fd)) begin
            scan=$fscanf(fd,"%d %d %d %d %d %d %d %d\n",r,s,k,f,h,a,x,w);
            if(scan!=8) $fatal(1,"bad stimulus");
            @(negedge clk);reset=r;start=s;k_cfg=k;fetch_enable=f;host_we=h;host_addr=a;host_x=x;host_w=w;
            #1; if(cycle>0) check();
            sf=!reset && start && start_ready;hf=host_we && host_ready;
            addr=dut.rd_addr; mask=dut.rd_en;rf=(mask!=0);
            if(cycle>0) begin
                if(rf!==(!reset && mb && f && mi*P<mk)) $fatal(1,"FAIL P=%0d cycle=%0d read enable",P,cycle+1);
                if(rf && addr!==mi) $fatal(1,"FAIL P=%0d cycle=%0d address",P,cycle+1);
                for(j=0;j<P;j=j+1)
                    if(((mask>>j)&1)!==(!reset && mb && f && mi*P+j<mk))
                        $fatal(1,"FAIL P=%0d cycle=%0d tail mask",P,cycle+1);
            end
            @(posedge clk);cycle=cycle+1;mv=0;me=0;
            if(reset) begin
                if(mb) aborted=aborted+1;
                mb=0;mk=0;mi=0;mr=0;melems=0;mo=0;q0=0;q1=0;l0=0;l1=0;reduce_q=0;
                for(j=0;j<4;j=j+1) begin mp[j]=0;ms[j]=0;end
            end else begin
                if(mb && mi*P<mk && !f) stalls=stalls+1;
                if(reduce_q) begin
                    total=0;for(j=0;j<P;j=j+1) total=total+ms[j];
                    if(total!==task_expected || melems!==mk || cycle-start_cycle!==((mk+P-1)/P+3+stalls))
                        $fatal(1,"FAIL P=%0d cycle=%0d reduction/latency",P,cycle);
                    mo=total;mv=1;mb=0;completed=completed+1;
                    for(j=0;j<4;j=j+1) ms[j]=0;
                end
                reduce_q=0;
                if(q1) begin
                    mr=mr+1;
                    for(j=0;j<P;j=j+1) if((q1>>j)&1) begin
                        ms[j]=ms[j]+p1[j];melems=melems+1;macs=macs+1;
                    end
                    if(l1) reduce_q=1;
                end
                for(j=0;j<P;j=j+1) if((q0>>j)&1) mp[j]=p0[j];
                q1=q0;l1=l0;for(j=0;j<P;j=j+1) p1[j]=p0[j];
                q0=mask;l0=0;
                if(rf) begin
                    mi=mi+1;l0=(mi*P>=mk);reads=reads+1;
                    for(j=0;j<P;j=j+1) if((mask>>j)&1) begin
                        p0[j]=mx[addr*P+j]*mw[addr*P+j];elements=elements+1;
                    end
                end
                if(hf) begin mx[a]=x;mw[a]=w;writes=writes+1;end
                if(sf) begin
                    if(k>=1 && k<=256) begin
                        mb=1;mk=k;mi=0;mr=0;melems=0;q0=0;q1=0;l0=0;l1=0;reduce_q=0;
                        for(j=0;j<4;j=j+1) ms[j]=0;
                        starts=starts+1;start_cycle=cycle;stalls=0;task_expected=0;
                        for(j=0;j<k;j=j+1) task_expected=task_expected+mx[j]*mw[j];
                    end else begin me=1;invalid=invalid+1;end
                end
            end
            #1;check();
            for(j=0;j<P;j=j+1) if((mask>>j)&1) begin
                if($signed(dut.x_rd_data[j*8+:8])!==mx[addr*P+j] || $signed(dut.w_rd_data[j*8+:8])!==mw[addr*P+j])
                    $fatal(1,"FAIL P=%0d cycle=%0d bank RAM read",P,cycle);
            end
            $fdisplay(tf,"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d",
                cycle,r,s,k,f,h,a,x,w,sf,rf,hf,addr,mask,busy,host_ready,dut.core.k_latched,
                dut.core.issued_groups,dut.core.retired_groups,dut.core.retired_elements,
                dut.core.rsp_mask,dut.core.rsp_last,dut.core.mul_mask,dut.core.mul_last,dut.core.reduce_pending,
                mp[0],mp[1],mp[2],mp[3],ms[0],ms[1],ms[2],ms[3],out_valid,$signed(out_data),cfg_error);
        end
        if(mb) $fatal(1,"unfinished task");
        $display("PASS STEP004 P=%0d cycles=%0d starts=%0d completed=%0d invalid=%0d aborted=%0d reads=%0d elements=%0d macs=%0d host_writes=%0d",
            P,cycle,starts,completed,invalid,aborted,reads,elements,macs,writes);
        $fclose(fd);$fclose(tf);done=1;
    end
endmodule
module tb_dot_banked;
    wire d1,d2,d4;
    banked_checker #(.P(1)) a(d1);
    banked_checker #(.P(2)) b(d2);
    banked_checker #(.P(4)) c(d4);
    initial begin wait(d1 && d2 && d4);$display("PASS ALL_CONFIGS");$finish;end
    initial begin #20000000;$fatal(1,"simulation watchdog");end
endmodule

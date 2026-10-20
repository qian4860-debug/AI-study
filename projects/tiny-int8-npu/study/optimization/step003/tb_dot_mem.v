`timescale 1ns/1ps
module tb_dot_mem;
    reg clk=0; always #5 clk=~clk;
    reg reset=1,start=0,fetch_enable=0,host_we=0;
    reg [8:0] k_cfg=0;
    reg [7:0] host_addr=0;
    reg signed [7:0] host_x=0,host_w=0;
    wire start_ready,host_ready,busy,out_valid,cfg_error;
    wire signed [23:0] out_data;
    dot_mem_top dut(.*);

    integer fd,tf,scan,cycle=0,r,s,k,f,h,a,x,w;
    integer mb=0,mk=0,mi=0,mr=0,ma=0,mo=0,mv=0,me=0;
    integer q0=0,q1=0,l0=0,l1=0,p0=0,p1=0,mp=0;
    integer mx[0:255],mw[0:255];
    integer sf,rf,hf,addr,task_expected=0,j;
    integer requests=0,retired=0,completed=0,aborted=0,invalid=0,starts=0,writes=0;
    task check;
    begin
        if(busy!==mb[0] || start_ready!==!mb || host_ready!==(!mb && !start && !reset) ||
           out_valid!==mv[0] || cfg_error!==me[0] || $signed(out_data)!==mo ||
           dut.core.k_latched!==mk[8:0] || dut.core.issued_count!==mi[8:0] ||
           dut.core.retired_count!==mr[8:0] || $signed(dut.core.acc)!==ma ||
           dut.core.rsp_valid!==q0[0] || dut.core.rsp_last!==l0[0] ||
           dut.core.mul_valid!==q1[0] || dut.core.mul_last!==l1[0] ||
           $signed(dut.core.product_reg)!==mp)
            $fatal(1,"FAIL cycle=%0d state/tag/count/acc/output mismatch",cycle);
        if(dut.x_rd_en !== dut.w_rd_en || dut.x_rd_addr !== dut.w_rd_addr)
            $fatal(1,"FAIL cycle=%0d unpaired read",cycle);
        if(mi-mr !== q0+q1 || mr>mi || mi>mk)
            $fatal(1,"FAIL cycle=%0d in-flight conservation",cycle);
        if((l0 && !q0) || (l1 && !q1)) $fatal(1,"FAIL cycle=%0d orphan last tag",cycle);
        if(!busy && (dut.x_rd_en!==0 || dut.w_rd_en!==0 || q0 || q1))
            $fatal(1,"FAIL cycle=%0d ghost activity after completion",cycle);
    end endtask
    initial begin
        fd=$fopen("stimulus.txt","r"); tf=$fopen("rtl_trace.csv","w");
        if(!fd || !tf) $fatal(1,"cannot open vectors");
        $fdisplay(tf,"cycle,reset,start,k_cfg,fetch_enable,host_we,host_addr,host_x,host_w,start_fire,read_fire,host_fire,read_addr,busy,start_ready,host_ready,k_latched,issued_count,retired_count,rsp_valid,rsp_last,mul_valid,mul_last,product_reg,acc,out_valid,out_data,cfg_error");
        while(!$feof(fd)) begin
            scan=$fscanf(fd,"%d %d %d %d %d %d %d %d\n",r,s,k,f,h,a,x,w);
            if(scan!=8) $fatal(1,"bad vector");
            @(negedge clk);
            reset=r; start=s; k_cfg=k; fetch_enable=f; host_we=h; host_addr=a;host_x=x;host_w=w;
            #1; if(cycle>0) check();
            sf=!reset && start && start_ready;
            rf=dut.x_rd_en; hf=host_we && host_ready; addr=dut.x_rd_addr;
            if(cycle>0 && rf!==(!reset && mb && f && mi<mk))
                $fatal(1,"FAIL cycle=%0d request enable mismatch",cycle+1);
            if(rf && (addr!==mi || addr>=mk)) $fatal(1,"FAIL cycle=%0d read address mismatch",cycle+1);
            @(posedge clk); cycle=cycle+1;
            mv=0; me=0;
            if(reset) begin
                if(mb) aborted=aborted+1;
                mb=0;mk=0;mi=0;mr=0;ma=0;mo=0;q0=0;q1=0;l0=0;l1=0;mp=0;
            end else begin
                // Consume the older queue entry before advancing either tag.
                if(q1) begin
                    retired=retired+1; mr=mr+1; ma=ma+p1;
                    if(l1) begin
                        if(ma!==task_expected || mr!==mk) $fatal(1,"FAIL cycle=%0d complete dot product",cycle);
                        mo=ma; ma=0; mv=1; mb=0; completed=completed+1;
                    end
                end
                if(q0) mp=p0;
                q1=q0; l1=l0; p1=p0;
                q0=rf; l0=0;
                if(rf) begin
                    p0=mx[addr]*mw[addr]; mi=mi+1; l0=(mi==mk); requests=requests+1;
                end
                if(hf) begin mx[a]=x; mw[a]=w; writes=writes+1; end
                if(sf) begin
                    if(k>=1 && k<=256) begin
                        mb=1;mk=k;mi=0;mr=0;ma=0;q0=0;q1=0;l0=0;l1=0;starts=starts+1;
                        task_expected=0;
                        for(j=0;j<k;j=j+1) task_expected=task_expected+mx[j]*mw[j];
                    end else begin me=1; invalid=invalid+1; end
                end
            end
            #1;
            check();
            if(rf && ($signed(dut.x_rd_data)!==mx[addr] || $signed(dut.w_rd_data)!==mw[addr]))
                $fatal(1,"FAIL cycle=%0d synchronous RAM read data",cycle);
            $fdisplay(tf,"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d",
                cycle,r,s,k,f,h,a,x,w,sf,rf,hf,addr,busy,start_ready,host_ready,dut.core.k_latched,
                dut.core.issued_count,dut.core.retired_count,dut.core.rsp_valid,dut.core.rsp_last,
                dut.core.mul_valid,dut.core.mul_last,$signed(dut.core.product_reg),$signed(dut.core.acc),out_valid,$signed(out_data),cfg_error);
        end
        if(mb) $fatal(1,"unfinished task");
        $display("PASS STEP003 cycles=%0d starts=%0d completed=%0d invalid=%0d aborted=%0d requests=%0d retired=%0d host_writes=%0d",
            cycle,starts,completed,invalid,aborted,requests,retired,writes);
        $fclose(fd);$fclose(tf);$finish;
    end
    initial begin #20000000; $fatal(1,"simulation watchdog, not hardware timeout"); end
endmodule

`timescale 1ns/1ps
module tb_dot_serial_cfg;
    reg clk=0;
    always #5 clk=~clk;
    reg reset=1, start=0, in_valid=0;
    reg [8:0] k_cfg=0;
    reg signed [7:0] x=0,w=0;
    wire start_ready,in_ready,busy,out_valid,cfg_error;
    wire signed [23:0] out_data;
    dot_serial_cfg dut(.*);

    integer fd,trace_fd,scan,cycle=0;
    integer r,s,k,v,xb,wb;
    integer model_busy=0,model_k=0,model_count=0,model_acc=0;
    integer model_out=0,model_valid=0,model_error=0;
    integer starts=0,completed=0,errors=0,aborted=0,accepted=0;
    integer input_x,input_w,queue_count=0,queue_sum;
    integer queue_x[0:255],queue_w[0:255];
    integer j,product_value,pre_start,pre_data;
    task compare;
    begin
        if(busy !== model_busy[0] || start_ready !== !model_busy || in_ready !== model_busy[0] ||
           out_valid !== model_valid[0] || cfg_error !== model_error[0] ||
           $signed(out_data) !== model_out || dut.k_latched !== model_k[8:0] ||
           dut.accepted_count !== model_count[8:0] || $signed(dut.acc) !== model_acc)
            $fatal(1,"FAIL cycle=%0d busy=%b count=%0d k=%0d acc=%0d out=%0d valid=%b error=%b EXPECT busy=%0d count=%0d k=%0d acc=%0d out=%0d valid=%0d error=%0d",
                cycle,busy,dut.accepted_count,dut.k_latched,$signed(dut.acc),$signed(out_data),out_valid,cfg_error,
                model_busy,model_count,model_k,model_acc,model_out,model_valid,model_error);
    end
    endtask
    initial begin
        fd=$fopen("stimulus.txt","r");
        trace_fd=$fopen("rtl_trace.csv","w");
        if(!fd || !trace_fd) $fatal(1,"cannot open input/trace");
        $fdisplay(trace_fd,"cycle,reset,start,k_cfg,in_valid,x,w,start_fire,data_fire,busy,start_ready,in_ready,k_latched,accepted_count,acc,out_valid,out_data,cfg_error");
        while(!$feof(fd)) begin
            scan=$fscanf(fd,"%d %d %d %d %d %d\n",r,s,k,v,xb,wb);
            if(scan != 6) $fatal(1,"malformed stimulus");
            @(negedge clk);
            reset=r; start=s; k_cfg=k; in_valid=v; x=xb; w=wb;
            // No state change is allowed merely because reset rises mid-cycle.
            #1;
            if(cycle>0) compare();
            pre_start = !reset && start && start_ready;
            pre_data = !reset && in_valid && in_ready;
            if(cycle>0 && (pre_start !== (!r && s && !model_busy) || pre_data !== (!r && v && model_busy)))
                $fatal(1,"pre-edge handshake mismatch");
            @(posedge clk);
            cycle=cycle+1;
            model_valid=0; model_error=0;
            if(reset) begin
                if(model_busy) aborted=aborted+1;
                model_busy=0; model_k=0; model_count=0; model_acc=0;
                model_out=0; queue_count=0;
            end else if(!model_busy && start) begin
                if(k>=1 && k<=256) begin
                    starts=starts+1;
                    model_busy=1; model_k=k; model_count=0; model_acc=0; queue_count=0;
                end else begin
                    model_error=1; errors=errors+1;
                end
            end else if(model_busy && in_valid) begin
                accepted=accepted+1;
                input_x=$signed(x); input_w=$signed(w);
                product_value=input_x*input_w;
                queue_x[queue_count]=input_x; queue_w[queue_count]=input_w;
                queue_count=queue_count+1;
                model_count=model_count+1;
                model_acc=model_acc+product_value;
                if(model_count==model_k) begin
                    // Independent task queue evaluates the complete dot product.
                    queue_sum=0;
                    for(j=0;j<queue_count;j=j+1) queue_sum=queue_sum+queue_x[j]*queue_w[j];
                    if(queue_sum !== model_acc) $fatal(1,"scoreboard queue mismatch");
                    model_out=queue_sum; model_valid=1; model_busy=0;
                    model_count=0; model_acc=0; completed=completed+1;
                end
            end
            #1;
            compare();
            $fdisplay(trace_fd,"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d",
                cycle,r,s,k,v,$signed(x),$signed(w),pre_start,pre_data,busy,start_ready,in_ready,
                dut.k_latched,dut.accepted_count,$signed(dut.acc),out_valid,$signed(out_data),cfg_error);
        end
        if(model_busy) $fatal(1,"unfinished final task");
        $display("PASS STEP002 cycles=%0d starts=%0d completed=%0d invalid=%0d aborted=%0d accepted=%0d",
            cycle,starts,completed,errors,aborted,accepted);
        $fclose(fd); $fclose(trace_fd); $finish;
    end
    initial begin
        #20000000; $fatal(1,"simulation watchdog (not a hardware timeout)");
    end
endmodule

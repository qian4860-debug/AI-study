// LANES is restricted to 1, 2 or 4. Each lane owns one partial sum.
// Pipeline: synchronous RAM -> product register -> lane sum -> final reduction.
module dot_banked_core #(parameter integer LANES=4)(
    input wire clk, reset, start,
    output wire start_ready,
    input wire [8:0] k_cfg,
    input wire fetch_enable,
    output wire [LANES-1:0] rd_en,
    output wire [7:0] rd_addr,
    input wire [LANES*8-1:0] x_rd_data, w_rd_data,
    output reg busy,
    output reg signed [23:0] out_data,
    output reg out_valid, cfg_error
);
    reg [8:0] k_latched, issued_groups, retired_groups;
    reg [8:0] retired_elements;
    reg [LANES-1:0] rsp_mask, mul_mask;
    reg rsp_last, mul_last, reduce_pending;
    reg signed [15:0] products[0:LANES-1];
    reg signed [23:0] sums[0:LANES-1];
    wire [8:0] issue_base=issued_groups*LANES;
    wire read_fire=!reset && busy && fetch_enable && (issue_base<k_latched);
    wire last_request=(issue_base+LANES>=k_latched);
    wire signed [23:0] reduction;
    wire signed [23:0] pair01, pair23;
    assign start_ready=!busy;
    assign rd_addr=issued_groups[7:0];
    genvar lane;
    generate for(lane=0;lane<LANES;lane=lane+1) begin: pe
        assign rd_en[lane]=read_fire && (issue_base+lane<k_latched);
        wire signed [7:0] xv=x_rd_data[lane*8+:8];
        wire signed [7:0] wv=w_rd_data[lane*8+:8];
        wire signed [15:0] product=xv*wv;
        wire signed [23:0] extended_product={{8{products[lane][15]}},products[lane]};
        always @(posedge clk) begin
            if(reset) begin products[lane]<=0; sums[lane]<=0; end
            else begin
                if(rsp_mask[lane]) products[lane]<=product;
                if(mul_mask[lane]) sums[lane]<=sums[lane]+extended_product;
                if(reduce_pending || (start && start_ready && k_cfg>=1 && k_cfg<=256))
                    sums[lane]<=0;
            end
        end
    end endgenerate
    generate
        if(LANES==1) begin: reduce1
            assign reduction=sums[0];
            assign pair01=0; assign pair23=0;
        end else if(LANES==2) begin: reduce2
            assign pair01=sums[0]+sums[1]; assign pair23=0;
            assign reduction=pair01;
        end else begin: reduce4
            assign pair01=sums[0]+sums[1];
            assign pair23=sums[2]+sums[3];
            assign reduction=pair01+pair23;
        end
    endgenerate
    integer n;
    reg [8:0] retiring_now;
    always @* begin
        retiring_now=0;
        for(n=0;n<LANES;n=n+1) retiring_now=retiring_now+mul_mask[n];
    end
    always @(posedge clk) begin
        if(reset) begin
            busy<=0;out_data<=0;out_valid<=0;cfg_error<=0;k_latched<=0;
            issued_groups<=0;retired_groups<=0;retired_elements<=0;
            rsp_mask<=0;mul_mask<=0;rsp_last<=0;mul_last<=0;reduce_pending<=0;
        end else begin
            out_valid<=0;cfg_error<=0;
            rsp_mask<=rd_en; rsp_last<=read_fire && last_request;
            mul_mask<=rsp_mask; mul_last<=(|rsp_mask) && rsp_last;
            reduce_pending<=0;
            if(read_fire) issued_groups<=issued_groups+9'd1;
            if(|mul_mask) begin
                retired_groups<=retired_groups+9'd1;
                retired_elements<=retired_elements+retiring_now;
                if(mul_last) reduce_pending<=1;
            end
            if(reduce_pending) begin out_data<=reduction;out_valid<=1;busy<=0;end
            if(start && start_ready) begin
                if(k_cfg>=9'd1 && k_cfg<=9'd256) begin
                    busy<=1;k_latched<=k_cfg;issued_groups<=0;retired_groups<=0;retired_elements<=0;
                    rsp_mask<=0;mul_mask<=0;rsp_last<=0;mul_last<=0;reduce_pending<=0;
                end else cfg_error<=1;
            end
        end
    end
endmodule

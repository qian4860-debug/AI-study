set_param general.maxThreads 2
read_verilog ../dot_banked_core.v
read_verilog ../bank_ram.v
read_verilog ../fc_int8_top.v
synth_design -top fc_int8_top -part xc7a100tcsg324-1 -mode out_of_context
create_clock -name clk -period 10.000 [get_ports clk]
set util [report_utilization -return_string]
set fp [open ../synthesis_utilization.rpt w];puts $fp $util;close $fp
report_timing_summary -file ../synthesis_timing.rpt
set dsp [llength [get_cells -quiet -hier -filter {REF_NAME =~ DSP48*}]]
set ff [llength [get_cells -quiet -hier -filter {REF_NAME =~ FD*}]]
set ram [llength [get_cells -quiet -hier -filter {REF_NAME =~ RAMB*}]]
set lut -1
regexp {\| Slice LUTs\*\s*\|\s*([0-9]+)} $util match lut
if {$lut<0} {error "Missing Slice LUT count"}
set fp [open ../synthesis_results.json w]
puts $fp "\{\"status\":\"PASS\",\"tool\":\"Vivado [version -short]\",\"part\":\"xc7a100tcsg324-1\",\"top\":\"fc_int8_top\",\"stage\":\"out_of_context_synthesis\",\"clock_period_ns\":10.0,\"Slice_LUTs\":$lut,\"FF\":$ff,\"DSP\":$dsp,\"RAMB_cells\":$ram\}"
close $fp
puts "PASS STEP005_SYNTH Slice_LUTs=$lut FF=$ff DSP=$dsp RAMB_cells=$ram"

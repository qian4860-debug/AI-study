set_param general.maxThreads 2
read_verilog ../dot_serial_mem.v
read_verilog ../sync_byte_ram.v
read_verilog ../dot_mem_top.v
synth_design -top dot_mem_top -part xc7a100tcsg324-1 -mode out_of_context
create_clock -name clk -period 10.000 [get_ports clk]
set util [report_utilization -return_string]
set fp [open ../synthesis_utilization.rpt w]; puts $fp $util; close $fp
report_timing_summary -file ../synthesis_timing.rpt
set dsps [llength [get_cells -quiet -hier -filter {REF_NAME =~ DSP48*}]]
set ffs [llength [get_cells -quiet -hier -filter {REF_NAME =~ FD*}]]
set rams [llength [get_cells -quiet -hier -filter {REF_NAME =~ RAMB*}]]
set lut_count -1
regexp {\| Slice LUTs\*\s*\|\s*([0-9]+)} $util match lut_count
if {$lut_count < 0} { error "Slice LUT count missing" }
set fp [open ../synthesis_results.json w]
puts $fp "\{\"status\":\"PASS\",\"tool\":\"Vivado [version -short]\",\"part\":\"xc7a100tcsg324-1\",\"top\":\"dot_mem_top\",\"stage\":\"out_of_context_synthesis\",\"clock_period_ns\":10.0,\"DSP\":$dsps,\"Slice_LUTs\":$lut_count,\"FF\":$ffs,\"RAMB_cells\":$rams\}"
close $fp
puts "PASS STEP003_SYNTH Slice_LUTs=$lut_count FF=$ffs DSP=$dsps RAMB_cells=$rams"

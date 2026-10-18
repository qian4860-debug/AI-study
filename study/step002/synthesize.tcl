# Run from step002/build. Out-of-context synthesis, no board implementation.
set_param general.maxThreads 2
read_verilog ../dot_serial_cfg.v
synth_design -top dot_serial_cfg -part xc7a100tcsg324-1 -mode out_of_context
create_clock -name clk -period 10.000 [get_ports clk]
report_utilization -file ../synthesis_utilization.rpt
report_timing_summary -file ../synthesis_timing.rpt
set dsps [llength [get_cells -hier -filter {REF_NAME =~ DSP48*}]]
set luts [llength [get_cells -hier -filter {REF_NAME =~ LUT*}]]
set ffs [llength [get_cells -hier -filter {REF_NAME =~ FD*}]]
set fp [open ../synthesis_results.json w]
puts $fp "\{\"status\":\"PASS\",\"tool\":\"Vivado [version -short]\",\"part\":\"xc7a100tcsg324-1\",\"stage\":\"out_of_context_synthesis\",\"clock_period_ns\":10.0,\"DSP\":$dsps,\"LUT_cells\":$luts,\"FF\":$ffs\}"
close $fp
puts "PASS STEP002_SYNTH DSP=$dsps LUT_cells=$luts FF=$ffs"

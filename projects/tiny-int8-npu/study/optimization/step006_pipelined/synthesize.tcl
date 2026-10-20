set_param general.maxThreads 2
set json [open ../synthesis_results.json w]
puts $json "\{\"status\":\"PASS\",\"tool\":\"Vivado [version -short]\",\"part\":\"xc7a100tcsg324-1\",\"clock_period_ns\":10.0,\"stage\":\"out_of_context_synthesis\",\"configs\":\{"
set sep ""
foreach style {block distributed} {
 create_project -in_memory -part xc7a100tcsg324-1
 foreach f {dot_banked_core.v fc_int8_top.v requant_i8.v mlp2_top.v} {read_verilog ../$f}
 read_verilog ../bank_ram_${style}.v
 synth_design -top mlp2_top -part xc7a100tcsg324-1 -mode out_of_context
 create_clock -name clk -period 10.000 [get_ports clk]
 set util [report_utilization -return_string]
 set f [open ../util_${style}.rpt w];puts $f $util;close $f
 report_timing_summary -file ../timing_${style}.rpt
 report_timing -max_paths 3 -file ../paths_${style}.rpt
 set dsp [llength [get_cells -quiet -hier -filter {REF_NAME =~ DSP48*}]]
 set ff [llength [get_cells -quiet -hier -filter {REF_NAME =~ FD*}]]
 set ram [llength [get_cells -quiet -hier -filter {REF_NAME =~ RAMB*}]]
 set lut -1;regexp {\| Slice LUTs\*\s*\|\s*([0-9]+)} $util match lut
 if {$lut<0} {error "missing LUT count"}
 set slack [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
 puts $json "$sep\"$style\":\{\"Slice_LUTs\":$lut,\"FF\":$ff,\"DSP\":$dsp,\"RAMB_cells\":$ram,\"WNS_ns\":$slack\}"
 puts "PASS PIPELINE_SYNTH $style LUT=$lut FF=$ff DSP=$dsp RAM=$ram WNS=$slack"
 set sep ",";close_project
}
puts $json "\}\}";close $json

set_param general.maxThreads 2
set json [open ../synthesis_results.json w]
puts $json "\{\"status\":\"PASS\",\"tool\":\"Vivado [version -short]\",\"part\":\"xc7a100tcsg324-1\",\"clock_period_ns\":10.0,\"stage\":\"out_of_context_synthesis\",\"configs\":\{"
set sep ""
foreach mode {0 1 2} name {block hybrid distributed} {
 create_project -in_memory -part xc7a100tcsg324-1
 foreach f {dot_tile_core.v requant_i8.v sync_ram_style.v fc_shared.v mlp2_top.v} {read_verilog ../$f}
 synth_design -top mlp2_top -generic RAM_MODE=$mode -part xc7a100tcsg324-1 -mode out_of_context
 create_clock -name clk -period 10.000 [get_ports clk]
 set util [report_utilization -return_string]
 set f [open ../util_${name}.rpt w];puts $f $util;close $f
 report_utilization -hierarchical -file ../hierarchy_${name}.rpt
 report_timing_summary -file ../timing_${name}.rpt
 report_timing -max_paths 3 -file ../paths_${name}.rpt
 set dsp [llength [get_cells -quiet -hier -filter {REF_NAME =~ DSP48*}]]
 set ff [llength [get_cells -quiet -hier -filter {REF_NAME =~ FD*}]]
 set ram [llength [get_cells -quiet -hier -filter {REF_NAME =~ RAMB*}]]
 set cores [llength [get_cells -quiet -hier -filter {REF_NAME =~ dot_tile_core*}]]
 set quants [llength [get_cells -quiet -hier -filter {REF_NAME =~ requant_i8*}]]
 if {$cores!=1 || $quants!=1} {error "Expected one tile core and quantizer, got $cores/$quants"}
 set lut -1;regexp {\| Slice LUTs\*\s*\|\s*([0-9]+)} $util match lut
 if {$lut<0} {error "missing LUT count"}
 set slack [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
 puts $json "$sep\"$name\":\{\"RAM_MODE\":$mode,\"Slice_LUTs\":$lut,\"FF\":$ff,\"DSP\":$dsp,\"RAMB_cells\":$ram,\"WNS_ns\":$slack,\"tile_core_instances\":$cores,\"quantizer_instances\":$quants\}"
 puts "PASS STEP008B_SYNTH $name LUT=$lut FF=$ff DSP=$dsp RAM=$ram WNS=$slack core=$cores quant=$quants"
 set sep ",";close_project
}
puts $json "\}\}";close $json

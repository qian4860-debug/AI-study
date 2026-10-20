set_param general.maxThreads 2
set json [open ../synthesis_results.json w]
puts $json "\{\"status\":\"PASS\",\"tool\":\"Vivado [version -short]\",\"part\":\"xc7a100tcsg324-1\",\"stage\":\"out_of_context_synthesis\",\"clock_period_ns\":10.0,\"configs\":\{"
set sep ""
foreach config {s003 s004p1 s004p2 s004p4 s005 s006block s006distributed} {
 create_project -in_memory -part xc7a100tcsg324-1
 if {$config eq "s003"} {
  foreach f {dot_serial_mem.v sync_byte_ram.v dot_mem_top.v} {read_verilog ../step003/$f}
  set top dot_mem_top
 } else {
  if {[string match s004* $config]} {set folder step004} else {set folder step005}
  if {$config eq "s006block"} {set folder baseline}
  foreach f {dot_banked_core.v bank_ram.v} {read_verilog ../$folder/$f}
  if {[string match s004* $config]} {read_verilog ../step004/dot_banked_top.v;set top dot_banked_top} else {
   read_verilog ../step005/fc_int8_top.v;set top fc_int8_top
   if {[string match s006* $config]} {
    read_verilog ../step006/requant_i8.v;read_verilog ../step006/mlp2_top.v;set top mlp2_top
   }
  }
 }
 if {[string match s004* $config]} {
  set p [string index $config end]
  synth_design -top $top -generic LANES=$p -part xc7a100tcsg324-1 -mode out_of_context
 } else {synth_design -top $top -part xc7a100tcsg324-1 -mode out_of_context}
 create_clock -name clk -period 10.000 [get_ports clk]
 set util [report_utilization -return_string]
 set f [open ../util_${config}.rpt w];puts $f $util;close $f
 report_timing_summary -file ../timing_${config}.rpt
 set dsp [llength [get_cells -quiet -hier -filter {REF_NAME =~ DSP48*}]]
 set ff [llength [get_cells -quiet -hier -filter {REF_NAME =~ FD*}]]
 set ram [llength [get_cells -quiet -hier -filter {REF_NAME =~ RAMB*}]]
 set lut -1
 regexp {\| Slice LUTs\*\s*\|\s*([0-9]+)} $util match lut
 if {$lut<0} {error "missing LUT count"}
 set paths [get_timing_paths -delay_type max -max_paths 1]
 set slack [get_property SLACK $paths]
 puts $json "$sep\"$config\":\{\"Slice_LUTs\":$lut,\"FF\":$ff,\"DSP\":$dsp,\"RAMB_cells\":$ram,\"WNS_ns\":$slack\}"
 set sep ","
 puts "PASS MEMORY_SYNTH $config LUT=$lut FF=$ff DSP=$dsp RAM=$ram WNS=$slack"
 close_project
}
puts $json "\}\}"
close $json

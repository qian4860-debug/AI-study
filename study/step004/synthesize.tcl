set_param general.maxThreads 2
set json [open ../synthesis_results.json w]
puts $json "\{\"status\":\"PASS\",\"tool\":\"Vivado [version -short]\",\"part\":\"xc7a100tcsg324-1\",\"stage\":\"out_of_context_synthesis\",\"clock_period_ns\":10.0,\"configs\":\{"
set separator ""
foreach p {1 2 4} {
    create_project -in_memory -part xc7a100tcsg324-1
    read_verilog ../dot_banked_core.v
    read_verilog ../bank_ram.v
    read_verilog ../dot_banked_top.v
    synth_design -top dot_banked_top -generic LANES=$p -part xc7a100tcsg324-1 -mode out_of_context
    create_clock -name clk -period 10.000 [get_ports clk]
    set util [report_utilization -return_string]
    set fp [open ../util_p${p}.rpt w];puts $fp $util;close $fp
    report_timing_summary -file ../timing_p${p}.rpt
    set dsp [llength [get_cells -quiet -hier -filter {REF_NAME =~ DSP48*}]]
    set ff [llength [get_cells -quiet -hier -filter {REF_NAME =~ FD*}]]
    set ram [llength [get_cells -quiet -hier -filter {REF_NAME =~ RAMB*}]]
    set lut -1
    regexp {\| Slice LUTs\*\s*\|\s*([0-9]+)} $util match lut
    if {$lut<0} {error "Slice LUT count missing"}
    puts $json "$separator\"$p\":\{\"Slice_LUTs\":$lut,\"FF\":$ff,\"DSP\":$dsp,\"RAMB_cells\":$ram\}"
    set separator ","
    puts "PASS STEP004_SYNTH P=$p Slice_LUTs=$lut FF=$ff DSP=$dsp RAMB_cells=$ram"
    close_project
}
puts $json "\}\}"
close $json

"""Run exact software checks and actual RTL simulation; exits nonzero on failure."""
from pathlib import Path
import csv
import hashlib
import ast
import io
import json
import os
import random
import shutil
import subprocess
import sys
from reference import gemv, pack_gemv, convolution, pack_convolution, cycle_model

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
BUILD = ROOT/'build'
RTL = REPO/'lab3-2/BOARD/reference/rtl'


def run(cmd):
    p = subprocess.run([str(x) for x in cmd], cwd=BUILD, capture_output=True, text=True)
    (BUILD/(Path(str(cmd[0])).stem+'.log')).write_text(p.stdout+p.stderr, encoding='utf-8')
    if p.returncode:
        raise RuntimeError(p.stdout+p.stderr)
    return p.stdout+p.stderr


def simulate(top, files):
    iv, vv = shutil.which('iverilog'), shutil.which('vvp')
    if iv and vv:
        run([iv,'-g2012','-s',top,'-o',top+'.vvp',*files])
        return run([vv,top+'.vvp']), 'Icarus Verilog'
    binpath = Path(os.environ.get('VIVADO_BIN',r'D:\vivado\2025.1\Vivado\bin'))
    if not (binpath/'xvlog.bat').exists():
        raise RuntimeError('RTL simulator required: install Icarus or set VIVADO_BIN')
    run([binpath/'xvlog.bat','--sv',*files])
    run([binpath/'xelab.bat',top,'--timescale','1ns/1ps','-s',top+'_snapshot'])
    return run([binpath/'xsim.bat',top+'_snapshot','-runall']), 'Vivado Simulator 2025.1'


def software_checks(rng):
    path = REPO/'lab3-1/data_generator.py'
    # Execute only the upstream pure-Python serializers, avoiding its optional
    # NumPy dependency. Their source stays unmodified and tied to the Git SHA.
    tree = ast.parse(path.read_text(encoding='utf-8'))
    writers = ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef)
                              and n.name in ('write_input','write_weight','write_output')],type_ignores=[])
    upstream = {}
    exec(compile(writers,str(path),'exec'),upstream)
    class Matrix:
        def __init__(self,values):
            self.values=values
            self.shape=(len(values),len(values[0]))
        def __getitem__(self,key):
            r,c=key
            return self.values[r][c]
    shapes = [(1,1),(7,4),(10,5),(8,5),(7,7),(254,254)]
    shapes += [(m,rng.randint(1,m)) for m in range(2,18)]
    for m,n in shapes:
        a = [[rng.randrange(256) for _ in range(m)] for _ in range(m)]
        b = [[rng.randrange(256) for _ in range(n)] for _ in range(n)]
        out = convolution(a,b)
        flat_kernel=[v for row in b for v in row]
        for y,row in enumerate(out):
            for x,value in enumerate(row):
                patch=[v for source in a[y:y+n] for v in source[x:x+n]]
                assert value == sum(map(lambda pair: pair[0]*pair[1],zip(patch,flat_kernel)))
        aw,bw,cw = pack_convolution(a,b)
        streams=[]
        for func,values in [('write_input',a),('write_weight',b),('write_output',out)]:
            fd=io.StringIO()
            upstream[func](fd,Matrix(values))
            streams.append([int(v,16) for v in fd.getvalue().split()])
        raw,weights,outputs=streams
        assert aw == [int.from_bytes(bytes(raw[i:i+4]),'big') for i in range(len(raw)-3)]
        assert bw == [sum(weights[j+i] << (8*(3-i)) for i in range(4)) for j in range(0,len(weights),4)]
        assert cw == [sum(outputs[j+i] << (32*(3-i)) for i in range(4)) for j in range(0,len(outputs),4)]
        # Decode physical windows and lanes, including the row/column tails.
        for c in range(m):
            for r in range(m):
                assert aw[c*(m+3)+r] >> 24 == a[r][c]
        for r in range(n):
            for c in range(n):
                assert (bw[(r//4)*n+c] >> (8*(3-r%4))) & 255 == b[r][c]
        l=m-n+1
        for r in range(l):
            for c in range(((l+3)//4)*4):
                assert (cw[r*((l+3)//4)+c//4] >> (32*(3-c%4))) & 0xffffffff == (out[r][c] if c<l else 0)
    assert convolution([[255]*254 for _ in range(254)],[[255]*254 for _ in range(254)]) == [[4195152900]]
    assert convolution([[1,2,3],[4,5,6],[7,8,9]],[[1,2],[3,4]]) == [[37,47],[67,77]]
    # Known lane order values catch a shared encoder/decoder reversal.
    assert pack_gemv([[1],[2],[3],[4]],[-1]) == ([0x04030201],[255],[0xffffffff,0xfffffffe,0xfffffffd,0xfffffffc])
    assert pack_convolution([[1,2],[3,4]],[[1]])[0][0] == 0x01030000
    for a,b in [([],[]),([[128]],[0]),([[0]],[128]),([[1,2]],[1]),([[0]*254 for _ in range(254)],[0]*254)]:
        try: gemv(a,b)
        except ValueError: pass
        else: raise AssertionError('invalid GEMV accepted')
    return len(shapes)+2


def make_tb(cases):
    header = '''`timescale 1ns/1ps
module tb_gemv;
reg clk=0; always #5 clk=~clk;
reg rst_n=0,in_valid=0;
reg [7:0] K=0,M=0,N=1;
wire busy,A_ram_en,B_ram_en,C_ram_en,A_wr_en,B_wr_en,C_wr_en;
wire [15:0] A_index,B_index,C_index;
wire [31:0] A_data_in,B_data_in,A_data_out,B_data_out;
wire [127:0] C_data_in,C_data_out;
TPU dut(.*);
board_bram #(.DATA_WIDTH(32)) ma(clk,1'b0,1'b0,16'd0,32'd0,clk,A_ram_en,A_index,A_data_out);
board_bram #(.DATA_WIDTH(32)) mb(clk,1'b0,1'b0,16'd0,32'd0,clk,B_ram_en,B_index,B_data_out);
board_bram #(.DATA_WIDTH(128)) mc(clk,C_ram_en,C_wr_en,C_index,C_data_in,clk,1'b0,16'd0,C_data_out);
reg [127:0] golden[0:1023];
integer i,cycles,reads,writes,macs,fd,oldstate,oldrow,oldcol;
task idle_check;
begin
 if(A_ram_en!==0 || B_ram_en!==0 || C_ram_en!==0 || C_wr_en!==0 || A_wr_en!==0 || B_wr_en!==0)
   $fatal(1,"illegal idle enables or input write");
end endtask
task execute;
input integer id,rows,cols;
begin
 @(negedge clk); idle_check(); M=rows; K=cols; N=1; in_valid=1;
 @(posedge clk); #1; if(busy!==1) $fatal(1,"busy failed to assert");
 @(negedge clk); in_valid=0; M=8'hxx; K=8'hxx; N=8'hxx;
 cycles=0; reads=0; writes=0; macs=0;
 while(busy===1) begin
   if(cycles>rows*(2*cols+1)+2) $fatal(1,"timeout");
   oldstate=dut.state; oldrow=dut.row; oldcol=dut.col;
   if(A_wr_en!==0 || B_wr_en!==0) $fatal(1,"input write");
   if(A_ram_en) begin
     if(A_index >= ((rows+3)/4)*cols || B_index>=cols) $fatal(1,"read address");
     reads=reads+1;
   end
   if(C_ram_en) begin
     if(C_index>=rows || !C_wr_en || C_data_in!==golden[C_index]) $fatal(1,"write data/address");
     writes=writes+1;
   end
   if(oldstate==2) macs=macs+1;
   @(posedge clk); #1; cycles=cycles+1;
   if(id==0) $fdisplay(fd,"%0d,%0d,%0d,%0d,%0d",cycles,oldstate,oldrow,oldcol,$signed(dut.partial_sum));
   @(negedge clk);
 end
 if(busy!==0 || cycles!==rows*(2*cols+1)+1 || reads!==rows*cols || macs!==rows*cols || writes!==rows)
   $fatal(1,"counter mismatch");
 for(i=0;i<rows;i=i+1) if(mc.mem[i]!==golden[i]) $fatal(1,"C mismatch row %0d",i);
 idle_check();
 $display("PASS GEMV id=%0d M=%0d K=%0d cycles=%0d reads=%0d macs=%0d writes=%0d",id,rows,cols,cycles,reads,macs,writes);
end endtask
initial begin
 fd=$fopen("rtl_trace.csv","w");
 $fdisplay(fd,"cycle,state,row,k,acc");
 #1; rst_n=1; #1; rst_n=0; #1;
 idle_check(); @(negedge clk); rst_n=1;
'''
    body=[]
    for idx,(a,b) in enumerate(cases):
        aw,bw,cw=pack_gemv(a,b)
        for name,values,width in [('a',aw,8),('b',bw,8),('c',cw,32)]:
            (BUILD/f'{name}{idx}.hex').write_text('\n'.join(f'{v:0{width}x}' for v in values)+'\n')
        body += [f'$readmemh("a{idx}.hex",ma.mem,0,{len(aw)-1});',
                 f'$readmemh("b{idx}.hex",mb.mem,0,{len(bw)-1});',
                 f'$readmemh("c{idx}.hex",golden,0,{len(cw)-1});',
                 'for(i=0;i<1024;i=i+1) mc.mem[i]=128\'hdeadbeef;',
                 f'execute({idx},{len(a)},{len(b)});']
    # Interrupt between active clock edges. Discarded task must not write later.
    body += ['''@(negedge clk); M=2;K=3;N=1;in_valid=1;
 @(negedge clk); in_valid=0;
 repeat(3) @(negedge clk);
 #2; rst_n=0; #1;
 if(busy!==0 || dut.partial_sum!==0) $fatal(1,"async abort failed");
 idle_check(); @(negedge clk); rst_n=1;
 repeat(3) begin @(negedge clk); idle_check(); end
 $readmemh("a0.hex",ma.mem,0,2);
 $readmemh("b0.hex",mb.mem,0,2);
 $readmemh("c0.hex",golden,0,1);
 execute(999,2,3);
 $display("PASS RESET_ABORT_RESTART");
 $fclose(fd); $finish;
end
endmodule''']
    (BUILD/'tb_gemv.sv').write_text(header+'\n'.join(body))


def main():
    BUILD.mkdir(exist_ok=True)
    result={'status':'RUNNING','seed':20261015,'upstream_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()}
    result_path=ROOT/'results.json'
    result_path.write_text(json.dumps(result,indent=2))
    try:
        rng=random.Random(result['seed'])
        result['convolution_reference_cases']=software_checks(rng)
        cases=[([[1,-2,3],[-128,127,-1]],[-1,2,-3])]
        for m,k in [(1,1),(1,3),(3,1),(5,3),(7,17),(16,256-2),(254,1),(4,254),(17,13),(16,256-2)]:
            cases.append(([[rng.randint(-128,127) for _ in range(k)] for _ in range(m)], [rng.randint(-128,127) for _ in range(k)]))
        cases += [([[-128]*254],[-128]*254), ([[127]*254],[-128]*254), ([[0]*3 for _ in range(5)],[0]*3)]
        for _ in range(30):
            m,k=rng.randint(1,20),rng.randint(1,40)
            cases.append(([[rng.randint(-128,127) for _ in range(k)] for _ in range(m)],[rng.randint(-128,127) for _ in range(k)]))
        for a,b in cases:
            out,trace=cycle_model(a,b)
            assert out==gemv(a,b)
            assert len(trace)==len(a)*(2*len(b)+1)+1
        make_tb(cases)
        mac_log,tool=simulate('tb_mac',[RTL/'mac_pe.v',ROOT/'tb_mac.sv'])
        (BUILD/'tb_mac.log').write_text(mac_log,encoding='utf-8')
        assert 'PASS MAC checks=66045' in mac_log, mac_log
        log,_=simulate('tb_gemv',[RTL/'mac_pe.v',RTL/'TPU.v',RTL/'board_bram.v',BUILD/'tb_gemv.sv'])
        (BUILD/'tb_gemv.log').write_text(log,encoding='utf-8')
        lines=[l for l in log.splitlines() if l.startswith('PASS GEMV')]
        assert len(lines)==len(cases)+1 and 'PASS RESET_ABORT_RESTART' in log,log
        actual=list(csv.DictReader((BUILD/'rtl_trace.csv').open()))
        expected=cycle_model(*cases[0])[1]
        codes={'READ':1,'MAC':2,'WRITE':3,'DRAIN':4}
        assert len(actual)==len(expected)
        for got,want in zip(actual,expected):
            assert [int(got[k]) for k in ['cycle','state','row','k','acc']] == [want['cycle'],codes[want['state']],want['row'],want['k'],want['acc']],(got,want)
        (ROOT/'trace_example.csv').write_text((BUILD/'rtl_trace.csv').read_text())
        metrics=[]
        for line in lines:
            entry={k:int(v) for k,v in (s.split('=') for s in line.split()[2:])}
            entry['mac_per_cycle']=entry['macs']/entry['cycles']
            entry['bram_read_bytes']=entry['reads']*8
            entry['bram_write_bytes']=entry['writes']*16
            metrics.append(entry)
        result.update(status='PASS',simulator=tool,mac_checks=66045,gemv_cases=len(cases),restart_cases=1,cycle_trace_checked=True,metrics=metrics,
                      limitations=['No FPGA run, synthesis, STA or PPA measurement','Lab3-1 RTL scaffold remains unimplemented; convolution reference and packing checked only'])
        result['python']=sys.version
        result['source_sha256']={str(p.relative_to(REPO)):hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in [RTL/'TPU.v',RTL/'mac_pe.v',RTL/'board_bram.v',ROOT/'reference.py',ROOT/'verify.py',ROOT/'tb_mac.sv']}
    except Exception as e:
        result.update(status='FAIL',error=str(e))
        raise
    finally:
        result_path.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print(f"PASS: MAC={result['mac_checks']}, GEMV={len(cases)} + restart, convolution={result['convolution_reference_cases']}, trace=exact")


if __name__=='__main__': main()

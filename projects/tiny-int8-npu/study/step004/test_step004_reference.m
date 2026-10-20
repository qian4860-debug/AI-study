function test_step004_reference()
    diary('matlab_console.log');
    cleanup=onCleanup(@() diary('off'));
    addpath(fullfile(fileparts(mfilename('fullpath')),'..','step002'));
    cases=jsondecode(fileread('vectors.json'));
    for i=1:numel(cases)
        actual=dot_int8_reference(int8(cases(i).x),int8(cases(i).w));
        assert(actual==cases(i).expected,'Case %d mismatch.',i);
        % Independent strided-bank partial sums and final reduction.
        for lanes=[1 2 4]
            partial=zeros(1,lanes);
            for lane=1:lanes
                rows=lane:lanes:cases(i).K;
                partial(lane)=sum(double(cases(i).x(rows)).*double(cases(i).w(rows)));
            end
            assert(sum(partial)==actual,'Case %d lanes %d mapping mismatch.',i,lanes);
        end
    end
    result=struct('status','PASS','version',version,'cases',numel(cases), ...
        'bank_mapping_checks',3*numel(cases));
    fid=fopen('matlab_results.json','w');assert(fid~=-1);
    fprintf(fid,'%s\n',jsonencode(result));fclose(fid);
    fprintf('PASS MATLAB STEP004 cases=%d mapping_checks=%d\n',numel(cases),3*numel(cases));
end

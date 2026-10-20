function test_step003_reference()
    diary('matlab_console.log');
    cleanup = onCleanup(@() diary('off'));
    addpath(fullfile(fileparts(mfilename('fullpath')), '..', 'step002'));
    tasks = jsondecode(fileread('vectors.json'));
    for i=1:numel(tasks)
        actual = dot_int8_reference(int8(tasks(i).x),int8(tasks(i).w));
        assert(actual == tasks(i).expected, 'Task %d mismatch.',i);
    end
    result=struct('status','PASS','version',version,'task_checks',numel(tasks));
    fid=fopen('matlab_results.json','w'); assert(fid~=-1);
    fprintf(fid,'%s\n',jsonencode(result)); fclose(fid);
    fprintf('PASS MATLAB STEP003 tasks=%d\n',numel(tasks));
end

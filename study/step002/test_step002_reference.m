function test_step002_reference()
% Run from this directory after verify_step002.py has generated its vectors.
    diary('matlab_console.log');
    cleanup = onCleanup(@() diary('off'));
    assert(dot_int8_reference(int8(-128),int8(-128)) == 16384);
    assert(dot_int8_reference(int8([2 -3 4]),int8([1 2 -1])) == -8);
    assert(dot_int8_reference(int8(-128*ones(1,256)),int8(-128*ones(1,256))) == 4194304);
    assert(dot_int8_reference(int8(-128*ones(1,256)),int8(127*ones(1,256))) == -4161536);
    tasks = jsondecode(fileread('vectors.json'));
    for i = 1:numel(tasks)
        actual = dot_int8_reference(int8(tasks(i).x),int8(tasks(i).w));
        assert(actual == tasks(i).expected, 'Task %d mismatch.', i);
    end
    rejected = 0;
    invalid = {@() dot_int8_reference([],[]), ...
               @() dot_int8_reference(int8(ones(1,257)),int8(ones(1,257))), ...
               @() dot_int8_reference(int8([1 2]),int8(1)), ...
               @() dot_int8_reference([1 2],[1 2])};
    for i = 1:numel(invalid)
        try
            invalid{i}();
        catch
            rejected = rejected + 1;
        end
    end
    assert(rejected == numel(invalid));
    result = struct('status','PASS','version',version, ...
        'directed_checks',4,'completed_task_checks',numel(tasks), ...
        'invalid_input_checks',rejected);
    fid = fopen('matlab_results.json','w');
    assert(fid ~= -1);
    fprintf(fid,'%s\n',jsonencode(result));
    fclose(fid);
    fprintf('PASS MATLAB directed=4 tasks=%d invalid=4\n',numel(tasks));
end

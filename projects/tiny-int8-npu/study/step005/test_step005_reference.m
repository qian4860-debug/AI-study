function test_step005_reference()
    diary('matlab_console.log');cleanup=onCleanup(@() diary('off'));
    cases=jsondecode(fileread('vectors.json'));
    outputs=0;
    for i=1:numel(cases)
        W=reshape(int8(cases(i).w_flat),cases(i).K,cases(i).M).';
        result=fc_int8_reference(int8(cases(i).x),W,int32(cases(i).bias),logical(cases(i).relu));
        assert(isequal(double(result.dot(:)),double(cases(i).dot(:))));
        assert(isequal(double(result.pre(:)),double(cases(i).pre(:))));
        assert(isequal(double(result.output(:)),double(cases(i).expected(:))));
        outputs=outputs+cases(i).M;
    end
    rejected=0;
    invalid={@() fc_int8_reference(int8(1),int8(1),int32(0),1), ...
             @() fc_int8_reference(int8([1 2]),int8(1),int32(0),true), ...
             @() fc_int8_reference(int8(1),int8(ones(9,1)),int32(zeros(9,1)),true)};
    for i=1:numel(invalid)
        try, invalid{i}(); catch, rejected=rejected+1; end
    end
    assert(rejected==numel(invalid));
    meta=struct('status','PASS','version',version,'layers',numel(cases),'outputs',outputs,'invalid_checks',rejected);
    fid=fopen('matlab_results.json','w');assert(fid~=-1);
    fprintf(fid,'%s\n',jsonencode(meta));fclose(fid);
    fprintf('PASS MATLAB STEP005 layers=%d outputs=%d invalid=%d\n',numel(cases),outputs,rejected);
end

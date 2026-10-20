function test_step006_reference
% Double represents every signed33*uint16 product exactly (<2^48).
root=fileparts(mfilename('fullpath'));
a=readmatrix(fullfile(root,'build','quant_matlab.csv'));
p=a(:,1).*a(:,2)./(2.^a(:,3));
% Independent signed-floor formulation, rather than abs/sign RTL algorithm.
lo=floor(p);f=p-lo;
rounded=lo+(f>0.5 | (f==0.5 & mod(lo,2)~=0));
q=max(-128,min(127,rounded));sat=(rounded<-128 | rounded>127);
tie=(f==0.5);
assert(all(q==a(:,4)) && all(sat==a(:,5)) && all(tie==a(:,6)),'quant mismatch');
fd=fopen(fullfile(root,'build','quant_matlab.csv'),'rb');bytes=fread(fd,Inf,'*uint8');fclose(fd);
md=java.security.MessageDigest.getInstance('SHA-256');md.update(bytes);
digest=lower(reshape(dec2hex(typecast(md.digest(),'uint8'),2).',1,[]));
r=struct('status','PASS','version',version,'quant_checks',size(a,1),'input_sha256',digest);
fd=fopen(fullfile(root,'matlab_results.json'),'w');fprintf(fd,'%s',jsonencode(r));fclose(fd);
fprintf('PASS STEP006 MATLAB quant_checks=%d\n',size(a,1));
end

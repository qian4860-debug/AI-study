function y = dot_int8_reference(x, w)
% Exact mathematical oracle. No handshake or cycle behavior is modeled.
    assert(isa(x, 'int8') && isa(w, 'int8'), 'Inputs must be int8.');
    assert(isvector(x) && isvector(w), 'Inputs must be vectors.');
    assert(numel(x) == numel(w), 'Lengths must match.');
    K = numel(x);
    assert(K >= 1 && K <= 256, 'Length must be in 1..256.');
    products = int32(x(:)) .* int32(w(:));
    y = sum(double(products));
    assert(y >= -2^23 && y <= 2^23-1, 'Result exceeds signed 24 bits.');
end

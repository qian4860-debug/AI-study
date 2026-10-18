"""Exact integer oracles and NYCU memory layouts. No quantization/scales/bias."""
def matrix(a, lo, hi):
    if not a or not a[0] or any(len(r) != len(a[0]) for r in a):
        raise ValueError('nonempty rectangular matrix required')
    if any(type(v) is not int or not lo <= v <= hi for r in a for v in r):
        raise ValueError('element outside specified integer range')


def gemv(a, b, hardware=True):
    matrix(a, -128, 127)
    m, k = len(a), len(a[0])
    if len(b) != k or any(type(v) is not int or not -128 <= v <= 127 for v in b):
        raise ValueError('INT8 vector of length K required')
    if not (1 <= m <= 254 and 1 <= k <= 254):
        raise ValueError('NYCU dimensions outside 1..254')
    if hardware and ((m+3)//4)*k > 1024:
        raise ValueError('board A BRAM capacity exceeded')
    return [sum(x*y for x, y in zip(row, b)) for row in a]


def pack(values, bits, msb_first=False):
    values = list(values)
    if msb_first:
        values.reverse()
    return sum((v & ((1 << bits)-1)) << (bits*i) for i, v in enumerate(values))


def pack_gemv(a, b):
    c = gemv(a, b)
    m, k = len(a), len(b)
    aw = [pack((a[block*4+l][j] if block*4+l < m else 0 for l in range(4)), 8)
          for block in range((m+3)//4) for j in range(k)]
    return aw, [v & 255 for v in b], [v & 0xffffffff for v in c]


def convolution(image, kernel):
    matrix(image, 0, 255)
    matrix(kernel, 0, 255)
    m, n = len(image), len(kernel)
    if len(image[0]) != m or len(kernel[0]) != n or not 1 <= n <= m <= 254:
        raise ValueError('square matrices with 1 <= N <= M <= 254 required')
    l = m-n+1
    return [[sum(image[y+r][x+c]*kernel[r][c] for r in range(n) for c in range(n))
             for x in range(l)] for y in range(l)]


def pack_convolution(image, kernel):
    out = convolution(image, kernel)
    m, n, l = len(image), len(kernel), len(out)
    # A addresses are overlapping four-byte windows, NOT disjoint 32-bit words.
    raw = [image[r][c] if r < m else 0 for c in range(m) for r in range(m+3)]
    aw = [pack(raw[i:i+4], 8, True) for i in range(len(raw)-3)]
    bw = [pack((kernel[t*4+r][c] if t*4+r < n else 0 for r in range(4)), 8, True)
          for t in range((n+3)//4) for c in range(n)]
    cw = [pack((out[r][t*4+i] if t*4+i < l else 0 for i in range(4)), 32, True)
          for r in range(l) for t in range((l+3)//4)]
    return aw, bw, cw


def cycle_model(a, b):
    """GEMV baseline: synchronous read, MAC, per-row write, final drain."""
    aw, bw, _ = pack_gemv(a, b)
    m, k = len(a), len(b)
    rows, trace = [], []
    acc = 0
    for r in range(m):
        for j in range(k):
            addr = (r//4)*k+j
            trace.append(dict(cycle=len(trace)+1, state='READ', row=r, k=j,
                              a_index=addr, b_index=j, acc=acc))
            av = (aw[addr] >> (8*(r%4))) & 255
            bv = bw[j] & 255
            av = av-256 if av >= 128 else av
            bv = bv-256 if bv >= 128 else bv
            acc = av*bv if j == 0 else acc+av*bv
            trace.append(dict(cycle=len(trace)+1, state='MAC', row=r, k=j, acc=acc))
        rows.append(acc)
        trace.append(dict(cycle=len(trace)+1, state='WRITE', row=r, k=k-1, acc=acc))
    trace.append(dict(cycle=len(trace)+1, state='DRAIN', row=m-1, k=k-1, acc=rows[-1]))
    return rows, trace

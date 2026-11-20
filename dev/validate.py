"""Strict structural validator for the generated U3D + 3D PDF test output."""
import struct, zlib, sys

sys.path.insert(0, '/workspace/sketchup-3d-pdf-exporter/dev')
from reference_mirror import cube_groups, build, build_pdf, BLOCK_FILE_HEADER, BLOCK_MODIFIER_CHAIN

ERRORS = []
CHECKS = [0]


def check(cond, msg):
    CHECKS[0] += 1
    if not cond:
        ERRORS.append(msg)
    return cond


class Reader:
    def __init__(self, buf, base=0):
        self.buf = buf
        self.pos = base

    def u8(self):
        v = self.buf[self.pos]
        self.pos += 1
        return v

    def u16(self):
        v = struct.unpack_from('<H', self.buf, self.pos)[0]
        self.pos += 2
        return v

    def u32(self):
        v = struct.unpack_from('<I', self.buf, self.pos)[0]
        self.pos += 4
        return v

    def u64(self):
        v = struct.unpack_from('<Q', self.buf, self.pos)[0]
        self.pos += 8
        return v

    def f32(self):
        v = struct.unpack_from('<f', self.buf, self.pos)[0]
        self.pos += 4
        return v

    def f64(self):
        v = struct.unpack_from('<f', self.buf, self.pos)[0] if False else struct.unpack_from('<d', self.buf, self.pos)[0]
        self.pos += 8
        return v

    def u32x3(self):
        return (self.u32(), self.u32(), self.u32())

    def string(self):
        n = self.u16()
        s = self.buf[self.pos:self.pos + n]
        self.pos += n
        return s.decode('utf-8')


BLOCK_NAMES = {
    0x00443355: 'FileHeader', 0xFFFFFF12: 'FileReference', 0xFFFFFF14: 'ModifierChain',
    0xFFFFFF15: 'PriorityUpdate', 0xFFFFFF21: 'GroupNode', 0xFFFFFF22: 'ModelNode',
    0xFFFFFF23: 'LightNode', 0xFFFFFF24: 'ViewNode', 0xFFFFFF31: 'CLODMeshDeclaration',
    0xFFFFFF3B: 'CLODBaseMeshContinuation', 0xFFFFFF3C: 'CLODMeshContinuation',
    0xFFFFFF45: 'ShadingModifier', 0xFFFFFF53: 'LitTextureShader',
    0xFFFFFF54: 'MaterialResource', 0xFFFFFF55: 'TextureDeclaration',
    0xFFFFFF5C: 'TextureContinuation',
}


def parse_block(r, depth=0):
    """Parse one U3D block; returns (name, info). Leaves r at 4-aligned position."""
    check(r.pos % 4 == 0, 'block at offset %d is not 4-byte aligned' % r.pos)
    start = r.pos
    btype = r.u32()
    dsize = r.u32()
    msize = r.u32()
    check(msize == 0, 'unexpected metaDataSize %d for block %s' % (msize, BLOCK_NAMES.get(btype, hex(btype))))
    data_end = r.pos + dsize

    name = BLOCK_NAMES.get(btype, 'Unknown(%s)' % hex(btype))
    info = {}

    if btype == BLOCK_FILE_HEADER:
        maj, mnr = r.u16(), r.u16()
        check(maj == 0, 'file header major version must be 0, got %d' % maj)
        profile = r.u32()
        decl_size = r.u32()
        fsize = r.u64()
        enc = r.u32()
        scale = r.f64()
        info.update(major=maj, minor=mnr, profile=profile, decl_size=decl_size,
                    file_size=fsize, encoding=enc, scale=scale)
    elif btype == BLOCK_MODIFIER_CHAIN:
        cname = r.string()
        ctype = r.u32()
        r.u32()
        if r.pos % 4:
            r.pos += 4 - r.pos % 4
        mcount = r.u32()
        consumed = []
        for _ in range(mcount):
            consumed.append(parse_block(r, depth + 1))
        check(r.pos == data_end,
              'modifier chain %s: contained blocks end at %d, data size says %d'
              % (cname, r.pos, data_end))
        info.update(name=cname, type=ctype, count=mcount, modifiers=consumed)
    elif btype == 0xFFFFFF22:
        nname = r.string()
        pcount = r.u32()
        resname = r.string()
        vis = r.u32()
        check(pcount == 0, 'model node parent count expected 0')
        info.update(name=nname, resource=resname, visibility=vis)
    elif btype == 0xFFFFFF31:
        mname = r.string()
        check(r.u32() == 0, 'CLOD declaration chain index must be 0')
        mesh_attrs = r.u32()
        face_count = r.u32()
        pos_count = r.u32()
        nrm_count = r.u32()
        dif_count = r.u32()
        spec_count = r.u32()
        txc_count = r.u32()
        shading_count = r.u32()
        shadings = []
        for _ in range(shading_count):
            attrs = r.u32()
            layers = r.u32()
            dims = [r.u32() for _ in range(layers)]
            orig = r.u32()
            shadings.append((attrs, layers, dims, orig))
        check(dif_count == 0 and spec_count == 0 and txc_count == 0,
              'unexpected color/texture resources in declaration')
        min_res = r.u32()
        max_res = r.u32()
        check(min_res == pos_count and max_res == pos_count,
              'CLOD resolution mismatch: min=%d max=%d positions=%d' % (min_res, max_res, pos_count))
        r.u32(); r.u32(); r.u32()
        info_quants = [r.f32() for _ in range(5)]
        r.f32(); r.f32(); r.f32()
        bone_count = r.u32()
        check(bone_count == 0, 'unexpected bone count %d' % bone_count)
        check(all(x > 0 for x in info_quants), 'inverse quant factors should be non-zero')
        check(r.pos == data_end,
              'CLOD declaration %s: consumed %d, dataSize %d' % (mname, r.pos, data_end))
        info.update(name=mname, attrs=mesh_attrs, face_count=face_count,
                    position_count=pos_count, normal_count=nrm_count, shadings=shadings)
    elif btype == 0xFFFFFF3B:
        mname = r.string()
        check(r.u32() == 0, 'base mesh continuation chain index must be 0')
        base_faces = r.u32()
        base_pos = r.u32()
        base_nrm = r.u32()
        check(r.u32() == 0 and r.u32() == 0 and r.u32() == 0,
              'unexpected color/tex counts in base mesh continuation')
        positions = []
        for _ in range(base_pos):
            positions.append((r.f32(), r.f32(), r.f32()))
        normals = []
        for _ in range(base_nrm):
            normals.append((r.f32(), r.f32(), r.f32()))
        faces = []
        for _ in range(base_faces):
            sid = r.u32()
            corners = []
            for _ in range(3):
                corners.append((r.u32(), r.u32() if not info.get('_exclude_normals') else None))
            faces.append((sid, corners))
        for _, corners in faces:
            for c in corners:
                check(c[0] < base_pos, 'position index %d out of range' % c[0])
                if c[1] is not None:
                    check(c[1] < base_nrm, 'normal index %d out of range' % c[1])
        check(r.pos == data_end,
              'base mesh continuation %s: consumed %d, dataSize %d' % (mname, r.pos - start, data_end - start))
        info.update(name=mname, faces=faces, base_pos=base_pos, base_nrm=base_nrm, mesh='ok')
        got = r.pos
        check(got == data_end, 'base mesh continuation consumed != dataSize')
    elif btype == 0xFFFFFF45:
        cname = r.string()
        r.u32()
        r.u32()
        lists = r.u32()
        counts = [r.u32() for _ in range(lists)]
        shaders = []
        for c in counts:
            for _ in range(c):
                shaders.append(r.string())
        check(r.pos == data_end, 'shading modifier consumed != dataSize')
        info.update(name=cname, shader_lists=counts, shaders=shaders)
    elif btype == 0xFFFFFF53:
        sname = r.string()
        attrs = r.u32()
        r.f32()
        r.u32(); r.u32(); r.u32(); r.u32(); r.u32()
        mat = r.string()
        check(r.pos == data_end, 'lit texture shader %s consumed != dataSize' % sname)
        info.update(name=sname, attrs=attrs, material=mat)
    elif btype == 0xFFFFFF54:
        mname = r.string()
        attrs = r.u32()
        amb = (r.f32(), r.f32(), r.f32())
        dif = (r.f32(), r.f32(), r.f32())
        spec = (r.f32(), r.f32(), r.f32())
        emi = (r.f32(), r.f32(), r.f32())
        refl = r.f32()
        opac = r.f32()
        check(r.pos == data_end, 'material resource %s consumed != dataSize' % mname)
        info.update(name=mname, attrs=attrs, diffuse=dif, opacity=opac, ambient=amb)
    else:
        check(btype in BLOCK_NAMES, 'unknown block type %s at %d' % (hex(btype), start))
        return name, info

    check(r.pos == data_end, 'block %s: consumed to %d but dataSize ends at %d' % (name, r.pos, data_end))
    # padding to next 4-aligned offset (end of whole buffer or next block)
    if r.pos % 4:
        captured = r.buf[r.pos:r.pos + (4 - r.pos % 4)]
        check(all(b == 0 for b in captured), 'non-zero padding bytes at %d' % r.pos)
        r.pos += 4 - r.pos % 4
    return name, info


def walk_u3d(u3d):
    top_level, all_blocks = [], []

    def add(name, info, flat=True):
        if flat:
            top_level.append((name, info))
        all_blocks.append((name, info))
        if name == 'ModifierChain':
            for n, i in info['modifiers']:
                add(n, i, flat=False)
                if n == 'ModifierChain':
                    raise AssertionError('unexpected chain nesting depth 2')

    def walk(r):
        while r.pos < len(u3d):
            name, info = parse_block(r)
            add(name, info)

    r = Reader(u3d)
    check((lambda b: struct.unpack_from('<I', b, 0)[0])(u3d) == BLOCK_FILE_HEADER, 'first block must be file header')
    walk(r)
    hdr_info = next(i for n, i in all_blocks if n == 'FileHeader')
    return top_level, all_blocks, hdr_info


def validate_u3d(u3d):
    blocks, nested, hdr = walk_u3d(u3d)
    names = [b[0] for b in nested]
    top = [n for n, _ in blocks]
    check(hdr['profile'] & 0x4 and hdr['profile'] & 0x8, 'profile flags')
    check(hdr['encoding'] == 106, 'encoding')
    check(abs(hdr['scale'] - 0.0254) < 1e-9, 'unit scale')

    # declaration size = all blocks after the header block before first continuation
    decl_bytes = 0
    seen_cont = False
    r2 = Reader(u3d)
    while r2.pos < len(u3d):
        bstart = r2.pos
        name, info = parse_block(r2)
        btotal = r2.pos - bstart
        if name in ('CLODBaseMeshContinuation', 'CLODMeshContinuation'):
            seen_cont = True
        elif name != 'FileHeader' and not seen_cont:
            decl_bytes += btotal
    check(hdr['decl_size'] == decl_bytes,
          'declarationSize %d != computed declaration bytes %d' % (hdr['decl_size'], decl_bytes))
    check(hdr['file_size'] == len(u3d),
          'fileSize %d != actual %d' % (hdr['file_size'], len(u3d)))
    check(top[1] == 'ModifierChain' and top[2] == 'ModifierChain', 'two modifier chains after header')
    node_chain = blocks[1][1]
    res_chain = blocks[2][1]
    check(node_chain['type'] == 0 and res_chain['type'] == 1, 'chain types 0 and 1')
    mod_names = [n for n, _ in node_chain['modifiers']]
    check(mod_names == ['ModelNode', 'ShadingModifier'], 'node chain: model node then shading modifier')
    check([n for n, _ in res_chain['modifiers']] == ['CLODMeshDeclaration'], 'resource chain contains CLOD decl')

    decl = next(i for n, i in nested if n == 'CLODMeshDeclaration')
    base = next(i for n, i in nested if n == 'CLODBaseMeshContinuation')
    check(decl['face_count'] == len(base['faces']), 'face count consistency')
    check(decl['position_count'] == base['base_pos'], 'position count consistency')
    check(decl['normal_count'] == base['base_nrm'], 'normal count consistency')

    shaders = {i['name']: i for n, i in nested if n == 'LitTextureShader'}
    materials = {i['name']: i for n, i in nested if n == 'MaterialResource'}
    shading = next(i for n, i in nested if n == 'ShadingModifier')
    n_lists = len(shading['shader_lists'])
    check(n_lists == len(decl['shadings']), 'shader lists vs shading descriptions')
    for i, sname in enumerate(shading['shaders']):
        check(sname in shaders, 'shader %s declared' % sname)
        mat = shaders[sname]['material']
        check(mat in materials, 'material %s for %s declared' % (mat, sname))
    for sid, corners in base['faces']:
        check(sid < n_lists, 'face shading id %d in range' % sid)
    used_pos = set(c[0] for _, cc in base['faces'] for c in cc)
    check(len(used_pos) == base['base_pos'], 'no orphan positions (dedupe worked)')
    return blocks, nested, hdr


def validate_pdf(pdf):
    check(pdf.startswith(b'%PDF-1.7'), 'pdf header')
    xref_pos = int(pdf.rsplit(b'startxref\n', 1)[1].split(b'\n')[0])
    check(pdf[xref_pos:xref_pos + 4] == b'xref', 'startxref points at xref table')

    # offsets from xref
    rows = pdf[xref_pos:].split(b'\n')
    n_objs = int(rows[1].split()[1])
    offs = {}
    for i in range(1, n_objs):
        row = rows[2 + i]
        check(len(row) == 19, 'xref row %d length 19 (+EOL = 20)' % i)
        check(row.endswith(b'n '), 'xref row %d in-use entry with padding' % i)
        offs[i] = int(row[:10])

    for obj_num, off in offs.items():
        expected = b'%d 0 obj' % obj_num
        check(pdf[off:off + len(expected)] == expected,
              'xref offset for obj %d points at correct object' % obj_num)

    # extract obj 7 (u3d stream) and validate independently
    o7 = offs[7]
    ms = pdf.index(b'<< /Type /3D /Subtype /U3D /Length ', o7)
    mlen = pdf.index(b' >>', ms)
    length = int(pdf[ms + len(b'<< /Type /3D /Subtype /U3D /Length '):mlen])
    sstart = pdf.index(b'stream\n', o7) + len(b'stream\n')
    u3d = pdf[sstart:sstart + length]
    validate_u3d(u3d)

    # inflate content stream
    o5 = offs[5]
    cl = pdf.index(b'/Length ', o5) + len(b'/Length ')
    clen = int(pdf[cl:pdf.index(b' ', cl)])
    cs = pdf.index(b'stream\n', o5) + len(b'stream\n')
    decoded = zlib.decompress(pdf[cs:cs + clen])
    check(b'Tj' in decoded and b'/F1' in decoded, 'content stream shows text')
    check(b'/OwnerSwitch' not in decoded, 'sane content')

    for key in [b'/Subtype /3D', b'/3DD 7 0 R', b'/C2W [', b'/CO [', b'/AAC 45',
                b'/LS << /Type /3DLightingScheme /Subtype /Headlamp >>',
                b'/BG << /Type /3DBG /C [1 1 1] >>', b'/3DA << /A /PO /DIS /I /TB true >>']:
        check(key in pdf, 'annotation key present: %s' % key.decode('utf-8'))

    trailer = pdf[pdf.index(b'trailer'):]
    check(b'/Size %d' % n_objs in trailer, 'trailer size matches')
    check(b'/Root 1 0 R' in trailer, 'trailer root')
    check(pdf.rstrip().endswith(b'%%EOF'), 'EOF marker')


if __name__ == '__main__':
    u3d = build(cube_groups())
    pdf = build_pdf(u3d, 'Test Cube (Export)', [[0, 0, 0], [1, 1, 1]])
    blocks, nested, hdr = validate_u3d(u3d)
    print('U3D blocks:', [n for n, _ in blocks])
    validate_pdf(pdf)
    if ERRORS:
        print('FAILED checks: %d passed, %d failed' % (CHECKS[0] - len(ERRORS), len(ERRORS)))
        for e in ERRORS:
            print(' -', e)
        sys.exit(1)
    print('\nAll %d checks passed.' % CHECKS[0])

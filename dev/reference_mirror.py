import struct, zlib, sys

# Faithful Python transliteration of the Ruby plugin's binary writers
# (Sketchup3dPdfExporter::Binary / U3dBuilder / PdfBuilder) for validation.

NODE_CHAIN_NAME = b'SketchupModel'
RESOURCE_CHAIN_NAME = b'SketchupModelResource'

BLOCK_FILE_HEADER = 0x00443355
BLOCK_MODIFIER_CHAIN = 0xFFFFFF14
BLOCK_MODEL_NODE = 0xFFFFFF22
BLOCK_CLOD_MESH_DECLARATION = 0xFFFFFF31
BLOCK_CLOD_BASE_MESH_CONTINUATION = 0xFFFFFF3B
BLOCK_SHADING_MODIFIER = 0xFFFFFF45
BLOCK_LIT_TEXTURE_SHADER = 0xFFFFFF53
BLOCK_MATERIAL_RESOURCE = 0xFFFFFF54

MIB_UTF8 = 106
PROFILE = 0x00000004 | 0x00000008
INCHES_TO_METERS = 0.0254
FILE_HEADER_BLOCK_SIZE = 44


def bin(s):
    if isinstance(s, str):
        return s.encode('utf-8')
    return s


def u16(v):
    return struct.pack('<H', v)


def u32(v):
    return struct.pack('<I', v & 0xFFFFFFFF)


def f32(v):
    return struct.pack('<f', v)


def f64(v):
    return struct.pack('<d', v)


def f32x3(x, y, z):
    return f32(x) + f32(y) + f32(z)


def string(text):
    b = bin(text)
    return u16(len(b)) + b


def block(block_type, data):
    body = u32(block_type) + u32(len(data)) + u32(0) + data
    rem = len(body) % 4
    if rem:
        body += b'\x00' * (4 - rem)
    return body


def modifier_chain(name, chain_type, modifier_blocks):
    data = string(name)
    data += u32(chain_type) + u32(0)
    local = 2 + len(bin(name)) + 8
    if (local % 4):
        data += b'\x00' * (4 - local % 4)
    data += u32(len(modifier_blocks))
    for m in modifier_blocks:
        data += m
    return block(BLOCK_MODIFIER_CHAIN, data)


def shader_name(i):
    return 'Shader_%d' % i


def material_name(i):
    return 'Material_%d' % i


def build(groups):
    groups = [g for g in groups if g['triangles']]
    assert groups, 'No exportable faces'

    positions, normals, faces = [], [], []
    position_cache, normal_cache = {}, {}
    for g in groups:
        for tri in g['triangles']:
            corner_indices = []
            for p in tri[0:3]:
                idx = position_cache.get(p)
                if idx is None:
                    idx = len(positions)
                    position_cache[p] = idx
                    positions.append(p)
                corner_indices.append(idx)
            nkey = tri[3]
            nidx = normal_cache.get(nkey)
            if nidx is None:
                nidx = len(normals)
                normal_cache[nkey] = nidx
                normals.append(nkey)
            faces.append((g['shading_id'], corner_indices, nidx))

    declaration = write_node_modifier_chain(groups)
    declaration += write_resource_modifier_chain(len(faces), len(positions), len(normals), groups)
    for g in groups:
        declaration += write_lit_texture_shader(g)
    for g in groups:
        declaration += write_material_resource(g)
    continuation = write_base_mesh_continuation(positions, normals, faces)

    file_size = FILE_HEADER_BLOCK_SIZE + len(declaration) + len(continuation)
    header = file_header_block(len(declaration), file_size)
    return header + declaration + continuation


def file_header_block(declaration_size, file_size):
    data = u16(0) + u16(0)
    data += u32(PROFILE)
    data += u32(declaration_size)
    data += u32(file_size) + u32(0)
    data += u32(MIB_UTF8)
    data += f64(INCHES_TO_METERS)
    return block(BLOCK_FILE_HEADER, data)


def write_node_modifier_chain(groups):
    model_node = block(BLOCK_MODEL_NODE, model_node_data())
    shading_modifier = block(BLOCK_SHADING_MODIFIER, shading_modifier_data(groups))
    return modifier_chain(NODE_CHAIN_NAME, 0, [model_node, shading_modifier])


def model_node_data():
    return string(NODE_CHAIN_NAME) + u32(0) + string(RESOURCE_CHAIN_NAME) + u32(3)


def shading_modifier_data(groups):
    data = string(NODE_CHAIN_NAME) + u32(1) + u32(1) + u32(len(groups))
    for g in groups:
        data += u32(1)
    for g in groups:
        data += string(shader_name(g['shading_id']))
    return data


def write_resource_modifier_chain(face_count, position_count, normal_count, groups):
    data = string(RESOURCE_CHAIN_NAME) + u32(0)
    data += u32(0) + u32(face_count) + u32(position_count) + u32(normal_count)
    data += u32(0) + u32(0) + u32(0)
    data += u32(len(groups))
    for g in groups:
        data += u32(0) + u32(0) + u32(g['shading_id'])
    data += u32(position_count) + u32(position_count)
    data += u32(300) + u32(300) + u32(300)
    data += f32(1.0) * 1 + f32(1.0) + f32(1.0) + f32(1.0) + f32(1.0)
    data += f32(0.0) + f32(0.0) + f32(0.0)
    data += u32(0)
    clod = block(BLOCK_CLOD_MESH_DECLARATION, data)
    return modifier_chain(RESOURCE_CHAIN_NAME, 1, [clod])


def write_lit_texture_shader(g):
    data = string(shader_name(g['shading_id']))
    data += u32(0x1) + f32(0.0) + u32(0x00000617) + u32(0x00000606) + u32(0x1) + u32(0) + u32(0)
    data += string(material_name(g['shading_id']))
    return block(BLOCK_LIT_TEXTURE_SHADER, data)


def write_material_resource(g):
    r, g_, b = g['diffuse']
    data = string(material_name(g['shading_id'])) + u32(0x37)
    data += f32x3(r * 0.5, g_ * 0.5, b * 0.5)
    data += f32x3(r, g_, b)
    data += f32x3(0.1, 0.1, 0.1)
    data += f32x3(0.0, 0.0, 0.0)
    data += f32(0.1) + f32(g['opacity'])
    return block(BLOCK_MATERIAL_RESOURCE, data)


def write_base_mesh_continuation(positions, normals, faces):
    data = string(RESOURCE_CHAIN_NAME) + u32(0)
    data += u32(len(faces)) + u32(len(positions)) + u32(len(normals))
    data += u32(0) + u32(0) + u32(0)
    for p in positions:
        data += f32x3(p[0], p[1], p[2])
    for n in normals:
        data += f32x3(n[0], n[1], n[2])
    for sid, corners, nidx in faces:
        data += u32(sid)
        for i in range(3):
            data += u32(corners[i]) + u32(nidx)
    return block(BLOCK_CLOD_BASE_MESH_CONTINUATION, data)


def num(v):
    s = '%.4f' % v
    if '.' in s:
        s = s.rstrip('0').rstrip('.')
    return s


def camera_view(bbox):
    center = [(bbox[0][i] + bbox[1][i]) * 0.5 for i in range(3)]
    extent = [abs(bbox[1][i] - bbox[0][i]) for i in range(3)]
    radius = max(extent) * 0.5 or 1.0

    def normalize(v):
        ln = (v[0] ** 2 + v[1] ** 2 + v[2] ** 2) ** 0.5
        if ln < 1e-12:
            ln = 1.0
        return [v[0] / ln, v[1] / ln, v[2] / ln]

    def reject_axis(v, axis):
        d = v[0] * axis[0] + v[1] * axis[1] + v[2] * axis[2]
        r = [v[0] - d * axis[0], v[1] - d * axis[1], v[2] - d * axis[2]]
        if abs(r[0]) + abs(r[1]) + abs(r[2]) <= 1e-9:
            r = [0.0, 0.0, 1.0] if abs(axis[2]) < 0.9 else [1.0, 0.0, 0.0]
        return r

    def cross(a, b):
        return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]

    dirv = normalize([1.0, -1.2, 0.9])
    eye = [center[i] + dirv[i] * radius * 3.0 for i in range(3)]
    z_axis = dirv
    y_axis = normalize(reject_axis([0.0, 0.0, 1.0], z_axis))
    x_axis = cross(y_axis, z_axis)
    c2w = [x_axis[0], y_axis[0], z_axis[0], eye[0],
           x_axis[1], y_axis[1], z_axis[1], eye[1],
           x_axis[2], y_axis[2], z_axis[2], eye[2]]
    return c2w, center


def deflated(data):
    return zlib.compress(data)


def build_pdf(u3d, title, bbox):
    u3d = bin(u3d)
    c2w, co = camera_view(bbox)
    title_bytes = title.encode('ascii', 'replace').replace(b'\\', b'\\\\').replace(b'(', b'\\(').replace(b')', b'\\)')

    content = b'q 1 1 1 rg 0 0 842 595 re f Q\n'
    content += b'BT /F1 18 Tf 0.1 0.1 0.1 rg 40 566 Td (' + title_bytes + b') Tj ET\n'
    content += b'BT /F1 9 Tf 0.35 0.35 0.35 rg 40 550 Td (Interactive 3D content - open with Adobe Acrobat or Adobe Reader) Tj ET\n'
    content_stream = deflated(content)

    objects = {}
    objects[1] = b'<< /Type /Catalog /Pages 2 0 R /ViewerPreferences << /DisplayDocTitle true >> >>'
    objects[2] = b'<< /Type /Pages /Count 1 /Kids [3 0 R] >>'
    objects[3] = b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 842 595] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R /Annots [6 0 R] >>'
    objects[4] = b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'
    objects[5] = b'<< /Length %d /Filter /FlateDecode >>\nstream\n' % len(content_stream) + content_stream + b'\nendstream'

    annot = b'<< /Type /Annot /Subtype /3D /F 4 /Rect [36 36 806 544] /3DA << /A /PO /DIS /I /TB true >> /3DV << /C2W ['
    annot += ' '.join(num(v) for v in c2w).encode()
    annot += b'] /CO ['
    annot += ' '.join(num(v) for v in co).encode()
    annot += b'] /AAC 45 /MS /M /LS << /Type /3DLightingScheme /Subtype /Headlamp >> /BG << /Type /3DBG /C [1 1 1] >> >> /3DD 7 0 R >>'
    objects[6] = annot

    objects[7] = b'<< /Type /3D /Subtype /U3D /Length %d >>\nstream\n' % len(u3d) + u3d + b'\nendstream'
    objects[8] = b'<< /Title (' + title_bytes + b') /Producer (SketchUp 3D PDF Exporter) >>'

    out = b'%PDF-1.7\n%\xe2\xe3\xcf\xd3\n'
    offsets = {}
    for i in sorted(objects):
        offsets[i] = len(out)
        out += b'%d 0 obj\n' % i + objects[i] + b'\nendobj\n'

    xref_offset = len(out)
    count = max(objects) + 1
    out += b'xref\n0 %d\n' % count
    out += b'0000000000 65535 f \n'
    for i in range(1, count):
        if i in offsets:
            out += ('%010d 00000 n ' % offsets[i]).encode() + b'\n'
        else:
            out += b'0000000000 65535 f \n'
    out += b'trailer\n<< /Size %d /Root 1 0 R /Info 8 0 R >>\n' % count
    out += b'startxref\n%d\n%%%%EOF\n' % xref_offset
    return out


# ---- test dataset: unit cube, two materials, 12 triangles, 8 corners, 2 normals ----
def cube_groups():
    P = [
        (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (1.0, 1.0, 1.0), (0.0, 1.0, 1.0),
    ]
    quads = [
        (0, 3, 2, 1, [0.0, 0.0, -1.0]), (4, 5, 6, 7, [0.0, 0.0, 1.0]),
        (0, 1, 5, 4, [0.0, -1.0, 0.0]), (3, 7, 6, 2, [0.0, 1.0, 0.0]),
        (1, 2, 6, 5, [1.0, 0.0, 0.0]), (0, 4, 7, 3, [-1.0, 0.0, 0.0]),
    ]
    tris_red, tris_blue = [], []
    for qi, (a, b, c, d, n) in enumerate(quads):
        for t in ((P[a], P[b], P[c]), (P[a], P[c], P[d])):
            (tris_red if qi % 2 == 0 else tris_blue).append([t[0], t[1], t[2], tuple(n)])
    return [
        {'name': 'red', 'diffuse': [0.8, 0.1, 0.1], 'opacity': 1.0, 'shading_id': 0, 'triangles': tris_red},
        {'name': 'blue', 'diffuse': [0.1, 0.1, 0.8], 'opacity': 0.5, 'shading_id': 1, 'triangles': tris_blue},
    ]


if __name__ == '__main__':
    u3d = build(cube_groups())
    pdf = build_pdf(u3d, 'Test Cube (Export)', [[0, 0, 0], [1, 1, 1]])
    open('/tmp/test.u3d', 'wb').write(u3d)
    open('/tmp/test.pdf', 'wb').write(pdf)
    print('u3d bytes:', len(u3d), 'pdf bytes:', len(pdf))

require 'sketchup.rb'
require 'extensions.rb'
require 'zlib'

module Sketchup3dPdfExporter
  NODE_CHAIN_NAME = 'SketchupModel'.freeze
  RESOURCE_CHAIN_NAME = 'SketchupModelResource'.freeze
  MENU_LABEL = 'Export 3D PDF...'.freeze

  BLOCK_FILE_HEADER = 0x00443355
  BLOCK_MODIFIER_CHAIN = 0xFFFFFF14
  BLOCK_MODEL_NODE = 0xFFFFFF22
  BLOCK_CLOD_MESH_DECLARATION = 0xFFFFFF31
  BLOCK_CLOD_BASE_MESH_CONTINUATION = 0xFFFFFF3B
  BLOCK_SHADING_MODIFIER = 0xFFFFFF45
  BLOCK_LIT_TEXTURE_SHADER = 0xFFFFFF53
  BLOCK_MATERIAL_RESOURCE = 0xFFFFFF54

  MIB_UTF8 = 106
  PROFILE_NO_COMPRESSION = 0x00000004
  PROFILE_DEFINED_UNITS = 0x00000008
  INCHES_TO_METERS = 0.0254

  FILE_HEADER_BLOCK_SIZE = 44

  class ExportError < StandardError; end

  module Binary
    module_function

    def bin(s)
      if s.respond_to?(:force_encoding)
        s.dup.force_encoding(Encoding::BINARY)
      else
        s.dup
      end
    end

    def raw_length(s)
      s.respond_to?(:bytesize) ? s.bytesize : s.length
    end

    def u16(value)
      [value].pack('v')
    end

    def u32(value)
      [value].pack('V')
    end

    def f32(value)
      value = 0.0 if value.nil? || value.to_f.nan?
      [value].pack('e')
    rescue ArgumentError
      [value].pack('f')
    end

    def f64(value)
      value = 0.0 if value.nil? || value.to_f.nan?
      [value].pack('E')
    rescue ArgumentError
      [value].pack('d')
    end

    def f32x3(x, y, z)
      f32(x) << f32(y) << f32(z)
    end

    def string(text)
      bytes = bin(text.to_s)
      u16(raw_length(bytes)) << bytes
    end

    def block(block_type, data)
      body = u32(block_type) << u32(raw_length(data)) << u32(0) << data
      rem = raw_length(body) % 4
      body << ("\x00" * ((4 - rem) % 4)) unless rem.zero?
      body
    end

    def modifier_chain(name, chain_type, modifier_blocks)
      data = String.new
      data << string(name)
      data << u32(chain_type)
      data << u32(0)
      local = 2 + raw_length(bin(name.to_s)) + 8
      data << ("\x00" * ((4 - (local % 4)) % 4))
      data << u32(modifier_blocks.length)
      modifier_blocks.each { |m| data << m }
      block(BLOCK_MODIFIER_CHAIN, data)
    end
  end

  Group = Struct.new(:name, :diffuse, :opacity, :shading_id, :triangles)

  module U3dBuilder
    B = Sketchup3dPdfExporter::Binary
    NODE = Sketchup3dPdfExporter::NODE_CHAIN_NAME
    RESOURCE = Sketchup3dPdfExporter::RESOURCE_CHAIN_NAME

    module_function

    def build(groups)
      groups = groups.reject { |g| g.triangles.empty? }
      raise ExportError, 'No exportable faces were found in the model or selection.' if groups.empty?

      positions = []
      normals = []
      position_cache = {}
      normal_cache = {}
      faces = []

      groups.each do |group|
        group.triangles.each do |tri|
          corner_indices = tri[0, 3].map do |p|
            idx = position_cache[p]
            unless idx
              idx = positions.length
              position_cache[p] = idx
              positions << p
            end
            idx
          end
          nkey = tri[3]
          nidx = normal_cache[nkey]
          unless nidx
            nidx = normals.length
            normal_cache[nkey] = nidx
            normals << nkey
          end
          faces << [group.shading_id, corner_indices, nidx]
        end
      end

      raise ExportError, 'No triangle geometry to export.' if faces.empty?

      declaration = String.new
      declaration << write_node_modifier_chain(groups)
      declaration << write_resource_modifier_chain(faces.length, positions.length, normals.length, groups)
      groups.each { |g| declaration << write_lit_texture_shader(g) }
      groups.each { |g| declaration << write_material_resource(g) }
      continuation = write_base_mesh_continuation(positions, normals, faces)

      decl_size = Binary.raw_length(declaration)
      file_size = FILE_HEADER_BLOCK_SIZE + decl_size + Binary.raw_length(continuation)
      header = file_header_block(decl_size, file_size)
      header << declaration << continuation
    end

    def file_header_block(declaration_size, file_size)
      data = String.new
      data << B.u16(0) << B.u16(0)
      data << B.u32(PROFILE_NO_COMPRESSION | PROFILE_DEFINED_UNITS)
      data << B.u32(declaration_size)
      data << B.u32(file_size & 0xFFFFFFFF) << B.u32((file_size >> 32) & 0xFFFFFFFF)
      data << B.u32(MIB_UTF8)
      data << B.f64(INCHES_TO_METERS)
      B.block(BLOCK_FILE_HEADER, data)
    end

    def write_node_modifier_chain(groups)
      model_node = B.block(BLOCK_MODEL_NODE, model_node_data)
      shading_modifier = B.block(BLOCK_SHADING_MODIFIER, shading_modifier_data(groups))
      B.modifier_chain(NODE, 0, [model_node, shading_modifier])
    end

    def model_node_data
      data = String.new
      data << B.string(NODE)
      data << B.u32(0)
      data << B.string(RESOURCE)
      data << B.u32(3)
      data
    end

    def shading_modifier_data(groups)
      data = String.new
      data << B.string(NODE)
      data << B.u32(1)
      data << B.u32(1)
      data << B.u32(groups.length)
      groups.each { |g| data << B.u32(1) }
      groups.each { |g| data << B.string(shader_name(g.shading_id)) }
      data
    end

    def shader_name(index)
      format('Shader_%d', index)
    end

    def material_name(index)
      format('Material_%d', index)
    end

    def write_resource_modifier_chain(face_count, position_count, normal_count, groups)
      data = String.new
      data << B.string(RESOURCE)
      data << B.u32(0)
      data << B.u32(0) << B.u32(face_count) << B.u32(position_count) << B.u32(normal_count)
      data << B.u32(0) << B.u32(0) << B.u32(0)
      data << B.u32(groups.length)
      groups.each do |g|
        data << B.u32(0)
        data << B.u32(0)
        data << B.u32(g.shading_id)
      end
      data << B.u32(position_count)
      data << B.u32(position_count)
      data << B.u32(300) << B.u32(300) << B.u32(300)
      data << B.f32(1.0) << B.f32(1.0) << B.f32(1.0) << B.f32(1.0) << B.f32(1.0)
      data << B.f32(0.0) << B.f32(0.0) << B.f32(0.0)
      data << B.u32(0)
      clod_declaration = B.block(BLOCK_CLOD_MESH_DECLARATION, data)
      B.modifier_chain(RESOURCE, 1, [clod_declaration])
    end

    def write_lit_texture_shader(group)
      data = String.new
      data << B.string(shader_name(group.shading_id))
      data << B.u32(0x1)
      data << B.f32(0.0)
      data << B.u32(0x00000617)
      data << B.u32(0x00000606)
      data << B.u32(0x1)
      data << B.u32(0)
      data << B.u32(0)
      data << B.string(material_name(group.shading_id))
      B.block(BLOCK_LIT_TEXTURE_SHADER, data)
    end

    def write_material_resource(group)
      r, g, b = group.diffuse
      data = String.new
      data << B.string(material_name(group.shading_id))
      data << B.u32(0x37)
      data << B.f32x3(r * 0.5, g * 0.5, b * 0.5)
      data << B.f32x3(r, g, b)
      data << B.f32x3(0.1, 0.1, 0.1)
      data << B.f32x3(0.0, 0.0, 0.0)
      data << B.f32(0.1)
      data << B.f32(group.opacity)
      B.block(BLOCK_MATERIAL_RESOURCE, data)
    end

    def write_base_mesh_continuation(positions, normals, faces)
      data = String.new
      data << B.string(RESOURCE)
      data << B.u32(0)
      data << B.u32(faces.length)
      data << B.u32(positions.length)
      data << B.u32(normals.length)
      data << B.u32(0) << B.u32(0) << B.u32(0)
      positions.each { |p| data << B.f32x3(p[0], p[1], p[2]) }
      normals.each { |n| data << B.f32x3(n[0], n[1], n[2]) }
      faces.each do |shading_id, corners, nidx|
        data << B.u32(shading_id)
        3.times do |i|
          data << B.u32(corners[i]) << B.u32(nidx)
        end
      end
      B.block(BLOCK_CLOD_BASE_MESH_CONTINUATION, data)
    end
  end

  module Tessellator
    module_function

    def collect_triangles(entities, transformation)
      groups_by_material = {}
      each_visible_face(entities, transformation) do |face, t|
        next if face.deleted?

        mat = face.material || face.back_material
        key = mat.object_id
        group = groups_by_material[key]
        unless group
          group = Group.new(
            mat ? mat.name.to_s : 'Default',
            material_diffuse(mat),
            material_opacity(mat),
            groups_by_material.length,
            []
          )
          groups_by_material[key] = group
        end
        append_face(face, t, group)
      end
      groups_by_material.values
    end

    def material_diffuse(material)
      if material.is_a?(Sketchup::Material)
        c = material.color
        [c.red / 255.0, c.green / 255.0, c.blue / 255.0]
      else
        [0.90, 0.90, 0.90]
      end
    end

    def material_opacity(material)
      return 1.0 unless material.is_a?(Sketchup::Material)

      a = material.alpha.to_f
      a <= 0.0 ? 1.0 : a
    end

    def each_visible_face(entities, transformation = Geom::Transformation.new, &block)
      entities.each do |entity|
        case entity
        when Sketchup::Face
          block.call(entity, transformation) if entity_visible?(entity)
        when Sketchup::Group
          if entity_visible?(entity)
            each_visible_face(entity.definition.entities, transformation * entity.transformation, &block)
          end
        when Sketchup::ComponentInstance
          if entity_visible?(entity)
            each_visible_face(entity.definition.entities, transformation * entity.transformation, &block)
          end
        end
      end
    end

    def entity_visible?(entity)
      return false if entity.hidden? || entity.deleted?

      layer = entity.layer
      return false if layer && !layer.visible?

      true
    rescue StandardError
      true
    end

    def append_face(face, transformation, group)
      mesh = face.mesh
      points = mesh.points
      polygons = mesh.polygons
      return if points.empty? || polygons.empty?

      normal = face.normal.transform(transformation)
      normal.normalize
      nkey = [normal.x, normal.y, normal.z]
      polygons.each do |polygon|
        next if polygon.length < 3

        0.upto(polygon.length - 3) do |i|
          t_a = points[polygon[i].abs - 1].transform(transformation)
          t_b = points[polygon[i + 1].abs - 1].transform(transformation)
          t_c = points[polygon[i + 2].abs - 1].transform(transformation)
          tri = [
            [t_a.x, t_a.y, t_a.z],
            [t_b.x, t_b.y, t_b.z],
            [t_c.x, t_c.y, t_c.z],
            nkey
          ]
          group.triangles << tri unless degenerate?(tri)
        end
      end
    end

    def degenerate?(tri)
      ux = tri[1][0] - tri[0][0]
      uy = tri[1][1] - tri[0][1]
      uz = tri[1][2] - tri[0][2]
      vx = tri[2][0] - tri[0][0]
      vy = tri[2][1] - tri[0][1]
      vz = tri[2][2] - tri[0][2]
      nx = uy * vz - uz * vy
      ny = uz * vx - ux * vz
      nz = ux * vy - uy * vx
      (nx * nx + ny * ny + nz * nz) < 1.0e-20
    end
  end

  module PdfBuilder
    module_function

    def build(u3d_data, title, bbox)
      u3d_data = Binary.bin(u3d_data)
      camera = camera_view(bbox)
      title_text = pdf_string(title)

      content = String.new
      content << "q 1 1 1 rg 0 0 842 595 re f Q\n"
      content << "BT /F1 18 Tf 0.1 0.1 0.1 rg 40 566 Td (#{title_text}) Tj ET\n"
      content << "BT /F1 9 Tf 0.35 0.35 0.35 rg 40 550 Td (Interactive 3D content - open with Adobe Acrobat or Adobe Reader) Tj ET\n"
      content_stream = Zlib::Deflate.deflate(Binary.bin(content))
      content_len = Binary.raw_length(content_stream)
      u3d_len = Binary.raw_length(u3d_data)

      objects = []
      objects[1] = '<< /Type /Catalog /Pages 2 0 R /ViewerPreferences << /DisplayDocTitle true >> >>'
      objects[2] = '<< /Type /Pages /Count 1 /Kids [3 0 R] >>'
      objects[3] = '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 842 595] ' \
                   '/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R /Annots [6 0 R] >>'
      objects[4] = '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'
      objects[5] = "<< /Length #{content_len} /Filter /FlateDecode >>\nstream\n#{content_stream}\nendstream"

      annot = String.new
      annot << '<< /Type /Annot /Subtype /3D /F 4 '
      annot << '/Rect [36 36 806 544] '
      annot << '/3DA << /A /PO /DIS /I /TB true >> '
      annot << '/3DV << /C2W ['
      annot << camera[:c2w].map { |v| num(v) }.join(' ')
      annot << '] /CO ['
      annot << camera[:co].map { |v| num(v) }.join(' ')
      annot << '] /AAC 45 /MS /M '
      annot << '/LS << /Type /3DLightingScheme /Subtype /Headlamp >> '
      annot << '/BG << /Type /3DBG /C [1 1 1] >> >> '
      annot << '/3DD 7 0 R >>'
      objects[6] = annot

      objects[7] = "<< /Type /3D /Subtype /U3D /Length #{u3d_len} >>\nstream\n#{u3d_data}\nendstream"
      objects[8] = "<< /Title (#{title_text}) /Producer (SketchUp 3D PDF Exporter) >>"

      pdf = Binary.bin("%PDF-1.7\n%\xE2\xE3\xCF\xD3\n")
      offsets = {}
      objects.each_index do |i|
        next unless objects[i]

        offsets[i] = Binary.raw_length(pdf)
        pdf << "#{i} 0 obj\n#{objects[i]}\nendobj\n"
      end

      xref_offset = Binary.raw_length(pdf)
      count = objects.length
      pdf << "xref\n0 #{count}\n"
      pdf << "0000000000 65535 f \n"
      (1...count).each do |i|
        if offsets[i]
          pdf << format('%010d 00000 n ', offsets[i]) << "\n"
        else
          pdf << "0000000000 65535 f \n"
        end
      end
      pdf << "trailer\n<< /Size #{count} /Root 1 0 R /Info 8 0 R >>\n"
      pdf << "startxref\n#{xref_offset}\n%%EOF\n"
      pdf
    end

    def num(value)
      s = format('%.4f', value.to_f)
      s = s.sub(/(\.\d*?)0+\z/, '\1')
      s.chomp('.')
    end

    def pdf_string(text)
      if text.to_s.respond_to?(:encode)
        safe = text.to_s.encode('ASCII-8BIT', invalid: :replace, undef: :replace, replace: '?')
      else
        safe = text.to_s.gsub(/[^\x20-\x7e]/, '?')
      end
      safe.gsub(/[\\()]/) { |c| '\\' + c }
    end

    def camera_view(bbox)
      center = [
        (bbox[0][0] + bbox[1][0]) * 0.5,
        (bbox[0][1] + bbox[1][1]) * 0.5,
        (bbox[0][2] + bbox[1][2]) * 0.5
      ]
      extent = [
        (bbox[1][0] - bbox[0][0]).abs,
        (bbox[1][1] - bbox[0][1]).abs,
        (bbox[1][2] - bbox[0][2]).abs
      ]
      radius = extent.max * 0.5
      radius = 1.0 if radius <= 0.0

      dir = normalize([1.0, -1.2, 0.9])
      eye = [
        center[0] + dir[0] * radius * 3.0,
        center[1] + dir[1] * radius * 3.0,
        center[2] + dir[2] * radius * 3.0
      ]

      z_axis = dir
      y_axis = normalize(reject_axis([0.0, 0.0, 1.0], z_axis))
      x_axis = cross(y_axis, z_axis)

      c2w = [
        x_axis[0], y_axis[0], z_axis[0], eye[0],
        x_axis[1], y_axis[1], z_axis[1], eye[1],
        x_axis[2], y_axis[2], z_axis[2], eye[2]
      ]
      { c2w: c2w, co: center }
    end

    def normalize(v)
      len = Math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
      len = 1.0 if len < 1.0e-12
      [v[0] / len, v[1] / len, v[2] / len]
    end

    def reject_axis(v, axis)
      d = v[0] * axis[0] + v[1] * axis[1] + v[2] * axis[2]
      r = [v[0] - d * axis[0], v[1] - d * axis[1], v[2] - d * axis[2]]
      return r if (r[0].abs + r[1].abs + r[2].abs) > 1.0e-9

      fallback = axis[2].abs < 0.9 ? [0.0, 0.0, 1.0] : [1.0, 0.0, 0.0]
      [fallback[0], fallback[1], fallback[2]]
    end

    def cross(a, b)
      [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0]
      ]
    end
  end

  module_function

  def export_from_ui
    model = Sketchup.active_model
    title = model_title(model)
    default_name = title.gsub(/[^\w\-]/, '_') + '.pdf'
    path = UI.savepanel('Export 3D PDF', last_dir(model), default_name)
    return if path.nil? || path.empty?

    path += '.pdf' unless path.downcase.end_with?('.pdf')
    Sketchup.status_text = 'Exporting 3D PDF...'
    begin
      export(model, path, title)
      UI.messagebox("3D PDF exported to:\n#{path}", MB_OK)
    rescue ExportError => e
      UI.messagebox("3D PDF export failed: #{e.message}", MB_ICONWARNING)
    rescue StandardError => e
      UI.messagebox("3D PDF export failed unexpectedly: #{e.class} - #{e.message}", MB_ICONWARNING)
    ensure
      Sketchup.status_text = ''
    end
  end

  def export(model, path, title)
    Sketchup.status_text = 'Collecting geometry...'
    source = model.selection.empty? ? model.entities : model.selection
    groups = Tessellator.collect_triangles(source, Geom::Transformation.new)

    Sketchup.status_text = 'Writing U3D mesh data...'
    u3d = U3dBuilder.build(groups)

    Sketchup.status_text = 'Writing PDF...'
    pdf = PdfBuilder.build(u3d, title, model_bbox(groups))

    File.open(path, 'wb') { |f| f.write(pdf) }
    path
  end

  def model_title(model)
    t = model.title
    return 'SketchUp Model' if t.nil? || t.empty?

    t
  end

  def last_dir(model)
    p = model.path
    return Sketchup.temp_dir if p.nil? || p.empty?

    File.dirname(p)
  end

  def model_bbox(groups)
    min = [Float::MAX, Float::MAX, Float::MAX]
    max = [-Float::MAX, -Float::MAX, -Float::MAX]
    groups.each do |g|
      g.triangles.each do |tri|
        tri[0, 3].each do |p|
          3.times do |i|
            min[i] = p[i] if p[i] < min[i]
            max[i] = p[i] if p[i] > max[i]
          end
        end
      end
    end
    [min, max]
  end
end

unless defined?(Sketchup3dPdfExporter::MENU_REGISTERED)
  cmd = UI::Command.new('Export 3D PDF') { Sketchup3dPdfExporter.export_from_ui }
  cmd.tooltip = 'Export the current model as an interactive 3D PDF'
  cmd.menu_text = Sketchup3dPdfExporter::MENU_LABEL
  UI.menu('Extensions').add_item(cmd)
  Sketchup3dPdfExporter::MENU_REGISTERED = true
end

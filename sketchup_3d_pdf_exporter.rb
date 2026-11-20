require 'sketchup.rb'
require 'extensions.rb'

module Sketchup3dPdfExporter
  PLUGIN_ROOT = File.dirname(__FILE__)
  PLUGIN_VERSION = '1.0.0'.freeze

  unless file_loaded?(__FILE__)
    extension = SketchupExtension.new('3D PDF Exporter', File.join(PLUGIN_ROOT, 'sketchup_3d_pdf_exporter', 'exporter'))
    extension.description = 'Export SketchUp models as interactive 3D PDF files (U3D).'
    extension.version = PLUGIN_VERSION
    extension.creator = 'Sketchup3dPdfExporter contributors'
    extension.copyright = "Copyright 2024, MIT License (see LICENSE)"
    Sketchup.register_extension(extension, true)
    file_loaded(__FILE__)
  end
end

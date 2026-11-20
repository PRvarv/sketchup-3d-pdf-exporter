# SketchUp 3D PDF Exporter

A SketchUp Ruby plugin that exports models to interactive **3D PDF** files, with no
external dependencies and no SketchUp Pro license beyond what SketchUp already ships.

The plugin tessellates the current model (or the active selection), converts SketchUp
face materials into U3D material resources, and generates a standards-compliant
`PDF 1.7` document with an embedded `U3D` (ECMA-363, Universal 3D) 3D data stream,
a camera view that frames the model, and an annotation that plays automatically when
the page opens.

Open the result in **Adobe Acrobat / Adobe Reader** to rotate, zoom and pan the model.

## Features

- Menu item under **Extensions → Export 3D PDF...**
- Exports the whole model, or just the current selection if one is active
- Recurses into groups and component instances (visibility respected)
- One U3D shader/material pair per SketchUp material, including per-material colors
- Material transparency is carried over as U3D opacity
- Vertex positions are exported in inches with the U3D "defined units" profile set to
  the exact inch → meter factor (0.0254)
- Hand-built PDF: catalog, page, title text, 3D annotation with auto-activation
  (`/A /PO`), default camera view (`/3DV` with framing `C2W`), compressed page
  content, valid xref table
- Pure Ruby + SketchUp API only; `zlib` (bundled with any Ruby) for stream compression

## Installation

1. Copy these two items into your SketchUp **Plugins** directory
   (Extensions → Preferences — you can find the path via
   `Sketchup.find_support_file('Plugins')` in the Ruby Console):
   - `sketchup_3d_pdf_exporter.rb`
   - `sketchup_3d_pdf_exporter/` (folder)
2. Restart SketchUp (or run `load 'sketchup_3d_pdf_exporter.rb'` in the Ruby Console).
3. Use **Extensions → Export 3D PDF...**.

Works with SketchUp 2014 and later (Ruby 2.0+). Falls back gracefully on very old
Ruby versions for float packing.

## Usage

1. Open a model. Optionally select geometry to export only that part.
2. **Extensions → Export 3D PDF...**
3. Choose a destination `.pdf` file.
4. Open the file in Adobe Acrobat/Reader and click the 3D content.

## Notes and limitations

- Viewing interactive 3D content requires Adobe Acrobat or Adobe Reader; Chrome,
  macOS Preview and most non-Adobe PDF viewers show only the static page text.
- Curved SketchUp surfaces are exported with flat (per-face) normals, so smooth
  curved surfaces may look faceted.
- Textured materials are exported as their plain material color (texture mappings
  are not embedded); likewise SketchUp per-vertex paint colors are not exported.
- Only surface geometry (faces) is exported; edges, guides, dimensions and
  section planes are skipped.
- The 3D data uses the U3D format (legacy `/Subtype /3D` annotation, `Subtype /U3D`
  stream), which is what the PDF spec and Adobe provide; PRC is not implemented.

## Repository layout

- `sketchup_3d_pdf_exporter.rb` — plugin loader / extension registration
- `sketchup_3d_pdf_exporter/exporter.rb` — implementation:
  `Binary` (U3D byte packing), `U3dBuilder` (U3D CLOD mesh serialization),
  `Tessellator` (SketchUp geometry collection), `PdfBuilder` (PDF 1.7 writer),
  and the menu/UI glue
- `dev/reference_mirror.py` — a Python transliteration of the Ruby binary writers,
  used to validate the byte-level output
- `dev/validate.py` — strict structural validator: parses every U3D block
  (alignment, contained block sizes, counts vs. payload, palette cross-references),
  checks the PDF xref table, inflates both streams, and re-parses the embedded U3D

## Validation

Run the dev checks (no Ruby needed):

```sh
cd dev && python3 validate.py
```

The validator checks, among ~600 assertions: block 4-byte alignment, `DataSize`
vs. parsed field consumption, modifier-chain nesting, declaration/file sizes in the
U3D header, vertex dedupe, face/position/normal count consistency across the
declaration and continuation blocks, shader/material palette references, PDF xref
offsets, and text-stream integrity.

## License

MIT — see `LICENSE`.

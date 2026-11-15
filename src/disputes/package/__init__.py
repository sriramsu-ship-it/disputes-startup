"""Response package (R-20) and audit export documents (R-22). OWNER: package agent.

- `build`   : the immutable, versioned response-package dict written on final approval.
- `model`   : read-side view models (package document, export summary, integrity checks).
- `render`  : standalone HTML rendering (inline CSS) used for PDF and the zip bundle.
- `pdf`     : HTML -> PDF with a headless Chromium binary (no network, scripts disabled).
- `bundle`  : the R-22 attachments zip (export JSON/HTML/PDF, packages, extracted attachment text).

Everything here is SYNTHETIC-demo grade: the package schema is a placeholder that has NOT been
validated against the e-OSCAR ACDV response format or the Metro 2 format (U6).
"""

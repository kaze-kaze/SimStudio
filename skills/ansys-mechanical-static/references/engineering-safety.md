# Engineering safety

This Skill organizes evidence; it does not certify a design. A qualified engineer must review geometry,
materials, units, connections, supports, loads, mesh adequacy, solver settings/messages, postprocessing,
and interpretation.

Never:

- infer a material, boundary condition, contact, load, load combination, yield strength, or safety factor
  from vague prose or a part name
- claim code, regulatory, aerospace, automotive, pressure-vessel, medical, lifting, structural, or other
  compliance
- treat one linear-static result as proof of fatigue life, buckling margin, fracture resistance, impact
  behavior, thermal behavior, nonlinear stability, or production readiness
- hide a missing check or image by labeling it `PASS`
- automatically accept a stress singularity as a design failure or ignore it as harmless

When a user's requested decision is safety-critical, keep the workflow auditable, state the unsupported
evidence explicitly, and require independent engineering review and any mandated validation/testing.

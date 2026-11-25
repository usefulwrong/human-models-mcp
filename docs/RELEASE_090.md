# Human Models MCP v0.9.0 Research Preview candidate

Package and CLI version `0.9.0rc1`. Target platform Linux x86-64, Docker and
Python 3.12. Use the full public source archive for Compose, model provisioning,
scenarios, Anatomy Lab and historical demos. The wheel contains the core
Python package. The sdist contains Python build inputs and source examples.
Use `human-models-mcp --version` to identify the installed core.
This candidate is prepared for operator review.

[Watch the whole-body run and inspect the bilateral muscle plots](demo/v09/README.md).

| Capability | Status | Evidence and interpretation |
| --- | --- | --- |
| MS-Human-700 native signals and state clock | SUPPORTED | 700 actuators in the pinned model. The assisted showcase has 111 saved states and eight selectable fields. Excitation, activation, signed force, path length, velocity and power are model outputs. Force magnitude and saved-sample work are derived. [Scientific scope](SCIENTIFIC_SCOPE.md) |
| BodyParts3D 4.3 geometry, composites and FMA Registry | SUPPORTED | Optional pinned local sources. The Registry preserves source disagreements and exposes mesh and concept identities. [Installation](V09_ANATOMY_LAB.md) |
| Native-to-anatomy crosswalk | CANDIDATE | The reviewed crosswalk contains 76 accepted rows (74 exact FMA), 378 candidates and 246 unassigned. Unassigned actuators retain model signals. Geometry-only display nodes carry no actuator signal. |
| Moving surfaces, atlas registration and Blender view | ILLUSTRATIVE | Shared saved states drive the two views. Linear blend skinning and coordinate parity establish geometric transfer. |
| Operator landmark inspection | SUPPORTED | Operator evidence can be recorded locally with source and target pins, coordinate frames and review history. |
| Anatomically validated registration and measured attachment footprints | NOT_VERIFIED | Zero independently reviewed source/target landmark pairs and zero measured footprints. |
| Complete authored 4.3i inferred graph | NOT_VERIFIED | Available membership data and direct source relationships retain separate provenance. |
| Muscle-only assisted-palm showcase | NOT_SUPPORTED | `muscle_driven=NOT_ACHIEVED`, `external_control=USED`. |
| Human experimental validation and physiological tissue deformation | NOT_SUPPORTED | `human_experimental_validation=NOT_VALIDATED`. Activation is a model signal. Clinical diagnosis, medical advice, patient-specific anatomy and validated tissue stress/strain are outside this release's scope. |
| Volumetric FEM validation | NOT_RUN | The moving viewer uses illustrative surface transforms and skinning. |

For a reproducible historical calculation and the original render passports,
see the [v0.8 workflow](V08_WORKFLOW.md). The Anatomy Lab runs on loopback by
default. Keep optional source caches and generated local scenes under operator
control. Their terms are itemized in [third-party notices](../notices/THIRD_PARTY.md)
and the [atlas setup](V09_ANATOMY_LAB.md).

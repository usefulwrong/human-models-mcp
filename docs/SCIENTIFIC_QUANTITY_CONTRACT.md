# Scientific quantity receipts

The existing `muscle.timeseries`, `muscle.select`, `muscle.selection`, `get_result` and experimental `get_contact` reads return an additive `scientific_quantity` object. The schema identifier is `hmm.scientific_quantity/1`. Existing value fields, units, identifiers, aggregation and selection mechanisms are retained. Blender stores selection and contact receipts alongside the replay.

| Field | Interpretation |
| --- | --- |
| `run_id`, `scenario`, `model` | Run UUID, scenario ID/version/hash, model source revision and asset-tree hash. The derived MJCF hash is included when recorded. |
| `controls`, `acceptance` | Resolved parameters, controller mode, recorded joint assistance and external-control flags, fixed support equalities, and original gates. New runs record explicit overrides and scenario/schema defaults. Historical runs report `NOT_AVAILABLE` for default provenance. |
| `window` | Exact selected state/time/hash, requested series time window and paging, or whole-run scope. Series responses pair each value with `state_indices`, `time_s` and `state_sha256`. The interpolated render pose can display the last saved signal during playback. |
| `sources_sha256` | Manifest-listed source artifacts. Metric-specific inputs and model binding can be audited against the source manifest and motion/trajectory digests. Contact responses also identify the selected proxy part and coordinate frame. |
| `quantities` | Units, definition, availability, numerical origin, native engine identifier where applicable, and `improve_estimate` for that observable. Unavailable quantities can have a known unit, such as Pa for skin pressure. |
| `reference_comparison`, `human_validation`, `uncertainty_sources` | Independent comparison status, scenario validation status and named limitations. A comparison belongs only to its stated observable and protocol. |
| `uncertainty_interval`, `physiological_scaling` | Explicit `NOT_AVAILABLE` and `NOT_RUN` with the data and method needed. |

A raw muscle series keeps the native actuator ID and exact name. Its `identity` carries side, actuator-to-group status, individual FMA claims and display references. The receipt carries the pinned crosswalk and catalog, group-to-FMA status when a group is selected, and source membership and registration for selected geometry. An accepted sided group can still have a candidate part association. A geometry-only selection retains its display identity and returns `NO_DATA` with no signal or overlay.

Use `get_result(run_id, claim_id="quantity:force_N")` for the definition on a run with recorded muscle chunks. Use the exact `muscle.timeseries` or `muscle.select` request for values. For the experimental contact run, `quantity:normal_force_N` describes per-event normal force, and `quantity:skin_contact_pressure` describes the missing quantity. `get_result` still accepts metric, artifact and gate claims. Run-level summary figures in a contact receipt have their own scope and verified source. Displayed forces describe collision proxy events and carry no safety classification.

## Transports

- The staged Anatomy Lab accepts typed requests over `POST /api/query` and `anatomy_lab` on official MCP stdio. Use `whole.open` to obtain the installed run and motion digest. `whole.contact` checks the selected saved state against the same Python reader as the MCP `get_contact` tool. Point `HUMAN_MODELS_HOME/results` and the installed MotionScene at the same read-only run store.
- `muscle.timeseries` accepts an optional unit assertion. For example, `metric="force_N", unit="N", actuator_ids=[122]` requests a bounded native series. An incompatible assertion returns structured `invalid_input`. Search misses and an empty in-range window return `NO_DATA`. Existing integrity errors cover corrupted or absent pinned bytes and out-of-range saved windows. An out-of-range contact state returns `invalid_input`.
- Publish a shared exact selection with `muscle.select`, then use `python scripts/muscle_intelligence/export_selection.py RUN_ID OUTPUT.json` in the staged environment. The exporter uses official stdio, preserves units and numerical values, and provides the envelope for Blender `blender_muscles.py -- build`. Reopen the scene with `-- reopen` to verify its saved state, values, pose and palette. The editability of the resulting Blender file permits later edits, so export hashes apply to the audited file.
- In Python, `human_models_mcp.contact_results.get_contact(run_id, "hand_r", sample=55)` returns the contact JSON used by MCP. Write that receipt to a JSON file and pass it as the optional third argument to `blender.py -- CLIP_DIR build CONTACT.json` in a writable copy of the derived clip. The scene stores the exact receipt in **Saved contact scientific quantities** and opens at the receipt's saved index.

The installed muscle crosswalk is pinned to its originating trajectory and clip. Pose interpolation in the reference replay uses display transforms. The chart and overlay hold the most recent saved sample between poses. Seeking snaps both to the selected state. Experimental contact playback renders discrete saved states. The contact reader checks the selected state hash and time against trajectory bytes. A run-specific anatomical crosswalk for that profile has not been reviewed.

## Interpretation of recorded values

| Quantity | Unit | Definition |
| --- | --- | --- |
| Excitation / activation | 1 | Recorded input and modeled activation state, respectively. |
| Signed force / magnitude | N | Scalar transmission force and its absolute value. Tension generally carries negative sign. |
| Length / velocity | m / m/s | Transmission path length and signed rate of change. Separate fiber and tendon lengths are unavailable. |
| Signed power / sampled work | W / J | Force times path velocity and its cumulative trapezoid on exact saved samples from the first state. The solver-step work is separately identified. |
| Group reductions | Same as input | Arithmetic mean of path activation/excitation. Signed force, magnitude, power and work are summed according to the selected metric. A summed magnitude is a scalar path statistic. Length and velocity are kept per path. |
| Surface color | 1 | Uniform linked-mesh color from group activation. Anatomical attachment, tissue stress and volume deformation remain unverified. |
| Normal force / gap | N / m | Native normal-force component and collision gap per event. The hand total sums each selected event once. Display vertex distance is separately derived from the mapped geometry and floor plane. |

Engine verification, calibration, independent experimental validation and engineering sensitivity are distinct. A positive numerical gate records the tested model and controls. Activation timing can be compared under a matched EMG protocol. Contact normal forces can be checked with matched force plates. Pressure needs its own spatially resolved independent measurement. Model outputs alone provide no individual injury classification.

[MuJoCo muscle model](https://mujoco.readthedocs.io/en/stable/modeling.html#muscles) · [Hicks et al., 2015](https://pmc.ncbi.nlm.nih.gov/articles/PMC4321112/) · [Contact model and limitations](CONTACT_MODEL_AND_LIMITATIONS.md)

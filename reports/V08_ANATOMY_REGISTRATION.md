# v0.8 registration of right clavicular pectoralis major

**Result: ILLUSTRATIVE.** The source is BodyParts3D 4.3 FJ1447/BP23304/FMA34690.
The companion bones are FJ3362/FMA13322 and FJ3368/FMA23130. The three
pinned OBJ files are verified with the sizes and SHA-256 in the asset lock.
The source index cross-checks the FJ/FMA relationships. The provenance file
records DBCLS attribution, the mirror copy terms and the current archive terms.
No source OBJ is included in the project or its build products.
[Asset lock](../src/human_models_mcp/atlas_pectoralis.json) ·
[Asset license and attribution](../notices/BODYPARTS3D.md) ·
[DBCLS source index](https://dbarchive.biosciencedbc.jp/en/bodyparts3d/download.html)

The inferred atlas world basis uses X left, Y posterior and Z superior. Its
proper signed permutation converts to model X anterior, Y left, Z up.
Millimetres are scaled by 0.001. Each atlas bone is fitted to the corresponding
native mesh in the compiled model's reference pose with a proper rigid
transform. Rest-shape local coordinates then follow `clavicle_r` and
`humerus_r`, with weights derived from nearest atlas-bone vertices. Fit
diagnostics include extrema and closest native attachment vertex, bidirectional
nearest-vertex RMSE, distance to sites `PECM1_r-P4` and `PECM1_r-P1`,
mesh topology, adjacent-frame displacement and bone triangle crossings.
The limits of 18 mm nearest-vertex RMSE and 35 mm for landmark proxies are
engineering rejection guards.

The 1,492-vertex, 1,846-triangle surface moves during seven saved
`pushup_palms` states, including source indices 0, 55 and 110. In the palms
derivative the nearest-vertex RMSEs are 2.89 mm (clavicle) and 7.39 mm (humerus).
The rest attachment gap is about 1.75 mm near the clavicle and 20.17 mm near the
humerus. The near-rigid insert remains approximately 20.17 mm from the model
site across the replay. Blender finds 152 surface-triangle crossings with the
clavicle at each of the seven samples and none with the humerus or scapula.
These include a source attachment region and require anatomical review to
interpret. Blender matches the exported skinned surface within 0.067 µm against
a 3 µm transfer tolerance. This residual verifies transfer of the visual rig.

The contact sheet shows a clearly moving surface on the anterior right
shoulder and visible shape change at the bottom. Atlas donor proportions,
geometric vertex proxies and the humeral residual prevent verified
registration. Use the neutral violet material. The product reports no
activation map, fibers, tissue strain, stress or material response. Further
work requires reviewed homologous landmarks and insertion footprints, and
independent evaluation of intersection and placement through motion.

After exact-coordinate diagnostic welding, FJ1447 has zero open and zero
nonmanifold edges. The render retains the original vertex and face indexing.
The largest observed vertex displacement into the bottom sample is 0.150 m
between sampled states. That includes rigid body motion and illustrates why
vertex displacement cannot be interpreted as muscle fiber strain.

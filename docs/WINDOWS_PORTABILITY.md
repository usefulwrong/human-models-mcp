# Windows portability engineering notes

The public tree was inventoried from the 0.9.0rc2 checkout. Docker isolation,
the model inventory, scenario contracts, numerical bounds, saved-state and
artifact schemas, and anatomy source restrictions are independent of the
installer and operating-system integrations.

| Area | rc2 dependency | Portability decision |
| --- | --- | --- |
| Execution and queue | flock, Linux rlimits and parent-death signaling, Blender process groups | Centralize locks and process containment. Keep Linux limits. Windows uses Job Objects and fails closed when assignment fails. |
| Data and evidence | Host-native relative path spelling, locale encoding, newline translation, symlinks | Use portable manifest IDs, UTF-8, explicit newlines and validation of Windows names and reparse points. Stage ordinary copies. |
| Graphics | OSMesa is the Linux default; several scenarios request images by default | Use GLFW on Windows. Provide an explicit physics-only path. Preserve the failed-render contract. |
| Release and developer tools | Compose, Make, UID/GID, /app, /proc, /opt/blender, /tmp, .client-venv/bin | Keep container operations in the Linux workflow. Route standalone launch, provisioning and diagnostics through the native entry point. Linux-specific tests remain in scope on Linux. |
| Dependencies | Linux-first Python and renderer locks; system FFmpeg and Blender | Verify Windows wheels separately and pin native vendor archives. Keep test dependencies optional for Windows users. |
| Anatomy Lab | Node packer, original asset symlink, Bash and patch for operator staging | Use local provisioning and the existing viewer and MCP tools. Keep redistribution restrictions on the catalog, crosswalk and models. |
| Security | Non-root offline Docker container with bounded mounts | Native is an owner-local runtime with resource and path controls. It inherits the user's filesystem and network access. |

## Decisions verified during implementation

The pinned MuJoCo 3.17.0 file provider uses a narrow native file call. The
Windows adapter puts the original locked bytes into MuJoCo's VFS. The
inventory excludes other model variants' body files because the VFS uses
a basename fallback for nested includes. Linux keeps the existing file
provider. Direct and VFS compilations are compared with exact geometry,
initial coordinates and actuator lengths.

MuJoCo 3.17.0 maps its Windows `wgl` and `glfw` selectors to GLFW. The
diagnostic probes the native backend in a bounded process and reports
the OpenGL renderer only after producing an image. CPU physics uses
the disabled-graphics setting when render is false. The renderer worker
reconstructs loaded-elbow XML with the original recipe. A moved rc2
run supplies its verified original diagnostic XML, since the old hash
includes absolute asset paths.

Windows uses the locked truststore package for HTTPS provisioning.
An ordinary CPython TLS context failed to build the GitHub chain on the
clean Evaluation guest, while the Windows chain engine verified it.
Only the provisioning process changes its TLS context.

The Windows worker waits on an inherited startup pipe until it is assigned
to a Job Object. Closing the write end without a start token aborts the
gate. The job uses kill-on-close and aggregate memory and process-count
limits. Scientific jobs also have aggregate user-mode CPU limits.
Nested assignment must succeed before the worker starts. Linux keeps
rlimits, a deadline and parent-death signaling.
[Windows Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)

The compact embeddable CPython 3.12.10 is the official Windows binary for
this candidate. Later Python 3.12 security releases ship as source-only.
A Windows artifact with a newer maintained interpreter needs its own
review, pinned build evidence and compatibility run.

The MuJoCo Windows wheel imports `MSVCP140.dll` and
`MSVCP140_ATOMIC_WAIT.dll`. The official CPython ZIP includes the C runtime
but omits those C++ libraries. Core downloads the pinned Microsoft x64
framework package and installs only the hashed C++ runtime DLLs beside
`python.exe`. The framework and DLLs stay out of the public ZIP.
[Microsoft C++ deployment methods](https://learn.microsoft.com/en-us/cpp/windows/choosing-a-deployment-method)

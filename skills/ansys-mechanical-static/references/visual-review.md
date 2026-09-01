# Visual review

After a real solve, attempt to export at least:

- total deformation
- equivalent von Mises stress
- a mesh image when the installed Mechanical graphics API and headless mode permit it

The generated script activates requested result objects and calls the official Mechanical graphics
export API. Each image receives its own `PASS` or `NOT_RUN` state and reason in
`mechanical-artifacts.json`. Headless graphics, product edition, renderer, or version differences can
make export unavailable. Do not turn that condition into a solver failure unless the user's acceptance
criteria require images.

Review:

- expected fixed and loaded faces
- gross deformation direction and relative shape
- mesh continuity and obvious coarse regions
- stress concentration location
- unexpected disconnected, unconstrained, duplicate, or tiny geometry

Images complement numerical verification. They neither replace DPF checks nor prove result validity. If
no image can be exported, preserve the numerical evidence and report visual review as `NOT_RUN`.

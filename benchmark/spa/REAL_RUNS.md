# Real development SPA verification (candidate truth, 2026-11-08 UTC)

These checks use the two pinned **development** apps from `benchmark/apps.json` with repository baseline patches applied. No holdout data, real login submission, invitation, or external service operation was used. HTTP traffic to non-loopback hosts was blocked. Candidate expectations were written from application source, rendered DOM and screenshot inspection, not generated from collector output. No human has approved these labels.

## Material Kit React

Revision `69e780a40c455d664b2e13c525faf1d492a072a7`, `material-kit-react.candidate.json`, 1280×800.

- Three sign-in states: initial password concealed, revealed, concealed again.
- 36 expected raw candidates over three states, no omissions/extras, no name/role mismatch; 6/6 numbered handle clicks matched. Native placeholders without href remain raw anchor candidates, with no implicit link role/name.
- Median extraction 8.60 ms, p95 8.80 ms (three samples only; no performance gate).
- Separate Products functional stress: three filter-open / Women-checkbox toggle / Escape / sort-Newest cycles; User route and browser Back; fixed header y=0 before/after scroll600. Eighteen steps, thirteen numeric clicks. No exhaustive Products precision/recall claim.
- Found actual styled-input omission: checkbox input opacity=0 overlays a visible SVG inside its label; original collector excluded all filter checkbox targets. After narrow collector correction, all three Women checkbox numeric clicks succeeded. Before/after traces and DOM evidence preserved separately.

## shadcn-admin

Revision `e16c87f213a5ba5e45964e9b67c792105ec74d26`, production build, `shadcn-admin.candidate.json`, 1280×800.

- Three sign-in states, 30 expected candidates total, no omissions/extras, 6/6 numbered clicks matched after source-based label correction.
- Initial candidate expected button names GitHub/Facebook only. Source `src/assets/brand-icons/icon-{github,facebook}.tsx` gives nested role=img SVG titles as well as visible button text, so accessible-name content recursion yields GitHub GitHub / Facebook Facebook. Original mismatch evidence retained; corrected manifest has zero name/role mismatch.
- Original fallback-font run remained **failed/partial** because Google Fonts requests were blocked; preserved in `/workspace/shared/stepmeter-real-shadcn-fallback`. Then official CSS and 25 referenced fonts.gstatic.com font assets were provisioned into the ignored test checkout only, with original URLs and SHA256 hashes in `/workspace/shared/stepmeter-font-evidence/manifest.json`. Runtime external blocking remained unchanged. Rebuilt rerun has no blocked hosts, no name/role mismatches and `review_pending`, never human-approved. Extraction median 8.52 ms / p95 10.02 ms (3 samples).
- Separate Tasks functional stress: three Status popover open/Escape cycles and row-menu/Edit-dialog/Escape cycles, Users route and browser Back. Seventeen steps, ten numeric clicks. No exhaustive Tasks precision/recall claim.

## Evidence and remaining acceptance

Execution evidence held outside tracked source:
- `/workspace/shared/stepmeter-real-material`: report, screenshots, transitions-before-fix.json, transitions-after-fix.json, checkbox-diagnostic.json, source-independent transition script.
- `/workspace/shared/stepmeter-real-shadcn`: report, initial-label-mismatch.json, screenshots, transitions.json and transition script.

The candidate manifests are executable with `python -m benchmark.spa_eval`. Follow `selection.md` to checkout/install/start the pinned apps. Preserve original third-party license files. `ground_truth_review.status` stays pending until a person reviews exhaustive labels.

Still incomplete: exhaustive reviewed labels for the complex Tasks/Products states, teammate SPA repository/revision/task, and combined coverage across three real apps. Cookie-modal/virtual-scroll/Shadow DOM/iframe coverage remains synthetic-only; do not attribute those features to either real app. The Material fixed header and both apps' repeated UI/route transitions were actually exercised. Do not call 3.1 accepted from these two partial runs.

## Reproduce the local-only font profile and transitions

The source-local change is reproducible using accompanying evidence `stepmeter-font-evidence/localize.py`, `google-fonts.css`, `manifest.json`, and `local-font-index.patch`. It downloads only the exact official font URLs and writes `public/stepmeter-fonts/` plus an index.html link change in the ignored shadcn app checkout, then rebuild with `npm --prefix benchmark/apps/shadcn-admin run build`. Verify recorded hashes before reusing saved bytes. No StepMeter production font config was edited.

Run each app using the `selection.md` command, then:

```sh
python -m benchmark.spa_eval --manifest benchmark/spa/material-kit-react.candidate.json --base-url http://127.0.0.1:8767 --output benchmark/evidence/spa/material
python -m benchmark.spa_eval --manifest benchmark/spa/shadcn-admin.candidate.json --base-url http://127.0.0.1:8772 --output benchmark/evidence/spa/shadcn
# The evidence package includes each app's transitions.py. Run with repository root on PYTHONPATH.
```

Candidate runs intentionally exit 2 because human review remains pending. Source checkout and builds succeeded; screenshots were inspected. All test servers started for these runs were stopped; no server/scheduler or remote state was installed.

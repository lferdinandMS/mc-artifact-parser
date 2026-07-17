# Walkthrough Runbook (User Acceptance)

## Purpose
This runbook is for the primary user to validate the end-to-end image workflow, assess output quality, and decide whether results are usable for real artifacts.

## Pre-checks
1. Open PowerShell in the repository root.
2. Confirm Python environment is active if you use a virtual environment.
3. Ensure Tesseract is available in PATH for this terminal session.

Run these commands:

    cd "c:\Users\lferdinand\microsoft_source\mc-artifact-parser"
    $env:Path = "C:\Users\lferdinand\AppData\Local\Programs\Tesseract-OCR;" + $env:Path
    tesseract --version

Expected result:
- Tesseract version prints successfully.

## Walkthrough Test (Single Image)
Use this first when validating a new image type.

    python -m mc_artifact_parser --sources "C:\path\to\your-image.png" --output-root .\walkthrough-single

Inspect these files:
- walkthrough-single/session/source-review.md
- walkthrough-single/final/data-dictionary.md
- walkthrough-single/final/erd.mmd

Pass criteria:
1. source-review.md exists.
2. Entity Count is greater than or equal to 1.
3. data-dictionary.md contains at least one entity table.

## Walkthrough Test (Batch Images)
Use this for real workload testing with many files.

    $images = Get-ChildItem "C:\Users\lferdinand\Pictures\Screenshots" -File |
      Where-Object { $_.Extension -match '^(\.png|\.jpg|\.jpeg|\.bmp|\.gif|\.tif|\.tiff|\.webp)$' } |
      Select-Object -ExpandProperty FullName
    python -m mc_artifact_parser --sources $images --output-root .\walkthrough-batch

Inspect these files:
- walkthrough-batch/session/source-review.md
- walkthrough-batch/session/session_mapping.md
- walkthrough-batch/drafts/data-dictionary.md
- walkthrough-batch/final/data-dictionary.md
- walkthrough-batch/final/erd.mmd

Pass criteria:
1. Pipeline prints all stages: review-sources, propose-mapping, approve-mapping, draft-outputs, finalize.
2. source-review.md exists and has Entity Count greater than or equal to 1.
3. final outputs exist in final folder.

## Greenfield Walkthrough (From Clean Slate)
Use this when starting a brand new artifact set and you want to run the staged slash-command flow.

1. Start from a clean output root.

    ```powershell
    python -m mc_artifact_parser /clean --output-root .\greenfield-run
    ```

2. Run mapping stage with your new inputs.

    ```powershell
    python -m mc_artifact_parser /mapping --sources "C:\path\to\new-image-1.png" "C:\path\to\new-image-2.png" --output-root .\greenfield-run
    ```

3. Review and refine mapping files before extraction.

Review these files:
- greenfield-run/session/source-review.md
- greenfield-run/session/session_mapping.md
- greenfield-run/mappings/*.md

4. Finalize extraction using approved mapping outputs.

    ```powershell
    python -m mc_artifact_parser /extraction --output-root .\greenfield-run
    ```

5. Validate final artifacts.

Inspect these files:
- greenfield-run/final/data-dictionary.md
- greenfield-run/final/erd.mmd
- greenfield-run/session/mapping_contract.json

Pass criteria:
1. `/mapping` prints mapping output locations.
2. `/extraction` prints final output locations and mapping contract path.
3. `final/data-dictionary.md` and `final/erd.mmd` both exist.
4. Output column headers reflect the finalized mapping where applicable.

## User Acceptance Assessment Checklist
Use this checklist after each walkthrough run:

1. Coverage
- Did all expected images process without command failure?
- Did at least one entity appear for each schema-like image?

2. Signal quality
- Are entity names meaningful?
- Are obvious OCR garbage rows limited?
- Do parsed columns roughly match expected business fields?

3. Actionability
- Are open questions useful for human review?
- Is data-dictionary.md good enough for downstream refinement?

4. Decision
- Accept for current image set.
- Accept with manual cleanup.
- Reject and improve OCR filtering rules.

## Interpreting Outcomes
- If Entity Count is 0:
  - The input may be non-schema visual content, or OCR failed to produce parseable lines.
- If Entity Count is greater than 0 but noisy:
  - Workflow is functioning; quality tuning is needed for your image style.
- If final outputs are missing:
  - Validate command arguments and terminal environment.

## Troubleshooting
1. Tesseract not found
- Re-run PATH setup in current terminal session.

2. No entities detected
- Try a clearer source image (higher resolution, less UI clutter).
- Run single image mode to isolate behavior.

3. Very noisy entities
- Prefer screenshots focused on schema text/tables rather than dashboards.
- Use the acceptance checklist and mark as "Accept with manual cleanup" or "Reject".

## Quick Regression Command (Maintainer)
Run after parser updates:

    python -m unittest tests.test_image_adapter tests.test_cli tests.test_workbench tests.test_outputs

Expected result:
- All tests pass.

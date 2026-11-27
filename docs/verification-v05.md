# V0.5 engineering verification and release gates

Base: 49a5cfb. Candidate package: 0.5.0.dev1. Run date: 2026-11-28 (Asia/Shanghai). The five development PRs are stacked in roadmap order. Select the final branch for the integrated candidate. Independent signoff and version tags remain pending.

| Stage | Exercised through the application | Open acceptance evidence |
|---|---|---|
| 0.1 | Versioned PI and sample order, fractional quantities, supported currency exponents, incomplete previews, installments, tooling, insurance, approved beneficiaries, A4/Letter and signed preview digests | Independent labeled order cohort and professional visual signoff |
| 0.2 | Packaged 17-source registry, scoped intent lookup, private reference annotations, dated dual-review rule registration, revocation, separate valuation, three document-label languages | Current official sources and professional review for each activated destination. Two acquired open-reference originals remain private. No third-party training authorization is asserted |
| 0.3 | Workbook scan, signed mapping, immutable original, brand rows, static appendices, images, formula caches, actual Calc rendering for approved layouts and independent readback | 30 authorized distinct enterprise families and group-separated acceptance. Named ranges are inspected; unsupported names, active formulas and conflicting fixed content require migration |
| 0.4 | Split shipment, reservations, revision, origin, weights, volume, return/cancellation, signed CI/PL, customs worksheets, contract draft and credit discrepancy checklist | 150 independently labeled cross-document scenarios; origin verification, jurisdiction-specific filing and real shipment signoff. CN pre-entry is a structured draft, not a filing integration |
| 0.5 | Authenticated HTTP and stdio, tenant storage isolation, scoped registries, review page/callback, download expiry, idempotent ingestion, archive retry, backup/restore, status counters, optional S3 adapter, contract export and SBOM | Live enterprise gateway/S3/IAM, pilot organizations, independent blind cases, operational retention approvals and hosted CI |

## Reproducible evidence

- Python 3.11 and 3.12 isolated environments, installed with requirements.lock. Each ran 147 Pytest cases. Local Calc rendered the signed template with an appendix. Warnings are SDK/dependency deprecations.
- A real stdio client discovers all 41 structured tools and calls each one successfully. The HTTP integration uses a loopback TCP socket, real MCP sessions, two tenants and separate viewer/editor credentials. Cross-tenant reads and downloads and viewer mutations are rejected.
- Both environments ran the 100-intake synthetic Make/Block cohort. Seventy proceeded with simulated signatures; thirty required clarification. Zero wrong releases, false blocks, incorrect totals or unauthorized releases in this cohort. These cases are variations of a fixture and do not meet the independent-case population thresholds.
- Six fictional Excel/PDF pairs cover German standard PI, French image PI, British sample order, US Letter sample PI, a batch commercial invoice and packing list. The full sample PI is USD 68.50; the split shipment is one pair at USD 15.25 plus USD 4.20 batch freight, total USD 19.45. The six PDF layouts and spreadsheet prints were inspected as rendered pages. Automated checks also exercise a multipage table and a two-sheet signed enterprise template. Independent human visual review is outstanding.
- Recovery tests verify hashes, restore to a separate directory, reject corruption and retry an issuance after a simulated archive outage. S3 checksum protocol was tested using a stand-in. Production object storage was not connected.
- Built a wheel and checked its registry, PI standard and entry points. The base/test lock scan reported zero known advisories for 43 scanned packages. This is a point-in-time dependency scan. Export a deployment-specific SBOM with tools/export_contract.py; optional S3 and host packages require their own scan.
- GitHub Actions returned a runner-start failure on PR 1. GitHub's check annotation identified an account billing lock. No hosted green build is claimed. The local dual-version result is independently reproducible.

## Before release

Obtain account-owner resolution of hosted CI, actual template use permissions, and double-reviewed real transactions split by company, source and template. Run the blind evaluator and report the actual population, uncertainty interval and failures. No real first-pass rate or field accuracy has been measured. Run deployment drills for tenant provisioning, finance verification, recovery and object lifecycle. Release only after the roadmap's stage signoffs.

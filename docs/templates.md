# V0.1 template contract

Choose the order kind for Standard PI, Product Image PI, Sample PI or Sample Order Sheet. The image PI requires product photos per row for approval. Attach PNG/JPEG bytes as base64 in the order logo or item image field. Multi-SKU rows retain the SKU, description, specification, quantity, unit and unit price. Sample documents additionally require customization, charging policy and credit toward a bulk purchase.

For enterprise XLSX layouts place the following exact anchors once in column A of a single six-column worksheet. The register tool recognizes them, checks spacing and stores the workbook under a content hash. Select the returned hash as the order template_id.

| Anchor | Position example | Generated section |
|---|---|---|
| {{title}} | A2 | Document title merged across A:E, with space for logo |
| {{details}} | A4 | Twelve label/value slots, with merged B:F values |
| {{items}} | A20 | Repeated item header, dynamic rows, editable formulas and totals |

Leave at least twelve rows between the metadata and line header. Title and column header cells may carry enterprise colors and fonts. The engine sets print area, repeats the line header and fits one page wide. Existing business values, formulas, arbitrary merges, hidden rows and external links are outside this profile. Include the logo in the order. PDF uses the standard A4 layout and order assets independently of Excel cell placement.

Explicit zero is required for unused fees. Sample fee is a one-time separate line and unit price applies per unit. Discount is a positive absolute currency amount. Free samples allow buyer-paid freight. Round each extended price half-up to the currency minor unit. USD, EUR, GBP and CNY use two decimals, JPY uses zero. No taxes, FX conversion or inferred delivery promises.

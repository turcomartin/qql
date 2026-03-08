# Data Context: sales

_Auto-generated. Your **Notes** are preserved across regenerations._

Last updated: 2026-03-08 14:13 UTC


## Business Domain
This table stores daily restaurant sales transactions spanning September 21 to November 20, 2024, tracking sold products by waiter, ticket number, and monetary values. The data reflects a high-frequency retail environment with negative totals and quantities indicating returns or adjustments within the same reporting period.

## Column Guide
- date — transaction timestamp covering a 61-day span in late 2024 (YYYY-MM-DD format)
- week_day — text label for the day of the week corresponding to the date column
- hour — time of day without timezone indicating when the sale occurred within the service window
- ticket_number — unique identifier per transaction starting with prefixes FCA, FCB, NCA, or NCB
- waiter — employee ID assigned to the transaction (high variance implied by stddev of 21.76)
- product_name — name of the item sold, dominated by various types of Alfajores and Conitos
- quantity — number of units sold per line allowing negative values for returns or adjustments
- unitary_price — cost per individual unit showing wide price distribution (stddev 7603.17 vs avg 6990.29)
- total — aggregate monetary value per ticket which can be negative, indicating refunds or credits

## Taxonomy
**Alfajor Varieties**: Alf. 150 aniv. Suelto, Alfador Sin Azucar Suelto, Alfajor choc x un, Alfajor merengue x un
**Dessert Brands**: Conito choc caja x6un, Conito coco y ddl suelto, Dulce de leche vidrio x450g
**Packing Formats**: Suelto (loose), caja x12un (box of 12), caja x6un (box of 6), pouch x475g

## Key Metrics
- Busiest Day: Friday with 4160 distinct transactions
- Top Product: Alf. 150 aniv. Suelto with 2551 occurrences
- Typical Unit Price Range: 1900.00 to 10000.00 (P25–P75)
- Total Transaction Span: 61 days (2024-09-21 to 2024-11-20)

## Business Rules
Returns/refunds: `quantity < 0`
Revenue calculation: `sum(quantity * unitary_price)` grouped by product_name
Filter active waiters: `waiter >= P25 (101.00)` to exclude low-volume outliers
Negative ticket logic check: `total < 0` identifies refund transactions
Date range filter: `date BETWEEN '2024-09-21' AND '2024-11-20'`

## Data Quality Notes
No significant quality issues detected.

---

## Dataset Overview
- Table: sales
- Total rows: 24,212
- Date range: 2024-09-21 → 2024-11-20



## Column Overview
| Column | Type | Distinct | Null% | Range / Values |
|--------|------|----------|-------|----------------|
| date | date | — | 0% | 2024-09-21 → 2024-11-20 |
| week_day | text | 7 | 0% | Friday, Monday, Saturday, Sunday, Thursday, … |
| hour | time without time zone | — | 0% | 09:13:00 → 22:02:00 |
| ticket_number | text | high | 0% | prefixes: FCA, FCB, NCA, NCB |
| waiter | integer | 9 | 0% | 0 – 116, avg 93.52, σ 21.76 |
| product_name | text | 68 | 0% | top: Alf. 150 aniv. Suelto |
| quantity | numeric | 25 | 0% | -4.00 – 30.00, avg 1.40, σ 1.11 |
| unitary_price | numeric | 67 | 0% | 0.00 – 75000.00, avg 6990.29, σ 7603.17 |
| total | numeric | 220 | 0% | -43000.00 – 605000.00, avg 8888.22, σ 12043.36 |



## Value Reference

### week_day
Distinct values (7): Friday, Monday, Saturday, Sunday, Thursday, Tuesday, Wednesday

### ticket_number
~11,771 distinct values (high-cardinality). Common prefixes: FCA, FCB, NCA, NCB. Do not filter on this column unless the user provides an exact value.

### waiter
9 distinct integer values. Range: 0 – 116

### product_name
68 distinct values. Top 30 by frequency:
Alf. 150 aniv. Suelto, Alfajor Sin Azucar Suelto, Alfajor choc x un, Alfajor choc blanco nuez x un, Alfajor merengue x un, Alfajor mixto caja x12un, Alfajor 70 cacao x un, Alfajor Super DDL x un, Alfajor mixto caja x6un, Alf. 150 aniv. X 8 unidades, Alfajor choc caja x12un, Conito choc caja x6un, Conito coco y ddl suelto, Alfajor Sin Azucar x9 Un, Alfajor choc caja x6un, Conito choc x un, Dulce de leche vidrio x450g, Alfajor choc blanco x un, Alfajor mini choc pouch x475g, Alfajor semilia 70 cacao x un, Alfajor 70 cacao caja x9un, Alfajor surtido caja x6un, Galletita limon caja x12un, Conito choc caja x12un, Alfajor Super DDL x 9 un, Conito coco y ddl x 6 un, Alfajor mini choc pouch x125g, Galletita choc limon caja x12u, Alfajor merengue fruta x un, Alfajor surtido caja x12un

### quantity
25 distinct integer values. Range: -4.00 – 30.00



## Statistics

### waiter
Range: 0 – 116 | Avg: 93.52 | Stddev: 21.76 | Median: 103.00 | P25: 101.00 | P75: 104.00 | Distinct: 9 | Nulls: 0.0%

### quantity
Range: -4.00 – 30.00 | Avg: 1.40 | Stddev: 1.11 | Median: 1.00 | P25: 1.00 | P75: 1.00 | Distinct: 25 | Nulls: 0.0%

### unitary_price
Range: 0.00 – 75000.00 | Avg: 6990.29 | Stddev: 7603.17 | Median: 2500.00 | P25: 1900.00 | P75: 10000.00 | Distinct: 67 | Nulls: 0.0%

### total
Range: -43000.00 – 605000.00 | Avg: 8888.22 | Stddev: 12043.36 | Median: 4200.00 | P25: 2000.00 | P75: 15000.00 | Distinct: 220 | Nulls: 0.0%

### Date Ranges
- date: 2024-09-21 → 2024-11-20
- hour: 09:13:00 → 22:02:00


---


## Notes
<!-- Add domain knowledge here. This section is never overwritten. -->

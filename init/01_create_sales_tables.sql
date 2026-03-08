-- Ensure dates like 11/13/2024 are parsed correctly
SET datestyle = 'MDY';

-- 1) Table definition matching services/dataset/data.csv
CREATE TABLE IF NOT EXISTS sales(
    "date" date,
    week_day text,
    "hour" time without time zone,
    ticket_number text,
    waiter integer,
    product_name text,
    quantity numeric(12, 2),
    unitary_price numeric(12, 2),
    total numeric(12, 2)
);


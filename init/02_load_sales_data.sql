-- 2) Load CSV data into the sales table
COPY sales("date", week_day, "hour", ticket_number, waiter, product_name, quantity, unitary_price, total)
FROM
    '/docker-entrypoint-initdb.d/data.csv' WITH (
        FORMAT csv,
        HEADER TRUE,
        DELIMITER ',');


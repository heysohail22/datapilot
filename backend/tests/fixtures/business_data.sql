-- Isolated test database only. Never apply this fixture to a connected business DB.
CREATE TABLE orders (
    order_id integer PRIMARY KEY,
    customer_id integer NOT NULL,
    sold_at date NOT NULL,
    status text NOT NULL,
    net_revenue numeric(14,2) NOT NULL,
    historical_cogs numeric(14,2) NOT NULL
);
CREATE TABLE order_items (
    item_id integer PRIMARY KEY,
    order_id integer REFERENCES orders(order_id),
    quantity integer NOT NULL
);
INSERT INTO orders VALUES
 (1,1,'2025-01-10','completed',100000,60000),
 (2,2,'2025-01-20','completed',10000,9000),
 (3,1,'2025-02-10','completed',132000,80000),
 (4,3,'2025-02-15','cancelled',999999,1),
 (5,4,'2024-01-10','completed',50000,30000),
 (6,5,'2023-01-10','completed',40000,25000),
 (7,6,'2022-01-10','completed',30000,18000),
 (8,7,'2021-01-10','completed',20000,10000);
INSERT INTO order_items VALUES (1,1,1),(2,1,2),(3,2,1),(4,3,1);

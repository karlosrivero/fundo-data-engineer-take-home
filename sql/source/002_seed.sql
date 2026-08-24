INSERT INTO customers VALUES
  (1, 'AR-100', 'Ana', 'Rivera', '1988-04-10', 'ana@example.com', '+541155501001', FALSE, '2025-01-01 00:00:00+00', '2025-01-01 00:00:00+00'),
  (2, ' ar 100 ', 'Ana', 'Rivera', '1988-04-10', 'ANA@example.com ', '11 5550 1001', FALSE, '2025-01-03 00:00:00+00', '2025-01-03 00:00:00+00'),
  (3, 'AR-200', 'Luis', 'Testerman', '1979-06-01', 'luis@fundo.com', '+541155501003', FALSE, '2025-01-01 00:00:00+00', '2025-01-01 00:00:00+00'),
  (4, NULL, 'Demo', 'Account', NULL, 'test@fundo.com', '000', TRUE, '2025-01-01 00:00:00+00', '2025-01-01 00:00:00+00'),
  (5, NULL, 'Mara', 'Lopez', '1991-11-20', 'shared@example.com', '+541155501005', FALSE, '2025-01-02 00:00:00+00', '2025-01-02 00:00:00+00'),
  (6, NULL, 'Maria', 'Lopez', '1991-11-20', 'shared@example.com', '+541155501006', FALSE, '2025-01-02 00:00:00+00', '2025-01-02 00:00:00+00'),
  (7, 'AR-300', 'Noah', 'Diaz', '1985-09-09', 'not-an-email', '123', FALSE, '2025-01-04 00:00:00+00', '2025-01-04 00:00:00+00'),
  (8, NULL, 'Ops', 'Real', '1990-02-02', 'ops@fundo.com', '+541155501008', FALSE, '2025-01-05 00:00:00+00', '2025-01-05 00:00:00+00');

INSERT INTO advances VALUES
  (101, 1, 'requested', 100000, '2025-01-05 00:00:00+00', '2025-01-05 00:00:00+00'),
  (102, 2, 'funded', 150000, '2025-01-06 00:00:00+00', '2025-01-06 00:00:00+00'),
  (103, 3, 'paid_off', 200000, '2025-01-05 00:00:00+00', '2025-02-01 00:00:00+00'),
  (104, 5, 'cancelled', 80000, '2025-01-07 00:00:00+00', '2025-01-07 00:00:00+00'),
  (105, 6, 'requested', 90000, '2025-01-08 00:00:00+00', '2025-01-08 00:00:00+00'),
  (106, 8, 'funded', 125000, '2025-01-09 00:00:00+00', '2025-01-09 00:00:00+00');

INSERT INTO cards VALUES
  ('card-1', 1, 'tok_001', '1111', 'active', '2025-01-05 00:00:00+00', '2025-01-05 00:00:00+00'),
  ('card-2', 2, 'tok_002', '2222', 'active', '2025-01-06 00:00:00+00', '2025-01-06 00:00:00+00'),
  ('card-3', 3, 'tok_003', '3333', 'inactive', '2025-01-06 00:00:00+00', '2025-01-06 00:00:00+00'),
  ('card-4', 5, 'tok_004', '4444', 'active', '2025-01-07 00:00:00+00', '2025-01-07 00:00:00+00');

INSERT INTO transactions
SELECT 100000 + n,
       101 + (n % 6),
       CASE WHEN n % 3 = 0 THEN 'repayment' ELSE 'disbursement' END,
       1000 + (n % 10000),
       '2025-01-01 00:00:00+00'::timestamptz + (n || ' minutes')::interval,
       '2025-01-01 00:00:00+00'::timestamptz + (n || ' minutes')::interval
FROM generate_series(1, 1000) AS n;

INSERT INTO advance_status_history (advance_id, status, changed_at)
SELECT advance_id, status, updated_at FROM advances;

INSERT INTO scratch_customer_export
SELECT customer_id, row_to_json(customers)::text, '2025-02-01 00:00:00+00'
FROM customers;


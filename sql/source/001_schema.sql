CREATE TABLE customers (
    customer_id BIGINT PRIMARY KEY,
    government_id TEXT,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    birth_date DATE,
    email TEXT,
    phone TEXT,
    is_test BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE advances (
    advance_id BIGINT PRIMARY KEY,
    customer_id BIGINT NOT NULL REFERENCES customers(customer_id),
    status TEXT NOT NULL CHECK (status IN ('requested', 'funded', 'paid_off', 'cancelled')),
    amount_cents BIGINT NOT NULL CHECK (amount_cents >= 0),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE transactions (
    transaction_id BIGINT PRIMARY KEY,
    advance_id BIGINT NOT NULL REFERENCES advances(advance_id),
    transaction_type TEXT NOT NULL,
    amount_cents BIGINT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE cards (
    card_id TEXT PRIMARY KEY, -- deliberate bad schema choice: identifier is unbounded text
    customer_id BIGINT NOT NULL REFERENCES customers(customer_id),
    token TEXT NOT NULL UNIQUE,
    last_four CHAR(4) NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE advance_status_history (
    history_id BIGSERIAL PRIMARY KEY,
    advance_id BIGINT NOT NULL REFERENCES advances(advance_id),
    status TEXT NOT NULL,
    changed_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE scratch_customer_export (
    customer_id BIGINT,
    exported_payload TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE demo_mutations (
    mutation_name TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX customers_updated_idx ON customers(updated_at);
CREATE INDEX advances_updated_idx ON advances(updated_at);
CREATE INDEX transactions_updated_idx ON transactions(updated_at);
CREATE INDEX cards_updated_idx ON cards(updated_at);


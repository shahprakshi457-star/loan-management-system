USE loan_mang;

-- Valid loan: Ravi, Chennai Main, Personal Loan
INSERT INTO loan (borrower_id, officer_id, branch_id, product_id,
                  principal, annual_rate_pct, tenure_months, start_date)
VALUES (1, 1, 1, 2, 100000, 12, 12, '2026-11-01');

UPDATE loan SET status = 'ACTIVE' WHERE loan_id = 1;     -- trigger builds 12 installments
SELECT * FROM installment WHERE loan_id = 1;

CALL record_payment(1, 8884.88, 'UPI', 'UPI123');        -- pays installment 1 in full
SELECT * FROM v_installment_status WHERE loan_id = 1;
SELECT * FROM v_loan_outstanding;

-- These should FAIL, which is what you show in Assessment 10:
INSERT INTO loan (borrower_id, officer_id, branch_id, product_id,
                  principal, annual_rate_pct, tenure_months, start_date)
VALUES (2, 2, 1, 2, 100000, 12, 12, '2026-11-01');       -- Meena isn't certified for Personal Loan

INSERT INTO loan (borrower_id, officer_id, branch_id, product_id,
                  principal, annual_rate_pct, tenure_months, start_date)
VALUES (2, 1, 1, 2, 5000, 12, 12, '2026-11-01');         -- below the product minimum

CALL record_payment(1, 100, 'UPI', 'UPI124');            -- installment already paid

-- 5NF lossless-join demo: rebuilds the original ternary relation
SELECT ob.officer_id, ob.branch_id, bp.product_id
FROM officer_branch ob
JOIN branch_product bp  ON bp.branch_id = ob.branch_id
JOIN officer_product op ON op.officer_id = ob.officer_id AND op.product_id = bp.product_id;
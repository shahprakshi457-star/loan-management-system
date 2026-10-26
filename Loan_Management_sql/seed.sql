USE loan_mang;

INSERT INTO postal_area VALUES
 ('600001','Chennai','Tamil Nadu'),
 ('625001','Madurai','Tamil Nadu'),
 ('641001','Coimbatore','Tamil Nadu');

INSERT INTO loan_product (name, min_amt, max_amt, min_tenure_months, max_tenure_months) VALUES
 ('Home Loan',     500000, 10000000, 60, 360),
 ('Personal Loan',  50000,  1000000,  6,  60);

INSERT INTO officer (name) VALUES ('Ravi'), ('Meena');          -- ids 1, 2
INSERT INTO branch (name, pincode) VALUES
 ('Chennai Main','600001'), ('Madurai Central','625001');       -- ids 1, 2

-- works at
INSERT INTO officer_branch VALUES (1,1), (1,2), (2,1);
-- branch offers   (1 = Home, 2 = Personal)
INSERT INTO branch_product VALUES (1,1), (1,2), (2,1);
-- officer certified for
INSERT INTO officer_product VALUES (1,1), (1,2), (2,1);

INSERT INTO borrower (full_name, dob) VALUES
 ('Asha Kumar','1994-03-12'), ('Rahul Menon','1990-07-25');
INSERT INTO borrower_phone VALUES (1,'9876543210'), (1,'9876500001'), (2,'9123456780');
INSERT INTO borrower_email VALUES (1,'asha@example.com'), (2,'rahul@example.com');
INSERT INTO borrower_address (borrower_id, line1, pincode) VALUES
 (1,'12 Anna Nagar','600001'), (2,'45 KK Nagar','625001');
 
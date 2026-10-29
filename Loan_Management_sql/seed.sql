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

INSERT INTO borrower (full_name, dob) VALUES ('Karthik Subramanian', '1988-11-02');
SET @b = LAST_INSERT_ID();
INSERT INTO borrower_phone VALUES (@b, '9444012301');
INSERT INTO borrower_email VALUES (@b, 'karthik.s@example.com');
INSERT INTO borrower_address (borrower_id, line1, pincode) VALUES (@b, '21 Gandhipuram Main Road', '641001');

INSERT INTO borrower (full_name, dob) VALUES ('Divya Lakshmi', '1992-02-18');
SET @b = LAST_INSERT_ID();
INSERT INTO borrower_phone VALUES (@b, '9444012302'), (@b, '9444012392');
INSERT INTO borrower_email VALUES (@b, 'divya.l@example.com');
INSERT INTO borrower_address (borrower_id, line1, pincode) VALUES (@b, '8 Race Course Road', '641001');

INSERT INTO borrower (full_name, dob) VALUES ('Arjun Venkatesh', '1985-07-30');
SET @b = LAST_INSERT_ID();
INSERT INTO borrower_phone VALUES (@b, '9444012303');
INSERT INTO borrower_email VALUES (@b, 'arjun.v@example.com');
INSERT INTO borrower_address (borrower_id, line1, pincode) VALUES (@b, '54 Usman Road, T Nagar', '600001');

INSERT INTO borrower (full_name, dob) VALUES ('Sneha Iyer', '1999-09-09');
SET @b = LAST_INSERT_ID();
INSERT INTO borrower_phone VALUES (@b, '9444012304');
INSERT INTO borrower_email VALUES (@b, 'sneha.iyer@example.com');
INSERT INTO borrower_address (borrower_id, line1, pincode) VALUES (@b, '3 Tank Street, Mylapore', '600001');

INSERT INTO borrower (full_name, dob) VALUES ('Mohammed Faizal', '1990-01-21');
SET @b = LAST_INSERT_ID();
INSERT INTO borrower_phone VALUES (@b, '9444012305');
INSERT INTO borrower_address (borrower_id, line1, pincode) VALUES (@b, '17 Periyar Bus Stand Road', '625001');

INSERT INTO borrower (full_name, dob) VALUES ('Lakshmi Narayanan', '1979-12-05');
SET @b = LAST_INSERT_ID();
INSERT INTO borrower_phone VALUES (@b, '9444012306'), (@b, '9444012396');
INSERT INTO borrower_email VALUES (@b, 'lakshmi.n@example.com');
INSERT INTO borrower_address (borrower_id, line1, pincode) VALUES (@b, '62 Anna Nagar West', '600001');

INSERT INTO borrower (full_name, dob) VALUES ('Vikram Raj', '1994-04-27');
SET @b = LAST_INSERT_ID();
INSERT INTO borrower_phone VALUES (@b, '9444012307');
INSERT INTO borrower_email VALUES (@b, 'vikram.raj@example.com');
INSERT INTO borrower_address (borrower_id, line1, pincode) VALUES (@b, '9 Goripalayam Main Road', '625001');

INSERT INTO borrower (full_name, dob) VALUES ('Nandini Ramesh', '2001-06-15');
SET @b = LAST_INSERT_ID();
INSERT INTO borrower_phone VALUES (@b, '9444012308');
INSERT INTO borrower_email VALUES (@b, 'nandini.r@example.com');
INSERT INTO borrower_address (borrower_id, line1, pincode) VALUES (@b, '14 RS Puram', '641001');
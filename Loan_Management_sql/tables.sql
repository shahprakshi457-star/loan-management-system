DROP DATABASE IF EXISTS loan_mang;
CREATE DATABASE loan_mang;
USE loan_mang;

CREATE TABLE postal_area(
pincode CHAR(6) PRIMARY KEY,
city VARCHAR(60) NOT NULL,
state VARCHAR(60) NOT NULL
);

CREATE TABLE borrower(
	borrower_id INT AUTO_INCREMENT PRIMARY KEY,
    full_name VARCHAR(100) NOT NULL,
    dob DATE NOT NULL,
    create_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
CREATE TABLE borrower_phone(
	borrower_id INT NOT NULL,
	phone VARCHAR(15) NOT NULL UNIQUE,
	PRIMARY KEY (borrower_id, phone),
	FOREIGN KEY (borrower_id) REFERENCES borrower(borrower_id) ON DELETE CASCADE
);

CREATE TABLE borrower_email(
	borrower_id INT NOT NULL,
	email VARCHAR(100) NOT NULL UNIQUE,
	PRIMARY KEY (borrower_id, email),
	FOREIGN KEY (borrower_id) REFERENCES borrower(borrower_id) ON DELETE CASCADE
);

CREATE TABLE borrower_address(
	address_id INT AUTO_INCREMENT PRIMARY KEY,
    borrower_id INT NOT NULL,
    line1 VARCHAR(150) NOT NULL,
    pincode CHAR(6) NOT NULL,
    FOREIGN KEY (borrower_id) REFERENCES borrower(borrower_id) ON DELETE CASCADE,
    FOREIGN KEY (PINCODE) REFERENCES postal_area(pincode)
    );
    
CREATE TABLE officer(
	officer_id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(80) NOT NULL
    );

CREATE TABLE branch(
	branch_id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(80) NOT NULL UNIQUE,
    pincode CHAR(6) NOT NULL,
    FOREIGN KEY (pincode) REFERENCES postal_area(pincode)
    );
    
CREATE TABLE loan_product(
	product_id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(60) NOT NULL UNIQUE,
    min_amt DECIMAL(14, 2) NOT NULL,
    max_amt DECIMAL(14, 2) NOT NULL,
    min_tenure_months INT NOT NULL,
    max_tenure_months INT NOT NULL,
    CHECK (max_amt >= min_amt),
	CHECK (max_tenure_months >= min_tenure_months)
    );

-- The three binary tables that replace the ternary (officer, branch, product) table
CREATE TABLE officer_branch (
  officer_id INT NOT NULL,
  branch_id  INT NOT NULL,
  PRIMARY KEY (officer_id, branch_id),
  FOREIGN KEY (officer_id) REFERENCES officer(officer_id),
  FOREIGN KEY (branch_id)  REFERENCES branch(branch_id)
);

CREATE TABLE branch_product (
  branch_id  INT NOT NULL,
  product_id INT NOT NULL,
  PRIMARY KEY (branch_id, product_id),
  FOREIGN KEY (branch_id)  REFERENCES branch(branch_id),
  FOREIGN KEY (product_id) REFERENCES loan_product(product_id)
);

CREATE TABLE officer_product (
  officer_id INT NOT NULL,
  product_id INT NOT NULL,
  PRIMARY KEY (officer_id, product_id),
  FOREIGN KEY (officer_id) REFERENCES officer(officer_id),
  FOREIGN KEY (product_id) REFERENCES loan_product(product_id)
);

CREATE TABLE loan (
  loan_id         INT AUTO_INCREMENT PRIMARY KEY,
  borrower_id     INT NOT NULL,
  officer_id      INT NOT NULL,
  branch_id       INT NOT NULL,
  product_id      INT NOT NULL,
  principal       DECIMAL(14,2) NOT NULL CHECK (principal > 0),
  annual_rate_pct DECIMAL(6,3)  NOT NULL CHECK (annual_rate_pct > 0),
  tenure_months   INT NOT NULL CHECK (tenure_months > 0),
  start_date      DATE NOT NULL,
  status          ENUM('APPLIED','ACTIVE','CLOSED','DEFAULTED') NOT NULL DEFAULT 'APPLIED',
  created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (borrower_id) REFERENCES borrower(borrower_id),
  -- these three composite FKs enforce the 5NF business rule
  FOREIGN KEY (officer_id, branch_id)  REFERENCES officer_branch(officer_id, branch_id),
  FOREIGN KEY (branch_id,  product_id) REFERENCES branch_product(branch_id, product_id),
  FOREIGN KEY (officer_id, product_id) REFERENCES officer_product(officer_id, product_id)
);

CREATE TABLE installment (
  installment_id INT AUTO_INCREMENT PRIMARY KEY,
  loan_id        INT NOT NULL,
  seq_no         INT NOT NULL,
  due_date       DATE NOT NULL,
  principal_due  DECIMAL(14,2) NOT NULL CHECK (principal_due >= 0),
  interest_due   DECIMAL(14,2) NOT NULL CHECK (interest_due  >= 0),
  UNIQUE (loan_id, seq_no),
  FOREIGN KEY (loan_id) REFERENCES loan(loan_id)
);

CREATE TABLE payment (
  payment_id     INT AUTO_INCREMENT PRIMARY KEY,
  loan_id        INT NOT NULL,
  amount         DECIMAL(14,2) NOT NULL CHECK (amount > 0),
  mode           ENUM('UPI','CARD','NETBANKING','CASH') NOT NULL,
  bank_reference VARCHAR(60),
  status         ENUM('PENDING','SUCCESS','FAILED','REVERSED') NOT NULL DEFAULT 'SUCCESS',
  paid_at        DATETIME NOT NULL,
  UNIQUE (mode, bank_reference),
  FOREIGN KEY (loan_id) REFERENCES loan(loan_id)
);

CREATE TABLE installment_payment (
  payment_id     INT NOT NULL,
  installment_id INT NOT NULL,
  principal_paid DECIMAL(14,2) NOT NULL CHECK (principal_paid >= 0),
  interest_paid  DECIMAL(14,2) NOT NULL CHECK (interest_paid  >= 0),
  PRIMARY KEY (payment_id, installment_id),
  FOREIGN KEY (payment_id)     REFERENCES payment(payment_id),
  FOREIGN KEY (installment_id) REFERENCES installment(installment_id)
);

CREATE INDEX idx_installment_due ON installment(due_date);
CREATE INDEX idx_loan_status ON loan(status);

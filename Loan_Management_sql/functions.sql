USE loan_mang;
DELIMITER $$

-- Builds the EMI schedule (reducing balance)
CREATE PROCEDURE generate_emi_schedule(IN p_loan_id BIGINT)
BEGIN
  DECLARE v_p DECIMAL(14,2);
  DECLARE v_rate DECIMAL(6,3);
  DECLARE v_n INT;
  DECLARE v_start DATE;
  DECLARE v_r DOUBLE;
  DECLARE v_emi DECIMAL(14,2);
  DECLARE v_bal DECIMAL(14,2);
  DECLARE v_int DECIMAL(14,2);
  DECLARE v_prin DECIMAL(14,2);
  DECLARE i INT DEFAULT 1;

  SELECT principal, annual_rate_pct, tenure_months, start_date
    INTO v_p, v_rate, v_n, v_start
    FROM loan WHERE loan_id = p_loan_id;

  SET v_r   = v_rate / 12 / 100;
  SET v_emi = ROUND(v_p * v_r * POW(1 + v_r, v_n) / (POW(1 + v_r, v_n) - 1), 2);
  SET v_bal = v_p;

  WHILE i <= v_n DO
    SET v_int  = ROUND(v_bal * v_r, 2);
    SET v_prin = v_emi - v_int;
    IF i = v_n THEN SET v_prin = v_bal; END IF;   -- last EMI absorbs rounding

    INSERT INTO installment (loan_id, seq_no, due_date, principal_due, interest_due)
    VALUES (p_loan_id, i, DATE_ADD(v_start, INTERVAL i MONTH), v_prin, v_int);

    SET v_bal = v_bal - v_prin;
    SET i = i + 1;
  END WHILE;
END$$

-- Records a payment against one installment (interest first, then principal)
CREATE PROCEDURE record_payment(
  IN p_installment_id BIGINT, IN p_amount DECIMAL(14,2),
  IN p_mode VARCHAR(20), IN p_ref VARCHAR(60))
BEGIN
  DECLARE v_loan BIGINT DEFAULT NULL;
  DECLARE v_status VARCHAR(20);
  DECLARE v_prin_due, v_int_due, v_prin_paid, v_int_paid DECIMAL(14,2);
  DECLARE v_prin_left, v_int_left, v_int_pay, v_prin_pay DECIMAL(14,2);
  DECLARE v_pid BIGINT;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;

  START TRANSACTION;

  SELECT i.loan_id, i.principal_due, i.interest_due, l.status
    INTO v_loan, v_prin_due, v_int_due, v_status
    FROM installment i JOIN loan l ON l.loan_id = i.loan_id
   WHERE i.installment_id = p_installment_id FOR UPDATE;

  IF v_loan IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Installment not found';
  END IF;
  IF v_status <> 'ACTIVE' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Loan is not active';
  END IF;
  IF p_amount <= 0 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Amount must be positive';
  END IF;

  SELECT COALESCE(SUM(ip.principal_paid),0), COALESCE(SUM(ip.interest_paid),0)
    INTO v_prin_paid, v_int_paid
    FROM installment_payment ip JOIN payment p ON p.payment_id = ip.payment_id
   WHERE ip.installment_id = p_installment_id AND p.status = 'SUCCESS';

  SET v_prin_left = v_prin_due - v_prin_paid;
  SET v_int_left  = v_int_due  - v_int_paid;

  IF v_prin_left + v_int_left <= 0 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Installment already paid';
  END IF;
  IF p_amount > v_prin_left + v_int_left THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Payment exceeds amount due';
  END IF;

  SET v_int_pay  = LEAST(p_amount, v_int_left);
  SET v_prin_pay = p_amount - v_int_pay;

  INSERT INTO payment (loan_id, amount, mode, bank_reference, status, paid_at)
  VALUES (v_loan, p_amount, p_mode, p_ref, 'SUCCESS', NOW());
  SET v_pid = LAST_INSERT_ID();

  INSERT INTO installment_payment (payment_id, installment_id, principal_paid, interest_paid)
  VALUES (v_pid, p_installment_id, v_prin_pay, v_int_pay);

  COMMIT;
END$$

-- Validates the loan against product limits
CREATE TRIGGER trg_loan_limits BEFORE INSERT ON loan
FOR EACH ROW
BEGIN
  DECLARE v_min, v_max DECIMAL(14,2);
  DECLARE v_tmin, v_tmax INT;
    SELECT min_amt, max_amt, min_tenure_months, max_tenure_months
    INTO v_min, v_max, v_tmin, v_tmax
    FROM loan_product WHERE product_id = NEW.product_id;
  IF NEW.principal < v_min OR NEW.principal > v_max THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Principal outside product limits';
  END IF;
  IF NEW.tenure_months < v_tmin OR NEW.tenure_months > v_tmax THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Tenure outside product limits';
  END IF;
END$$

-- Approving a loan (APPLIED -> ACTIVE) generates its schedule
CREATE TRIGGER trg_loan_activate AFTER UPDATE ON loan
FOR EACH ROW
BEGIN
  IF OLD.status = 'APPLIED' AND NEW.status = 'ACTIVE' THEN
    CALL generate_emi_schedule(NEW.loan_id);
  END IF;
END$$

DELIMITER ;

-- Derived status and balances (nothing stored that could drift)
CREATE VIEW v_installment_status AS
SELECT i.installment_id, i.loan_id, i.seq_no, i.due_date,
       i.principal_due, i.interest_due,
       i.principal_due + i.interest_due AS total_due,
       COALESCE(SUM(CASE WHEN p.status = 'SUCCESS'
                         THEN ip.principal_paid + ip.interest_paid END), 0) AS total_paid,
       CASE
         WHEN COALESCE(SUM(CASE WHEN p.status = 'SUCCESS'
                                THEN ip.principal_paid + ip.interest_paid END), 0)
              >= i.principal_due + i.interest_due THEN 'PAID'
         WHEN i.due_date < CURDATE() THEN 'OVERDUE'
         ELSE 'PENDING'
       END AS status
FROM installment i
LEFT JOIN installment_payment ip ON ip.installment_id = i.installment_id
LEFT JOIN payment p              ON p.payment_id = ip.payment_id
GROUP BY i.installment_id, i.loan_id, i.seq_no, i.due_date, i.principal_due, i.interest_due;

CREATE VIEW v_loan_outstanding AS
SELECT l.loan_id, l.principal,
       l.principal - COALESCE(SUM(CASE WHEN p.status = 'SUCCESS'
                                       THEN ip.principal_paid END), 0) AS outstanding_principal
FROM loan l
LEFT JOIN installment i          ON i.loan_id = l.loan_id
LEFT JOIN installment_payment ip ON ip.installment_id = i.installment_id
LEFT JOIN payment p              ON p.payment_id = ip.payment_id
GROUP BY l.loan_id, l.principal;

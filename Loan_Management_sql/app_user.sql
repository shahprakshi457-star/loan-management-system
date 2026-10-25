CREATE USER 'loan_app'@'localhost' IDENTIFIED BY 'star';
GRANT SELECT, INSERT, UPDATE, DELETE, EXECUTE ON loan_mang.* TO 'loan_app'@'localhost';
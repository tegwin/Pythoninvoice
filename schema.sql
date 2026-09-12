-- ============================================================
--  Invoice Manager - Complete MySQL / MariaDB Schema
--
--  Generated from the application source, then verified by
--  loading into MySQL 8.0 and running the app against it.
--  Safe to re-run: every CREATE is IF NOT EXISTS.
--
--  Load with:
--    mysql -u<user> -p <database> < schema.sql
-- ============================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

CREATE DATABASE IF NOT EXISTS `invoice_manager`
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE `invoice_manager`;

CREATE TABLE IF NOT EXISTS `api_keys` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  name VARCHAR(255) NOT NULL,
  key_hash VARCHAR(255) NOT NULL,
  key_prefix VARCHAR(20) NOT NULL,
  permissions TEXT,
  last_used TIMESTAMP NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  active TINYINT DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `bill_items` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  bill_id INT NOT NULL,
  description TEXT,
  quantity DECIMAL(15,4) DEFAULT 1,
  unit_price DECIMAL(15,2) DEFAULT 0,
  total DECIMAL(15,2) DEFAULT 0,
  coa_id INT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `bill_payments` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  bill_id INT NOT NULL,
  amount DECIMAL(15,2) NOT NULL,
  payment_date DATE NOT NULL,
  payment_method VARCHAR(100),
  reference VARCHAR(255),
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `bills` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  supplier_id INT,
  bill_number VARCHAR(100) NOT NULL,
  reference VARCHAR(255),
  bill_date DATE NOT NULL,
  due_date DATE,
  currency VARCHAR(10) DEFAULT 'GBP',
  tax_rate DECIMAL(10,2) DEFAULT 0,
  subtotal DECIMAL(15,2) DEFAULT 0,
  tax_amount DECIMAL(15,2) DEFAULT 0,
  total DECIMAL(15,2) DEFAULT 0,
  amount_paid DECIMAL(15,2) DEFAULT 0,
  status VARCHAR(50) DEFAULT 'draft',
  notes TEXT,
  attachment_path VARCHAR(500),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `exchange_rate` DECIMAL(15,6) DEFAULT 1,
  `base_currency` VARCHAR(10),
  `base_total` DECIMAL(15,2)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `chart_of_accounts` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  code VARCHAR(50) NOT NULL,
  name VARCHAR(255) NOT NULL,
  account_type VARCHAR(100) NOT NULL,
  description TEXT,
  parent_id INT,
  active TINYINT DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY unique_code (user_id, code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `company_settings` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  company_name VARCHAR(255),
  address_line1 VARCHAR(255),
  address_line2 VARCHAR(255),
  city VARCHAR(100),
  state VARCHAR(100),
  postal_code VARCHAR(50),
  country VARCHAR(100),
  phone VARCHAR(100),
  email VARCHAR(255),
  website VARCHAR(255),
  logo_path VARCHAR(500),
  default_tax_rate DECIMAL(10,2) DEFAULT 0,
  default_currency VARCHAR(10) DEFAULT 'GBP',
  invoice_prefix VARCHAR(50) DEFAULT 'INV',
  invoice_next_number INT DEFAULT 1001,
  payment_terms TEXT,
  bank_details TEXT,
  smtp_host VARCHAR(255),
  smtp_port INT DEFAULT 587,
  smtp_username VARCHAR(255),
  smtp_password VARCHAR(255),
  smtp_use_tls TINYINT DEFAULT 1,
  smtp_from_email VARCHAR(255),
  reminders_enabled TINYINT DEFAULT 0,
  reminder_1_days INT DEFAULT 7,
  reminder_2_days INT DEFAULT 0,
  reminder_3_days INT DEFAULT -7,
  max_reminders INT DEFAULT 3,
  send_payment_thanks TINYINT DEFAULT 0,
  brand_name VARCHAR(255),
  brand_logo_path VARCHAR(500),
  show_brand_name TINYINT DEFAULT 1,
  show_brand_logo TINYINT DEFAULT 0,
  show_powered_by TINYINT DEFAULT 0,
  tax_rates VARCHAR(255) DEFAULT '0,5,10,15,20,25',
  show_footer TINYINT DEFAULT 1,
  footer_text VARCHAR(500) DEFAULT 'Powered by Invoice Manager',
  currency_api_key VARCHAR(255),
  currency_api_provider VARCHAR(100) DEFAULT 'currencyapi',
  auto_update_rates TINYINT DEFAULT 0,
  rates_last_updated TIMESTAMP NULL,
  `email_invoice_created` TINYINT DEFAULT 0,
  `tax_authority` VARCHAR(100),
  `tax_authority_api_key` VARCHAR(500),
  `tax_authority_email` VARCHAR(255),
  `accountant_name` VARCHAR(255),
  `accountant_email` VARCHAR(255),
  `accountant_phone` VARCHAR(100),
  `email_provider` VARCHAR(50) DEFAULT 'smtp',
  `graph_tenant_id` VARCHAR(255),
  `graph_client_id` VARCHAR(255),
  `graph_client_secret` VARCHAR(500),
  `graph_sender_email` VARCHAR(255),
  `coa_mandatory` TINYINT DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `credit_note_applications` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  credit_note_id INT NOT NULL,
  invoice_id INT NOT NULL,
  amount DECIMAL(12,2) NOT NULL,
  applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  notes TEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `credit_note_items` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  credit_note_id INT NOT NULL,
  description VARCHAR(2000) NOT NULL,
  quantity DECIMAL(10,4) DEFAULT 1,
  unit_price DECIMAL(12,2) DEFAULT 0,
  tax_rate DECIMAL(5,2) DEFAULT 0,
  line_total DECIMAL(12,2) DEFAULT 0,
  sort_order INT DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `credit_notes` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  credit_note_number VARCHAR(50) NOT NULL,
  customer_id INT,
  invoice_id INT,
  status VARCHAR(20) DEFAULT 'draft',
  issue_date DATE,
  currency VARCHAR(10) DEFAULT 'GBP',
  tax_rate DECIMAL(5,2) DEFAULT 0,
  subtotal DECIMAL(12,2) DEFAULT 0,
  tax_amount DECIMAL(12,2) DEFAULT 0,
  total DECIMAL(12,2) DEFAULT 0,
  amount_used DECIMAL(12,2) DEFAULT 0,
  reason TEXT,
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `currency_rates` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  base_currency VARCHAR(10) NOT NULL,
  target_currency VARCHAR(10) NOT NULL,
  rate DECIMAL(20,10) NOT NULL,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY unique_rate (user_id, base_currency, target_currency)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `customer_portal_users` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  customer_id INT NOT NULL,
  email VARCHAR(255) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  is_active TINYINT DEFAULT 1,
  must_change_password TINYINT DEFAULT 1,
  last_login TIMESTAMP NULL,
  impersonation_token VARCHAR(255) NULL,
  impersonation_expires TIMESTAMP NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY unique_customer_portal (user_id, customer_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `customers` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  uuid VARCHAR(36),
  user_id INT NOT NULL,
  name VARCHAR(255) NOT NULL,
  email VARCHAR(255),
  phone VARCHAR(100),
  address_line1 VARCHAR(255),
  address_line2 VARCHAR(255),
  city VARCHAR(100),
  state VARCHAR(100),
  postal_code VARCHAR(50),
  country VARCHAR(100),
  tax_number VARCHAR(100),
  custom_tax_rate DECIMAL(10,2),
  custom_currency VARCHAR(10),
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `email_invoice_created` TINYINT DEFAULT 1,
  `email_invoice_reminder` TINYINT DEFAULT 1,
  `email_payment_received` TINYINT DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `email_log` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  invoice_id INT,
  customer_id INT,
  email_type VARCHAR(50) NOT NULL,
  to_email VARCHAR(255) NOT NULL,
  subject VARCHAR(500) NOT NULL,
  status VARCHAR(50) DEFAULT 'pending',
  error_message TEXT,
  sent_at TIMESTAMP NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `email_templates` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  template_type VARCHAR(50) NOT NULL,
  subject VARCHAR(500) NOT NULL,
  body TEXT NOT NULL,
  enabled TINYINT DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY unique_template (user_id, template_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `enabled_currencies` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  currency_code VARCHAR(10) NOT NULL,
  enabled TINYINT DEFAULT 1,
  UNIQUE KEY unique_currency (user_id, currency_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `expenses` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  supplier_id INT,
  coa_id INT,
  expense_date DATE NOT NULL,
  description TEXT,
  category VARCHAR(100),
  amount DECIMAL(15,2) NOT NULL,
  tax_rate DECIMAL(10,2) DEFAULT 0,
  tax_amount DECIMAL(15,2) DEFAULT 0,
  net_amount DECIMAL(15,2) DEFAULT 0,
  currency VARCHAR(10) DEFAULT 'GBP',
  payment_method VARCHAR(100),
  reference VARCHAR(255),
  receipt_path VARCHAR(500),
  is_billable TINYINT DEFAULT 0,
  is_reimbursable TINYINT DEFAULT 0,
  status VARCHAR(50) DEFAULT 'pending',
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `gocardless_billing_requests` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  customer_id INT,
  billing_request_id VARCHAR(255),
  flow_id VARCHAR(255),
  authorisation_url VARCHAR(500),
  status VARCHAR(50),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `gocardless_customers` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  customer_id INT NOT NULL,
  gc_customer_id VARCHAR(255) NOT NULL,
  gc_mandate_id VARCHAR(255),
  mandate_status VARCHAR(50),
  bank_account_last4 VARCHAR(10),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY unique_gc_customer (user_id, customer_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `gocardless_mandates` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  customer_id INT,
  gc_mandate_id VARCHAR(255),
  gc_customer_id VARCHAR(255),
  status VARCHAR(50),
  scheme VARCHAR(50),
  reference VARCHAR(255),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `gocardless_payments` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  invoice_id INT NOT NULL,
  gc_payment_id VARCHAR(255) NOT NULL,
  gc_mandate_id VARCHAR(255),
  amount DECIMAL(15,2) NOT NULL,
  currency VARCHAR(10) DEFAULT 'GBP',
  status VARCHAR(50) DEFAULT 'pending',
  charge_date DATE,
  description VARCHAR(255),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `gocardless_settings` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL UNIQUE,
  enabled TINYINT DEFAULT 0,
  live_mode TINYINT DEFAULT 0,
  sandbox_access_token TEXT,
  live_access_token TEXT,
  webhook_secret VARCHAR(255),
  include_in_invoice_pdf TINYINT DEFAULT 1,
  include_in_email TINYINT DEFAULT 1,
  payment_description VARCHAR(255) DEFAULT 'Invoice Payment',
  days_until_collection INT DEFAULT 5,
  success_redirect_url VARCHAR(500),
  creditor_id VARCHAR(255),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `gocardless_webhook_logs` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT,
  event_type VARCHAR(100),
  event_id VARCHAR(255),
  resource_type VARCHAR(100),
  action VARCHAR(100),
  invoice_id INT,
  status VARCHAR(50),
  message TEXT,
  payload LONGTEXT,
  received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `incoming_webhook_logs` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  webhook_id INT NOT NULL,
  received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  payload LONGTEXT,
  headers TEXT,
  status VARCHAR(50) DEFAULT 'received',
  response TEXT,
  invoice_id INT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `incoming_webhooks` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  name VARCHAR(255) NOT NULL,
  description TEXT,
  endpoint_key VARCHAR(255) NOT NULL UNIQUE,
  secret_key VARCHAR(255),
  provider VARCHAR(100) DEFAULT 'generic',
  active TINYINT DEFAULT 1,
  last_received_at TIMESTAMP NULL,
  receive_count INT DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `invoice_items` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  invoice_id INT NOT NULL,
  product_id INT,
  description TEXT NOT NULL,
  quantity DECIMAL(15,4) DEFAULT 1,
  unit_price DECIMAL(15,2) DEFAULT 0,
  tax_rate DECIMAL(10,2) DEFAULT 0,
  line_total DECIMAL(15,2) DEFAULT 0,
  sort_order INT DEFAULT 0,
  coa_id INT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `invoice_reminders` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  invoice_id INT NOT NULL,
  reminder_number INT DEFAULT 1,
  days_before_due INT DEFAULT 7,
  scheduled_date DATE,
  sent_at TIMESTAMP NULL,
  status VARCHAR(50) DEFAULT 'pending'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `invoices` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  customer_id INT,
  invoice_number VARCHAR(100) NOT NULL,
  status VARCHAR(50) DEFAULT 'draft',
  issue_date DATE,
  due_date DATE,
  currency VARCHAR(10) DEFAULT 'GBP',
  tax_rate DECIMAL(10,2) DEFAULT 0,
  subtotal DECIMAL(15,2) DEFAULT 0,
  tax_amount DECIMAL(15,2) DEFAULT 0,
  total DECIMAL(15,2) DEFAULT 0,
  amount_paid DECIMAL(15,2) DEFAULT 0,
  notes TEXT,
  payment_terms TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  paid_at TIMESTAMP NULL,
  `exchange_rate` DECIMAL(15,6) DEFAULT 1,
  `base_currency` VARCHAR(10),
  `base_total` DECIMAL(15,2)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `payments` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  invoice_id INT NOT NULL,
  amount DECIMAL(15,2) NOT NULL,
  payment_date DATE NOT NULL,
  payment_method VARCHAR(100),
  reference VARCHAR(255),
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  `created_via` VARCHAR(100)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `products` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  name VARCHAR(255) NOT NULL,
  description TEXT,
  unit_price DECIMAL(15,2) NOT NULL DEFAULT 0,
  unit VARCHAR(50) DEFAULT 'unit',
  sku VARCHAR(100),
  is_service TINYINT DEFAULT 0,
  billing_term VARCHAR(100),
  taxable TINYINT DEFAULT 1,
  active TINYINT DEFAULT 1,
  coa_id INT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `recurring_invoice_items` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  recurring_invoice_id INT NOT NULL,
  product_id INT,
  description TEXT NOT NULL,
  quantity DECIMAL(15,4) DEFAULT 1,
  unit_price DECIMAL(15,2) DEFAULT 0,
  tax_rate DECIMAL(10,2) DEFAULT 0,
  line_total DECIMAL(15,2) DEFAULT 0,
  is_recurring_item TINYINT DEFAULT 1,
  sort_order INT DEFAULT 0,
  coa_id INT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `recurring_invoices` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  customer_id INT NOT NULL,
  frequency VARCHAR(50) NOT NULL,
  start_date DATE NOT NULL,
  end_date DATE,
  next_invoice_date DATE NOT NULL,
  last_invoice_date DATE,
  currency VARCHAR(10) DEFAULT 'GBP',
  tax_rate DECIMAL(10,2) DEFAULT 0,
  notes TEXT,
  payment_terms TEXT,
  auto_send TINYINT DEFAULT 0,
  send_days_before INT DEFAULT 0,
  invoice_prefix VARCHAR(50) DEFAULT 'REC-',
  invoices_generated INT DEFAULT 0,
  active TINYINT DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `roadmap_features` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  phase_id INT,
  title VARCHAR(255) NOT NULL,
  description TEXT,
  status VARCHAR(50) DEFAULT 'planned',
  priority VARCHAR(50) DEFAULT 'medium',
  category VARCHAR(100),
  votes INT DEFAULT 0,
  sort_order INT DEFAULT 0,
  completed_at TIMESTAMP NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `roadmap_phases` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(255) NOT NULL,
  description TEXT,
  status VARCHAR(50) DEFAULT 'planned',
  start_date DATE,
  end_date DATE,
  sort_order INT DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  `target_date` DATE,
  `color` VARCHAR(50),
  `updated_at` TIMESTAMP NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `roadmap_requests` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  title VARCHAR(255),
  description TEXT,
  submitted_by VARCHAR(255),
  email VARCHAR(255),
  status VARCHAR(50) DEFAULT 'pending',
  votes INT DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `stripe_payment_sessions` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  invoice_id INT NOT NULL,
  session_id VARCHAR(255) NOT NULL,
  payment_intent_id VARCHAR(255),
  payment_url VARCHAR(500),
  status VARCHAR(50) DEFAULT 'pending',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `stripe_settings` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL UNIQUE,
  enabled TINYINT DEFAULT 0,
  live_mode TINYINT DEFAULT 0,
  test_publishable_key VARCHAR(255),
  test_secret_key VARCHAR(255),
  live_publishable_key VARCHAR(255),
  live_secret_key VARCHAR(255),
  webhook_secret VARCHAR(255),
  include_in_invoice_pdf TINYINT DEFAULT 1,
  include_in_email TINYINT DEFAULT 1,
  payment_button_text VARCHAR(255) DEFAULT 'Pay Now with Card',
  success_url VARCHAR(500),
  cancel_url VARCHAR(500),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `stripe_webhook_logs` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT,
  event_type VARCHAR(100),
  event_id VARCHAR(255),
  invoice_id INT,
  status VARCHAR(50),
  message TEXT,
  payload LONGTEXT,
  received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `sumup_checkouts` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  invoice_id INT NOT NULL,
  checkout_id VARCHAR(255) NOT NULL,
  checkout_reference VARCHAR(255),
  amount DECIMAL(15,2) NOT NULL,
  currency VARCHAR(10) DEFAULT 'GBP',
  status VARCHAR(50) DEFAULT 'pending',
  payment_url VARCHAR(500),
  transaction_id VARCHAR(255),
  transaction_code VARCHAR(255),
  paid_at TIMESTAMP NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `sumup_settings` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL UNIQUE,
  enabled TINYINT DEFAULT 0,
  api_key VARCHAR(255),
  merchant_code VARCHAR(100),
  include_in_invoice_pdf TINYINT DEFAULT 1,
  include_in_email TINYINT DEFAULT 1,
  payment_description VARCHAR(255) DEFAULT 'Invoice Payment',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `webhook_secret` VARCHAR(255)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `sumup_webhook_logs` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT,
  event_type VARCHAR(100),
  event_id VARCHAR(255),
  invoice_id INT,
  status VARCHAR(50),
  message TEXT,
  payload LONGTEXT,
  received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `suppliers` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  name VARCHAR(255) NOT NULL,
  contact_name VARCHAR(255),
  email VARCHAR(255),
  phone VARCHAR(100),
  address_line1 VARCHAR(255),
  address_line2 VARCHAR(255),
  city VARCHAR(100),
  state VARCHAR(100),
  postal_code VARCHAR(50),
  country VARCHAR(100) DEFAULT 'United Kingdom',
  tax_id VARCHAR(100),
  payment_terms INT DEFAULT 30,
  default_coa_id INT,
  notes TEXT,
  is_active TINYINT DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `team_members` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  owner_user_id INT NOT NULL,
  member_user_id INT NOT NULL,
  role VARCHAR(50) DEFAULT 'viewer',
  permissions TEXT,
  invited_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  accepted_at TIMESTAMP NULL,
  active TINYINT DEFAULT 1,
  UNIQUE KEY unique_team (owner_user_id, member_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `user_preferences` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  preference_key VARCHAR(255) NOT NULL,
  preference_value TEXT,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY unique_pref (user_id, preference_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `users` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  username VARCHAR(255) UNIQUE NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  email VARCHAR(255),
  display_name VARCHAR(255),
  phone VARCHAR(100),
  timezone VARCHAR(100) DEFAULT 'Europe/London',
  bio TEXT,
  avatar_path VARCHAR(500),
  role VARCHAR(50) DEFAULT 'owner',
  parent_user_id INT,
  totp_secret VARCHAR(255),
  totp_enabled TINYINT DEFAULT 0,
  backup_codes TEXT,
  login_count INT DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  last_login TIMESTAMP NULL,
  active TINYINT DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `vat_submissions` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  period_start DATE NOT NULL,
  period_end DATE NOT NULL,
  output_vat DECIMAL(15,2) DEFAULT 0,
  input_vat DECIMAL(15,2) DEFAULT 0,
  net_vat DECIMAL(15,2) DEFAULT 0,
  total_sales DECIMAL(15,2) DEFAULT 0,
  total_purchases DECIMAL(15,2) DEFAULT 0,
  checklist_sales_verified TINYINT DEFAULT 0,
  checklist_vat_numbers TINYINT DEFAULT 0,
  checklist_credit_notes TINYINT DEFAULT 0,
  checklist_expenses_receipts TINYINT DEFAULT 0,
  checklist_partial_exemption TINYINT DEFAULT 0,
  checklist_reverse_charge TINYINT DEFAULT 0,
  checklist_eu_supply TINYINT DEFAULT 0,
  checklist_accountant_reviewed TINYINT DEFAULT 0,
  submitted_to_authority TINYINT DEFAULT 0,
  submitted_to_authority_at TIMESTAMP NULL,
  submitted_to_accountant TINYINT DEFAULT 0,
  submitted_to_accountant_at TIMESTAMP NULL,
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY unique_vat_period (user_id, period_start, period_end)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `webhooks` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  url VARCHAR(500) NOT NULL,
  events TEXT,
  secret VARCHAR(255),
  active TINYINT DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  last_triggered TIMESTAMP NULL,
  failure_count INT DEFAULT 0,
  `webhook_id` VARCHAR(255),
  `name` VARCHAR(255),
  `headers` TEXT,
  `auth_type` VARCHAR(50),
  `auth_value` VARCHAR(255),
  `trigger_count` INT DEFAULT 0,
  `last_status` VARCHAR(50),
  `last_error` TEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `wise_credits` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  invoice_id INT,
  transaction_id VARCHAR(255),
  reference VARCHAR(255),
  amount DECIMAL(15,2),
  currency VARCHAR(10),
  status VARCHAR(50),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `wise_settings` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL UNIQUE,
  enabled TINYINT DEFAULT 0,
  live_mode TINYINT DEFAULT 0,
  sandbox_api_token TEXT,
  live_api_token TEXT,
  profile_id VARCHAR(100),
  webhook_public_key TEXT,
  include_in_invoice_pdf TINYINT DEFAULT 1,
  include_in_email TINYINT DEFAULT 1,
  gbp_account_details TEXT,
  eur_account_details TEXT,
  usd_account_details TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `wise_transactions` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  invoice_id INT,
  transaction_id VARCHAR(255) NOT NULL,
  reference_number VARCHAR(255),
  amount DECIMAL(15,2) NOT NULL,
  currency VARCHAR(10),
  status VARCHAR(50),
  sender_name VARCHAR(255),
  matched_at TIMESTAMP NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY unique_transaction (user_id, transaction_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `wise_transfers` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  invoice_id INT,
  transfer_id VARCHAR(255),
  quote_id VARCHAR(255),
  status VARCHAR(50),
  amount DECIMAL(15,2),
  currency VARCHAR(10),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `wise_webhook_logs` (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT,
  event_type VARCHAR(100),
  event_id VARCHAR(255),
  invoice_id INT,
  status VARCHAR(50),
  message TEXT,
  payload LONGTEXT,
  received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ------------------------------------------------------------
-- Indexes for the most common lookups.
-- ------------------------------------------------------------
CREATE INDEX idx_invoices_user      ON `invoices`      (user_id, status);
CREATE INDEX idx_invoices_customer  ON `invoices`      (customer_id);
CREATE INDEX idx_invoice_items_inv  ON `invoice_items` (invoice_id);
CREATE INDEX idx_payments_invoice   ON `payments`      (invoice_id);
CREATE INDEX idx_customers_user     ON `customers`     (user_id);
CREATE INDEX idx_products_user      ON `products`      (user_id);
CREATE INDEX idx_bills_user         ON `bills`         (user_id, status);
CREATE INDEX idx_expenses_user      ON `expenses`      (user_id);
CREATE INDEX idx_suppliers_user     ON `suppliers`     (user_id);

SET FOREIGN_KEY_CHECKS = 1;

-- Optional manual schema creation; the Python importer creates these staging tables automatically.
-- Run only inside your EXISTING MySQL database.


CREATE TABLE IF NOT EXISTS nameplate_ocr_raw (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  source_key VARCHAR(512) NOT NULL,
  source_file VARCHAR(255) NOT NULL,
  file_sha256 CHAR(64) NOT NULL,
  asset_tag_detected VARCHAR(64) NULL,
  asset_tag_red_ocr VARCHAR(255) NULL,
  ocr_text LONGTEXT NOT NULL,
  ocr_confidence DECIMAL(5,2) NULL,
  parsed_json JSON NOT NULL,
  flags_json JSON NOT NULL,
  imported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_nameplate_source (source_key),
  KEY idx_nameplate_hash (file_sha256),
  KEY idx_nameplate_tag (asset_tag_detected)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS nameplate_assets_staging (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  raw_id BIGINT UNSIGNED NOT NULL,
  asset_tag VARCHAR(64) NULL,
  category VARCHAR(50) NULL,
  manufacturer VARCHAR(100) NULL,
  model VARCHAR(150) NULL,
  serial_number VARCHAR(100) NULL,
  manufactured_ym CHAR(7) NULL,
  power_kw DECIMAL(10,2) NULL,
  electrical_spec VARCHAR(120) NULL,
  fla_amps DECIMAL(10,2) NULL,
  max_speed_rpm INT NULL,
  capacity_raw VARCHAR(255) NULL,
  weight_kg DECIMAL(12,2) NULL,
  lubricant VARCHAR(255) NULL,
  grease_interval_hours INT NULL,
  needs_review TINYINT(1) NOT NULL DEFAULT 1,
  flags_json JSON NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_nameplate_raw_id (raw_id),
  KEY idx_staging_asset_tag (asset_tag),
  CONSTRAINT fk_nameplate_raw FOREIGN KEY (raw_id)
    REFERENCES nameplate_ocr_raw(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

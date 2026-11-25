-- 033: Add singleton platform branding settings for the application shell.

CREATE TABLE IF NOT EXISTS platform_global_settings (
    id INT NOT NULL DEFAULT 1,
    brand_icon VARCHAR(50) NOT NULL DEFAULT 'H',
    brand_name VARCHAR(100) NOT NULL DEFAULT 'AI Hub',
    brand_subtitle VARCHAR(100) NOT NULL DEFAULT '合趣网络',
    updated_by INT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

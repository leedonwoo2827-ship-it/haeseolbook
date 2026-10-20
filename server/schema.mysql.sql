-- 해설북 MySQL 스키마 (MySQL 5.7+ / MariaDB 10.4+, utf8mb4)
-- 설치: mysql -u <user> -p <db> < schema.mysql.sql

CREATE TABLE IF NOT EXISTS hsb_users (
  id          VARCHAR(32)  NOT NULL PRIMARY KEY,
  email       VARCHAR(191) NOT NULL UNIQUE,
  name        VARCHAR(80)  NULL,
  provider    VARCHAR(16)  NOT NULL,
  created_at  DATETIME     NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 기기 유형(pc|tablet|phone)별 활성 기기 1대 (총 3대)
CREATE TABLE IF NOT EXISTS hsb_devices (
  id            VARCHAR(36)  NOT NULL PRIMARY KEY,
  user_id       VARCHAR(32)  NOT NULL,
  type          VARCHAR(8)   NOT NULL,
  label         VARCHAR(80)  NULL,
  refresh_hash  CHAR(64)     NULL,
  last_seen_at  DATETIME     NOT NULL,
  revoked_at    DATETIME     NULL,
  created_at    DATETIME     NOT NULL,
  KEY idx_devices_user_type (user_id, type),
  CONSTRAINT fk_devices_user FOREIGN KEY (user_id) REFERENCES hsb_users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hsb_login_codes (
  code        VARCHAR(64)  NOT NULL PRIMARY KEY,
  user_id     VARCHAR(32)  NOT NULL,
  expires_at  DATETIME     NOT NULL,
  used_at     DATETIME     NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hsb_books (
  id            VARCHAR(64)  NOT NULL PRIMARY KEY,
  title         VARCHAR(200) NOT NULL,
  exam          VARCHAR(80)  NOT NULL,
  subject       VARCHAR(80)  NOT NULL,
  year          INT          NOT NULL,
  round         VARCHAR(40)  NOT NULL,
  -- IP 허브 아이템 패키지 버전 (item.json version). 직접 seed 한 경우 NULL
  item_version  VARCHAR(20)  NULL,
  published_at  DATETIME     NULL,
  created_at    DATETIME     NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hsb_pages (
  id          VARCHAR(80)  NOT NULL PRIMARY KEY,
  book_id     VARCHAR(64)  NOT NULL,
  page_no     INT          NOT NULL,
  width       DOUBLE       NOT NULL,
  height      DOUBLE       NOT NULL,
  image_keys  TEXT         NOT NULL,
  UNIQUE KEY uq_pages_book_no (book_id, page_no),
  CONSTRAINT fk_pages_book FOREIGN KEY (book_id) REFERENCES hsb_books(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hsb_regions (
  id       VARCHAR(80) NOT NULL PRIMARY KEY,
  page_id  VARCHAR(80) NOT NULL,
  kind     VARCHAR(10) NOT NULL,
  quiz_id  VARCHAR(80) NULL,
  x DOUBLE NOT NULL, y DOUBLE NOT NULL, w DOUBLE NOT NULL, h DOUBLE NOT NULL,
  KEY idx_regions_page (page_id),
  CONSTRAINT fk_regions_page FOREIGN KEY (page_id) REFERENCES hsb_pages(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hsb_quizzes (
  id            VARCHAR(80)  NOT NULL PRIMARY KEY,
  book_id       VARCHAR(64)  NOT NULL,
  no            INT          NOT NULL,
  answer        INT          NOT NULL,
  choice_count  INT          NOT NULL DEFAULT 4,
  keywords      TEXT         NOT NULL,
  solution_md   MEDIUMTEXT   NOT NULL,
  youtube_id    VARCHAR(11)  NULL,
  start_sec     DOUBLE       NULL,
  end_sec       DOUBLE       NULL,
  -- AI 해설영상이 넘겨주는 포인터 트랙 [{t,page,x,y}] (영상 시각 ↔ 원문 좌표). 없으면 NULL
  cues          MEDIUMTEXT   NULL,
  UNIQUE KEY uq_quizzes_book_no (book_id, no),
  CONSTRAINT fk_quizzes_book FOREIGN KEY (book_id) REFERENCES hsb_books(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 내 서재 (무료 교재 담기)
CREATE TABLE IF NOT EXISTS hsb_library (
  user_id     VARCHAR(32) NOT NULL,
  book_id     VARCHAR(64) NOT NULL,
  created_at  DATETIME    NOT NULL,
  PRIMARY KEY (user_id, book_id),
  CONSTRAINT fk_library_user FOREIGN KEY (user_id) REFERENCES hsb_users(id) ON DELETE CASCADE,
  CONSTRAINT fk_library_book FOREIGN KEY (book_id) REFERENCES hsb_books(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 페이지 단위 필기. rev 는 서버가 단조 증가시키는 낙관적 동시성 토큰
CREATE TABLE IF NOT EXISTS hsb_ink_pages (
  user_id     VARCHAR(32) NOT NULL,
  book_id     VARCHAR(64) NOT NULL,
  page_id     VARCHAR(80) NOT NULL,
  rev         INT         NOT NULL,
  checksum    VARCHAR(32) NOT NULL,
  data        LONGTEXT    NOT NULL,
  device_id   VARCHAR(36) NOT NULL,
  updated_at  DATETIME    NOT NULL,
  PRIMARY KEY (user_id, page_id),
  KEY idx_ink_user_book (user_id, book_id, updated_at),
  CONSTRAINT fk_ink_user FOREIGN KEY (user_id) REFERENCES hsb_users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hsb_quiz_attempts (
  id          BIGINT      NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id     VARCHAR(32) NOT NULL,
  quiz_id     VARCHAR(80) NOT NULL,
  chosen      INT         NOT NULL,
  correct     TINYINT(1)  NOT NULL,
  created_at  DATETIME    NOT NULL,
  KEY idx_attempts_user_quiz (user_id, quiz_id),
  CONSTRAINT fk_attempts_user FOREIGN KEY (user_id) REFERENCES hsb_users(id) ON DELETE CASCADE,
  CONSTRAINT fk_attempts_quiz FOREIGN KEY (quiz_id) REFERENCES hsb_quizzes(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

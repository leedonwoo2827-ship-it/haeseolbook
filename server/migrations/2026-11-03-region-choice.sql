-- 보기 칸(kind='choice') — 원문 위 ①②③④ 자리를 펜·손가락으로 한 번 누르면 그 보기로 채점.
-- `php bin/hsb.php migrate` 가 자동으로 더하므로, 운영 DB 에 손으로 적용할 때만 쓴다.
ALTER TABLE hsb_regions ADD COLUMN choice_no INT NULL;

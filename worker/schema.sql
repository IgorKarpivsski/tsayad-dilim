CREATE TABLE IF NOT EXISTS clicks (
  day TEXT NOT NULL,
  post_id INTEGER NOT NULL,
  product_id TEXT NOT NULL,
  source TEXT NOT NULL,
  variant TEXT,
  n INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, post_id, source)
);

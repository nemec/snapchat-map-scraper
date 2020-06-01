CREATE TABLE "media" (
	"id"	TEXT NOT NULL,
	"location_id"	INTEGER NOT NULL,
	"duration_seconds"	REAL,
	"timestamp"	TEXT,
	"title"	INTEGER,
	"overlay_text"	TEXT,
	"preview_path"	TEXT,
	"media_path"	TEXT,
	"overlay_path"	TEXT,
	"reviewed"	INTEGER NOT NULL DEFAULT 0,
	"classification"	TEXT,
	"insert_date"	TEXT DEFAULT CURRENT_TIMESTAMP,
	PRIMARY KEY("id"),
	FOREIGN KEY("location_id") REFERENCES "locations"("id")
);
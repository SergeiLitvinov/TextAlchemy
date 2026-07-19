import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import Column, Integer, String, Text, create_engine
from sqlalchemy.orm import Session, declarative_base

from textalchemy.core.types import BibItem
from textalchemy.organize.bibliography import BibliographyParser

Base = declarative_base()


class BibRecord(Base):  # type: ignore[valid-type,misc]
    __tablename__ = "bibliography"

    id = Column(Integer, primary_key=True, autoincrement=True)
    authors = Column(Text, default="[]")
    title = Column(String(500), default="")
    year = Column(Integer, nullable=True)
    doc_type = Column(String(50), default="unknown")
    source = Column(String(500), default="")
    pages = Column(String(100), default="")
    doi = Column(String(200), default="")
    isbn = Column(String(100), default="")
    url = Column(String(500), default="")
    journal = Column(String(300), default="")
    publisher = Column(String(300), default="")
    city = Column(String(200), default="")
    raw_text = Column(Text, default="")
    created_at = Column(String(30), default=lambda: datetime.now().isoformat())
    updated_at = Column(String(30), default=lambda: datetime.now().isoformat())

    def to_bibitem(self) -> BibItem:
        raw = self.raw_text or ""
        authors = json.loads(str(self.authors)) if self.authors else []
        return BibItem(
            index=int(self.id),  # type: ignore[arg-type]
            raw_text=str(raw),
            authors=authors,
            title=str(self.title or ""),
            year=self.year,  # type: ignore[arg-type]
            doc_type=str(self.doc_type or "unknown"),
            source=str(self.source or ""),
            pages=str(self.pages or ""),
            doi=str(self.doi or ""),
            isbn=str(self.isbn or ""),
            url=str(self.url or ""),
            journal=str(self.journal or ""),
            publisher=str(self.publisher or ""),
            city=str(self.city or ""),
        )

    @classmethod
    def from_bibitem(cls, item: BibItem, record_id: Optional[int] = None) -> "BibRecord":
        return cls(
            id=record_id if record_id is not None else (item.index if item.index else None),
            authors=json.dumps(item.authors, ensure_ascii=False),
            title=item.title,
            year=item.year,
            doc_type=item.doc_type,
            source=item.source,
            pages=item.pages,
            doi=item.doi,
            isbn=item.isbn,
            url=item.url or "",
            journal=item.journal or "",
            publisher=item.publisher or "",
            city=item.city or "",
            raw_text=item.raw_text,
        )


class Database:
    def __init__(self, db_path: str | Path = ".textalchemy/library.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{self.db_path}")
        Base.metadata.create_all(self.engine)

    def session(self) -> Session:
        return Session(self.engine)

    def import_from_file(self, path: str | Path) -> int:
        """Импорт из текстового файла библиографии (не JSON)."""
        items = BibliographyParser.parse_file(str(path))
        count = 0
        with self.session() as sess:
            for item in items:
                rec = BibRecord.from_bibitem(item)
                sess.add(rec)
                count += 1
            sess.commit()
        return count

    def all_items(self) -> list[BibItem]:
        with self.session() as sess:
            records = sess.query(BibRecord).order_by(BibRecord.id).all()
        return [r.to_bibitem() for r in records]

    def add_item(self, item: BibItem) -> BibItem:
        rec = BibRecord.from_bibitem(item)
        with self.session() as sess:
            sess.add(rec)
            sess.flush()
            item.index = int(rec.id)  # type: ignore[arg-type]
            sess.commit()
        return item

    def update_item(self, item_id: int, item: BibItem) -> bool:
        with self.session() as sess:
            rec = sess.query(BibRecord).filter_by(id=item_id).first()
            if not rec:
                return False
            rec.authors = json.dumps(item.authors, ensure_ascii=False)  # type: ignore[assignment]
            rec.title = item.title  # type: ignore[assignment]
            rec.year = item.year  # type: ignore[assignment]
            rec.doc_type = item.doc_type  # type: ignore[assignment]
            rec.source = item.source  # type: ignore[assignment]
            rec.pages = item.pages  # type: ignore[assignment]
            rec.doi = item.doi  # type: ignore[assignment]
            rec.isbn = item.isbn  # type: ignore[assignment]
            rec.url = item.url or ""  # type: ignore[assignment]
            rec.journal = item.journal or ""  # type: ignore[assignment]
            rec.publisher = item.publisher or ""  # type: ignore[assignment]
            rec.city = item.city or ""  # type: ignore[assignment]
            rec.raw_text = item.raw_text  # type: ignore[assignment]
            rec.updated_at = datetime.now().isoformat()  # type: ignore[assignment]
            sess.commit()
        return True

    def delete_item(self, item_id: int) -> bool:
        with self.session() as sess:
            rec = sess.query(BibRecord).filter_by(id=item_id).first()
            if not rec:
                return False
            sess.delete(rec)
            sess.commit()
        return True

    def get_item(self, item_id: int) -> Optional[BibItem]:
        with self.session() as sess:
            rec = sess.query(BibRecord).filter_by(id=item_id).first()
        return rec.to_bibitem() if rec else None

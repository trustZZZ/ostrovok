"""
SQLAlchemy модели базы данных.
PostgreSQL + PostGIS + pgvector
"""
from sqlalchemy import Column, Integer, BigInteger, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship, DeclarativeBase
from geoalchemy2 import Geometry

class Base(DeclarativeBase):
    pass

class Hotel(Base):
    __tablename__ = "hotels"
    
    id = Column(Integer, primary_key=True)
    osm_id = Column(BigInteger, unique=True, index=True)
    name = Column(String, nullable=False)
    address = Column(String)
    geom = Column(Geometry("POINT", srid=4326), nullable=False)
    floors = Column(Integer, default=3)
    facade_azimuth = Column(Float)  # азимут главного фасада, градусы от севера
    created_at = Column(DateTime, server_default="now()")
    
    features = relationship("HotelFeature", back_populates="hotel", cascade="all, delete-orphan")
    questions = relationship("HotelierQuestion", back_populates="hotel", cascade="all, delete-orphan")

class HotelFeature(Base):
    __tablename__ = "hotel_features"
    
    id = Column(Integer, primary_key=True)
    hotel_id = Column(Integer, ForeignKey("hotels.id", ondelete="CASCADE"), index=True)
    feature_key = Column(String, nullable=False, index=True)  # "sunset_view", "noise_score"
    value = Column(JSONB, nullable=False)
    source = Column(String, nullable=False)  # "SRTM+OSM", "Wikidata", "hotelier", "Open-Meteo"
    confidence = Column(Float, nullable=False)  # 0.0 – 1.0
    computed_at = Column(DateTime, server_default="now()")
    expires_at = Column(DateTime)
    raw_evidence = Column(JSONB)  # логи вычислений для объяснимости
    
    hotel = relationship("Hotel", back_populates="features")

class HotelierQuestion(Base):
    __tablename__ = "hotelier_questions"
    
    id = Column(Integer, primary_key=True)
    hotel_id = Column(Integer, ForeignKey("hotels.id", ondelete="CASCADE"), index=True)
    feature_key = Column(String, nullable=False)
    question = Column(Text, nullable=False)
    answer_raw = Column(Text)
    answer_parsed = Column(JSONB)
    status = Column(String, default="pending")  # pending | answered | disputed
    asked_at = Column(DateTime, server_default="now()")
    answered_at = Column(DateTime)
    
    hotel = relationship("Hotel", back_populates="questions")

class Route(Base):
    __tablename__ = "routes"
    
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    author = Column(String)
    description = Column(Text)
    points = Column(JSONB)  # [{geom, title, why, time}]
    hotel_ids = Column(JSONB)  # [int, ...]
